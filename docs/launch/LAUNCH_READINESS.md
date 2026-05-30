# LAUNCH_READINESS — §14 Checklist, Mapped & Honest

> **Source:** `final_use.md` §14 (launch-readiness checklist). This document reproduces the
> §14 checklist verbatim and maps **each** item to the real subsystem module(s) and the
> `runs/<phase>/acceptance.md` record that satisfies it — or marks it **PENDING-EXTERNAL**
> with the reason (e.g. requires GPU / Moshi-Mimi weights / live services), citing the
> `docs/MODEL_LOCKS.md` `pending-human-pin` row or `docs/OPEN_QUESTIONS.md` ID.
>
> **Status legend**
> - **DONE** — code + tests + acceptance present, CPU-verified.
> - **PENDING-EXTERNAL** — needs GPU / weights / live services / human pin.
> - **TO-MEASURE** — logic exists + tested; live numbers must be measured on target hardware.
>
> **Honesty rule:** no live latency number is claimed anywhere in this repo. Latency gates
> are *staged ambitions* with working gate machinery; the values are TO-MEASURE on GPU
> (`docs/LATENCY_TARGETS.md`, Q-003, Q-008).

---

## §14 launch-readiness checklist (verbatim) → status

> *"Before any beta or public launch, all of the following must be true."* — `final_use.md` §14

| # | §14 item | Status | Subsystem (real module) | Acceptance record / pin |
|---|---|---|---|---|
| 1 | canonical architecture documents exist and are updated | **DONE** | `docs/DECISIONS.md`, `docs/INTERFACES.md`, `docs/code/architecture_overview.md` | `runs/0-1-foundation/acceptance.md`, `runs/phase-17-docs/acceptance.md` |
| 2 | model/version/asset locks are pinned | **DONE (roles) / PENDING-EXTERNAL (exact checkpoints)** | `docs/MODEL_LOCKS.md` | roles frozen; Mimi/Moshi/CSM/sherpa/IndicConformer/text-brain/e5/Postgres/Qdrant/AudioSeal rows `pending-human-pin` (Q-001…Q-007, Q-011) |
| 3 | transport path survives reconnect and jitter tests | **DONE** | `client/src/audio/webrtc.ts`, `edge/webrtc_gateway/gateway.py` (`JitterBuffer`, reconnect/backoff) | `runs/phase-2-3-client/acceptance.md` (23 gateway + 28 TS tests) |
| 4 | filler system is bounded and can be disabled | **DONE** | `client/src/router/filler_engine.ts` (`setEnabled(false)`, safe classes), `edge/planner/short_turn.py` | `runs/phase-2-3-client/acceptance.md`, `runs/phase-4-8-edge/acceptance.md` |
| 5 | turn-state machine is explicit and tested | **DONE** | `edge/session/turn_state.py` (`TurnStateMachine`, single transition table, guards/timeouts) | `runs/phase-4-8-edge/acceptance.md` (`test_turn_state.py`, 15 tests) |
| 6 | Mimi roundtrip is intelligible | **DONE (mock) / PENDING-EXTERNAL (real Mimi)** | `speech/codec/mimi_bridge.py` (`MimiCodecBridge`, `MockCodecBackend` / lazy `MimiBackend`) | `runs/phase-5-6-10-speech/acceptance.md` (roundtrip < 1e-3 on mock); real Mimi weights `pending-human-pin` (Q-002) |
| 7 | Moshi runtime can stream, cancel, and repair | **DONE (echo backend) / PENDING-EXTERNAL (real Moshi)** | `speech/moshi_runtime/service.py` (`MoshiRuntimeService`, `EchoTransformBackend` / lazy `MoshiBackend`), `speech/moshi_runtime/repair.py` | `runs/phase-5-6-10-speech/acceptance.md` (stream/cancel/repair tests); real Moshi weights `pending-human-pin` (Q-001) |
| 8 | fallback path works for degraded mode | **DONE** | `aux/fallback/orchestrator.py` (`FailoverOrchestrator`), `aux/fallback/classic_baseline.py`, `aux/fallback/temp_output.py` | `runs/phase-7-13-aux/acceptance.md` |
| 9 | moderation and voice policy gates are active | **DONE** | `safety/moderation/gate.py`, `safety/voice_policy/policy.py` (consent-first, protected list, spoof checks) | `runs/phase-11-safety/acceptance.md` (52 tests; 50/50 clones refused) |
| 10 | watermark path is tested | **DONE (fallback) / PENDING-EXTERNAL (real AudioSeal)** | `safety/watermark/audioseal.py` (`Watermarker.protect`/`assert_compliant`) | `runs/phase-11-safety/acceptance.md`; AudioSeal checkpoint `pending-human-pin` (Q-007) |
| 11 | replay harness and regression thresholds are operational | **DONE** | `evals/replay/harness.py`, `evals/gates.py` (`RegressionGate`), `evals/latency/metrics.py` | `runs/phase-15-evals/acceptance.md` (61 tests; 10/10 gates on reference mock) |
| 12 | docs/training JSONL validates cleanly | **DONE** | `docs/training/qa_dataset.jsonl`, `scripts/validate_training_jsonl.py` | `runs/phase-17-docs/acceptance.md` (58/58 lines OK, exit 0) |
| 13 | rollback plan exists and has been rehearsed | **DONE (plan + evaluator) / PENDING-EXTERNAL (live rehearsal)** | `infra/deploy/rollback.py` (`RollbackEvaluator`), `infra/deploy/release_policy.yaml`, `infra/deploy/RUNBOOKS.md` | `runs/phase-16-infra/acceptance.md` (evaluator CPU-verified); live drill on staging is PENDING (Q-003) |

