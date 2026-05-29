"""
SoulYatri Speech — Barge-in Detection
========================================
Detects when the user interrupts the AI while it's speaking,
triggering audio output suppression and turn recovery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from ..utils.logging_config import get_logger
from ..utils.metrics import barge_in_total

logger = get_logger(__name__)


@dataclass
class BargeInEvent:
    """Represents a detected barge-in event."""

    session_id: str
    timestamp: float
    agent_was_speaking: bool     # Was the agent actively playing audio?
    speech_probability: float    # VAD probability of the interrupting speech
    time_since_agent_started: float  # How long was the agent speaking before barge-in?


class BargeInDetector:
    """Detects barge-in events — user speaking over the AI.

    Works by checking if the user's speech is detected (via VAD)
    while the turn state machine indicates the agent is speaking.

    The detector uses hysteresis to avoid false triggers from
    brief noise or echo leakage.
    """

    def __init__(
        self,
        min_speech_duration_ms: int = 200,
        cooldown_ms: int = 500,
    ) -> None:
        """
        Args:
            min_speech_duration_ms: Minimum user speech duration to trigger barge-in.
            cooldown_ms: Minimum time between barge-in events.
        """
        self._min_speech_frames = max(1, min_speech_duration_ms // 30)
        self._cooldown_seconds = cooldown_ms / 1000.0
        self._speech_frame_count = 0
        self._last_barge_in_time = 0.0
        self._agent_speaking_since: Optional[float] = None

    def set_agent_speaking(self, is_speaking: bool) -> None:
        """Update whether the agent is currently playing audio.

        Args:
            is_speaking: True if agent is outputting audio.
        """
        if is_speaking and self._agent_speaking_since is None:
            self._agent_speaking_since = time.time()
        elif not is_speaking:
            self._agent_speaking_since = None
            self._speech_frame_count = 0

    def check_barge_in(
        self,
        session_id: str,
        speech_probability: float,
        threshold: float = 0.5,
    ) -> Optional[BargeInEvent]:
        """Check if the current audio frame constitutes a barge-in.

        Should be called for every VAD frame while the agent is speaking.

        Args:
            session_id: Session identifier.
            speech_probability: VAD speech probability for this frame.
            threshold: Speech probability threshold.

        Returns:
            BargeInEvent if barge-in detected, None otherwise.
        """
        # Not a barge-in if agent isn't speaking
        if self._agent_speaking_since is None:
            self._speech_frame_count = 0
            return None

        # Check cooldown
        now = time.time()
        if now - self._last_barge_in_time < self._cooldown_seconds:
            return None

        # Track consecutive speech frames
        if speech_probability >= threshold:
            self._speech_frame_count += 1
        else:
            # Reset on silence (non-consecutive speech doesn't count)
            self._speech_frame_count = max(0, self._speech_frame_count - 1)

        # Trigger barge-in only after enough consecutive speech frames
        if self._speech_frame_count >= self._min_speech_frames:
            time_since_start = now - self._agent_speaking_since

            event = BargeInEvent(
                session_id=session_id,
                timestamp=now,
                agent_was_speaking=True,
                speech_probability=speech_probability,
                time_since_agent_started=round(time_since_start, 3),
            )

            barge_in_total.inc()
            self._last_barge_in_time = now
            self._speech_frame_count = 0

            logger.info(
                "barge_in_detected",
                session_id=session_id,
                time_since_agent_started=event.time_since_agent_started,
                speech_prob=round(speech_probability, 3),
            )

            return event

        return None

    def reset(self) -> None:
        """Reset the detector state."""
        self._speech_frame_count = 0
        self._agent_speaking_since = None
        self._last_barge_in_time = 0.0
