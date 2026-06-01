# Module Reference

> Per-subsystem reference with **real** module names, key classes/functions, and their
> inputs→outputs. Every name below was verified by reading the source file named in the
> heading. Where a module lazy-loads an optional model, the documented behavior is the
> CPU/no-weights fallback path that actually runs in this repo (DECISIONS.md D-008).

---

## 0. Shared contracts — `shared/contracts.py`

The importable realization of [INTERFACES.md](../INTERFACES.md). Pydantic v2 models +
stdlib enums only. Exported names (`__all__`): `now_ms`, `AudioFrame`, `CodecChunk`,
`TurnState`, `TurnEvent`, `EmotionState`, `PersonaState`, `RouteTarget`, `RouteDecision`,
`FallbackDecision`, `MemoryKind`, `MemoryWrite`, `MemoryReadQuery`, `MemoryReadResult`,
`VoiceAction`, `VoiceRequest`, `ModerationDecision`.

| Type | Kind | Key fields / values | Inputs → Outputs |
|---|---|---|---|
| `AudioFrame` | model | `session_id, seq, pcm: list[float], sample_rate=16000, ts_ms, is_final` | In-process view of a PCM frame; JSON round-trippable. |
| `CodecChunk` | model | `turn_id, seq, codec_tokens: list[int], ts_ms, is_final, sample_rate=24000` | Mimi/RVQ token packet bridging audio ↔ runtime. |
| `TurnState` | enum | `idle, listening, buffering, candidate_filler, forwarding, thinking, speaking, barge_in, repairing, ended` | Canonical conversational states. |
| `TurnEvent` | model | `session_id, from_state, to_state, trigger, ts_ms, metadata` | Emitted on every transition. |
| `EmotionState` | model | `valence/arousal/dominance ∈[-1,1]`, `warmth/uncertainty/pace/intensity ∈[0,1]`, `label, confidence` | Continuous affect latents. |
| `PersonaState` | model | `persona_id, speaker_style_ref, emotion: EmotionState, language` | Identity-preserving turn conditioning. |
| `RouteTarget` | enum | `cached_filler, full_stack, silent_wait` | Router target. |
| `RouteDecision` | model | `route, phrase_id, intent, confidence, reason, emit_filler_then_forward` | Output of local/edge router + filler. |
| `FallbackDecision` | model | `use_fallback, reason, expected_recovery_ms` | Speech-native ↔ classic failover. |
| `MemoryKind` | enum | `turn_summary, preference, profile, tool_result` | Memory write kind. |
| `MemoryWrite` | model | `session_id, kind, content: dict, ts_ms` | A write into the tiered store. |
| `MemoryReadQuery` | model | `session_id, query, kinds, top_k` | Bounded retrieval request. |
| `MemoryReadResult` | model | `session_id, items: list[dict], latency_ms` | Retrieval result. |
| `VoiceAction` | enum | `style_transfer, voice_clone, persona_render` | Consent-gated voice action. |
| `VoiceRequest` | model | `voice_ref_id, consent_token, requested_action` | Consent-gated request. |
| `ModerationDecision` | model | `allowed, category, escalate, reason` | Moderation gate output. |
| `now_ms()` | func | — | `() → int` wall-clock ms. |

---

## 1. Edge subsystem — `edge/`

### `edge/session/turn_state.py` — `TurnStateMachine`

Explicit, auditable conversational state machine (no hidden if-else sprawl).

- **Classes:** `TurnStateMachine`, `TransitionRejected` (with `to_dict()`),
  `InvalidTransitionError`. Uses `shared.contracts.TurnState` / `TurnEvent`.
- **State accessors:** `state`, `previous_state`, `turn_id`, `state_entered_ms`, `events`,
  `rejections`, `is_user_speaking`, `is_agent_speaking`, `is_processing`,
  `time_in_state_ms(now=…)`.
- **Transitions:** `can_transition(to_state) → bool`; `transition(to_state, trigger, …)`
  returns a `TurnEvent` or raises `InvalidTransitionError`; `try_transition(...)` returns
  `TurnEvent | TransitionRejected` (never raises).
