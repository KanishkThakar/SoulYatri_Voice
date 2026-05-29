# Requirements Document

## Introduction

This document specifies an **updated, Kiro-native build roadmap** for **SoulYatri**: a speech-native, low-latency, emotional, code-switched (Hindi / English / Hinglish) conversational voice AI built from open-source components only.

The deliverable of this spec is a **roadmap/planning artifact** — a single coherent, current, executable phased plan — not the execution of large model-training runs. The roadmap reconciles three sources of truth that currently disagree with each other:

1. **The code that already exists** in this workspace — a Phase 1 classic pipeline (`Audio → WebRTC → Silero VAD → faster-whisper STT → Ollama Qwen3/Llama 3.3 LLM → edge-tts TTS → Audio`) plus Phase 2 scaffolding (`server/pipeline/turn_state.py`, `filler.py`, `emotion.py`, `speaker.py`, `barge_in.py`, `features.py`).
2. **The scattered strategy PDFs** in `docs/` — the `SOULYATRI_MASTER_BIBLE` (a funded, multi-month, custom-model program: fork CSM-3B + Mimi + Moshi, custom codec, custom tokenizer, FiLM emotion control, DPO+GRPO alignment, kill-metrics vs ElevenLabs/Hume/Rumik/Sarvam), the `VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN` (explicitly **rejects** from-scratch training; targets a fast solo demo with LoRA SFT + DPO-lite and <300 ms practical latency), and the clean-room competitive teardown (benchmark stack: VoiceBench, EmergentTTS-Eval, Seed-TTS-eval, MUSHRA, Speech Arena).
3. **The current (2026) open-source model landscape** verified on the Hugging Face Hub, which now offers full-duplex / any-to-any speech-native models that can be **adopted directly**, materially de-risking the "build a backbone" phase that the PDFs worried about.

### Central tension the roadmap must resolve

The `MASTER_BIBLE` assumes a funded team building a custom model from forked weights, while the `VOX_OMEGA` plan rejects from-scratch work and targets a fast solo demo. This roadmap resolves the tension by defining a **single phased path with two named tracks** — a **LEAN track** (adopt an existing speech-native model, ship a demo fast) executed first, and an **optional AMBITIOUS track** (fork + fine-tune a custom codec / tokenizer / alignment for differentiation) gated behind explicit, measurable decision gates.

### Relationship to the existing `ai-training-docs` spec

The existing Kiro spec `.kiro/specs/ai-training-docs/` produces only a `docs/` folder of documentation and Q&A training data; it is **not** a build roadmap. This roadmap **references** that spec as the documentation/knowledge-base workstream and **does not duplicate** its content or re-specify documentation generation.

### Scope Summary

- **In scope:** Producing the phased build roadmap; defining model adoption/selection criteria and the evaluation harness used to choose; defining the Hinglish data engine, emotion/persona control, full-duplex/latency targets, the benchmark programme with launch gates, the LEAN-vs-AMBITIOUS track structure with decision gates, budget/compute awareness, safety/consent/watermarking guardrails, and open-source/licensing constraints.
- **Out of scope:** From-scratch foundation-model pretraining; executing large GPU training runs as part of this spec; re-specifying the `ai-training-docs` documentation workstream; production infrastructure procurement.

## Glossary

