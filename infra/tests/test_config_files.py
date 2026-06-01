"""
Config-file validation (Phase 16C / monitoring).

Parses the YAML config files this domain owns with ``yaml.safe_load`` and asserts the
required keys are present, per the Definition of Done. These tests do not require any
running services (no Prometheus, no Docker daemon).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from infra.deploy.rollback import RollbackEvaluator, load_release_policy
from infra.monitoring import (
    load_prometheus_config,
    scrape_job_names,
    validate_prometheus_config,
)

INFRA_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = INFRA_ROOT / "deploy"
DOCKER = INFRA_ROOT / "docker"
MONITORING = INFRA_ROOT / "monitoring"


# ---------------------------------------------------------------------------
# release_policy.yaml
# ---------------------------------------------------------------------------
def test_release_policy_parses_and_has_required_keys() -> None:
    path = DEPLOY / "release_policy.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data["rollout"] == "canary"
    assert "rollback_trigger" in data
    trigger = data["rollback_trigger"]
    # The §16C skeleton keys must exist.
    assert "p95_ttfb_ms" in trigger
    assert "error_rate_pct" in trigger
    assert isinstance(trigger["p95_ttfb_ms"], (int, float))


def test_release_policy_loads_into_evaluator() -> None:
    policy = load_release_policy(DEPLOY / "release_policy.yaml")
    evaluator = RollbackEvaluator(policy)
    # Breaching the configured p95 ceiling must roll back end-to-end from the real file.
    limit = policy.threshold_for("p95_ttfb_ms").limit
    decision = evaluator.evaluate({"p95_ttfb_ms": limit + 1})
    assert decision.should_rollback is True


# ---------------------------------------------------------------------------
# prometheus.yml + alerts.rules.yml
# ---------------------------------------------------------------------------
def test_prometheus_config_parses_and_valid() -> None:
    config = load_prometheus_config(MONITORING / "prometheus.yml")
    assert "global" in config
    assert "scrape_configs" in config
    problems = validate_prometheus_config(config)
    assert problems == [], f"prometheus config problems: {problems}"


def test_prometheus_has_server_scrape_job() -> None:
    config = load_prometheus_config(MONITORING / "prometheus.yml")
    names = scrape_job_names(config)
    assert any("soulyatri" in n for n in names)


def test_alerts_rules_parse_and_have_groups() -> None:
    path = MONITORING / "alerts.rules.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "groups" in data and data["groups"]
    # Every rule has an alert name + expr.
    for group in data["groups"]:
        assert "name" in group
        for rule in group.get("rules", []):
            assert "alert" in rule
            assert "expr" in rule


# ---------------------------------------------------------------------------
# docker-compose.full.yml
# ---------------------------------------------------------------------------
def test_compose_full_parses_and_has_model_stack_services() -> None:
    path = DOCKER / "docker-compose.full.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    services = data.get("services", {})
    # Must extend the root patterns (livekit + redis) and add the model-stack stores.
    for required in ("livekit", "redis", "postgres", "qdrant", "server", "prometheus"):
        assert required in services, f"missing service: {required}"

    # The server is built from our Dockerfile, not pulled.
    assert services["server"]["build"]["dockerfile"] == "infra/docker/Dockerfile.server"

    # Prometheus mounts our scrape config.
    vols = services["prometheus"]["volumes"]
    assert any("prometheus.yml" in v for v in vols)


def test_compose_full_declares_named_volumes() -> None:
    path = DOCKER / "docker-compose.full.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    volumes = data.get("volumes", {})
    for required in ("redis_data", "postgres_data", "qdrant_data", "prometheus_data"):
        assert required in volumes


def test_dockerfile_server_exists_and_exposes_port() -> None:
    path = DOCKER / "Dockerfile.server"
    text = path.read_text(encoding="utf-8")
    assert "EXPOSE 8000" in text
    assert "uvicorn" in text
    # CPU-safe default + non-root user (release hardening).
    assert "USER soulyatri" in text


def test_root_compose_untouched_reference() -> None:
    """Sanity: the root compose still exists and we did not delete its services."""
    root = INFRA_ROOT.parent / "docker-compose.yml"
    data = yaml.safe_load(root.read_text(encoding="utf-8"))
    services = data.get("services", {})
    assert "livekit" in services and "redis" in services
