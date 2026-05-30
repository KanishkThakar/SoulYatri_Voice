# Acceptance — Phase 0 + Phase 1 Foundation

**Task:** Build the FOUNDATION (Phase 0 architecture freeze + Phase 1 repo scaffold,
CI, environments, service contracts) per `final_use.md`.

**Environment:** Windows, Python 3.11.9, pydantic 2.13.4, ruff 0.15.10. CPU-only,
no GPU, no Moshi/Mimi weights.

## Commands run

```text
# 1. Import smoke test (required)
python -c "import shared.contracts"
→ shared.contracts import OK   (exit 0)

# 2. Contract tests (required)
python -m pytest tests/test_contracts.py -q
→ 19 passed                    (exit 0)

# 3. All 43 domain packages import on CPU
python -c "import edge, speech, aux, memory, safety, infra, evals, training, ..."
→ all 43 packages import OK     (exit 0)

# 4. Lint
ruff check shared edge speech aux memory safety infra evals training tests
→ All checks passed!            (exit 0)

# 5. Format check (CI parity)
ruff format --check shared edge speech aux memory safety infra evals training tests
→ 47 files already formatted    (exit 0)
```

## Phase 0 acceptance (0A/0B/0C)
- Any agent can answer primary model (Moshi), codec (Mimi), filler path, memory path
  (Redis/Postgres/Qdrant), safety path (consent-first + watermark), and fallback path
  (classic STT→LLM→TTS baseline) from `docs/DECISIONS.md` + `docs/INTERFACES.md`.
- Model roles, language targets, latency budget, and session-state ownership documented;
  unresolved items captured in `docs/OPEN_QUESTIONS.md` (not improvised).
- Branch/worktree rules, review checklist, issue/PR templates, and global Definition of
  Done present in `docs/AGENT_PROTOCOL.md`.

## Phase 1 acceptance (1A/1B/1C)
- Repo tree from `final_use.md` §4 created as real packages alongside existing code; every
  folder has a stated owner/purpose; no "misc" directories.
- Quality gates: `pyproject.toml` (ruff + mypy + pytest), `.pre-commit-config.yaml`,
  `.github/workflows/ci.yml` (lint + type-check + pytest, CPU-only, py3.10 + py3.11).
- Environment contracts: `.env.example` extended with Postgres, Qdrant, Redis URL,
  embeddings, Mimi/Moshi/CSM, sherpa-onnx, watermarking, voice policy, moderation,
  Indic STT, observability — existing keys preserved.
- Shared contracts: `shared/contracts.py` implements AudioFrame, CodecChunk, TurnState,
  TurnEvent, EmotionState, PersonaState, RouteDecision, FallbackDecision, MemoryWrite,
  MemoryReadQuery/Result, VoiceRequest, ModerationDecision — all import cleanly on CPU.

## Notes
- `mypy` is configured (scoped to `shared` + `tests`) and runs in CI; it was not installed
  in the local shell, so type-checking is validated by CI rather than locally.
- Existing `server/` and `client/` baselines untouched; CI/lint/test scopes exclude them
  to avoid coupling the foundation gates to legacy conventions.
