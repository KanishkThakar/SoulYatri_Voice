# SoulYatri Speech-Native Voice Roadmap

> **Status:** Authoritative build-sequencing plan (planning artifact).
> **Deliverable type:** This roadmap is a planning artifact — a single coherent, phased build plan. It plans model adoption, evaluation, and fine-tuning work; it does not execute any GPU-based model-training run.

This document is the single, current, executable phased plan for evolving the **SoulYatri_Platform** from its existing Phase 1 classic cascade into a speech-native, low-latency, emotional, code-switched (Hindi / English / Hinglish) conversational voice AI built from open-source components only.

It reconciles three disagreeing sources of truth — the code that already exists in this workspace, the scattered strategy PDFs in `docs/`, and the verified 2026 open-source model landscape — into **one path with two named tracks**: a **LEAN_Track** (primary) executed first, and an optional **AMBITIOUS_Track** gated behind an explicit, measurable decision gate.

## Document structure

This roadmap is organized into the following top-level sections. The sections authored here cover the phase/track/gate structure, traceability to the implementation guide, and the conflict register. Subsequent sections — model adoption and selection, evolution from the Phase 1 pipeline, the Hinglish moat, emotion/persona control, full-duplex/latency targets, the benchmark programme, budget/compute awareness, safety/consent/watermarking scope, and the scope-and-relationship statements — follow below and are authored as the roadmap is completed.

1. Phase and track structure *(this section)*
2. Phase-to-implementation-guide traceability *(this section)*
3. Decision_Gate `G1` (LEAN → AMBITIOUS) *(this section)*
4. Conflict register *(this section)*
5. Model adoption and selection
6. Evolution from the Phase 1 pipeline
7. Hinglish moat, emotion/persona, full-duplex and latency
8. Benchmark programme and launch gates
9. Budget and compute awareness
10. Safety, consent, and watermarking scope
11. Scope boundaries and relationship to existing artifacts

---

## 1. Phase and track structure

The roadmap defines an ordered sequence of **seven phases**. Each phase has a unique ordinal position and a unique identifier. The ordinals are contiguous and start at 1.

- The **first phase** (`P1-baseline`, ordinal 1) is the existing **Phase_1_Pipeline** — the already-coded classic cascade (Silero VAD → faster-whisper → Ollama LLM → edge-tts).
- The **final phase** (`P7-diff-gate`, ordinal 7) is the **speech-native SoulYatri_Platform** at its AMBITIOUS Differentiation Launch Gate.

The phases are partitioned into two tracks separated by Decision_Gate `G1`:

- **LEAN_Track — labeled `primary`.** Phases `P1`–`P5`. Adopt an existing Speech-Native Core, apply lightweight adaptation only where evals show a gap, and ship a demo behind the LEAN Demo Launch Gate.
- **AMBITIOUS_Track — labeled `optional`.** Phases `P6`–`P7`. Fork and fine-tune a custom codec / tokenizer / alignment (DPO/GRPO) for differentiation. This track is **positioned after Decision_Gate `G1`** and is entered only when `G1`'s exit criteria are met.

### 1.1 Ordered phase table

| Ordinal | ID | Track | Track label | Title | Speech-native |
|---|---|---|---|---|---|
| 1 | `P1-baseline` | LEAN | primary | Phase_1_Pipeline (existing classic cascade) | No |
| 2 | `P2-core-select` | LEAN | primary | Speech-Native Core selection + Evaluation Harness | No |
| 3 | `P3-integrate` | LEAN | primary | Concurrent integration (core + Phase 1 fallback) | Partial |
| 4 | `P4-moat-duplex` | LEAN | primary | Hinglish moat + Emotion/Persona (FiLM) + Full-duplex + Latency | Yes |
| 5 | `P5-safety-gate` | LEAN | primary | Safety/consent/watermark + LEAN Demo Launch Gate | Yes |
| 6 | `P6-custom` | AMBITIOUS | optional | Custom codec/tokenizer + alignment (DPO/GRPO) | Yes |
| 7 | `P7-diff-gate` | AMBITIOUS | optional | AMBITIOUS Differentiation Launch Gate (final speech-native platform) | Yes |

The LEAN_Track (`P1`–`P5`) is **primary** and is executed first. The AMBITIOUS_Track (`P6`–`P7`) is **optional** and sits after Decision_Gate `G1`. Remaining on the LEAN_Track is always an allowed outcome (see `G1` fallback below).

