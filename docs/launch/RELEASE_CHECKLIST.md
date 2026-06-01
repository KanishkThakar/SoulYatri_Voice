# RELEASE_CHECKLIST — Preflight & Release Gate (Phase 18B)

> **Source:** `final_use.md` §Phase 18B (preflight checks), §8 (cross-phase acceptance:
> §8.1 latency, §8.2 quality, §8.3 safety), §14 (launch-readiness checklist),
> `docs/LATENCY_TARGETS.md`.
> **Acceptance (final_use.md §18B):** *no launch proceeds without a checklist pass.*
>
> **Grounding rule:** every gate below cites a **real subsystem module** and/or a real
> `runs/<phase>/acceptance.md` record. Status is honest:
> - **DONE** — code + tests + acceptance present and CPU-verified.
> - **PENDING-EXTERNAL** — needs GPU / Moshi-Mimi weights / live services; cites the
>   `docs/MODEL_LOCKS.md` `pending-human-pin` row or `docs/OPEN_QUESTIONS.md` ID.
> - **TO-MEASURE** — logic exists and is tested, but real wall-clock numbers must be
>   measured on target hardware before the gate can show a live value.

---

## # Release Gate

> This is the §18B skeleton gate. It is the single go/no-go summary. Each line expands
> into the detailed preflight sections below. A launch proceeds **only** when every line
> is satisfied (DONE) or has an explicit, human-accepted PENDING-EXTERNAL waiver.

```md
# Release Gate
- [ ] latency gate passed
- [ ] safety gate passed
- [ ] watermark gate passed
- [ ] fallback tested
- [ ] rollback tested
- [ ] docs updated
- [ ] known risks logged
```

| Gate line | Status (this build) | Backed by |
|---|---|---|
| latency gate passed | **TO-MEASURE** (gate logic DONE on CPU; live numbers need hardware) | `evals/gates.py`, `evals/replay/harness.py` · `runs/phase-15-evals/acceptance.md` |
| safety gate passed | **DONE** (CPU-verified) | `safety/moderation/gate.py`, `safety/voice_policy/policy.py` · `runs/phase-11-safety/acceptance.md` |
| watermark gate passed | **DONE** (interface + fallback CPU-verified; real AudioSeal pin pending) | `safety/watermark/audioseal.py` · `runs/phase-11-safety/acceptance.md` · MODEL_LOCKS AudioSeal `pending-human-pin` |
| fallback tested | **DONE** (CPU-verified, stub backends) | `aux/fallback/orchestrator.py`, `aux/fallback/classic_baseline.py` · `runs/phase-7-13-aux/acceptance.md` |
| rollback tested | **DONE** (evaluator + policy CPU-verified; live rehearsal pending) | `infra/deploy/rollback.py`, `infra/deploy/release_policy.yaml` · `runs/phase-16-infra/acceptance.md` |
| docs updated | **DONE** | `docs/index.md`, `docs/code/*`, `docs/training/*` · `runs/phase-17-docs/acceptance.md` |
| known risks logged | **DONE** | `docs/RISKS.md`, `docs/OPEN_QUESTIONS.md` |

---

## 1. Latency preflight (`final_use.md` §8.1 + `docs/LATENCY_TARGETS.md`)

The latency gates are **staged targets**, not day-one guarantees. The regression-gate
*machinery* is implemented and CPU-verified; the *live values* must be measured on target
hardware once Moshi/Mimi weights and a GPU are available.

