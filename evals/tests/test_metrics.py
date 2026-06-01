"""Tests for the metric registry + percentile aggregation (Phase 15A)."""

from __future__ import annotations

import pytest

from evals.latency.metrics import (
    METRIC_REGISTRY,
    STAGE_LATENCY_METRICS,
    Distribution,
    MetricsCollector,
    metric_names,
    percentile,
)


# ---------------------------------------------------------------------------
# Registry coverage
# ---------------------------------------------------------------------------
def test_registry_contains_required_metrics():
    required = {
        "time_to_first_audible_ms",
        "first_token_ms",
        "turn_end_detection_delay_ms",
        "interruption_recovery_ms",
        "filler_hit_rate",
        "filler_false_positive_rate",
    }
    assert required.issubset(set(METRIC_REGISTRY))


def test_registry_includes_per_stage_breakdown():
    for stage in STAGE_LATENCY_METRICS:
        assert stage in METRIC_REGISTRY


def test_metric_names_sorted_and_unique():
    names = metric_names()
    assert names == sorted(names)
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Percentile correctness
# ---------------------------------------------------------------------------
def test_percentile_empty_is_zero():
    assert percentile([], 50) == 0.0


def test_percentile_single_value():
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 99) == 42.0


def test_percentile_known_values_linear_interpolation():
    data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    # numpy default ("linear") percentile reference values.
    assert percentile(data, 50) == pytest.approx(5.5)
    assert percentile(data, 95) == pytest.approx(9.55)
    assert percentile(data, 99) == pytest.approx(9.91)
    assert percentile(data, 0) == 1.0
    assert percentile(data, 100) == 10.0


def test_percentile_even_length_p50_is_midpoint():
    assert percentile([10.0, 20.0], 50) == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Collector aggregation
# ---------------------------------------------------------------------------
def test_collector_distribution_p50_p95_p99():
    c = MetricsCollector()
    for v in range(1, 101):  # 1..100
        c.record("time_to_first_audible_ms", float(v))
    dist = c.distribution("time_to_first_audible_ms")
    assert isinstance(dist, Distribution)
    assert dist.count == 100
    assert dist.p50 == pytest.approx(percentile([float(v) for v in range(1, 101)], 50))
    assert dist.p95 == pytest.approx(percentile([float(v) for v in range(1, 101)], 95))
    assert dist.p99 == pytest.approx(percentile([float(v) for v in range(1, 101)], 99))
    assert dist.min == 1.0
    assert dist.max == 100.0
    assert dist.mean == pytest.approx(50.5)


def test_collector_empty_distribution_is_zeroed():
    c = MetricsCollector()
    dist = c.distribution("unseen_metric")
    assert dist.count == 0
    assert dist.p50 == dist.p95 == dist.p99 == 0.0


def test_collector_rate_events():
    c = MetricsCollector()
    for hit in [True, True, True, False]:
        c.record_rate_event("filler_hit_rate", hit)
    assert c.mean("filler_hit_rate") == pytest.approx(0.75)


def test_collector_record_many_and_snapshot():
    c = MetricsCollector()
    c.record_many("first_token_ms", [100.0, 200.0, 300.0])
    snap = c.snapshot()
    assert "first_token_ms" in snap
    assert snap["first_token_ms"].count == 3


def test_collector_window_bounds_samples():
    c = MetricsCollector(window=10)
    for v in range(100):
        c.record("interruption_recovery_ms", float(v))
    # Only the last 10 samples are retained.
    assert c.count("interruption_recovery_ms") == 10
    assert c.values("interruption_recovery_ms")[0] == 90.0


def test_distribution_to_dict_round_trips_keys():
    c = MetricsCollector()
    c.record("wer", 0.1)
    d = c.distribution("wer").to_dict()
    assert set(d) == {"name", "count", "p50", "p95", "p99", "mean", "min", "max"}