- **SoulYatri_Platform**: The overall conversational voice AI system being evolved, comprising the current pipeline code in `server/` and `client/` and its future speech-native form.
- **Roadmap**: The planning artifact produced by this spec — the phased plan, tracks, gates, criteria, and targets. This is the primary deliverable.
- **Phase_1_Pipeline**: The already-coded classic cascade (Silero VAD → faster-whisper → Ollama LLM → edge-tts) defined in `server/agent.py` and `server/pipeline/`.
- **Speech_Native_Core**: The adopted speech-in / speech-out (S2S) or full-duplex conversational model that becomes the SoulYatri_Platform's primary conversational brain, replacing the text bottleneck of the Phase_1_Pipeline.
- **Candidate_Model**: An open-source model considered for adoption as the Speech_Native_Core or as an auxiliary component. Verified 2026 candidates include: `kyutai/moshiko-pytorch-bf16` and `kyutai/moshika-pytorch-bf16` (Moshi, full-duplex), `Qwen/Qwen3-Omni-30B-A3B-Instruct` (any-to-any), `zai-org/glm-4-voice-9b`, `sesame/csm-1b`, `LiquidAI/LFM2.5-Audio-1.5B`, `stepfun-ai/Step-Audio-2-mini`, `openbmb/MiniCPM-o-4_5`, `CofeAI/FLM-Audio`, `tencent/Covo-Audio-Chat`, `OpenMOSS-Team/MOSS-Audio-4B-Instruct`, `gpt-omni/mini-omni2`.
- **Codec_Component**: The neural audio codec that tokenizes/de-tokenizes audio. Candidates: `kyutai/mimi`, `neuphonic/neucodec`, `HKUSTAudio/xcodec2`.
- **Indic_Stack**: Open-source models and datasets providing the Hindi/Hinglish moat. Candidates: `ai4bharat/indic-conformer-600m-multilingual`, `shunyalabs/zero-stt-hinglish`, `ai4bharat/IndicF5`, `ai4bharat/indic-parler-tts`, `collabora/whisper-large-v2-hindi`, and the `ai4bharat/IndicVoices` dataset.
- **TTS_Fallback**: Open-source text-to-speech used as a fallback or auxiliary output path. Candidates: `hexgrad/Kokoro-82M`, `bosonai/higgs-audio-v2`, `SparkAudio/Spark-TTS`, `kyutai/tts-1.6b`.
- **Hinglish_Data_Engine**: The data acquisition, transliteration, segmentation, and labeling pipeline that produces the code-switch data moat.
- **Emotion_Persona_Controller**: The component that conditions output tone using discrete emotion tags plus continuous valence/arousal/dominance (V/A/D) vectors and FiLM-style conditioning.
- **Duplex_Manager**: The component responsible for full-duplex turn-taking, barge-in detection, and response repair, evolving `server/pipeline/barge_in.py` and `turn_state.py`.
- **Evaluation_Harness**: The reproducible measurement system used to score Candidate_Models and SoulYatri_Platform builds against defined metrics for selection and gating.
- **Benchmark_Suite**: The collection of benchmark families used by the Evaluation_Harness — VoiceBench, EmergentTTS-Eval, Seed-TTS-eval, MUSHRA listening tests, and Speech Arena, plus a Hinglish code-switch benchmark.
- **LEAN_Track**: The first, primary path — adopt an existing Speech_Native_Core, apply lightweight adaptation (LoRA / prompt / adapters) only where evals show a gap, and ship a demo.
- **AMBITIOUS_Track**: The optional later path — fork and fine-tune custom codec / tokenizer / alignment (DPO/GRPO) for differentiation.
- **Decision_Gate**: A named checkpoint with measurable entry/exit criteria that governs progression between phases and the transition from the LEAN_Track to the AMBITIOUS_Track.
- **Launch_Gate**: A Decision_Gate whose criteria must be satisfied before a build is declared demo-ready or ship-ready.
- **Safety_Guard**: The subsystem covering crisis detection, consent management, voice-cloning restriction, and audio watermarking.
- **Licensing_Register**: The maintained record of every adopted model, dataset, and tool with its license and usage constraints.

## Requirements

### Requirement 1: Phased Path with LEAN and AMBITIOUS Tracks and Decision Gates

**User Story:** As the project lead, I want a single coherent phased plan that reconciles the "fast solo demo" and "funded custom-model" strategies, so that the team follows one path instead of two contradictory PDFs.

#### Acceptance Criteria

