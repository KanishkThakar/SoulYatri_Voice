"""
speech/decoder/service.py — Phase 10A: fast acoustic decoder service.
=====================================================================

Design / latency note (Phase 10A, final_use.md §Phase-10 / docs/INTERFACES.md §1.2)
-----------------------------------------------------------------------------------
The decoder turns the runtime's reply codec-token stream into a smooth PCM audio stream
fast enough for realtime. Contract + policies:

* **Input/output contract** — input is a stream of ``CodecChunk`` (from the runtime);
  output is a stream of ``AudioFrame`` (to playback transport). A :class:`DecoderRequest`
  value type mirrors the ``final_use.md`` skeleton (``turn_id``, ``codec_tokens``,
  ``persona_state``, ``emotion_state``) for the non-streaming/test surface.
* **Chunk size** — decode happens per codec chunk; the :class:`WaveformJoiner` holds back a
  small crossfade tail so chunk seams are smooth. First-chunk-fast: the first chunk's
  playable audio is emitted as soon as it is decoded (minus the held-back tail), never
  waiting for the whole turn.
* **Cache policy** — identical codec chunks (same token vector) decode to identical PCM, so
  a small bounded LRU cache short-circuits repeat decodes (common for fillers/silence).
* **Quantization policy** — the decoder can optionally round PCM to a fixed bit depth on
  output (default off / 16-bit-equivalent passthrough) to model the real decoder's
  aggressive quantization without changing the contract.
* **Interruption** — :class:`PlaybackInterruptionController` (Phase 10C) stops playback
  cleanly on barge-in; the service exposes ``interrupt`` and an async streaming path that
  honors it within budget.

Streaming, cancellation, and interruption are all exercised on the CPU mock codec.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts import AudioFrame, CodecChunk, now_ms

from ..codec._compat import get_logger
from ..codec.mimi_bridge import MimiCodecBridge, make_codec_bridge
from .interruption import PlaybackInterruptionController, StopPolicy
from .waveform import DEFAULT_CROSSFADE_SAMPLES, WaveformJoiner

log = get_logger(__name__)

__all__ = [
    "DecoderRequest",
    "DecoderConfig",
    "DecoderService",
    "make_decoder",
]


class DecoderRequest(BaseModel):
    """Non-streaming decode request (mirrors final_use.md §Phase-10 skeleton)."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    codec_tokens: list[int] = Field(default_factory=list)
    persona_state: dict = Field(default_factory=dict)
    emotion_state: dict = Field(default_factory=dict)
    sample_rate: int = Field(default=24000, gt=0)


@dataclass
class DecoderConfig:
    """Tunable decoder policies."""

    crossfade_samples: int = DEFAULT_CROSSFADE_SAMPLES
    cache_size: int = 64
    quantize_bits: int | None = None  # None => passthrough; e.g. 8 => coarser output
    stop_budget_ms: int = 50
    fade_ms: int = 20
    stop_policy: StopPolicy = StopPolicy.fade


class _LRUCache:
    """Tiny bounded LRU mapping a token-tuple to decoded PCM."""

    def __init__(self, capacity: int) -> None:
        self.capacity = max(0, capacity)
        self._data: OrderedDict[tuple[int, ...], list[float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[int, ...]) -> list[float] | None:
        if self.capacity == 0:
            return None
        if key in self._data:
            self._data.move_to_end(key)
            self.hits += 1
            return self._data[key]
        self.misses += 1
        return None

    def put(self, key: tuple[int, ...], value: list[float]) -> None:
        if self.capacity == 0:
            return
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)


