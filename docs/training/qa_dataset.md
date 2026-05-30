# Training Corpus — Human-Readable Mirror

> Human-readable mirror of [`qa_dataset.jsonl`](qa_dataset.jsonl), generated from the canonical JSONL. The JSONL is the machine-consumable artifact; this file is for reading and review. Records are grouped by their primary tag. Schema: see [schema.md](schema.md).

Total records: **58**.

## architecture

### Q1. What is the core SoulYatri runtime?

SoulYatri is a speech-native voice AI whose frozen runtime loop is Audio -> Mimi codec tokens -> Moshi speech-native runtime -> codec tokens -> Audio. It preserves pauses, intonation, laughter, and turn-taking instead of flattening speech to text. A classic STT->LLM->TTS path exists only as a fallback, observability, tooling, or bring-up baseline.

- **Source:** `docs/code/architecture_overview.md`, `docs/DECISIONS.md`
- **Tags:** architecture, runtime, speech-native

### Q2. Is SoulYatri a text chatbot that speaks?

No. Per DECISIONS.md D-001 and D-002, SoulYatri is a speech-native, full-duplex, emotional Hindi+English+Hinglish voice AI. The speech-native loop is the product, not a text chatbot with TTS bolted on.

- **Source:** `docs/DECISIONS.md`, `docs/code/architecture_overview.md`
- **Tags:** architecture, product, speech-native

### Q3. What is the domain-folder map of the repository?

Per final_use.md section 4 and DECISIONS.md D-003, the repo root is the soulyatri root with domain folders alongside server/ and client/: edge/ (turn detection, emotion, speaker, barge-in, planner, session), speech/ (codec, moshi_runtime, decoder, persona), aux/ (text_brain, stt, fallback), memory/ (redis, postgres, qdrant, summarizer, tool_router), safety/ (moderation, voice_policy, watermark), infra/ (scaling, deploy, monitoring), evals/ (replay, latency, audio, hinglish, emotion), training/, shared/, docs/, scripts/, tests/, runs/.

- **Source:** `docs/code/architecture_overview.md`, `docs/DECISIONS.md`
- **Tags:** architecture, repo, folders

## setup

### Q4. How do I start the SoulYatri Python server?

From the repo root, create and activate a venv, install server requirements, then run the module: python -m server.main. That launches uvicorn on settings.server_host:settings.server_port (default 0.0.0.0:8000) with the FastAPI app server.main:app. Copy .env.example to .env first to configure it.

- **Source:** `README.md`, `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** setup, server, quickstart

### Q5. What is the quick-start sequence to run SoulYatri end to end?

1) cp .env.example .env and edit it. 2) ollama pull qwen3:8b. 3) docker-compose up -d for infrastructure. 4) Create a venv, pip install -r server/requirements.txt, run python -m server.main. 5) cd client, npm install, npm run dev. 6) Open http://localhost:3000 and talk.

- **Source:** `README.md`
- **Tags:** setup, quickstart, client, server

## api

### Q6. What HTTP endpoints does the server expose?

server/main.py exposes GET /health (returns {status, version, phase}), GET /metrics (Prometheus text exposition with soulyatri_ prefixed metrics), GET /api/token (LiveKit room-join JWT), and the WebSocket WS /ws/audio/{session_id} for real-time audio.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** api, endpoints, http

### Q7. What does GET /health return?

It returns the JSON object {"status": "healthy", "version": "0.1.0", "phase": 2} from the health_check handler in server/main.py.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** api, health

## livekit

### Q8. How does the LiveKit token flow work?

The client calls GET /api/token?room=&identity=. The server builds a JWT with livekit.api.AccessToken(api_key, api_secret).with_identity(identity).with_grants(VideoGrants(room_join=True, room)).to_jwt() and returns {token, url, room, identity}, where url is settings.livekit.url. If livekit-api is not installed it returns a dummy 'dev-token'. The client then connects to LiveKit with that url and token.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** livekit, token, api, transport

### Q9. What are the default room and identity for /api/token?

The /api/token handler defaults room to 'soulyatri-room' and identity to 'user' when the query parameters are not supplied.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** livekit, token, api, defaults

## websocket

### Q10. Describe the WebSocket audio handshake.

Connect to WS /ws/audio/{session_id}. The server accepts the socket and registers audio, transcript, and turn-metadata callbacks. The client sends binary frames of raw 16-bit PCM mono at 16 kHz, and may send JSON text control frames {"type":"config","sample_rate":16000} or {"type":"end"}. The server sends back binary 16-bit PCM at 24 kHz plus JSON text frames of type audio_meta, transcript, and turn_metadata.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`, `server/utils/audio.py`
- **Tags:** websocket, audio, protocol, handshake