- **Timeouts:** `timeout_ms()`, `is_timed_out(now=…)`, `check_timeout(now=…) → TurnEvent | None`.
- **Semantic event helpers** (each returns `TurnEvent | TransitionRejected`):
  `on_speech_start`, `on_speech_end`, `on_turn_confirmed`, `on_filler_handled`,
  `on_pipeline_needed`, `on_pipeline_start`, `on_response_ready`, `on_speaking_done`,
  `on_barge_in`, `on_repair_start`, `on_repair_done`, `on_session_end`; `reset()`.
- **Inputs → outputs:** event helper / `transition()` call → validated state change emitting
  a `TurnEvent`, or an auditable `TransitionRejected`.

### `edge/turn_detection/features.py` — streaming features

- **`VADProvider`** — `speech_probability(samples, sample_rate=16000) → float`. Tries to
  load Silero; `using_fallback` true → energy-threshold `_fallback_probability`.
- **`SpeechFeatures`** (dataclass, `to_dict()`) — per-frame feature record.
- **`StreamingFeatureExtractor`** — `process_frame(...)` and `stream(...)`; `in_speech`,
  `reset()`. Inputs: PCM frames → outputs: streaming `SpeechFeatures` (no full-utterance
  blocking).

### `edge/turn_detection/detector.py` — endpointing

- **`EndpointingDetector`** — `process_frame(samples, ts_ms) → EndpointDecision`,
  `process_probability(speech_probability, ts_ms) → EndpointDecision`, `stream(...)`;
  accessors `in_speech`, `using_fallback`, `trailing_silence_ms`, `reset()`.
- **`EndpointDecision`** (dataclass, `to_dict()`) — speech start/end markers.

### `edge/barge_in/detector.py` — interruption detection

- **`BargeInDetector`** — `set_agent_speaking(is_speaking, now=…)`, then
  `check(session_id, speech_probability, now=…) → BargeInEvent | None`;
  `mark_false_positive()`, `reset()`, `metrics`, `agent_is_speaking`. Bounds false positives
  via consecutive-frame debounce, hysteresis decay, and a cooldown window.
- **`BargeInEvent`** (dataclass) — `session_id, ts_ms, speech_probability,
  time_since_agent_started_ms, detection_latency_ms, cancel=True, repair=True`.
- **`BargeInMetrics`** (dataclass) — `false_positive_rate`, `mean_detection_latency_ms`.
- **Inputs → outputs:** per-frame VAD probability while agent speaks → confirmed
  `BargeInEvent` carrying cancel + repair signals.

### `edge/emotion/extractor.py` — `EmotionExtractor`

- `extract(samples, sample_rate=16000) → shared.contracts.EmotionState`. Lazy-loads a
  wav2vec2-class SER model (`superb/wav2vec2-base-superb-er`); fallback derives V/A/D from
  RMS + zero-crossing rate. Label space + `_EMOTION_VAD` anchors match
  `server/pipeline/emotion.py`. Accessors: `is_loaded`, `using_fallback`.

### `edge/speaker/encoder.py` — `SpeakerEncoder`

- `encode(samples, sample_rate=16000) → list[float]` (L2-normalized, `embedding_dim=192`
  ECAPA-TDNN default). Lazy-loads `speechbrain/spkrec-ecapa-voxceleb`; fallback is a
  deterministic spectral/statistical hash embedding. Module-level `cosine_similarity(a, b)`
  supports same-vs-different-speaker continuity checks.

### `edge/planner/` — perceived-latency control

- **`short_turn.py`**: `ShortTurnClassifier.classify(...) → ShortTurnResult` with
  `TurnClass` enum; detects trivial/short/emotional/uncertain turns and attaches route
  confidence.
- **`speculation.py`**: `SpeculationController` — `decide(result: ShortTurnResult) →
  SpeculativePlan`, `start/cancel/commit`, `reconcile(final_route: RouteDecision)`,
  `reset()`. `SpeculativePlan` (`SpeculationMode`, `is_active`, `is_safe`, `to_dict`) and
  `SpeculationMetrics` (`wrong_rate`). Speculation is always safe to cancel.
- **`handoff.py`**: `HandoffController` — `begin_filler(text)`, `handoff_to_main(main_text,
  filler_done=True)`, `suppress_filler(...)`, `complete()`, `reset()`. Emits
  `HandoffAction` (`HandoffKind`: `start_filler, suppress_filler_start, crossfade,
  stop_filler, play_main, suppress_main, noop`). Dedupes a leading filler copy from the main
  output so the user never hears a double response. `OnsetState` machine:
  `idle → filler_playing → handing_off → main_playing → done`.

