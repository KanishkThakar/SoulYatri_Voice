"""Phase 10 tests — decoder streaming (first-chunk-fast), smooth joins, interruption.

Acceptance: first chunk arrives quickly; playback is smooth; output stops within budget on
interruption. All on the mock codec (CPU, no weights).
"""

from __future__ import annotations

import asyncio

from shared.contracts import CodecChunk
from speech.codec._dsp import peak
from speech.codec._signal import make_frames, sine_pcm
from speech.codec.mimi_bridge import make_codec_bridge
from speech.decoder.interruption import (
    PlaybackInterruptionController,
    StopPolicy,
)
from speech.decoder.service import DecoderConfig, DecoderRequest, make_decoder
from speech.decoder.waveform import WaveformJoiner, decode_chunks_to_pcm


def _encoded_chunks(seconds: float = 0.5):
    bridge = make_codec_bridge(backend="mock")
    pcm = sine_pcm(int(bridge.sample_rate * seconds), freq=200.0, sample_rate=bridge.sample_rate)
    frames = list(make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate))
    return bridge, list(bridge.encode(iter(frames)))


def test_decoder_request_roundtrip():
    decoder = make_decoder()
    req = DecoderRequest(turn_id="t1", codec_tokens=[30000, 31000, 32000], sample_rate=24000)
    frame = decoder.decode_request(req)
    assert frame.sample_rate == 24000
    assert len(frame.pcm) == 3
    assert frame.is_final is True


def test_decode_all_smooth_join_no_huge_artifact():
    bridge, chunks = _encoded_chunks(0.3)
    decoder = make_decoder(bridge=bridge)
    frames = decoder.decode_all(chunks)
    assert frames, "expected decoded frames"
    assert frames[-1].is_final is True
    # Concatenate and confirm no wild out-of-range artifact at joins.
    pcm = []
    for f in frames:
        pcm.extend(f.pcm)
    assert peak(pcm) <= 1.01


def test_waveform_joiner_crossfade_continuity():
    # Two chunks decoded and joined should not introduce a step discontinuity larger
    # than the source signal's own peak at the seam.
    bridge, chunks = _encoded_chunks(0.2)
    joined = decode_chunks_to_pcm(chunks, bridge=bridge)
    assert joined
    # Max absolute first difference should stay bounded (smooth sine, smooth joins).
    max_step = max(abs(joined[i + 1] - joined[i]) for i in range(len(joined) - 1))
    assert max_step < 0.2, f"join discontinuity too large: {max_step}"


def test_cache_hit_on_repeated_chunk():
    decoder = make_decoder(config=DecoderConfig(cache_size=8))
    chunk = CodecChunk(turn_id="t", seq=0, codec_tokens=[10000] * 100, is_final=True)
    decoder._decode_cached(chunk)
    decoder._decode_cached(chunk)
    stats = decoder.stats()
    assert stats["cache_hits"] >= 1


def test_streaming_first_chunk_fast_and_complete():
    async def scenario():
        bridge, chunks = _encoded_chunks(0.5)
        decoder = make_decoder(bridge=bridge)

        async def feed():
            for c in chunks:
                yield c

        out = []
        async for frame in decoder.stream_decode(feed(), session_id="s1"):
            out.append(frame)
        return out

    out = asyncio.run(scenario())
    assert out, "expected streamed frames"
    assert out[-1].is_final is True
    # First playable frame should arrive before the whole turn is decoded.
    assert len(out) >= 2


def test_streaming_stops_on_interruption():
    async def scenario():
        bridge, chunks = _encoded_chunks(1.0)
        decoder = make_decoder(bridge=bridge)

        async def feed():
            for c in chunks:
                await asyncio.sleep(0.005)
                yield c

        out = []

        async def consume():
            async for frame in decoder.stream_decode(feed(), session_id="s2"):
                out.append(frame)

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0.02)
        result = decoder.interrupt([0.5] * 480, policy=StopPolicy.fade)
        await asyncio.wait_for(task, timeout=2.0)
        return out, result, len(chunks)

    out, result, n_chunks = asyncio.run(scenario())
    assert result.interrupted is True
    assert result.within_budget is True
    # Stopped early: fewer frames than total input chunks.
    assert len(out) < n_chunks


def test_interruption_fade_within_budget():
    ctrl = PlaybackInterruptionController(sample_rate=24000, stop_budget_ms=50, fade_ms=20)
    pending = [0.8] * 4800  # 200 ms of audio
    result = ctrl.interrupt(pending, policy=StopPolicy.fade)
    assert result.policy is StopPolicy.fade
    assert result.client_action == "fade"
    assert result.within_budget is True
    # Faded head must end at (near) zero amplitude for a clean stop.
    assert abs(result.final_pcm[-1]) < 1e-6
    # Most of the pending audio is discarded.
    assert result.discarded_samples > result.played_samples


def test_interruption_hard_cut_discards_all():
    ctrl = PlaybackInterruptionController(sample_rate=24000)
    pending = [0.8] * 1000
    result = ctrl.interrupt(pending, policy=StopPolicy.hard_cut)
    assert result.policy is StopPolicy.hard_cut
    assert result.client_action == "flush"
    assert result.played_samples == 0
    assert result.discarded_samples == 1000
    assert result.within_budget is True


def test_waveform_joiner_stats():
    bridge, chunks = _encoded_chunks(0.2)
    joiner = WaveformJoiner(bridge)
    for c in chunks:
        joiner.push(c)
    stats = joiner.stats()
    assert stats["chunks_seen"] == len(chunks)
    assert stats["emitted_samples"] > 0