1. THE Roadmap SHALL define an ordered sequence of at least two phases in which each phase has a unique ordinal position and a unique identifier, the first phase is the existing Phase_1_Pipeline, and the final phase is a speech-native SoulYatri_Platform.
2. THE Roadmap SHALL label the LEAN_Track explicitly as "primary" and the AMBITIOUS_Track explicitly as "optional", where the AMBITIOUS_Track is positioned after the Decision_Gate defined in criterion 3.
3. THE Roadmap SHALL define at least one Decision_Gate positioned between the LEAN_Track and the AMBITIOUS_Track.
4. WHERE a Decision_Gate is defined, THE Roadmap SHALL specify, for that gate, entry criteria and exit criteria where each criterion is expressed as a named metric, a numeric threshold, and a comparison operator that together resolve to a single pass/fail result, and exactly one named owner role responsible for the gate decision.
5. IF a Decision_Gate's exit criteria are not met, THEN THE Roadmap SHALL define a fallback action that names the phase or track to continue on, where remaining on the LEAN_Track is an explicitly allowed option.
6. THE Roadmap SHALL map each phase to at least one identified section heading of the existing `Soulyatri_Final_Speech_Native_Implementation_Guide.md` so that traceability to the implementation guide is preserved.
7. WHERE the Roadmap makes a decision that conflicts with the `SOULYATRI_MASTER_BIBLE` or `VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN` documents, THE Roadmap SHALL record, for each such conflict, the conflict topic, the superseding decision, and the rationale.

### Requirement 2: Speech-Native Core Adoption and Selection

**User Story:** As an ML engineer, I want explicit criteria for adopting an existing speech-native model, so that I select a backbone instead of building one from scratch.

#### Acceptance Criteria

1. THE Roadmap SHALL designate "adopt an existing open-source Speech_Native_Core" as the primary backbone strategy and "fork and fine-tune a custom model" as a deferred AMBITIOUS_Track activity.
2. THE Roadmap SHALL enumerate the verified 2026 Candidate_Models for the Speech_Native_Core, including at least Moshi (`kyutai/moshiko-pytorch-bf16`, `kyutai/moshika-pytorch-bf16`), `Qwen/Qwen3-Omni-30B-A3B-Instruct`, `zai-org/glm-4-voice-9b`, `sesame/csm-1b`, and `LiquidAI/LFM2.5-Audio-1.5B`.
3. THE Roadmap SHALL define weighted selection criteria for the Speech_Native_Core covering full-duplex capability, streaming latency, Hindi/Hinglish capability, license permissiveness, VRAM/compute footprint, and community activity, where each criterion carries a numeric weight, the weights sum to 100 percent, and each criterion has a defined minimum pass threshold.
4. WHEN a Candidate_Model is evaluated for adoption, THE Evaluation_Harness SHALL score the Candidate_Model against every defined selection criterion.
5. THE Roadmap SHALL designate `sesame/csm-1b` and a TTS_Fallback as reference/fallback generators rather than as the primary backbone.
6. WHERE the selected Speech_Native_Core requires a Codec_Component, THE Roadmap SHALL specify `kyutai/mimi` as the primary Codec_Component and SHALL name `neuphonic/neucodec` and `HKUSTAudio/xcodec2` as alternatives.
7. IF no Candidate_Model meets every per-criterion minimum pass threshold defined in criterion 3, THEN THE Roadmap SHALL specify retaining the Phase_1_Pipeline as the production path until a qualifying model is available.
8. WHEN a Candidate_Model meets every per-criterion minimum pass threshold defined in criterion 3 and is selected, THE Roadmap SHALL specify retaining the Phase_1_Pipeline as an additional fallback path that runs alongside the selected Speech_Native_Core until the selected Speech_Native_Core has passed the LEAN_Track Launch_Gate.
9. WHEN more than one Candidate_Model meets every per-criterion minimum pass threshold, THE Roadmap SHALL select the Candidate_Model with the highest weighted aggregate score across the selection criteria.

### Requirement 3: Evolution from the Phase 1 Pipeline

**User Story:** As a developer maintaining the running system, I want the migration from the classic pipeline to the speech-native core to preserve a working fallback, so that the product never regresses to a non-functional state during the transition.

#### Acceptance Criteria

