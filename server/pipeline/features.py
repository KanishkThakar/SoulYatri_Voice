"""
SoulYatri Speech — Feature Extraction Orchestrator
=====================================================
Combines emotion + speaker extraction into a single per-turn
feature bundle. Runs both extractors and produces TurnMetadata.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .emotion import EmotionExtractor, EmotionResult
from .speaker import SpeakerEncoder, SpeakerEmbedding
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TurnMetadata:
    """Per-turn feature bundle combining all extracted features."""

    session_id: str
    turn_id: str
    speech_started: bool = False
    speech_ended: bool = False
    emotion: Optional[EmotionResult] = None
    speaker_embedding: Optional[SpeakerEmbedding] = None
    speaker_embedding_id: str = ""
    barge_in: bool = False
    language: str = "en"
    duration: float = 0.0
    extraction_time: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict for WebSocket transmission."""
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "speech_started": self.speech_started,
            "speech_ended": self.speech_ended,
            "emotion": self.emotion.to_dict() if self.emotion else None,
            "speaker_embedding_id": self.speaker_embedding_id,
            "barge_in": self.barge_in,
            "language": self.language,
            "duration": round(self.duration, 3),
        }


class FeatureExtractor:
    """Orchestrates emotion and speaker feature extraction per turn.

    Manages the lifecycle of both extractors and produces
    unified TurnMetadata for each speech segment.
    """

    def __init__(self) -> None:
        self._emotion = EmotionExtractor()
        self._speaker = SpeakerEncoder()
        self._initialized = False

        # Speaker embedding cache per session for tracking
        self._speaker_cache: dict[str, np.ndarray] = {}

    def load_models(self) -> None:
        """Load all feature extraction models.

        This is CPU/GPU heavy and should be called once at startup.
        Models are loaded sequentially to avoid GPU memory spikes.
        """
        logger.info("loading_feature_extraction_models")

        try:
            self._emotion.load_model()
        except Exception as e:
            logger.warning(
                "emotion_model_skipped",
                error=str(e),
                note="Emotion extraction will return neutral for all turns",
            )

        try:
            self._speaker.load_model()
        except Exception as e:
            logger.warning(
                "speaker_model_skipped",
                error=str(e),
                note="Speaker tracking will be disabled",
            )

        self._initialized = True
        logger.info("feature_extraction_models_loaded")

    def extract_features(
        self,
        session_id: str,
        turn_id: str,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str = "en",
    ) -> TurnMetadata:
        """Extract all features for a speech turn.

        Args:
            session_id: Session identifier.
            turn_id: Turn identifier within the session.
            audio: Float32 audio data.
            sample_rate: Audio sample rate.
            language: Detected language.

        Returns:
            TurnMetadata with all extracted features.
        """
        start = time.perf_counter()

        # Audio duration
        duration = len(audio) / sample_rate

        # --- Emotion extraction ---
        emotion = self._emotion.extract(audio, sample_rate)

        # --- Speaker embedding ---
        speaker_emb = self._speaker.extract_embedding(audio, sample_rate)

        # Track speaker across turns
        speaker_id = ""
        if speaker_emb and np.any(speaker_emb.embedding):
            # Check if this speaker matches a cached one
            if session_id in self._speaker_cache:
                is_same = SpeakerEncoder.is_same_speaker(
                    self._speaker_cache[session_id],
                    speaker_emb.embedding,
                )
                speaker_id = f"spk_{session_id}" if is_same else f"spk_{session_id}_new"
            else:
                speaker_id = f"spk_{session_id}"

            # Update cache
            self._speaker_cache[session_id] = speaker_emb.embedding

        extraction_time = time.perf_counter() - start

        metadata = TurnMetadata(
            session_id=session_id,
            turn_id=turn_id,
            speech_started=True,
            speech_ended=True,
            emotion=emotion,
            speaker_embedding=speaker_emb,
            speaker_embedding_id=speaker_id,
            language=language,
            duration=duration,
            extraction_time=round(extraction_time, 3),
        )

        logger.info(
            "features_extracted",
            session_id=session_id,
            turn_id=turn_id,
            emotion=emotion.label if emotion else "unknown",
            speaker_id=speaker_id,
            extraction_time=round(extraction_time, 3),
        )

        return metadata

    def clear_session_cache(self, session_id: str) -> None:
        """Clear cached speaker data for a session.

        Args:
            session_id: Session to clear.
        """
        self._speaker_cache.pop(session_id, None)
