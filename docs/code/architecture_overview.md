# Architecture Overview

> Grounded in [`docs/DECISIONS.md`](../DECISIONS.md), [`docs/INTERFACES.md`](../INTERFACES.md),
> [`shared/contracts.py`](../../shared/contracts.py), [`README.md`](../../README.md),
> `server/main.py`, `server/agent.py`, and the `edge/`, `speech/`, `aux/`, `memory/`,
> `safety/`, `infra/`, `evals/`, `training/` package trees that exist in this repository.

## 1. The frozen speech-native loop

SoulYatri's product identity is a **speech-native** voice AI — not a text chatbot that
happens to speak. The canonical runtime loop, frozen in
[DECISIONS.md](../DECISIONS.md) D-002, is:

```text
Audio → Mimi codec tokens → Moshi speech-native runtime → codec tokens → Audio
```

This preserves pauses, interruptions, intonation, laughter, emotional contour, speaking
rhythm, and turn-taking instead of flattening speech to text before responding. The end-
to-end shape (from `final_use.md` §2.1) is:

```text
Client mic → AEC/NS → VAD + local router → WebRTC/Opus transport
   → Edge runtime (turn detection, emotion, speaker, barge-in)
   → Mimi audio tokenizer → Moshi semantic runtime → emotion/persona layer
   → fast acoustic decoder → codec decoder → PCM stream → client playback
```

A traditional **STT → text-LLM → TTS** path may exist, but only as a fallback/degraded
shipping path, an observability aid, a tooling/data-prep path, or a temporary bring-up
baseline (DECISIONS.md D-002). It must never redefine the core architecture.

### Environment reality (D-008)

The development environment in this repo has **no GPU** and **no Moshi/Mimi weights**.
Therefore every foundation module imports and runs on CPU without weights, and heavy
optional dependencies (torch, transformers, moshi, mimi) are **not** imported at module
top level. Speech-native components are built as **interfaces + graceful fallbacks** that
become real once weights and hardware are pinned. This is visible throughout the code:

- `speech/codec/mimi_bridge.py` selects a `MimiBackend` only if weights load; otherwise a
  `MockCodecBackend` keeps the `encode`/`decode` roundtrip working.
- `speech/moshi_runtime/service.py` selects a `MoshiBackend` if available, else an
  `EchoTransformBackend` CPU fallback.
- `edge/emotion/extractor.py` and `edge/speaker/encoder.py` lazy-load SER / ECAPA models
  and fall back to deterministic signal-based features.
- `memory/store.py` tiers lazy-connect to Redis/Postgres/Qdrant and fall back to
  in-memory stores so the whole store "runs with NO services up".

## 2. Domain-folder map

The repository root *is* the `soulyatri/` root (DECISIONS.md D-003). The `final_use.md`
§4 domain folders are added **alongside** the existing `server/` and `client/`, not nested
under a new folder. Each folder has a single owner.

| Folder | Role | Key real modules |
|---|---|---|
| `client/` | Browser capture, local routing, transport, playback (Next.js + TS) | `client/src/audio/`, `client/src/app/` |
| `edge/` | Fast near-user decisions: turn detection, emotion, speaker, barge-in, planning, state machine | `edge/session/turn_state.py`, `edge/turn_detection/`, `edge/emotion/extractor.py`, `edge/speaker/encoder.py`, `edge/barge_in/detector.py`, `edge/planner/` |
| `speech/` | The speech-native core: codec bridge, token stream, Moshi runtime, decoder, persona | `speech/codec/mimi_bridge.py`, `speech/codec/token_stream.py`, `speech/moshi_runtime/service.py`, `speech/decoder/service.py`, `speech/persona/controller.py` |
| `aux/` | Auxiliary text: text-brain, STT utilities, classic fallback orchestration | `aux/text_brain/service.py`, `aux/stt/transcript_service.py`, `aux/fallback/orchestrator.py` |
| `memory/` | Tiered memory: Redis hot cache, Postgres profile, Qdrant semantic + tool router | `memory/store.py`, `memory/contracts.py`, `memory/redis/`, `memory/postgres/`, `memory/qdrant/`, `memory/tool_router/` |
| `safety/` | Consent-first voice policy, moderation gate, watermarking | `safety/moderation/gate.py`, `safety/voice_policy/policy.py`, `safety/watermark/audioseal.py`, `safety/contracts.py` |
| `infra/` | Scaling, regional routing, rollback, monitoring | `infra/scaling/scheduler.py`, `infra/deploy/regions.py`, `infra/deploy/rollback.py`, `infra/monitoring/` |
| `evals/` | Replay harness, latency/quality metrics, observability | `evals/replay/harness.py`, `evals/latency/metrics.py`, `evals/observability.py` |
| `training/` | Data engine, labeling, SFT, preference (no scratch pretraining) | `training/` tree |
| `shared/` | Cross-subsystem contracts | `shared/contracts.py` |
| `server/` | FastAPI gateway + Phase-1 classic baseline pipeline | `server/main.py`, `server/agent.py`, `server/pipeline/` |
| `docs/`, `scripts/`, `tests/`, `runs/` | Knowledge base, helpers, tests, acceptance evidence | — |

## 3. The shared contract surface

