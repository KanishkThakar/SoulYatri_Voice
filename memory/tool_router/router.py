"""
memory/tool_router/router.py — Tool router (Phase 12C).

Runs tool calls with **timeout + bounded retry + safe-tool allowlist + graceful degradation**.
The single hard guarantee: a tool failure never propagates as an exception into the voice
runtime — :meth:`ToolRouter.invoke` always returns a :class:`ToolResult`, and on unrecoverable
failure it optionally produces an :class:`EscalationDecision` toward the aux text-brain.

Execution model
---------------
Handlers are arbitrary callables. They run in a worker thread so a hung handler cannot block
the caller past the timeout (the calling thread waits only ``timeout_ms``; a stuck worker is
abandoned, not awaited). This keeps the hot path bounded even though Python threads can't be
force-killed. Retries apply to errors and (optionally) timeouts with exponential backoff.

No heavy deps; stdlib ``concurrent.futures`` + ``threading`` only.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from memory._logging import get_logger
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

__all__ = ["ToolRouter"]

log = get_logger("memory.tool_router.router")


class ToolRouter:
    """Registers tools and invokes them safely under timeout/retry/allowlist policy.

    Parameters
    ----------
    allowlist:
        The :class:`SafeToolAllowlist`. If omitted, every registered tool whose ``safe`` flag
        is True is auto-allowlisted (explicit, conservative default).
    default_timeout / default_retry:
        Applied when a :class:`ToolSpec` doesn't override them.
    text_brain:
        Optional callable ``(ToolCall, ToolResult) -> Any`` used on escalation. If provided,
        its output is attached to the escalated result; failures here also degrade gracefully.
    auto_allow_safe:
        When no explicit allowlist is passed, allowlist tools registered with ``safe=True``.
    """

    def __init__(
        self,
        *,
        allowlist: SafeToolAllowlist | None = None,
        default_timeout: TimeoutPolicy | None = None,
        default_retry: RetryPolicy | None = None,
        text_brain: Callable[[ToolCall, ToolResult], Any] | None = None,
        auto_allow_safe: bool = True,
    ) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._explicit_allowlist = allowlist is not None
        self.allowlist = allowlist or SafeToolAllowlist()
        self.default_timeout = default_timeout or TimeoutPolicy()
        self.default_retry = default_retry or RetryPolicy()
        self.text_brain = text_brain
        self.auto_allow_safe = auto_allow_safe
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="toolrouter")

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------
    def register(self, spec: ToolSpec) -> None:
        """Register a tool. Auto-allowlists safe tools when no explicit allowlist was given."""
        self._tools[spec.name] = spec
        if spec.safe and self.auto_allow_safe and not self._explicit_allowlist:
            self.allowlist.allow(spec.name)
        log.debug(
            "tool_registered", tool=spec.name, safe=spec.safe,
            allowed=self.allowlist.is_allowed(spec.name),
        )

    def register_fn(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        safe: bool = False,
        description: str = "",
        timeout: TimeoutPolicy | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        """Convenience: register a bare callable as a tool."""
        self.register(
            ToolSpec(
                name=name, handler=handler, safe=safe, description=description,
                timeout=timeout, retry=retry,
            )
        )

    # ------------------------------------------------------------------
    # invocation
    # ------------------------------------------------------------------
    def invoke(self, call: ToolCall) -> ToolResult:
        """Run a tool safely. Always returns a :class:`ToolResult` (never raises)."""
        started = time.perf_counter()

        spec = self._tools.get(call.tool)
        if spec is None:
            return self._finish(
                call,
                ToolResult(
                    tool=call.tool, status=ToolStatus.blocked,
                    error="unknown_tool", reason="tool is not registered",
                ),
                started,
            )

        if not self.allowlist.is_allowed(call.tool):
            log.warning("tool_blocked", tool=call.tool, session_id=call.session_id)
            return self._finish(
                call,
                ToolResult(
                    tool=call.tool, status=ToolStatus.blocked,
                    error="not_allowlisted", reason="tool not on safe-tool allowlist",
                ),
                started,
            )

        timeout = spec.timeout or self.default_timeout
        retry = spec.retry or self.default_retry

        last_error: str | None = None
        last_status = ToolStatus.error
        attempts = 0
        for attempt in range(1, retry.max_attempts + 1):
            attempts = attempt
            delay = retry.delay_for_attempt(attempt)
            if delay > 0:
                time.sleep(delay)
            status, output, err = self._run_once(spec, call, timeout)
            if status is ToolStatus.ok:
                return self._finish(
                    call,
                    ToolResult(
                        tool=call.tool, status=ToolStatus.ok, output=output, attempts=attempts
                    ),
                    started,
                )
            last_status = status
            last_error = err
            # Decide whether to retry.
            if status is ToolStatus.timeout and not retry.retry_on_timeout:
                break
            log.warning(
                "tool_attempt_failed", tool=call.tool, attempt=attempt,
                status=status.value, reason=err,
            )

        # All attempts exhausted -> degrade gracefully, maybe escalate.
        result = ToolResult(
            tool=call.tool, status=last_status, error=last_error, attempts=attempts,
            reason=f"failed after {attempts} attempt(s)",
        )
        result = self._maybe_escalate(call, result)
        return self._finish(call, result, started)

    def _run_once(
        self, spec: ToolSpec, call: ToolCall, timeout: TimeoutPolicy
    ) -> tuple[ToolStatus, Any, str | None]:
        """Run the handler once under a timeout in a worker thread."""
        future = self._executor.submit(spec.handler, **call.args)
        try:
            output = future.result(timeout=timeout.timeout_ms / 1000.0)
            return ToolStatus.ok, output, None
        except FutureTimeout:
            future.cancel()  # best-effort; a running thread can't be force-killed
            log.warning(
                "tool_timeout", tool=call.tool, timeout_ms=timeout.timeout_ms,
            )
            return ToolStatus.timeout, None, f"timeout after {timeout.timeout_ms}ms"
        except Exception as exc:  # handler raised
            return ToolStatus.error, None, f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # escalation
    # ------------------------------------------------------------------
    def escalation_decision(self, call: ToolCall, result: ToolResult) -> EscalationDecision:
        """Decide whether a failed/blocked call should escalate to the text-brain."""
        # Blocked-by-policy calls do not escalate (the policy said no).
        if result.status is ToolStatus.blocked:
            return EscalationDecision(escalate=False, reason="blocked_by_policy")
        if result.status in (ToolStatus.timeout, ToolStatus.error):
            return EscalationDecision(
                escalate=True,
                reason=f"tool_{result.status.value}",
                task="tool_plan",
            )
        return EscalationDecision(escalate=False, reason="ok")

    def _maybe_escalate(self, call: ToolCall, result: ToolResult) -> ToolResult:
        decision = self.escalation_decision(call, result)
        if not decision.escalate:
            return result
        result.escalated = True
        result.reason = f"{result.reason}; escalating: {decision.reason}"
        if self.text_brain is not None:
            try:
                fallback_output = self.text_brain(call, result)
                result.status = ToolStatus.escalated
                result.output = fallback_output
                log.info("tool_escalated", tool=call.tool, reason=decision.reason)
            except Exception as exc:  # text-brain itself failed — stay graceful
                log.warning(
                    "tool_escalation_failed", tool=call.tool, reason=type(exc).__name__
                )
        else:
            # No text-brain wired: mark escalated intent without changing the failure status.
            log.info("tool_escalation_pending", tool=call.tool, reason=decision.reason)
        return result

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _finish(self, call: ToolCall, result: ToolResult, started: float) -> ToolResult:
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        log.debug(
            "tool_invoke_done", tool=call.tool, status=result.status.value,
            attempts=result.attempts, latency_ms=result.latency_ms,
            escalated=result.escalated,
        )
        return result

    def close(self) -> None:
        """Shut down the worker pool (best-effort; safe to call multiple times)."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> ToolRouter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
