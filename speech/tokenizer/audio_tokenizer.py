"""
speech/tokenizer/audio_tokenizer.py — audio tokenization adapter (final_use.md §5.3).
=====================================================================================

Design note
-----------
The audio tokenizer is the role that "converts waveform into discrete codec tokens
preserving rhythm and prosody" (guide §5.3). In the frozen stack the tokenizer *is* the
Mimi codec's encode side, so rather than duplicate logic this is a thin, intention-
revealing adapter over :class:`speech.codec.mimi_bridge.MimiCodecBridge`.

Keeping it as a separate symbol matters because callers (edge ingest, runtime) talk about
"tokenizing user speech" and "detokenizing model output" as distinct verbs even though
both ride the same codec bridge. This adapter gives them that vocabulary without a second
backend.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from speech.codec._compat import AudioFrame, CodecChunk, get_logger
from speech.codec.mimi_bridge import MimiCodecBridge, make_codec_bridge

log = get_logger(__name__)

__all__ = ["AudioTokenizer"]


class AudioTokenizer:
    """Waveform <-> codec token adapter over the Mimi codec bridge.

    Parameters mirror :class:`MimiCodecBridge`; an existing bridge can be injected to
    share a single backend (and therefore a single lazy weight load) across the system.
    """

    def __init__(self, bridge: MimiCodecBridge | None = None, **bridge_kwargs) -> None:
        self._bridge = bridge or make_codec_bridge(**bridge_kwargs)
        log.info("audio_tokenizer_init", backend=self._bridge.backend_name)

    @property
    def bridge(self) -> MimiCodecBridge:
        return self._bridge

    @property
    def sample_rate(self) -> int:
        return self._bridge.sample_rate

    @property
    def backend_name(self) -> str:
        return self._bridge.backend_name

    def tokenize(self, frames: Iterable[AudioFrame]) -> Iterator[CodecChunk]:
        """Tokenize user/model waveform into a codec-token stream."""
        return self._bridge.encode(frames)

    def detokenize(self, chunks: Iterable[CodecChunk]) -> Iterator[AudioFrame]:
        """Reconstruct waveform from a codec-token stream."""
        return self._bridge.decode(chunks)
