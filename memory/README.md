# memory/ — Memory, retrieval, semantic tools & fallback reasoning (Phase 12)

> **Intent (final_use.md Phase 12):** give the assistant durable context *without poisoning
> the hot path*. Every retrieval must justify itself; every tool call must have a timeout and
> a graceful fallback.

This subsystem implements the cross-subsystem memory contracts from
[`shared/contracts.py`](../shared/contracts.py) / [`docs/INTERFACES.md`](../docs/INTERFACES.md)
§6 — `MemoryWrite`, `MemoryReadQuery`, `MemoryReadResult`, `MemoryKind` — and builds the three
storage tiers, a retrieval summarizer, and a safe tool router on top of them.

## Design principles

1. **Lazy-connect + in-memory fallback everywhere.** Redis, Postgres, and Qdrant are all
   optional at runtime. Each backend tries to connect on first use with a short timeout; if
   the driver is missing, the server is down, or any operation raises, it transparently
   degrades to a bounded in-process store. The whole subsystem (and its tests) runs with **no
   external services** on a CPU-only machine with no model weights (DECISIONS D-008).
2. **Never block the hot path.** Short socket/connect timeouts, bounded ring buffers, bounded
   `top_k`, a retrieval deadline budget, and tool timeouts keep latency predictable. A dead
   backend flips an instance to its fallback for the rest of its life rather than retrying on
   every call.
3. **Bounded, justified retrieval.** Reads are capped by `RetrievalPolicy` (`max_top_k`,
   `min_score`, recency decay) so memory stays compact and relevant.
4. **Graceful degradation is structural.** A failing tier is skipped, not fatal; a failing
   tool returns a structured `ToolResult` (never an exception) and may escalate to the aux
   text-brain.

## Layout

```
memory/
  contracts.py            # memory-internal helpers built on shared.contracts
  store.py                # MemoryStore facade — write/read policy orchestration
  _text.py                # tokenize / relevance / recency / cosine / hash_embedding
  _logging.py             # structured logging hooks (structlog or stdlib shim)
  redis/hot_cache.py      # 12A — Redis hot cache + in-memory fallback
  postgres/profile_store.py  # 12A — Postgres profile/relational store + dict fallback
  qdrant/semantic_memory.py  # 12A — Qdrant vector store + numpy/in-memory cosine fallback
  summarizer/pipeline.py  # 12B — turn compression, summarization, relevance, pruning
  tool_router/contracts.py   # 12C — tool schema, timeout/retry policy, allowlist, escalation
  tool_router/router.py      # 12C — safe tool invocation w/ timeout, retry, graceful failure
  tests/                  # pytest coverage for all of the above
```

## 12A — Memory tiers

| Tier | Module | Backend | Fallback | Role |
|---|---|---|---|---|
| hot | `redis/hot_cache.py` | Redis (list + EXPIRE) | bounded `deque` ring w/ TTL | recent-turn recall, fastest |
| profile | `postgres/profile_store.py` | Postgres (`psycopg` v3, upsert) | dict, upsert by `(session, kind, key)` | durable profile/preferences |
| semantic | `qdrant/semantic_memory.py` | Qdrant (cosine collection) | in-proc vectors + cosine | long-term semantic recall |

**Embeddings.** `MultilingualE5Embedder` lazily loads `intfloat/multilingual-e5-small` via
`sentence-transformers` when available (applying the `query:`/`passage:` prefixes the model
expects). With no weights it falls back to a deterministic 384-dim hashing-trick embedding
(`memory/_text.py::hash_embedding`) so vector shapes match a later real-model swap.

**Write/read policy.** `MemoryStore` fans a write out to the tiers its `MemoryKind` routes to
(`DEFAULT_WRITE_POLICY`) and merges bounded reads across tiers, de-duping by record id and
keeping the best score per record before truncating to the effective `top_k`:

| Kind | Tiers written |
|---|---|
| `turn_summary` | hot + semantic |
| `preference` | hot + profile |
| `profile` | profile |
| `tool_result` | hot |

```python
from memory import MemoryStore
from shared.contracts import MemoryWrite, MemoryReadQuery, MemoryKind

store = MemoryStore()                 # all tiers, fallbacks baked in
store.write(MemoryWrite(session_id="s1", kind=MemoryKind.preference,
                        content={"language": "hinglish"}))
result = store.read(MemoryReadQuery(session_id="s1", query="language", top_k=5))
# result.items -> [{..., "score": 0.87}], result.latency_ms -> int
```

## 12B — Retrieval summarizer (`summarizer/pipeline.py`)

`SummarizerPipeline` keeps retrieved context relevant and compact:

- **turn compression** — `compress_turn()` collapses whitespace and extractively trims a
  verbose turn to a char budget (handles Hindi `।` sentence breaks).
- **memory summarization** — `summarize_memories()` fuses many records into one deduped,
  newest-first digest, with an optional `summarize_fn` hook for the aux text-brain
  (abstractive). Hook failures degrade to the extractive digest.
- **relevance scoring** — `score_relevance()` blends lexical overlap with recency decay;
  `rerank()` thresholds + sorts; `build_context()` returns a bounded `RetrievedContext`.
- **stale-memory pruning** — `prune()` drops records past a max age or below a recency floor,
  then caps survivors at `max_keep` (freshest kept).

## 12C — Tool contracts & router (`tool_router/`)

Kept inside `memory/` to respect file ownership. `ToolRouter.invoke()` guarantees it **always
returns a `ToolResult` and never raises into the voice runtime**:

- **schema** — `ToolSpec` (handler + `safe` flag + per-tool timeout/retry), `ToolCall`,
  `ToolResult`, `ToolStatus` (`ok|timeout|error|blocked|escalated`).
- **timeout policy** — handlers run in a worker thread; the caller waits at most `timeout_ms`,
  so a hung tool can't block the hot path.
- **retry policy** — bounded `max_attempts` with exponential backoff; optional retry-on-timeout.
- **safe-tool allowlist** — only allowlisted tools run; everything else is `blocked`. With no
  explicit allowlist, tools registered `safe=True` are auto-allowed.
- **text-brain escalation** — exhausted timeouts/errors produce an `EscalationDecision` and, if
  a `text_brain` callable is wired, hand off to it (its own failures stay graceful). Blocked-by-
  policy calls do **not** escalate.

```python
from memory.tool_router import ToolRouter, ToolCall
router = ToolRouter()
router.register_fn("get_time", lambda: "12:00", safe=True)
res = router.invoke(ToolCall(session_id="s1", tool="get_time"))   # res.ok, res.output
```

## Structured logging hooks

`memory/_logging.py::get_logger(name)` binds to `structlog` (matching
`server/utils/logging_config.py`) when installed, else a stdlib shim with the same
`log.info("event", key=value)` call style. Every write/read/tool invocation emits a structured
event (`hot_cache_write`, `store_read`, `tool_invoke_done`, `*_fallback_memory`, …) so the
active backend and degradation paths are observable.

## Running tests

```bash
python -c "import memory.redis.hot_cache, memory.qdrant.semantic_memory, memory.summarizer.pipeline"
python -m pytest memory/tests -q
```

All tests pass with **no Redis/Postgres/Qdrant** running and **no model weights** installed.
See [`runs/phase-12-memory/acceptance.md`](../runs/phase-12-memory/acceptance.md).