| # | Preflight check | Gate target (LATENCY_TARGETS.md) | Subsystem / acceptance | Status |
|---|---|---|---|---|
| L1 | Stable bidirectional audio path before intelligence (Gate 0). | reconnect survival + jitter resilience | `client/src/audio/*`, `edge/webrtc_gateway/gateway.py` · `runs/phase-2-3-client/acceptance.md` | **DONE** (reconnect/jitter tests pass; raw audio latency not yet optimized) |
| L2 | Visible TTFA improvement after local filler (Gate 1). | `filler_hit_rate` up, `filler_false_positive_rate` bounded | `client/src/router/filler_engine.ts`, `edge/planner/short_turn.py` · `runs/phase-2-3-client/acceptance.md`, `runs/phase-4-8-edge/acceptance.md` | **DONE** (deterministic, bounded, disableable; perceived-latency win not yet measured live) |
| L3 | Sub-300 ms class first-audible ambition (Gate 2). | TTFA ~150–300 ms compute; <~80 ms perceived | `evals/gates.py` defaults, `evals/replay/harness.py` | **TO-MEASURE** (gate thresholds coded; needs GPU + Moshi/Mimi — Q-008, MODEL_LOCKS Moshi/Mimi) |
| L4 | Clean interruption stop budget (Gate 3, low-hundreds ms). | `interruption_recovery_ms` p50/p95 bounded | `speech/decoder/interruption.py`, `edge/barge_in/detector.py` · `runs/phase-5-6-10-speech/acceptance.md`, `runs/phase-4-8-edge/acceptance.md` | **DONE** (fade/hard-cut within budget on mock; live budget TO-MEASURE) |
| L5 | Per-stage latency breakdown is observable. | every delay has a measurable origin | `evals/latency/metrics.py` (`STAGE_LATENCY_METRICS`), `evals/observability.py` | **DONE** (p50/p95/p99 collector + Prometheus render, CPU-verified) |
| L6 | PRs fail automatically on threshold regressions. | `RegressionGate` red on regression | `evals/gates.py` · `runs/phase-15-evals/acceptance.md` | **DONE** (10/10 gates pass on reference mock; fails on simulated regression) |

> **Honesty note:** replay runs on `evals/replay/mock_pipeline.py` (deterministic, CPU).
> No live TTFA/first-token numbers have been captured. All "sub-300 ms" claims remain
> *ambitions to be measured on target hardware* (`docs/LATENCY_TARGETS.md`, Q-008).

---

## 2. Safety preflight (`final_use.md` §8.3)

Safety is a fail-closed, first-class gate. CPU-verified end to end with deterministic
fallbacks; the only external dependency is the real watermark/moderation checkpoint pin.

| # | Preflight check (§8.3) | Subsystem / acceptance | Status |
|---|---|---|---|
| S1 | **Non-consensual voice cloning blocked.** Consent-first; missing/forged consent refused; reference not retained. | `safety/voice_policy/policy.py` (`VoicePolicy.evaluate`, `ConsentStore`) · `runs/phase-11-safety/acceptance.md` (50/50 clone attempts refused, none retained) | **DONE** |
| S2 | **Risky-speech moderation path auditable.** Text + speech moderation, crisis/self-harm escalation, abuse log; fail-closed on classifier error. | `safety/moderation/gate.py` (`moderate_text`/`moderate_speech`), `safety/contracts.py` (`AuditLog`) · `runs/phase-11-safety/acceptance.md` | **DONE** (lexicon fallback; real ML classifier injectable via `load_classifier`) |
| S3 | **Protected-voice list + review workflow operating.** Protected refs route to admin review, never auto-approve. | `safety/voice_policy/policy.py` (`protected_voice_ids`, `register_protected_voice`, `escalate_admin_review`) · `runs/phase-11-safety/acceptance.md` | **DONE** |
| S4 | **Spoofing checks.** Forged/tampered/mismatched consent token → `category="spoofing"`; detector error fails closed. | `safety/voice_policy/policy.py` (HMAC verify, `SpoofDetector`) · `runs/phase-11-safety/acceptance.md` | **DONE** |
| S5 | **Production secret set.** `SAFETY_HMAC_SECRET` configured to a real value (not the dev default). | `safety/contracts.py` HMAC sign/verify · `.env.example` | **PENDING-EXTERNAL** (ops must set the secret at deploy; OPEN_QUESTIONS Q-012 consent-token format) |

