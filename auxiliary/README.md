# `aux/` — Auxiliary text brain, STT utilities & operational fallback

> **Owner:** auxiliary reasoning agent (`final_use.md` §4).
> **Scope of this note:** Phase 7 (auxiliary text brain + STT + async reasoning) and
> Phase 13 (modular shipping baseline + operational fallback).

## Prime directive

The `aux/` subsystem is **auxiliary**. The canonical SoulYatri product is the
**speech-native** loop `Audio → codec tokens → Moshi → codec tokens → Audio`
(`final_use.md` §1.2, §2.1). Nothing in this folder may become the primary
conversational runtime (DECISIONS.md D-002). The classic STT→LLM→TTS path here exists
only as a **fallback / bring-up / comparison / degraded-mode** baseline.

## CPU / no-weights guarantee

Everything imports and tests on a CPU-only machine with **no GPU, no model weights, and
no guaranteed live Ollama**. Heavy backends (faster-whisper, Qwen3/Llama via Ollama,
edge-tts, Silero VAD, numpy) are imported **lazily** and every path has a
**deterministic stub fallback**. The stubs make the system fully exercisable and keep
tests hermetic.

```
python -c "import aux.stt.transcript_service, aux.text_brain.service, aux.fallback.orchestrator"
python -m pytest aux/tests -q
```

## Module map

| Phase | Module | Purpose |
|---|---|---|
| 7A | `aux/stt/transcript_service.py` | Async transcript service (faster-whisper / IndicConformer-ready) for transcripts, logs, search, moderation review. Async API + background worker queue; never blocks the voice loop. |
| 7B | `aux/text_brain/contracts.py` | Pydantic request/response + tool schema (`TextBrainRequest`, `TextBrainResponse`, `ToolSpec`, `ToolCall`). Dependency-light. |
| 7B | `aux/text_brain/prompts.py` | Versioned prompt builders per task; explicit auxiliary framing. |
| 7B | `aux/text_brain/service.py` | Qwen3/Llama serving interface over Ollama (lazy `httpx`), per-request timeouts, deterministic stub fallback, output parsing into the schema. |
| 7C | `aux/text_brain/jobs.py` | Async support-job worker pool: memory compression, transcript cleanup, RAG query prep, moderation summaries, dataset labeling. Emits `MemoryWrite` for durable content. |
| 13A | `aux/fallback/classic_baseline.py` | Composes VAD→STT→LLM→TTS by reusing server wrappers + aux components. Baseline/degraded path with per-stage timings. |
| 13B | `aux/fallback/temp_output.py` | Temporary speech-output adapter (XTTS/OpenVoice/edge-tts class) behind a stable interface. **Marked NOT final architecture** (`IS_FINAL_ARCHITECTURE = False`). |
| 13C | `aux/fallback/orchestrator.py` | Failover policy producing `shared.contracts.FallbackDecision`; telemetry + UX messaging + recovery hysteresis. |
| — | `aux/text_brain/obs.py` | Shared structured-logging shim (structlog-or-stdlib) + in-memory `TelemetryRecorder` (observability hooks). |

## Contracts used / produced

- **Imported from `shared.contracts`:** `FallbackDecision` (13C output), `MemoryWrite` /
  `MemoryKind` (7C job output). No new cross-subsystem types were added — per
  `docs/INTERFACES.md` §8, new shared types must go through that document first.
- **Local contracts** (`aux/text_brain/contracts.py`) stay inside the `aux/` boundary.

## Async / non-blocking design (7A & 7C)

Both `TranscriptService` and `SupportJobRunner` follow the same pattern:

1. An `asyncio.Queue` fed by `submit(...)` (returns a job id immediately).
2. A pool of background worker tasks (`start()` / `stop()`, or `async with`).
3. Synchronous model compute is dispatched with `asyncio.to_thread(...)` so the event
   loop is **never** blocked. A test (`test_transcription_does_not_block_event_loop`)
   asserts a concurrent heartbeat keeps ticking while a 300 ms blocking backend runs.
4. `drain()` waits for the queue to empty; `result(job_id)` awaits a single job.

## Fallback / failover design (13)

`FailoverOrchestrator.decide(PrimaryHealth)` applies an **explicit, ordered, auditable**
rule set (no hidden `if/else` sprawl):

```
manual_override > primary_unavailable > consecutive_failures > high_error_rate > high_latency > healthy
```

It records telemetry for every decision and applies **hysteresis** (N healthy probes
required) before leaving fallback so the system does not flap between modes.
`user_message(...)` returns short, non-alarming UX copy per reason.

## Definition of Done (`final_use.md` §3.3)

- ✅ **Code** — Phases 7A/7B/7C + 13A/13B/13C implemented under `aux/`.
- ✅ **Tests** — `aux/tests/` (43 tests): async non-blocking transcript service,
  text-brain output schema + timeout fallback, classic baseline composition, failover
  decision logic.
- ✅ **Design note** — this file.
- ✅ **Structured logging hooks** — `aux/text_brain/obs.py` (`get_logger` + `telemetry`)
  wired through every module.
- ✅ **Acceptance result** — `runs/phase-7-13-aux/acceptance.md`.

## Handoff notes for adjacent teams

- **Memory team:** `SupportJobRunner.compress_memory(...)` yields `MemoryWrite(kind=turn_summary)`
  when a `session_id` is supplied. Persistence is yours (Phase 12); we only produce the
  write object.
- **Safety team:** `summarize_moderation(...)` produces review-ready summaries;
  transcripts for moderation review come from `TranscriptService(..., purpose="moderation_review")`.
  These are inputs to your gate, not a substitute for it.
- **Evals team:** `ClassicBaseline.run(...)` returns `BaselineStageTimings`
  (stt/llm/tts/total ms) and the `telemetry` recorder exposes `aux_baseline_run` /
  `aux_failover_decision` events for replay/latency comparison against the speech-native core.