1. THE Roadmap SHALL specify an incremental migration that includes at least one intermediate stage in which the Speech_Native_Core and the Phase_1_Pipeline run concurrently, so that the Speech_Native_Core is introduced alongside the Phase_1_Pipeline rather than replacing the Phase_1_Pipeline in a single step.
2. WHILE the Speech_Native_Core is being integrated, THE SoulYatri_Platform SHALL retain the Phase_1_Pipeline as a fallback path that is selectable per session through a runtime configuration setting.
3. THE Roadmap SHALL specify reuse of the existing edge components — Silero VAD, the turn-state machine in `server/pipeline/turn_state.py`, and the filler router in `server/pipeline/filler.py` — in the speech-native architecture.
4. THE Roadmap SHALL specify that faster-whisper and the Indic_Stack ASR models are retained as auxiliary STT for transcripts, memory, and moderation after the Speech_Native_Core is adopted.
5. IF the Speech_Native_Core does not produce its first audible response token within the first-response latency budget defined for the SoulYatri_Platform (300 milliseconds, per the practical first-response latency target) during a turn, THEN THE SoulYatri_Platform SHALL complete that turn using the Phase_1_Pipeline, or using a TTS_Fallback when the Phase_1_Pipeline is unavailable, and this fallback SHALL be triggered only by latency-budget violations and not by other Speech_Native_Core failure types.
6. THE Roadmap SHALL specify that the existing WebSocket audio protocol (`/ws/audio/{session_id}`) and LiveKit transport are either preserved unchanged or assigned an explicit version identifier when the Speech_Native_Core is introduced.

### Requirement 4: Evaluation Harness for Model Selection

**User Story:** As an ML engineer, I want a reproducible evaluation harness, so that model adoption decisions are made on measured evidence rather than marketing claims.

#### Acceptance Criteria

1. THE Roadmap SHALL define an Evaluation_Harness that produces comparable scores across all Candidate_Models, where comparable means the same metric set, the same input set, and the same scoring scale are applied to every Candidate_Model.
2. THE Evaluation_Harness SHALL measure, for each Candidate_Model, first-response latency in milliseconds at the 50th percentile, Hindi/Hinglish quality scored by the defined code-switch quality metric, emotional expressiveness on a defined numeric scale, and license compatibility as a categorical result.
3. WHEN the Evaluation_Harness completes a Candidate_Model run, THE Evaluation_Harness SHALL record the model identifier, the model version or revision, the metric scores, and the hardware used expressed as GPU class and VRAM in gigabytes.
4. THE Evaluation_Harness SHALL be reproducible such that re-running the harness at least three times on the same Candidate_Model and same hardware produces, for each metric, scores within a documented per-metric tolerance expressed as an absolute value or a percentage.
5. IF a Candidate_Model cannot be evaluated because of missing weights, license restriction, or hardware limits, THEN THE Evaluation_Harness SHALL record the exclusion category and reason and SHALL continue evaluating the remaining Candidate_Models without aborting.
6. THE Evaluation_Harness SHALL run with mocked inputs, small-sample inputs bounded by a documented maximum item count, or a combination of both for cost-sensitive operations, and SHALL NOT require any GPU model-training run.

### Requirement 5: Hinglish and Code-Switch Quality Moat

**User Story:** As a product owner, I want Hindi/English/Hinglish code-switch quality to be the primary differentiator, so that SoulYatri sounds native where global competitors sound foreign.

#### Acceptance Criteria

1. THE Roadmap SHALL designate Hinglish and Hindi/English code-switch quality as the SoulYatri_Platform's primary competitive moat.
2. THE Roadmap SHALL define a Hinglish_Data_Engine that sources consented code-switch conversational data, including both Romanized and native-script (Devanagari) variants.
3. THE Hinglish_Data_Engine SHALL incorporate the verified Indic_Stack resources, including `ai4bharat/indic-conformer-600m-multilingual`, `shunyalabs/zero-stt-hinglish`, `ai4bharat/IndicF5`, `ai4bharat/indic-parler-tts`, and the `ai4bharat/IndicVoices` dataset.
4. WHEN code-switched input mixing Hindi and English is received, THE SoulYatri_Platform SHALL produce a response whose Hindi-to-English token ratio is within 15 percentage points of the input's Hindi-to-English token ratio, as scored by the defined code-switch quality metric.
5. THE Hinglish_Data_Engine SHALL define a deterministic transliteration mapping between Romanized Hinglish and Devanagari such that the same input string always produces the same normalized output, applied for both input normalization and output rendering.
6. THE Benchmark_Suite SHALL include a Hinglish code-switch evaluation that a build passes only when it scores at or above 80 percent on the code-switch quality metric across the evaluation set.
7. WHERE the adopted Speech_Native_Core scores below the Hinglish code-switch pass threshold defined in criterion 6, THE Roadmap SHALL specify lightweight adaptation (LoRA or adapters) on the Hinglish_Data_Engine output before any custom-model work is considered.
8. IF a Romanized Hinglish input token has no entry in the transliteration mapping, THEN THE Hinglish_Data_Engine SHALL retain the original token unchanged in the normalized output and SHALL flag the token as unmapped for review.

