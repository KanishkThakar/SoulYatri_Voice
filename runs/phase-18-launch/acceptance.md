# Acceptance — Phase 18: Launch governance, operating loop, final release checklist

**Task:** Implement `final_use.md` §Phase 18 FULLY (18A daily operating loop, 18B release
checklist, 18C final handoff pack) + §14 launch-readiness checklist mapping, grounded in
the real subsystems and the existing `runs/*/acceptance.md` records.

**Owner:** launch/governance (docs) agent.

**Environment:** Windows, CPU-only, no GPU, no Moshi/Mimi weights. This is a
**docs/governance** phase — no source code under `server/`, `client/`, `edge/`, `speech/`,
`aux/`, `memory/`, `safety/`, `infra/`, `evals/`, `training/`, `shared/` was modified. All
prior Phase-0 docs were left intact; new launch docs were added under `docs/launch/`.

---

## Files created

| File | Phase | Purpose |
|---|---|---|
| `docs/launch/index.md` | 18 | Launch-pack index + how the docs fit together. |
| `docs/launch/OPERATING_MANUAL.md` | 18A | Daily triage, §9 task slicing, benchmark cadence, long-job approval, release cadence, multi-agent worktree/branch coordination. |
| `docs/launch/RELEASE_CHECKLIST.md` | 18B | Preflight (latency/safety/watermark/memory/load/docs/rollback) + the `# Release Gate` skeleton; each gate cross-references the real subsystem + acceptance record. |
| `docs/launch/LAUNCH_READINESS.md` | 14 | The §14 checklist reproduced verbatim and mapped item-by-item to subsystem + acceptance record (or PENDING-EXTERNAL with reason). |
| `docs/launch/HANDOFF_PACK.md` | 18C | Architecture summary, §12 benchmark snapshot template, consolidated risk register, runbook index, docs indexes, next-cycle issue backlog. |
| `runs/phase-18-launch/acceptance.md` | — | This record. |

---

## Acceptance criteria mapping (`final_use.md` §Phase 18 table)

### 18A — daily operating loop → *"agents and humans can coordinate without stepping on each other"*
- Daily triage sequence (T1–T5) produces exactly one micro-phase slice per agent.
  `docs/launch/OPERATING_MANUAL.md` §1.
- Task slicing uses the §9 ticket template verbatim; one ticket = one micro-phase = one
  branch = one acceptance file. §2.
- Benchmark review cadence (per-PR / daily / pre-release) wired to `evals/gates.py` +
  `evals/replay/harness.py`, with an explicit honesty note that live latency is
  TO-MEASURE. §3.
- Long-job approval rules (CPU dry-run / GPU adaptation / forbidden scratch pretraining)
  grounded in `training/sft/lora_sft.py`, `training/preference/dpo_lite.py`, D-005. §4.
- Release cadence (continuous → staging → canary → beta). §5.
- Multi-agent worktree/branch coordination consistent with `docs/AGENT_PROTOCOL.md` §1
  (isolated branches, `<domain>/<phase>-<slug>`, wave parallelism, cross-cutting review,
  destructive-op approval). §6.

### 18B — release checklist → *"no launch proceeds without checklist pass"*
- Reproduces the §18B `# Release Gate` skeleton (latency / safety / watermark / fallback /
  rollback / docs / risks). `docs/launch/RELEASE_CHECKLIST.md` § Release Gate.
- Preflight sections for latency (§8.1 / LATENCY_TARGETS gates), safety (§8.3 —
  non-consensual cloning blocked, moderation auditable, watermark tested, protected-voice
  list), watermark, memory, load/scaling, docs completeness, rollback readiness.
- **Every gate cites a real module and/or `runs/<phase>/acceptance.md`** and an honest
  status (DONE / PENDING-EXTERNAL / TO-MEASURE).

### 18C — final handoff pack → *"a new team can continue work from artifacts alone"*
- Architecture summary linking `docs/code/architecture_overview.md`.
- §12 benchmark snapshot template (metrics from `evals/latency/metrics.py`, gates from
  `evals/gates.py`, dimension scorers from `evals/{hinglish,emotion,audio}/`).
