"""
memory/tool_router/contracts.py — Tool contracts (Phase 12C).

Schema + policies for tool calls invoked during a conversation:

  * :class:`ToolSpec`          — declares a tool: name, description, handler, safety flag,
                                  per-tool timeout/retry overrides.
  * :class:`ToolCall`          — a request to run a tool with arguments.
  * :class:`ToolResult`        — the bounded outcome (status, output, latency, error).
  * :class:`ToolStatus`        — ok / timeout / error / blocked / escalated.
  * :class:`TimeoutPolicy`     — per-call timeout so the hot path is never blocked.
  * :class:`RetryPolicy`       — bounded retries with backoff for transient failures.
  * :class:`SafeToolAllowlist` — only explicitly allowed tools may run.
  * :class:`EscalationDecision`— hand off to the aux text-brain when a tool can't serve.

CPU/no-weights rule: plain pydantic v2 + stdlib. Handlers are plain callables; the router
runs them with a timeout (Phase 12C router).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ToolStatus",
    "ToolSpec",
    "ToolCall",
    "ToolResult",
    "TimeoutPolicy",
    "RetryPolicy",
    "SafeToolAllowlist",
    "EscalationDecision",
]


class ToolStatus(str, Enum):
    """Outcome of a tool invocation."""

    ok = "ok"
    timeout = "timeout"
    error = "error"
    blocked = "blocked"  # not on the safe-tool allowlist
    escalated = "escalated"  # handed off to the text-brain


class TimeoutPolicy(BaseModel):
    """Per-call timeout. Keeps a slow/hung tool from blocking the voice runtime."""

    model_config = ConfigDict(extra="forbid")

    timeout_ms: int = Field(default=800, gt=0, le=60_000)


class RetryPolicy(BaseModel):
    """Bounded retries with exponential backoff for transient failures."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=2, ge=1, le=5)
    backoff_ms: int = Field(default=50, ge=0, le=5_000)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    retry_on_timeout: bool = Field(default=True)

    def delay_for_attempt(self, attempt: int) -> float:
        """Backoff (in seconds) before ``attempt`` (1-indexed); attempt 1 has no delay."""
        if attempt <= 1:
            return 0.0
        ms = self.backoff_ms * (self.backoff_multiplier ** (attempt - 2))
        return ms / 1000.0


class ToolSpec(BaseModel):
    """Declares a callable tool and its safety/timeout/retry profile."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str = ""
    handler: Callable[..., Any] = Field(exclude=True, repr=False)
    safe: bool = Field(default=False, description="Must be True to be allowlisted by default.")
    timeout: TimeoutPolicy | None = None
    retry: RetryPolicy | None = None


class ToolCall(BaseModel):
    """A request to invoke a tool by name with keyword arguments."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    tool: str
    args: dict = Field(default_factory=dict)
    turn_id: str | None = None


class ToolResult(BaseModel):
    """Bounded outcome of a tool invocation — always returned, never raised at the caller."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    status: ToolStatus
    output: Any | None = None
    error: str | None = None
    attempts: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    escalated: bool = Field(default=False)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status is ToolStatus.ok


class SafeToolAllowlist(BaseModel):
    """The set of tool names permitted to run. Anything else is blocked."""

    model_config = ConfigDict(extra="forbid")

    allowed: set[str] = Field(default_factory=set)

    def is_allowed(self, tool: str) -> bool:
        return tool in self.allowed

    def allow(self, tool: str) -> None:
        self.allowed.add(tool)

    def block(self, tool: str) -> None:
        self.allowed.discard(tool)


class EscalationDecision(BaseModel):
    """Whether (and why) a failed/blocked tool call escalates to the aux text-brain."""

    model_config = ConfigDict(extra="forbid")

    escalate: bool
    reason: str = ""
    task: str = Field(
        default="tool_plan",
        description="aux text-brain task hint, e.g. tool_plan | rag_query.",
    )
