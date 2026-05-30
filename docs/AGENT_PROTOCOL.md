# AGENT_PROTOCOL — Execution Governance

> Source: `final_use.md` §3.3 (global Definition of Done), §4 (branching/worktree rule),
> §9 (agent task template), §10 (ticket slicing). This document is the operating contract
> for every agent (human or AI) touching the repo.

---

## 1. Branch & worktree rules

- Each active agent works in an **isolated branch or git worktree**. No shared scratch
  branches.
- Branch naming: `<domain>/<phase>-<short-slug>`, e.g. `speech/5a-mimi-bridge`,
  `edge/4b-turn-state`, `docs/0-architecture-freeze`.
- One **task slice per agent** at a time (see ticket slicing in `final_use.md` §10).
- Touch only the files and folders **owned by the task** (ownership map below). Cross-cutting
  changes to `shared/contracts.py` or `docs/INTERFACES.md` require explicit review.
- Human review merges **only after** tests and an acceptance note exist.
- Default branch (`main`/`master`) is never pushed to directly; open a PR.
- Destructive git operations (force-push, `reset --hard`, `clean -f`, branch `-D`) require
  explicit human permission.

### Folder ownership map (`final_use.md` §4)
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

## 2. Global Definition of Done (`final_use.md` §3.3)

A task is **not complete** until **all** of the following exist:
- [ ] **Code** that implements exactly the micro-phase contract.
- [ ] **Tests** covering the new behavior (pass on CPU-only CI).
- [ ] A short **design note or README update**.
- [ ] **Structured logging hooks** (consistent with `server/utils/logging_config.py`).
- [ ] A **benchmark or latency note** if the change is performance-sensitive.
- [ ] An explicit **acceptance result recorded** in `runs/` or `docs/`.

---

## 3. PR review checklist

Before requesting merge, confirm:
- [ ] Scope matches the assigned micro-phase; no unrelated folders touched.
- [ ] Architecture unchanged — speech-native core (`Audio → Mimi → Moshi → Mimi → Audio`)
      is **not** redesigned (D-002). Any text-first shortcut is fallback-only.
- [ ] Uses shared contracts from `shared/contracts.py`; no duplicate/incompatible types.
- [ ] Any new cross-subsystem type was added to `docs/INTERFACES.md` first.
- [ ] No GPU/weights/torch/transformers/moshi/mimi imported at module top-level in
      `shared/` or scaffold packages; heavy deps are lazy-loaded behind capability checks.
- [ ] `ruff`, `mypy`, and `pytest` pass locally and in CI.
- [ ] Definition of Done items above are all checked.
- [ ] Safety: no non-consensual voice cloning path; consent + watermark gates respected.
- [ ] Unclear items written to `docs/OPEN_QUESTIONS.md` rather than improvised.

---

## 4. Issue template

```md
### Goal
Implement one micro-phase exactly as specified in final_use.md (cite phase id).

### Scope
Folders/files owned by this task only:
- ...

### Inputs
- final_use.md (phase contract)
- docs/INTERFACES.md, docs/DECISIONS.md, docs/MODEL_LOCKS.md
- existing repo interfaces (server/pipeline/*, shared/contracts.py)

### Deliverables
- code
- tests
- short design note / README update
- benchmark note (if performance-sensitive)

### Acceptance
- behavior matches the micro-phase contract
- ruff + mypy + pytest pass
- structured logs exist
- acceptance evidence recorded in runs/ or docs/

### Do NOT
- redesign architecture
- introduce hidden dependencies
- touch unrelated folders
- merge without acceptance evidence
```

## 5. PR template

```md
## What
<one-line summary; cite phase id>

## Why
<link to issue / micro-phase>

## Changes
- ...

## Tests
- commands run + result (CPU-only)

## Acceptance evidence
- link to runs/<...> or docs/<...>

## Checklist
- [ ] Scope respected (owned folders only)
- [ ] Architecture unchanged (speech-native core preserved)
- [ ] Shared contracts used; INTERFACES.md updated if new types
- [ ] No top-level heavy/GPU imports in shared/scaffold
- [ ] ruff + mypy + pytest green
- [ ] Definition of Done complete
- [ ] Safety gates respected
```

---

## 6. Acceptance evidence convention

Record per-task acceptance under `runs/` as `runs/<phase>-<slug>/acceptance.md` (or `.json`
for machine-readable metrics), including: what was run, the command, the result, and any
latency/benchmark numbers. See `runs/README.md`.
