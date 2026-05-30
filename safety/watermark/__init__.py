"""safety/watermark/ — Synthesized-audio watermarking (final_use.md §4, Phase 11C).

Owner: safety agent. Inserts and verifies an audio watermark (AudioSeal-class) on
generated audio, logs detector outcomes, and exposes ops tooling. Pinning pending
(MODEL_LOCKS / OPEN_QUESTIONS Q-007).
"""

from .audioseal import (
    DEFAULT_PAYLOAD,
    DeterministicFallbackBackend,
    WatermarkComplianceError,
    Watermarker,
    ops_status,
)

__all__ = [
    "Watermarker",
    "DeterministicFallbackBackend",
    "WatermarkComplianceError",
    "DEFAULT_PAYLOAD",
    "ops_status",
]