---

## 2. Speech subsystem — `speech/`

### `speech/codec/mimi_bridge.py` — `MimiCodecBridge` (CodecBridge)

- `encode(frames: Iterable[AudioFrame]) → Iterator[CodecChunk]`,
  `decode(chunks: Iterable[CodecChunk]) → Iterator[AudioFrame]`,
  `roundtrip(frames) → list[AudioFrame]`, `roundtrip_error(frames) → float`.
- Accessors: `backend_name`, `is_real_backend`. Backends: `MimiBackend` (loads weights,
  `pragma: no cover`) or `MockCodecBackend` (deterministic quantize/dequantize fallback).
- Factory: `make_codec_bridge(**kwargs) → MimiCodecBridge`.
- **Inputs → outputs:** `AudioFrame` PCM ↔ `CodecChunk` tokens, intelligible roundtrip on
  the mock backend.

### `speech/codec/token_stream.py` — `TokenStream`

- Async token-stream contract with backpressure + cancellation. `put(chunk)`,
  `put_many(chunks)`, `close()`, `get() → TokenPacket | None`, async iteration
  (`__aiter__`), `cancel(reason)`, `stats()`; properties `cancelled`, `closed`, `qsize`.
- **`TokenPacket`** wraps a `CodecChunk` exposing `seq`, `is_final`, `ts_ms`. Exceptions:
  `StreamCancelled`, `SequenceError`. Helper `drain_to_list(stream) → list[TokenPacket]`.

### `speech/moshi_runtime/service.py` — `MoshiRuntimeService` (SpeechRuntime)

- `async stream_reply(session_id, chunks: AsyncIterator[CodecChunk]) →
  AsyncIterator[CodecChunk]`; `async cancel(session_id, turn_id)`.
- `set_persona(session_id, persona: PersonaState)`, `session_context(session_id) → dict`,
  `stats()`; accessors `backend_name`, `is_real_backend`. Backends: `MoshiBackend`
  (weights) or `EchoTransformBackend` (CPU fallback that transforms tokens deterministically).
- Factory: `make_runtime(**kwargs) → MoshiRuntimeService`.
- **Inputs → outputs:** stream of user `CodecChunk`s + session/persona state → incremental
  reply `CodecChunk`s with clean cancellation.

### `speech/moshi_runtime/session_runtime.py` — continuity state

- **`SessionStore`** — `get_or_create(session_id, persona=None) → SessionState`, `get`,
  `drop`, `observe_input/observe_output(session_id, chunk)`, `stats()`. L1 continuity cache
  (durable tiers live in `memory/`).
- **`SessionState`** — `persona`, bounded `history: deque[TurnRecord]`, `emotion_window`,
  `active_turn_id`; methods `push_emotion`, `recent_emotion() → EmotionState` (smoothed),
  `begin_turn`, `end_turn`, `context_digest() → dict`.
- **`TurnRecord`** — `turn_id, n_in_chunks, n_out_chunks, started_ms, ended_ms, cancelled,
  emotion`; `duration_ms()`.

### `speech/moshi_runtime/repair.py`

Cancel / rollback / restart / interruption-aware continuation hooks for the runtime
(Phase 6C repair path).

### `speech/decoder/service.py` — `DecoderService`

- `decode_request(request: DecoderRequest) → AudioFrame`,
  `decode_all(chunks) → list[AudioFrame]`,
  `async stream_decode(...)`, `interrupt(pending_pcm=None, policy: StopPolicy=None)`,
  `stats()`; property `sample_rate`. Has an internal `_LRUCache` for decoded chunks and a
  quantization policy (`_apply_quant`). `DecoderRequest` carries `turn_id, codec_tokens,
  persona_state, emotion_state`. Factory `make_decoder(**kwargs)`.
- **Inputs → outputs:** `CodecChunk`/`DecoderRequest` tokens → streamed `AudioFrame` PCM
  with fast first chunk and clean interruption.

### `speech/decoder/waveform.py` / `speech/decoder/interruption.py`

Waveform reconstruction (chunk-boundary smoothing / crossfade) and playback interruption
control (stop within budget, fade or hard-cut by policy).

### `speech/persona/controller.py` — `PersonaController`

