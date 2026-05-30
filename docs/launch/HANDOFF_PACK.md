# HANDOFF_PACK — Final Release Packet (Phase 18C)

> **Source:** `final_use.md` §Phase 18C (final handoff pack), §12 (evaluation matrix),
> §14 (launch-readiness checklist).
> **Acceptance (final_use.md §18C):** *a new team can continue work from artifacts alone.*
>
> This packet is the single entry point for the next cycle. It links the architecture
> summary, a benchmark snapshot template, the consolidated risk register, the runbook
> index, the docs indexes, and the open issue backlog. Everything here points at **real
> files** that exist in the repository.

---

## 1. Final architecture summary

SoulYatri is an open-source, **speech-native**, low-latency, full-duplex, emotional,
Hindi + English + Hinglish conversational voice AI. The frozen runtime loop is:

```text
Audio → Mimi codec tokens → Moshi speech-native runtime → codec tokens → Audio
```

It is **not** a classic ASR → LLM → TTS chatbot; the text path exists only as a
fallback / observability / tooling path (`docs/DECISIONS.md` D-002, D-003).

**Full architecture reference:** [`docs/code/architecture_overview.md`](../code/architecture_overview.md)
(grounded in real source: `README.md`, `shared/contracts.py`, `server/main.py`, and the
`edge/ speech/ aux/ memory/ safety/ infra/ evals/` trees).

Domain map and the subsystem that owns each stage of the loop:

| Stage | Subsystem (real path) | Acceptance record |
|---|---|---|
| Capture · transport · playback · local filler | `client/src/audio/*`, `client/src/router/*`, `edge/webrtc_gateway/gateway.py` | `runs/phase-2-3-client/acceptance.md` |
| Edge features · turn-state · barge-in · planner | `edge/turn_detection/*`, `edge/session/turn_state.py`, `edge/barge_in/detector.py`, `edge/planner/*` | `runs/phase-4-8-edge/acceptance.md` |
| Mimi codec bridge · token stream · Moshi runtime · fast decoder | `speech/codec/*`, `speech/moshi_runtime/*`, `speech/decoder/*` | `runs/phase-5-6-10-speech/acceptance.md` |
| Emotion · persona · relationship memory | `speech/persona/*` | `runs/phase-9-persona/acceptance.md` |
| Auxiliary text brain · STT · fallback baseline | `aux/text_brain/*`, `aux/stt/transcript_service.py`, `aux/fallback/*` | `runs/phase-7-13-aux/acceptance.md` |
| Safety: moderation · voice policy · watermark | `safety/moderation/gate.py`, `safety/voice_policy/policy.py`, `safety/watermark/audioseal.py` | `runs/phase-11-safety/acceptance.md` |
| Memory tiers · summarizer · tool router | `memory/store.py`, `memory/{redis,postgres,qdrant}/*`, `memory/summarizer/pipeline.py`, `memory/tool_router/router.py` | `runs/phase-12-memory/acceptance.md` |
| Scaling · regional routing · deploy hardening | `infra/scaling/*`, `infra/deploy/*`, `infra/monitoring/*` | `runs/phase-16-infra/acceptance.md` |
| Evaluation harness · regression gates | `evals/replay/*`, `evals/latency/metrics.py`, `evals/gates.py` | `runs/phase-15-evals/acceptance.md` |
| Data engine · adaptation scripts | `training/data_engine/*`, `training/sft/*`, `training/preference/*` | `runs/phase-14-training/acceptance.md` |
| Docs knowledge base · training corpus | `docs/code/*`, `docs/training/*` | `runs/phase-17-docs/acceptance.md` |
| Governance · launch | `docs/*`, `docs/launch/*` | `runs/0-1-foundation/acceptance.md`, `runs/phase-18-launch/acceptance.md` |

---

## 2. Benchmark snapshot template (`final_use.md` §12 evaluation matrix)

Use this template to record a benchmark snapshot at each milestone. Metrics come from
`evals/latency/metrics.py` (`METRICS`, `STAGE_LATENCY_METRICS`); gates come from
`evals/gates.py`; dimension scorers from `evals/hinglish/`, `evals/emotion/`,
`evals/audio/`. The §12 matrix maps onto these as below.

