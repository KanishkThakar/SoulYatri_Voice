# DECISIONS — Frozen Architecture & Decision Log

> **Status:** Phase 0 architecture freeze.
> **Authority:** This document records *frozen* decisions. It may only be changed by a
> new, explicit human-issued architecture decision. Agents may not silently override it.
> **Canonical sources (in order):**
> 1. `Soulyatri_Final_Speech_Native_Implementation_Guide.md`
> 2. `soulyatri_final_speech_native_implementation_guide_expanded.md`
> 3. `final_use.md` (canonical agent-executable master guide; consolidates the above)
> 4. Reference addenda only: the PDFs under `docs/` (build bibles, 60-day plan, kill-list, research memo)
>
> If any addendum conflicts with the canonical markdown architecture, **the canonical markdown wins.**

---

## D-001 — Product identity (FROZEN)

SoulYatri is an **open-source, speech-native, low-latency, full-duplex, emotional,
Hindi + English + Hinglish conversational voice AI**. It is *not* a text chatbot that
happens to speak.

## D-002 — Canonical runtime loop (FROZEN)

The core product loop is **speech-native**, not classic ASR → LLM → TTS:

```text
Audio → Mimi codec tokens → Moshi speech-native runtime → codec tokens → Audio
```

This preserves pauses, interruptions, intonation, laughter, emotional contour,
speaking rhythm, and turn-taking instead of flattening speech to text before responding.

A traditional **STT → text-LLM → TTS** path MAY exist, but **only** as:
- a fallback / degraded-mode shipping path,
- an observability and logging aid,
- a tooling / data-prep path,
- a temporary bring-up baseline.

It must **never** redefine the core product architecture.

## D-003 — Existing `server/` is the gateway + baseline (FROZEN for now)

The repository already contains a working FastAPI gateway and a Phase 1/2 pipeline
under `server/pipeline/` (`vad`, `stt`, `llm`, `tts`, `turn_state`, `filler`, `emotion`,
`speaker`, `features`, `barge_in`, `session`) and a Next.js client under `client/`.

**Decision:** Keep `server/` and `client/` intact. They serve as:
- the **WebRTC/WebSocket gateway** (`server/main.py`),
- the **classic baseline / fallback path** (Phase 13 of `final_use.md`),
- the reference implementation for turn-state, emotion, speaker, filler, and barge-in
  semantics that the new domain folders must stay consistent with.

The `final_use.md` Section 4 domain folders (`edge/`, `speech/`, `aux/`, `memory/`,
`safety/`, `infra/`, `evals/`, `training/`) are added **alongside** the existing code,
**not** nested under a new `soulyatri/` folder. The repository root *is* the
`soulyatri/` root.

## D-004 — Frozen V1 model roles

The default V1 stack (exact checkpoints pinned in `docs/MODEL_LOCKS.md`):

| Role | Frozen V1 choice |
|---|---|
| Transport codec | Opus (network transport only) |
| Neural speech codec | **Mimi** (waveform ↔ codec tokens) |
| Main speech-native runtime | **Moshi** (speech-in, speech-out, full-duplex core) |
| Speech-gen fallback / reference | CSM |
| Auxiliary text reasoning | Qwen3 or Llama 3.3 |
| Auxiliary STT | faster-whisper or IndicConformer |
| Client helper | sherpa-onnx (tiny local ASR/KWS/intent routing) |
| VAD | Silero VAD |
| Speaker embeddings | ECAPA-TDNN |
| Emotion encoder | wav2vec2-class SER model |
| Memory vectorizer | multilingual-e5 |
| Hot cache | Redis |
| Profile / relational store | Postgres |
| Vector store | Qdrant |
| Watermarking | AudioSeal or equivalent |

## D-005 — Non-negotiable constraints (FROZEN)

1. Open source only.
2. **No scratch foundation-model training** at the start.
3. Speech-native first.
4. Full duplex and interruption-aware.
5. Low latency and strong perceived responsiveness.
6. Hindi + English + Hinglish support.
7. Tiny local helper path for fast routing and fillers.
8. Fallback paths for robustness.
9. Fine-tune **only** where a measurable product gain justifies the cost.
10. Production-safe, **consent-first** voice behavior.

## D-006 — Filler subsystem rule (FROZEN)

The filler / cached-phrase subsystem is **mandatory** as a latency-masking layer but must
stay **simple, safe, bounded, and disableable**. It exists to avoid dead air and buy
300–700 ms. It must **not** silently take over non-trivial reasoning.

## D-007 — Safety rule (FROZEN)

No arbitrary public voice cloning. Any voice-reference / style-transfer capability is
**consent-first, auditable, and abuse-resistant**. Synthesized audio watermarking and
consent logs are required safety addenda, compatible with the canonical architecture.

## D-008 — Environment reality for this repo (current)

The development environment has **no GPU** and **no Moshi/Mimi weights**, and training
runs are out of scope here. Therefore:
- All foundation code must **import and run on CPU** without GPU or model weights.
- Heavy/optional model dependencies (torch, transformers, moshi, mimi) must **not** be
  imported at module top-level in the shared contracts or scaffold packages.
- Speech-native components are built as **interfaces + graceful fallbacks** until weights
  and hardware are available (tracked in `docs/MODEL_LOCKS.md` and `docs/OPEN_QUESTIONS.md`).

## D-009 — Shared contract surface

`docs/INTERFACES.md` is the single source of truth for cross-subsystem data types and
service interfaces. `shared/contracts.py` is its importable Python realization. Every
domain folder must depend on these shared contracts rather than redefining incompatible
local types. Where types already exist in `server/pipeline/` (e.g. `TurnState`, emotion
VAD dimensions), the shared contracts stay consistent with them.

---

## "Do-not-build-yet" list (frozen at Phase 0)

These are explicitly **deferred** to avoid early drift:
- scratch pretraining of any foundation model
- inventing a new neural codec
- giant training jobs before a latency baseline exists
- UI polish prioritized over runtime correctness
- clever/unpredictable filler logic
- any unsafe / non-consensual voice-cloning pathway

---

## Decision change procedure

To change a frozen decision: open an issue titled `ADR: <change>`, link the canonical
section being amended, get explicit human approval, then append a new `D-NNN` entry here
(supersede, do not silently edit history).