### Requirement 6: Emotion and Persona Control

**User Story:** As a user, I want the assistant to sound emotionally aware and consistent in persona, so that the conversation feels human rather than robotic.

#### Acceptance Criteria

1. THE Emotion_Persona_Controller SHALL accept as input both discrete emotion tags from the set {neutral, happy, sad, angry, fear, disgust, surprise} and a continuous valence/arousal/dominance (V/A/D) vector where each dimension is bounded to the inclusive range -1.0 to 1.0.
2. THE Roadmap SHALL specify that the continuous V/A/D representation already produced by `server/pipeline/emotion.py` is carried forward into the Emotion_Persona_Controller.
3. WHEN per-turn emotion features (the V/A/D vector, the dominant emotion label, and a confidence value) are extracted, THE Emotion_Persona_Controller SHALL apply those features to condition the SoulYatri_Platform's output tone for that turn.
4. THE Roadmap SHALL specify FiLM-style conditioning as the mechanism for injecting emotion and persona state into the output path.
5. WHILE the detected dominant emotion label is a distress label (sad, angry, or fear) with confidence of at least 0.50, THE SoulYatri_Platform SHALL apply empathetic or calming persona conditioning to every response turn for the duration of that state.
6. THE Roadmap SHALL specify the open-source emotion and speaker models retained for feature extraction, including a wav2vec2-based SER model (`speechbrain/emotion-recognition-wav2vec2-IEMOCAP` or the currently configured equivalent) and an ECAPA-TDNN speaker encoder.
7. IF per-turn emotion extraction is unavailable or fails for a turn, THEN THE Emotion_Persona_Controller SHALL apply neutral conditioning (V/A/D = 0.0, 0.0, 0.0 with the neutral tag) and SHALL continue the turn without interruption.

### Requirement 7: Full-Duplex, Barge-in, and Latency Targets

**User Story:** As a user, I want to interrupt the assistant naturally and get near-instant responses, so that the conversation feels live.

#### Acceptance Criteria

1. THE Roadmap SHALL set a practical first-response latency target of 300 milliseconds or less at the 50th percentile, measured from end-of-user-speech to first audible response token on the Roadmap's defined target hardware profile.
2. THE Roadmap SHALL set a stretch first-response latency target of 200 milliseconds or less at the 50th percentile on the Roadmap's defined target hardware profile.
3. THE Roadmap SHALL set a perceived-latency target of 80 milliseconds or less at the 50th percentile, measured from end-of-user-speech to first audible output of any kind including a cached filler phrase, achieved through streaming output and cached filler phrases.
4. WHEN the Duplex_Manager detects at least 150 milliseconds of voiced user speech while the SoulYatri_Platform is producing audio, THE Duplex_Manager SHALL suppress the SoulYatri_Platform's current audio output within 200 milliseconds of that detection.
5. WHEN a barge-in is detected, THE Duplex_Manager SHALL transition the turn state to a listening state within 100 milliseconds, including when the SoulYatri_Platform is already processing a prior interruption or is in an intermediate state, so that the new user utterance is captured.
6. THE Roadmap SHALL specify that the barge-in detection in `server/pipeline/barge_in.py` and the turn-state machine in `server/pipeline/turn_state.py` evolve into the full-duplex Duplex_Manager rather than being rebuilt from scratch.
7. IF the practical latency target is not met on the Roadmap's defined target hardware profile, THEN THE Roadmap SHALL specify mitigation options, including model quantization, a smaller Speech_Native_Core, or expanded filler coverage.