---

## 3. Watermark preflight (`final_use.md` §8.3 / Phase 11C)

| # | Preflight check | Subsystem / acceptance | Status |
|---|---|---|---|
| W1 | **All synthesized audio is watermarked before emit.** `protect()` embeds + self-verifies on every output path (incl. filler + classic TTS fallback). | `safety/watermark/audioseal.py` (`Watermarker.protect`) · `runs/phase-11-safety/acceptance.md` | **DONE** (CPU fallback) |
| W2 | **Emit is gated on compliance.** Non-verifiable output flagged `compliant=False`; `assert_compliant` is a hard emit-gate. | `safety/watermark/audioseal.py` (`Watermarker.assert_compliant`, `WatermarkComplianceError`) · `runs/phase-11-safety/acceptance.md` | **DONE** |
| W3 | **Detector outcomes logged + ops tooling.** Compliant/non-compliant recorded to `AuditLog`; `ops_status()` + `python -m safety.watermark.audioseal`. | `safety/watermark/audioseal.py` · `runs/phase-11-safety/acceptance.md` | **DONE** |
| W4 | **Real watermark backend pinned.** AudioSeal (or equivalent) checkpoint + insertion/detection thresholds. | `safety/watermark/audioseal.py` (`load_audioseal_backend`) · `docs/MODEL_LOCKS.md` AudioSeal row | **PENDING-EXTERNAL** (`pending-human-pin`; Q-007) |

---

## 4. Memory preflight (`final_use.md` §8.2 / Phase 12)

| # | Preflight check | Subsystem / acceptance | Status |
|---|---|---|---|
| M1 | **Bounded retrieval.** Tiered Redis/Postgres/Qdrant; `top_k` clamped, deadline + latency attached. | `memory/store.py`, `memory/redis/hot_cache.py`, `memory/qdrant/semantic_memory.py` · `runs/phase-12-memory/acceptance.md` | **DONE** (in-memory fallbacks CPU-verified) |
| M2 | **Relevant, compact context.** Rerank + dedupe + bounded digest + stale pruning. | `memory/summarizer/pipeline.py` · `runs/phase-12-memory/acceptance.md` | **DONE** |
| M3 | **Tool failures degrade gracefully.** Timeout/retry/allowlist; `invoke()` never raises; escalation safe. | `memory/tool_router/router.py` · `runs/phase-12-memory/acceptance.md` | **DONE** |
| M4 | **Live memory infra provisioned + schema'd.** Real Redis/Postgres/Qdrant endpoints + collection/table schema. | `infra/docker/docker-compose.full.yml`; `memory/*` read `REDIS_URL`/`DATABASE_URL`/`QDRANT_URL` · `docs/MODEL_LOCKS.md` Postgres/Qdrant rows | **PENDING-EXTERNAL** (Postgres/Qdrant `pending-human-pin`; Q-011 schema) |

---

## 5. Load / scaling preflight (`final_use.md` §8.2 stability / Phase 16)

| # | Preflight check | Subsystem / acceptance | Status |
|---|---|---|---|
| C1 | **Sessions do not starve each other.** Bounded concurrency, max-depth queue, backpressure/rejection, sticky routing. | `infra/scaling/scheduler.py`, `infra/scaling/envelopes.py` · `runs/phase-16-infra/acceptance.md` | **DONE** (CPU-verified) |
| C2 | **p95 latency controlled across geography.** Region routing + warm pools + health-aware fallback. | `infra/deploy/regions.py` (`RegionRouter`, `WarmPool`) · `runs/phase-16-infra/acceptance.md` | **DONE** (haversine-estimated; live p50/p95/p99 TO-MEASURE) |
| C3 | **Monitoring live.** Prometheus scrape + alert rules + dashboards. | `infra/monitoring/prometheus.yml`, `infra/monitoring/alerts.rules.yml` · `runs/phase-16-infra/acceptance.md` | **DONE** (config CPU-verified; needs live Prometheus to scrape) |
| C4 | **Real load test on target hardware.** p50/p95/p99 under representative concurrency. | `infra/scaling/*` + `evals/` | **PENDING-EXTERNAL** (needs GPU + live services; Q-003) |

