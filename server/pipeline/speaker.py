"""
SoulYatri Speech — Speaker Embedding Encoder
===============================================
Extracts speaker embeddings for voice consistency tracking
and speaker diarization across turns within a session.

Uses ECAPA-TDNN via SpeechBrain for 192-dim speaker vectors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import torch

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import speaker_similarity_hist, errors_total

logger = get_logger(__name__)


@dataclass
class SpeakerEmbedding:
    """Result from speaker embedding extraction."""

    embedding: np.ndarray        # 192-dim speaker vector
    processing_time: float
    model: str = "ecapa-tdnn"


class SpeakerEncoder:
    """ECAPA-TDNN speaker embedding extraction via SpeechBrain.

    Generates compact speaker vectors that can be compared
    using cosine similarity for speaker tracking.
    """

    def __init__(self) -> None:
        self._model = None
        self._model_source = settings.speaker.model_source
        self._save_dir = settings.speaker.save_dir
        self._device = settings.speaker.device
        self._initialized = False

    def load_model(self) -> None:
        """Load the speaker encoder model. Call once at startup."""
        logger.info(
            "loading_speaker_model",
            model_source=self._model_source,
            device=self._device,
        )

        try:
            from speechbrain.inference.speaker import EncoderClassifier

            device = self._device if torch.cuda.is_available() else "cpu"
            self._model = EncoderClassifier.from_hparams(
                source=self._model_source,
                savedir=self._save_dir,
                run_opts={"device": device},
            )

            self._initialized = True
            logger.info("speaker_model_loaded", device=device)

        except Exception as e:
            logger.error("speaker_model_load_failed", error=str(e))
            raise

    def extract_embedding(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> SpeakerEmbedding:
        """Extract a speaker embedding from audio.

        Args:
            audio: Float32 audio array.
            sample_rate: Sample rate (must be 16kHz).

        Returns:
            SpeakerEmbedding with the 192-dim vector.
        """
        if not self._initialized:
            return SpeakerEmbedding(
                embedding=np.zeros(192, dtype=np.float32),
                processing_time=0.0,
            )

        start = time.perf_counter()

        try:
            # SpeechBrain expects a torch tensor
            waveform = torch.from_numpy(audio).unsqueeze(0).float()

            with torch.no_grad():
                embedding = self._model.encode_batch(waveform)

            # Shape: (1, 1, 192) → (192,)
            embedding_np = embedding.squeeze().cpu().numpy()

            processing_time = time.perf_counter() - start

            logger.debug(
                "speaker_embedding_extracted",
                shape=embedding_np.shape,
                processing_time=round(processing_time, 3),
            )

            return SpeakerEmbedding(
                embedding=embedding_np,
                processing_time=round(processing_time, 3),
            )

        except Exception as e:
            processing_time = time.perf_counter() - start
            errors_total.labels(
                component="speaker", error_type=type(e).__name__
            ).inc()
            logger.error("speaker_embedding_error", error=str(e))

            return SpeakerEmbedding(
                embedding=np.zeros(192, dtype=np.float32),
                processing_time=round(processing_time, 3),
            )

    @staticmethod
    def cosine_similarity(
        embedding_a: np.ndarray, embedding_b: np.ndarray
    ) -> float:
        """Compute cosine similarity between two speaker embeddings.

        Args:
            embedding_a: First speaker embedding.
            embedding_b: Second speaker embedding.

        Returns:
            Cosine similarity in [-1, 1]. Higher = more similar.
        """
        norm_a = np.linalg.norm(embedding_a)
        norm_b = np.linalg.norm(embedding_b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        similarity = float(
            np.dot(embedding_a, embedding_b) / (norm_a * norm_b)
        )

        speaker_similarity_hist.observe(similarity)
        return round(similarity, 4)

    @staticmethod
    def is_same_speaker(
        embedding_a: np.ndarray,
        embedding_b: np.ndarray,
        threshold: float = 0.75,
    ) -> bool:
        """Check if two embeddings are from the same speaker.

        Args:
            embedding_a: First speaker embedding.
            embedding_b: Second speaker embedding.
            threshold: Similarity threshold.

        Returns:
            True if same speaker.
        """
        sim = SpeakerEncoder.cosine_similarity(embedding_a, embedding_b)
        return sim >= threshold