### 1.2 Track flow

```
LEAN_Track (primary)
  P1-baseline → P2-core-select → P3-integrate → P4-moat-duplex → P5-safety-gate
                                                                       │
                                                                       ▼
                                                          Decision_Gate G1 (owner: ML Lead)
                                                          ┌────────────┴─────────────┐
                              exit criteria NOT met       │                          │   exit criteria met
                              (fallback)                  ▼                          ▼   + budget/compute justified
                                            remain on LEAN_Track          AMBITIOUS_Track (optional)
                                            (maintain + iterate demo)     P6-custom → P7-diff-gate
```

---

## 2. Phase-to-implementation-guide traceability

Every phase maps to at least one identified section heading of `Soulyatri_Final_Speech_Native_Implementation_Guide.md`, preserving traceability from the roadmap to the implementation guide. Detailed per-phase tasks are expanded in `soulyatri_final_speech_native_implementation_guide_expanded.md`.

| Ordinal | ID | Phase | Implementation-guide section(s) in `Soulyatri_Final_Speech_Native_Implementation_Guide.md` |
|---|---|---|---|
| 1 | `P1-baseline` | Phase_1_Pipeline (existing classic cascade) | "10. The actual implementation order → Phase 1 — production baseline" |
| 2 | `P2-core-select` | Speech-Native Core selection + Evaluation Harness | "3. Recommended open-source stack"; "9B — Evaluation harness" |
| 3 | `P3-integrate` | Concurrent integration (core + Phase 1 fallback) | "10 → Phase 2 — move to speech-native core"; "5. Final runtime architecture in detail" |
| 4 | `P4-moat-duplex` | Hinglish moat + Emotion/Persona (FiLM) + Full-duplex + Latency | "10 → Phase 3 — emotion and persona / Phase 4 — filler latency masking / Phase 5 — full duplex"; "13. Latency engineering" |
| 5 | `P5-safety-gate` | Safety/consent/watermark + LEAN Demo Launch Gate | "11.6 Safety subsystem"; "17. Launch criteria" |
| 6 | `P6-custom` | Custom codec/tokenizer + alignment (DPO/GRPO) | "8. Fine-tuning strategy"; "16. Fine-tuning recipes" |
| 7 | `P7-diff-gate` | AMBITIOUS Differentiation Launch Gate (final speech-native platform) | "17. Launch criteria"; "20. Final note on product strategy" |

---

## 3. Decision_Gate `G1` (LEAN → AMBITIOUS)

`G1` is the single Decision_Gate positioned **between the LEAN_Track and the AMBITIOUS_Track**. It governs the transition from `P5-safety-gate` (the end of the LEAN_Track) to `P6-custom` (the start of the optional AMBITIOUS_Track). The AMBITIOUS_Track is entered **only** when `G1`'s exit criteria all pass.

- **Gate ID:** `G1`
- **Kind:** decision
- **Transition governed:** LEAN_Track (`P5-safety-gate`) → AMBITIOUS_Track (`P6-custom`)
- **Owner role (exactly one):** **ML Lead** — the single named role responsible for the gate decision.

Each criterion below is expressed as a **named metric**, a **numeric threshold**, and a **comparison operator**, which together resolve to a single pass/fail result.

### 3.1 Entry criteria

The gate is evaluated only when every entry criterion passes — that is, the LEAN_Track has actually delivered a stable demo before any AMBITIOUS work is considered.

| Metric | Operator | Threshold | Meaning |
|---|---|---|---|
| `lean_demo_launch_gate_passed` | `==` | `1` | The `P5-safety-gate` LEAN Demo Launch Gate has passed (1 = passed, 0 = not passed). |
| `lean_demo_stable_days` | `>=` | `14` | The LEAN demo has been live and stable for at least 14 days. |

### 3.2 Exit criteria

When **every** exit criterion passes, the roadmap proceeds to `P6-custom` (subject to the AMBITIOUS budget/compute justification recorded in the budget section). If **any** exit criterion fails, the fallback action below applies.