> **Fill the `value` column from a real run on target hardware.** On the current CPU-only
> environment with no Moshi/Mimi weights, latency/quality values are produced only by the
> deterministic mock pipeline (`evals/replay/mock_pipeline.py`) and are **not** live
> numbers — leave them as `TO-MEASURE` until measured on GPU. (`docs/LATENCY_TARGETS.md`,
> Q-003, Q-008.)

```md
# Benchmark Snapshot — <date> / <build sha> / <hardware>
Pipeline: <mock | moshi-mimi-vX>     Scenarios: evals/replay/scenarios/*.json (7)

## §12 — Latency (evals/latency/metrics.py + evals/gates.py)
| metric                        | p50 | p95 | p99 | gate target                 | pass? |
|-------------------------------|-----|-----|-----|-----------------------------|-------|
| time_to_first_audible_ms      |     |     |     | sub-300ms ambition          |       |
| first_token_ms                |     |     |     | (LATENCY_TARGETS Gate 2)    |       |
| turn_end_detection_delay_ms   |     |     |     | bounded                     |       |
| interruption_recovery_ms      |     |     |     | low-hundreds-ms (Gate 3)    |       |
| filler_hit_rate               |     |  -  |  -  | high on trivial turns       |       |
| filler_false_positive_rate    |     |  -  |  -  | low/bounded                 |       |
| stage_* breakdown (vad…decoder)|    |     |     | every delay has an origin   |       |

## §12 — Quality / intelligibility / naturalness (evals/audio/scorer.py)
| dimension        | metric                  | value | gate | pass? |
|------------------|-------------------------|-------|------|-------|
| intelligibility  | WER (en/hi/hinglish)    |       |      |       |
| naturalness      | UTMOS-like proxy        |       |      |       |

## §12 — Emotion (evals/emotion/scorer.py)
| metric                 | value | gate | pass? |
|------------------------|-------|------|-------|
| label agreement        |       |      |       |
| continuous V/A/D agree |       |      |       |

## §12 — Code-switch (evals/hinglish/scorer.py)
| metric                      | value | gate | pass? |
|-----------------------------|-------|------|-------|
| code-switch ratio           |       |      |       |
| transliteration robustness  |       |      |       |

## §12 — Safety (safety/* + runs/phase-11-safety)
| check                          | result | pass? |
|--------------------------------|--------|-------|
| non-consensual clone blocked   |        |       |
| moderation auditable           |        |       |
| watermark verify on emit       |        |       |

## §12 — Stability (infra/* + evals)
| metric                | p50 | p95 | p99 | pass? |
|-----------------------|-----|-----|-----|-------|
| reconnect survival    |     |     |     |       |
| queue stability       |     |     |     |       |

Regression gate result: `python -c "..."` → [PASS/FAIL] N/M gates (evals/gates.py)
```

**Reference CPU result on the bundled mock pipeline** (from
`runs/phase-15-evals/acceptance.md`, proves the harness + gates work — *not* live latency):

```text
scenarios=7 turns=15 route_acc=1.00 intent_acc=1.00
[PASS] 10/10 gates passed
```

---

## 3. Consolidated risk register

The authoritative risk register is [`docs/RISKS.md`](../RISKS.md) (R-001 … R-014). The
top launch-blocking risks to carry into the next cycle:

| ID | Risk | Severity | Mitigation owner | Tracked by |
|---|---|---|---|---|
| R-001 | No GPU / no weights blocks Moshi/Mimi end-to-end. | High | speech/runtime | MODEL_LOCKS Moshi/Mimi; Q-003 |
| R-002 | Moshi unstable / too heavy for latency. | High | speech/runtime | CSM fallback behind `SpeechRuntime`; Phase 13 baseline |
| R-003 | First-audible misses sub-300 ms under load. | High | edge + infra | `evals/gates.py`; LATENCY_TARGETS; Q-008 |
| R-004 | Hinglish/code-switch quality weak. | High | training + evals | `evals/hinglish/`; `training/data_engine/` data moat |
| R-006 | Non-consensual cloning / impersonation misuse. | High | safety | `safety/voice_policy/policy.py` (DONE) |
| R-011 | Architecture drift to text-first core. | High | docs + all | `DECISIONS.md` D-002; PR checklist |
| R-014 | Moderation/crisis flow missing or unauditable. | High | safety | `safety/moderation/gate.py` (DONE) |