---

## 6. Docs completeness preflight (`final_use.md` §14 / Phase 17)

| # | Preflight check | Subsystem / acceptance | Status |
|---|---|---|---|
| D1 | **Canonical architecture docs exist + updated.** | `docs/DECISIONS.md`, `docs/code/architecture_overview.md` · `runs/phase-17-docs/acceptance.md` | **DONE** |
| D2 | **Model/version/asset locks pinned (or explicitly pending).** | `docs/MODEL_LOCKS.md` | **DONE** (roles frozen; exact checkpoints `pending-human-pin` where noted) |
| D3 | **Code/API/config docs grounded in real source.** | `docs/code/module_reference.md`, `docs/code/api_protocol_reference.md`, `docs/code/configuration_reference.md` · `runs/phase-17-docs/acceptance.md` | **DONE** |
| D4 | **Training JSONL validates cleanly.** | `docs/training/qa_dataset.jsonl`, `scripts/validate_training_jsonl.py` (58/58 OK) · `runs/phase-17-docs/acceptance.md` | **DONE** |
| D5 | **Launch docs present.** | `docs/launch/*` (this set) · `runs/phase-18-launch/acceptance.md` | **DONE** |

---

## 7. Rollback readiness preflight (`final_use.md` §16C / §14)

| # | Preflight check | Subsystem / acceptance | Status |
|---|---|---|---|
| RB1 | **Rollback policy defined.** Canary thresholds (`p95_ttfb_ms`, `error_rate_pct`) drive rollback/hold/promote. | `infra/deploy/release_policy.yaml`, `infra/deploy/rollback.py` (`RollbackEvaluator`, `ReleasePolicy`) · `runs/phase-16-infra/acceptance.md` | **DONE** (evaluator CPU-verified against the real YAML) |
| RB2 | **Runbooks exist.** Staging / canary / rollback + incident response. | `infra/deploy/RUNBOOKS.md`, `infra/deploy/INCIDENT_RESPONSE.md` · `runs/phase-16-infra/acceptance.md` | **DONE** |
| RB3 | **Fallback path proven.** Failover decision + classic baseline + degraded-mode output. | `aux/fallback/orchestrator.py`, `aux/fallback/classic_baseline.py`, `aux/fallback/temp_output.py` · `runs/phase-7-13-aux/acceptance.md` | **DONE** (stub backends CPU-verified) |
| RB4 | **Rollback rehearsed on live infra.** Prove a real promote→breach→rollback cycle in staging. | `infra/deploy/RUNBOOKS.md` rollback drill | **PENDING-EXTERNAL** (needs live staging cluster; Q-003) |

---

## 8. Go / No-Go summary

A release is **GO** only when:
1. Every `# Release Gate` line is **DONE**, or
2. Any **PENDING-EXTERNAL** / **TO-MEASURE** line has an explicit, human-signed waiver
   recorded in the release packet (`docs/launch/HANDOFF_PACK.md`) citing the blocking
   `MODEL_LOCKS.md` row or `OPEN_QUESTIONS.md` ID.

**Current honest standing (CPU-only dev environment):** all gate *logic, policy, and
fallbacks* are implemented, tested, and acceptance-recorded. The build is **NOT** GO for a
live public launch because the speech-native core (Moshi/Mimi) and real services
(GPU, Postgres, Qdrant, Prometheus, AudioSeal) are `pending-human-pin` / not provisioned,
and **no live latency has been measured**. It **is** ready for a hardware bring-up that
turns each PENDING-EXTERNAL / TO-MEASURE line green.