| Metric | Operator | Threshold | Meaning |
|---|---|---|---|
| `measured_competitive_gap_pct` | `>=` | `10` | A quantified deficit of at least 10 percentage points versus the best competitive comparison target on at least one Benchmark_Suite family — custom differentiation is justified only when a real, measured gap exists. |
| `ambitious_budget_justification_approved` | `==` | `1` | The AMBITIOUS budget range and per-phase compute footprint justification is approved (1 = approved, 0 = not approved). |
| `ambitious_compute_vram_gb_confirmed` | `>=` | `80` | The VRAM (in GB) confirmed available meets the minimum footprint required by the AMBITIOUS custom-codec / alignment phases. |

### 3.3 Fallback action (exit criteria not met)

**Fallback action:** `remain on LEAN_Track`.

If `G1`'s exit criteria are not all met, the roadmap does **not** enter the AMBITIOUS_Track. Instead it continues on the **LEAN_Track**, maintaining and iterating the shipped LEAN demo. Remaining on the LEAN_Track is an explicitly allowed outcome of `G1`.

---

## 4. Conflict register

Where this roadmap makes a build-sequencing decision that conflicts with the `SOULYATRI_MASTER_BIBLE` or `VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN` (or other) strategy documents in `docs/`, the conflict is recorded below with its topic, the conflicting document, the superseding decision, and the rationale. Each PDF is cited by its exact file name as it appears in the `docs/` directory.

| Conflict topic | Conflicting PDF | Superseding decision | Rationale |
|---|---|---|---|
| Build custom model from forked weights up front | `SOULYATRI_MASTER_BIBLE.pdf` | Adopt an existing open-source Speech-Native Core first; defer custom work to the AMBITIOUS_Track behind `G1`. | 2026 open-source full-duplex models are adoptable now; a custom build is high cost/risk and not justified until evals show a gap. |
| Reject all from-scratch / fine-tuning work for the demo | `VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN.pdf` | Allow **lightweight** adaptation (LoRA / adapters) on Hinglish data when the core scores below the code-switch pass threshold. | The moat (Hinglish) may need targeted adaptation even in the LEAN_Track; this is not large-scale training. |
| Custom neural codec is a prerequisite | `SOULYATRI_VOICE_AI_FINAL_BUILD_BIBLE.pdf` | Use `kyutai/mimi` as the primary codec; a custom codec is AMBITIOUS-only. | Mimi is production-ready and streaming-optimized; a custom codec is a differentiation bet, not a baseline need. |

---

<!--
Sections 5–11 (model adoption/selection, evolution from Phase 1, Hinglish moat,
emotion/persona, full-duplex/latency, benchmark programme, budget/compute,
safety scope, and scope/relationship statements) are appended by subsequent
roadmap-authoring tasks. Append below this marker.
-->

## 5. Model adoption and selection

### 5.1 Backbone strategy: adopt first, fork later

The roadmap designates **"adopt an existing open-source Speech_Native_Core"** as the **PRIMARY** backbone strategy. The verified 2026 open-source landscape now offers full-duplex / any-to-any speech-native models that can be adopted directly, which materially de-risks the "build a backbone" phase that the strategy PDFs worried about.

**"Fork and fine-tune a custom model"** (custom codec / tokenizer / alignment) is designated a **deferred AMBITIOUS_Track activity**, positioned after Decision_Gate `G1` in phase `P6-custom`. Custom-model work is entered only when a measured competitive gap and an approved budget/compute justification clear `G1` (see Section 3).

| Strategy | Designation | Phase |
|---|---|---|
| Adopt an existing open-source Speech_Native_Core | **PRIMARY** | `P2-core-select` → `P3-integrate` (LEAN) |
| Fork + fine-tune a custom codec / tokenizer / alignment | **Deferred — AMBITIOUS** | `P6-custom` (after `G1`) |

### 5.2 Verified 2026 Candidate_Models

The following Candidate_Models are enumerated for the Speech_Native_Core. All are verified on the Hugging Face Hub for the 2026 landscape.

**Primary candidates (full-duplex / any-to-any S2S backbone):**

| Candidate_Model | Notes |
|---|---|
| `kyutai/moshiko-pytorch-bf16` | Moshi, full-duplex speech-text; ~160 ms theoretical / ~200 ms practical latency on an L4-class GPU. |
| `kyutai/moshika-pytorch-bf16` | Moshi variant (alternate voice), full-duplex. |
| `Qwen/Qwen3-Omni-30B-A3B-Instruct` | Any-to-any omni-modal (large footprint). |
| `zai-org/glm-4-voice-9b` | Speech-native conversational model. |
| `sesame/csm-1b` | Conversational speech model — designated **reference/fallback only** (see Section 5.4). |
| `LiquidAI/LFM2.5-Audio-1.5B` | Compact audio model; favorable VRAM footprint. |

