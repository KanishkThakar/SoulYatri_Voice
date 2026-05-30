"""
edge/barge_in/detector.py — Interruption / barge-in detection (Phase 4C)
========================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 4C).

Detects when the user speaks over the AI ("barge-in"), generates **cancel** and
**repair** events, and records timing metrics. False positives are bounded by:

* requiring ``min_speech_frames`` *consecutive* speech frames (debounce noise/echo),
* a hysteresis decay on isolated speech frames, and
* a cooldown window between consecutive barge-in events.

This mirrors ``server/pipeline/barge_in.py`` but uses an injectable millisecond clock
(testable, no wall-clock dependence) and emits structured cancel/repair events plus a
running metrics summary so the acceptance test "interruption events fire reliably with
bounded false positives" is measurable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from edge.session.logging_hooks import get_logger

logger = get_logger(__name__)

Clock = Callable[[], int]


def _default_clock() -> int:
    import time

    return int(time.monotonic() * 1000)


@dataclass
class BargeInEvent:
    """A detected barge-in, carrying the cancel + repair signals for the runtime."""

    session_id: str
    ts_ms: int
    speech_probability: float
    time_since_agent_started_ms: int
    detection_latency_ms: int       # speech onset → confirmed barge-in.
    cancel: bool = True             # tells the speech runtime to stop output now.
    repair: bool = True             # tells the turn machine to enter repair/listen.

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "ts_ms": self.ts_ms,
            "speech_probability": round(self.speech_probability, 4),
            "time_since_agent_started_ms": self.time_since_agent_started_ms,
            "detection_latency_ms": self.detection_latency_ms,
            "cancel": self.cancel,
            "repair": self.repair,
        }


@dataclass
class BargeInMetrics:
    """Running barge-in metrics for observability + false-positive bounds."""

    frames_seen: int = 0
    speech_frames: int = 0
    detections: int = 0
    false_positive_candidates: int = 0   # detections later cancelled / withdrawn.
    detection_latencies_ms: list[int] = field(default_factory=list)

    @property
    def false_positive_rate(self) -> float:
        if self.detections == 0:
            return 0.0
        return self.false_positive_candidates / self.detections

    @property
    def mean_detection_latency_ms(self) -> float:
        if not self.detection_latencies_ms:
            return 0.0
        return sum(self.detection_latencies_ms) / len(self.detection_latencies_ms)

    def to_dict(self) -> dict:
        return {
            "frames_seen": self.frames_seen,
            "speech_frames": self.speech_frames,
            "detections": self.detections,
            "false_positive_candidates": self.false_positive_candidates,
            "false_positive_rate": round(self.false_positive_rate, 4),
            "mean_detection_latency_ms": round(self.mean_detection_latency_ms, 2),
        }


class BargeInDetector:
    """Detects barge-in (user speaking over the agent) with bounded false positives.

    Call :meth:`set_agent_speaking` when playback starts/stops, then feed every VAD
    frame to :meth:`check` while the agent is speaking. A :class:`BargeInEvent` is
    returned only when sustained user speech is confirmed.
    """

    def __init__(
        self,
        *,
        frame_ms: int = 30,
        min_speech_duration_ms: int = 200,
        cooldown_ms: int = 500,
        threshold: float = 0.5,
        clock: Clock = _default_clock,
    ) -> None:
        self._frame_ms = frame_ms
        self._min_speech_frames = max(1, min_speech_duration_ms // frame_ms)
        self._cooldown_ms = cooldown_ms
        self._threshold = threshold
        self._clock = clock

        self._agent_speaking_since_ms: int | None = None
        self._speech_run = 0
        self._speech_onset_ms: int | None = None
        self._last_detection_ms = -10**12
        self._metrics = BargeInMetrics()

    @property
    def metrics(self) -> BargeInMetrics:
        return self._metrics

    @property
    def agent_is_speaking(self) -> bool:
        return self._agent_speaking_since_ms is not None

    def set_agent_speaking(self, is_speaking: bool, *, now: int | None = None) -> None:
        """Mark whether the agent is currently playing audio.

        Barge-in can only be detected while the agent is speaking; toggling off resets
        the speech-run counters so leftover frames cannot trigger a stale detection.
        """
        ts = now if now is not None else self._clock()
        if is_speaking:
            if self._agent_speaking_since_ms is None:
                self._agent_speaking_since_ms = ts
        else:
            self._agent_speaking_since_ms = None
            self._speech_run = 0
            self._speech_onset_ms = None

    def check(
        self,
        session_id: str,
        speech_probability: float,
        *,
        now: int | None = None,
    ) -> BargeInEvent | None:
        """Evaluate one VAD frame; return a :class:`BargeInEvent` if barge-in confirmed.

        Should be called for every frame while the agent is speaking. Returns None when
        the agent is silent, during cooldown, or before sustained speech is confirmed.
        """
        ts = now if now is not None else self._clock()
        self._metrics.frames_seen += 1

        # Only meaningful while the agent is speaking.
        if self._agent_speaking_since_ms is None:
            self._speech_run = 0
            self._speech_onset_ms = None
            return None

        is_speech = speech_probability >= self._threshold
        if is_speech:
            self._metrics.speech_frames += 1
            if self._speech_run == 0:
                self._speech_onset_ms = ts
            self._speech_run += 1
        else:
            # Hysteresis: isolated speech frames decay instead of resetting hard, but a
            # full reset of the onset happens once the run collapses to zero.
            self._speech_run = max(0, self._speech_run - 1)
            if self._speech_run == 0:
                self._speech_onset_ms = None

        # Cooldown guard (do this AFTER updating run counters so state stays coherent).
        if ts - self._last_detection_ms < self._cooldown_ms:
            return None

        if self._speech_run >= self._min_speech_frames:
            onset = self._speech_onset_ms if self._speech_onset_ms is not None else ts
            event = BargeInEvent(
                session_id=session_id,
                ts_ms=ts,
                speech_probability=speech_probability,
                time_since_agent_started_ms=ts - self._agent_speaking_since_ms,
                detection_latency_ms=ts - onset,
            )
            self._last_detection_ms = ts
            self._speech_run = 0
            self._speech_onset_ms = None
            self._metrics.detections += 1
            self._metrics.detection_latencies_ms.append(event.detection_latency_ms)
            logger.info(
                "barge_in_detected",
                session_id=session_id,
                time_since_agent_started_ms=event.time_since_agent_started_ms,
                detection_latency_ms=event.detection_latency_ms,
                speech_probability=round(speech_probability, 3),
            )
            return event

        return None

    def mark_false_positive(self) -> None:
        """Record that the most recent detection turned out to be a false positive.

        The runtime calls this if a "barge-in" did not lead to a real user turn (e.g.
        the speech runtime resumed without repair). Feeds the false-positive rate so the
        bound can be asserted and tuned.
        """
        self._metrics.false_positive_candidates += 1
        logger.warning("barge_in_false_positive", count=self._metrics.false_positive_candidates)

    def reset(self) -> None:
        """Reset detector state (keeps accumulated metrics)."""
        self._agent_speaking_since_ms = None
        self._speech_run = 0
        self._speech_onset_ms = None
        self._last_detection_ms = -10**12