- `fuse_style(...)`, `shape(...)`, `conditioning(persona: PersonaState, dim=…) → FiLMParams`,
  `preserves_identity(a, b) → bool`, property `style_embedding`. Uses FiLM-style
  conditioning (`film_conditioning(emotion, dim)`) and a `StyleEmbeddingProvider`
  (`HashStyleEmbeddingProvider` fallback). Output varies emotion while preserving identity.
- Related: `speech/persona/emotion_schema.py` (emotion latent schema, Phase 9A),
  `speech/persona/relationship.py` (relationship memory, Phase 9C).

---

## 3. Auxiliary subsystem — `aux/`

### `aux/text_brain/` — auxiliary text reasoning

- **`contracts.py`**: `TextBrainTask` (enum: `memory_summary, tool_plan,
  moderation_summary, rag_query, transcript_cleanup, dataset_label`), `TextBrainRequest`
  (`task, payload, session_id, timeout_s, max_tokens, temperature`), `TextBrainResponse`
  (`ok, degraded, text, summary, tool_calls, rag_queries, labels, model, latency_ms, …`),
  `ToolSpec`/`ToolParam`/`ToolCall`, and `DEFAULT_TOOLS`.
- **`service.py`**: `TextBrainService.run(request: TextBrainRequest) → TextBrainResponse`
  (async), `tools`, `close()`. Calls Ollama (Qwen3/Llama 3.3) when available, else
  `StubTextBrain` produces a `degraded=True` deterministic response. Helper `run_task(...)`.
- **Inputs → outputs:** a typed task + payload → a deterministic-enough structured response;
  never blocks the voice loop.

### `aux/stt/transcript_service.py` — `TranscriptService`

- `async transcribe(...) → TranscriptResult`, `async submit(...) → job_id`,
  `result(job_id, timeout=None)`, `drain(timeout=None)`, `pending()`, async context manager.
  Backends: `FasterWhisperTranscriber` (lazy) or `StubTranscriber` fallback; `make_backend(
  prefer_whisper=True, …)`. `TranscriptResult.to_dict()`; jobs run on background workers so
  transcripts do not block the main loop.

### `aux/fallback/orchestrator.py` — `FailoverOrchestrator`

- `decide(health: PrimaryHealth) → shared.contracts.FallbackDecision`,
  `user_message(decision=None) → str`, `stats()`; properties `in_fallback`, `last_reason`.
- **`FailoverPolicy`** thresholds (`max_latency_ms=1200`, `max_error_rate=0.25`,
  `max_consecutive_failures=3`, `recovery_probes_required=2`, …). **`PrimaryHealth`**
  snapshot (`available, latency_ms, error_rate, consecutive_failures, manual_override`).
  **`FailoverReason`** enum drives `USER_MESSAGES`. Applies hysteresis so it does not flap.

---

## 4. Memory subsystem — `memory/`

### `memory/store.py` — `MemoryStore` (facade)

- `write(write: MemoryWrite, text=None) → MemoryRecord` (fan-out by kind to tiers),
  `read(query: MemoryReadQuery, policy=None, tiers=None) → MemoryReadResult` (merge across
  tiers, dedupe by id, keep best score, cap at `top_k`, attach `latency_ms`),
  `healthcheck() → dict[str, bool]`, `clear(session_id=None)`.
- Wires `HotCache` (Redis), `ProfileStore` (Postgres), `SemanticMemory` (Qdrant); each
  lazy-connects with an in-memory fallback so the store runs with no services up.

### `memory/contracts.py` — memory-internal helpers

- Re-exports canonical `MemoryKind/MemoryWrite/MemoryReadQuery/MemoryReadResult`.
- **`MemoryTier`** enum (`hot, profile, semantic`). **`MemoryRecord`** (`from_write`,
  `as_item(score=None)`). **`ScoredMemory`** (record + score). **`WritePolicy`**
  (`tiers_for(kind)`) and **`RetrievalPolicy`** (`max_top_k, min_score,
  recency_half_life_ms, deadline_ms`, `effective_top_k(requested)`).
- Defaults: `DEFAULT_WRITE_POLICY` (turn_summary→hot+semantic, preference→hot+profile,
  profile→profile, tool_result→hot), `DEFAULT_RETRIEVAL_POLICY`. **`MemoryBackend`**
  Protocol (`write/read/healthcheck`).
