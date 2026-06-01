"""
aux/stt/transcript_service.py — Auxiliary STT / transcript service (Phase 7A)
=============================================================================
faster-whisper (and/or IndicConformer) utilities for **transcripts, logs,
search, and moderation review**.

Design contract (final_use.md §Phase-7A):
  * Transcripts are an *auxiliary* artifact. They power logging, retrieval, and
    moderation review — they are NOT in the speech-native hot path.
  * Transcription MUST run **asynchronously** and MUST NOT block the main voice
    loop. We provide an async API plus a background worker queue so callers can
    fire-and-forget and collect results later.

CPU / no-weights rule:
  * faster-whisper is imported lazily inside the backend. If it (or its weights)
    are unavailable — the default on a CPU-only box — we fall back to a
    deterministic stub backend so the module imports and tests run anywhere.

This mirrors the patterns in ``server/pipeline/stt.py`` (``TranscriptionResult``,
auto language detection, lazy model load) without importing or mutating it.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from auxiliary.text_brain.obs import get_logger, telemetry

logger = get_logger(__name__)

# Whisper works best at 16 kHz mono (see server/utils/audio.py SAMPLE_RATE_16K).
SAMPLE_RATE_16K = 16000


# ---------------------------------------------------------------------------
# Result + job types
# ---------------------------------------------------------------------------
@dataclass
class TranscriptResult:
    """Result of an auxiliary transcription.

    Shape intentionally parallels ``server.pipeline.stt.TranscriptionResult`` so
    downstream consumers (logging, retrieval, moderation) treat both the same.
    """

    text: str
    language: str
    language_probability: float
    duration: float
    processing_time: float
    segments: list[dict] = field(default_factory=list)
    backend: str = "stub"
    is_stub: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "processing_time": self.processing_time,
            "segments": self.segments,
            "backend": self.backend,
            "is_stub": self.is_stub,
        }


class JobStatus(str, Enum):
    """Lifecycle of a queued transcription job."""

    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class TranscriptJob:
    """A unit of background transcription work."""

    job_id: str
    pcm_bytes: bytes
    sample_rate: int
    language: str | None
    purpose: str  # "log" | "search" | "moderation_review" | "fallback"
    status: JobStatus = JobStatus.queued
    result: TranscriptResult | None = None
    error: str | None = None
    enqueued_ms: int = field(default_factory=lambda: int(time.time() * 1000))


# ---------------------------------------------------------------------------
# Backend protocol + implementations
# ---------------------------------------------------------------------------
class TranscriberBackend(Protocol):
    """Pluggable transcription backend (sync compute, run off the event loop)."""

    name: str

    def transcribe(
        self, audio_f32: list[float], sample_rate: int, language: str | None
    ) -> TranscriptResult: ...


def _detect_language_from_bytes_len(text: str) -> str:
    """Tiny heuristic mirroring server EdgeTTS.detect_language for Devanagari."""
    hindi_chars = sum(1 for c in text if "\u0900" <= c <= "\u097f")
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha == 0:
        return "en"
    return "hi" if (hindi_chars / total_alpha) > 0.3 else "en"


class StubTranscriber:
    """Deterministic, dependency-free transcription backend.

    Produces a stable, content-derived placeholder transcript. This keeps the
    auxiliary path fully functional on CPU-only machines with no whisper weights,
    so logging / moderation review / tests never block on model availability.
    """

    name = "stub"

    def transcribe(
        self, audio_f32: list[float], sample_rate: int, language: str | None
    ) -> TranscriptResult:
        start = time.perf_counter()
        n = len(audio_f32)
        duration = round(n / sample_rate, 3) if sample_rate else 0.0
        # Deterministic placeholder text derived only from input shape.
        text = f"[stub-transcript samples={n} sr={sample_rate}]"
        lang = language or "en"
        return TranscriptResult(
            text=text,
            language=lang,
            language_probability=0.0,
            duration=duration,
            processing_time=round(time.perf_counter() - start, 6),
            segments=[{"start": 0.0, "end": duration, "text": text}],
            backend=self.name,
            is_stub=True,
        )


class FasterWhisperTranscriber:
    """Lazy faster-whisper backend.

    The model is loaded on first use and cached. Compute runs synchronously and is
    dispatched to a worker thread by the service so the event loop never blocks.
    Falls back to the stub at construction time if faster-whisper is unavailable.
    """

    name = "faster-whisper"

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel  # noqa: PLC0415 (lazy/optional)

        logger.info(
            "aux_stt_loading_model",
            model_size=self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        self._model = WhisperModel(
            self._model_size, device=self._device, compute_type=self._compute_type
        )

    def transcribe(
        self, audio_f32: list[float], sample_rate: int, language: str | None
    ) -> TranscriptResult:
        self._ensure_model()
        import numpy as np  # noqa: PLC0415 (lazy/optional)

        start = time.perf_counter()
        audio = np.asarray(audio_f32, dtype=np.float32)
        segments_iter, info = self._model.transcribe(
            audio, beam_size=5, language=language, vad_filter=False
        )
        segments: list[dict] = []
        parts: list[str] = []
        for seg in segments_iter:
            segments.append(
                {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
            )
            parts.append(seg.text.strip())
        text = " ".join(parts).strip()
        return TranscriptResult(
            text=text,
            language=info.language,
            language_probability=round(info.language_probability, 3),
            duration=round(len(audio) / sample_rate, 3),
            processing_time=round(time.perf_counter() - start, 3),
            segments=segments,
            backend=self.name,
            is_stub=False,
        )


def make_backend(prefer_whisper: bool = True, **whisper_kwargs: Any) -> TranscriberBackend:
    """Construct the best available backend, falling back to the stub on CPU.

    Returns a :class:`StubTranscriber` whenever faster-whisper (or its runtime
    dependency numpy) is not importable, so the service is always usable.
    """
    if not prefer_whisper:
        return StubTranscriber()
    try:
        import importlib.util

        if importlib.util.find_spec("faster_whisper") is None:
            raise ImportError("faster_whisper not installed")
        if importlib.util.find_spec("numpy") is None:
            raise ImportError("numpy not installed")
        return FasterWhisperTranscriber(**whisper_kwargs)
    except Exception as e:  # pragma: no cover - depends on environment
        logger.warning("aux_stt_backend_fallback_to_stub", error=str(e))
        return StubTranscriber()


# ---------------------------------------------------------------------------
# Async transcript service with background worker queue
# ---------------------------------------------------------------------------
def _pcm16_bytes_to_float32(pcm_bytes: bytes) -> list[float]:
    """Convert 16-bit PCM bytes to float32 samples in [-1, 1] without numpy.

    Mirrors ``server.utils.audio.pcm_to_float32`` but stays numpy-free so the
    auxiliary path imports on a bare CPU box.
    """
    import array

    samples = array.array("h")  # signed 16-bit
    # Drop a trailing odd byte if present (defensive).
    usable = pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % 2)]
    samples.frombytes(usable)
    return [s / 32768.0 for s in samples]


class TranscriptService:
    """Async, non-blocking transcript service.

    Two ways to use it:
      * ``await transcribe(...)`` — awaitable single transcription; the (sync)
        model compute is dispatched to a thread via ``asyncio.to_thread`` so the
        event loop is never blocked.
      * ``await submit(...)`` + ``await result(job_id)`` — enqueue a
        fire-and-forget job onto a background worker queue (for transcripts that
        feed logs / search / moderation review off the hot path).

    Start/stop the background workers with ``await start()`` / ``await stop()``,
    or use ``async with TranscriptService() as svc:``.
    """

    def __init__(
        self,
        backend: TranscriberBackend | None = None,
        *,
        workers: int = 1,
        prefer_whisper: bool = True,
    ) -> None:
        self._backend = backend or make_backend(prefer_whisper=prefer_whisper)
        self._n_workers = max(1, workers)
        self._queue: asyncio.Queue[TranscriptJob | None] = asyncio.Queue()
        self._jobs: dict[str, TranscriptJob] = {}
        self._results: dict[str, asyncio.Future] = {}
        self._workers: list[asyncio.Task] = []
        self._running = False

    @property
    def backend_name(self) -> str:
        return self._backend.name

    # -- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._workers = [loop.create_task(self._worker(i)) for i in range(self._n_workers)]
        logger.info("aux_stt_service_started", workers=self._n_workers, backend=self.backend_name)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # Send one sentinel per worker so each loop exits cleanly.
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("aux_stt_service_stopped")

    async def __aenter__(self) -> TranscriptService:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    # -- direct (awaitable) transcription -----------------------------------
    async def transcribe(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate: int = SAMPLE_RATE_16K,
        language: str | None = None,
        purpose: str = "log",
    ) -> TranscriptResult:
        """Transcribe PCM16 bytes without blocking the event loop.

        The synchronous model compute is run in a worker thread.
        """
        audio_f32 = _pcm16_bytes_to_float32(pcm_bytes)
        result = await asyncio.to_thread(self._backend.transcribe, audio_f32, sample_rate, language)
        telemetry.record(
            "aux_transcript",
            purpose=purpose,
            backend=result.backend,
            is_stub=result.is_stub,
            duration=result.duration,
            processing_time=result.processing_time,
        )
        logger.info(
            "aux_transcript_complete",
            purpose=purpose,
            backend=result.backend,
            chars=len(result.text),
            language=result.language,
        )
        return result

    # -- queued (fire-and-forget) transcription -----------------------------
    async def submit(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate: int = SAMPLE_RATE_16K,
        language: str | None = None,
        purpose: str = "log",
    ) -> str:
        """Enqueue a background transcription job; returns a job id immediately."""
        if not self._running:
            raise RuntimeError("TranscriptService not started. Call await start() first.")
        job = TranscriptJob(
            job_id=uuid.uuid4().hex,
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            language=language,
            purpose=purpose,
        )
        self._jobs[job.job_id] = job
        self._results[job.job_id] = asyncio.get_event_loop().create_future()
        await self._queue.put(job)
        telemetry.record("aux_transcript_submitted", job_id=job.job_id, purpose=purpose)
        return job.job_id

    def job(self, job_id: str) -> TranscriptJob | None:
        return self._jobs.get(job_id)

    async def result(self, job_id: str, timeout: float | None = None) -> TranscriptResult:
        """Await the result of a previously submitted job."""
        fut = self._results.get(job_id)
        if fut is None:
            raise KeyError(f"unknown job_id: {job_id}")
        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)

    async def drain(self, timeout: float | None = None) -> None:
        """Wait until all queued jobs have been processed."""
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _worker(self, idx: int) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            job.status = JobStatus.running
            try:
                audio_f32 = _pcm16_bytes_to_float32(job.pcm_bytes)
                result = await asyncio.to_thread(
                    self._backend.transcribe, audio_f32, job.sample_rate, job.language
                )
                job.result = result
                job.status = JobStatus.done
                fut = self._results.get(job.job_id)
                if fut is not None and not fut.done():
                    fut.set_result(result)
                telemetry.record(
                    "aux_transcript_job_done",
                    job_id=job.job_id,
                    worker=idx,
                    backend=result.backend,
                    purpose=job.purpose,
                )
            except Exception as e:  # pragma: no cover - defensive
                job.status = JobStatus.failed
                job.error = str(e)
                fut = self._results.get(job.job_id)
                if fut is not None and not fut.done():
                    fut.set_exception(e)
                logger.error("aux_transcript_job_failed", job_id=job.job_id, error=str(e))
            finally:
                self._queue.task_done()


# ---------------------------------------------------------------------------
# Convenience: one-shot transcription without managing a service lifecycle
# ---------------------------------------------------------------------------
async def transcribe_once(
    pcm_bytes: bytes,
    *,
    sample_rate: int = SAMPLE_RATE_16K,
    language: str | None = None,
    prefer_whisper: bool = True,
) -> TranscriptResult:
    """Transcribe a single buffer with a transient backend (no workers)."""
    svc = TranscriptService(prefer_whisper=prefer_whisper)
    return await svc.transcribe(pcm_bytes, sample_rate=sample_rate, language=language)


# Optional async callback hook type for integrators (e.g. moderation review).
TranscriptCallback = Callable[[TranscriptResult], Awaitable[None]]
