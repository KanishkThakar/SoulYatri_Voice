"""
speech/codec/_signal.py — deterministic synthetic audio for tests + benchmarks.
================================================================================

Pure-Python tone/noise generators (no numpy) used by the codec benchmark and the speech
test-suite to build reproducible ``AudioFrame`` streams without recording real audio.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from ._compat import AudioFrame

__all__ = ["sine_pcm", "chirp_pcm", "make_frames"]


def sine_pcm(
    n_samples: int, *, freq: float = 220.0, sample_rate: int = 24000, amplitude: float = 0.6
) -> list[float]:
    """Generate a mono sine wave of ``n_samples`` at ``freq`` Hz."""
    two_pi_f = 2.0 * math.pi * freq
    return [amplitude * math.sin(two_pi_f * (i / sample_rate)) for i in range(n_samples)]


def chirp_pcm(
    n_samples: int,
    *,
    f0: float = 110.0,
    f1: float = 880.0,
    sample_rate: int = 24000,
    amplitude: float = 0.6,
) -> list[float]:
    """Generate a linear chirp from ``f0`` to ``f1`` Hz over ``n_samples``."""
    if n_samples <= 1:
        return sine_pcm(n_samples, freq=f0, sample_rate=sample_rate, amplitude=amplitude)
    out: list[float] = []
    for i in range(n_samples):
        t = i / sample_rate
        frac = i / (n_samples - 1)
        freq = f0 + (f1 - f0) * frac
        out.append(amplitude * math.sin(2.0 * math.pi * freq * t))
    return out


def make_frames(
    pcm: list[float],
    *,
    session_id: str = "bench",
    frame_samples: int = 480,
    sample_rate: int = 24000,
    start_ts_ms: int = 0,
) -> Iterator[AudioFrame]:
    """Slice a PCM buffer into a stream of ``AudioFrame``s.

    The last frame is flagged ``is_final``. ``ts_ms`` advances by the per-frame duration so
    downstream jitter/timestamp logic has realistic spacing.
    """
    total = len(pcm)
    if total == 0:
        yield AudioFrame(
            session_id=session_id, seq=0, pcm=[], sample_rate=sample_rate,
            ts_ms=start_ts_ms, is_final=True,
        )
        return
    ms_per_frame = int(round(frame_samples / sample_rate * 1000))
    seq = 0
    for start in range(0, total, frame_samples):
        block = pcm[start : start + frame_samples]
        is_final = start + frame_samples >= total
        yield AudioFrame(
            session_id=session_id,
            seq=seq,
            pcm=block,
            sample_rate=sample_rate,
            ts_ms=start_ts_ms + seq * ms_per_frame,
            is_final=is_final,
        )
        seq += 1