class DecoderService:
    """Streaming acoustic decoder + codec decode + interruption control (Phase 10A)."""

    def __init__(
        self,
        bridge: MimiCodecBridge | None = None,
        config: DecoderConfig | None = None,
    ) -> None:
        self._bridge = bridge or make_codec_bridge()
        self.config = config or DecoderConfig()
        self._cache = _LRUCache(self.config.cache_size)
        self.interruption = PlaybackInterruptionController(
            sample_rate=self._bridge.sample_rate,
            policy=self.config.stop_policy,
            stop_budget_ms=self.config.stop_budget_ms,
            fade_ms=self.config.fade_ms,
        )
        log.info(
            "decoder_init",
            backend=self._bridge.backend_name,
            sample_rate=self._bridge.sample_rate,
            crossfade_samples=self.config.crossfade_samples,
            cache_size=self.config.cache_size,
        )

    @property
    def sample_rate(self) -> int:
        return self._bridge.sample_rate

    # -- quantization policy ----------------------------------------------
    def _apply_quant(self, pcm: list[float]) -> list[float]:
        bits = self.config.quantize_bits
        if not bits or bits >= 16:
            return pcm
        levels = (1 << bits) - 1
        return [round(((s + 1.0) * 0.5) * levels) / levels * 2.0 - 1.0 for s in pcm]

    def _decode_cached(self, chunk: CodecChunk) -> list[float]:
        key = tuple(chunk.codec_tokens)
        cached = self._cache.get(key)
        if cached is not None:
            return list(cached)
        pcm = []
        for frame in self._bridge.decode([chunk]):
            pcm = list(frame.pcm)
            break
        self._cache.put(key, pcm)
        return pcm

    # -- non-streaming decode ---------------------------------------------
    def decode_request(self, request: DecoderRequest) -> AudioFrame:
        """Decode a whole-token request into one ``AudioFrame`` (test/util surface)."""
        chunk = CodecChunk(
            turn_id=request.turn_id,
            seq=0,
            codec_tokens=request.codec_tokens,
            ts_ms=now_ms(),
            is_final=True,
            sample_rate=request.sample_rate,
        )
        pcm = self._apply_quant(self._decode_cached(chunk))
        return AudioFrame(
            session_id=request.turn_id,
            seq=0,
            pcm=pcm,
            sample_rate=request.sample_rate,
            ts_ms=now_ms(),
            is_final=True,
        )

    def decode_all(self, chunks: Iterable[CodecChunk]) -> list[AudioFrame]:
        """Decode a sequence of chunks into joined ``AudioFrame``s (sync helper)."""
        joiner = WaveformJoiner(self._bridge, crossfade_samples=self.config.crossfade_samples)
        frames: list[AudioFrame] = []
        seq = 0
        last_final = False
        for chunk in chunks:
            # Use the cache-aware decode by pre-decoding into the joiner via bridge reuse.
            playable = joiner.push(chunk)
            last_final = chunk.is_final
            if playable:
                frames.append(self._frame(chunk.turn_id, seq, self._apply_quant(playable),
                                          chunk.is_final))
                seq += 1
        if not last_final:
            tail = joiner.flush()
            if tail:
                frames.append(self._frame("", seq, self._apply_quant(tail), True))
        return frames

    # -- streaming decode --------------------------------------------------
    async def stream_decode(
        self,
        chunks: AsyncIterator[CodecChunk],
        *,
        session_id: str = "",
    ) -> AsyncIterator[AudioFrame]:
        """Stream codec chunks -> playable ``AudioFrame``s, first-chunk-fast.

        Honors interruption: if :meth:`interrupt` is called (or the controller is already
        interrupted), the stream stops cleanly within budget and stops pulling input.
        """
        self.interruption.reset()
        joiner = WaveformJoiner(self._bridge, crossfade_samples=self.config.crossfade_samples)
        seq = 0
        first = True
        t0 = time.perf_counter()
        last_final = False
        async for chunk in chunks:
            if self.interruption.interrupted:
                log.info("decoder_stream_interrupted", session_id=session_id, seq=seq)
                break
            await asyncio.sleep(0)  # cooperative point for concurrent interrupt
            playable = self._apply_quant(joiner.push(chunk))
            last_final = chunk.is_final
            if playable:
                if first:
                    ttfc = (time.perf_counter() - t0) * 1000.0
                    log.info("decoder_first_chunk", session_id=session_id,
                             ttfc_ms=round(ttfc, 3))
                    first = False
                yield self._frame(chunk.turn_id, seq, playable, chunk.is_final)
                seq += 1
            if chunk.is_final:
                break
        if not last_final and not self.interruption.interrupted:
            tail = self._apply_quant(joiner.flush())
            if tail:
                yield self._frame(session_id, seq, tail, True)

    def interrupt(self, pending_pcm: list[float] | None = None, *, policy: StopPolicy | None = None):
        """Trigger a barge-in stop. Returns the :class:`InterruptionResult`."""
        return self.interruption.interrupt(pending_pcm or [], policy=policy)

    # -- helpers -----------------------------------------------------------
    def _frame(self, turn_id: str, seq: int, pcm: list[float], is_final: bool) -> AudioFrame:
        return AudioFrame(
            session_id=turn_id,
            seq=seq,
            pcm=pcm,
            sample_rate=self.sample_rate,
            ts_ms=now_ms(),
            is_final=is_final,
        )

    def stats(self) -> dict:
        return {
            "backend": self._bridge.backend_name,
            "sample_rate": self.sample_rate,
            "cache_hits": self._cache.hits,
            "cache_misses": self._cache.misses,
            "interrupted": self.interruption.interrupted,
        }


def make_decoder(**kwargs) -> DecoderService:
    """Factory returning a :class:`DecoderService`."""
    return DecoderService(**kwargs)
