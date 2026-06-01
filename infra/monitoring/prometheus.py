"""
infra.monitoring.prometheus — scrape config helper (Phase 16 / §15A bridge)
===========================================================================
A tiny, dependency-light helper around the Prometheus scrape config that lives next to
this module (``prometheus.yml``). It does **not** require a running Prometheus — it only
loads/validates the config and exposes the set of metric names the SoulYatri server
emits from ``/metrics`` so dashboards/alerts stay consistent with reality.

The metric catalogue here is kept in sync with ``server/utils/metrics.py`` (all metrics
use the ``soulyatri_`` prefix). The §16C rollback evaluator's thresholds map onto these.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from infra.obs import get_logger

__all__ = [
    "SERVER_METRIC_NAMES",
    "REQUIRED_SCRAPE_KEYS",
    "config_path",
    "load_prometheus_config",
    "scrape_job_names",
    "validate_prometheus_config",
]

logger = get_logger("infra.monitoring.prometheus")

# Metric base-names exposed by server/utils/metrics.py via /metrics. Histograms also emit
# _bucket/_sum/_count and counters emit _total in the wire format; these are the logical
# series names dashboards/alerts reference.
SERVER_METRIC_NAMES: tuple[str, ...] = (
    "soulyatri_vad_latency_seconds",
    "soulyatri_stt_latency_seconds",
    "soulyatri_llm_ttft_seconds",
    "soulyatri_llm_total_latency_seconds",
    "soulyatri_tts_latency_seconds",
    "soulyatri_pipeline_e2e_latency_seconds",
    "soulyatri_vad_speech_segments_total",
    "soulyatri_stt_transcriptions_total",
    "soulyatri_llm_requests_total",
    "soulyatri_tts_requests_total",
    "soulyatri_errors_total",
    "soulyatri_active_sessions",
    "soulyatri_active_streams",
    "soulyatri_filler_played_total",
    "soulyatri_filler_hit_rate_total",
    "soulyatri_emotion_latency_seconds",
    "soulyatri_speaker_similarity",
    "soulyatri_barge_in_total",
    "soulyatri_turn_state_transitions_total",
)

# Keys a valid scrape config must contain.
REQUIRED_SCRAPE_KEYS: tuple[str, ...] = ("global", "scrape_configs")


def config_path() -> Path:
    """Absolute path to the bundled ``prometheus.yml``."""
    return Path(__file__).with_name("prometheus.yml")


def load_prometheus_config(path: str | Path | None = None) -> dict[str, Any]:
    """Parse the Prometheus scrape config (``yaml.safe_load``). Lazy ``pyyaml`` import."""
    import yaml  # noqa: PLC0415 (intentional lazy/optional import)

    p = Path(path) if path is not None else config_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("prometheus config must be a mapping")
    return data


def scrape_job_names(config: dict[str, Any]) -> list[str]:
    """Return the ``job_name`` of each configured scrape target."""
    jobs = config.get("scrape_configs", []) or []
    return [str(j.get("job_name", "")) for j in jobs]


def validate_prometheus_config(config: dict[str, Any]) -> list[str]:
    """Return a list of problems with the config (empty list == valid).

    Checks: required top-level keys present, at least one scrape job, every job has a
    name + static targets, and the SoulYatri server job exists.
    """
    problems: list[str] = []
    for key in REQUIRED_SCRAPE_KEYS:
        if key not in config:
            problems.append(f"missing top-level key: {key}")

    jobs = config.get("scrape_configs", []) or []
    if not jobs:
        problems.append("no scrape_configs defined")

    names = scrape_job_names(config)
    for i, job in enumerate(jobs):
        if not job.get("job_name"):
            problems.append(f"scrape_configs[{i}] missing job_name")
        targets = []
        for sc in job.get("static_configs", []) or []:
            targets.extend(sc.get("targets", []) or [])
        if not targets:
            problems.append(f"scrape job '{job.get('job_name', i)}' has no static targets")

    if not any("soulyatri" in n for n in names):
        problems.append("no scrape job for the soulyatri server")

    if problems:
        logger.warning("prometheus_config_invalid", problems=problems)
    return problems