---

## 4. Runbook index (infra)

| Runbook | Path | Covers |
|---|---|---|
| Staging / canary / rollback | [`infra/deploy/RUNBOOKS.md`](../../infra/deploy/RUNBOOKS.md) | Promote, canary, rollback procedures |
| Incident response | [`infra/deploy/INCIDENT_RESPONSE.md`](../../infra/deploy/INCIDENT_RESPONSE.md) | On-call, severity, escalation |
| Deployment topology | [`infra/deploy/deployment_topology.md`](../../infra/deploy/deployment_topology.md) | Regional layout, warm pools |
| Release policy | [`infra/deploy/release_policy.yaml`](../../infra/deploy/release_policy.yaml) | Canary thresholds, rollback triggers |
| Pinned versions | [`infra/docker/PINNED_VERSIONS.md`](../../infra/docker/PINNED_VERSIONS.md) | Image/version pins (digests for prod) |
| Dashboards & alerts | [`infra/monitoring/dashboards_and_alerts.md`](../../infra/monitoring/dashboards_and_alerts.md) | Prometheus dashboards + alert rules |
| Full-stack compose | [`infra/docker/docker-compose.full.yml`](../../infra/docker/docker-compose.full.yml) | Server + Postgres + Qdrant + Prometheus |

---

## 5. Docs index

| Index | Path | Covers |
|---|---|---|
| Top-level docs index | [`docs/index.md`](../index.md) | Governance + code + training knowledge base |
| Code docs index | [`docs/code/index.md`](../code/index.md) | Architecture, modules, API, configuration |
| Training corpus index | [`docs/training/index.md`](../training/index.md) | Q&A JSONL corpus + schema |
| Launch index | [`docs/launch/index.md`](index.md) | This launch/governance pack |
| Governance contract | [`docs/AGENT_PROTOCOL.md`](../AGENT_PROTOCOL.md) | Branch rules, DoD, PR checklist |
| Decision log | [`docs/DECISIONS.md`](../DECISIONS.md) | Frozen architecture (D-001 … D-009) |
| Interfaces | [`docs/INTERFACES.md`](../INTERFACES.md) | Cross-subsystem contracts |
| Model locks | [`docs/MODEL_LOCKS.md`](../MODEL_LOCKS.md) | V1 model/artifact manifest |
| Latency targets | [`docs/LATENCY_TARGETS.md`](../LATENCY_TARGETS.md) | Staged latency gates |

---

## 6. Issue backlog for the next cycle

Pulled from [`docs/OPEN_QUESTIONS.md`](../OPEN_QUESTIONS.md) (unresolved items) and the
`pending-human-pin` rows of [`docs/MODEL_LOCKS.md`](../MODEL_LOCKS.md). These are the
gating items that turn the PENDING-EXTERNAL / TO-MEASURE lines of
`docs/launch/RELEASE_CHECKLIST.md` green.

### 6.1 Pending human pins (MODEL_LOCKS.md)

