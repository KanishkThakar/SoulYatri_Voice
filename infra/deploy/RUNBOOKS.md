# Release runbooks — staging / canary / rollback (final_use.md §16C)

> **Goal:** "staging is reproducible and rollback is proven." The thresholds referenced
> here are encoded in [`release_policy.yaml`](release_policy.yaml) and evaluated by
> [`infra/deploy/rollback.py`](rollback.py).

## 0. Prerequisites

* Image built + pinned per [`infra/docker/PINNED_VERSIONS.md`](../docker/PINNED_VERSIONS.md).
* Prometheus scraping `/metrics` via [`infra/monitoring/prometheus.yml`](../monitoring/prometheus.yml).
* The full stack runs locally with:
  ```bash
  docker compose -f docker-compose.yml -f infra/docker/docker-compose.full.yml up
  ```

## 1. Staging (reproducible)

1. Deploy the candidate image to the staging environment (same compose topology as prod,
   smaller worker pool).
2. Run the eval/replay suite (Phase 15B) against staging.
3. Confirm `/metrics` is scraped and the dashboards render (see
   [`../monitoring/dashboards_and_alerts.md`](../monitoring/dashboards_and_alerts.md)).
4. Record the acceptance note in `runs/`.

**Exit criteria:** all regression gates (Phase 15C) green on staging.

## 2. Canary rollout

`release_policy.yaml` declares `rollout: canary` with stages `canary (10%) → ramp (50%)
→ full (100%)`.

1. Shift `canary.percent` (10%) of traffic to the new version.
2. Collect canary metrics for `bake_minutes` and at least `canary.min_samples` samples.
3. Feed observed metrics to the evaluator:
   ```python
   from infra.deploy.rollback import load_release_policy, RollbackEvaluator
   policy = load_release_policy("infra/deploy/release_policy.yaml")
   decision = RollbackEvaluator(policy).evaluate(
       {"p95_ttfb_ms": 410, "error_rate_pct": 0.4}, samples=240
   )
   # decision.action -> promote | hold | rollback
   ```
4. `promote` → advance to the next stage. `hold` → keep baking (insufficient samples).
   `rollback` → execute §3 immediately.

**Rollback triggers (from policy):** `p95_ttfb_ms > 450`, `p99_ttfb_ms > 900`,
`error_rate_pct > 1.0`, `interruption_recovery_ms > 350`.

## 3. Rollback (proven)

1. The evaluator returns `action == "rollback"` (or an alert in
   [`../monitoring/alerts.rules.yml`](../monitoring/alerts.rules.yml) fires).
2. Re-pin the load balancer / orchestrator to the **previous** pinned image digest.
3. Drain canary workers: stop new admissions (`SessionScheduler`), let sticky sessions
   finish, then terminate.
4. Verify metrics return below thresholds; confirm `decision.should_rollback` is no
   longer produced on the stable version.
5. Open an incident per [`INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md) and record the
   rollback in `runs/`.

**Proof of rollback:** the evaluator is unit-tested to fire on threshold breach
(`infra/tests/test_rollback.py`), and the previous image digest is always retained
(PINNED_VERSIONS policy), so revert is a single re-pin.

## 4. Quick reference

| Verdict | Meaning | Action |
|---|---|---|
| `promote` | within thresholds, enough samples | advance canary stage |
| `hold` | within thresholds, too few samples | keep baking |
| `rollback` | a threshold breached | revert to previous digest now |
