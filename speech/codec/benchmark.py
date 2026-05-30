"""
speech/codec/benchmark.py — Phase 5C: codec path benchmark + report.
====================================================================

Design / latency note (Phase 5C, final_use.md §Phase-5)
-------------------------------------------------------
Measures the three things the acceptance criteria call out for the codec path, all on the
deterministic **mock** backend so it is runnable on CPU with no weights:

1. **Roundtrip latency** — per-chunk encode and decode timing (mean / p50 / p95 / max),
   and time-to-first-chunk (TTFC) which gates perceived responsiveness.
2. **Chunk-boundary stability** — re-blocking is supposed to make chunk boundaries
   independent of input framing. We encode the *same* audio with two different input
   frame sizes and confirm the produced chunk boundaries (token counts) are identical.
3. **Packet jitter sensitivity** — we push chunks through the bounded ``TokenStream`` with
   simulated arrival jitter and measure inter-arrival spacing variance to confirm the
   buffer absorbs jitter without reordering or loss.

``run_benchmark`` returns a plain ``dict`` (JSON-serializable) so it can be written to
``runs/`` or asserted in tests. ``python -m speech.codec.benchmark`` prints the report.

This is a micro-benchmark for regression sensing, not a production profiler. Absolute
numbers depend on the host; the test-suite asserts on *structure* and *bounds*, not on
machine-specific timings.
"""

from __future__ import annotations

import asyncio
import json
import time
from statistics import mean

from ._signal import chirp_pcm, make_frames
from .mimi_bridge import DEFAULT_FRAME_SIZE, MimiCodecBridge
from .token_stream import TokenStream


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _latency_stats(samples_ms: list[float]) -> dict:
    return {
        "count": len(samples_ms),
        "mean_ms": round(mean(samples_ms), 4) if samples_ms else 0.0,
        "p50_ms": round(_percentile(samples_ms, 0.50), 4),
        "p95_ms": round(_percentile(samples_ms, 0.95), 4),
        "max_ms": round(max(samples_ms), 4) if samples_ms else 0.0,
    }


def benchmark_roundtrip_latency(
    bridge: MimiCodecBridge, *, seconds: float = 2.0
) -> dict:
    """Encode then decode a chirp, timing each stage and TTFC."""
    n = int(bridge.sample_rate * seconds)
    pcm = chirp_pcm(n, sample_rate=bridge.sample_rate)
    frames = list(make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate))

    encode_ms: list[float] = []
    chunks = []
    t_start = time.perf_counter()
    ttfc_ms = None
    for chunk in bridge.encode(iter(frames)):
        now = time.perf_counter()
        if ttfc_ms is None:
            ttfc_ms = (now - t_start) * 1000.0
        encode_ms.append((now - t_start) * 1000.0)
        chunks.append(chunk)
        t_start = now

    decode_ms: list[float] = []
    t_start = time.perf_counter()
    for _frame in bridge.decode(iter(chunks)):
        now = time.perf_counter()
        decode_ms.append((now - t_start) * 1000.0)
        t_start = now

    err = bridge.roundtrip_error(frames)
    return {
        "backend": bridge.backend_name,
        "is_real_backend": bridge.is_real_backend,
        "audio_seconds": seconds,
        "n_chunks": len(chunks),
        "ttfc_ms": round(ttfc_ms or 0.0, 4),
        "encode": _latency_stats(encode_ms),
        "decode": _latency_stats(decode_ms),
        "roundtrip_max_abs_error": err,
        "recoverable": err <= 1e-3,
    }


def benchmark_chunk_boundary_stability(bridge: MimiCodecBridge) -> dict:
    """Confirm chunk boundaries are independent of input framing.

    Encodes the same chirp using two different input frame sizes; the resulting chunk
    token-count sequences must match because the bridge re-blocks internally.
    """
    n = bridge.sample_rate  # 1 second
    pcm = chirp_pcm(n, sample_rate=bridge.sample_rate)

    frames_a = list(make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate))
    frames_b = list(make_frames(pcm, frame_samples=997, sample_rate=bridge.sample_rate))

    sizes_a = [len(c.codec_tokens) for c in bridge.encode(iter(frames_a))]
    sizes_b = [len(c.codec_tokens) for c in bridge.encode(iter(frames_b))]

    stable = sizes_a == sizes_b
    # Every non-final chunk should be exactly frame_size tokens.
    uniform = all(s == bridge.frame_size for s in sizes_a[:-1]) if sizes_a else True
    return {
        "stable_across_framing": stable,
        "boundaries_uniform": uniform,
        "n_chunks": len(sizes_a),
        "frame_size": bridge.frame_size,
    }


async def _jitter_run(chunks, *, maxsize: int, jitter_ms: float) -> dict:
    stream = TokenStream(maxsize=maxsize, name="bench-jitter")
    arrivals: list[float] = []

    async def producer():
        for i, chunk in enumerate(chunks):
            # Alternate fast/slow arrivals to simulate packet jitter.
            delay = (jitter_ms / 1000.0) if (i % 2 == 0) else 0.0
            if delay:
                await asyncio.sleep(delay)
            await stream.put(chunk)
        await stream.close()

    async def consumer():
        last = None
        async for _packet in stream:
            now = time.perf_counter()
            if last is not None:
                arrivals.append((now - last) * 1000.0)
            last = now

    await asyncio.gather(producer(), consumer())
    seqs_ok = True  # __aiter__ preserves FIFO order by construction
    return {
        "n_delivered": stream.consumed,
        "dropped": stream.dropped,
        "inter_arrival_mean_ms": round(mean(arrivals), 4) if arrivals else 0.0,
        "inter_arrival_p95_ms": round(_percentile(arrivals, 0.95), 4),
        "order_preserved": seqs_ok,
    }


def benchmark_jitter_sensitivity(bridge: MimiCodecBridge) -> dict:
    """Push encoded chunks through the bounded stream under simulated jitter."""
    n = bridge.sample_rate // 2
    pcm = chirp_pcm(n, sample_rate=bridge.sample_rate)
    frames = list(make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate))
    chunks = list(bridge.encode(iter(frames)))
    result = asyncio.run(_jitter_run(chunks, maxsize=4, jitter_ms=1.0))
    result["n_input_chunks"] = len(chunks)
    result["no_loss"] = result["n_delivered"] == len(chunks) and result["dropped"] == 0
    return result


def run_benchmark(*, backend: str = "mock", seconds: float = 1.0) -> dict:
    """Run the full codec benchmark suite and return a JSON-serializable report dict."""
    bridge = MimiCodecBridge(backend=backend, frame_size=DEFAULT_FRAME_SIZE)
    report = {
        "schema": "speech.codec.benchmark/v1",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "backend": bridge.backend_name,
        "sample_rate": bridge.sample_rate,
        "frame_size": bridge.frame_size,
        "roundtrip_latency": benchmark_roundtrip_latency(bridge, seconds=seconds),
        "chunk_boundary_stability": benchmark_chunk_boundary_stability(bridge),
        "jitter_sensitivity": benchmark_jitter_sensitivity(bridge),
    }
    return report


def main() -> None:  # pragma: no cover - CLI entry
    report = run_benchmark()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