- Tier modules: `memory/redis/hot_cache.py` (`HotCache`), `memory/postgres/profile_store.py`
  (`ProfileStore`), `memory/qdrant/semantic_memory.py` (`SemanticMemory`),
  `memory/summarizer/pipeline.py`, `memory/tool_router/` (`router.py`, `contracts.py`).

---

## 5. Safety subsystem — `safety/`

### `safety/moderation/gate.py` — `ModerationGate`

- `evaluate(text, path, session_id=None) → ModerationOutcome`,
  `moderate_text(text, session_id=None) → shared.contracts.ModerationDecision`,
  `moderate_speech(transcript, session_id=None) → ModerationDecision`. Fail-closed
  (`_fail_closed`) when the classifier errors. Module-level helpers `moderate_text(...)`,
  `moderate_speech(...)`. `_LexiconClassifier` is the default `TextClassifier`.

### `safety/voice_policy/policy.py` — `VoicePolicy`

- `evaluate(request: VoiceRequest) → VoicePolicyDecision`,
  `register_protected_voice(voice_ref_id)`. Consent-first: non-default voices require an
  active consent record. **`ConsentStore`** (`record_consent`, `revoke_consent`,
  `find_active`, `is_retained`, `consent_log`) and a `SpoofDetector`
  (`spoof_probability(voice_ref_id) → float`).

### `safety/watermark/audioseal.py` — `Watermarker`

- `embed(samples, sample_rate) → WatermarkedAudio`, `verify(...) → WatermarkResult`,
  `protect(...)`, `assert_compliant(result)` (raises `WatermarkComplianceError`); property
  `backend_name`. Backends: real `WatermarkBackend` or `DeterministicFallbackBackend`. Ops
  helpers `ops_status(...)` and a `main(argv)` CLI entry. `safety/contracts.py` defines
  `AuditLog`, `RiskCategory`, `ModerationOutcome`, `ConsentRecord`, `VoicePolicyDecision`,
  `WatermarkMarker/WatermarkedAudio/WatermarkResult` plus HMAC signing helpers.

---

## 6. Infra subsystem — `infra/`

### `infra/scaling/scheduler.py` — `SessionScheduler`

- `admit(session_id) → AdmissionResult`, `release(session_id) → str | None`,
  `worker_for(session_id)`, `is_active`, `is_queued`, `snapshot()`; properties
  `pool_capacity`, `active_count`, `queue_depth`, `max_queue_depth`, `worker_ids`,
  `is_saturated`. `AdmissionResult.accepted`, `AdmissionStatus`, `BackpressurePolicy`,
  `WorkerState` (`load`, `capacity`, `has_room`, `utilization`). Sticky-session worker
  assignment with backpressure + bounded queue. Also `infra/scaling/envelopes.py`
  (GPU/resource envelopes).

### `infra/deploy/regions.py` — `RegionRouter`

- `route(user: GeoPoint, preferred_region=None) → RegionRoute`, `set_health(name, healthy)`,
  `region(name)`, `region_names()`. `Region` (`estimated_latency_ms`, `is_eligible`),
  `WarmPool` (`available_warm`, `has_capacity`, `is_warm_ready`), `GeoPoint.distance_km`,
  `RouteOutcome`. Factory `default_india_first_topology() → RegionRouter`.

### `infra/deploy/rollback.py` — `RollbackEvaluator`

- `evaluate(metrics: dict[str, float], samples=None) → RollbackDecision` →
  `RollbackAction` (`rollback, hold, promote`). `ReleasePolicy.from_dict(...)` parses the
  §16C `release_policy.yaml` shape; `RollbackThreshold.is_breached(observed)`;
  `Comparison` (`greater_than, less_than`); `load_release_policy(path)`. Maps onto the
  server metrics (`soulyatri_pipeline_e2e_latency_seconds`, `soulyatri_errors_total`).
- Monitoring: `infra/monitoring/prometheus.py`, `prometheus.yml`, `alerts.rules.yml`;
  `infra/obs.py` provides `get_logger` + `telemetry`.

---

## 7. Evaluation subsystem — `evals/`

### `evals/replay/harness.py` — `ReplayHarness`