**Additional verified candidates considered:**

`stepfun-ai/Step-Audio-2-mini`, `openbmb/MiniCPM-o-4_5`, `CofeAI/FLM-Audio`, `tencent/Covo-Audio-Chat`, `OpenMOSS-Team/MOSS-Audio-4B-Instruct`, `gpt-omni/mini-omni2`.

Every Candidate_Model is scored by the Evaluation_Harness against every selection criterion (Section 5.3) before adoption.

### 5.3 Weighted selection criteria

The Speech_Native_Core is selected with the weighted criteria below. The **weights sum to 100**, and each criterion carries a **minimum pass threshold** (per-criterion score on a 0–100 scale). A candidate is eligible for selection only when it meets **every** per-criterion minimum; among eligible candidates, the one with the **highest weighted aggregate** is selected. When **no** candidate meets every minimum, the roadmap retains the Phase_1_Pipeline as the production path until a qualifying model is available.

| Criterion | Weight | Minimum pass threshold | Interpretation |
|---|---|---|---|
| `streaming_latency` | 25 | ≥ 60 | Maps to ≤ 300 ms p50 first-response on the target hardware profile. |
| `hinglish_capability` | 25 | ≥ 60 | Hindi / English / Hinglish code-switch capability. |
| `full_duplex` | 20 | ≥ 50 | Simultaneous listen/speak, barge-in support. |
| `license_permissiveness` | 15 | ≥ 70 | Recognized OSS license, intended use permitted. |
| `vram_footprint` | 10 | ≥ 40 | Fits the defined target hardware profile. |
| `community_activity` | 5 | ≥ 30 | Maintenance, releases, ecosystem support. |
| **Total** | **100** | — | — |

### 5.4 Codec component

When the selected Speech_Native_Core requires a Codec_Component:

- **Primary codec:** `kyutai/mimi` — a streaming neural codec at 12.5 Hz / 1.1 kbps with an 80 ms fully-causal frame size, ideal token granularity for a streaming transformer and consistent with the 80 ms perceived-latency target.
- **Alternatives:** `neuphonic/neucodec`, `HKUSTAudio/xcodec2`.

### 5.5 Reference / fallback generators (not the primary backbone)

The following are designated **reference / fallback generators only** — they are not adopted as the primary conversational backbone:

- `sesame/csm-1b` (reference conversational speech model).
- **TTS_Fallback:** `hexgrad/Kokoro-82M`, `bosonai/higgs-audio-v2`, `SparkAudio/Spark-TTS`, `kyutai/tts-1.6b`.

A TTS_Fallback is used on the output path when the Phase_1_Pipeline is unavailable during a latency-triggered fallback (see Section 6.3 and Section 7.3).

### 5.6 Phase 1 retained as an additional fallback until the LEAN Launch_Gate

When a Candidate_Model meets every per-criterion minimum and is selected, the roadmap retains the **Phase_1_Pipeline as an ADDITIONAL fallback path that runs alongside the selected Speech_Native_Core** until the selected core has passed the **LEAN_Track Launch_Gate**. This guarantees the product never regresses to a non-functional state during the migration: the proven classic cascade remains available, per session, throughout the LEAN integration window.

---

## 6. Evolution from the Phase 1 pipeline

The migration from the classic cascade to the Speech_Native_Core is **incremental** and **never replaces the working pipeline in a single step**.

### 6.1 Concurrent-run migration stage

Phase `P3-integrate` defines at least one intermediate stage in which the **Speech_Native_Core and the Phase_1_Pipeline run concurrently**. The core is introduced *alongside* the existing pipeline rather than swapped in. A **per-session runtime fallback switch** — a runtime configuration setting — selects, for each session, whether the conversational turn is served by the Speech_Native_Core (default) or by the Phase_1_Pipeline fallback. The Phase_1_Pipeline remains the per-session fallback for the entire integration window, and as an additional fallback until the LEAN Launch_Gate passes (Section 5.6).

### 6.2 Reuse of existing edge components

The speech-native architecture **reuses** the existing edge components rather than rebuilding them:

- **Silero VAD** — voice-activity detection, carried forward unchanged.
- **`server/pipeline/turn_state.py`** — the turn-state machine, carried forward and evolved into the Duplex_Manager.
- **`server/pipeline/filler.py`** — the filler router, carried forward to mask latency with cached filler phrases.

### 6.3 Retained auxiliary STT

After the Speech_Native_Core is adopted, **faster-whisper** and the **Indic_Stack ASR** models are retained as **auxiliary STT** — used for transcripts, memory, and moderation (not as the primary conversational path). This keeps transcript/memory/moderation capabilities intact independent of the speech-native core.

### 6.4 Transport continuity

The existing **WebSocket audio protocol `/ws/audio/{session_id}`** and the **LiveKit transport** are either **preserved unchanged** or **assigned an explicit version identifier (`v2`)** when the Speech_Native_Core is introduced. Clients and the edge runtime negotiate the protocol version explicitly, so transport changes are never silent.

---

## 7. Hinglish moat, emotion/persona, full-duplex and latency

### 7.1 Hinglish / code-switch quality moat

The roadmap designates **Hinglish and Hindi/English code-switch quality** as the SoulYatri_Platform's **PRIMARY competitive moat** — the differentiator that makes SoulYatri sound native where global competitors sound foreign.

- The **Hinglish_Data_Engine** sources **consented** code-switch conversational data, including both **Romanized** and **native-script (Devanagari)** variants.
- The engine incorporates the verified **Indic_Stack** resources:

| Resource | Role |
|---|---|
| `ai4bharat/indic-conformer-600m-multilingual` | Multilingual Indic ASR. |
| `shunyalabs/zero-stt-hinglish` | Hinglish-specialized STT. |
| `ai4bharat/IndicF5` | Indic TTS. |
| `ai4bharat/indic-parler-tts` | Indic Parler TTS. |
| `ai4bharat/IndicVoices` | Indic conversational dataset. |

When the adopted core scores below the 80% Hinglish code-switch pass threshold, the roadmap specifies **lightweight adaptation (LoRA / adapters)** on the Hinglish_Data_Engine output **before** any custom-model work is considered.

### 7.2 Emotion and persona control

- The continuous **valence / arousal / dominance (V/A/D)** representation already produced by `server/pipeline/emotion.py` is **carried forward** into the Emotion_Persona_Controller.
- **FiLM-style conditioning** is the specified mechanism for injecting emotion and persona state into the output path.
- Retained open-source feature-extraction models:

| Model | Role |
|---|---|
| `speechbrain/emotion-recognition-wav2vec2-IEMOCAP` (or the currently configured equivalent) | wav2vec2-based speech emotion recognition (SER). |
| ECAPA-TDNN speaker encoder | Speaker embedding / identity features (carried forward from `server/pipeline/speaker.py`). |

### 7.3 Full-duplex and latency targets

The roadmap sets three first-response latency targets, all measured at the **50th percentile (p50)** on the roadmap's defined target hardware profile:

| Target | Threshold (p50) | Measured from | How achieved |
|---|---|---|---|
| **Practical first-response** | ≤ **300 ms** | end-of-user-speech → first audible response token | Streaming Speech_Native_Core. |
| **Stretch first-response** | ≤ **200 ms** | end-of-user-speech → first audible response token | Optimized streaming (e.g. Moshi-class core). |
| **Perceived latency** | ≤ **80 ms** | end-of-user-speech → first audible output of any kind | Streaming output **plus cached filler phrases** from `filler.py`. |

The **Duplex_Manager** is the **evolution of `server/pipeline/barge_in.py` + `server/pipeline/turn_state.py`** — it is not rebuilt from scratch. It owns full-duplex turn-taking, barge-in suppression, and the latency-triggered fallback.

**Mitigations if the practical (300 ms) target is missed** on the target hardware profile:

- **Model quantization** of the Speech_Native_Core.
- Adopting a **smaller Speech_Native_Core**.
- **Expanded filler coverage** to mask latency perceptually.

---

## 8. Benchmark programme and launch gates

### 8.1 Benchmark families

The Benchmark_Suite includes the benchmark families from the clean-room strategy document, plus a Hinglish-specific benchmark:

