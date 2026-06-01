"""
aux/text_brain/contracts.py — Text-brain request/response schema (Phase 7B)
===========================================================================
Pydantic v2 contracts for the auxiliary text reasoning brain (Qwen3 / Llama 3.3,
served via Ollama in the baseline). These define the **input task schema**, the
**tool schema**, and the **deterministic output schema** the pipeline depends on.

These types are dependency-light (pydantic only) so they import on a CPU-only box.
The actual model client lives in ``service.py`` and is lazy with a stub fallback.

Mirrors the starter skeleton in final_use.md §Phase-7B::

    class TextBrainRequest(BaseModel):
        task: Literal["memory_summary", "tool_plan", "moderation_summary", "rag_query"]
        payload: dict
"""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TextBrainTask",
    "ToolParam",
    "ToolSpec",
    "ToolCall",
    "TextBrainRequest",
    "TextBrainResponse",
    "DEFAULT_TOOLS",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


class TextBrainTask(str, Enum):
    """Supported auxiliary text tasks (final_use.md §7B/§7C).

    The text brain is auxiliary: it serves memory, safety, tools, RAG prep, and
    offline analysis. It is never the primary conversational runtime.
    """

    memory_summary = "memory_summary"
    tool_plan = "tool_plan"
    moderation_summary = "moderation_summary"
    rag_query = "rag_query"
    transcript_cleanup = "transcript_cleanup"
    dataset_label = "dataset_label"


class ToolParam(BaseModel):
    """A single tool parameter declaration."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True


class ToolSpec(BaseModel):
    """Declarative tool schema the text brain may plan calls against.

    Kept compatible with ``aux/tool_router`` (Phase 12C) — the router owns timeout,
    retry, and allowlist policy; this is just the declaration the planner sees.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    params: list[ToolParam] = Field(default_factory=list)
    safe: bool = True


class ToolCall(BaseModel):
    """A planned tool invocation produced by ``task=tool_plan``."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict = Field(default_factory=dict)
    reason: str = ""


class TextBrainRequest(BaseModel):
    """Input to the text-brain service.

    ``payload`` carries task-specific data (e.g. ``{"turns": [...]}`` for
    ``memory_summary`` or ``{"query": "...", "tools": [...]}`` for ``tool_plan``).
    """

    model_config = ConfigDict(extra="forbid")

    task: TextBrainTask
    payload: dict = Field(default_factory=dict)
    session_id: str | None = None
    timeout_s: float = Field(default=8.0, gt=0, le=120, description="Per-request budget.")
    max_tokens: int = Field(default=256, gt=0, le=4096)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class TextBrainResponse(BaseModel):
    """Deterministic-enough output schema for pipeline use.

    Exactly one of ``text`` / ``summary`` / ``tool_calls`` / ``rag_queries`` is the
    primary payload depending on the task; all are present for uniform handling.
    ``ok`` + ``degraded`` let callers branch on stub/timeout without exceptions.
    """

    model_config = ConfigDict(extra="forbid")

    task: TextBrainTask
    ok: bool = True
    degraded: bool = Field(default=False, description="True when produced by stub/timeout path.")
    text: str = ""
    summary: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    rag_queries: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    model: str = "stub"
    latency_ms: int = 0
    reason: str = ""
    ts_ms: int = Field(default_factory=_now_ms)


# A tiny default allowlist of safe tools the planner may reference. The real
# enforcement (timeout/retry/allowlist) is owned by aux/tool_router (Phase 12C).
DEFAULT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="memory_lookup",
        description="Retrieve bounded memory items for the session.",
        params=[
            ToolParam(name="query", description="Natural-language memory query."),
            ToolParam(name="top_k", type="int", description="Max items.", required=False),
        ],
    ),
    ToolSpec(
        name="time_now",
        description="Return the current time.",
        params=[],
    ),
]
