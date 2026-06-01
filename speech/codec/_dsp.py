"""
speech/codec/_dsp.py — tiny pure-Python DSP helpers (no numpy required).
========================================================================

The CPU/no-weights baseline (DECISIONS.md D-008) must import and run without numpy,
torch, or any native audio library. These helpers implement the small amount of signal
math the codec + decoder fallbacks need:

* reversible 16-bit float<->int quantization (the mock codec's "RVQ stub"),
* linear resampling between sample rates,
* RMS / peak measurement for intelligibility checks,
* equal-power crossfade for smooth chunk joins,
* a linear fade ramp for clean interruption stops.

Everything is plain ``list[float]`` math so it is deterministic across machines.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "QUANT_LEVELS",
    "quantize_sample",
    "dequantize_token",
    "quantize_pcm",
    "dequantize_tokens",
    "resample_linear",
    "rms",
    "peak",
    "max_abs_error",
    "equal_power_crossfade",
    "linear_fade",
]

# 16-bit unsigned quantization grid. 65535 steps over [-1, 1] => step ~3.05e-5,
# i.e. worst-case roundtrip error ~1.53e-5, which keeps the mock roundtrip
# perceptually lossless ("intelligible/recoverable") while staying integer-token based.
QUANT_LEVELS = 65535


def quantize_sample(value: float, levels: int = QUANT_LEVELS) -> int:
    """Map a float sample in [-1, 1] to a non-negative integer token in [0, levels]."""
    if value != value:  # NaN guard
        value = 0.0
    clamped = -1.0 if value < -1.0 else (1.0 if value > 1.0 else value)
    return int(round((clamped + 1.0) * 0.5 * levels))


def dequantize_token(token: int, levels: int = QUANT_LEVELS) -> float:
    """Inverse of :func:`quantize_sample`."""
    t = 0 if token < 0 else (levels if token > levels else token)
    return (t / levels) * 2.0 - 1.0


def quantize_pcm(pcm: Sequence[float], levels: int = QUANT_LEVELS) -> list[int]:
    """Quantize a block of float samples to integer tokens."""
    return [quantize_sample(s, levels) for s in pcm]


def dequantize_tokens(tokens: Sequence[int], levels: int = QUANT_LEVELS) -> list[float]:
    """Dequantize integer tokens back to float samples in [-1, 1]."""
    return [dequantize_token(t, levels) for t in tokens]


def resample_linear(pcm: Sequence[float], src_rate: int, dst_rate: int) -> list[float]:
    """Resample ``pcm`` from ``src_rate`` to ``dst_rate`` with linear interpolation.

    Pure-Python and deterministic. Returns ``pcm`` unchanged when rates already match.
    """
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("sample rates must be positive")
    n = len(pcm)
    if src_rate == dst_rate or n == 0:
        return list(pcm)
    out_n = max(1, int(round(n * dst_rate / src_rate)))
    if n == 1:
        return [float(pcm[0])] * out_n
    out: list[float] = []
    ratio = (n - 1) / (out_n - 1) if out_n > 1 else 0.0
    for i in range(out_n):
        pos = i * ratio
        left = int(math.floor(pos))
        right = min(left + 1, n - 1)
        frac = pos - left
        out.append(pcm[left] * (1.0 - frac) + pcm[right] * frac)
    return out


def rms(pcm: Sequence[float]) -> float:
    """Root-mean-square amplitude of a block (0.0 for empty)."""
    if not pcm:
        return 0.0
    return math.sqrt(sum(s * s for s in pcm) / len(pcm))


def peak(pcm: Sequence[float]) -> float:
    """Peak absolute amplitude of a block (0.0 for empty)."""
    if not pcm:
        return 0.0
    return max(abs(s) for s in pcm)


def max_abs_error(a: Sequence[float], b: Sequence[float]) -> float:
    """Max absolute sample error over the overlapping region of two blocks."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return max(abs(a[i] - b[i]) for i in range(n))


def equal_power_crossfade(
    tail: Sequence[float], head: Sequence[float], overlap: int
) -> list[float]:
    """Equal-power crossfade joining the end of ``tail`` into the start of ``head``.

    Returns ``tail[:-overlap] + crossfade(overlap) + head[overlap:]``. Falls back to a
    plain concatenation when there is not enough material to overlap.
    """
    if overlap <= 0 or len(tail) < overlap or len(head) < overlap:
        return list(tail) + list(head)
    out = list(tail[:-overlap])
    for i in range(overlap):
        # cos/sin equal-power weights keep perceived loudness constant across the join.
        theta = (i / overlap) * (math.pi / 2.0)
        w_out = math.cos(theta)
        w_in = math.sin(theta)
        out.append(tail[len(tail) - overlap + i] * w_out + head[i] * w_in)
    out.extend(head[overlap:])
    return out


def linear_fade(pcm: Sequence[float], fade_samples: int, *, fade_out: bool = True) -> list[float]:
    """Apply a linear fade ramp over ``fade_samples`` at the end (or start) of a block."""
    out = list(pcm)
    n = len(out)
    if fade_samples <= 0 or n == 0:
        return out
    k = min(fade_samples, n)
    for i in range(k):
        if fade_out:
            gain = 1.0 - (i + 1) / k
            out[n - k + i] *= gain
        else:
            gain = (i + 1) / k
            out[i] *= gain
    return out
