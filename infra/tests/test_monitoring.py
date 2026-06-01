"""
Tests for infra.monitoring (Phase 16 monitoring) and infra.obs.

Covers: the metric catalogue stays consistent with what the server exposes from
/metrics, the prometheus helper validates a broken config, and the structured-logging
+ telemetry hooks work without structlog/prometheus running.
"""

from __future__ import annotations

import re
from pathlib import Path

from infra.monitoring import SERVER_METRIC_NAMES, validate_prometheus_config
from infra.obs import TelemetryRecorder, get_logger

SERVER_METRICS_PY = (
    Path(__file__).resolve().parents[2] / "server" / "utils" / "metrics.py"
)


def test_server_metric_names_exist_in_server_metrics_module() -> None:
    """Every name we monitor must actually be defined in server/utils/metrics.py.

    This keeps dashboards/alerts grounded in metrics the server really exposes
    (final_use.md §15A: "every delay has a measurable origin").
    """
    src = SERVER_METRICS_PY.read_text(encoding="utf-8")
    defined = set(re.findall(r'"(soulyatri_[a-z0-9_]+)"', src))
    missing = [m for m in SERVER_METRIC_NAMES if m not in defined]
    assert not missing, f"monitored metrics not found in server metrics.py: {missing}"


def test_validate_catches_missing_keys() -> None:
    problems = validate_prometheus_config({})
    assert any("global" in p for p in problems)
    assert any("scrape_configs" in p for p in problems)


def test_validate_catches_job_without_targets() -> None:
    bad = {
        "global": {},
        "scrape_configs": [{"job_name": "soulyatri-server", "static_configs": []}],
    }
    problems = validate_prometheus_config(bad)
    assert any("no static targets" in p for p in problems)


def test_validate_requires_soulyatri_job() -> None:
    cfg = {
        "global": {},
        "scrape_configs": [
            {"job_name": "other", "static_configs": [{"targets": ["x:1"]}]}
        ],
    }
    problems = validate_prometheus_config(cfg)
    assert any("soulyatri" in p for p in problems)


# ---------------------------------------------------------------------------
# obs — structured logging + telemetry
# ---------------------------------------------------------------------------
def test_get_logger_supports_kwargs_call_style() -> None:
    logger = get_logger("infra.tests")
    # Must not raise regardless of whether structlog is installed.
    logger.info("unit_event", key="value", n=1)
    logger.warning("warn_event")


def test_telemetry_recorder_records_and_filters() -> None:
    rec = TelemetryRecorder(maxlen=10)
    rec.record("a", x=1)
    rec.record("b", y=2)
    rec.record("a", x=3)
    assert rec.count() == 3
    assert rec.count("a") == 2
    last_a = rec.last("a")
    assert last_a is not None and last_a.fields["x"] == 3
    assert rec.last("b").to_dict()["name"] == "b"
    rec.clear()
    assert rec.count() == 0


def test_telemetry_recorder_is_bounded() -> None:
    rec = TelemetryRecorder(maxlen=3)
    for i in range(10):
        rec.record("e", i=i)
    assert rec.count() == 3  # ring buffer drops oldest