### Q11. What sample rates does the audio WebSocket use?

Client-to-server audio is raw 16-bit PCM mono at 16 kHz (SAMPLE_RATE_16K), and server-to-client audio is raw 16-bit PCM mono at 24 kHz. These constants live in server/utils/audio.py (SAMPLE_RATE_16K=16000, SAMPLE_RATE_24K=24000, SAMPLE_RATE_48K=48000).

- **Source:** `server/main.py`, `server/utils/audio.py`, `docs/code/api_protocol_reference.md`
- **Tags:** websocket, audio, sample-rate

### Q12. What control messages can the audio WebSocket client send?

Text JSON control frames: {"type":"config","sample_rate":16000} updates the server's client_sample_rate for later binary frames, and {"type":"end"} signals the client is done and breaks the receive loop. Invalid control JSON is logged as ws_invalid_control and ignored.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** websocket, protocol, control

### Q13. What JSON event types does the server send over the audio WebSocket?

The server sends audio_meta (sample_rate, size, metadata alongside each binary audio chunk), transcript (role, text, timestamp), and turn_metadata (per-turn feature metadata). Binary frames carry the 24 kHz PCM audio itself.

- **Source:** `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** websocket, events, protocol

## turn-state

### Q14. What is the turn-state machine and what states does it have?

TurnState is the canonical conversational state enum used across the project: idle, listening, buffering, candidate_filler, forwarding, thinking, speaking, barge_in, repairing, ended. edge/session/turn_state.py implements an explicit, auditable TurnStateMachine over these states, aligned with shared/contracts.py and the baseline server/pipeline/turn_state.py.

- **Source:** `shared/contracts.py`, `edge/session/turn_state.py`, `docs/code/module_reference.md`, `docs/INTERFACES.md`
- **Tags:** turn-state, edge, state-machine

### Q15. How does the TurnStateMachine reject invalid transitions?

TurnStateMachine.transition() raises InvalidTransitionError on an illegal move, while try_transition() returns a TurnEvent on success or a TransitionRejected (with to_dict()) without raising. can_transition(to_state) checks legality up front, and every transition emits an auditable TurnEvent.

- **Source:** `edge/session/turn_state.py`, `docs/code/module_reference.md`
- **Tags:** turn-state, edge, transitions

### Q16. What semantic helper methods does the edge TurnStateMachine provide?

It exposes intent-named helpers that each return TurnEvent or TransitionRejected: on_speech_start, on_speech_end, on_turn_confirmed, on_filler_handled, on_pipeline_needed, on_pipeline_start, on_response_ready, on_speaking_done, on_barge_in, on_repair_start, on_repair_done, and on_session_end, plus reset().

- **Source:** `edge/session/turn_state.py`, `docs/code/module_reference.md`
- **Tags:** turn-state, edge, api

## filler

### Q17. How does the filler subsystem work and what is its rule?

The filler subsystem masks latency with cached phrases and is mandatory but must stay simple, safe, bounded, and disableable (DECISIONS.md D-006). In the baseline, server/pipeline/filler.py provides FillerPhraseBank and FillerRouter.classify(...) returning a RoutingDecision. The router decides cached_filler vs full_stack vs silent_wait (RouteTarget/RouteDecision in shared/contracts.py). It must never silently take over non-trivial reasoning.

- **Source:** `docs/DECISIONS.md`, `server/pipeline/filler.py`, `shared/contracts.py`, `docs/code/module_reference.md`
- **Tags:** filler, routing, latency

## fallback

### Q18. What is the classic fallback path and when is it used?

The classic baseline is VAD(Silero) -> STT(faster-whisper) -> LLM(Ollama Qwen3) -> TTS(edge-tts), orchestrated by server/agent.py VoiceAgent. aux/fallback/orchestrator.py FailoverOrchestrator.decide(PrimaryHealth) returns a FallbackDecision that routes to this baseline during incidents (primary unavailable, high latency, high error rate, or consecutive failures), with hysteresis so it does not flap. It may ship in degraded mode but never redefines the core architecture.

- **Source:** `server/agent.py`, `aux/fallback/orchestrator.py`, `shared/contracts.py`, `docs/code/architecture_overview.md`, `README.md`
- **Tags:** fallback, failover, baseline

### Q19. What thresholds drive the failover decision?

aux/fallback/orchestrator.py FailoverPolicy defaults to max_latency_ms=1200, max_error_rate=0.25, max_consecutive_failures=3, recovery_probes_required=2, and default_recovery_ms=5000. FailoverReason enumerates auditable reasons (primary_unavailable, high_latency, high_error_rate, consecutive_failures, manual_override, recovered).

- **Source:** `aux/fallback/orchestrator.py`, `docs/code/module_reference.md`
- **Tags:** fallback, failover, thresholds

## safety

### Q20. How does SoulYatri handle safety and consent for voice?

Safety is a first-class gate (DECISIONS.md D-007): no arbitrary public voice cloning. safety/moderation/gate.py ModerationGate.moderate_text/moderate_speech returns a ModerationDecision and fails closed on classifier errors. safety/voice_policy/policy.py VoicePolicy.evaluate(VoiceRequest) is consent-first (non-default voices need an active consent record via ConsentStore). safety/watermark/audioseal.py Watermarker embeds and verifies watermarks on generated audio.

- **Source:** `docs/DECISIONS.md`, `safety/moderation/gate.py`, `safety/voice_policy/policy.py`, `safety/watermark/audioseal.py`, `docs/code/module_reference.md`
- **Tags:** safety, consent, moderation, watermark

### Q21. What does the moderation gate do when its classifier errors?

safety/moderation/gate.py ModerationGate fails closed: when the classifier raises, _fail_closed produces a blocking/escalating ModerationOutcome rather than allowing the turn. This matches the MODERATION_FAIL_CLOSED=true default in .env.example.

- **Source:** `safety/moderation/gate.py`, `.env.example`, `docs/code/module_reference.md`
- **Tags:** safety, moderation, fail-closed

### Q22. How is generated audio watermarked and verified?

safety/watermark/audioseal.py Watermarker.embed(samples, sample_rate) inserts a watermark and verify(...) detects it, returning a WatermarkResult; assert_compliant raises WatermarkComplianceError if non-compliant. It uses a real WatermarkBackend or a DeterministicFallbackBackend, and ops_status/main provide ops tooling. WATERMARK_ENABLED and WATERMARK_DETECT_THRESHOLD are set in .env.example.

- **Source:** `safety/watermark/audioseal.py`, `.env.example`, `docs/code/module_reference.md`
- **Tags:** safety, watermark, audio

## memory

### Q23. What are the memory tiers in SoulYatri?

memory/contracts.py defines MemoryTier with three tiers: hot (Redis, recent turns, fast+bounded), profile (Postgres, durable user/session profile), and semantic (Qdrant, vector store for semantic recall). memory/store.py MemoryStore is the facade that fans writes out by kind and merges bounded reads across tiers.

- **Source:** `memory/contracts.py`, `memory/store.py`, `docs/code/module_reference.md`
- **Tags:** memory, tiers, storage

### Q24. How does MemoryStore route writes to tiers?

memory/store.py MemoryStore.write applies the WritePolicy from memory/contracts.py. DEFAULT_WRITE_POLICY routes turn_summary -> hot+semantic, preference -> hot+profile, profile -> profile, and tool_result -> hot. A failure in one tier is logged and does not break the others.

- **Source:** `memory/store.py`, `memory/contracts.py`, `docs/code/module_reference.md`
- **Tags:** memory, write-policy, tiers

### Q25. How are memory reads kept bounded?

memory/store.py MemoryStore.read merges reads across tiers, dedupes by record id keeping the best score, sorts by score, truncates to the effective top_k, and attaches latency_ms. RetrievalPolicy in memory/contracts.py caps top_k (max_top_k), drops weak items (min_score), decays by recency_half_life_ms, and enforces a deadline_ms budget.

- **Source:** `memory/store.py`, `memory/contracts.py`, `docs/code/module_reference.md`
- **Tags:** memory, retrieval, bounded

### Q26. Can the memory store run without Redis, Postgres, or Qdrant?

Yes. Each tier (HotCache, ProfileStore, SemanticMemory) lazy-connects and falls back to an in-memory store, so memory/store.py MemoryStore runs with no external services up. This follows the CPU/no-weights rule in DECISIONS.md D-008.

- **Source:** `memory/store.py`, `docs/DECISIONS.md`, `docs/code/module_reference.md`
- **Tags:** memory, fallback, cpu

## codec

### Q27. What is the CodecChunk and where is it used?

CodecChunk (shared/contracts.py) is the token-stream packet bridging audio and the speech-native runtime: turn_id, seq, codec_tokens (list[int]), ts_ms, is_final, sample_rate (default 24000). It is the output of the Mimi tokenizer and the input/output of Moshi. speech/codec/mimi_bridge.py produces/consumes it and speech/codec/token_stream.py streams it.

- **Source:** `shared/contracts.py`, `speech/codec/mimi_bridge.py`, `speech/codec/token_stream.py`, `docs/INTERFACES.md`, `docs/code/module_reference.md`
- **Tags:** codec, mimi, contracts

### Q28. How does the Mimi codec bridge behave without weights?

speech/codec/mimi_bridge.py MimiCodecBridge selects a MimiBackend if weights load, otherwise a MockCodecBackend that does deterministic quantize/dequantize so encode/decode roundtrip still works on CPU. It exposes encode(frames)->CodecChunks, decode(chunks)->AudioFrames, roundtrip(), roundtrip_error(), and backend_name/is_real_backend.

- **Source:** `speech/codec/mimi_bridge.py`, `docs/code/module_reference.md`, `docs/DECISIONS.md`
- **Tags:** codec, mimi, fallback

## moshi

### Q29. What is the Moshi runtime service interface?

speech/moshi_runtime/service.py MoshiRuntimeService implements the SpeechRuntime contract: async stream_reply(session_id, chunks: AsyncIterator[CodecChunk]) -> AsyncIterator[CodecChunk] and async cancel(session_id, turn_id). It consumes codec tokens plus context state (not text), streams output incrementally, and supports clean cancellation. Without weights it uses an EchoTransformBackend CPU fallback.

- **Source:** `speech/moshi_runtime/service.py`, `docs/INTERFACES.md`, `docs/code/module_reference.md`
- **Tags:** moshi, runtime, speech-native

### Q30. How does the runtime preserve continuity across turns?

speech/moshi_runtime/session_runtime.py SessionStore/SessionState keep per-session continuity: a bounded history of TurnRecords, the active PersonaState, and a recent emotion window. recent_emotion() returns a smoothed EmotionState, and context_digest() gives a compact carryover view for the backend. Durable tiers live in memory/; this is the L1 continuity cache.

- **Source:** `speech/moshi_runtime/session_runtime.py`, `docs/code/module_reference.md`
- **Tags:** moshi, continuity, session

## decoder

### Q31. What does the fast acoustic decoder do?

speech/decoder/service.py DecoderService turns codec tokens into PCM. decode_request(DecoderRequest)->AudioFrame, decode_all(chunks), async stream_decode(...), and interrupt(pending_pcm, policy) for clean barge-in stops. It uses an internal LRU cache and a quantization policy so the first chunk arrives quickly and the decoder is not a bottleneck.

- **Source:** `speech/decoder/service.py`, `docs/code/module_reference.md`
- **Tags:** decoder, speech, playback

## emotion

### Q32. How is emotion represented in SoulYatri?

EmotionState (shared/contracts.py) is a continuous latent, not a one-word tag: valence/arousal/dominance in [-1,1] plus warmth/uncertainty/pace/intensity in [0,1], with optional label and confidence. edge/emotion/extractor.py EmotionExtractor.extract(samples) produces it, lazy-loading a wav2vec2 SER model or falling back to RMS + zero-crossing-rate features.

- **Source:** `shared/contracts.py`, `edge/emotion/extractor.py`, `docs/INTERFACES.md`, `docs/code/module_reference.md`
- **Tags:** emotion, persona, contracts

## persona

### Q33. How does the persona controller preserve identity while varying emotion?

speech/persona/controller.py PersonaController uses FiLM-style conditioning (film_conditioning + a StyleEmbeddingProvider) to shape output. conditioning(persona)->FiLMParams attaches affect to a turn, and preserves_identity(a, b) checks that the same persona identity is maintained while emotion varies.

- **Source:** `speech/persona/controller.py`, `docs/code/module_reference.md`
- **Tags:** persona, emotion, identity

## barge-in

### Q34. What does the barge-in detector do?

edge/barge_in/detector.py BargeInDetector detects the user speaking over the agent. Call set_agent_speaking(True) when playback starts, then check(session_id, speech_probability) per VAD frame; it returns a BargeInEvent (with cancel and repair flags) only after sustained speech is confirmed. False positives are bounded by consecutive-frame debounce, hysteresis decay, and a cooldown window, tracked in BargeInMetrics.

- **Source:** `edge/barge_in/detector.py`, `docs/code/module_reference.md`
- **Tags:** barge-in, edge, interruption

## planner

### Q35. How does the planner reduce perceived latency safely?

edge/planner uses short_turn.py ShortTurnClassifier to flag trivial/short/emotional turns, speculation.py SpeculationController to start a safe, cancellable onset (decide->SpeculativePlan, reconcile against the final RouteDecision), and handoff.py HandoffController to hand off from filler to the real output while de-duplicating any repeated leading content so the user never hears a double response.

- **Source:** `edge/planner/short_turn.py`, `edge/planner/speculation.py`, `edge/planner/handoff.py`, `docs/code/module_reference.md`
- **Tags:** planner, speculation, latency

## aux

### Q36. What is the auxiliary text brain for?

aux/text_brain is auxiliary, never the primary runtime. TextBrainService.run(TextBrainRequest)->TextBrainResponse handles tasks like memory_summary, tool_plan, moderation_summary, rag_query, transcript_cleanup, and dataset_label. It calls Ollama (Qwen3/Llama 3.3) when available, else a StubTextBrain returns a degraded deterministic response so the voice loop is never blocked.

- **Source:** `aux/text_brain/service.py`, `aux/text_brain/contracts.py`, `docs/code/module_reference.md`
- **Tags:** aux, text-brain, reasoning

### Q37. How are transcripts generated without blocking the voice loop?

aux/stt/transcript_service.py TranscriptService runs transcription on background workers: submit(...) returns a job id, result(job_id) awaits it, and transcribe(...) does a one-shot. Backends are FasterWhisperTranscriber (lazy) or a StubTranscriber fallback, so transcripts are asynchronous and do not block the main loop.

- **Source:** `aux/stt/transcript_service.py`, `docs/code/module_reference.md`
- **Tags:** aux, stt, async

## configuration

### Q38. What settings groups exist in server/config.py?

server/config.py defines a root Settings (server_host, server_port, log_level, log_format) plus nested BaseSettings: LiveKitSettings (LIVEKIT_), OllamaSettings (OLLAMA_), WhisperSettings (WHISPER_), TTSSettings (TTS_), SessionSettings (SESSION_), EmotionSettings (EMOTION_), SpeakerSettings (SPEAKER_), FillerSettings (FILLER_), and BargeInSettings (BARGE_IN_). The singleton is settings = Settings().

- **Source:** `server/config.py`, `docs/code/configuration_reference.md`
- **Tags:** configuration, settings, env

### Q39. What is the default LLM model and how is it configured?

OllamaSettings (prefix OLLAMA_) defaults base_url to http://localhost:11434 and model to qwen3:8b. Override with OLLAMA_BASE_URL and OLLAMA_MODEL in .env. README.md instructs ollama pull qwen3:8b before running.

- **Source:** `server/config.py`, `.env.example`, `README.md`, `docs/code/configuration_reference.md`
- **Tags:** configuration, ollama, llm

### Q40. How is the whisper STT configured?

WhisperSettings (prefix WHISPER_) defaults model_size=small, device=cuda, compute_type=float16. Override with WHISPER_MODEL_SIZE (tiny/base/small/medium/large-v3), WHISPER_DEVICE (cuda or cpu), and WHISPER_COMPUTE_TYPE (float16/int8/int8_float16) in .env.

- **Source:** `server/config.py`, `.env.example`, `docs/code/configuration_reference.md`
- **Tags:** configuration, whisper, stt

### Q41. What TTS voices does SoulYatri use by default?

TTSSettings (prefix TTS_) defaults voice_hindi=hi-IN-SwaraNeural and voice_english=en-IN-NeerjaNeural (edge-tts neural voices). Other documented options include hi-IN-MadhurNeural and en-IN-PrabhatNeural.

- **Source:** `server/config.py`, `.env.example`, `docs/code/configuration_reference.md`
- **Tags:** configuration, tts, voices

### Q42. What are the barge-in detection settings?

BargeInSettings (prefix BARGE_IN_) defaults enabled=True, threshold=0.5, min_speech_duration_ms=200, and cooldown_ms=500. These bound when a barge-in is confirmed and how soon another can fire.

- **Source:** `server/config.py`, `docs/code/configuration_reference.md`
- **Tags:** configuration, barge-in, settings

## contracts

### Q43. What is the shared contract surface and why does it exist?

shared/contracts.py is the importable realization of docs/INTERFACES.md and the single source of truth for cross-subsystem types. It uses pydantic v2 models and stdlib enums only (no torch/GPU imports) so it loads on CPU. Every domain folder depends on these types rather than redefining incompatible local ones.

- **Source:** `shared/contracts.py`, `docs/INTERFACES.md`, `docs/code/architecture_overview.md`
- **Tags:** contracts, shared, interfaces

### Q44. Which types are exported from shared/contracts.py?

Its __all__ exports now_ms, AudioFrame, CodecChunk, TurnState, TurnEvent, EmotionState, PersonaState, RouteTarget, RouteDecision, FallbackDecision, MemoryKind, MemoryWrite, MemoryReadQuery, MemoryReadResult, VoiceAction, VoiceRequest, and ModerationDecision.

- **Source:** `shared/contracts.py`, `docs/code/module_reference.md`
- **Tags:** contracts, shared, types

## server

### Q45. What is the role of the existing server/ folder?

Per DECISIONS.md D-003, server/ is kept intact as the WebRTC/WebSocket gateway (server/main.py), the classic baseline/fallback path (server/agent.py VoiceAgent + server/pipeline/*), and the reference implementation for turn-state, emotion, speaker, filler, and barge-in semantics that the new edge/ and speech/ folders stay consistent with.

- **Source:** `docs/DECISIONS.md`, `server/main.py`, `server/agent.py`, `docs/code/architecture_overview.md`
- **Tags:** server, gateway, baseline

## infra

### Q46. How does the infra session scheduler handle load?

infra/scaling/scheduler.py SessionScheduler.admit(session_id) returns an AdmissionResult (accepted or queued/rejected), release(session_id) frees a slot and can promote a queued session, and worker_for(session_id) gives sticky assignment. It exposes pool_capacity, active_count, queue_depth, is_saturated, and snapshot(), applying a BackpressurePolicy with a bounded queue.

- **Source:** `infra/scaling/scheduler.py`, `docs/code/module_reference.md`
- **Tags:** infra, scaling, backpressure

### Q47. How does the canary rollback evaluator decide to roll back?

infra/deploy/rollback.py RollbackEvaluator.evaluate(metrics, samples) returns a RollbackDecision with action rollback, hold, or promote. Any breached RollbackThreshold (parsed from release_policy.yaml via ReleasePolicy.from_dict) forces rollback; otherwise too few samples means hold, and healthy with enough samples means promote. It maps onto server metrics like soulyatri_pipeline_e2e_latency_seconds and soulyatri_errors_total.

- **Source:** `infra/deploy/rollback.py`, `docs/code/module_reference.md`
- **Tags:** infra, rollback, canary

### Q48. How does region routing work?

infra/deploy/regions.py RegionRouter.route(user: GeoPoint, preferred_region) returns a RegionRoute, choosing an eligible Region by estimated latency and warm-pool readiness; set_health(name, healthy) toggles region health. default_india_first_topology() builds an India-first RegionRouter.

- **Source:** `infra/deploy/regions.py`, `docs/code/module_reference.md`
- **Tags:** infra, regions, routing

## evals

### Q49. What does the evals replay harness do?

evals/replay/harness.py ReplayHarness runs fixed Scenarios (loaded from evals/replay/scenarios/*.json covering English, Hindi, Hinglish code-switch, interruption/barge-in, and distress). run(scenarios)->ReplayReport reports route_accuracy and intent_accuracy so model/runtime changes can be replayed and compared.

- **Source:** `evals/replay/harness.py`, `docs/code/module_reference.md`
- **Tags:** evals, replay, regression

### Q50. What latency and quality metrics does evals track?

evals/latency/metrics.py defines MetricsCollector and a MetricSpec registry. Core metrics include time_to_first_audible_ms, first_token_ms, turn_end_detection_delay_ms, interruption_recovery_ms, filler_hit_rate, and filler_false_positive_rate, plus per-stage breakdowns (stage_vad_ms..stage_decoder_ms) and quality specs wer, emotion_agreement, code_switch_score, and naturalness_proxy.

- **Source:** `evals/latency/metrics.py`, `docs/code/module_reference.md`
- **Tags:** evals, latency, metrics

## metrics

### Q51. What Prometheus metrics does the server expose?

server/utils/metrics.py defines metrics under the soulyatri_ prefix, including soulyatri_vad_latency_seconds, soulyatri_stt_latency_seconds, soulyatri_llm_ttft_seconds, soulyatri_pipeline_e2e_latency_seconds, soulyatri_active_sessions, soulyatri_filler_hit_rate_total, soulyatri_barge_in_total, and soulyatri_errors_total. They are served at GET /metrics.

- **Source:** `server/utils/metrics.py`, `server/main.py`, `docs/code/api_protocol_reference.md`
- **Tags:** metrics, prometheus, observability

## cpu

### Q52. Why can the codebase run on a machine with no GPU or model weights?

DECISIONS.md D-008 requires all foundation code to import and run on CPU without weights. Heavy deps (torch, transformers, moshi, mimi) are not imported at module top level; speech-native components are interfaces plus graceful fallbacks (MockCodecBackend, EchoTransformBackend, deterministic emotion/speaker features, in-memory memory tiers).

- **Source:** `docs/DECISIONS.md`, `speech/codec/mimi_bridge.py`, `speech/moshi_runtime/service.py`, `docs/code/architecture_overview.md`
- **Tags:** cpu, fallback, environment

## models

### Q53. What is the frozen V1 model stack?

Per DECISIONS.md D-004: Opus (transport codec), Mimi (neural speech codec), Moshi (main speech-native runtime), CSM (speech-gen fallback/reference), Qwen3 or Llama 3.3 (aux text), faster-whisper or IndicConformer (aux STT), sherpa-onnx (client helper), Silero VAD, ECAPA-TDNN (speaker), wav2vec2-class SER (emotion), multilingual-e5 (memory vectorizer), Redis, Postgres, Qdrant, and AudioSeal (watermarking).

- **Source:** `docs/DECISIONS.md`
- **Tags:** models, stack, frozen

## process

### Q54. What is the definition of done for a SoulYatri task?

Per final_use.md section 3.3, a task is done only when all of these exist: code, tests, a short design note or README update, structured logging hooks, a benchmark/latency note if performance-sensitive, and an explicit acceptance result recorded under runs/ or docs/. Phase 17's acceptance is recorded in runs/phase-17-docs/acceptance.md.

- **Source:** `final_use.md`, `runs/phase-17-docs/acceptance.md`
- **Tags:** process, definition-of-done, governance

## training

### Q55. How do I validate the training JSONL corpus?

Run python scripts/validate_training_jsonl.py from the repo root. It parses docs/training/qa_dataset.jsonl line by line and asserts each line is valid standalone JSON with non-empty instruction and response strings and non-empty source and tags arrays. A non-zero exit code reports the failing line and reason.

- **Source:** `scripts/validate_training_jsonl.py`, `docs/training/schema.md`
- **Tags:** training, validation, jsonl

### Q56. What schema does each training record follow?

Each line of docs/training/qa_dataset.jsonl is one JSON object with keys instruction (string), response (string), source (array of real doc/code paths), and tags (array of topic strings), matching the final_use.md Phase 17 example.

- **Source:** `docs/training/schema.md`, `final_use.md`
- **Tags:** training, schema, jsonl

## governance

### Q57. Where do the governance and architecture decisions live?

Under docs/: DECISIONS.md (frozen decision log), INTERFACES.md (shared contracts source of truth), MODEL_LOCKS.md (pinned models), LATENCY_TARGETS.md, ASSUMPTIONS.md, RISKS.md, OPEN_QUESTIONS.md, and AGENT_PROTOCOL.md. docs/index.md links them all alongside the code and training knowledge base.

- **Source:** `docs/index.md`, `docs/DECISIONS.md`, `docs/INTERFACES.md`
- **Tags:** governance, docs, index

## routing

### Q58. What is the RouteDecision and who produces it?

RouteDecision (shared/contracts.py) is the output of the local/edge router and filler subsystem: route (RouteTarget: cached_filler, full_stack, silent_wait), phrase_id, intent, confidence, reason, and emit_filler_then_forward (latency sponge). The baseline equivalent is RoutingDecision from server/pipeline/filler.py.

- **Source:** `shared/contracts.py`, `server/pipeline/filler.py`, `docs/INTERFACES.md`, `docs/code/module_reference.md`
- **Tags:** routing, filler, contracts
