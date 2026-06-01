# Phase 12 — Memory, retrieval, semantic tools & fallback reasoning — Acceptance

**Owner:** memory agent · **Scope:** `memory/` tree only · **Status:** ✅ complete

Implements final_use.md Phase 12 (12A memory tiers, 12B retrieval summarizer, 12C tool
contracts) against the canonical contracts in `shared/contracts.py` / `docs/INTERFACES.md` §6.
Environment: CPU-only, no model weights; Redis/Postgres/Qdrant **not** required.

## Definition of Done (final_use.md §3.3)

| Requirement | Status | Evidence |
|---|---|---|
| code | ✅ | `memory/{contracts,store,_text,_logging}.py`, `redis/hot_cache.py`, `postgres/profile_store.py`, `qdrant/semantic_memory.py`, `summarizer/pipeline.py`, `tool_router/{contracts,router}.py` |
| tests | ✅ | `memory/tests/` — 86 tests, all passing |
| design note / README | ✅ | `memory/README.md` |
| structured logging hooks | ✅ | `memory/_logging.py` (structlog-or-stdlib shim); every backend emits structured events |
| benchmark/latency note | ✅ (bounded) | `RetrievalPolicy.deadline_ms`, bounded `top_k`, tool `timeout_ms`; reads attach `latency_ms` |
| acceptance recorded in `runs/` | ✅ | this file |

## Acceptance criteria (Phase 12 table)

| Micro-phase | Acceptance test | Result |
|---|---|---|
| 12A memory tiers | "memory retrieval is fast and bounded" | ✅ all three tiers respect `top_k` (clamped by `RetrievalPolicy.max_top_k`); reads carry `latency_ms`; ring/age bounds enforced |
| 12B retrieval summarizer | "retrieved context remains relevant and compact" | ✅ rerank thresholds by relevance, dedupes; `build_context` is bounded (`max_records`) + compact (`digest_max_chars`); pruning drops stale memory |
| 12C tool contracts | "tool failures degrade gracefully without breaking voice runtime" | ✅ `invoke()` never raises; timeout/retry/allowlist enforced; escalation to text-brain; text-brain failure stays graceful |

## Verification (run from repo root)

### 1. Required import check
```
$ python -c "import memory.redis.hot_cache, memory.qdrant.semantic_memory, memory.summarizer.pipeline"
VERIFY IMPORT OK
```

### 2. Memory test suite
```
$ python -m pytest memory/tests -q
86 passed in ~0.5s
```

Coverage by required area:
- **hot-cache write/read with fallback** — `tests/test_hot_cache.py` (write/read in memory
  fallback, TTL expiry, ring bound, recency order, kind filter, session isolation, clear).
- **bounded top_k retrieval** — asserted in `test_hot_cache.py`, `test_semantic_memory.py`,
  `test_profile_store.py`, `test_store.py` (both requested `top_k` and policy `max_top_k`).
- **summarizer relevance + pruning** — `tests/test_summarizer.py` (compression bounds,
  dedupe, relevance ranking, compact bounded context, prune by age / recency floor / max_keep).
- **tool-router timeout / allowlist / graceful failure** — `tests/test_tool_router.py`
  (timeout returns fast without blocking, unsafe/unknown tools blocked, retry-then-success,
  exhausted retries degrade, escalation to text-brain, graceful text-brain failure).
- Plus `tests/test_contracts.py` (re-exports match `shared`, no heavy imports) and
  `tests/test_store.py` (tier fan-out, dedupe across tiers, per-tier health, tier-failure
  isolation).

### 3. No external services / no weights confirmed
Redis, numpy, structlog, sentence-transformers, qdrant-client, psycopg are all absent in the
environment; tests pass entirely on in-memory fallbacks. Tests assert `torch`, `transformers`,
`qdrant_client`, `sentence_transformers`, `redis`, `psycopg` are never imported.

### 4. Lint
```
$ python -m ruff check memory
All checks passed!
```

### 5. No regression in the wider repo
```
$ python -m pytest -q
365 passed in ~1.2s
```

## File ownership compliance

Only files under `memory/` (incl. new `memory/tests/` and `memory/tool_router/`) and this
`runs/phase-12-memory/acceptance.md` were created/edited. No changes to `shared/`,
`docs/INTERFACES.md`, `pyproject.toml`, `server/`, or other domains. The tool router lives
under `memory/tool_router/` to respect ownership. `memory/contracts.py` only adds
memory-internal helper types and re-exports the canonical `shared.contracts` types unchanged.

## Notes for downstream teams

**aux / text-brain team:**
- `SummarizerPipeline(summarize_fn=...)` and `summarize_memories(..., summarize_fn=...)` accept
  a `Callable[[str], str]` hook — wire your Qwen3/Llama abstractive summarizer here for Phase
  7C memory compression. Failures in the hook degrade to the extractive digest automatically.
- `ToolRouter(text_brain=callable)` expects `(ToolCall, ToolResult) -> Any`. `EscalationDecision.task`
  carries a task hint (`tool_plan` by default) aligned with `aux/text_brain` `TextBrainRequest.task`.
  Only timeouts/errors escalate; policy-blocked calls do not.

**safety team:**
- The tool router enforces a **safe-tool allowlist** (`SafeToolAllowlist`); anything not
  allowlisted returns `ToolStatus.blocked`. Pass an explicit allowlist to disable the
  auto-allow-safe default. This is the natural choke point to enforce moderation/consent before
  a tool runs.
- Semantic/profile records persist raw `content`; apply moderation/PII policy upstream of
  `MemoryStore.write` if needed. `speaker_style_ref`/consent enforcement remains in `safety/`.

**infra/SRE:**
- Backends read `REDIS_URL`, `DATABASE_URL`, `QDRANT_URL` (with sane localhost defaults).
  `MemoryStore.healthcheck()` returns per-tier booleans (`False` == running on fallback) for
  monitoring dashboards.