- `run_turn(turn, scenario) → TurnResult`, `run_scenario(scenario) → ScenarioResult`,
  `run(scenarios=None) → ReplayReport`. `Scenario`/`ScenarioTurn` (`from_dict`),
  `PipelineFn` Protocol, `ReplayReport` (`route_accuracy`, `intent_accuracy`, `to_dict`,
  `to_json`), `load_scenario(path)`, `load_scenarios(directory=None)`. Scenario fixtures
  live in `evals/replay/scenarios/*.json` (English, Hindi, Hinglish code-switch,
  interruption/barge-in, distress).

### `evals/latency/metrics.py` — `MetricsCollector`

- `record(name, value)`, `record_timing(name, ms)`, `record_rate_event(name, hit)`,
  `distribution(name) → Distribution`, `snapshot()`, `mean`, `count`, `values`.
  `MetricSpec` registry (`METRIC_REGISTRY`, `metric_names()`); canonical names list
  `METRICS = [time_to_first_audible_ms, turn_end_detection_delay_ms,
  interruption_recovery_ms, filler_hit_rate, filler_false_positive_rate]` plus
  `STAGE_LATENCY_METRICS` (`stage_vad_ms … stage_decoder_ms`) and quality specs (`wer`,
  `emotion_agreement`, `code_switch_score`, `naturalness_proxy`). `percentile(values, q)`.
- `evals/text_metrics.py` and `evals/observability.py` provide text quality helpers and
  structured observability.

---

## 8. Server gateway + baseline — `server/`

The classic baseline / fallback path and WebRTC/WebSocket gateway (DECISIONS.md D-003).
See [api_protocol_reference.md](api_protocol_reference.md) and
[configuration_reference.md](configuration_reference.md) for the API and settings.

### `server/agent.py` — `VoiceAgent`

- `async initialize()` / `async shutdown()`; callback setters `set_audio_callback`,
  `set_transcript_callback`, `set_turn_metadata_callback`; `async handle_audio_frame(
  session_id, audio_bytes, sample_rate)`, `async handle_session_end(session_id)`. Internal
  `_quick_vad_check` and `_process_speech_segment` run VAD → STT → LLM → TTS, drive a
  per-session `TurnStateMachine`, route fillers, and extract emotion + speaker features.

### `server/pipeline/` — classic stages

| Module | Key types | Role |
|---|---|---|
| `vad.py` | `SileroVAD`, `VADConfig`, `SpeechSegment` | Speech start/end gating. |
| `stt.py` | `WhisperSTT`, `TranscriptionResult` | faster-whisper transcription. |
| `llm.py` | `OllamaLLM`, `LLMResponse`, `SOULYATRI_SYSTEM_PROMPT` | Text reasoning via Ollama. |
| `tts.py` | `EdgeTTS`, `TTSResult` | edge-tts synthesis (Hindi + English voices). |
| `session.py` | `SessionManager`, `SessionState`, `ConversationTurn` | Session + history. |
| `turn_state.py` | `TurnStateMachine`, `TurnState`, `TurnEvent` | Baseline state machine (superset-aligned with `edge/`). |
| `filler.py` | `FillerPhraseBank`, `FillerRouter`, `FillerPhrase`, `RoutingDecision` | Cached filler routing (`classify(...)`). |
| `features.py` | `FeatureExtractor`, `TurnMetadata` | Parallel feature extraction. |
| `emotion.py` | `EmotionExtractor`, V/A/D mapping | Baseline emotion features. |
| `speaker.py` | `SpeakerEncoder`, `SpeakerEmbedding` | Speaker tracking. |
| `barge_in.py` | `BargeInDetector`, `BargeInEvent` | Baseline barge-in. |

### `server/utils/`

- `audio.py`: `pcm_to_float32`, `float32_to_pcm16`, `resample`, WAV helpers; constants
  `SAMPLE_RATE_16K=16000`, `SAMPLE_RATE_24K=24000`, `SAMPLE_RATE_48K=48000`,
  `CHANNELS_MONO`, `SAMPLE_WIDTH_16BIT`.
- `metrics.py`: Prometheus metrics with the `soulyatri_` prefix (e.g.
  `soulyatri_pipeline_e2e_latency_seconds`, `soulyatri_errors_total`,
  `soulyatri_active_sessions`, `soulyatri_filler_hit_rate_total`).
- `logging_config.py`: `setup_logging()`, `get_logger(name)` (structlog).
