# OPERATING_MANUAL — Daily Agent Operating Loop (Phase 18A)

> **Source:** `final_use.md` §Phase 18A (daily operating loop), §9 (agent task template),
> §10 (ticket slicing), §3.3 (global Definition of Done), §4 (branching/worktree rule).
> **Companion contract:** `docs/AGENT_PROTOCOL.md` — this manual is the *daily cadence*
> layered on top of that *governance contract*. Where they overlap, `AGENT_PROTOCOL.md`
> is authoritative on rules; this manual is authoritative on rhythm.
>
> **Goal (final_use.md §18A acceptance):** agents and humans can coordinate without
> stepping on each other.

---

## 0. Operating principles (do not relitigate)

1. **One micro-phase per agent at a time.** A "task slice" is exactly one `A`/`B`/`C`
   micro-phase from `final_use.md` §6, never a whole macro phase. (`final_use.md` §10,
   `AGENT_PROTOCOL.md` §1.)
2. **Touch only owned folders.** Cross-cutting edits to `shared/contracts.py` or
   `docs/INTERFACES.md` require explicit review. (Ownership map below.)
3. **No merge without acceptance evidence** under `runs/<phase>-<slug>/acceptance.md`.
   (`final_use.md` §3.3; `AGENT_PROTOCOL.md` §6.)
4. **Architecture is frozen.** The speech-native loop
   `Audio → Mimi → Moshi → Mimi → Audio` is never redesigned by a daily task
   (`docs/DECISIONS.md` D-002). Ambiguities go to `docs/OPEN_QUESTIONS.md`, not into code.
5. **CPU-only reality.** Heavy deps (torch/transformers/moshi/mimi/numpy) are lazy-loaded
   behind capability checks; nothing GPU-bound at module import (D-008).

### Folder ownership map (`final_use.md` §4, mirrored from `AGENT_PROTOCOL.md` §1)

| Folder | Owner role |
|---|---|
| `client/` | client agent |
| `edge/` | edge/runtime agent |
| `speech/` | speech/runtime agent |
| `aux/` | auxiliary reasoning agent |
| `memory/` | memory agent |
| `safety/` | safety agent |
| `infra/` | infra/SRE agent |
| `evals/` | evaluation agent |
| `training/` | data/training agent |
| `docs/` | documentation agent |
| `server/`, `client/` (existing) | gateway/baseline — change only with explicit approval (D-003) |

---

## 1. Daily triage (start of each working session)

Triage is a short, fixed sequence. It produces *today's task slices* and nothing else.

| Step | Action | Source / artifact |
|---|---|---|
| T1 | **Scan open work.** Read the issue backlog (next-cycle items in `docs/launch/HANDOFF_PACK.md` §6) + any open PRs. | HANDOFF_PACK §6 |
| T2 | **Check the gate board.** Read the latest regression report under `runs/` and the launch-readiness status in `docs/launch/LAUNCH_READINESS.md`. Any red gate is the day's first priority. | `evals/gates.py`, LAUNCH_READINESS |
| T3 | **Pull `pending-human-pin` items.** Anything blocked on a human pin (`docs/MODEL_LOCKS.md`, `docs/OPEN_QUESTIONS.md`) is surfaced for the human, not worked around. | MODEL_LOCKS, OPEN_QUESTIONS |
| T4 | **Slice tasks.** Convert each ready item into exactly one micro-phase ticket using the §9 template (below). One slice per agent. | `final_use.md` §9/§10 |
| T5 | **Assign branches.** Each slice gets an isolated branch/worktree named `<domain>/<phase>-<slug>`. | `AGENT_PROTOCOL.md` §1 |

**Triage exit criterion:** every active agent has exactly one assigned micro-phase, an
owned-folder list, and a target acceptance file path.

---

## 2. Task slicing — the §9 ticket template

Every assigned slice **must** be written as this ticket before work starts. This is the
`final_use.md` §9 template, kept verbatim so daily tickets and the governance contract
never drift.