### Requirement 8: Benchmark and Evaluation Programme with Launch Gates

**User Story:** As the project lead, I want measurable launch gates tied to recognized benchmarks, so that "ready to demo" and "ready to ship" are objective decisions.

#### Acceptance Criteria

1. THE Benchmark_Suite SHALL include the benchmark families from the clean-room strategy document: VoiceBench, EmergentTTS-Eval, Seed-TTS-eval, MUSHRA listening tests, and Speech Arena.
2. THE Roadmap SHALL define a Launch_Gate for the LEAN_Track demo that specifies, for each of latency, Hinglish code-switch quality, and emotional expressiveness, a numeric pass threshold expressed with its unit and comparison operator together with the Benchmark_Suite metric or Evaluation_Harness measurement used to evaluate it, where the latency threshold is a 50th-percentile first-response latency of 300 milliseconds or less and the Hinglish quality threshold is the Hinglish code-switch pass threshold defined for the Benchmark_Suite.
3. WHERE an AMBITIOUS_Track differentiation release is planned, THE Roadmap SHALL define a separate Launch_Gate that specifies, for each Benchmark_Suite family used to judge the release, a numeric pass threshold with its unit and comparison operator, and SHALL state, for each competitive comparison target, the numeric score the release must meet or exceed.
4. WHEN a SoulYatri_Platform build is evaluated against a Launch_Gate, THE Evaluation_Harness SHALL report, for each gate threshold, the measured value, the threshold value, and a pass or fail result, and SHALL report an overall gate result of pass only when every gate threshold passes.
5. IF any Launch_Gate threshold is not met, THEN THE Roadmap SHALL mark the corresponding release as blocked, SHALL withhold the demo-ready or ship-ready declaration for that release, and SHALL specify a remediation path that identifies each failing threshold and the corrective action for it.
6. THE Roadmap SHALL define the competitive comparison targets (ElevenLabs, Hume, Rumik/Silk, Sarvam) used as external reference points for the Benchmark_Suite.

### Requirement 9: Budget and Compute Awareness

**User Story:** As the project lead, I want each phase to carry an explicit budget and compute estimate, so that the LEAN-vs-AMBITIOUS decision is grounded in cost reality.

#### Acceptance Criteria

1. WHERE a phase is defined, THE Roadmap SHALL state, for that phase, an estimated compute footprint expressed as the minimum GPU class and the minimum VRAM in gigabytes (GB) required to execute that phase.
2. THE Roadmap SHALL state a budget range for the LEAN_Track and a separate budget range for the AMBITIOUS_Track, where each range is expressed as a lower-bound value and an upper-bound value in a single stated currency.
3. THE Roadmap SHALL state that the LEAN_Track is executable by a team of at most five people without large-scale GPU training runs, where "large-scale GPU training runs" means multi-GPU or multi-node from-scratch model training.
4. WHEN the AMBITIOUS_Track is proposed at a Decision_Gate, THE Roadmap SHALL require, before that track is entered, an explicit justification that includes the AMBITIOUS_Track budget range defined in criterion 2 and the per-phase compute footprint (GPU class and VRAM in GB) defined in criterion 1.
5. IF the available compute is below the minimum required for a phase, OR the available compute is zero, OR compute-availability data is invalid or missing, THEN THE Roadmap SHALL specify, for that phase, a reduced-scope alternative whose stated compute footprint (GPU class and VRAM in GB) does not exceed the compute confirmed to be available.

### Requirement 10: Safety, Consent, and Watermarking for Voice Cloning

**User Story:** As a responsible operator, I want consent-first guardrails on voice cloning and crisis handling, so that the system is safe to deploy and resists misuse.

#### Acceptance Criteria

