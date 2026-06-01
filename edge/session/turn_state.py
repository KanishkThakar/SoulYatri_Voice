"""
edge/session/turn_state.py — Explicit edge turn-state machine (Phase 4B)
========================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 4B).

An explicit, auditable state machine over the canonical
:class:`shared.contracts.TurnState` enum:

    idle → listening → buffering → candidate_filler → forwarding →
    thinking → speaking → idle      (with barge_in / repairing as interrupts)

Design rules (final_use.md Phase-4 agent prompt):
* No hidden if-else sprawl: every event either produces a **valid transition** or an
  **explicit rejection** (:class:`TransitionRejected`), recorded for audit.
* Emits a :class:`shared.contracts.TurnEvent` on every successful transition.
* Explicit guards + per-state timeouts. Timeouts are evaluated by an injectable clock
  via :meth:`check_timeout` (no event loop required → fully testable on CPU).

This mirrors ``server/pipeline/turn_state.py`` but standardizes on the shared contracts
(lowercase ``TurnState`` values, ``TurnEvent`` with ``ts_ms``) so edge events are wire
compatible with the rest of the system.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from edge.session.logging_hooks import get_logger
from shared.contracts import TurnEvent, TurnState, now_ms

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Transition table — the single source of truth (no scattered if/else)
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.idle: {TurnState.listening, TurnState.ended},
    TurnState.listening: {TurnState.buffering, TurnState.idle, TurnState.ended},
    TurnState.buffering: {
        TurnState.listening,          # false end-of-turn, speech resumed
        TurnState.candidate_filler,   # silence confirmed
        TurnState.idle,
        TurnState.ended,
    },
    TurnState.candidate_filler: {
        TurnState.idle,               # filler-only handled the turn
        TurnState.forwarding,         # full pipeline needed
        TurnState.ended,
    },
    TurnState.forwarding: {
        TurnState.thinking,
        TurnState.idle,
        TurnState.ended,
    },
    TurnState.thinking: {
        TurnState.speaking,
        TurnState.idle,               # empty response / error
        TurnState.barge_in,           # user interrupted while processing
        TurnState.ended,
    },
    TurnState.speaking: {
        TurnState.idle,               # finished speaking
        TurnState.barge_in,           # user interrupted
        TurnState.ended,
    },
    TurnState.barge_in: {
        TurnState.repairing,
        TurnState.listening,
        TurnState.ended,
    },
    TurnState.repairing: {
        TurnState.listening,
        TurnState.idle,
        TurnState.ended,
    },
    TurnState.ended: set(),           # terminal
}


# ---------------------------------------------------------------------------
# Per-state timeouts (milliseconds) and their fail-safe recovery target
# ---------------------------------------------------------------------------
STATE_TIMEOUTS_MS: dict[TurnState, int] = {
    TurnState.listening: 30_000,
    TurnState.buffering: 2_000,
    TurnState.candidate_filler: 1_000,
    TurnState.forwarding: 1_000,
    TurnState.thinking: 15_000,
    TurnState.speaking: 60_000,
    TurnState.barge_in: 2_000,
    TurnState.repairing: 3_000,
}


def _recovery_state(state: TurnState) -> TurnState:
    """Where a timed-out state should fail safe to."""
    if state == TurnState.barge_in:
        return TurnState.repairing
    if state == TurnState.repairing:
        return TurnState.idle
    return TurnState.idle


@dataclass
class TransitionRejected:
    """Explicit, auditable record of a rejected transition (never silently dropped)."""

    session_id: str
    from_state: TurnState
    attempted_state: TurnState
    trigger: str
    reason: str
    ts_ms: int = field(default_factory=now_ms)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "from_state": self.from_state.value,
            "attempted_state": self.attempted_state.value,
            "trigger": self.trigger,
            "reason": self.reason,
            "ts_ms": self.ts_ms,
        }


class InvalidTransitionError(RuntimeError):
    """Raised by :meth:`TurnStateMachine.transition` on an invalid transition."""

    def __init__(self, rejection: TransitionRejected) -> None:
        self.rejection = rejection
        super().__init__(
            f"Invalid transition {rejection.from_state.value} → "
            f"{rejection.attempted_state.value} (trigger={rejection.trigger}, "
            f"reason={rejection.reason})"
        )


Clock = Callable[[], int]


class TurnStateMachine:
    """Explicit per-session turn-state machine over the canonical ``TurnState``.

    Args:
        session_id: Owning session.
        clock: Callable returning current time in ms (injectable for deterministic
            timeout testing). Defaults to :func:`shared.contracts.now_ms`.
        on_transition: Optional callback invoked with each emitted ``TurnEvent``.
        on_rejection: Optional callback invoked with each ``TransitionRejected``.
    """

    def __init__(
        self,
        session_id: str,
        *,
        clock: Clock = now_ms,
        on_transition: Callable[[TurnEvent], None] | None = None,
        on_rejection: Callable[[TransitionRejected], None] | None = None,
    ) -> None:
        self._session_id = session_id
        self._clock = clock
        self._on_transition = on_transition
        self._on_rejection = on_rejection

        self._state = TurnState.idle
        self._previous_state: TurnState | None = None
        self._state_entered_ms = clock()
        self._turn_id = 0
        self._events: list[TurnEvent] = []
        self._rejections: list[TransitionRejected] = []

        logger.info("turn_machine_created", session_id=session_id, state=self._state.value)

    # --- read-only properties ------------------------------------------------
    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def previous_state(self) -> TurnState | None:
        return self._previous_state

    @property
    def turn_id(self) -> int:
        return self._turn_id

    @property
    def state_entered_ms(self) -> int:
        return self._state_entered_ms

    @property
    def events(self) -> list[TurnEvent]:
        return list(self._events)

    @property
    def rejections(self) -> list[TransitionRejected]:
        return list(self._rejections)

    @property
    def is_user_speaking(self) -> bool:
        return self._state in (TurnState.listening, TurnState.buffering)

    @property
    def is_agent_speaking(self) -> bool:
        return self._state == TurnState.speaking

    @property
    def is_processing(self) -> bool:
        return self._state in (
            TurnState.candidate_filler,
            TurnState.forwarding,
            TurnState.thinking,
        )

    def time_in_state_ms(self, *, now: int | None = None) -> int:
        return (now if now is not None else self._clock()) - self._state_entered_ms

    # --- core transition logic ----------------------------------------------
    def can_transition(self, to_state: TurnState) -> bool:
        """True if ``to_state`` is reachable from the current state."""
        return to_state in VALID_TRANSITIONS.get(self._state, set())

    def transition(
        self,
        to_state: TurnState,
        trigger: str = "manual",
        metadata: dict | None = None,
    ) -> TurnEvent:
        """Perform a transition, raising :class:`InvalidTransitionError` if invalid.

        On success a :class:`TurnEvent` is emitted, recorded, and returned.
        """
        if not self.can_transition(to_state):
            rejection = self._reject(to_state, trigger, "transition_not_allowed")
            raise InvalidTransitionError(rejection)

        ts = self._clock()
        event = TurnEvent(
            session_id=self._session_id,
            from_state=self._state,
            to_state=to_state,
            trigger=trigger,
            ts_ms=ts,
            metadata=metadata or {},
        )

        # New turn begins when we leave idle to start listening.
        if to_state == TurnState.listening and self._state == TurnState.idle:
            self._turn_id += 1

        self._previous_state = self._state
        self._state = to_state
        self._state_entered_ms = ts
        self._events.append(event)

        logger.info(
            "turn_transition",
            session_id=self._session_id,
            from_state=event.from_state.value,
            to_state=event.to_state.value,
            trigger=trigger,
            turn_id=self._turn_id,
        )

        if self._on_transition is not None:
            try:
                self._on_transition(event)
            except Exception as exc:  # noqa: BLE001 - callback must not break the FSM
                logger.error("transition_callback_error", error=str(exc))

        return event

    def try_transition(
        self,
        to_state: TurnState,
        trigger: str = "manual",
        metadata: dict | None = None,
    ) -> TurnEvent | TransitionRejected:
        """Like :meth:`transition` but returns a :class:`TransitionRejected` instead of
        raising. The return type makes the valid-or-explicit-rejection rule total."""
        if not self.can_transition(to_state):
            return self._reject(to_state, trigger, "transition_not_allowed")
        return self.transition(to_state, trigger, metadata)

    def _reject(self, to_state: TurnState, trigger: str, reason: str) -> TransitionRejected:
        rejection = TransitionRejected(
            session_id=self._session_id,
            from_state=self._state,
            attempted_state=to_state,
            trigger=trigger,
            reason=reason,
        )
        self._rejections.append(rejection)
        logger.warning(
            "transition_rejected",
            session_id=self._session_id,
            from_state=self._state.value,
            attempted_state=to_state.value,
            trigger=trigger,
            reason=reason,
        )
        if self._on_rejection is not None:
            try:
                self._on_rejection(rejection)
            except Exception as exc:  # noqa: BLE001
                logger.error("rejection_callback_error", error=str(exc))
        return rejection

    # --- timeouts ------------------------------------------------------------
    def timeout_ms(self) -> int | None:
        """Configured timeout for the current state, or None if unbounded."""
        return STATE_TIMEOUTS_MS.get(self._state)

    def is_timed_out(self, *, now: int | None = None) -> bool:
        """True if the current state has exceeded its configured timeout."""
        limit = self.timeout_ms()
        if limit is None:
            return False
        return self.time_in_state_ms(now=now) >= limit

    def check_timeout(self, *, now: int | None = None) -> TurnEvent | None:
        """If the current state has timed out, fail safe to its recovery state.

        Returns the emitted ``TurnEvent`` if a recovery transition fired, else None.
        Intended to be polled by the session loop (no background tasks required).
        """
        if not self.is_timed_out(now=now):
            return None
        recovery = _recovery_state(self._state)
        if not self.can_transition(recovery):
            return None
        logger.warning(
            "turn_state_timeout",
            session_id=self._session_id,
            state=self._state.value,
            recovery_state=recovery.value,
            timeout_ms=self.timeout_ms(),
        )
        return self.transition(recovery, trigger="timeout")

    # --- convenience event helpers (thin wrappers over try_transition) -------
    def on_speech_start(self) -> TurnEvent | TransitionRejected:
        """User started speaking — handles resume and barge-in cases explicitly."""
        if self._state == TurnState.buffering:
            return self.try_transition(TurnState.listening, "speech_resume")
        if self._state == TurnState.speaking:
            return self.try_transition(TurnState.barge_in, "barge_in")
        return self.try_transition(TurnState.listening, "speech_start")

    def on_speech_end(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.buffering, "speech_end")

    def on_turn_confirmed(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.candidate_filler, "turn_confirmed")

    def on_filler_handled(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.idle, "filler_handled")

    def on_pipeline_needed(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.forwarding, "pipeline_needed")

    def on_pipeline_start(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.thinking, "pipeline_start")

    def on_response_ready(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.speaking, "response_ready")

    def on_speaking_done(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.idle, "speaking_done")

    def on_barge_in(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.barge_in, "barge_in")

    def on_repair_start(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.repairing, "repair_start")

    def on_repair_done(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.listening, "repair_done")

    def on_session_end(self) -> TurnEvent | TransitionRejected:
        return self.try_transition(TurnState.ended, "session_end")

    def reset(self) -> None:
        """Reset to idle (e.g. between sessions). Keeps history for audit."""
        self._previous_state = self._state
        self._state = TurnState.idle
        self._state_entered_ms = self._clock()
        logger.info("turn_machine_reset", session_id=self._session_id, turn_id=self._turn_id)
