# Incident response (final_use.md §16C)

> **Goal:** make production boring. A short, explicit playbook for when SoulYatri
> degrades. Pairs with [`RUNBOOKS.md`](RUNBOOKS.md) (rollback) and
> [`../monitoring/dashboards_and_alerts.md`](../monitoring/dashboards_and_alerts.md).

## Severity levels

| Sev | Condition | Response time |
|---|---|---|
| **SEV1** | Voice loop down / no audio for most users | immediate, page on-call |
| **SEV2** | p95 latency or error-rate breach (rollback thresholds) | < 15 min |
| **SEV3** | Single region degraded; others healthy | < 1 hour |
| **SEV4** | Cosmetic / non-user-facing | next business day |

## Detection

* **Alerts** ([`../monitoring/alerts.rules.yml`](../monitoring/alerts.rules.yml)):
  `HighE2ELatencyP95`, `HighErrorRate`, `HighLLMTTFTP95`, `SessionPoolSaturated`.
* **Canary evaluator** ([`rollback.py`](rollback.py)) returning `rollback`.
* These mirror the same thresholds as `release_policy.yaml`, so alerting and rollout
  agree on "unhealthy".

## Triage decision tree

1. **Is a deploy in flight?** → If yes and metrics breached, **roll back first**
   (RUNBOOKS §3), ask questions after. Reverting to the previous pinned digest is the
   fastest safe action.
2. **Is it one region?** → `RegionRouter.set_health(region, False)`. Traffic shifts to
   the configured `fallbacks` chain automatically; drain the bad region.
3. **Is the pool saturated?** → Check `SessionScheduler.snapshot()` (`queue_depth`,
   per-worker `utilization`). Scale workers or raise envelopes; backpressure is already
   protecting latency by rejecting rather than queueing unboundedly.
4. **Is a dependency down?** (Ollama / Redis / Postgres / Qdrant) → the voice loop
   should degrade via the aux fallback path (`aux/fallback/orchestrator.py`); confirm it
   engaged. Restore the dependency.

## Mitigation levers (fastest → slowest)

1. Roll back to previous image digest (RUNBOOKS §3).
2. Mark the degraded region unhealthy → fallback routing.
3. Reduce canary traffic percent to 0.
4. Scale the worker pool / adjust `GpuEnvelope` caps.
5. Disable optional features (filler, emotion, speaker) via env to shed compute.

## Communication

* Open an incident channel; assign an **incident commander** and a **scribe**.
* Post the active SEV, user impact, current hypothesis, and next checkpoint time.
* On resolution, post the all-clear and link the timeline.

## Postmortem

Within 48h of SEV1/SEV2, write a blameless postmortem in `runs/` covering: timeline,
detection latency, root cause, what mitigated it, and concrete action items (with
owners). Update thresholds in `release_policy.yaml` / `alerts.rules.yml` if they failed
to catch the issue early enough.