- Consolidated risk register linking `docs/RISKS.md`.
- Runbook index linking `infra/deploy/*` + `infra/monitoring/*`.
- Docs indexes linking `docs/index.md` + sub-indexes.
- Issue backlog (B-01…B-25) pulled from `docs/OPEN_QUESTIONS.md` + the `pending-human-pin`
  rows of `docs/MODEL_LOCKS.md`.

---

## Grounding verification

Every checklist item references a real subsystem module and/or a real acceptance record.
Confirmed present at authoring time:

- Acceptance records (all 12 read and cited): `runs/0-1-foundation/`,
  `runs/phase-2-3-client/`, `runs/phase-4-8-edge/`, `runs/phase-5-6-10-speech/`,
  `runs/phase-7-13-aux/`, `runs/phase-9-persona/`, `runs/phase-11-safety/`,
  `runs/phase-12-memory/`, `runs/phase-14-training/`, `runs/phase-15-evals/`,
  `runs/phase-16-infra/`, `runs/phase-17-docs/`.
- Real safety symbols verified by source read: `VoicePolicy`, `protected_voice_ids`,
  `register_protected_voice`, `escalate_admin_review` in `safety/voice_policy/policy.py`;
  `Watermarker.protect` / `Watermarker.assert_compliant` in `safety/watermark/audioseal.py`.
- Real infra runbooks verified present: `infra/deploy/RUNBOOKS.md`,
  `infra/deploy/INCIDENT_RESPONSE.md`, `infra/deploy/release_policy.yaml`,
  `infra/deploy/rollback.py`, `infra/monitoring/*`.
- No live latency numbers are claimed anywhere; sub-300 ms remains a staged ambition
  marked TO-MEASURE (`docs/LATENCY_TARGETS.md`, Q-003, Q-008).

---

## Definition of Done (`final_use.md` §3.3)

- [x] **Code/docs** — launch governance docs implementing 18A/18B/18C + §14 mapping.
- [x] **Tests** — N/A for a docs phase; instead, **link integrity + grounding** were
      checked (every cited module path and `runs/*/acceptance.md` exists). The validated
      artifacts they reference (61 evals tests, 52 safety tests, etc.) carry their own
      acceptance under `runs/`.
- [x] **Design note** — `docs/launch/index.md` + section intros in each doc.
- [x] **Structured logging hooks** — N/A (no runtime code added); the operating manual
      points at the existing per-domain logging shims.
- [x] **Benchmark/latency note** — `HANDOFF_PACK.md` §2 benchmark snapshot template +
      the reference CPU mock result; live numbers explicitly TO-MEASURE.
- [x] **Acceptance recorded** — this file under `runs/`.

---

## Ownership compliance

Only files under `docs/launch/` and this `runs/phase-18-launch/acceptance.md` were
created. No source folders were modified. Existing Phase-0 governance docs
(`DECISIONS.md`, `AGENT_PROTOCOL.md`, `MODEL_LOCKS.md`, `LATENCY_TARGETS.md`, `RISKS.md`,
`OPEN_QUESTIONS.md`, `ASSUMPTIONS.md`, `INTERFACES.md`, `index.md`) were **not** overwritten.

---

## Project build status (all phases)

Honest, repo-grounded rollup. Every phase below has code + tests + an acceptance record;
**CPU-verified** means it imports and tests pass on the CPU-only dev host with deterministic
fallbacks (no GPU / no Moshi-Mimi weights, per D-008).

