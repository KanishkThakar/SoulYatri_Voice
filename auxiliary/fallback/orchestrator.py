"""
aux/fallback/orchestrator.py — Failover policy + controller (Phase 13C)
=======================================================================
Decides **when to route to the classic baseline** instead of the speech-native
core, records telemetry, and surfaces user-facing messaging — so production
incidents degrade gracefully without architecture confusion (final_use.md §13C).

Output contract: ``shared.contracts.FallbackDecision`` (see docs/INTERFACES.md §4.2)::

    class FallbackDecision(BaseModel):
        use_fallback: bool
        reason: str
        expected_recovery_ms: int | None = None

Policy inputs are captured in :class:`PrimaryHealth`. The policy is explicit and
auditable (no hidden if-else sprawl): each rule has a name and a reason string that
flows into the decision telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from auxiliary.text_brain.obs import get_logger, telemetry
from shared.contracts import FallbackDecision

logger = get_logger(__name__)


class FailoverReason(str, Enum):
    """Auditable reasons a failover decision can carry."""

    healthy = "healthy"
    primary_unavailable = "primary_unavailable"
    high_latency = "high_latency"
    high_error_rate = "high_error_rate"
    consecutive_failures = "consecutive_failures"
    manual_override = "manual_override"
    recovered = "recovered"


# Default user-facing messages per reason (kept short + non-alarming).
USER_MESSAGES: dict[FailoverReason, str] = {
    FailoverReason.healthy: "",
    FailoverReason.primary_unavailable: "I'm switching to a backup voice mode for a moment.",
    FailoverReason.high_latency: "Things are a little slow right now; using a faster backup mode.",
    FailoverReason.high_error_rate: "I hit a snag and switched to a reliable backup mode.",
    FailoverReason.consecutive_failures: "I'm using a backup mode while the main system recovers.",
    FailoverReason.manual_override: "Backup mode is enabled by an operator.",
    FailoverReason.recovered: "Back to the full experience.",
}


@dataclass
class FailoverPolicy:
    """Thresholds governing the failover decision.

    Defaults are conservative: prefer the speech-native core, fall back only on
    clear degradation. All thresholds are explicit so the policy is auditable and
    testable.
    """

    max_latency_ms: int = 1200  # primary p95 budget before we consider it degraded
    max_error_rate: float = 0.25  # fraction of recent turns that errored
    max_consecutive_failures: int = 3
    default_recovery_ms: int = 5000
    # Hysteresis: require this many healthy probes before leaving fallback.
    recovery_probes_required: int = 2


@dataclass
class PrimaryHealth:
    """A snapshot of speech-native core health used to decide failover."""

    available: bool = True
    latency_ms: int | None = None
    error_rate: float = 0.0
    consecutive_failures: int = 0
    manual_override: bool = False


@dataclass
class _OrchestratorState:
    in_fallback: bool = False
    healthy_probes: int = 0
    last_reason: FailoverReason = FailoverReason.healthy
    decisions: int = 0
    fallbacks: int = 0


class FailoverOrchestrator:
    """Stateful failover controller.

    Call :meth:`decide` with the latest :class:`PrimaryHealth` snapshot to obtain a
    :class:`shared.contracts.FallbackDecision`. The controller applies hysteresis so
    the system does not flap between modes, records telemetry for every decision,
    and exposes :meth:`user_message` for UX surfacing.
    """

    def __init__(self, policy: FailoverPolicy | None = None) -> None:
        self._policy = policy or FailoverPolicy()
        self._state = _OrchestratorState()

    @property
    def in_fallback(self) -> bool:
        return self._state.in_fallback

    @property
    def last_reason(self) -> FailoverReason:
        return self._state.last_reason

    def _evaluate(self, health: PrimaryHealth) -> tuple[bool, FailoverReason]:
        """Pure rule evaluation -> (should_use_fallback, reason). Order = priority."""
        p = self._policy
        if health.manual_override:
            return True, FailoverReason.manual_override
        if not health.available:
            return True, FailoverReason.primary_unavailable
        if health.consecutive_failures >= p.max_consecutive_failures:
            return True, FailoverReason.consecutive_failures
        if health.error_rate > p.max_error_rate:
            return True, FailoverReason.high_error_rate
        if health.latency_ms is not None and health.latency_ms > p.max_latency_ms:
            return True, FailoverReason.high_latency
        return False, FailoverReason.healthy

    def decide(self, health: PrimaryHealth) -> FallbackDecision:
        """Produce a FallbackDecision from the current health snapshot."""
        should_fallback, reason = self._evaluate(health)
        self._state.decisions += 1

        if should_fallback:
            # Enter (or stay in) fallback; reset recovery counter.
            self._state.healthy_probes = 0
            if not self._state.in_fallback:
                self._state.in_fallback = True
                self._state.fallbacks += 1
                logger.warning(
                    "aux_failover_engaged", reason=reason.value, latency_ms=health.latency_ms
                )
            self._state.last_reason = reason
            decision = FallbackDecision(
                use_fallback=True,
                reason=reason.value,
                expected_recovery_ms=self._estimate_recovery(reason, health),
            )
        else:
            # Healthy probe. Apply hysteresis before leaving fallback.
            if self._state.in_fallback:
                self._state.healthy_probes += 1
                if self._state.healthy_probes >= self._policy.recovery_probes_required:
                    self._state.in_fallback = False
                    self._state.healthy_probes = 0
                    self._state.last_reason = FailoverReason.recovered
                    logger.info("aux_failover_recovered")
                    decision = FallbackDecision(
                        use_fallback=False, reason=FailoverReason.recovered.value
                    )
                else:
                    # Not enough healthy probes yet — stay in fallback.
                    self._state.last_reason = self._state.last_reason
                    decision = FallbackDecision(
                        use_fallback=True,
                        reason=f"recovering:{self._state.healthy_probes}/"
                        f"{self._policy.recovery_probes_required}",
                        expected_recovery_ms=self._policy.default_recovery_ms,
                    )
            else:
                self._state.last_reason = FailoverReason.healthy
                decision = FallbackDecision(use_fallback=False, reason=FailoverReason.healthy.value)

        telemetry.record(
            "aux_failover_decision",
            use_fallback=decision.use_fallback,
            reason=decision.reason,
            in_fallback=self._state.in_fallback,
            latency_ms=health.latency_ms,
            error_rate=health.error_rate,
        )
        return decision

    def _estimate_recovery(self, reason: FailoverReason, health: PrimaryHealth) -> int | None:
        if reason is FailoverReason.manual_override:
            return None  # operator-controlled
        if reason is FailoverReason.high_latency and health.latency_ms:
            # Rough estimate: scale with how far over budget we are.
            over = health.latency_ms - self._policy.max_latency_ms
            return max(self._policy.default_recovery_ms, over * 2)
        return self._policy.default_recovery_ms

    def user_message(self, decision: FallbackDecision | None = None) -> str:
        """Return UX messaging for the current (or supplied) decision."""
        reason = self._state.last_reason
        if decision is not None and decision.reason.startswith("recovering"):
            return USER_MESSAGES[FailoverReason.consecutive_failures]
        try:
            return USER_MESSAGES[FailoverReason(reason)]
        except ValueError:
            return ""

    def stats(self) -> dict[str, int]:
        return {
            "decisions": self._state.decisions,
            "fallbacks": self._state.fallbacks,
            "in_fallback": int(self._state.in_fallback),
        }


__all__ = [
    "FailoverOrchestrator",
    "FailoverPolicy",
    "PrimaryHealth",
    "FailoverReason",
    "FallbackDecision",
    "USER_MESSAGES",
]
