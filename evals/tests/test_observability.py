"""Tests for structured logging + Prometheus-style exposition (Phase 15A)."""

from __future__ import annotations

from evals.latency.metrics import MetricsCollector
from evals.observability import (
    EventLog,
    get_logger,
    log_snapshot,
    render_prometheus,
    render_structured_lines,
)


def _populated_collector() -> MetricsCollector:
    c = MetricsCollector()
    for v in [200.0, 220.0, 260.0, 300.0]:
        c.record("time_to_first_audible_ms", v)
    c.record_rate_event("filler_hit_rate", True)
    c.record_rate_event("filler_hit_rate", False)
    return c


def test_get_logger_supports_kwargs():
    log = get_logger("evals.test")
    # Must not raise whether structlog is present or the stdlib adapter is used.
    log.info("unit_test_event", value=1, ok=True)


def test_event_log_records_and_queries():
    log = EventLog()
    log.emit("alpha", x=1)
    log.emit("beta", y=2)
    log.emit("alpha", x=3)
    assert len(log.events("alpha")) == 2
    assert log.last("beta").fields["y"] == 2
    assert log.last().name == "alpha"


def test_event_log_clear():
    log = EventLog()
    log.emit("e")
    log.clear()
    assert log.events() == []


def test_render_prometheus_contains_help_type_and_series():
    text = render_prometheus(_populated_collector())
    assert "# HELP soulyatri_eval_time_to_first_audible_ms" in text
    assert "# TYPE soulyatri_eval_time_to_first_audible_ms" in text
    # latency metric expands to p50/p95/p99/count series.
    assert "soulyatri_eval_time_to_first_audible_ms_p50" in text
    assert "soulyatri_eval_time_to_first_audible_ms_p95" in text
    assert "soulyatri_eval_time_to_first_audible_ms_p99" in text
    assert "soulyatri_eval_time_to_first_audible_ms_count" in text
    # rate metric renders a single mean series (no percentile suffix).
    assert "soulyatri_eval_filler_hit_rate " in text


def test_render_prometheus_empty_collector_is_empty_string():
    assert render_prometheus(MetricsCollector()) == ""


def test_render_structured_lines_returns_dicts():
    lines = render_structured_lines(_populated_collector())
    assert isinstance(lines, list)
    assert all(isinstance(d, dict) for d in lines)
    names = {d["name"] for d in lines}
    assert "time_to_first_audible_ms" in names


def test_log_snapshot_emits_one_event_per_metric():
    collector = _populated_collector()
    log = log_snapshot(collector)
    snapshots = log.events("metric_snapshot")
    assert len(snapshots) == len(collector.names())
    assert snapshots[0].fields["p50"] is not None
