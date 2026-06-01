"""speech/tokenizer/ — Audio tokenization adapter (final_use.md §4, §5.3).

Owner: speech/runtime agent. Converts waveform into discrete codec tokens preserving
rhythm and prosody. Primary path = Mimi; loaded lazily, GPU-optional. Thin adapter over
speech.codec.mimi_bridge.MimiCodecBridge.
"""

from .audio_tokenizer import AudioTokenizer

__all__ = ["AudioTokenizer"]
