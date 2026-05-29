"""
SoulYatri Speech — Turn Management State Machine
====================================================
Explicit state machine for session turn management.
Replaces ad-hoc if-statements with defined transitions,
guards, timeouts, and cancellation behavior.

States:
    IDLE → LISTENING → BUFFERING → CANDIDATE_FILLER → FORWARDING →
    THINKING → SPEAKING → IDLE
    (with BARGE_IN and REPAIRING as interrupt states)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any

from ..utils.logging_config import get_logger
from ..utils.metrics import turn_state_transitions

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Turn states
# ---------------------------------------------------------------------------
class TurnState(Enum):
    """All possible states in the turn lifecycle."""

    IDLE = "idle"                     # Waiting for user to speak
    LISTENING = "listening"           # User is speaking
    BUFFERING = "buffering"          # VAD detected silence, buffering for turn-end
    CANDIDATE_FILLER = "candidate_filler"  # Checking if filler can handle this
    FORWARDING = "forwarding"        # Sending to full pipeline
    THINKING = "thinking"            # Pipeline is processing (STT→LLM→TTS)
    SPEAKING = "speaking"            # Agent is playing audio response
    BARGE_IN = "barge_in"            # User interrupted while agent was speaking
    REPAIRING = "repairing"          # Recovering from barge-in
    ENDED = "ended"                  # Session has ended


# ---------------------------------------------------------------------------
# Transition definitions
# ---------------------------------------------------------------------------
# Map of (current_state) → set of valid next states
VALID_TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.IDLE: {TurnState.LISTENING, TurnState.ENDED},
    TurnState.LISTENING: {TurnState.BUFFERING, TurnState.IDLE, TurnState.ENDED},
    TurnState.BUFFERING: {
        TurnState.LISTENING,       # More speech detected (false end)
        TurnState.CANDIDATE_FILLER,  # Silence confirmed → check filler
        TurnState.IDLE,
        TurnState.ENDED,
    },
    TurnState.CANDIDATE_FILLER: {
        TurnState.IDLE,            # Filler-only handled the turn
        TurnState.FORWARDING,      # Need full pipeline
        TurnState.ENDED,
    },
    TurnState.FORWARDING: {
        TurnState.THINKING,        # Pipeline started processing
        TurnState.IDLE,
        TurnState.ENDED,
    },
    TurnState.THINKING: {
        TurnState.SPEAKING,        # Response ready
        TurnState.IDLE,            # Empty response / error → go idle
        TurnState.BARGE_IN,        # User interrupted while processing
        TurnState.ENDED,
    },
    TurnState.SPEAKING: {
        TurnState.IDLE,            # Finished speaking
        TurnState.BARGE_IN,        # User interrupted
        TurnState.ENDED,
    },
    TurnState.BARGE_IN: {
        TurnState.REPAIRING,       # Handle the interruption
        TurnState.LISTENING,       # Start listening to the new utterance
        TurnState.ENDED,
    },
    TurnState.REPAIRING: {
        TurnState.LISTENING,       # Recovered, listening again
        TurnState.IDLE,            # Gave up, go idle
        TurnState.ENDED,
    },
    TurnState.ENDED: set(),        # Terminal state
}


# ---------------------------------------------------------------------------
# State timeouts (seconds)
# ---------------------------------------------------------------------------
STATE_TIMEOUTS: dict[TurnState, float] = {
    TurnState.LISTENING: 30.0,      # Max listen time before forcing end
    TurnState.BUFFERING: 2.0,       # Max buffer time before confirming turn-end
    TurnState.CANDIDATE_FILLER: 1.0,  # Max time to decide filler vs pipeline
    TurnState.FORWARDING: 1.0,      # Max time to start pipeline
    TurnState.THINKING: 15.0,       # Max pipeline processing time
    TurnState.SPEAKING: 60.0,       # Max speaking time
    TurnState.BARGE_IN: 2.0,        # Max time to handle barge-in
    TurnState.REPAIRING: 3.0,       # Max repair time
}


# ---------------------------------------------------------------------------
# State event
# ---------------------------------------------------------------------------
@dataclass
class TurnEvent:
    """An event emitted on state transitions."""

    session_id: str
    from_state: TurnState
    to_state: TurnState
    trigger: str          # What caused the transition
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Turn state machine
# ---------------------------------------------------------------------------
class TurnStateMachine:
    """Explicit state machine for a single session's turn lifecycle.

    Each session gets its own state machine instance. The machine
    enforces valid transitions and emits events for logging/metrics.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._state = TurnState.IDLE
        self._previous_state: Optional[TurnState] = None
        self._state_entered_at: float = time.time()
        self._turn_id: int = 0
        self._event_history: list[TurnEvent] = []
        self._on_transition: Optional[Callable[[TurnEvent], Any]] = None

        # Timeout handling
        self._timeout_task: Optional[asyncio.Task] = None

        logger.info(
            "turn_machine_created",
            session_id=session_id,
            initial_state=self._state.value,
        )

    @property
    def state(self) -> TurnState:
        """Current turn state."""
        return self._state

    @property
    def previous_state(self) -> Optional[TurnState]:
        """The state before the current one."""
        return self._previous_state

    @property
    def turn_id(self) -> int:
        """Current turn number in this session."""
        return self._turn_id

    @property
    def time_in_state(self) -> float:
        """Seconds spent in the current state."""
        return time.time() - self._state_entered_at

    @property
    def is_user_speaking(self) -> bool:
        """Whether the user is currently speaking."""
        return self._state in (TurnState.LISTENING, TurnState.BUFFERING)

    @property
    def is_agent_speaking(self) -> bool:
        """Whether the agent is currently playing audio."""
        return self._state == TurnState.SPEAKING

    @property
    def is_processing(self) -> bool:
        """Whether the pipeline is processing."""
        return self._state in (
            TurnState.CANDIDATE_FILLER,
            TurnState.FORWARDING,
            TurnState.THINKING,
        )

    def set_transition_callback(
        self, callback: Callable[[TurnEvent], Any]
    ) -> None:
        """Set a callback invoked on every state transition.

        Args:
            callback: Function receiving a TurnEvent.
        """
        self._on_transition = callback

    def can_transition(self, to_state: TurnState) -> bool:
        """Check if a transition to the given state is valid.

        Args:
            to_state: Target state.

        Returns:
            True if the transition is allowed.
        """
        valid = VALID_TRANSITIONS.get(self._state, set())
        return to_state in valid

    def transition(
        self,
        to_state: TurnState,
        trigger: str = "manual",
        metadata: Optional[dict] = None,
    ) -> TurnEvent:
        """Transition to a new state.

        Args:
            to_state: Target state.
            trigger: What caused this transition (for logging).
            metadata: Optional extra data for the event.

        Returns:
            The TurnEvent for this transition.

        Raises:
            ValueError: If the transition is not valid.
        """
        if not self.can_transition(to_state):
            raise ValueError(
                f"Invalid transition: {self._state.value} → {to_state.value} "
                f"(trigger={trigger}, session={self._session_id})"
            )

        event = TurnEvent(
            session_id=self._session_id,
            from_state=self._state,
            to_state=to_state,
            trigger=trigger,
            metadata=metadata or {},
        )

        # Increment turn counter on new listening phase
        if to_state == TurnState.LISTENING and self._state == TurnState.IDLE:
            self._turn_id += 1

        # Update state
        self._previous_state = self._state
        self._state = to_state
        self._state_entered_at = time.time()

        # Record history
        self._event_history.append(event)

        # Metrics
        turn_state_transitions.labels(
            from_state=event.from_state.value,
            to_state=event.to_state.value,
        ).inc()

        logger.info(
            "turn_transition",
            session_id=self._session_id,
            from_state=event.from_state.value,
            to_state=event.to_state.value,
            trigger=trigger,
            turn_id=self._turn_id,
            time_in_prev_state=round(
                event.timestamp - (self._event_history[-2].timestamp if len(self._event_history) > 1 else event.timestamp),
                3,
            ),
        )

        # Fire callback
        if self._on_transition:
            try:
                self._on_transition(event)
            except Exception as e:
                logger.error("transition_callback_error", error=str(e))

        # Cancel any existing timeout
        self._cancel_timeout()

        # Start a timeout monitor for states that need fail-safe recovery
        timeout_seconds = STATE_TIMEOUTS.get(to_state)
        if timeout_seconds:
            self._start_timeout_monitor(to_state, timeout_seconds)

        return event

    def try_transition(
        self,
        to_state: TurnState,
        trigger: str = "manual",
        metadata: Optional[dict] = None,
    ) -> Optional[TurnEvent]:
        """Try to transition; return None if invalid instead of raising.

        Args:
            to_state: Target state.
            trigger: Trigger description.
            metadata: Optional metadata.

        Returns:
            TurnEvent if successful, None if transition is invalid.
        """
        if not self.can_transition(to_state):
            logger.debug(
                "transition_blocked",
                session_id=self._session_id,
                from_state=self._state.value,
                to_state=to_state.value,
                trigger=trigger,
            )
            return None

        return self.transition(to_state, trigger, metadata)

    # --- Convenience transition methods ---

    def on_speech_start(self) -> Optional[TurnEvent]:
        """User started speaking."""
        if self._state == TurnState.BUFFERING:
            # False end-of-turn, they're still speaking
            return self.try_transition(TurnState.LISTENING, "speech_resume")
        if self._state == TurnState.SPEAKING:
            # Barge-in!
            return self.try_transition(TurnState.BARGE_IN, "barge_in")
        return self.try_transition(TurnState.LISTENING, "speech_start")

    def on_speech_end(self) -> Optional[TurnEvent]:
        """User stopped speaking (silence detected)."""
        return self.try_transition(TurnState.BUFFERING, "speech_end")

    def on_turn_confirmed(self) -> Optional[TurnEvent]:
        """Turn-end confirmed after buffering silence."""
        return self.try_transition(TurnState.CANDIDATE_FILLER, "turn_confirmed")

    def on_filler_selected(self) -> Optional[TurnEvent]:
        """Filler can handle this turn alone."""
        return self.try_transition(TurnState.IDLE, "filler_handled")

    def on_pipeline_needed(self) -> Optional[TurnEvent]:
        """Full pipeline needed for this turn."""
        return self.try_transition(TurnState.FORWARDING, "pipeline_needed")

    def on_pipeline_start(self) -> Optional[TurnEvent]:
        """Pipeline started processing."""
        return self.try_transition(TurnState.THINKING, "pipeline_start")

    def on_response_ready(self) -> Optional[TurnEvent]:
        """Pipeline produced a response, start speaking."""
        return self.try_transition(TurnState.SPEAKING, "response_ready")

    def on_speaking_done(self) -> Optional[TurnEvent]:
        """Finished playing the audio response."""
        return self.try_transition(TurnState.IDLE, "speaking_done")

    def on_barge_in_handled(self) -> Optional[TurnEvent]:
        """Barge-in has been handled, start listening to new utterance."""
        if self._state == TurnState.BARGE_IN:
            return self.try_transition(TurnState.LISTENING, "barge_in_recovery")
        return None

    def on_session_end(self) -> Optional[TurnEvent]:
        """Session is ending."""
        return self.try_transition(TurnState.ENDED, "session_end")

    def on_error(self) -> Optional[TurnEvent]:
        """Error occurred, return to idle."""
        return self.try_transition(TurnState.IDLE, "error_recovery")

    # --- Timeout management ---

    def _cancel_timeout(self) -> None:
        """Cancel any pending timeout task."""
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            self._timeout_task = None

    def _start_timeout_monitor(self, state: TurnState, timeout_seconds: float) -> None:
        """Start an async timeout monitor for the current state."""

        async def _timeout_worker(expected_state: TurnState, entered_at: float) -> None:
            try:
                await asyncio.sleep(timeout_seconds)
                if self._state != expected_state:
                    return
                if self._state_entered_at != entered_at:
                    return

                recovery_state = TurnState.LISTENING if expected_state == TurnState.BARGE_IN else TurnState.IDLE
                if self.can_transition(recovery_state):
                    logger.warning(
                        "turn_state_timeout",
                        session_id=self._session_id,
                        state=expected_state.value,
                        timeout_seconds=timeout_seconds,
                        recovery_state=recovery_state.value,
                    )
                    self._timeout_task = None
                    self.transition(recovery_state, trigger="timeout")
            except asyncio.CancelledError:
                return

        try:
            self._timeout_task = asyncio.create_task(
                _timeout_worker(state, self._state_entered_at)
            )
        except RuntimeError:
            # No running event loop available; timeout monitoring is best-effort.
            self._timeout_task = None

    def get_recent_events(self, count: int = 10) -> list[TurnEvent]:
        """Get the most recent state transition events.

        Args:
            count: Number of events to return.

        Returns:
            List of recent TurnEvents.
        """
        return self._event_history[-count:]

    def reset(self) -> None:
        """Reset the state machine to IDLE."""
        self._cancel_timeout()
        self._state = TurnState.IDLE
        self._previous_state = None
        self._state_entered_at = time.time()
        logger.info(
            "turn_machine_reset",
            session_id=self._session_id,
            turn_id=self._turn_id,
        )