```text
Goal:
Implement one micro-phase exactly as specified in the master guide (cite phase id, e.g. 5B).

Scope:
Touch only the files and folders owned by this task.

Inputs:
- final_use.md (the micro-phase contract)
- docs/INTERFACES.md, docs/DECISIONS.md, docs/MODEL_LOCKS.md, docs/LATENCY_TARGETS.md
- existing repo interfaces (server/pipeline/*, shared/contracts.py)

Deliverables:
- code
- tests
- short design note / README update
- benchmark notes if performance-sensitive

Acceptance:
- behavior matches the micro-phase contract
- ruff + mypy + pytest pass (CPU-only)
- structured logs exist
- acceptance evidence recorded in runs/<phase>-<slug>/acceptance.md

Do NOT:
- redesign architecture
- introduce hidden dependencies
- touch unrelated folders
- merge without acceptance evidence
```

**Slicing rules:**
- One ticket = one micro-phase = one branch = one acceptance file.
- If a slice cannot be finished without touching another agent's folder, **stop** and
  raise a cross-cutting review request instead of widening scope.
- If the slice is blocked on a missing pin/weight/service, mark it `PENDING-EXTERNAL`,
  cite the `MODEL_LOCKS.md` row / `OPEN_QUESTIONS.md` ID, and pick a different slice.

---

## 3. Benchmark review cadence

Performance-sensitive changes are gated by the Phase 15 evaluation harness, not by vibes.

| Cadence | What is reviewed | Tooling | Gate |
|---|---|---|---|
| **Per PR** | TTFA, first-token, turn-end delay, filler hit/false-positive, interruption recovery, WER, emotion agreement, code-switch, naturalness on the fixed replay scenarios. | `evals/replay/harness.py`, `evals/gates.py` | PR **fails** on threshold regression (`RegressionGate`). |
| **Daily** | The latest `runs/` regression report vs the previous one; any drift even within threshold is noted in triage T2. | `evals/latency/metrics.py` (p50/p95/p99), `evals/observability.py` | Drift logged; sustained drift opens a backlog item. |
| **Pre-release** | Full launch-readiness gate sweep across all subsystems. | `docs/launch/RELEASE_CHECKLIST.md` | No launch without a green sweep. |

**Honesty rule (grounding):** the replay harness runs on **deterministic fixtures and a
mock pipeline** on CPU (`evals/replay/mock_pipeline.py`). It proves the *gate logic and
regression discipline* work. **Real wall-clock latency on target hardware has not been
measured** (no GPU / no Moshi-Mimi weights — `docs/MODEL_LOCKS.md` Moshi/Mimi rows are
`pending-human-pin`). Live numbers are "to be measured on target hardware" and must never
be reported as if observed. (`docs/LATENCY_TARGETS.md` staged gates; Q-008.)

---

## 4. Long-job approval (training / heavy compute)

No long or expensive job runs on a whim. Training is governed by Phase 14 discipline.

| Job class | Examples | Approval rule |
|---|---|---|
| **CPU dry-run** | `python -m training.sft.lora_sft --dry-run`, replay sweeps, lint/test. | No approval needed; default daily work. |
| **GPU adaptation** | SFT/LoRA (`training/sft/lora_sft.py`), DPO-lite (`training/preference/dpo_lite.py`) on a GPU host. | **Requires human approval** + a measurable-gain gate (`min_product_gain`); enforces the no-scratch-training rule (`final_use.md` §3.2, D-005). Records a reproducible `RunManifest`. |
| **Scratch pretraining** | Foundation-model pretraining. | **Forbidden** at this stage (D-005, "Do-not-build-yet" list). Requires a new human ADR to even consider. |

Every approved long job records its manifest (config, seed, data hash, metrics,
`executed` flag) and lands an acceptance note under `runs/`. On this CPU host, a real run
raises `TrainingUnavailableError` by design (`runs/phase-14-training/acceptance.md`).

---

## 5. Release cadence