1. THE Safety_Guard SHALL require recorded consent — comprising a speaker identifier, a permitted-use scope, and a timestamp — before any speaker's voice is used for cloning or voice-style transfer.
2. WHEN the SoulYatri_Platform synthesizes speech output on any output path, including fallback paths, THE Safety_Guard SHALL apply an audio watermark that is detectable by a watermark detector to that output.
3. IF a voice-cloning request lacks recorded consent, THEN THE Safety_Guard SHALL refuse the cloning request, SHALL indicate the refusal to the requester, and SHALL NOT retain the requested voice reference.
4. WHEN the crisis classifier labels user speech as a self-harm or crisis situation at or above its decision threshold, THE Safety_Guard SHALL surface crisis-support guidance to the user.
5. WHEN the crisis classifier labels user speech as a self-harm or crisis situation at or above its decision threshold, THE Safety_Guard SHALL flag the turn for human review.
6. THE Safety_Guard SHALL maintain a consent log for every voice used in a product-facing capacity, recording the speaker identifier, the permitted-use scope, and the consent timestamp, and SHALL retain that log for as long as the voice remains in product-facing use.
7. THE Roadmap SHALL specify that safety classification and watermarking are part of the LEAN_Track demo scope rather than deferred to the AMBITIOUS_Track.

### Requirement 11: Open-Source-Only and Licensing Constraints

**User Story:** As a maintainer, I want every adopted component to be open-source with a tracked license, so that the project stays reproducible and legally clear.

#### Acceptance Criteria

1. THE SoulYatri_Platform SHALL use only models, datasets, and tools that carry a recognized open-source license identifier recorded in the Licensing_Register.
2. WHEN a model, dataset, or tool is adopted, THE Licensing_Register SHALL record, before that component is used in any build, the component name, its open-source license identifier, and any commercial-use or attribution constraints.
3. IF license recording fails for an adopted component, THEN THE Roadmap SHALL allow adoption to proceed, SHALL raise a compliance warning identifying that component, and SHALL retain that warning as unresolved until the missing license information is recorded.
4. IF a Candidate_Model is excluded for any reason, including a license that prohibits the intended use or non-licensing reasons such as performance or compatibility, THEN THE Licensing_Register SHALL record the exclusion and the exclusion reason.
5. THE Roadmap SHALL specify that, at every Launch_Gate, the Licensing_Register is reviewed to confirm that each adopted component has a recorded open-source license identifier and that no adopted component carries a license prohibiting its intended use.
6. THE Licensing_Register SHALL flag any dataset whose terms restrict redistribution or require subject consent, and SHALL record the specific restriction type for that dataset.
7. IF, at a Launch_Gate review, the Licensing_Register contains an unresolved compliance warning or an adopted component whose license prohibits its intended use, THEN THE Roadmap SHALL block the corresponding release until the flagged issue is resolved.
8. WHILE a dataset is flagged in the Licensing_Register as restricting redistribution or requiring subject consent, THE Hinglish_Data_Engine SHALL exclude that dataset's content from any redistributed output until the recorded restriction is satisfied.

### Requirement 12: Relationship to Existing Artifacts and Scope Boundaries

**User Story:** As a contributor, I want the roadmap to clearly state what it supersedes, what it references, and what is out of scope, so that the team has one authoritative plan.

#### Acceptance Criteria

1. THE Roadmap SHALL include an explicit statement declaring itself the authoritative build plan for all build-sequencing decisions, superseding every strategy PDF document located in the `docs/` directory.
2. THE Roadmap SHALL reference the existing `.kiro/specs/ai-training-docs/` spec as the documentation/knowledge-base workstream.
3. THE Roadmap SHALL NOT restate or redefine any documentation-generation requirement that is already defined in the `.kiro/specs/ai-training-docs/` spec.
4. THE Roadmap SHALL include an explicit statement excluding from-scratch foundation-model pretraining from its scope.
5. THE Roadmap SHALL include an explicit statement excluding execution of GPU-based model-training runs from this spec's scope, identifying training execution as downstream work that the Roadmap plans but does not perform.
6. WHERE the Roadmap references a strategy PDF, THE Roadmap SHALL cite that document by its exact file name as it appears in the `docs/` directory.
7. THE Roadmap SHALL include an explicit statement that the sole deliverable of this spec is a planning artifact and not executable model-training code.
