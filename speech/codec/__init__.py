"""speech/codec/ — Neural codec bridge + token-stream contract (final_use.md §4, Phase 5).

Owner: speech/runtime agent. Mimi encode/decode roundtrip behind a stable CodecBridge
interface (SNAC/DAC may sit behind it). Defines token packet sequencing, backpressure,
and cancellation. Emits CodecChunk (shared/contracts.py).

Public API:
  * MimiCodecBridge / make_codec_bridge  — Phase 5A waveform <-> codec tokens
  * TokenStream / TokenPacket            — Phase 5B bounded async token stream
  * run_benchmark                        — Phase 5C codec path benchmark
  * CodecBridge                          — the Phase 5 protocol (from shared or local shim)

Heavy Mimi weights load lazily; this package imports cleanly with no GPU/weights.
"""

from ._compat import CodecBridge
from .mimi_bridge import (
    CODEC_SAMPLE_RATE,
    DEFAULT_FRAME_SIZE,
    MimiCodecBridge,
    MockCodecBackend,
    make_codec_bridge,
)
from .token_stream import (
    SequenceError,
    StreamCancelled,
    TokenPacket,
    TokenStream,
    drain_to_list,
)

__all__ = [
    "CodecBridge",
    "MimiCodecBridge",
    "MockCodecBackend",
    "make_codec_bridge",
    "CODEC_SAMPLE_RATE",
    "DEFAULT_FRAME_SIZE",
    "TokenStream",
    "TokenPacket",
    "StreamCancelled",
    "SequenceError",
    "drain_to_list",
]
