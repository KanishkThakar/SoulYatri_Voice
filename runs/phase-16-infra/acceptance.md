# Phase 16 — infra acceptance (Scaling, concurrency, regional routing, deployment hardening)

**Owner:** infra/SRE agent · **Scope:** `infra/` only · **Mode:** CPU-only, no cluster/GPU/live services.

## What was built

| Micro-phase | Deliverable | Location |
|---|---|---|
| 16A | GPU resource envelopes (max sessions per GPU class/VRAM) | `infra/scaling/envelopes.py` |
| 16A | `SessionScheduler` — bounded concurrency, max-depth queue, backpressure/rejection, sticky routing, FIFO promotion | `infra/scaling/scheduler.py` |
| 16B | `RegionRouter` + `WarmPool` — nearest/affinity/warm routing, health-aware fallback chain | `infra/deploy/regions.py` |
| 16B | Deployment topology design doc | `infra/deploy/deployment_topology.md` |
| 16C | `RollbackEvaluator` + `ReleasePolicy` — canary rollback/hold/promote from metrics | `infra/deploy/rollback.py` |
| 16C | Canary + rollback thresholds | `infra/deploy/release_policy.yaml` |
| 16C | Server image (CPU-safe, non-root, /metrics healthcheck) | `infra/docker/Dockerfile.server` |
| 16C | Full stack = root patterns + Postgres + Qdrant + server + Prometheus | `infra/docker/docker-compose.full.yml` |
| 16C | Pinned-version notes | `infra/docker/PINNED_VERSIONS.md` |
| 16C | Staging/canary/rollback runbooks + incident response | `infra/deploy/RUNBOOKS.md`, `infra/deploy/INCIDENT_RESPONSE.md` |
| mon | Prometheus scrape config + alert rules + helper | `infra/monitoring/prometheus.yml`, `alerts.rules.yml`, `prometheus.py` |
| mon | Dashboards/alerts design doc | `infra/monitoring/dashboards_and_alerts.md` |
| — | Structured logging + telemetry hooks | `infra/obs.py` |
| — | Design note | `infra/README.md` |

## Acceptance mapping (final_use.md §16)

- **16A "sessions do not starve each other":** scheduler never overcommits a worker,
  spreads to the least-loaded worker, bounds the queue, and rejects under saturation.
  Tested in `infra/tests/test_scheduler.py` + `test_envelopes.py`.
- **16B "p95 latency controlled across geography":** region router prefers warm/affine
  nearest regions and falls back deterministically when a region is unhealthy. Tested in
  `infra/tests/test_regions.py`.
- **16C "rollback is proven":** evaluator fires `rollback` on threshold breach loaded
  from the real `release_policy.yaml`. Tested in `infra/tests/test_rollback.py` +
  `test_config_files.py`.

## Verification

Commands run from repo root:

```
python -c "import infra"
python -m pytest infra -q -p no:cacheprovider --timeout=60
python -m ruff check infra
```

Results recorded below (see PR/CI log):
- import: OK
- pytest: PASS (see summary line)
- ruff: clean

## Notes / non-goals

- Root `docker-compose.yml` left untouched; full stack extends its patterns.
- Latency is *estimated* (haversine) for deterministic, cluster-free tests.
- Image tags pinned to minor versions; production must pin to digests (PINNED_VERSIONS.md).