| Benchmark family | Purpose |
|---|---|
| **VoiceBench** | LLM-based voice-assistant evaluation. |
| **EmergentTTS-Eval** | Prosody / expressiveness via model-as-judge. |
| **Seed-TTS-eval** | TTS quality / intelligibility. |
| **MUSHRA listening tests** | Human listening quality (subjective). |
| **Speech Arena** | Comparative arena-style ranking. |
| **Hinglish code-switch benchmark** | Code-switch quality on the defined Hinglish evaluation set (moat-specific). |

### 8.2 LEAN Demo Launch_Gate

The LEAN_Track demo is gated by the **LEAN Demo Launch_Gate** (phase `P5-safety-gate`). Each threshold is expressed with its **numeric value, unit, comparison operator**, and the **metric / measurement** used. The overall gate result is **pass only when every threshold passes** (and the Licensing_Register is clean — see Section 10/11 forthcoming).

| Gate dimension | Operator | Threshold | Unit | Metric / measurement |
|---|---|---|---|---|
| First-response latency | `<=` | 300 | ms (p50) | Evaluation_Harness first-response latency, 50th percentile, end-of-user-speech → first audible response token. |
| Hinglish code-switch quality | `>=` | 80 | % | Hinglish code-switch benchmark score across the evaluation set (the Benchmark_Suite Hinglish pass threshold). |
| Emotional expressiveness | `>=` | 70 | points (0–100) | EmergentTTS-Eval expressiveness score (Evaluation_Harness emotional-expressiveness scale). |

If any LEAN gate threshold is not met, the demo release is marked **blocked**, the demo-ready declaration is withheld, and a remediation path is recorded that identifies each failing threshold and its corrective action.

### 8.3 AMBITIOUS Differentiation Launch_Gate

The optional AMBITIOUS_Track differentiation release (phase `P7-diff-gate`) is gated by a separate Launch_Gate that defines, for **each Benchmark_Suite family** used to judge the release, a numeric pass threshold with its unit and operator, and states, **for each competitive comparison target, the numeric score the release must meet or exceed**.

| Benchmark family | Operator | Pass threshold | Unit |
|---|---|---|---|
| VoiceBench | `>=` | 85 | score (0–100) |
| EmergentTTS-Eval | `>=` | 80 | score (0–100) |
| Seed-TTS-eval | `>=` | 80 | score (0–100) |
| MUSHRA | `>=` | 80 | MUSHRA score (0–100) |
| Speech Arena | `>=` | 1200 | Elo-style rating |
| Hinglish code-switch | `>=` | 90 | % |

**Competitive comparison targets** (external reference points the differentiation release must meet or exceed, per family):

| Competitive target | Reference scope | Differentiation requirement |
|---|---|---|
| **ElevenLabs** | Expressiveness / TTS quality (EmergentTTS-Eval, MUSHRA) | Meet or exceed on prosody/expressiveness while leading on Hinglish code-switch. |
| **Hume** | Emotional expressiveness | Meet or exceed on the emotional-expressiveness measure. |
| **Rumik/Silk** | Conversational / arena | Meet or exceed on Speech Arena ranking. |
| **Sarvam** | Indic / Hinglish | Meet or exceed on the Hinglish code-switch benchmark (the moat). |

The AMBITIOUS differentiation release is declared ship-ready **only** when every per-family threshold passes **and** every competitive comparison target is met or exceeded. Any unmet threshold marks the release **blocked** with a recorded remediation path.

---

## 9. Budget and compute awareness

Each phase carries an explicit compute footprint, and each track carries an explicit budget range, so that the LEAN-vs-AMBITIOUS decision at `G1` (Section 3) is grounded in cost reality rather than ambition. These figures are **planning estimates** stated for sequencing decisions; this roadmap does not execute any GPU run that would incur them (see Section 11).

### 9.1 Track budget ranges

Both ranges are expressed in a **single stated currency — US dollars (USD)** — as a lower-bound and an upper-bound value, with `lower <= upper`. These ranges match the planner defaults in `roadmap/budget_planner.py` (`DEFAULT_LEAN_BUDGET`, `DEFAULT_AMBITIOUS_BUDGET`).

| Track | Lower bound | Upper bound | Currency | Covers |
|---|---|---|---|---|
| **LEAN_Track** (primary) | 5,000 | 50,000 | USD | Model adoption, the mocked Evaluation_Harness, lightweight LoRA/adapter adaptation, integration, the safety subsystem, and the LEAN Demo Launch_Gate. |
| **AMBITIOUS_Track** (optional) | 50,000 | 500,000 | USD | Custom codec / tokenizer work, DPO/GRPO alignment, expanded data, and the Differentiation Launch_Gate. |