| Phase | Scope | Status | Acceptance record |
|---|---|---|---|
| 0 + 1 | Architecture freeze, governance, repo scaffold, CI, contracts | **CPU-verified** (19 contract tests; ruff/format clean) | `runs/0-1-foundation/acceptance.md` |
| 2 + 3 | Client audio capture/transport/playback + local router/filler | **CPU-verified** (23 gateway + 28 TS tests) | `runs/phase-2-3-client/acceptance.md` |
| 4 + 8 | Edge features, turn-state machine, barge-in + response planning/speculation | **CPU-verified** (91 edge tests; 114 with gateway) | `runs/phase-4-8-edge/acceptance.md` |
| 5 + 6 + 10 | Mimi codec bridge, token stream, Moshi runtime, fast decoder + interruption | **CPU-verified** (72 tests; mock/echo backends — real Moshi/Mimi PENDING-EXTERNAL) | `runs/phase-5-6-10-speech/acceptance.md` |
| 9 | Emotion schema, persona controller (FiLM), relationship memory | **CPU-verified** (39 tests) | `runs/phase-9-persona/acceptance.md` |
| 7 + 13 | Auxiliary text brain, STT utilities, classic baseline + failover | **CPU-verified** (43 tests; stub backends) | `runs/phase-7-13-aux/acceptance.md` |
| 11 | Moderation gate, consent-first voice policy, watermarking | **CPU-verified** (52 tests; real AudioSeal/classifier PENDING-EXTERNAL) | `runs/phase-11-safety/acceptance.md` |
| 12 | Memory tiers (Redis/Postgres/Qdrant), summarizer, tool router | **CPU-verified** (86 tests; in-memory fallbacks — live infra PENDING-EXTERNAL) | `runs/phase-12-memory/acceptance.md` |
| 14 | Data engine, schemas, SFT/LoRA + DPO-lite scripts (no training run) | **CPU-verified** (66 tests; dry-run only — GPU training PENDING-EXTERNAL) | `runs/phase-14-training/acceptance.md` |
| 15 | Evaluation harness, observability, regression gates | **CPU-verified** (61 tests; 10/10 gates on reference mock) | `runs/phase-15-evals/acceptance.md` |
| 16 | Scaling/concurrency, regional routing, deploy hardening, monitoring | **CPU-verified** (scheduler/regions/rollback tests; live cluster PENDING-EXTERNAL) | `runs/phase-16-infra/acceptance.md` |
| 17 | Docs knowledge base + training corpus (JSONL) | **CPU-verified** (58/58 JSONL lines validate) | `runs/phase-17-docs/acceptance.md` |
| 18 | Launch governance, operating loop, release checklist, handoff pack | **DONE** (this phase; grounding verified) | `runs/phase-18-launch/acceptance.md` |

### Code-complete + CPU-verified
All 18 macro phases are code-complete with passing CPU tests and acceptance records.
The full speech-native control surface — capture, transport, filler, edge turn-state,
codec bridge, runtime shell, persona, decoder, auxiliary text, safety, memory, evals,
scaling, docs, and launch governance — exists and runs on CPU behind deterministic
fallbacks.

### Gated on external hardware / weights / services (PENDING-EXTERNAL / TO-MEASURE)
- **Speech-native core:** real **Mimi** + **Moshi** weights (`MODEL_LOCKS.md`
  `pending-human-pin`, Q-001/Q-002) — today mock/echo backends stand in.
- **Live latency:** sub-300 ms first-audible ambition + interruption stop budget +
  p50/p95/p99 under load are **TO-MEASURE on GPU** (`LATENCY_TARGETS.md`, Q-003/Q-008).
- **Safety backends:** real **AudioSeal** watermark + real moderation classifier
  (`pending-human-pin`, Q-007); set `SAFETY_HMAC_SECRET` in production.
- **Memory infra:** live **Postgres** + **Qdrant** (+ schemas) and **Redis**
  (`pending-human-pin`, Q-011).
- **Ops:** live **Prometheus** scrape + a rehearsed promote→breach→**rollback** drill on a
  staging cluster (Q-003).

These are tracked as the next-cycle backlog (B-01…B-25) in
`docs/launch/HANDOFF_PACK.md` §6 and mapped to the §14 checklist in
`docs/launch/LAUNCH_READINESS.md`.

**Bottom line:** SoulYatri is **architecturally complete and CPU-verified end to end**,
and **not yet GO for live public launch** — the remaining work is a hardware/weights
bring-up that flips each PENDING-EXTERNAL / TO-MEASURE gate green. No live performance
numbers are claimed; they are explicitly to be measured on target hardware.
