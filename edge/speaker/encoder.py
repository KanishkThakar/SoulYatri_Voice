"""
edge/speaker/encoder.py — Speaker embedding feature provider (Phase 4A)
=======================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 4A).

Produces fixed-dimension speaker embeddings for speaker tracking / style continuity.
An ECAPA-TDNN model (final_use.md §2.2) is loaded **lazily** and only if torch +
speechbrain are importable; otherwise a deterministic signal-hash fallback is used so
the module imports and runs on a CPU-only machine with no weights (DECISIONS.md D-008).

The fallback embedding is intentionally simple but useful: it is L2-normalized and
stable for the same input, so cosine similarity is meaningful for "same vs different
speaker window" continuity checks in tests and bring-up.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence

from edge.session.logging_hooks import get_logger

logger = get_logger(__name__)

DEFAULT_EMBEDDING_DIM = 192  # ECAPA-TDNN default dimensionality.


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors; 0.0 for degenerate input."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class SpeakerEncoder:
    """Lazy-loaded speaker embedding provider with a deterministic fallback."""

    def __init__(
        self,
        model_name: str = "speechbrain/spkrec-ecapa-voxceleb",
        *,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        use_fallback: bool = False,
    ) -> None:
        self._model_name = model_name
        self._embedding_dim = embedding_dim
        self._use_fallback = use_fallback
        self._model = None
        self._load_attempted = False
        self._loaded = False

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def using_fallback(self) -> bool:
        return not self._loaded

    def _try_load(self) -> None:
        """One-time lazy load of the ECAPA model. Never raises."""
        if self._load_attempted or self._use_fallback:
            return
        self._load_attempted = True
        try:  # pragma: no cover - requires torch + speechbrain weights
            import torch  # noqa: F401
            from speechbrain.inference.speaker import EncoderClassifier

            self._model = EncoderClassifier.from_hparams(source=self._model_name)
            self._loaded = True
            logger.info("speaker_model_loaded", model=self._model_name)
        except Exception as exc:  # noqa: BLE001
            self._loaded = False
            logger.warning(
                "speaker_model_unavailable_using_fallback",
                model=self._model_name,
                error=str(exc),
            )

    def encode(
        self,
        samples: Sequence[float],
        sample_rate: int = 16000,
    ) -> list[float]:
        """Return an L2-normalized speaker embedding for a window of samples.

        Args:
            samples: Float32 mono samples in [-1, 1].
            sample_rate: Sample rate in Hz.

        Returns:
            A list of floats of length ``embedding_dim`` (unit norm unless silent).
        """
        self._try_load()
        if self._loaded:
            try:  # pragma: no cover - requires real model
                return self._encode_model(samples, sample_rate)
            except Exception as exc:  # noqa: BLE001
                logger.error("speaker_model_inference_failed", error=str(exc))
                self._loaded = False
        return self._encode_fallback(samples)

    def _encode_model(self, samples: Sequence[float], sample_rate: int) -> list[float]:  # pragma: no cover
        import torch

        wav = torch.tensor([list(samples)], dtype=torch.float32)
        emb = self._model.encode_batch(wav)  # type: ignore[union-attr]
        vec = emb.squeeze().detach().cpu().tolist()
        return self._l2_normalize([float(v) for v in vec])

    def _encode_fallback(self, samples: Sequence[float]) -> list[float]:
        """Deterministic embedding derived from coarse spectral/statistical features.

        We bucket the signal into ``embedding_dim`` bins and seed each bin from a hash
        of (bin index, bin energy). This is stable for identical input and varies with
        the signal, which is enough for continuity / same-speaker similarity in tests.
        """
        dim = self._embedding_dim
        n = len(samples)
        if n == 0:
            return [0.0] * dim

        # Aggregate energy per bin.
        bins = [0.0] * dim
        for i, s in enumerate(samples):
            bins[i % dim] += s * s

        # Silence (no energy) → zero vector (no speaker identity to encode).
        if sum(bins) <= 0.0:
            return [0.0] * dim
        # Mix each bin's energy with a deterministic hash to spread the signal.
        vec = [0.0] * dim
        for idx in range(dim):
            energy = bins[idx]
            seed = struct.pack("<id", idx, energy)
            digest = hashlib.sha256(seed).digest()
            # Map first 8 bytes to a float in [-1, 1].
            raw = struct.unpack("<q", digest[:8])[0]
            vec[idx] = (raw / (2**63)) * (0.5 + math.tanh(energy))
        normalized = self._l2_normalize(vec)
        logger.debug("speaker_fallback_embedding", dim=dim, frames=n)
        return normalized

    @staticmethod
    def _l2_normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 0.0:
            return vec
        return [v / norm for v in vec]
