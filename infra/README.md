# `infra/` — Scaling, concurrency, regional routing & deployment hardening

> **Owner:** infra/SRE agent (`final_use.md` §4).
> **Scope of this note:** Phase 16 — per-session budgeting (16A), regional runtime
> layout (16B), release hardening (16C), and monitoring config.
> **Prime directive (Agent prompt §16):** *make production boring.* Resource budgets,
> queues, rollout, rollback, and regional routing must be explicit and testable.

## CPU / no-cluster guarantee

Everything here imports and unit-tests on a CPU-only machine with **no cluster, GPU, or
live services**. The Python modules are pure, deterministic, and side-effect-free
(besides structured logging + in-memory telemetry). Heavy/optional deps (`structlog`,
`pyyaml`) are imported **lazily** with clean fallbacks.

```bash
python -c "import infra"
python -m pytest infra -q
ruff check infra
```

The repo-root `docker-compose.yml` (LiveKit + Redis) is **not modified**; the full
stack lives in `infra/docker/docker-compose.full.yml` and extends those patterns.

## Module map

| Phase | Path | Purpose |
|---|---|---|
| 16A | `infra/scaling/envelopes.py` | `GpuClass` / `SessionProfile` / `GpuEnvelope` — max sessions per GPU class/VRAM. |
| 16A | `infra/scaling/scheduler.py` | `SessionScheduler` — bounded concurrency, max-depth queue, backpressure/rejection, sticky session→worker routing, FIFO promotion on release. |
| 16B | `infra/deploy/regions.py` | `RegionRouter` — nearest-region by effective cost, affinity, warm-pool bias, health-aware fallback chain, `WarmPool` model. |
| 16B | `infra/deploy/deployment_topology.md` | Regional layout design doc (edge placement, fallback, warm pools, p95 control). |
| 16C | `infra/deploy/rollback.py` | `RollbackEvaluator` — decides rollback/hold/promote from canary metrics vs `release_policy.yaml`. |
| 16C | `infra/deploy/release_policy.yaml` | Canary + rollback thresholds (the §16C skeleton, extended). |
| 16C | `infra/docker/Dockerfile.server` | CPU-safe, non-root, `/metrics`-healthchecked server image. |
| 16C | `infra/docker/docker-compose.full.yml` | Extends root (LiveKit+Redis) with Postgres + Qdrant + server + Prometheus. |
| 16C | `infra/docker/PINNED_VERSIONS.md` | Image/runtime pin policy. |
| 16C | `infra/deploy/RUNBOOKS.md` | Staging / canary / rollback runbooks. |
| 16C | `infra/deploy/INCIDENT_RESPONSE.md` | Incident-response playbook. |
| mon | `infra/monitoring/prometheus.py` | Scrape-config loader/validator + the server metric catalogue. |
| mon | `infra/monitoring/prometheus.yml` | Prometheus scrape config (server `/metrics`, livekit, self). |
| mon | `infra/monitoring/alerts.rules.yml` | Alert rules; thresholds mirror `release_policy.yaml`. |
| mon | `infra/monitoring/dashboards_and_alerts.md` | Dashboards/alerts design doc grounded in real metrics. |
| — | `infra/obs.py` | Structured-logging shim (structlog-or-stdlib) + in-memory `TelemetryRecorder`. |

## 16A — Per-session budgeting & admission control

`SessionScheduler` is the testable realization of "sessions do not starve each other":

* **Worker-pool sizing** — each worker is a `GpuEnvelope` (GPU class × session profile).
  `max_sessions = min(VRAM capacity, operator hard cap)`.
* **Bounded concurrency** — global capacity = sum of per-worker envelopes; a worker is
  never overcommitted.
* **Queue + backpressure** — a FIFO admit-queue with `max_queue_depth`. When the pool
  **and** queue are full, `admit()` returns `AdmissionStatus.rejected` (explicit
  backpressure) instead of unbounded buffering. A `reject` policy disables queueing
  entirely.
* **Sticky routing** — a `session_id` maps to one worker for its lifetime (speaker /
  emotion continuity, INTERFACES.md §5); re-admitting the same id is idempotent.
* **Fair release** — `release()` frees the slot and promotes the FIFO queue head onto
  the freed worker.

Every decision emits an `infra_admission` / `infra_release` telemetry event.

## 16B — Regional runtime layout

`RegionRouter.route(user, preferred_region)` picks a region by **effective cost**
(`estimated_latency_ms − affinity_bonus − warm_bonus`), skipping unhealthy or
capacity-exhausted regions. If the preferred region is down it walks the configured
`fallbacks` chain, then the global best. `default_india_first_topology()` provides a
runnable India-first reference (Mumbai primary, Singapore + Frankfurt warm secondaries).
Latency is **estimated from coordinates** (haversine) so the policy is deterministic and
needs no cloud. See `deployment_topology.md` for the full design.

## 16C — Release hardening

`release_policy.yaml` declares `rollout: canary` and the rollback thresholds
(`p95_ttfb_ms`, `p99_ttfb_ms`, `error_rate_pct`, `interruption_recovery_ms`).
`RollbackEvaluator.evaluate(metrics, samples=…)` returns:

* `rollback` — a threshold was breached (fail fast, fail safe),
* `hold` — within thresholds but fewer than `min_canary_samples` observed,
* `promote` — healthy and enough evidence to advance.

The thresholds are reused by the Prometheus alert rules, so automated rollback and human
paging agree on "unhealthy". `Dockerfile.server` + `docker-compose.full.yml` reproduce
the full stack locally; `RUNBOOKS.md` / `INCIDENT_RESPONSE.md` make staging reproducible
and rollback a single re-pin to the previous digest.

## Monitoring

`SERVER_METRIC_NAMES` mirrors `server/utils/metrics.py`; a test fails if they drift.
The scrape config and alert rules are config only and validated by tests
(`yaml.safe_load` + required-key assertions) — no running Prometheus required.

## Definition of Done (`final_use.md` §3.3)

- ✅ **Code** — `infra/scaling/` (16A), `infra/deploy/regions.py` (16B),
  `infra/deploy/rollback.py` (16C), `infra/monitoring/prometheus.py`.
- ✅ **Tests** — `infra/tests/` covering scheduler admission/backpressure/sticky-routing,
  GPU envelope limits, region routing + fallback selection, rollback firing on breach,
  and config-file parsing (compose/prometheus/release_policy).
- ✅ **Design note** — this file + `deployment_topology.md` + the runbook/incident docs.
- ✅ **Structured logging hooks** — `infra/obs.py` (`get_logger` + `telemetry`) wired
  through the scheduler, region router, and rollback evaluator.
- ✅ **Acceptance result** — `runs/phase-16-infra/acceptance.md`.

## Handoff notes for adjacent teams

- **Server/runtime:** call `SessionScheduler.admit(session_id)` at session start and
  `release(session_id)` at end; honour `AdmissionStatus.rejected` (return a graceful
  "busy" to the client). Export `snapshot()` fields as gauges for the capacity dashboard.
- **Edge/gateway:** call `RegionRouter.route(user_geo, preferred_region)` to place a new
  session; persist the chosen region as the user's affinity for continuity.
- **Release automation:** feed canary metrics into `RollbackEvaluator`; on
  `should_rollback`, execute `RUNBOOKS.md` §3 (re-pin previous digest).
