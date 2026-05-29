"""
SoulYatri Speech — Emotion Extraction
========================================
Speech emotion recognition using wav2vec2-based models.
Extracts discrete emotion labels and continuous emotion vectors
(valence, arousal, dominance) from speech audio.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import torch

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import emotion_latency, errors_total

logger = get_logger(__name__)

# Emotion label mapping for the default HuggingFace SER model
EMOTION_LABELS = ["neutral", "happy", "sad", "angry", "fear", "disgust", "surprise"]


@dataclass
class EmotionResult:
    """Result from speech emotion recognition."""

    label: str                    # Dominant emotion label
    confidence: float             # Confidence of the dominant label
    valence: float               # Pleasure dimension (-1 to 1)
    arousal: float               # Activation dimension (-1 to 1)
    dominance: float             # Control dimension (-1 to 1)
    all_scores: dict[str, float]  # Scores for all labels
    processing_time: float

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "dominance": round(self.dominance, 3),
        }


# Rough VAD (valence-arousal-dominance) mappings per emotion
_EMOTION_VAD: dict[str, tuple[float, float, float]] = {
    "neutral":  (0.0,  0.0,  0.0),
    "happy":    (0.8,  0.6,  0.5),
    "sad":      (-0.6, -0.3, -0.5),
    "angry":    (-0.4,  0.8,  0.7),
    "fear":     (-0.6,  0.7, -0.6),
    "disgust":  (-0.5,  0.3,  0.3),
    "surprise": (0.2,  0.7,  0.0),
}


class EmotionExtractor:
    """Speech emotion recognition using wav2vec2.

    Loads a HuggingFace emotion classification model and extracts
    per-turn emotion features. Runs on GPU if available.
    """

    def __init__(self) -> None:
        self._model = None
        self._feature_extractor = None
        self._model_name = settings.emotion.model_name
        self._device = settings.emotion.device
        self._initialized = False

    def load_model(self) -> None:
        """Load the emotion recognition model. Call once at startup."""
        logger.info(
            "loading_emotion_model",
            model=self._model_name,
            device=self._device,
        )

        try:
            from transformers import (
                AutoModelForAudioClassification,
                AutoFeatureExtractor,
            )

            self._feature_extractor = AutoFeatureExtractor.from_pretrained(
                self._model_name
            )
            self._model = AutoModelForAudioClassification.from_pretrained(
                self._model_name
            )

            device = torch.device(self._device if torch.cuda.is_available() else "cpu")
            self._model = self._model.to(device)
            self._model.eval()

            self._initialized = True
            logger.info(
                "emotion_model_loaded",
                model=self._model_name,
                device=str(device),
            )

        except Exception as e:
            logger.error("emotion_model_load_failed", error=str(e))
            raise

    def extract(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> EmotionResult:
        """Extract emotion from an audio segment.

        Args:
            audio: Float32 audio array at the given sample rate.
            sample_rate: Sample rate of the audio.

        Returns:
            EmotionResult with label, VAD dimensions, and scores.
        """
        if not self._initialized:
            # Return neutral if model not loaded
            return EmotionResult(
                label="neutral",
                confidence=1.0,
                valence=0.0,
                arousal=0.0,
                dominance=0.0,
                all_scores={"neutral": 1.0},
                processing_time=0.0,
            )

        start = time.perf_counter()

        try:
            # Prepare input
            inputs = self._feature_extractor(
                audio,
                sampling_rate=sample_rate,
                return_tensors="pt",
                padding=True,
            )

            device = next(self._model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            # Run inference
            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits

            # Softmax to get probabilities
            probs = torch.nn.functional.softmax(logits, dim=-1)[0]
            probs_np = probs.cpu().numpy()

            # Map to emotion labels
            model_labels = list(self._model.config.id2label.values()) if hasattr(self._model.config, 'id2label') else EMOTION_LABELS

            all_scores = {}
            for i, label in enumerate(model_labels):
                if i < len(probs_np):
                    # Normalize label name
                    normalized = label.lower().strip()
                    all_scores[normalized] = float(probs_np[i])

            # Find dominant emotion
            if all_scores:
                dominant_label = max(all_scores, key=all_scores.get)
                dominant_confidence = all_scores[dominant_label]
            else:
                dominant_label = "neutral"
                dominant_confidence = 1.0

            # Compute weighted VAD values from all emotions
            valence = 0.0
            arousal = 0.0
            dominance = 0.0
            for label, score in all_scores.items():
                vad = _EMOTION_VAD.get(label, (0.0, 0.0, 0.0))
                valence += vad[0] * score
                arousal += vad[1] * score
                dominance += vad[2] * score

            processing_time = time.perf_counter() - start
            emotion_latency.observe(processing_time)

            result = EmotionResult(
                label=dominant_label,
                confidence=round(dominant_confidence, 3),
                valence=round(valence, 3),
                arousal=round(arousal, 3),
                dominance=round(dominance, 3),
                all_scores={k: round(v, 3) for k, v in all_scores.items()},
                processing_time=round(processing_time, 3),
            )

            logger.info(
                "emotion_extracted",
                label=result.label,
                confidence=result.confidence,
                valence=result.valence,
                arousal=result.arousal,
                processing_time=result.processing_time,
            )

            return result

        except Exception as e:
            processing_time = time.perf_counter() - start
            errors_total.labels(component="emotion", error_type=type(e).__name__).inc()
            logger.error("emotion_extraction_error", error=str(e))

            return EmotionResult(
                label="neutral",
                confidence=0.0,
                valence=0.0,
                arousal=0.0,
                dominance=0.0,
                all_scores={},
                processing_time=round(processing_time, 3),
            )
