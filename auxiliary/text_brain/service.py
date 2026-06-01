"""
aux/text_brain/service.py — Auxiliary text-brain service (Phase 7B)
===================================================================
Serving-mode interface over Qwen3 / Llama 3.3 (via Ollama, matching
``server/pipeline/llm.py`` and ``server/config.py``).

Responsibilities (final_use.md §Phase-7B):
  * a stable text-brain contract (``TextBrainRequest`` -> ``TextBrainResponse``),
  * prompts + tool schema + output schema,
  * per-request timeouts,
  * outputs deterministic enough for pipeline use.

Robustness rules:
  * The Ollama HTTP client is created **lazily**. There is no guaranteed live
    Ollama in this environment.
  * On timeout, connection failure, or any client error, we degrade to a
    **deterministic stub** that produces a valid ``TextBrainResponse`` with
    ``degraded=True`` — callers never crash and the schema is always honored.

This module wraps the *pattern* of ``server/pipeline/llm.py`` (Ollama chat,
streaming, persona/system prompt) without importing or mutating it, so the
auxiliary brain stays isolated from the voice runtime.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from auxiliary.text_brain.contracts import (
    DEFAULT_TOOLS,
    TextBrainRequest,
    TextBrainResponse,
    TextBrainTask,
    ToolCall,
    ToolSpec,
)
from auxiliary.text_brain.obs import get_logger, telemetry
from auxiliary.text_brain.prompts import build_messages

logger = get_logger(__name__)

# Defaults align with server/config.py OllamaSettings (env-overridable by callers).
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"


# ---------------------------------------------------------------------------
# Deterministic stub brain — used as the fallback (and for CPU-only tests)
# ---------------------------------------------------------------------------
class StubTextBrain:
    """Deterministic, dependency-free text-brain backend.

    Produces valid, schema-conformant responses derived only from the request, so
    the auxiliary path is always functional even with no Ollama / no weights.
    """

    model = "stub"

    def generate(self, req: TextBrainRequest, tools: list[ToolSpec]) -> TextBrainResponse:
        task = req.task
        payload = req.payload

        if task is TextBrainTask.memory_summary:
            turns = payload.get("turns", [])
            summary = self._summarize_turns(turns)
            return TextBrainResponse(task=task, summary=summary, text=summary, model=self.model)

        if task is TextBrainTask.tool_plan:
            calls = self._plan_tools(payload.get("query", ""), tools)
            return TextBrainResponse(task=task, tool_calls=calls, model=self.model)

        if task is TextBrainTask.moderation_summary:
            events = payload.get("events", [])
            summary = self._moderation_summary(events)
            return TextBrainResponse(task=task, summary=summary, text=summary, model=self.model)

        if task is TextBrainTask.rag_query:
            queries = self._rag_queries(payload.get("utterance", ""))
            return TextBrainResponse(task=task, rag_queries=queries, model=self.model)

        if task is TextBrainTask.transcript_cleanup:
            cleaned = self._cleanup(payload.get("text", ""))
            return TextBrainResponse(task=task, text=cleaned, model=self.model)

        if task is TextBrainTask.dataset_label:
            labels = self._label(
                payload.get("text", ""),
                payload.get("labels", ["warm_ack", "question", "distress", "smalltalk"]),
            )
            return TextBrainResponse(task=task, labels=labels, model=self.model)

        return TextBrainResponse(task=task, ok=False, reason="unknown_task", model=self.model)

    # -- deterministic heuristics ------------------------------------------
    @staticmethod
    def _summarize_turns(turns: list[Any]) -> str:
        if not turns:
            return "No conversation content to summarize."
        first = str(turns[0]).strip()
        last = str(turns[-1]).strip()
        if len(turns) == 1:
            return f"User discussed: {first[:160]}"
        return f"Conversation covered {len(turns)} turns from '{first[:60]}' to '{last[:60]}'."

    @staticmethod
    def _plan_tools(query: str, tools: list[ToolSpec]) -> list[ToolCall]:
        q = query.lower()
        names = {t.name for t in tools}
        calls: list[ToolCall] = []
        if ("time" in q or "clock" in q) and "time_now" in names:
            calls.append(ToolCall(tool="time_now", arguments={}, reason="query mentions time"))
        if ("remember" in q or "memory" in q or "recall" in q) and "memory_lookup" in names:
            calls.append(
                ToolCall(
                    tool="memory_lookup",
                    arguments={"query": query, "top_k": 5},
                    reason="query asks to recall information",
                )
            )
        return calls

    @staticmethod
    def _moderation_summary(events: list[Any]) -> str:
        if not events:
            return "No moderation-relevant events."
        joined = " ".join(str(e).lower() for e in events)
        flags = [k for k in ("self_harm", "abuse", "crisis", "harass") if k in joined]
        flag_note = f" Flags: {', '.join(flags)}." if flags else ""
        return f"{len(events)} moderation event(s) recorded for review.{flag_note}"

    @staticmethod
    def _rag_queries(utterance: str) -> list[str]:
        u = utterance.strip()
        if not u:
            return []
        words = [w for w in u.split() if len(w) > 3]
        base = " ".join(words[:6]) or u
        out = [base]
        if len(words) > 6:
            out.append(" ".join(words[:3]))
        return out[:3]

    @staticmethod
    def _cleanup(text: str) -> str:
        cleaned = " ".join(text.split()).strip()
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        if cleaned and cleaned[-1] not in ".?!":
            cleaned += "."
        return cleaned

    @staticmethod
    def _label(text: str, label_space: list[str]) -> list[str]:
        t = text.lower()
        if any(w in t for w in ("sad", "depress", "hurt", "alone")) and "distress" in label_space:
            return ["distress"]
        if "?" in text and "question" in label_space:
            return ["question"]
        if any(w in t for w in ("thanks", "ok", "acha", "great")) and "warm_ack" in label_space:
            return ["warm_ack"]
        return [label_space[0]] if label_space else []


# ---------------------------------------------------------------------------
# Output parsing for live-model responses
# ---------------------------------------------------------------------------
def _parse_tool_calls(text: str) -> list[ToolCall]:
    """Best-effort parse of a JSON tool-call array from model text."""
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        arr = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return []
    calls: list[ToolCall] = []
    for item in arr if isinstance(arr, list) else []:
        if isinstance(item, dict) and "tool" in item:
            calls.append(
                ToolCall(
                    tool=str(item["tool"]),
                    arguments=item.get("arguments", {}) or {},
                    reason=str(item.get("reason", "")),
                )
            )
    return calls


def _parse_labels(text: str) -> list[str]:
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        arr = json.loads(text[start:end])
        return [str(x) for x in arr] if isinstance(arr, list) else []
    except (ValueError, json.JSONDecodeError):
        return [w.strip() for w in text.replace("\n", ",").split(",") if w.strip()][:4]


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------
class TextBrainService:
    """Auxiliary text-brain serving interface (Ollama-backed, stub fallback).

    Use ``await run(request)`` to execute a task. The service:
      1. builds task-specific prompts,
      2. calls Ollama with a per-request timeout (lazy HTTP client),
      3. parses the output into the deterministic ``TextBrainResponse`` schema,
      4. degrades to :class:`StubTextBrain` on any failure or timeout.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        tools: list[ToolSpec] | None = None,
        use_ollama: bool = True,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._tools = tools if tools is not None else list(DEFAULT_TOOLS)
        self._use_ollama = use_ollama
        self._client: Any = None
        self._stub = StubTextBrain()

    @property
    def tools(self) -> list[ToolSpec]:
        return self._tools

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx  # noqa: PLC0415 (lazy/optional)

        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=httpx.Timeout(30.0, connect=5.0)
        )
        return self._client

    async def run(self, request: TextBrainRequest) -> TextBrainResponse:
        """Execute a text-brain task, honoring the request timeout."""
        start = time.perf_counter()

        if not self._use_ollama:
            return self._finish(self._stub_response(request), start, degraded=True)

        try:
            text = await asyncio.wait_for(self._call_ollama(request), timeout=request.timeout_s)
            resp = self._parse(request, text)
            telemetry.record(
                "aux_text_brain", task=request.task.value, model=self._model, degraded=False
            )
            return self._finish(resp, start, degraded=False, model=self._model)
        except asyncio.TimeoutError:
            logger.warning(
                "aux_text_brain_timeout", task=request.task.value, timeout=request.timeout_s
            )
            resp = self._stub_response(request)
            resp.reason = "timeout"
            telemetry.record(
                "aux_text_brain", task=request.task.value, degraded=True, reason="timeout"
            )
            return self._finish(resp, start, degraded=True)
        except Exception as e:
            logger.warning("aux_text_brain_fallback", task=request.task.value, error=str(e))
            resp = self._stub_response(request)
            resp.reason = f"fallback:{type(e).__name__}"
            telemetry.record(
                "aux_text_brain", task=request.task.value, degraded=True, reason="error"
            )
            return self._finish(resp, start, degraded=True)

    # -- internals ----------------------------------------------------------
    def _stub_response(self, request: TextBrainRequest) -> TextBrainResponse:
        return self._stub.generate(request, self._tools)

    async def _call_ollama(self, request: TextBrainRequest) -> str:
        client = await self._ensure_client()
        messages = build_messages(request, self._tools)
        resp = await client.post(
            "/api/chat",
            json={
                "model": self._model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": request.temperature,
                    "num_predict": request.max_tokens,
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

    def _parse(self, request: TextBrainRequest, text: str) -> TextBrainResponse:
        task = request.task
        text = (text or "").strip()
        if task is TextBrainTask.tool_plan:
            return TextBrainResponse(task=task, tool_calls=_parse_tool_calls(text))
        if task is TextBrainTask.rag_query:
            queries = [ln.strip() for ln in text.splitlines() if ln.strip()][:3]
            return TextBrainResponse(task=task, rag_queries=queries)
        if task is TextBrainTask.dataset_label:
            return TextBrainResponse(task=task, labels=_parse_labels(text))
        if task in (TextBrainTask.memory_summary, TextBrainTask.moderation_summary):
            return TextBrainResponse(task=task, summary=text, text=text)
        # transcript_cleanup + default
        return TextBrainResponse(task=task, text=text)

    @staticmethod
    def _finish(
        resp: TextBrainResponse,
        start: float,
        *,
        degraded: bool,
        model: str | None = None,
    ) -> TextBrainResponse:
        resp.degraded = degraded
        resp.latency_ms = int((time.perf_counter() - start) * 1000)
        if model is not None:
            resp.model = model
        logger.info(
            "aux_text_brain_complete",
            task=resp.task.value,
            degraded=resp.degraded,
            latency_ms=resp.latency_ms,
            model=resp.model,
        )
        return resp


# ---------------------------------------------------------------------------
# Convenience one-shot helper
# ---------------------------------------------------------------------------
async def run_task(
    task: TextBrainTask | str,
    payload: dict,
    *,
    use_ollama: bool = True,
    timeout_s: float = 8.0,
) -> TextBrainResponse:
    """Run a single text-brain task without managing a service instance."""
    if isinstance(task, str):
        task = TextBrainTask(task)
    svc = TextBrainService(use_ollama=use_ollama)
    try:
        return await svc.run(TextBrainRequest(task=task, payload=payload, timeout_s=timeout_s))
    finally:
        await svc.close()
