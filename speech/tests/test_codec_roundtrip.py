"""Phase 5A/5C tests — codec roundtrip intelligibility + benchmark structure.

All on the mock backend (CPU, no weights). Acceptance: roundtrip audio remains
recoverable/intelligible and chunk boundaries are stable.
"""

from __future__ import annotations

import math

from speech.codec._dsp import rms
from speech.codec._signal import chirp_pcm, make_frames, sine_pcm
from speech.codec.benchmark import run_benchmark
from speech.codec.mimi_bridge import MimiCodecBridge, make_codec_bridge


def _bridge() -> MimiCodecBridge:
    return make_codec_bridge(backend="mock")


def test_bridge_selects_mock_without_weights():
    bridge = make_codec_bridge(backend="auto")
    # No Mimi weights in this environment -> auto must fall back to the mock backend.
    assert bridge.backend_name == "mock"
    assert bridge.is_real_backend is False


def test_roundtrip_is_recoverable():
    bridge = _bridge()
    pcm = sine_pcm(24000, freq=220.0, sample_rate=bridge.sample_rate)
    frames = list(make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate))
    err = bridge.roundtrip_error(frames)
    # 16-bit grid => worst-case error ~1.53e-5. Comfortably recoverable.
    assert err < 1e-3, f"roundtrip error too high: {err}"


def test_roundtrip_preserves_energy():
    bridge = _bridge()
    pcm = chirp_pcm(12000, sample_rate=bridge.sample_rate)
    frames = list(make_frames(pcm, frame_samples=512, sample_rate=bridge.sample_rate))
    out = bridge.roundtrip(frames)
    decoded: list[float] = []
    for f in out:
        decoded.extend(f.pcm)
    in_rms = rms(pcm)
    out_rms = rms(decoded[: len(pcm)])
    assert math.isclose(in_rms, out_rms, rel_tol=0.05), (in_rms, out_rms)


def test_resample_roundtrip_16k_to_24k():
    # Frames captured at 16 kHz must still roundtrip through the 24 kHz codec.
    bridge = _bridge()
    pcm = sine_pcm(16000, freq=180.0, sample_rate=16000)
    frames = list(make_frames(pcm, frame_samples=320, sample_rate=16000))
    out = bridge.roundtrip(frames)
    assert out, "expected decoded frames"
    assert all(f.sample_rate == bridge.sample_rate for f in out)


def test_chunk_sequencing_monotonic_and_final():
    bridge = _bridge()
    pcm = sine_pcm(10000, sample_rate=bridge.sample_rate)
    frames = list(make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate))
    chunks = list(bridge.encode(iter(frames)))
    assert chunks, "expected codec chunks"
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].is_final is True
    assert all(not c.is_final for c in chunks[:-1])


def test_benchmark_report_structure_and_bounds():
    report = run_benchmark(backend="mock", seconds=0.5)
    assert report["backend"] == "mock"
    rt = report["roundtrip_latency"]
    assert rt["recoverable"] is True
    assert rt["n_chunks"] >= 1
    assert rt["ttfc_ms"] >= 0.0
    stability = report["chunk_boundary_stability"]
    assert stability["stable_across_framing"] is True
    assert stability["boundaries_uniform"] is True
    jitter = report["jitter_sensitivity"]
    assert jitter["no_loss"] is True
    assert jitter["order_preserved"] is True