| Stage | Trigger | Gate document |
|---|---|---|
| **Continuous (main)** | Every merged PR is green on CPU CI (`.github/workflows/ci.yml`: ruff + mypy + pytest). | `AGENT_PROTOCOL.md` §3 PR checklist |
| **Staging** | Accumulated slices form a coherent increment. | `infra/deploy/RUNBOOKS.md` (staging) |
| **Canary** | Staging is reproducible; rollback rehearsed. | `infra/deploy/release_policy.yaml` + `infra/deploy/rollback.py` (`RollbackEvaluator`) |
| **Beta / public** | Full `docs/launch/RELEASE_CHECKLIST.md` `# Release Gate` passes; `docs/launch/LAUNCH_READINESS.md` has no unexplained red item. | RELEASE_CHECKLIST + LAUNCH_READINESS |

Canary rollback is automatic on threshold breach (`p95_ttfb_ms`, `error_rate_pct` in
`release_policy.yaml`). Rollback must be **rehearsed** before any beta (launch-readiness
final item).

---

## 6. Multi-agent worktree / branch coordination

Consistent with `docs/AGENT_PROTOCOL.md` §1 and §10 ticket slicing.

- **Isolation.** Each active agent works in its own branch or git worktree. No shared
  scratch branches. Branch name: `<domain>/<phase>-<short-slug>`
  (e.g. `speech/5a-mimi-bridge`, `edge/4b-turn-state`, `docs/18-launch-governance`).
- **Wave parallelism (`final_use.md` §10).** Agents are scheduled in waves so that
  same-folder collisions cannot happen within a wave:
  - Wave 1 — foundation (Phase 0+1, 2, 3)
  - Wave 2 — edge & runtime (Phase 4, 5, 6)
  - Wave 3 — support systems (Phase 7+12, 9+11, 10+13)
  - Wave 4 — data & evaluation (Phase 14, 15, 16)
  - Wave 5 — docs & launch (Phase 17, 18)
- **Cross-cutting contracts.** Only one agent at a time may propose a change to
  `shared/contracts.py` / `docs/INTERFACES.md`, and only via explicit review. New
  cross-subsystem types go into `docs/INTERFACES.md` **first**, then code.
- **Merge discipline.** Default branch (`main`/`master`) is never pushed to directly;
  open a PR. Human review merges **only after** tests + an acceptance note exist.
- **Destructive git ops** (force-push, `reset --hard`, `clean -f`, branch `-D`) require
  explicit human permission.
- **Conflict protocol.** If two slices need the same file, the second agent rebases after
  the first merges; they do not co-edit a shared branch.

---

## 7. End-of-slice checklist (Definition of Done, `final_use.md` §3.3)

A slice is **done** only when all of these exist:

- [ ] Code implementing exactly the micro-phase contract.
- [ ] Tests covering the new behavior, green on CPU-only CI.
- [ ] A short design note or README update.
- [ ] Structured logging hooks (consistent with `server/utils/logging_config.py` and the
      per-domain `obs.py` / `logging_hooks.py` shims).
- [ ] A benchmark / latency note if the change is performance-sensitive.
- [ ] An explicit acceptance result under `runs/<phase>-<slug>/acceptance.md`.

If any box is unchecked, the slice is **not** done — it does not merge and it does not
count toward a release.

---

## 8. Daily loop, one screen

```text
TRIAGE  → read backlog + gate board + pending pins
SLICE   → one micro-phase per agent (§9 ticket)
BRANCH  → <domain>/<phase>-<slug>, isolated worktree
BUILD   → code + tests + design note + logs (+ benchmark if perf)
VERIFY  → ruff + mypy + pytest (CPU) ; replay+gates if perf-sensitive
RECORD  → runs/<phase>-<slug>/acceptance.md
REVIEW  → PR checklist (AGENT_PROTOCOL §3) ; human merge only with acceptance
REPEAT  → next slice ; escalate pins to human, never improvise architecture
```
