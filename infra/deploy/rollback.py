"""
infra.deploy.rollback — canary/rollback policy evaluator (Phase 16C)
====================================================================
A small, deterministic policy evaluator that decides whether a canary rollout should
**continue**, **roll back**, or **promote**, based on observed metrics versus the
thresholds declared in ``infra/deploy/release_policy.yaml``.

final_use.md §16C starter skeleton:

    # infra/deploy/release_policy.yaml
    rollout: canary
    rollback_trigger:
      p95_ttfb_ms: 450
      error_rate_pct: 1.0

This module turns that config into a real decision function so "rollback is proven"
(the §16C acceptance test) without needing a live deployment. It maps cleanly onto the
server's exposed metrics (``soulyatri_pipeline_e2e_latency_seconds`` ≈ TTFB/TTFA,
``soulyatri_errors_total`` ≈ error rate) — see ``infra/monitoring/``.

No I/O beyond optionally loading the YAML policy file; pure logic otherwise.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infra.obs import get_logger, telemetry

__all__ = [
    "Comparison",
    "RollbackThreshold",
    "ReleasePolicy",
    "RollbackAction",
    "RollbackDecision",
    "RollbackEvaluator",
    "load_release_policy",
]

logger = get_logger("infra.deploy.rollback")


class Comparison(str, enum.Enum):
    """How an observed metric is compared against its threshold."""

    greater_than = "greater_than"   # breach when observed > threshold (latency, errors)
    less_than = "less_than"         # breach when observed < threshold (e.g. min hit rate)


class RollbackAction(str, enum.Enum):
    """The verdict produced by the evaluator."""

    rollback = "rollback"   # a threshold was breached -> revert the canary
    hold = "hold"           # within thresholds but not yet enough evidence to promote
    promote = "promote"     # healthy and enough samples observed -> promote canary


# Default comparison direction per metric key (operators may override in YAML).
_DEFAULT_COMPARISONS: dict[str, Comparison] = {
    "p95_ttfb_ms": Comparison.greater_than,
    "p99_ttfb_ms": Comparison.greater_than,
    "error_rate_pct": Comparison.greater_than,
    "interruption_recovery_ms": Comparison.greater_than,
    "filler_false_positive_rate": Comparison.greater_than,
}


@dataclass(frozen=True)
class RollbackThreshold:
    """A single ``metric -> limit`` rule with a comparison direction."""

    metric: str
    limit: float
    comparison: Comparison = Comparison.greater_than

    def is_breached(self, observed: float) -> bool:
        if self.comparison is Comparison.greater_than:
            return observed > self.limit
        return observed < self.limit


@dataclass
class ReleasePolicy:
    """Parsed ``release_policy.yaml``."""

    rollout: str
    thresholds: list[RollbackThreshold] = field(default_factory=list)
    min_canary_samples: int = 0
    canary_percent: float | None = None

    def threshold_for(self, metric: str) -> RollbackThreshold | None:
        for t in self.thresholds:
            if t.metric == metric:
                return t
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReleasePolicy:
        """Build a policy from a parsed YAML/JSON mapping.

        Accepts the §16C skeleton shape::

            rollout: canary
            rollback_trigger:
              p95_ttfb_ms: 450
              error_rate_pct: 1.0

        plus optional ``min_canary_samples``, ``canary_percent``, and a ``comparisons``
        map to override the default direction per metric.
        """
        rollout = str(data.get("rollout", "canary"))
        triggers = data.get("rollback_trigger", {}) or {}
        overrides = data.get("comparisons", {}) or {}

        thresholds: list[RollbackThreshold] = []
        for metric, limit in triggers.items():
            comparison = _resolve_comparison(metric, overrides.get(metric))
            thresholds.append(
                RollbackThreshold(metric=metric, limit=float(limit), comparison=comparison)
            )

        canary = data.get("canary", {}) or {}
        return cls(
            rollout=rollout,
            thresholds=thresholds,
            min_canary_samples=int(canary.get("min_samples", data.get("min_canary_samples", 0))),
            canary_percent=(
                float(canary["percent"]) if "percent" in canary else data.get("canary_percent")
            ),
        )


def _resolve_comparison(metric: str, override: str | None) -> Comparison:
    if override is not None:
        return Comparison(override)
    return _DEFAULT_COMPARISONS.get(metric, Comparison.greater_than)


@dataclass
class RollbackDecision:
    """Auditable verdict for a metrics observation."""

    action: RollbackAction
    breached: list[str] = field(default_factory=list)
    reason: str = ""
    observed: dict[str, float] = field(default_factory=dict)

    @property
    def should_rollback(self) -> bool:
        return self.action is RollbackAction.rollback

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "breached": list(self.breached),
            "reason": self.reason,
            "observed": dict(self.observed),
        }


class RollbackEvaluator:
    """Evaluates observed canary metrics against a :class:`ReleasePolicy`."""

    def __init__(self, policy: ReleasePolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> ReleasePolicy:
        return self._policy

    def evaluate(self, metrics: dict[str, float], *, samples: int | None = None) -> RollbackDecision:
        """Decide rollback/hold/promote from observed ``metrics``.

        * Any breached threshold -> :attr:`RollbackAction.rollback` (fail fast, fail safe).
        * Otherwise, if ``samples`` is below ``min_canary_samples`` -> ``hold`` (not
          enough evidence yet).
        * Otherwise -> ``promote``.

        Metrics not present in ``metrics`` are treated as "not observed" and skipped
        (an absent metric never triggers a rollback on its own).
        """
        breached: list[str] = []
        observed: dict[str, float] = {}

        for threshold in self._policy.thresholds:
            if threshold.metric not in metrics:
                continue
            value = float(metrics[threshold.metric])
            observed[threshold.metric] = value
            if threshold.is_breached(value):
                breached.append(threshold.metric)

        if breached:
            decision = RollbackDecision(
                action=RollbackAction.rollback,
                breached=breached,
                reason="threshold breach: " + ", ".join(sorted(breached)),
                observed=observed,
            )
        elif samples is not None and samples < self._policy.min_canary_samples:
            decision = RollbackDecision(
                action=RollbackAction.hold,
                reason=(
                    f"insufficient canary samples ({samples} < "
                    f"{self._policy.min_canary_samples})"
                ),
                observed=observed,
            )
        else:
            decision = RollbackDecision(
                action=RollbackAction.promote,
                reason="all observed metrics within thresholds",
                observed=observed,
            )

        telemetry.record(
            "infra_rollback_eval",
            action=decision.action.value,
            breached=",".join(decision.breached),
            samples=samples,
        )
        logger.info(
            "rollback_evaluation",
            action=decision.action.value,
            breached=decision.breached,
            reason=decision.reason,
        )
        return decision


def load_release_policy(path: str | Path) -> ReleasePolicy:
    """Load and parse a ``release_policy.yaml`` file into a :class:`ReleasePolicy`.

    ``pyyaml`` is imported lazily so importing this module never requires it.
    """
    import yaml  # noqa: PLC0415 (intentional lazy/optional import)

    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"release policy must be a mapping, got {type(data).__name__}")
    return ReleasePolicy.from_dict(data)