`lower <= upper` holds for both ranges (LEAN: 5,000 ≤ 50,000; AMBITIOUS: 50,000 ≤ 500,000), and both ranges use the same stated currency (USD).

### 9.2 Per-phase compute footprint

Each phase states a compute footprint as a **minimum GPU class** plus a **minimum VRAM in gigabytes (GB)**. The footprints below are drawn from the `GPU_VRAM_LADDER` in `roadmap/budget_planner.py`; the planner's `select_scope(phase, available_compute)` returns a reduced-scope alternative (never exceeding the confirmed-available compute) when available compute is below a phase minimum, is zero, or is invalid/missing.

| Ordinal | Phase | Track | Min GPU class | Min VRAM (GB) |
|---|---|---|---|---|
| 1 | `P1-baseline` | LEAN | `T4-16GB` | 16 |
| 2 | `P2-core-select` | LEAN | `L4-24GB` | 24 |
| 3 | `P3-integrate` | LEAN | `L4-24GB` | 24 |
| 4 | `P4-moat-duplex` | LEAN | `A100-40GB` | 40 |
| 5 | `P5-safety-gate` | LEAN | `L4-24GB` | 24 |
| 6 | `P6-custom` | AMBITIOUS | `A100-80GB` | 80 |
| 7 | `P7-diff-gate` | AMBITIOUS | `A100-80GB` | 80 |

Every LEAN_Track phase (`P1`–`P5`) fits on a **single GPU at or below 40 GB VRAM**. The step up to 80 GB VRAM occurs only in the optional AMBITIOUS_Track (`P6`–`P7`), which is consistent with the `G1` exit criterion `ambitious_compute_vram_gb_confirmed >= 80` (Section 3.2).

### 9.3 LEAN feasibility claim (≤ 5 people, no large-scale GPU training)

The **LEAN_Track is executable by a team of at most five (5) people without large-scale GPU training runs**, where "large-scale GPU training runs" means **multi-GPU or multi-node from-scratch model training**. The LEAN_Track adopts an existing open-source Speech_Native_Core and applies only lightweight adaptation (LoRA / adapters) where evals show a gap — no from-scratch pretraining and no multi-GPU/multi-node training are required to reach the LEAN Demo Launch_Gate. This claim is asserted programmatically by `BudgetComputePlanner.assert_lean_feasibility()` (`lean_max_team_size = 5`, `lean_excludes_large_scale_training = True`).

### 9.4 AMBITIOUS justification requirement (precondition for entering AMBITIOUS at `G1`)

Before the **AMBITIOUS_Track is entered at Decision_Gate `G1`**, an **explicit justification is required** and must be approved. That justification must include **both**:

1. The **AMBITIOUS_Track budget range** from Section 9.1 (50,000–500,000 USD), and
2. The **per-phase compute footprint** (minimum GPU class + minimum VRAM in GB) for the AMBITIOUS phases `P6-custom` and `P7-diff-gate` from Section 9.2 (each `A100-80GB` / 80 GB).

This precondition maps to the `G1` exit criterion `ambitious_budget_justification_approved == 1` (Section 3.2) and is enforced in code by `BudgetComputePlanner.require_ambitious_justification(...)`, which blocks AMBITIOUS entry unless the justification carries the AMBITIOUS budget range, the per-phase footprints, and explicit approval. Absent a complete, approved justification, the roadmap remains on the LEAN_Track (the `G1` fallback).

---

## 10. Safety, consent, and watermarking scope

### 10.1 Safety, consent, and watermarking are in the LEAN demo scope (not deferred)

**Safety classification, consent management, and audio watermarking are part of the LEAN_Track DEMO scope** — they are delivered in phase `P5-safety-gate` and gated by the LEAN Demo Launch_Gate. They are **not** deferred to the optional AMBITIOUS_Track. Concretely, within the LEAN_Track the Safety_Guard:

- **Consent management** — requires a recorded `ConsentRecord` (speaker identifier, permitted-use scope, timestamp) before any voice is used for cloning or voice-style transfer, refuses and does not retain the reference when consent is missing, and maintains a consent log for every product-facing voice.
- **Safety classification** — surfaces crisis-support guidance and flags the turn for human review when the crisis classifier scores at or above its decision threshold.
- **Watermarking** — applies a detector-verifiable audio watermark to **every** synthesized output on **every** output path, including fallback (Phase_1_Pipeline / TTS_Fallback) paths.

