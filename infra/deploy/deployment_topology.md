# Deployment topology — regional runtime layout (final_use.md §16B)

> **Owner:** infra/SRE agent. **Goal:** "p95 latency stays controlled across target
> geography" via region routing, edge placement near users, fallback-region behaviour,
> and warm model pools. The importable realization is
> [`infra/deploy/regions.py`](regions.py).

## 1. Target geography

SoulYatri is Hindi + English + Hinglish first, so the **home region is India**
(`ap-south-1`, Mumbai). Warm secondaries sit in Singapore (`ap-southeast-1`) and
Frankfurt (`eu-central-1`) to cover diaspora users and to provide failover capacity.
`infra.deploy.regions.default_india_first_topology()` encodes this as a runnable default.

## 2. Layered placement

```text
User device
  │  (Opus / WebRTC — lowest possible RTT)
  ▼
Edge PoP  ── turn detection, VAD, emotion/speaker features, barge-in (Phase 4)
  │  (codec tokens, not raw audio, cross the backbone)
  ▼
Regional runtime  ── Mimi ↔ Moshi speech-native core + decoder (Phases 5/6/10)
  │
  ▼
Regional data tier ── Redis (hot, L2) · Postgres (profile, L4) · Qdrant (semantic, L3)
```

* **Edge placement** keeps the latency-sensitive, lightweight work (VAD, turn-state,
  feature extraction) physically close to users. Only codec tokens traverse the
  backbone to the regional GPU runtime, which bounds bandwidth and RTT.
* **Regional runtime** hosts the GPU workers sized by
  [`infra.scaling.GpuEnvelope`](../scaling/envelopes.py). The
  [`SessionScheduler`](../scaling/scheduler.py) admits sessions per worker and applies
  backpressure when saturated.
* **Data tier** is co-located per region to keep memory reads bounded (INTERFACES.md §6).

## 3. Region routing

`RegionRouter.route(user, preferred_region)` chooses a region by an **effective cost**
(lower is better):

```text
cost(region) = estimated_latency_ms(region, user)
               − affinity_bonus_ms   (if region == user's preferred/home region)
               − warm_bonus_ms       (if region has a warm replica ready)
```

* `estimated_latency_ms` = the region's `edge_latency_ms` floor + a haversine
  distance-derived RTT estimate. Deterministic, no network calls — so it is testable.
* **Affinity** keeps a user pinned to their home region for session continuity and to
  avoid cross-region cache misses.
* **Warm-pool bonus** prefers regions that can serve **without a cold start**, which is
  the single biggest p95 risk for model runtimes.

### Resolution order

1. Preferred region is **healthy + has capacity** → use it (`affinity`).
2. Preferred region ineligible → walk its configured `fallbacks` chain in order
   (`fallback`).
3. Chain exhausted (or no preference given) → global lowest-effective-cost healthy
   region (`last_resort` / `nearest`).
4. Nothing healthy with capacity → `none` (caller sheds load / shows graceful busy).

## 4. Fallback-region behaviour

Each `Region` declares an ordered `fallbacks` list. When a region is marked unhealthy
(`RegionRouter.set_health(name, False)`) — e.g. by a health probe or an incident — new
sessions deterministically shift to the next healthy region in the chain. Existing
sticky sessions are drained by the `SessionScheduler` (they finish on their current
worker; no new admissions to the unhealthy region).

## 5. Warm model pools

`WarmPool(warm, in_use, capacity)` models pre-loaded replicas:

* `available_warm = warm − in_use` → replicas that serve **immediately**.
* `has_capacity = in_use < capacity` → whether the region can take one more session.
* `is_warm_ready` → a warm replica is free **and** the region has capacity.

Operators keep `warm ≥ expected concurrent new-session rate × cold_start_seconds` so the
router can almost always pick a warm region. Cold starts are a fallback, not the norm.

## 6. How this controls p95

* Edge placement minimizes the fixed RTT term.
* Warm pools remove cold-start spikes (the dominant p95 tail for model runtimes).
* Affinity avoids cross-region cache-miss penalties.
* Health-aware fallback prevents a degraded region from inflating the tail.
* Admission control ([scaling](../scaling/)) bounds queue latency so saturated workers
  reject rather than silently grow unbounded latency.
