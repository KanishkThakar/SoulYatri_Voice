# Acceptance — Phase 7 + Phase 13 (Auxiliary text brain, STT, fallback)

**Task:** Implement Phase 7 (auxiliary text brain, STT utilities, async reasoning) and
Phase 13 (modular shipping baseline + operational fallback) per `final_use.md`, within
the `aux/` ownership boundary.

**Environment:** Windows, Python 3.11.9, pydantic 2.13.4, httpx + pytest-asyncio present;
**no** structlog, **no** numpy, **no** faster-whisper, **no** GPU/weights, **no** live
Ollama. All heavy backends are lazy with deterministic stub fallbacks, so everything
imports and tests on CPU.

## Commands run

```text
# 1. Import smoke test (required)
python -c "import aux.stt.transcript_service, aux.text_brain.service, aux.fallback.orchestrator"
→ import OK                              (exit 0)

# 2. aux test suite (required)
python -m pytest aux/tests -q
→ 43 passed in 0.76s                     (exit 0)

# 3. Cross-check with shared contracts (no interference)
python -m pytest tests/test_contracts.py aux/tests -q
→ 62 passed                              (exit 0)

# 4. Lint (repo gate)
python -m ruff check aux
→ All checks passed!                     (exit 0)

# 5. Format check (repo gate)
python -m ruff format --check aux
→ 19 files already formatted             (exit 0)
```

## Files created

### Phase 7 — auxiliary text brain, STT, async reasoning
- `aux/stt/transcript_service.py` (7A) — async, non-blocking transcript service.
  faster-whisper backend (lazy) + deterministic `StubTranscriber`. Async `transcribe(...)`
  dispatches sync compute via `asyncio.to_thread`; background worker queue via
  `submit/result/drain`. Purposes: log / search / moderation_review / fallback.
- `aux/text_brain/contracts.py` (7B) — `TextBrainRequest`/`TextBrainResponse`, tool schema
  (`ToolSpec`, `ToolParam`, `ToolCall`), task enum, timeouts. Pydantic-only.
- `aux/text_brain/prompts.py` (7B) — versioned per-task prompt builders, explicit
  auxiliary framing.
- `aux/text_brain/service.py` (7B) — Qwen3/Llama serving interface over Ollama (lazy
  httpx), per-request timeout, output parsing, deterministic `StubTextBrain` fallback.
- `aux/text_brain/jobs.py` (7C) — `SupportJobRunner` async worker pool: memory
  compression, transcript cleanup, RAG query prep, moderation summaries, dataset
  labeling; emits `shared.contracts.MemoryWrite` for durable content.
- `aux/text_brain/obs.py` — structured-logging shim (structlog-or-stdlib) +
  `TelemetryRecorder` observability hooks (shared across the aux domain).

### Phase 13 — modular baseline & operational fallback
- `aux/fallback/classic_baseline.py` (13A) — `ClassicBaseline` composes VAD→STT→LLM→TTS,
  reusing `server/pipeline` wrappers by import where present and aux CPU-safe components
  otherwise. Returns per-stage timings + stub markers.
- `aux/fallback/temp_output.py` (13B) — `SpeechOutputAdapter` interface with
  `EdgeTTSAdapter` (wraps `server/pipeline/tts.py`, lazy) and `StubSpeechOutput` (silent
  PCM). Clearly marked **NOT final architecture** (`IS_FINAL_ARCHITECTURE = False`).
- `aux/fallback/orchestrator.py` (13C) — `FailoverOrchestrator` produces
  `shared.contracts.FallbackDecision`; explicit ordered rules, telemetry, UX messaging,
  recovery hysteresis.

### Tests + docs
- `aux/tests/__init__.py`, `aux/tests/conftest.py`
- `aux/tests/test_transcript_service.py` (12 tests)
- `aux/tests/test_text_brain.py` (15 tests)
- `aux/tests/test_fallback.py` (16 tests)
- `aux/README.md` (design note)
- `runs/phase-7-13-aux/acceptance.md` (this file)

## Phase 7 acceptance

- **7A — transcript service:** transcripts are generated **asynchronously and do not
  block the main loop**. `test_transcription_does_not_block_event_loop` injects a 300 ms
  blocking backend and asserts a concurrent heartbeat keeps ticking (≥10 ticks) because
  compute runs in a worker thread. Background queue submit/result/drain verified.
- **7B — text-brain contract:** tool calls and summaries are **deterministic enough for
  pipeline use** — the stub backend yields stable, schema-conformant output. **Timeout
  fallback** verified: a slow Ollama call past `timeout_s` degrades to a valid
  `TextBrainResponse(degraded=True, reason="timeout")` with no exception; client errors
  degrade to `reason="fallback:*"`.
- **7C — async support jobs:** the five named jobs complete without affecting voice
  latency (background pool); `memory_summary` with a `session_id` emits a `MemoryWrite`
  (`kind=turn_summary`). `drain()` clears the queue.

## Phase 13 acceptance

- **13A — classic baseline:** `ClassicBaseline` works for controlled tests on CPU
  (stub STT + stub TTS), produces a coherent reply and per-stage timings, and is tagged
  `is_final_architecture=False`.
- **13B — temporary output path:** fallback audio can ship in degraded mode behind a
  stable `SpeechOutputAdapter`; module is explicitly marked not-final and falls back to
  silent-PCM stub when edge-tts/pydub are absent.
- **13C — failover policy:** `FallbackDecision` produced for primary-unavailable, high
  latency, high error rate, consecutive failures, and manual override; rule ordering and
  recovery **hysteresis** verified; telemetry recorded; `user_message(...)` returns UX
  copy. Production incidents degrade gracefully without architecture confusion.

## Definition of Done (`final_use.md` §3.3)

- ✅ code — Phases 7A/7B/7C + 13A/13B/13C
- ✅ tests — `aux/tests/` (43 passing)
- ✅ design note — `aux/README.md`
- ✅ structured logging hooks — `aux/text_brain/obs.py` wired through all modules
- ✅ acceptance result recorded — this file

## Ownership compliance

- Only files under `aux/` (+ `aux/tests/`) and `runs/phase-7-13-aux/acceptance.md` were
  created/edited.
- `shared/`, `docs/INTERFACES.md`, `pyproject.toml`, and `server/` were **not** modified.
  `server/pipeline/{stt,tts,vad}.py` are reused by **import only** (lazy), never edited.
- Imports `FallbackDecision`, `MemoryWrite` (and `MemoryKind`) from `shared.contracts`;
  no new shared cross-subsystem types were introduced.

## Notes for adjacent teams

- **Memory team:** `SupportJobRunner.compress_memory(...)` returns a job whose
  `memory_write` is a ready-to-persist `MemoryWrite(kind=turn_summary)` when a
  `session_id` is provided. Persistence (Redis/Postgres/Qdrant, Phase 12) is yours.
- **Safety team:** `summarize_moderation(...)` and `TranscriptService(purpose=
  "moderation_review")` provide review inputs; they feed your moderation gate
  (Phase 11A) and do not replace it. Escalation/decisions remain in `safety/`.
- **Evals team:** `ClassicBaseline.run(...)` exposes `BaselineStageTimings`
  (stt/llm/tts/total ms); `aux.text_brain.obs.telemetry` records `aux_baseline_run`,
  `aux_failover_decision`, `aux_transcript*`, and `aux_text_brain` events for
  replay/latency comparison against the speech-native core.
- **All teams:** structlog is optional in this env — `aux/text_brain/obs.get_logger`
  transparently falls back to stdlib logging with the same `key=value` call style.
