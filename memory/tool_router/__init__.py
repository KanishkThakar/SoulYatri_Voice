"""memory/tool_router/ — Tool contracts & router (final_use.md Phase 12C).

Owner: memory agent. Kept inside the ``memory/`` tree to respect file ownership.

Defines the tool schema, timeout policy, retry policy, a safe-tool allowlist, and text-brain
escalation. Core guarantee: tool failures degrade gracefully and never break the voice
runtime. No heavy deps at import time — everything is pydantic v2 + stdlib.
"""

from memory.tool_router.contracts import (
    EscalationDecision,
    RetryPolicy,
    SafeToolAllowlist,
    TimeoutPolicy,
    ToolCall,
    ToolResult,
    ToolSpec,
    ToolStatus,
)
from memory.tool_router.router import ToolRouter

__all__ = [
    "ToolSpec",
    "ToolCall",
    "ToolResult",
    "ToolStatus",
    "TimeoutPolicy",
    "RetryPolicy",
    "SafeToolAllowlist",
    "EscalationDecision",
    "ToolRouter",
]
