"""
edge/emotion/extractor.py — Streaming emotion feature provider (Phase 4A)
=========================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 4A).

Emits the canonical :class:`shared.contracts.EmotionState` (continuous affect latents,
not brittle one-word tags). A wav2vec2-class SER model (final_use.md §2.2) is loaded
**lazily** and only if torch + transformers are importable; otherwise a deterministic
signal-based fallback is used so the module imports and runs on a CPU-only machine with
no model weights (DECISIONS.md D-008).

Design goals:
* Streaming-friendly: ``extract`` works on short windows; no full-utterance blocking.
* Deterministic fallback: identical input → identical ``EmotionState`` (testable).
* Consistent label space + V/A/D mapping with ``server/pipeline/emotion.py``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from edge.session.logging_hooks import get_logger
from shared.contracts import EmotionState

logger = get_logger(__name__)

# Label space + rough valence/arousal/dominance anchors, kept consistent with
# server/pipeline/emotion.py (EMOTION_LABELS / _EMOTION_VAD).
EMOTION_LABELS: tuple[str, ...] = (
    "neutral",
    "happy",
    "sad",
    "angry",
    "fear",
    "disgust",
    "surprise",
)

_EMOTION_VAD: dict[str, tuple[float, float, float]] = {
    "neutral": (0.0, 0.0, 0.0),
    "happy": (0.8, 0.6, 0.5),
    "sad": (-0.6, -0.3, -0.5),
    "angry": (-0.4, 0.8, 0.7),
    "fear": (-0.6, 0.7, -0.6),
    "disgust": (-0.5, 0.3, 0.3),
    "surprise": (0.2, 0.7, 0.0),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _rms(samples: Sequence[float]) -> float:
    if not samples:
        return 0.0
    total = 0.0
    for s in samples:
        total += s * s
    return math.sqrt(total / len(samples))


def _zero_crossing_rate(samples: Sequence[float]) -> float:
    """Fraction of adjacent-sample sign changes (proxy for spectral brightness/pitch)."""
    if len(samples) < 2:
        return 0.0
    crossings = 0
    prev = samples[0]
    for cur in samples[1:]:
        if (cur >= 0.0) != (prev >= 0.0):
            crossings += 1
        prev = cur
    return crossings / (len(samples) - 1)


class EmotionExtractor:
    """Lazy-loaded speech-emotion feature provider with a deterministic fallback.

    The heavy SER model is never imported at construction time. The first call to
    :meth:`extract` attempts a lazy load (unless ``use_fallback=True``); any failure
    permanently flips the extractor into deterministic fallback mode and logs once.
    """

    def __init__(
        self,
        model_name: str = "superb/wav2vec2-base-superb-er",
        *,
        use_fallback: bool = False,
    ) -> None:
        self._model_name = model_name
        self._use_fallback = use_fallback
        self._model = None
        self._feature_extractor = None
        self._load_attempted = False
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        """Whether a real SER model is loaded (False means deterministic fallback)."""
        return self._loaded

    @property
    def using_fallback(self) -> bool:
        """Whether the extractor is operating in deterministic fallback mode."""
        return not self._loaded

    def _try_load(self) -> None:
        """Attempt a one-time lazy load of the SER model. Never raises."""
        if self._load_attempted or self._use_fallback:
            return
        self._load_attempted = True
        try:  # pragma: no cover - requires torch + transformers weights
            import torch  # noqa: F401
            from transformers import (
                AutoFeatureExtractor,
                AutoModelForAudioClassification,
            )

            self._feature_extractor = AutoFeatureExtractor.from_pretrained(self._model_name)
            self._model = AutoModelForAudioClassification.from_pretrained(self._model_name)
            self._model.eval()
            self._loaded = True
            logger.info("emotion_model_loaded", model=self._model_name)
        except Exception as exc:  # noqa: BLE001 - intentional broad fallback
            self._loaded = False
            logger.warning(
                "emotion_model_unavailable_using_fallback",
                model=self._model_name,
                error=str(exc),
            )

    def extract(
        self,
        samples: Sequence[float],
        sample_rate: int = 16000,
    ) -> EmotionState:
        """Extract an :class:`EmotionState` from a window of float PCM samples.

        Args:
            samples: Float32 mono samples in [-1, 1] (a short streaming window is fine).
            sample_rate: Sample rate in Hz.

        Returns:
            An :class:`EmotionState` with continuous V/A/D + persona control scalars.
        """
        self._try_load()
        if self._loaded:
            try:  # pragma: no cover - requires real model
                return self._extract_model(samples, sample_rate)
            except Exception as exc:  # noqa: BLE001
                logger.error("emotion_model_inference_failed", error=str(exc))
                self._loaded = False
        return self._extract_fallback(samples)

    def _extract_model(self, samples: Sequence[float], sample_rate: int) -> EmotionState:  # pragma: no cover
        import torch

        inputs = self._feature_extractor(  # type: ignore[misc]
            list(samples),
            sampling_rate=sample_rate,
            return_tensors="pt",
            padding=True,
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits  # type: ignore[misc]
        probs = torch.nn.functional.softmax(logits, dim=-1)[0].tolist()

        id2label = getattr(self._model.config, "id2label", None)  # type: ignore[union-attr]
        labels = (
            [v.lower().strip() for v in id2label.values()]
            if id2label
            else list(EMOTION_LABELS)
        )
        scores = {labels[i]: float(probs[i]) for i in range(min(len(labels), len(probs)))}
        return self._state_from_scores(scores)

    def _extract_fallback(self, samples: Sequence[float]) -> EmotionState:
        """Deterministic, signal-based affect estimate (no weights required).

        Uses energy (RMS) and zero-crossing rate as cheap proxies for arousal and
        spectral brightness. Mapped into the continuous latent schema. Silence maps to
        a calm-neutral state with low confidence.
        """
        rms = _rms(samples)
        zcr = _zero_crossing_rate(samples)

        # Energy → arousal/intensity; brightness (zcr) nudges valence.
        arousal = _clamp(rms * 4.0 - 0.2, -1.0, 1.0)
        valence = _clamp((zcr - 0.18) * 2.5 - rms * 0.5, -1.0, 1.0)
        dominance = _clamp(rms * 2.0 - 0.1, -1.0, 1.0)

        intensity = _clamp(rms * 3.5, 0.0, 1.0)
        # Faster speech (more zero crossings) → higher pace target.
        pace = _clamp(0.4 + (zcr - 0.18) * 1.5, 0.0, 1.0)
        # Warmth softens when arousal is high and valence is negative.
        warmth = _clamp(0.65 + valence * 0.25 - max(0.0, arousal) * 0.2, 0.0, 1.0)
        # Confidence grows with signal energy; silence is "we don't really know".
        confidence = _clamp(rms * 5.0, 0.0, 1.0)
        # Uncertainty is the complement of confidence, lightly damped.
        uncertainty = _clamp(1.0 - confidence, 0.0, 1.0) * 0.6

        label = self._nearest_label(valence, arousal, dominance)

        state = EmotionState(
            valence=round(valence, 4),
            arousal=round(arousal, 4),
            dominance=round(dominance, 4),
            warmth=round(warmth, 4),
            uncertainty=round(uncertainty, 4),
            pace=round(pace, 4),
            intensity=round(intensity, 4),
            label=label,
            confidence=round(confidence, 4),
        )
        logger.debug(
            "emotion_fallback",
            label=label,
            valence=state.valence,
            arousal=state.arousal,
            confidence=state.confidence,
        )
        return state

    def _state_from_scores(self, scores: dict[str, float]) -> EmotionState:  # pragma: no cover
        if not scores:
            return EmotionState(label="neutral", confidence=0.0, uncertainty=1.0)
        dominant = max(scores, key=lambda k: scores[k])
        valence = arousal = dominance = 0.0
        for label, score in scores.items():
            vad = _EMOTION_VAD.get(label, (0.0, 0.0, 0.0))
            valence += vad[0] * score
            arousal += vad[1] * score
            dominance += vad[2] * score
        confidence = scores[dominant]
        return EmotionState(
            valence=round(_clamp(valence, -1.0, 1.0), 4),
            arousal=round(_clamp(arousal, -1.0, 1.0), 4),
            dominance=round(_clamp(dominance, -1.0, 1.0), 4),
            warmth=round(_clamp(0.65 + valence * 0.25, 0.0, 1.0), 4),
            uncertainty=round(_clamp(1.0 - confidence, 0.0, 1.0), 4),
            pace=round(_clamp(0.4 + arousal * 0.3, 0.0, 1.0), 4),
            intensity=round(_clamp(abs(arousal), 0.0, 1.0), 4),
            label=dominant,
            confidence=round(confidence, 4),
        )

    @staticmethod
    def _nearest_label(valence: float, arousal: float, dominance: float) -> str:
        best_label = "neutral"
        best_dist = float("inf")
        for label, (lv, la, ld) in _EMOTION_VAD.items():
            dist = (lv - valence) ** 2 + (la - arousal) ** 2 + (ld - dominance) ** 2
            if dist < best_dist:
                best_dist = dist
                best_label = label
        return best_label
