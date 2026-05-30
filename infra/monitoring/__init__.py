"""
infra.monitoring — observability config + helpers (final_use.md §15A / Phase 16).

Config-first and dependency-light: a Prometheus scrape config (``prometheus.yml``),
alerting rules (``alerts.rules.yml``), and a dashboards/alerts design doc
(``dashboards_and_alerts.md``). The small helper validates the config and exposes the
metric names the server emits from ``/metrics`` so dashboards stay grounded in reality.

Nothing here requires a running Prometheus.
"""

from infra.monitoring.prometheus import (
    REQUIRED_SCRAPE_KEYS,
    SERVER_METRIC_NAMES,
    config_path,
    load_prometheus_config,
    scrape_job_names,
    validate_prometheus_config,
)

__all__ = [
    "SERVER_METRIC_NAMES",
    "REQUIRED_SCRAPE_KEYS",
    "config_path",
    "load_prometheus_config",
    "scrape_job_names",
    "validate_prometheus_config",
]
