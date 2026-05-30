"""
evals/gates.py — regression gates (Phase 15C).
==============================================
"PRs can fail automatically on threshold regressions" (final_use.md §15C).

This module compares a :class:`evals.latency.metrics.MetricsCollector` snapshot
against a set of configurable :class:`Threshold` rules and produces a
JSON-serializable pass/fail :class:`GateReport`. The defaults come from
``docs/LATENCY_TARGETS.md`` (sub-300 ms first-audible ambition; low-hundreds-ms
interruption stop) and the §12 evaluation matrix (WER, emotion agreement,
code-switch, filler hit / false-positive rates).

Direction of comparison is derived from the metric registry:
  * **higher-is-better** metrics (filler_hit_rate, emotion_agreement, …) → the
    threshold is a *floor*: ``value >= limit`` passes.
  * **lower-is-better** metrics (latency, WER, filler_false_positive_rate) → the
    threshold is a *ceiling*: ``value <= limit`` passes.

Latency/score metrics are aggregated by a configurable percentile (default p95);
rate/gauge metrics use the mean. Everything is pure stdlib, deterministic, and
CPU-only.

Numeric per-stage budgets remain open question Q-008 in
``docs/LATENCY_TARGETS.md``; the defaults below are explicit, overridable, and
documented as provisional rather than hard guarantees.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from evals.latency.metrics import (
    METRIC_REGISTRY,
    MetricsCollector,
    percentile,
)

__all__ = [
    "Threshold",
    "GateResult",
    "GateReport",
    "default_thresholds",
    "RegressionGate",
]


@dataclass(frozen=True)
class Threshold:
    """A single regression threshold for one metric.

    ``limit`` is interpreted as a ceiling for lower-is-better metrics and a floor
    for higher-is-better metrics (direction taken from the metric registry, or
    overridden via ``higher_is_better``). ``aggregate`` selects how a sample
    window is reduced to one comparable value: ``"p50"`` / ``"p95"`` / ``"p99"``
    / ``"mean"`` / ``"max"`` / ``"min"``.
    """

    metric: str
    limit: float
    aggregate: str = "p95"
    higher_is_better: bool | None = None  # None → look up registry

    def resolve_direction(self) -> bool:
        """Resolve higher-is-better, preferring the explicit override."""
        if self.higher_is_better is not None:
            return self.higher_is_better
        spec = METRIC_REGISTRY.get(self.metric)
        return bool(spec.higher_is_better) if spec else False


@dataclass
class GateResult:
    """Outcome of evaluating one threshold."""

    metric: str
    aggregate: str
    value: float
    limit: float
    higher_is_better: bool
    passed: bool
    samples: int
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class GateReport:
    """Aggregate pass/fail report over all evaluated thresholds."""

    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True only if every gated result passed."""
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[GateResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "total": len(self.results),
            "failed": len(self.failures),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        """One-line human-readable summary."""
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {len(self.results) - len(self.failures)}/{len(self.results)} gates passed"


def default_thresholds() -> list[Threshold]:
    """Default regression thresholds from LATENCY_TARGETS.md + §12 matrix.

    These are provisional defaults (LATENCY_TARGETS.md Q-008). Latency metrics
    gate on p95; quality/rate metrics gate on the mean.
    """
    return [
        # --- latency gates (docs/LATENCY_TARGETS.md) ---
        Threshold("time_to_first_audible_ms", 300.0, "p95"),  # sub-300ms ambition
        Threshold("first_token_ms", 220.0, "p95"),  # provisional (Q-008)
        Threshold("turn_end_detection_delay_ms", 150.0, "p95"),  # provisional (Q-008)
        Threshold("interruption_recovery_ms", 300.0, "p95"),  # low-hundreds-ms stop
        # --- filler routing rates (§12 / LATENCY_TARGETS.md definitions) ---
        Threshold("filler_hit_rate", 0.80, "mean"),  # higher is better → floor
        Threshold("filler_false_positive_rate", 0.05, "mean"),  # ceiling
        # --- §12 quality dimensions ---
        Threshold("wer", 0.30, "mean"),  # intelligibility ceiling
        Threshold("emotion_agreement", 0.70, "mean"),  # floor
        Threshold("code_switch_score", 0.70, "mean"),  # floor
        Threshold("naturalness_proxy", 0.70, "mean"),  # floor
    ]


def _aggregate_value(collector: MetricsCollector, metric: str, aggregate: str) -> float:
    """Reduce a metric's sample window to a single comparable value."""
    values = collector.values(metric)
    if not values:
        return 0.0
    agg = aggregate.lower()
    if agg == "mean":
        return sum(values) / len(values)
    if agg == "max":
        return float(max(values))
    if agg == "min":
        return float(min(values))
    if agg in ("p50", "p95", "p99"):
        return percentile(values, float(agg[1:]))
    raise ValueError(f"Unknown aggregate: {aggregate!r}")


class RegressionGate:
    """Evaluates a metrics snapshot against thresholds → pass/fail report.

    The gate *fails on regression*: any threshold breach flips
    :attr:`GateReport.passed` to False so CI can block a merge (final_use.md
    §15C acceptance test).
    """

    def __init__(self, thresholds: list[Threshold] | None = None) -> None:
        self.thresholds = thresholds if thresholds is not None else default_thresholds()

    def evaluate(self, collector: MetricsCollector) -> GateReport:
        """Evaluate every threshold against ``collector`` and build a report."""
        report = GateReport()
        for th in self.thresholds:
            report.results.append(self._evaluate_one(collector, th))
        return report

    @staticmethod
    def _evaluate_one(collector: MetricsCollector, th: Threshold) -> GateResult:
        higher_is_better = th.resolve_direction()
        samples = collector.count(th.metric)
        value = _aggregate_value(collector, th.metric, th.aggregate)

        if samples == 0:
            # No data → cannot regress; pass but flag it for the reader.
            return GateResult(
                metric=th.metric,
                aggregate=th.aggregate,
                value=value,
                limit=th.limit,
                higher_is_better=higher_is_better,
                passed=True,
                samples=0,
                reason="no samples recorded; gate skipped",
            )

        if higher_is_better:
            passed = value >= th.limit
            cmp = ">=" if passed else "<"
            reason = f"{th.aggregate}={value:.4g} {cmp} floor {th.limit:.4g}"
        else:
            passed = value <= th.limit
            cmp = "<=" if passed else ">"
            reason = f"{th.aggregate}={value:.4g} {cmp} ceiling {th.limit:.4g}"

        return GateResult(
            metric=th.metric,
            aggregate=th.aggregate,
            value=value,
            limit=th.limit,
            higher_is_better=higher_is_better,
            passed=passed,
            samples=samples,
            reason=reason,
        )
