"""
edge/turn_detection/detector.py — Streaming turn-end / endpointing detection (Phase 4A/4B)
==========================================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 4A "speech start/end markers" + Phase 4B
"turn-state machine" guards).

Streaming endpointing: decides *when a user's turn has ended* from a live frame stream,
without ever waiting for a full-utterance transcript. The detector is **VAD-driven** and
emits, per frame, an :class:`EndpointDecision` with explicit speech start / speech end /
turn-end-candidate / turn-end-confirmed markers and the timing needed to drive the
:class:`edge.session.turn_state.TurnStateMachine`:

    speech_started   → machine: idle/buffering → listening
    speech_ended     → machine: listening → buffering   (provisional end-of-turn)
    turn_end_candidate (short silence)  → still buffering, may resume
    turn_end_confirmed (silence ≥ hangover) → machine: buffering → candidate_filler

CPU/no-weights rule (DECISIONS.md D-008):
* The VAD is the lazy Silero-or-energy-fallback :class:`VADProvider` from
  ``edge/turn_detection/features.py`` — Silero is imported lazily inside the provider and
  an energy + zero-crossing heuristic is the deterministic CPU fallback.
* Everything here is pure Python and deterministic given the VAD output, so the
  endpointing behavior is fully testable on synthetic audio with no model weights.

The detector is *streaming*: :meth:`process_frame` returns immediately for each frame and
:meth:`stream` is a generator, so it never blocks on a whole utterance.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from edge.session.logging_hooks import get_logger
from edge.turn_detection.features import VADProvider

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Per-frame endpointing decision
# ---------------------------------------------------------------------------
@dataclass
class EndpointDecision:
    """Per-frame endpointing decision emitted by :class:`EndpointingDetector`.

    The boolean *edge* flags fire on the frame where the edge occurs (they are not
    sticky), so a consumer can map them 1:1 onto turn-state transitions.
    """

    session_id: str
    seq: int
    ts_ms: int
    speech_probability: float
    is_speech: bool                     # debounced "currently in speech" state.
    speech_started: bool = False        # rising edge this frame.
    speech_ended: bool = False          # falling edge (provisional end-of-turn) this frame.
    turn_end_candidate: bool = False    # silence has begun after speech (may still resume).
    turn_end_confirmed: bool = False    # silence held ≥ hangover → turn is over.
    silence_ms: int = 0                 # contiguous trailing silence after speech.
    speech_ms: int = 0                  # contiguous speech in the current run.

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "speech_probability": round(self.speech_probability, 4),
            "is_speech": self.is_speech,
            "speech_started": self.speech_started,
            "speech_ended": self.speech_ended,
            "turn_end_candidate": self.turn_end_candidate,
            "turn_end_confirmed": self.turn_end_confirmed,
            "silence_ms": self.silence_ms,
            "speech_ms": self.speech_ms,
        }


# ---------------------------------------------------------------------------
# Streaming endpointing detector
# ---------------------------------------------------------------------------
class EndpointingDetector:
    """Streaming turn-end detector driven by a VAD probability stream.

    The detector debounces noisy VAD with two hysteresis windows and a hangover:

    * **speech onset** fires after ``start_frames`` consecutive speech frames,
    * **speech offset** (provisional end-of-turn) fires after ``end_frames`` consecutive
      silence frames following speech,
    * a **turn-end candidate** is raised as soon as trailing silence begins (so the
      session can pre-warm a filler), and
    * a **turn-end confirmation** fires once trailing silence reaches ``hangover_ms``
      (the endpointing decision the state machine acts on).

    Args:
        session_id: Owning session (for structured logs / events).
        sample_rate: Audio sample rate in Hz.
        frame_ms: Nominal duration of one frame in ms (used to convert ms → frames and
            to accumulate silence/speech durations).
        speech_threshold: VAD probability at/above which a frame counts as speech.
        start_frames: Consecutive speech frames required to declare speech onset.
        end_frames: Consecutive silence frames required to declare a provisional offset.
        hangover_ms: Trailing-silence duration required to *confirm* the turn end.
        min_speech_ms: Minimum cumulative speech before an offset/turn-end is allowed
            (suppresses turn-ends from a single cough/blip).
        vad: Optional :class:`VADProvider` (defaults to a lazy Silero/energy provider).
    """

    def __init__(
        self,
        session_id: str,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        speech_threshold: float = 0.5,
        start_frames: int = 2,
        end_frames: int = 3,
        hangover_ms: int = 600,
        min_speech_ms: int = 180,
        vad: VADProvider | None = None,
    ) -> None:
        self._session_id = session_id
        self._sample_rate = sample_rate
        self._frame_ms = max(1, frame_ms)
        self._threshold = speech_threshold
        self._start_frames = max(1, start_frames)
        self._end_frames = max(1, end_frames)
        self._hangover_ms = max(0, hangover_ms)
        self._min_speech_ms = max(0, min_speech_ms)
        self._vad = vad or VADProvider()

        # Streaming state.
        self._seq = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._silence_ms = 0
        self._speech_ms = 0
        self._had_speech = False          # any qualifying speech seen since last turn end.
        self._candidate_emitted = False   # turn_end_candidate already raised for this tail.
        self._confirmed = False           # turn_end_confirmed already raised for this tail.

    # --- read-only state -----------------------------------------------------
    @property
    def in_speech(self) -> bool:
        """Whether the detector currently considers the user to be speaking."""
        return self._in_speech

    @property
    def using_fallback(self) -> bool:
        """True when the underlying VAD is the deterministic energy fallback."""
        return self._vad.using_fallback

    @property
    def trailing_silence_ms(self) -> int:
        """Contiguous trailing silence (ms) accumulated since the last speech frame."""
        return self._silence_ms

    def reset(self) -> None:
        """Reset streaming state for a new turn/session (keeps any loaded VAD model)."""
        self._seq = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._silence_ms = 0
        self._speech_ms = 0
        self._had_speech = False
        self._candidate_emitted = False
        self._confirmed = False

    # --- core streaming API --------------------------------------------------
    def process_frame(self, samples: Sequence[float], ts_ms: int) -> EndpointDecision:
        """Process one audio frame and return its endpointing decision immediately.

        Args:
            samples: Float32 mono samples for this frame (a short streaming window).
            ts_ms: Frame timestamp in milliseconds.

        Returns:
            The per-frame :class:`EndpointDecision` with edge markers for this frame.
        """
        prob = self._vad.speech_probability(samples, self._sample_rate)
        return self._advance(prob, ts_ms)

    def process_probability(self, speech_probability: float, ts_ms: int) -> EndpointDecision:
        """Advance the detector from a precomputed VAD probability (no audio needed).

        Useful when VAD has already been run elsewhere (e.g. shared with the feature
        extractor) so the same probability stream drives both without recomputation.
        """
        return self._advance(speech_probability, ts_ms)

    def _advance(self, speech_probability: float, ts_ms: int) -> EndpointDecision:
        seq = self._seq
        self._seq += 1

        prob = max(0.0, min(1.0, speech_probability))
        is_speech_frame = prob >= self._threshold

        started = False
        ended = False
        candidate = False
        confirmed = False

        if is_speech_frame:
            self._speech_run += 1
            self._silence_run = 0
            self._silence_ms = 0
            self._speech_ms += self._frame_ms
            # A new speech tail invalidates any pending end markers.
            self._candidate_emitted = False
            self._confirmed = False
            if not self._in_speech and self._speech_run >= self._start_frames:
                self._in_speech = True
                started = True
                if self._speech_ms >= self._min_speech_ms:
                    self._had_speech = True
                logger.debug(
                    "endpoint_speech_started",
                    session_id=self._session_id,
                    seq=seq,
                    ts_ms=ts_ms,
                )
            elif self._in_speech and self._speech_ms >= self._min_speech_ms:
                self._had_speech = True
        else:
            self._silence_run += 1
            self._speech_run = 0
            self._silence_ms += self._frame_ms

            # Provisional offset: speech → silence confirmed after end_frames.
            if self._in_speech and self._silence_run >= self._end_frames:
                self._in_speech = False
                self._speech_ms = 0
                if self._had_speech:
                    ended = True
                    logger.debug(
                        "endpoint_speech_ended",
                        session_id=self._session_id,
                        seq=seq,
                        ts_ms=ts_ms,
                        silence_ms=self._silence_ms,
                    )

            # Turn-end candidate: trailing silence has begun after real speech.
            if (
                self._had_speech
                and not self._in_speech
                and not self._candidate_emitted
                and self._silence_ms > 0
            ):
                candidate = True
                self._candidate_emitted = True
                logger.debug(
                    "endpoint_turn_end_candidate",
                    session_id=self._session_id,
                    seq=seq,
                    silence_ms=self._silence_ms,
                )

            # Turn-end confirmation: trailing silence held for the full hangover.
            if (
                self._had_speech
                and not self._in_speech
                and not self._confirmed
                and self._silence_ms >= self._hangover_ms
            ):
                confirmed = True
                self._confirmed = True
                logger.info(
                    "endpoint_turn_end_confirmed",
                    session_id=self._session_id,
                    seq=seq,
                    ts_ms=ts_ms,
                    silence_ms=self._silence_ms,
                )
                # Tail consumed: require fresh speech before the next turn end.
                self._had_speech = False

        return EndpointDecision(
            session_id=self._session_id,
            seq=seq,
            ts_ms=ts_ms,
            speech_probability=prob,
            is_speech=self._in_speech,
            speech_started=started,
            speech_ended=ended,
            turn_end_candidate=candidate,
            turn_end_confirmed=confirmed,
            silence_ms=self._silence_ms,
            speech_ms=self._speech_ms,
        )

    def stream(
        self,
        frames: Iterable[tuple[Sequence[float], int]],
    ) -> Iterator[EndpointDecision]:
        """Lazily map ``(samples, ts_ms)`` frames to :class:`EndpointDecision` records.

        A generator: one decision is yielded per input frame as soon as it is processed,
        proving the endpointer never buffers a whole utterance before emitting output.
        """
        for samples, ts_ms in frames:
            yield self.process_frame(samples, ts_ms)
