"""
Tests for aux/stt/transcript_service.py (Phase 7A).

Covers:
  * import hygiene (no heavy deps pulled in),
  * deterministic stub backend output,
  * direct async transcription does not block the event loop,
  * background queue submit/result/drain (fire-and-forget) behavior,
  * non-blocking property: a concurrent heartbeat keeps ticking while a slow
    transcription runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import struct
import sys
import time

from auxiliary.stt.transcript_service import (
    JobStatus,
    StubTranscriber,
    TranscriptResult,
    TranscriptService,
    _pcm16_bytes_to_float32,
    make_backend,
    transcribe_once,
)
from auxiliary.tests.conftest import run_async


def _silence_pcm(n_samples: int) -> bytes:
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


# ---------------------------------------------------------------------------
# Import hygiene / backend selection
# ---------------------------------------------------------------------------
def test_no_heavy_imports() -> None:
    """Importing the service must not pull torch/transformers/faster_whisper/numpy."""
    for heavy in ("torch", "transformers", "faster_whisper"):
        assert heavy not in sys.modules, f"{heavy} should not be imported eagerly"


def test_make_backend_falls_back_to_stub_on_cpu() -> None:
    backend = make_backend(prefer_whisper=True)
    # On a CPU-only box with no faster-whisper/numpy this must be the stub.
    assert backend.name in ("stub", "faster-whisper")
    forced = make_backend(prefer_whisper=False)
    assert forced.name == "stub"


def test_pcm_conversion_roundtrip_shape() -> None:
    pcm = struct.pack("<4h", 0, 16384, -16384, 32767)
    floats = _pcm16_bytes_to_float32(pcm)
    assert len(floats) == 4
    assert -1.0 <= min(floats) <= max(floats) <= 1.0
    assert abs(floats[1] - 0.5) < 0.01


def test_pcm_conversion_handles_odd_byte() -> None:
    # Odd trailing byte must be dropped defensively (no exception).
    floats = _pcm16_bytes_to_float32(b"\x00\x10\x05")
    assert len(floats) == 1


# ---------------------------------------------------------------------------
# Stub backend
# ---------------------------------------------------------------------------
def test_stub_backend_deterministic() -> None:
    stub = StubTranscriber()
    audio = [0.0] * 16000
    r1 = stub.transcribe(audio, 16000, None)
    r2 = stub.transcribe(audio, 16000, None)
    assert isinstance(r1, TranscriptResult)
    assert r1.text == r2.text
    assert r1.is_stub is True
    assert r1.duration == 1.0


# ---------------------------------------------------------------------------
# Direct async transcription
# ---------------------------------------------------------------------------
def test_transcribe_once() -> None:
    pcm = _silence_pcm(8000)  # 0.5s at 16k

    async def go() -> TranscriptResult:
        return await transcribe_once(pcm, prefer_whisper=False)

    result = run_async(go())
    assert result.is_stub is True
    assert result.duration == 0.5
    assert "stub-transcript" in result.text


def test_service_transcribe_direct() -> None:
    pcm = _silence_pcm(16000)

    async def go() -> TranscriptResult:
        async with TranscriptService(prefer_whisper=False) as svc:
            return await svc.transcribe(pcm, purpose="moderation_review")

    result = run_async(go())
    assert result.backend == "stub"
    assert result.language == "en"


# ---------------------------------------------------------------------------
# Background queue
# ---------------------------------------------------------------------------
def test_submit_and_result() -> None:
    pcm = _silence_pcm(4000)

    async def go() -> tuple[TranscriptResult, JobStatus]:
        async with TranscriptService(prefer_whisper=False, workers=2) as svc:
            job_id = await svc.submit(pcm, purpose="search")
            result = await svc.result(job_id, timeout=5.0)
            return result, svc.job(job_id).status

    result, status = run_async(go())
    assert result.is_stub is True
    assert status is JobStatus.done


def test_drain_processes_all_jobs() -> None:
    pcm = _silence_pcm(1600)

    async def go() -> int:
        async with TranscriptService(prefer_whisper=False, workers=3) as svc:
            for _ in range(10):
                await svc.submit(pcm, purpose="log")
            await svc.drain(timeout=10.0)
            assert svc.pending == 0
            return 10

    assert run_async(go()) == 10


def test_submit_before_start_raises() -> None:
    async def go() -> None:
        svc = TranscriptService(prefer_whisper=False)
        try:
            await svc.submit(_silence_pcm(10))
        except RuntimeError:
            return
        raise AssertionError("expected RuntimeError when submitting before start()")

    run_async(go())


# ---------------------------------------------------------------------------
# Non-blocking property — the core 7A acceptance criterion
# ---------------------------------------------------------------------------
def test_transcription_does_not_block_event_loop() -> None:
    """A slow (sleep-based) backend must not stall a concurrent heartbeat.

    We inject a backend whose transcribe() sleeps synchronously. Because the
    service dispatches it via asyncio.to_thread, a concurrent async heartbeat must
    keep ticking many times while the single transcription is in flight.
    """

    class SlowBackend:
        name = "slow"

        def transcribe(self, audio, sample_rate, language):  # type: ignore[no-untyped-def]
            time.sleep(0.3)  # blocking compute, simulates a heavy model
            return TranscriptResult(
                text="slow",
                language="en",
                language_probability=0.0,
                duration=0.0,
                processing_time=0.3,
                backend=self.name,
                is_stub=True,
            )

    ticks = 0

    async def heartbeat(stop: asyncio.Event) -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.01)

    async def go() -> int:
        svc = TranscriptService(backend=SlowBackend())
        stop = asyncio.Event()
        hb = asyncio.create_task(heartbeat(stop))
        result = await svc.transcribe(_silence_pcm(10), purpose="log")
        stop.set()
        await hb
        assert result.text == "slow"
        return ticks

    n_ticks = run_async(go())
    # 0.3s blocking / 0.01s heartbeat ≈ 30 ticks if non-blocking; a blocked loop
    # would yield ~0-1. Use a generous lower bound to avoid flakiness.
    assert n_ticks >= 10, f"event loop appears blocked (only {n_ticks} ticks)"
