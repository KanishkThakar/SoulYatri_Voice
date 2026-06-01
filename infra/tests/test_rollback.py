"""
Tests for infra.deploy.rollback (Phase 16C — canary/rollback policy evaluator).

Covers: rollback fires on threshold breach (the §16C acceptance), promote when healthy,
hold on insufficient samples, multi-metric breach reporting, comparison overrides,
absent metrics never triggering rollback, and parsing the §16C YAML skeleton shape.
"""

from __future__ import annotations

from infra.deploy import (
    Comparison,
    ReleasePolicy,
    RollbackAction,
    RollbackEvaluator,
    RollbackThreshold,
)


def _skeleton_policy() -> ReleasePolicy:
    # The exact final_use.md §16C starter skeleton shape.
    return ReleasePolicy.from_dict(
        {
            "rollout": "canary",
            "rollback_trigger": {"p95_ttfb_ms": 450, "error_rate_pct": 1.0},
        }
    )


def test_rollback_fires_on_latency_breach() -> None:
    evaluator = RollbackEvaluator(_skeleton_policy())
    decision = evaluator.evaluate({"p95_ttfb_ms": 600, "error_rate_pct": 0.2})
    assert decision.action is RollbackAction.rollback
    assert decision.should_rollback is True
    assert "p95_ttfb_ms" in decision.breached


def test_rollback_fires_on_error_rate_breach() -> None:
    evaluator = RollbackEvaluator(_skeleton_policy())
    decision = evaluator.evaluate({"p95_ttfb_ms": 100, "error_rate_pct": 2.5})
    assert decision.should_rollback is True
    assert decision.breached == ["error_rate_pct"]


def test_multiple_breaches_all_reported() -> None:
    evaluator = RollbackEvaluator(_skeleton_policy())
    decision = evaluator.evaluate({"p95_ttfb_ms": 999, "error_rate_pct": 9.9})
    assert decision.action is RollbackAction.rollback
    assert set(decision.breached) == {"p95_ttfb_ms", "error_rate_pct"}


def test_promote_when_within_thresholds() -> None:
    evaluator = RollbackEvaluator(_skeleton_policy())
    decision = evaluator.evaluate({"p95_ttfb_ms": 410, "error_rate_pct": 0.4})
    assert decision.action is RollbackAction.promote
    assert decision.should_rollback is False


def test_boundary_equal_is_not_a_breach() -> None:
    # greater_than: observed == limit is NOT a breach.
    evaluator = RollbackEvaluator(_skeleton_policy())
    decision = evaluator.evaluate({"p95_ttfb_ms": 450, "error_rate_pct": 1.0})
    assert decision.action is RollbackAction.promote


def test_hold_when_insufficient_samples() -> None:
    policy = ReleasePolicy.from_dict(
        {
            "rollout": "canary",
            "rollback_trigger": {"p95_ttfb_ms": 450},
            "canary": {"min_samples": 200},
        }
    )
    evaluator = RollbackEvaluator(policy)
    decision = evaluator.evaluate({"p95_ttfb_ms": 100}, samples=50)
    assert decision.action is RollbackAction.hold
    # But a breach still rolls back regardless of sample count.
    breach = evaluator.evaluate({"p95_ttfb_ms": 999}, samples=5)
    assert breach.action is RollbackAction.rollback


def test_absent_metric_never_triggers_rollback() -> None:
    evaluator = RollbackEvaluator(_skeleton_policy())
    # Only one metric observed; the other is simply skipped.
    decision = evaluator.evaluate({"error_rate_pct": 0.1})
    assert decision.action is RollbackAction.promote
    assert "p95_ttfb_ms" not in decision.observed


def test_comparison_override_less_than() -> None:
    # A 'minimum' style metric: breach when observed drops BELOW the limit.
    policy = ReleasePolicy.from_dict(
        {
            "rollout": "canary",
            "rollback_trigger": {"filler_hit_rate": 0.5},
            "comparisons": {"filler_hit_rate": "less_than"},
        }
    )
    evaluator = RollbackEvaluator(policy)
    assert evaluator.evaluate({"filler_hit_rate": 0.3}).should_rollback is True
    assert evaluator.evaluate({"filler_hit_rate": 0.9}).action is RollbackAction.promote


def test_threshold_is_breached_helper() -> None:
    gt = RollbackThreshold(metric="m", limit=10, comparison=Comparison.greater_than)
    assert gt.is_breached(11) is True
    assert gt.is_breached(10) is False
    lt = RollbackThreshold(metric="m", limit=10, comparison=Comparison.less_than)
    assert lt.is_breached(9) is True
    assert lt.is_breached(10) is False


def test_decision_to_dict_is_jsonable() -> None:
    evaluator = RollbackEvaluator(_skeleton_policy())
    d = evaluator.evaluate({"p95_ttfb_ms": 999}).to_dict()
    assert d["action"] == "rollback"
    assert "p95_ttfb_ms" in d["breached"]


def test_policy_default_comparison_for_known_metric() -> None:
    policy = _skeleton_policy()
    t = policy.threshold_for("p95_ttfb_ms")
    assert t is not None
    assert t.comparison is Comparison.greater_than
