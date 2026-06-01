"""
Tests for memory/tool_router/ (Phase 12C).

Covers tool schema, the safe-tool allowlist (blocking), timeout policy, retry policy with
backoff, graceful failure (never raises into the runtime), and text-brain escalation.
"""

from __future__ import annotations

import time

from memory.tool_router.contracts import (
    EscalationDecision,
    RetryPolicy,
    SafeToolAllowlist,
    TimeoutPolicy,
    ToolCall,
    ToolResult,
    ToolStatus,
)
from memory.tool_router.router import ToolRouter


# ---------------------------------------------------------------------------
# contracts
# ---------------------------------------------------------------------------
def test_retry_backoff_schedule() -> None:
    retry = RetryPolicy(max_attempts=3, backoff_ms=100, backoff_multiplier=2.0)
    assert retry.delay_for_attempt(1) == 0.0
    assert retry.delay_for_attempt(2) == 0.1  # 100ms
    assert retry.delay_for_attempt(3) == 0.2  # 100 * 2^1 ms


def test_allowlist_ops() -> None:
    al = SafeToolAllowlist()
    assert not al.is_allowed("x")
    al.allow("x")
    assert al.is_allowed("x")
    al.block("x")
    assert not al.is_allowed("x")


def test_tool_result_ok_property() -> None:
    assert ToolResult(tool="t", status=ToolStatus.ok).ok is True
    assert ToolResult(tool="t", status=ToolStatus.error).ok is False


# ---------------------------------------------------------------------------
# router happy path
# ---------------------------------------------------------------------------
def test_safe_tool_runs_and_returns_output() -> None:
    router = ToolRouter()
    router.register_fn("echo", lambda value: value, safe=True)
    res = router.invoke(ToolCall(session_id="s1", tool="echo", args={"value": 42}))
    assert res.status is ToolStatus.ok
    assert res.output == 42
    assert res.attempts == 1
    assert res.latency_ms >= 0
    router.close()


def test_unknown_tool_blocked() -> None:
    router = ToolRouter()
    res = router.invoke(ToolCall(session_id="s1", tool="missing"))
    assert res.status is ToolStatus.blocked
    assert res.error == "unknown_tool"
    router.close()


# ---------------------------------------------------------------------------
# allowlist enforcement
# ---------------------------------------------------------------------------
def test_unsafe_tool_blocked_by_allowlist() -> None:
    router = ToolRouter()
    # Registered but NOT safe and not explicitly allowlisted -> blocked.
    router.register_fn("danger", lambda: "boom", safe=False)
    res = router.invoke(ToolCall(session_id="s1", tool="danger"))
    assert res.status is ToolStatus.blocked
    assert res.error == "not_allowlisted"
    router.close()


def test_explicit_allowlist_overrides_auto() -> None:
    al = SafeToolAllowlist(allowed={"only_this"})
    router = ToolRouter(allowlist=al)
    router.register_fn("only_this", lambda: "ok", safe=False)
    router.register_fn("other", lambda: "no", safe=True)  # safe but not in explicit allowlist
    assert router.invoke(ToolCall(session_id="s1", tool="only_this")).status is ToolStatus.ok
    assert router.invoke(ToolCall(session_id="s1", tool="other")).status is ToolStatus.blocked
    router.close()


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------
def test_timeout_does_not_block_caller() -> None:
    router = ToolRouter(
        default_timeout=TimeoutPolicy(timeout_ms=80),
        default_retry=RetryPolicy(max_attempts=1),
    )

    def slow() -> str:
        time.sleep(5.0)
        return "late"

    router.register_fn("slow", slow, safe=True)
    started = time.perf_counter()
    res = router.invoke(ToolCall(session_id="s1", tool="slow"))
    elapsed = time.perf_counter() - started
    assert res.status is ToolStatus.timeout
    assert elapsed < 2.0  # returned long before the 5s handler finished
    router.close()


# ---------------------------------------------------------------------------
# retries
# ---------------------------------------------------------------------------
def test_retry_then_success() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("transient")
        return "recovered"

    router = ToolRouter(
        default_retry=RetryPolicy(max_attempts=3, backoff_ms=1),
    )
    router.register_fn("flaky", flaky, safe=True)
    res = router.invoke(ToolCall(session_id="s1", tool="flaky"))
    assert res.status is ToolStatus.ok
    assert res.output == "recovered"
    assert res.attempts == 2
    router.close()


def test_error_exhausts_retries_and_degrades() -> None:
    def always_fail() -> str:
        raise RuntimeError("nope")

    router = ToolRouter(default_retry=RetryPolicy(max_attempts=2, backoff_ms=1))
    router.register_fn("bad", always_fail, safe=True)
    res = router.invoke(ToolCall(session_id="s1", tool="bad"))
    # Never raises into the caller; returns a structured failure.
    assert res.status in (ToolStatus.error, ToolStatus.escalated)
    assert res.attempts == 2
    router.close()


# ---------------------------------------------------------------------------
# escalation
# ---------------------------------------------------------------------------
def test_escalation_decision_blocked_does_not_escalate() -> None:
    router = ToolRouter()
    res = ToolResult(tool="x", status=ToolStatus.blocked)
    decision = router.escalation_decision(ToolCall(session_id="s1", tool="x"), res)
    assert isinstance(decision, EscalationDecision)
    assert decision.escalate is False
    router.close()


def test_escalation_decision_error_escalates() -> None:
    router = ToolRouter()
    res = ToolResult(tool="x", status=ToolStatus.error)
    decision = router.escalation_decision(ToolCall(session_id="s1", tool="x"), res)
    assert decision.escalate is True
    assert decision.task == "tool_plan"
    router.close()


def test_escalation_uses_text_brain() -> None:
    def text_brain(call: ToolCall, result: ToolResult) -> str:
        return f"text-brain handled {call.tool}"

    router = ToolRouter(
        default_retry=RetryPolicy(max_attempts=1),
        text_brain=text_brain,
    )
    router.register_fn("bad", lambda: (_ for _ in ()).throw(RuntimeError("x")), safe=True)
    res = router.invoke(ToolCall(session_id="s1", tool="bad"))
    assert res.status is ToolStatus.escalated
    assert res.escalated is True
    assert res.output == "text-brain handled bad"
    router.close()


def test_text_brain_failure_stays_graceful() -> None:
    def boom_brain(call: ToolCall, result: ToolResult):
        raise RuntimeError("brain down")

    router = ToolRouter(
        default_retry=RetryPolicy(max_attempts=1),
        text_brain=boom_brain,
    )
    router.register_fn("bad", lambda: (_ for _ in ()).throw(RuntimeError("x")), safe=True)
    res = router.invoke(ToolCall(session_id="s1", tool="bad"))
    # Escalation flagged, brain failed, but the call still returns without raising.
    assert res.escalated is True
    assert res.status is ToolStatus.error
    router.close()


def test_context_manager_closes() -> None:
    with ToolRouter() as router:
        router.register_fn("echo", lambda value: value, safe=True)
        res = router.invoke(ToolCall(session_id="s1", tool="echo", args={"value": "hi"}))
        assert res.ok