`shared/contracts.py` is the importable realization of [INTERFACES.md](../INTERFACES.md).
Every domain folder depends on these types rather than redefining incompatible local ones.
The contracts are pydantic v2 models + stdlib enums only (no GPU/torch imports), so they
import on CPU. The exported types (`shared/contracts.py::__all__`) are:

- **Audio:** `AudioFrame` (PCM frame), `CodecChunk` (Mimi/RVQ token packet).
- **Turn state:** `TurnState` (enum), `TurnEvent`.
- **Emotion/persona:** `EmotionState` (valence/arousal/dominance + warmth/uncertainty/pace/
  intensity), `PersonaState`.
- **Routing/latency:** `RouteTarget`, `RouteDecision`, `FallbackDecision`.
- **Memory:** `MemoryKind`, `MemoryWrite`, `MemoryReadQuery`, `MemoryReadResult`.
- **Safety:** `VoiceAction`, `VoiceRequest`, `ModerationDecision`.
- Helper: `now_ms()`.

`TurnState` values (`idle, listening, buffering, candidate_filler, forwarding, thinking,
speaking, barge_in, repairing, ended`) are aligned across `shared/contracts.py`,
`edge/session/turn_state.py`, and the Phase-1 `server/pipeline/turn_state.py`.

## 4. How the `server/` gateway + Phase-1 baseline fits

The repo already contains a working FastAPI gateway (`server/main.py`) and a Phase-1/2
pipeline under `server/pipeline/`. Per DECISIONS.md D-003 these are kept intact and serve
three roles:

1. **The WebRTC/WebSocket gateway** — `server/main.py` exposes `/health`, `/metrics`,
   `/api/token` (LiveKit token), and `/ws/audio/{session_id}` (binary PCM up/down + JSON
   control). See [api_protocol_reference.md](api_protocol_reference.md).
2. **The classic baseline / fallback path** (`final_use.md` Phase 13) — the
   `VoiceAgent` in `server/agent.py` orchestrates the classic loop:

   ```text
   Audio → WebRTC → VAD (Silero) → STT (faster-whisper) → LLM (Ollama Qwen3) → TTS (edge-tts) → Audio
   ```

   per [README.md](../../README.md). `VoiceAgent.handle_audio_frame` does a quick VAD
   check, then `_process_speech_segment` runs the pipeline, drives a `TurnStateMachine`,
   routes fillers, extracts emotion + speaker features in parallel, and handles barge-in.
3. **The reference implementation** for turn-state, emotion, speaker, filler, and barge-in
   semantics that the new `edge/` and `speech/` domain folders stay consistent with. For
   example `edge/session/turn_state.py` is a superset-aligned state machine of
   `server/pipeline/turn_state.py`, and `edge/emotion/extractor.py` keeps the same label
   space and V/A/D anchors as `server/pipeline/emotion.py`.

### Two pipelines, one contract

```text
PRIMARY (speech-native, speech/*):   AudioFrame → MimiCodecBridge.encode → CodecChunk
                                       → MoshiRuntimeService.stream_reply → CodecChunk
                                       → DecoderService.stream_decode → AudioFrame

BASELINE (classic, server/*):        PCM → SileroVAD → WhisperSTT → OllamaLLM → EdgeTTS → PCM
```

Both speak the same `shared.contracts` types at their boundaries, and `aux/fallback/
orchestrator.py` (`FailoverOrchestrator`) decides — via a `FallbackDecision` — when to route
to the classic baseline during incidents, with hysteresis so it does not flap.

## 5. Cross-subsystem flow (a single turn)

1. **Client** captures mic PCM, runs local VAD, may play a cached filler, and streams audio
   over WebRTC/WebSocket to the gateway.
2. **Edge** (`edge/turn_detection`, `edge/emotion`, `edge/speaker`, `edge/barge_in`) extracts
   streaming features and drives the `TurnStateMachine`; `edge/planner` classifies short
   turns and may start a safe speculative onset.
3. **Speech core** encodes audio to `CodecChunk`s (`MimiCodecBridge`), streams them through
   `MoshiRuntimeService`, conditions output with `PersonaController` (emotion/persona), and
   decodes back to audio with `DecoderService`.
4. **Aux** runs asynchronously: `TranscriptService` for logs/search, `TextBrainService` for
   memory summaries / tool plans / moderation summaries.
5. **Memory** persists writes across tiers (`MemoryStore`) and serves bounded reads.
6. **Safety** gates the turn (`ModerationGate`), enforces consent (`VoicePolicy`), and
   watermarks generated audio (`Watermarker`).
7. **Infra** admits/queues sessions (`SessionScheduler`), routes by region (`RegionRouter`),
   and evaluates canary health (`RollbackEvaluator`).
8. **Evals** replay scenarios (`ReplayHarness`) and track latency/quality metrics.

## 6. What is intentionally not built yet

Per DECISIONS.md "Do-not-build-yet" list: scratch pretraining, a new neural codec, giant
training jobs before a latency baseline, UI polish over runtime correctness, clever/
unpredictable filler logic, and any non-consensual voice-cloning pathway. The filler
subsystem stays simple, bounded, and disableable (D-006); voice features are consent-first
and watermarked (D-007).
