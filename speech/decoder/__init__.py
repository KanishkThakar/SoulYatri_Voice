"""speech/decoder/ — Fast acoustic decoder + codec decode + interruption control (final_use.md §4, Phase 10).

Owner: speech/runtime agent. Transforms high-level speech tokens into fine acoustic
tokens and reconstructs waveform with smooth chunk joins. Stops cleanly on barge-in.
Optimized for streaming continuity (no full-sentence blocking).

Public API:
  * DecoderService / make_decoder            — Phase 10A streaming decoder service
  * WaveformJoiner / decode_chunks_to_pcm    — Phase 10B waveform reconstruction + joins
  * PlaybackInterruptionController/StopPolicy — Phase 10C interruption control
"""

from .interruption import (
    InterruptionResult,
    PlaybackInterruptionController,
    StopPolicy,
)
from .service import DecoderConfig, DecoderRequest, DecoderService, make_decoder
from .waveform import (
    DEFAULT_CROSSFADE_SAMPLES,
    WaveformJoiner,
    decode_chunks_to_pcm,
)

__all__ = [
    "DecoderService",
    "make_decoder",
    "DecoderConfig",
    "DecoderRequest",
    "WaveformJoiner",
    "decode_chunks_to_pcm",
    "DEFAULT_CROSSFADE_SAMPLES",
    "PlaybackInterruptionController",
    "StopPolicy",
    "InterruptionResult",
]
