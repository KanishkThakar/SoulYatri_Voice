"""Tests for the regression gates passing AND failing vs thresholds (Phase 15C)."""

from __future__ import annotations

import json

from evals.gates import (
    GateReport,
    RegressionGate,
    Threshold,
    default_thresholds,
)
from evals.latency.metrics import MetricsCollector
from evals.replay.harness import ReplayHarness
from evals.replay.mock_pipeline import make_mock_pipeline


def _healthy_collector() -> MetricsCollector:
    """A collector populated with within-budget metrics."""
    c = MetricsCollector()
    for _ in range(20):
        c.record("time_to_first_audible_ms", 250.0)
        c.record("first_token_ms", 150.0)
        c.record("turn_end_detection_delay_ms", 100.0)
        c.record("interruption_recovery_ms", 180.0)
        c.record_rate_event("filler_hit_rate", True)
        c.record_rate_event("filler_false_positive_rate", False)
        c.record("wer", 0.10)
        c.record("emotion_agreement", 0.90)
        c.record("code_switch_score", 0.85)
        c.record("naturalness_proxy", 0.88)
    return c


# ---------------------------------------------------------------------------
# Passing path
# ---------------------------------------------------------------------------
def test_gate_passes_on_healthy_metrics():
    gate = RegressionGate()
    report = gate.evaluate(_healthy_collector())
    assert report.passed, report.summary()
    assert report.failures == []


def test_default_thresholds_cover_required_metrics():
    metrics = {t.metric for t in default_thresholds()}
    required = {
        "time_to_first_audible_ms",
        "first_token_ms",
        "turn_end_detection_delay_ms",
        "interruption_recovery_ms",
        "filler_hit_rate",
        "filler_false_positive_rate",
        "wer",
        "emotion_agreement",
    }
    assert required.issubset(metrics)


# ---------------------------------------------------------------------------
# Failing path — regression detection
# ---------------------------------------------------------------------------
def test_gate_fails_on_latency_regression():
    c = _healthy_collector()
    # Blow past the sub-300ms TTFA ceiling.
    for _ in range(20):
        c.record("time_to_first_audible_ms", 800.0)
    report = RegressionGate().evaluate(c)
    assert not report.passed
    failed_metrics = {r.metric for r in report.failures}
    assert "time_to_first_audible_ms" in failed_metrics


def test_gate_fails_on_filler_false_positive_regression():
    c = _healthy_collector()
    # Drive false-positive rate above the 0.05 ceiling.
    for _ in range(20):
        c.record_rate_event("filler_false_positive_rate", True)
    report = RegressionGate().evaluate(c)
    assert not report.passed
    assert "filler_false_positive_rate" in {r.metric for r in report.failures}


def test_gate_fails_on_low_emotion_agreement():
    c = _healthy_collector()
    for _ in range(40):
        c.record("emotion_agreement", 0.10)  # below 0.70 floor
    report = RegressionGate().evaluate(c)
    assert not report.passed
    assert "emotion_agreement" in {r.metric for r in report.failures}


def test_gate_skips_metric_with_no_samples():
    gate = RegressionGate([Threshold("time_to_first_audible_ms", 300.0, "p95")])
    report = gate.evaluate(MetricsCollector())
    # No samples → gate passes but is flagged as skipped.
    assert report.passed
    assert report.results[0].samples == 0
    assert "skipped" in report.results[0].reason


def test_higher_is_better_floor_direction():
    c = MetricsCollector()
    for _ in range(10):
        c.record_rate_event("filler_hit_rate", False)  # 0.0, below 0.80 floor
    report = RegressionGate([Threshold("filler_hit_rate", 0.80, "mean")]).evaluate(c)
    assert not report.passed


def test_custom_threshold_override_direction():
    c = MetricsCollector()
    c.record("custom_metric", 5.0)
    # Treat as higher-is-better with floor of 10 → should fail.
    th = Threshold("custom_metric", 10.0, "mean", higher_is_better=True)
    report = RegressionGate([th]).evaluate(c)
    assert not report.passed


def test_report_json_serializable():
    report = RegressionGate().evaluate(_healthy_collector())
    payload = json.loads(report.to_json())
    assert payload["passed"] is True
    assert payload["total"] == len(report.results)
    assert isinstance(payload["results"], list)


def test_end_to_end_replay_then_gate_fails_on_scaled_latency():
    # A regressed pipeline (4x latency) replayed → gate must fail.
    collector = MetricsCollector()
    ReplayHarness(make_mock_pipeline(timing_scale=4.0), collector=collector).run()
    report = RegressionGate().evaluate(collector)
    assert isinstance(report, GateReport)
    assert not report.passed


def test_end_to_end_replay_then_gate_passes_on_nominal_latency():
    collector = MetricsCollector()
    ReplayHarness(make_mock_pipeline(timing_scale=1.0), collector=collector).run()
    # Seed the quality metrics that the replay harness does not produce so the
    # full default gate set has data to evaluate.
    for _ in range(10):
        collector.record("wer", 0.1)
        collector.record("emotion_agreement", 0.9)
        collector.record("code_switch_score", 0.85)
        collector.record("naturalness_proxy", 0.88)
    report = RegressionGate().evaluate(collector)
    assert report.passed, report.summary()