| Backlog item | Artifact | Blocks | Source row |
|---|---|---|---|
| B-01 | Pin exact **Mimi** version + sample-rate / RVQ layout. | Phase 5 codec contract | MODEL_LOCKS Mimi `pending-human-pin` (Q-002) |
| B-02 | Pin exact **Moshi** checkpoint / repo commit + streaming config. | Phase 5/6 speech-native core | MODEL_LOCKS Moshi `pending-human-pin` (Q-001) |
| B-03 | Decide **CSM** fallback usage + where/why. | Phase 6/13 fallback | MODEL_LOCKS CSM `pending-human-pin` |
| B-04 | Pin **sherpa-onnx** runtime package + model assets. | Phase 3 local helper | MODEL_LOCKS sherpa `pending-human-pin` |
| B-05 | Pin **IndicConformer** (or equiv.) + Hindi/Hinglish eval plan. | Phase 7 Indic STT | MODEL_LOCKS IndicConformer `pending-human-pin` (Q-005) |
| B-06 | Decide **Qwen3 vs Llama 3.3** + size/quantization/serving. | Phase 7/12 text brain | MODEL_LOCKS text-brain `pending-human-pin` (Q-004) |
| B-07 | Pin **multilingual-e5** version + chunking + dimensionality. | Phase 12 retrieval | MODEL_LOCKS e5 `pending-human-pin` (Q-011) |
| B-08 | Pin **Postgres** version + schema. | Phase 12 profile store | MODEL_LOCKS Postgres `pending-human-pin` (Q-011) |
| B-09 | Pin **Qdrant** version + collection schema. | Phase 12 semantic memory | MODEL_LOCKS Qdrant `pending-human-pin` (Q-011) |
| B-10 | Pin **AudioSeal** (or equiv.) checkpoint + insertion/detection policy. | Phase 11 watermark | MODEL_LOCKS AudioSeal `pending-human-pin` (Q-007) |
| B-11 | Pin emergency fallback stack (XTTS/OpenVoice, whisper.cpp, SNAC/DAC). | Phase 13 degraded mode | MODEL_LOCKS optional/fallback `pending-human-pin` |

### 6.2 Open questions (OPEN_QUESTIONS.md)

| Backlog item | Question | Blocks | ID |
|---|---|---|---|
| B-12 | Where will GPU inference run + when do weights land? | Phase 5/6/16 end-to-end | Q-003 |
| B-13 | Numeric per-stage latency budgets (capture, tokenize, TTFT, decode, network). | Phase 8/15 enforceable gates | Q-008 |
| B-14 | Session-state ownership boundary between `server/`, `edge/`, `speech/`. | Phase 4/6 | Q-009 |
| B-15 | Full migration of WS PCM transport to LiveKit WebRTC, and when. | Phase 2 transport | Q-010 |
| B-16 | Consent token format + protected-voice list storage + review workflow. | Phase 11 voice policy | Q-012 |
| B-17 | Persona ID catalog + speaker-style embedding fusion method. | Phase 9 persona | Q-013 |
| B-18 | CI policy for GPU-dependent tests (skip vs dedicated runner). | Phase 1/15 | Q-014 |
| B-19 | Emotion SER model + label space to standardize on. | Phase 9 emotion | Q-006 |
| B-20 | Source-of-truth: keep both `Soulyatri_Final_*` markdowns or designate `final_use.md` master. | governance | Q-015 |

### 6.3 Live bring-up tasks (measure / rehearse)

| Backlog item | Task | Turns green |
|---|---|---|
| B-21 | Measure live TTFA / first-token / interruption recovery on GPU + Moshi/Mimi. | RELEASE_CHECKLIST L3, L4 (TO-MEASURE) |
| B-22 | Run real load test (p50/p95/p99) under representative concurrency. | RELEASE_CHECKLIST C4 |
| B-23 | Rehearse promote→breach→rollback on a live staging cluster. | RELEASE_CHECKLIST RB4 |
| B-24 | Set `SAFETY_HMAC_SECRET` (and other prod secrets) at deploy. | RELEASE_CHECKLIST S5 |
| B-25 | Provision + schema live Redis/Postgres/Qdrant + Prometheus. | RELEASE_CHECKLIST M4, C3 |

---

## 7. How a new team starts from here

1. Read `docs/code/architecture_overview.md` (the system), then `docs/DECISIONS.md`
   (why it is frozen), then `docs/launch/OPERATING_MANUAL.md` (how to run a day).
2. Open `docs/launch/LAUNCH_READINESS.md` to see exactly which §14 items are DONE vs
   PENDING-EXTERNAL and the subsystem/acceptance record behind each.
3. Work the §6 backlog top-down: pins first (Mimi/Moshi unblock the core), then live
   bring-up (B-21…B-25) to flip the TO-MEASURE / PENDING-EXTERNAL gates.
4. Every change follows the daily loop in `OPERATING_MANUAL.md` and the Definition of
   Done — one micro-phase, one branch, tests, acceptance under `runs/`.
