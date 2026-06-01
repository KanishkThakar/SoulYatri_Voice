"""
Tests for aux/text_brain (Phase 7B + 7C).

Covers:
  * contract construction + JSON round-trip,
  * deterministic stub brain output per task,
  * service output-schema conformance with use_ollama=False (stub path),
  * timeout fallback produces a valid degraded response (no exception),
  * async support jobs complete and emit MemoryWrite for memory_summary.
"""

from __future__ import annotations

import asyncio

from auxiliary.tests.conftest import run_async
from auxiliary.text_brain.contracts import (
    DEFAULT_TOOLS,
    TextBrainRequest,
    TextBrainResponse,
    TextBrainTask,
    ToolCall,
)
from auxiliary.text_brain.jobs import JobState, SupportJobRunner
from auxiliary.text_brain.service import StubTextBrain, TextBrainService, run_task
from shared.contracts import MemoryKind, MemoryWrite


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
def test_request_roundtrip() -> None:
    req = TextBrainRequest(task=TextBrainTask.memory_summary, payload={"turns": ["hi"]})
    rebuilt = TextBrainRequest.model_validate_json(req.model_dump_json())
    assert rebuilt == req


def test_response_roundtrip() -> None:
    resp = TextBrainResponse(
        task=TextBrainTask.tool_plan,
        tool_calls=[ToolCall(tool="time_now", arguments={}, reason="x")],
    )
    rebuilt = TextBrainResponse.model_validate_json(resp.model_dump_json())
    assert rebuilt == resp


# ---------------------------------------------------------------------------
# Stub brain
# ---------------------------------------------------------------------------
def test_stub_memory_summary() -> None:
    brain = StubTextBrain()
    resp = brain.generate(
        TextBrainRequest(task=TextBrainTask.memory_summary, payload={"turns": ["a", "b", "c"]}),
        DEFAULT_TOOLS,
    )
    assert resp.summary
    assert "3 turns" in resp.summary


def test_stub_tool_plan_detects_time() -> None:
    brain = StubTextBrain()
    resp = brain.generate(
        TextBrainRequest(task=TextBrainTask.tool_plan, payload={"query": "what time is it?"}),
        DEFAULT_TOOLS,
    )
    assert any(c.tool == "time_now" for c in resp.tool_calls)


def test_stub_rag_query() -> None:
    brain = StubTextBrain()
    resp = brain.generate(
        TextBrainRequest(
            task=TextBrainTask.rag_query,
            payload={"utterance": "tell me about my favourite restaurant booking"},
        ),
        DEFAULT_TOOLS,
    )
    assert 1 <= len(resp.rag_queries) <= 3


def test_stub_dataset_label_distress() -> None:
    brain = StubTextBrain()
    resp = brain.generate(
        TextBrainRequest(task=TextBrainTask.dataset_label, payload={"text": "I feel so alone"}),
        DEFAULT_TOOLS,
    )
    assert "distress" in resp.labels


# ---------------------------------------------------------------------------
# Service — stub path (no Ollama), schema conformance
# ---------------------------------------------------------------------------
def test_service_stub_path_schema() -> None:
    async def go() -> TextBrainResponse:
        svc = TextBrainService(use_ollama=False)
        try:
            return await svc.run(
                TextBrainRequest(task=TextBrainTask.memory_summary, payload={"turns": ["hi"]})
            )
        finally:
            await svc.close()

    resp = run_async(go())
    assert isinstance(resp, TextBrainResponse)
    assert resp.degraded is True  # stub path is a degraded response
    assert resp.summary
    assert resp.latency_ms >= 0
    # Must still be schema-valid / round-trippable.
    TextBrainResponse.model_validate_json(resp.model_dump_json())


def test_run_task_helper() -> None:
    resp = run_async(
        run_task(
            "rag_query",
            {"utterance": "what's the weather like in mumbai tomorrow"},
            use_ollama=False,
        )
    )
    assert resp.task is TextBrainTask.rag_query
    assert resp.degraded is True
    assert len(resp.rag_queries) >= 1


# ---------------------------------------------------------------------------
# Timeout fallback — core 7B acceptance criterion
# ---------------------------------------------------------------------------
def test_timeout_falls_back_to_stub() -> None:
    """If the Ollama call exceeds the request timeout, we degrade gracefully."""

    class SlowService(TextBrainService):
        async def _call_ollama(self, request):  # type: ignore[no-untyped-def]
            await asyncio.sleep(5.0)  # far exceeds the tiny timeout below
            return "never returned"

    async def go() -> TextBrainResponse:
        svc = SlowService(use_ollama=True)
        try:
            return await svc.run(
                TextBrainRequest(
                    task=TextBrainTask.memory_summary,
                    payload={"turns": ["x"]},
                    timeout_s=0.05,
                )
            )
        finally:
            await svc.close()

    resp = run_async(go())
    assert resp.degraded is True
    assert resp.reason == "timeout"
    assert resp.summary  # stub still produced valid content


def test_client_error_falls_back_to_stub() -> None:
    """Any client exception degrades to a valid stub response (no raise)."""

    class BrokenService(TextBrainService):
        async def _call_ollama(self, request):  # type: ignore[no-untyped-def]
            raise ConnectionError("ollama unreachable")

    async def go() -> TextBrainResponse:
        svc = BrokenService(use_ollama=True)
        try:
            return await svc.run(
                TextBrainRequest(task=TextBrainTask.tool_plan, payload={"query": "time now"})
            )
        finally:
            await svc.close()

    resp = run_async(go())
    assert resp.degraded is True
    assert resp.reason.startswith("fallback:")
    assert resp.task is TextBrainTask.tool_plan


# ---------------------------------------------------------------------------
# Async support jobs (7C)
# ---------------------------------------------------------------------------
def test_support_jobs_complete() -> None:
    async def go() -> tuple[JobState, MemoryWrite | None]:
        async with SupportJobRunner(use_ollama=False, workers=2) as runner:
            job_id = await runner.compress_memory(
                ["I prefer Hinglish", "Book a table at 8pm"], session_id="s1"
            )
            job = await runner.result(job_id, timeout=5.0)
            return job.state, job.memory_write

    state, mw = run_async(go())
    assert state is JobState.done
    assert isinstance(mw, MemoryWrite)
    assert mw.kind is MemoryKind.turn_summary
    assert mw.session_id == "s1"
    assert "summary" in mw.content


def test_support_jobs_drain_many() -> None:
    async def go() -> int:
        async with SupportJobRunner(use_ollama=False, workers=3) as runner:
            for i in range(8):
                await runner.clean_transcript(f"  raw transcript number {i}  ")
            await runner.drain(timeout=10.0)
            return runner.pending

    assert run_async(go()) == 0


def test_support_jobs_no_memory_write_without_session() -> None:
    async def go():  # type: ignore[no-untyped-def]
        async with SupportJobRunner(use_ollama=False) as runner:
            job_id = await runner.compress_memory(["a", "b"])  # no session_id
            return await runner.result(job_id, timeout=5.0)

    job = run_async(go())
    assert job.memory_write is None
    assert job.response is not None and job.response.summary
