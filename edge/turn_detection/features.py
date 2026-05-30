"""
edge/turn_detection/features.py — Streaming speech feature extraction (Phase 4A)
================================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 4A).

Integrates VAD + speaker embeddings + emotion vectors + timestamps + speech
start/end markers into a single **streaming** feature service. Features are emitted
per-frame as audio arrives — the service never waits for a full utterance before
producing output (acceptance test: "features stream without waiting for full
utterances").

CPU/no-weights rule (DECISIONS.md D-008):
* Silero VAD is loaded lazily; an energy + zero-crossing fallback is used otherwise.
* Speaker (ECAPA) and emotion (wav2vec2 SER) providers are the lazy ones from
  ``edge/speaker/encoder.py`` and ``edge/emotion/extractor.py``.

Everything imports and runs on a bare CPU machine. The fallbacks are deterministic so
the streaming behavior is fully testable.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from edge.emotion.extractor import EmotionExtractor
from edge.session.logging_hooks import get_logger
from edge.speaker.encoder import SpeakerEncoder
from shared.contracts import EmotionState

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Voice activity detection (lazy Silero + deterministic energy fallback)
# ---------------------------------------------------------------------------
class VADProvider:
    """Per-frame speech probability. Lazy Silero VAD with an energy-based fallback."""

    def __init__(self, *, use_fallback: bool = False, energy_threshold: float = 0.012) -> None:
        self._use_fallback = use_fallback
        self._energy_threshold = energy_threshold
        self._model = None
        self._load_attempted = False
        self._loaded = False

    @property
    def using_fallback(self) -> bool:
        return not self._loaded

    def _try_load(self) -> None:
        if self._load_attempted or self._use_fallback:
            return
        self._load_attempted = True
        try:  # pragma: no cover - requires torch + silero weights
            import torch

            model, _utils = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            self._model = model
            self._loaded = True
            logger.info("vad_model_loaded", model="silero_vad")
        except Exception as exc:  # noqa: BLE001
            self._loaded = False
            logger.warning("vad_model_unavailable_using_fallback", error=str(exc))

    def speech_probability(self, samples: Sequence[float], sample_rate: int = 16000) -> float:
        """Return a speech probability in [0, 1] for a single frame."""
        self._try_load()
        if self._loaded:
            try:  # pragma: no cover - requires real model
                import torch

                tensor = torch.tensor(list(samples), dtype=torch.float32)
                return float(self._model(tensor, sample_rate).item())  # type: ignore[operator]
            except Exception as exc:  # noqa: BLE001
                logger.error("vad_model_inference_failed", error=str(exc))
                self._loaded = False
        return self._fallback_probability(samples)

    def _fallback_probability(self, samples: Sequence[float]) -> float:
        """Energy + zero-crossing heuristic mapped to a smooth [0, 1] probability."""
        if not samples:
            return 0.0
        energy = math.sqrt(sum(s * s for s in samples) / len(samples))
        # Logistic curve centered on the energy threshold.
        x = (energy - self._energy_threshold) * 60.0
        prob = 1.0 / (1.0 + math.exp(-x))
        return max(0.0, min(1.0, prob))


# ---------------------------------------------------------------------------
# Streaming feature record
# ---------------------------------------------------------------------------
@dataclass
class SpeechFeatures:
    """Per-frame streaming feature bundle emitted by :class:`StreamingFeatureExtractor`."""

    session_id: str
    seq: int
    ts_ms: int
    is_speech: bool
    speech_probability: float
    speech_started: bool = False  # Rising edge: silence → speech this frame.
    speech_ended: bool = False    # Falling edge: speech → silence confirmed this frame.
    speaker_embedding: list[float] = field(default_factory=list)
    emotion: EmotionState | None = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "seq": self.seq,
            "ts_ms": self.ts_ms,
            "is_speech": self.is_speech,
            "speech_probability": round(self.speech_probability, 4),
            "speech_started": self.speech_started,
            "speech_ended": self.speech_ended,
            "has_speaker_embedding": bool(self.speaker_embedding),
            "emotion_label": self.emotion.label if self.emotion else None,
        }


# ---------------------------------------------------------------------------
# Streaming feature extractor
# ---------------------------------------------------------------------------
class StreamingFeatureExtractor:
    """Streams per-frame speech features as audio arrives.

    Hysteresis: speech "starts" after ``start_frames`` consecutive speech frames and
    "ends" after ``end_frames`` consecutive non-speech frames. This debounces noise and
    produces stable start/end markers without waiting for a whole utterance.

    Heavy speaker/emotion features are only computed on demand (and emotion only on a
    configurable cadence) to keep the per-frame path cheap; they remain optional so the
    VAD/marker stream is never blocked.
    """

    def __init__(
        self,
        session_id: str,
        *,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        speech_threshold: float = 0.5,
        start_frames: int = 2,
        end_frames: int = 8,
        vad: VADProvider | None = None,
        speaker: SpeakerEncoder | None = None,
        emotion: EmotionExtractor | None = None,
        compute_speaker: bool = True,
        compute_emotion: bool = True,
        emotion_every_n_frames: int = 16,
    ) -> None:
        self._session_id = session_id
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._threshold = speech_threshold
        self._start_frames = max(1, start_frames)
        self._end_frames = max(1, end_frames)

        self._vad = vad or VADProvider()
        self._speaker = speaker or SpeakerEncoder()
        self._emotion = emotion or EmotionExtractor()
        self._compute_speaker = compute_speaker
        self._compute_emotion = compute_emotion
        self._emotion_every_n = max(1, emotion_every_n_frames)

        self._seq = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._last_emotion: EmotionState | None = None

    @property
    def in_speech(self) -> bool:
        """Whether the extractor currently considers the user to be speaking."""
        return self._in_speech

    def reset(self) -> None:
        """Reset streaming state for a new session/turn (keeps loaded models)."""
        self._seq = 0
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._last_emotion = None

    def process_frame(
        self,
        samples: Sequence[float],
        ts_ms: int,
    ) -> SpeechFeatures:
        """Process one audio frame and emit its :class:`SpeechFeatures` immediately.

        Args:
            samples: Float32 mono samples for this frame.
            ts_ms: Frame timestamp in milliseconds.

        Returns:
            The per-frame feature bundle (with start/end markers as edges occur).
        """
        seq = self._seq
        self._seq += 1

        prob = self._vad.speech_probability(samples, self._sample_rate)
        is_speech_frame = prob >= self._threshold

        started = False
        ended = False

        if is_speech_frame:
            self._speech_run += 1
            self._silence_run = 0
            if not self._in_speech and self._speech_run >= self._start_frames:
                self._in_speech = True
                started = True
                logger.debug("speech_started", session_id=self._session_id, seq=seq, ts_ms=ts_ms)
        else:
            self._silence_run += 1
            self._speech_run = 0
            if self._in_speech and self._silence_run >= self._end_frames:
                self._in_speech = False
                ended = True
                logger.debug("speech_ended", session_id=self._session_id, seq=seq, ts_ms=ts_ms)

        speaker_embedding: list[float] = []
        emotion: EmotionState | None = None

        # Only compute the heavy features while there is speech, to keep the stream cheap.
        if self._in_speech or started:
            if self._compute_speaker:
                speaker_embedding = self._speaker.encode(samples, self._sample_rate)
            if self._compute_emotion and (seq % self._emotion_every_n == 0 or started):
                emotion = self._emotion.extract(samples, self._sample_rate)
                self._last_emotion = emotion
            else:
                emotion = self._last_emotion

        return SpeechFeatures(
            session_id=self._session_id,
            seq=seq,
            ts_ms=ts_ms,
            is_speech=self._in_speech,
            speech_probability=prob,
            speech_started=started,
            speech_ended=ended,
            speaker_embedding=speaker_embedding,
            emotion=emotion,
        )

    def stream(
        self,
        frames: Iterable[tuple[Sequence[float], int]],
    ) -> Iterator[SpeechFeatures]:
        """Lazily map an iterable of ``(samples, ts_ms)`` frames to feature records.

        This is a generator: it yields one :class:`SpeechFeatures` per input frame as
        soon as that frame is processed, proving the path never buffers a whole
        utterance before producing output.
        """
        for samples, ts_ms in frames:
            yield self.process_frame(samples, ts_ms)