---

## Cross-phase acceptance coverage (`final_use.md` §8)

### §8.1 latency gates
- Stable baseline audio path — **DONE** (`runs/phase-2-3-client`).
- Visible TTFA improvement after fillers — **DONE** logic; **TO-MEASURE** live
  (`runs/phase-2-3-client`, `runs/phase-4-8-edge`).
- Sub-300 ms class first-audible ambition — **TO-MEASURE** (gate thresholds in
  `evals/gates.py`; needs GPU + Moshi/Mimi; Q-008).
- Clean interruption stop (low-hundreds-ms) — **DONE** on mock
  (`speech/decoder/interruption.py`, `edge/barge_in/detector.py`); live **TO-MEASURE**.

### §8.2 quality gates
- Intelligible codec roundtrip — **DONE (mock)** (`runs/phase-5-6-10-speech`).
- Consistent turn-state transitions — **DONE** (`runs/phase-4-8-edge`).
- Safe filler classification, low false positives — **DONE** (`runs/phase-2-3-client`).
- Emotion conditioning, identity-preserving — **DONE** (`runs/phase-9-persona`).
- Hinglish improves on held-out tests — **DONE (scorer)** (`evals/hinglish/scorer.py`,
  `runs/phase-15-evals`); real model gains **PENDING-EXTERNAL** (training, Q-004/Q-005).
- Fallback route functional during incidents — **DONE** (`runs/phase-7-13-aux`).

### §8.3 safety gates
- Non-consensual cloning blocked — **DONE** (`runs/phase-11-safety`).
- Risky-speech moderation auditable — **DONE** (`runs/phase-11-safety`).
- Watermark hooks tested — **DONE (fallback)** (`runs/phase-11-safety`); real AudioSeal
  **PENDING-EXTERNAL** (Q-007).
- Protected-voice list + review workflow operating — **DONE** (`runs/phase-11-safety`).

---

## Readiness rollup

| Bucket | Count | Items |
|---|---|---|
| **DONE (CPU-verified)** | 9 of 13 §14 items fully done | #1, #3, #4, #5, #8, #9, #11, #12, plus the DONE half of #2/#6/#7/#10/#13 |
| **PENDING-EXTERNAL** | model pins + live services | #2 (exact checkpoints), #6 (real Mimi), #7 (real Moshi), #10 (real AudioSeal), #13 (live rehearsal); infra: Postgres/Qdrant/Prometheus provisioning |
| **TO-MEASURE** | live latency on GPU | §8.1 sub-300 ms ambition, interruption stop budget, p50/p95/p99 under load |

**Bottom line:** the SoulYatri system is **code-complete and CPU-verified** across all 18
prior phases — every subsystem imports on CPU with deterministic fallbacks, has passing
tests, and an acceptance record under `runs/`. It is **not yet launch-GO for live public
traffic**: the speech-native core (Moshi/Mimi) and real services (GPU, Postgres, Qdrant,
Prometheus, AudioSeal) are `pending-human-pin` / unprovisioned, and **no live latency has
been measured**. The remaining work is a hardware bring-up that flips each
PENDING-EXTERNAL / TO-MEASURE item green — tracked as the issue backlog in
`docs/launch/HANDOFF_PACK.md` §6.
