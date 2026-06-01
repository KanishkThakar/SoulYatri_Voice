"""
speech/decoder/waveform.py — Phase 10B: codec tokens -> waveform with smooth joins.
===================================================================================

Design note (Phase 10B, final_use.md §Phase-10)
-----------------------------------------------
Reconstructs waveform from codec tokens *via the codec bridge* (so the same Mimi/mock
backend used for encoding is used for decoding — no second source of truth), then makes
consecutive chunks join smoothly:

* **chunk-boundary alignment** — each decoded chunk is appended in order; the joiner keeps
  a short tail of the previous chunk so it can blend the boundary.
* **smooth joins / crossfade** — an equal-power crossfade (``_dsp.equal_power_crossfade``)
  over a small overlap removes the click/discontinuity that raw concatenation produces at
  chunk seams. Crossfade width is configurable and falls back to plain concatenation when
  chunks are too short to overlap.

The joiner is incremental: ``push(chunk)`` returns the audio that is safe to play *now*
(everything except the trailing overlap region, which is held back to blend with the next
chunk), and ``flush()`` returns the final held-back tail. This is what lets the decoder
stream the first chunk fast while still producing artifact-free joins.
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.contracts import AudioFrame, CodecChunk

from ..codec._compat import get_logger
from ..codec._dsp import equal_power_crossfade
from ..codec.mimi_bridge import MimiCodecBridge, make_codec_bridge

log = get_logger(__name__)

__all__ = ["DEFAULT_CROSSFADE_SAMPLES", "WaveformJoiner", "decode_chunks_to_pcm"]

# 5 ms @ 24 kHz. Wide enough to mask a seam, short enough to not blur transients.
DEFAULT_CROSSFADE_SAMPLES = 120


class WaveformJoiner:
    """Incrementally decode + join codec chunks into a smooth PCM stream.

    Parameters
    ----------
    bridge:
        Codec bridge used to detokenize chunks. Shared with the encoder when injected.
    crossfade_samples:
        Overlap length for equal-power crossfade between consecutive chunks.
    """

    def __init__(
        self,
        bridge: MimiCodecBridge | None = None,
        *,
        crossfade_samples: int = DEFAULT_CROSSFADE_SAMPLES,
    ) -> None:
        self._bridge = bridge or make_codec_bridge()
        self.crossfade_samples = max(0, crossfade_samples)
        self._tail: list[float] = []  # held-back overlap region from the previous chunk
        self._emitted_samples = 0
        self._chunks_seen = 0

    @property
    def sample_rate(self) -> int:
        return self._bridge.sample_rate

    def _decode_one(self, chunk: CodecChunk) -> list[float]:
        # Reuse the bridge's single-chunk decode path.
        for frame in self._bridge.decode([chunk]):
            return list(frame.pcm)
        return []

    def push(self, chunk: CodecChunk) -> list[float]:
        """Decode + join one chunk; return PCM that is safe to play immediately.

        The trailing ``crossfade_samples`` are held back internally to blend with the next
        chunk. Call :meth:`flush` after the last chunk to drain that tail.
        """
        self._chunks_seen += 1
        samples = self._decode_one(chunk)

        if not self._tail:
            # First chunk: hold back the tail, emit the rest.
            playable, self._tail = self._split_tail(samples)
        else:
            joined = equal_power_crossfade(self._tail, samples, self.crossfade_samples)
            # Everything up to the new tail is now playable.
            playable, self._tail = self._split_tail(joined)

        if chunk.is_final:
            playable = playable + self._tail
            self._tail = []

        self._emitted_samples += len(playable)
        return playable

    def _split_tail(self, samples: list[float]) -> tuple[list[float], list[float]]:
        if self.crossfade_samples <= 0 or len(samples) <= self.crossfade_samples:
            # Not enough to hold back a full overlap; keep everything as tail until final.
            return [], list(samples)
        cut = len(samples) - self.crossfade_samples
        return samples[:cut], samples[cut:]

    def flush(self) -> list[float]:
        """Return any held-back tail (call once after the last non-final push)."""
        tail = self._tail
        self._tail = []
        self._emitted_samples += len(tail)
        return tail

    def stats(self) -> dict:
        return {
            "chunks_seen": self._chunks_seen,
            "emitted_samples": self._emitted_samples,
            "crossfade_samples": self.crossfade_samples,
            "sample_rate": self.sample_rate,
        }


def decode_chunks_to_pcm(
    chunks: Iterable[CodecChunk],
    *,
    bridge: MimiCodecBridge | None = None,
    crossfade_samples: int = DEFAULT_CROSSFADE_SAMPLES,
) -> list[float]:
    """One-shot helper: decode an iterable of chunks into a single joined PCM buffer."""
    joiner = WaveformJoiner(bridge, crossfade_samples=crossfade_samples)
    out: list[float] = []
    last_final = False
    for chunk in chunks:
        out.extend(joiner.push(chunk))
        last_final = chunk.is_final
    if not last_final:
        out.extend(joiner.flush())
    return out


def pcm_to_frame(
    pcm: list[float], *, session_id: str, seq: int, sample_rate: int, ts_ms: int, is_final: bool
) -> AudioFrame:
    """Wrap a PCM block as an ``AudioFrame`` for playback transport."""
    return AudioFrame(
        session_id=session_id,
        seq=seq,
        pcm=pcm,
        sample_rate=sample_rate,
        ts_ms=ts_ms,
        is_final=is_final,
    )
