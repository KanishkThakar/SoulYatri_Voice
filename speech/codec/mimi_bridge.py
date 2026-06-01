"""
speech/codec/mimi_bridge.py — Phase 5A: neural codec bridge (Mimi) with CPU fallback.
=====================================================================================

Design note (Phase 5A, final_use.md §Phase-5 / docs/INTERFACES.md §5.2)
-----------------------------------------------------------------------
This module implements the :class:`CodecBridge` contract:

    encode(frames: Iterable[AudioFrame]) -> Iterable[CodecChunk]
    decode(chunks: Iterable[CodecChunk]) -> Iterable[AudioFrame]

It is the bridge between waveform audio and the speech-native runtime. The *real*
architecture uses **Mimi** (the streaming neural codec used by Moshi). Because this
environment has **no GPU and no Mimi weights**, the bridge is built around two
interchangeable backends behind one interface:

* ``MimiBackend``  — lazy-loads the real ``moshi``/``mimi`` package + weights inside a
  method, guarded by try/except. Never imported at module top level.
* ``MockCodecBackend`` — a deterministic, dependency-free **reversible quantization
  stub** (16-bit float<->int) that makes the roundtrip *recoverable/intelligible* on a
  CPU with no weights, so everything imports and tests pass.

The bridge auto-selects the real backend when available and silently falls back to the
mock otherwise. Callers can force a backend for tests/benchmarks. The selected backend is
recorded on ``CodecBridge.backend_name`` and logged, so it is always auditable which path
ran (this is *not* the final architecture when the mock is active — that is documented in
the log line and the README).

Chunk policy
------------
* Sample rate: **24 kHz** (matches ``CodecChunk.sample_rate`` default and Moshi/Mimi).
* Frame policy: input ``AudioFrame``s may arrive at any capture rate (e.g. 16 kHz). They
  are resampled to 24 kHz before tokenization.
* Chunk policy: a fixed ``frame_size`` (default 1920 samples = 80 ms @ 24 kHz) controls
  how many samples map to one ``CodecChunk``, giving stable chunk boundaries for
  streaming. ``encode_stream``/``decode_stream`` re-block audio so boundaries do not
  depend on how the caller happened to split frames.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ._compat import AudioFrame, CodecChunk, get_logger
from ._dsp import (
    QUANT_LEVELS,
    dequantize_tokens,
    max_abs_error,
    quantize_pcm,
    resample_linear,
)

log = get_logger(__name__)

# Default codec sample rate (Mimi / Moshi operate at 24 kHz).
CODEC_SAMPLE_RATE = 24000
# 80 ms @ 24 kHz. Small enough for low first-chunk latency, large enough to be stable.
DEFAULT_FRAME_SIZE = 1920


# ---------------------------------------------------------------------------
# Backend protocol + implementations
# ---------------------------------------------------------------------------
@dataclass
class _Block:
    """An internal fixed-size block of resampled 24 kHz audio awaiting tokenization."""

    samples: list[float]
    ts_ms: int
    is_final: bool


class MockCodecBackend:
    """Deterministic, dependency-free reversible-quantization codec stub.

    Tokenization = 16-bit quantization of each sample (``_dsp.quantize_pcm``). Detokenize
    = exact inverse. This is intentionally *not* a compressing neural codec; it exists so
    the speech-native loop is end-to-end runnable and testable on CPU with no weights, and
    so roundtrip audio stays recoverable (max abs error <= 1 quantization step).
    """

    name = "mock"
    is_real = False

    def __init__(self, levels: int = QUANT_LEVELS) -> None:
        self.levels = levels

    def tokenize(self, samples: list[float]) -> list[int]:
        return quantize_pcm(samples, self.levels)

    def detokenize(self, tokens: list[int]) -> list[float]:
        return dequantize_tokens(tokens, self.levels)


class MimiBackend:
    """Lazy adapter around the real Mimi neural codec.

    The heavy import + weight load happens in :meth:`load`, guarded by try/except. If the
    ``moshi``/``mimi`` package or weights are unavailable (the case in this CPU/no-weights
    environment), :meth:`load` raises and the bridge falls back to the mock backend.

    NOTE: ``torch``/``moshi`` are imported *inside* ``load`` only — never at module top
    level — per the CPU/no-weights rule (DECISIONS.md D-008).
    """

    name = "mimi"
    is_real = True

    def __init__(self, weights_path: str | None = None, device: str = "cpu") -> None:
        self.weights_path = weights_path
        self.device = device
        self._model = None  # populated by load()

    def load(self) -> None:
        """Attempt to load Mimi weights. Raises on any failure so callers can fall back."""
        try:
            # Imported lazily and locally on purpose. Do not hoist to module scope.
            import torch  # noqa: F401
            from moshi.models import loaders  # type: ignore

            if not self.weights_path:
                raise RuntimeError("no Mimi weights path configured (set MIMI_WEIGHTS)")
            # The exact loader API is pinned in docs/MODEL_LOCKS.md when weights land.
            self._model = loaders.get_mimi(self.weights_path, device=self.device)
            self._model.eval()
        except Exception as exc:  # noqa: BLE001 - any failure => fall back to mock
            raise RuntimeError(f"Mimi unavailable, falling back to mock codec: {exc}") from exc

    def tokenize(self, samples: list[float]) -> list[int]:  # pragma: no cover - needs weights
        if self._model is None:
            raise RuntimeError("MimiBackend.load() must succeed before tokenize()")
        import torch

        with torch.no_grad():
            wav = torch.tensor(samples, dtype=torch.float32).reshape(1, 1, -1)
            codes = self._model.encode(wav)  # [B, K, T]
            return codes.reshape(-1).to("cpu").tolist()

    def detokenize(self, tokens: list[int]) -> list[float]:  # pragma: no cover - needs weights
        if self._model is None:
            raise RuntimeError("MimiBackend.load() must succeed before detokenize()")
        import torch

        with torch.no_grad():
            codes = torch.tensor(tokens, dtype=torch.long).reshape(1, -1, 1)
            wav = self._model.decode(codes)
            return wav.reshape(-1).to("cpu").tolist()


# ---------------------------------------------------------------------------
# CodecBridge — the public Phase-5A surface
# ---------------------------------------------------------------------------
class MimiCodecBridge:
    """``CodecBridge`` implementation: waveform <-> codec tokens (Phase 5A).

    Auto-selects the real Mimi backend when its weights/deps are importable, else falls
    back to the deterministic mock codec so the roundtrip is runnable on CPU.

    Parameters
    ----------
    sample_rate:
        Codec rate the tokens decode back to (default 24 kHz).
    frame_size:
        Samples per ``CodecChunk`` at ``sample_rate`` (default 1920 = 80 ms).
    backend:
        ``"auto"`` (default), ``"mimi"`` (force real, raises if unavailable), or
        ``"mock"`` (force the CPU fallback).
    weights_path:
        Optional Mimi weights path; defaults to the ``MIMI_WEIGHTS`` env var.
    """

    def __init__(
        self,
        *,
        sample_rate: int = CODEC_SAMPLE_RATE,
        frame_size: int = DEFAULT_FRAME_SIZE,
        backend: str = "auto",
        weights_path: str | None = None,
        device: str = "cpu",
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if frame_size <= 0:
            raise ValueError("frame_size must be positive")
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self._weights_path = weights_path or os.environ.get("MIMI_WEIGHTS")
        self._device = device
        self._backend = self._select_backend(backend)
        log.info(
            "codec_bridge_init",
            backend=self.backend_name,
            is_real=self._backend.is_real,
            sample_rate=self.sample_rate,
            frame_size=self.frame_size,
        )

    # -- backend selection -------------------------------------------------
    def _select_backend(self, backend: str):  # noqa: ANN202 - internal union
        if backend == "mock":
            return MockCodecBackend()
        if backend in ("auto", "mimi"):
            mimi = MimiBackend(self._weights_path, self._device)
            try:
                mimi.load()
                log.info("codec_backend_selected", backend="mimi", path=self._weights_path)
                return mimi
            except Exception as exc:  # noqa: BLE001
                if backend == "mimi":
                    raise
                log.warning(
                    "codec_backend_fallback",
                    requested="mimi",
                    using="mock",
                    reason=str(exc),
                    note="NOT final architecture; mock codec active (CPU/no-weights).",
                )
                return MockCodecBackend()
        raise ValueError(f"unknown backend: {backend!r}")

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def is_real_backend(self) -> bool:
        return self._backend.is_real

    # -- internal re-blocking ---------------------------------------------
    def _reblock(self, frames: Iterable[AudioFrame]) -> Iterator[_Block]:
        """Resample frames to the codec rate and re-block into fixed ``frame_size`` chunks.

        Re-blocking makes chunk boundaries independent of the caller's framing, which is
        what keeps chunk-boundary stability under jitter (Phase 5C measures this).
        """
        carry: list[float] = []
        last_ts = 0
        saw_final = False
        for frame in frames:
            last_ts = frame.ts_ms
            samples = resample_linear(frame.pcm, frame.sample_rate, self.sample_rate)
            carry.extend(samples)
            if frame.is_final:
                saw_final = True
            while len(carry) >= self.frame_size:
                block = carry[: self.frame_size]
                carry = carry[self.frame_size :]
                yield _Block(block, last_ts, is_final=False)
        # Flush remainder (zero-padded) as the final block so no audio is dropped.
        if carry or saw_final:
            if carry and len(carry) < self.frame_size:
                carry = carry + [0.0] * (self.frame_size - len(carry))
            yield _Block(carry, last_ts, is_final=True)

    # -- CodecBridge API ---------------------------------------------------
    def encode(self, frames: Iterable[AudioFrame]) -> Iterator[CodecChunk]:
        """Encode an iterable of ``AudioFrame`` into a stream of ``CodecChunk``.

        ``turn_id`` is taken from the frame ``session_id`` (the bridge is turn-agnostic;
        higher layers stamp a real ``turn_id`` — see ``token_stream``). Sequence numbers
        are assigned monotonically per call.
        """
        turn_id = "codec"
        first = True
        seq = 0
        for block in self._reblock(frames):
            if first:
                turn_id = getattr(block, "session_id", turn_id)
                first = False
            tokens = self._backend.tokenize(block.samples)
            yield CodecChunk(
                turn_id=turn_id,
                seq=seq,
                codec_tokens=tokens,
                ts_ms=block.ts_ms,
                is_final=block.is_final,
                sample_rate=self.sample_rate,
            )
            seq += 1

    def decode(self, chunks: Iterable[CodecChunk]) -> Iterator[AudioFrame]:
        """Decode an iterable of ``CodecChunk`` back into ``AudioFrame`` PCM."""
        seq = 0
        for chunk in chunks:
            samples = self._backend.detokenize(chunk.codec_tokens)
            yield AudioFrame(
                session_id=chunk.turn_id,
                seq=seq,
                pcm=samples,
                sample_rate=chunk.sample_rate or self.sample_rate,
                ts_ms=chunk.ts_ms,
                is_final=chunk.is_final,
            )
            seq += 1

    # -- convenience -------------------------------------------------------
    def roundtrip(self, frames: Iterable[AudioFrame]) -> list[AudioFrame]:
        """Encode then decode in one shot (used by tests + benchmark)."""
        return list(self.decode(self.encode(frames)))

    def roundtrip_error(self, frames: list[AudioFrame]) -> float:
        """Max abs sample error of a full encode->decode roundtrip.

        Concatenates input PCM (resampled to the codec rate) and output PCM and compares.
        For the mock backend this is bounded by one quantization step.
        """
        original: list[float] = []
        for f in frames:
            original.extend(resample_linear(f.pcm, f.sample_rate, self.sample_rate))
        decoded: list[float] = []
        for out in self.decode(self.encode(frames)):
            decoded.extend(out.pcm)
        return max_abs_error(original, decoded)


def make_codec_bridge(**kwargs) -> MimiCodecBridge:
    """Factory returning a :class:`MimiCodecBridge` (auto backend by default)."""
    return MimiCodecBridge(**kwargs)