Because these guardrails ship with the very first demo, the LEAN demo is safe to deploy and resists misuse from day one.

### 10.2 Licensing reviewed at every Launch_Gate

The **Licensing_Register is reviewed at every Launch_Gate** (the LEAN Demo Launch_Gate in Section 8.2 and the AMBITIOUS Differentiation Launch_Gate in Section 8.3). At each review the gate confirms that:

1. **Every adopted component** (model, dataset, tool) has a **recorded open-source license identifier** in the Licensing_Register, and
2. **No adopted component carries a license that prohibits its intended use.**

If, at a Launch_Gate review, the Licensing_Register holds an unresolved compliance warning or an adopted component whose license prohibits its intended use, the corresponding release is **blocked** until the flagged issue is resolved. This review is enforced in code by the `GateEvaluator` consulting the `LicensingRegister`: a gate's overall result is `pass` only when no unresolved warning and no prohibiting license is present.

---

## 11. Scope boundaries and relationship to existing artifacts

### 11.1 This roadmap is the authoritative build plan and supersedes every strategy PDF in `docs/`

**This roadmap (`roadmap/ROADMAP.md`) is the authoritative build plan for all build-sequencing decisions.** Where it conflicts with any strategy PDF in the `docs/` directory, **this roadmap supersedes that PDF.** It supersedes **every** strategy PDF located in `docs/`, each cited below by its exact file name as it appears in the `docs/` directory:

- `SOULYATRI_MASTER_BIBLE.pdf`
- `SOULYATRI_VOICE_AI_FINAL_BUILD_BIBLE.pdf`
- `SOULYATRI_VOICE_AI_FINAL_BUILD_BIBLE_FIXED.pdf`
- `VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN.pdf`
- `SILKPP_BUILD_BIBLE.pdf`
- `SILKPP_Kill_List_Battle_Plan.pdf`
- `Building a single clean-room voice model that can outcompete Rumik, Sarvam, Hume and ElevenLabs.pdf`

The strategy PDFs remain useful as background and rationale, but for any decision about **what to build, in what order, and behind which gate**, this roadmap is the single source of truth. Specific conflicts and their superseding decisions are recorded in the conflict register (Section 4).

### 11.2 Relationship to the `.kiro/specs/ai-training-docs/` spec

The existing Kiro spec **`.kiro/specs/ai-training-docs/`** is the **documentation / knowledge-base workstream** for the project. This roadmap **references** that spec as the workstream responsible for the project's documentation and Q&A training-data knowledge base. This roadmap **does not restate, redefine, or duplicate** any of that spec's documentation-generation requirements; those requirements remain owned and defined solely within `.kiro/specs/ai-training-docs/`. The two specs are complementary: `ai-training-docs` governs the docs/knowledge-base deliverables, while this roadmap governs the build sequencing.

### 11.3 Explicit scope exclusions

The following are **explicitly out of scope** for this spec:

- **From-scratch foundation-model pretraining is excluded.** This roadmap adopts existing open-source models; it never specifies pretraining a foundation model from scratch.
- **Executing GPU-based model-training runs is excluded.** Model-training execution (including the LoRA/adapter adaptation and the AMBITIOUS DPO/GRPO alignment that the roadmap *plans*) is **downstream work that this roadmap plans but does not perform.** This spec sequences, gates, and budgets that work; it does not run it. (Consistent with the mocked, no-GPU Evaluation_Harness in Section 5/8.)

### 11.4 Planning-artifact-only declaration

**The sole deliverable of this spec is a planning artifact** — this roadmap and its accompanying pure decision-logic tooling and tests. The deliverable is **not** executable model weights and **not** a model-training run. Every figure, footprint, gate, and budget in this document is a planning input for downstream execution decisions; producing trained models or running training is explicitly outside this spec's deliverable.

---

*End of roadmap. Sections 1–11 are complete: phase/track/gate structure and traceability (1–4), model adoption and evolution (5–6), the Hinglish moat, emotion/persona, full-duplex/latency and benchmark programme (7–8), and the budget/compute, safety-scope, and scope/relationship statements (9–11).*
