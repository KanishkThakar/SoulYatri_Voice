"""
aux/text_brain/jobs.py — Async support jobs (Phase 7C)
======================================================
Background workers for auxiliary text work that must complete **without affecting
voice latency** (final_use.md §Phase-7C):

  * memory compression       (-> MemoryWrite turn_summary)
  * transcript cleanup
  * RAG query preparation
  * moderation summaries
  * dataset labeling

Everything here runs on a background ``asyncio`` worker pool fed by a queue, so the
hot speech path is never blocked. Jobs use :class:`TextBrainService`, which itself
degrades to a deterministic stub when no model is available.

Outputs that belong in tiered memory are emitted as ``shared.contracts.MemoryWrite``
objects (the memory subsystem owns persistence — Phase 12).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from auxiliary.text_brain.contracts import TextBrainRequest, TextBrainResponse, TextBrainTask
from auxiliary.text_brain.obs import get_logger, telemetry
from auxiliary.text_brain.service import TextBrainService
from shared.contracts import MemoryKind, MemoryWrite

logger = get_logger(__name__)


class JobState(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class SupportJob:
    """A queued auxiliary text job."""

    job_id: str
    task: TextBrainTask
    payload: dict
    session_id: str | None = None
    state: JobState = JobState.queued
    response: TextBrainResponse | None = None
    memory_write: MemoryWrite | None = None
    error: str | None = None
    enqueued_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    started_ms: int | None = None
    finished_ms: int | None = None

    @property
    def latency_ms(self) -> int | None:
        if self.started_ms is not None and self.finished_ms is not None:
            return self.finished_ms - self.started_ms
        return None


class SupportJobRunner:
    """An async worker pool for auxiliary text jobs.

    Jobs are submitted with :meth:`submit` (returns immediately with a job id) and
    processed by background workers. Use :meth:`await result(job_id)` to collect a
    finished job, or :meth:`await drain()` to wait for the queue to empty.
    """

    def __init__(
        self,
        service: TextBrainService | None = None,
        *,
        workers: int = 2,
        use_ollama: bool = True,
    ) -> None:
        self._service = service or TextBrainService(use_ollama=use_ollama)
        self._n_workers = max(1, workers)
        self._queue: asyncio.Queue[SupportJob | None] = asyncio.Queue()
        self._jobs: dict[str, SupportJob] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._workers: list[asyncio.Task] = []
        self._running = False

    # -- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        loop = asyncio.get_event_loop()
        self._workers = [loop.create_task(self._worker(i)) for i in range(self._n_workers)]
        logger.info("aux_jobs_started", workers=self._n_workers)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        await self._service.close()
        logger.info("aux_jobs_stopped")

    async def __aenter__(self) -> SupportJobRunner:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    # -- submission ---------------------------------------------------------
    async def submit(
        self,
        task: TextBrainTask | str,
        payload: dict,
        *,
        session_id: str | None = None,
    ) -> str:
        if not self._running:
            raise RuntimeError("SupportJobRunner not started. Call await start() first.")
        if isinstance(task, str):
            task = TextBrainTask(task)
        job = SupportJob(job_id=uuid.uuid4().hex, task=task, payload=payload, session_id=session_id)
        self._jobs[job.job_id] = job
        self._futures[job.job_id] = asyncio.get_event_loop().create_future()
        await self._queue.put(job)
        telemetry.record("aux_job_submitted", job_id=job.job_id, task=task.value)
        return job.job_id

    # Ergonomic wrappers for the five named job kinds (final_use.md §7C).
    async def compress_memory(self, turns: list[str], *, session_id: str | None = None) -> str:
        return await self.submit(
            TextBrainTask.memory_summary, {"turns": turns}, session_id=session_id
        )

    async def clean_transcript(self, text: str, *, session_id: str | None = None) -> str:
        return await self.submit(
            TextBrainTask.transcript_cleanup, {"text": text}, session_id=session_id
        )

    async def prepare_rag_query(self, utterance: str, *, session_id: str | None = None) -> str:
        return await self.submit(
            TextBrainTask.rag_query, {"utterance": utterance}, session_id=session_id
        )

    async def summarize_moderation(
        self, events: list[str], *, session_id: str | None = None
    ) -> str:
        return await self.submit(
            TextBrainTask.moderation_summary, {"events": events}, session_id=session_id
        )

    async def label_sample(
        self, text: str, labels: list[str] | None = None, *, session_id: str | None = None
    ) -> str:
        payload: dict[str, Any] = {"text": text}
        if labels is not None:
            payload["labels"] = labels
        return await self.submit(TextBrainTask.dataset_label, payload, session_id=session_id)

    # -- results ------------------------------------------------------------
    def job(self, job_id: str) -> SupportJob | None:
        return self._jobs.get(job_id)

    async def result(self, job_id: str, timeout: float | None = None) -> SupportJob:
        fut = self._futures.get(job_id)
        if fut is None:
            raise KeyError(f"unknown job_id: {job_id}")
        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)

    async def drain(self, timeout: float | None = None) -> None:
        await asyncio.wait_for(self._queue.join(), timeout=timeout)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # -- worker -------------------------------------------------------------
    async def _worker(self, idx: int) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            job.state = JobState.running
            job.started_ms = int(time.time() * 1000)
            try:
                req = TextBrainRequest(
                    task=job.task, payload=job.payload, session_id=job.session_id
                )
                resp = await self._service.run(req)
                job.response = resp
                job.memory_write = _maybe_memory_write(job, resp)
                job.state = JobState.done
                job.finished_ms = int(time.time() * 1000)
                fut = self._futures.get(job.job_id)
                if fut is not None and not fut.done():
                    fut.set_result(job)
                telemetry.record(
                    "aux_job_done",
                    job_id=job.job_id,
                    worker=idx,
                    task=job.task.value,
                    degraded=resp.degraded,
                    latency_ms=job.latency_ms,
                )
            except Exception as e:  # pragma: no cover - defensive
                job.state = JobState.failed
                job.error = str(e)
                job.finished_ms = int(time.time() * 1000)
                fut = self._futures.get(job.job_id)
                if fut is not None and not fut.done():
                    fut.set_exception(e)
                logger.error("aux_job_failed", job_id=job.job_id, error=str(e))
            finally:
                self._queue.task_done()


def _maybe_memory_write(job: SupportJob, resp: TextBrainResponse) -> MemoryWrite | None:
    """Emit a MemoryWrite for job kinds that produce durable memory content."""
    if job.session_id is None:
        return None
    if job.task is TextBrainTask.memory_summary and resp.summary:
        return MemoryWrite(
            session_id=job.session_id,
            kind=MemoryKind.turn_summary,
            content={"summary": resp.summary, "degraded": resp.degraded},
        )
    return None
