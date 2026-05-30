# INTERFACES — Central Shared Contract

> **This is the single source of truth for cross-subsystem data types and service
> interfaces.** Every domain folder (`edge/`, `speech/`, `aux/`, `memory/`, `safety/`, …)
> implements against the contracts defined here. The importable realization lives in
> [`shared/contracts.py`](../shared/contracts.py); `tests/test_contracts.py` guards it.
>
> **Consistency rule:** where the existing `server/pipeline/` already defines a type
> (e.g. `TurnState`, emotion V/A/D dimensions), these contracts stay compatible with it.
> The shared `TurnState` values are a superset alignment of `server/pipeline/turn_state.py`.
>
> **CPU/no-weights rule (D-008):** contracts are plain data (pydantic v2 models + enums +
> dataclasses). No GPU, torch, transformers, moshi, or mimi imports here.

---

## 0. Conventions

- Serialization layer: **pydantic v2** `BaseModel` for wire/IO types; stdlib `Enum` for
  closed value sets. A couple of lightweight value types use `@dataclass`.
- Timestamps: integer **milliseconds** (`ts_ms`) unless explicitly a float epoch second.
- IDs: `session_id`, `turn_id`, `seq` are stable correlation keys across subsystems.
- All emotion/persona scalars are floats; valence/arousal/dominance ∈ [-1, 1], the
  control scalars (warmth/uncertainty/pace/intensity) ∈ [0, 1].
- Every model is JSON round-trippable (`model_dump()` / `model_validate()`).

---

## 1. Audio domain

### 1.1 `AudioFrame`
A single chunk of PCM audio moving through capture → transport → edge.

| Field | Type | Meaning |
|---|---|---|
| `session_id` | str | Owning session. |
| `seq` | int | Monotonic frame index within the session. |
| `pcm` | list[float] | Float32 mono samples in [-1, 1]. (On the wire this is raw bytes; in-process it is float samples.) |
| `sample_rate` | int | Hz (e.g. 16000 capture, 24000 playback). |
| `ts_ms` | int | Capture/emit timestamp in ms. |
| `is_final` | bool | Marks the last frame of a stream/turn. |

> Mirrors the client `AudioFrame` skeleton in `final_use.md` §2 (`{ pcm, tsMs }`) and the
> 16 kHz/24 kHz sample rates used by `server/utils/audio.py`.

### 1.2 `CodecChunk`  (token-stream packet)
The bridge unit between audio and the speech-native runtime — the output of the Mimi
tokenizer and the input/output of Moshi.

| Field | Type | Meaning |
|---|---|---|
| `turn_id` | str | Turn this chunk belongs to. |
| `seq` | int | Chunk sequence number (ordering + backpressure). |
| `codec_tokens` | list[int] | Discrete Mimi/RVQ codec tokens. |
| `ts_ms` | int | Emit timestamp in ms. |
| `is_final` | bool | Last chunk of the turn's token stream. |
| `sample_rate` | int | Sample rate the tokens decode back to. |

> Matches `final_use.md` §5 `speech/codec/interfaces.py::CodecChunk` and the
> `speech/codec/token_stream.*` contract (sequencing, backpressure, cancellation).

---

## 2. Turn state & events

### 2.1 `TurnState` (enum)
Canonical conversational states. Values align with `server/pipeline/turn_state.py` and
`edge/session/turn_state.py` from the guide.

```
idle | listening | buffering | candidate_filler | forwarding |
thinking | speaking | barge_in | repairing | ended
```

### 2.2 `TurnEvent`
Emitted on every state transition (auditable; no hidden if-else sprawl).

| Field | Type | Meaning |
|---|---|---|
| `session_id` | str | Session. |
| `from_state` | TurnState | Previous state. |
| `to_state` | TurnState | New state. |
| `trigger` | str | What caused the transition. |
| `ts_ms` | int | Transition time in ms. |
| `metadata` | dict | Optional extra context. |

> Consistent with the `TurnEvent` dataclass already in `server/pipeline/turn_state.py`
> (which uses float epoch `timestamp`; the shared contract standardizes on `ts_ms`).

---

## 3. Emotion & persona

### 3.1 `EmotionState` (latent schema — Phase 9A)
Continuous affect latents, **not** brittle one-word tags. Superset of the V/A/D produced
by `server/pipeline/emotion.py` plus the persona control scalars from `final_use.md` §5.5.

| Field | Type | Range | Meaning |
|---|---|---|---|
| `valence` | float | [-1, 1] | Pleasure / positivity. |
| `arousal` | float | [-1, 1] | Activation / energy. |
| `dominance` | float | [-1, 1] | Control. |
| `warmth` | float | [0, 1] | Empathy / warmth. |
| `uncertainty` | float | [0, 1] | Hedging / low confidence. |
| `pace` | float | [0, 1] | Speaking-rate target (0 slow … 1 fast). |
| `intensity` | float | [0, 1] | Expressive intensity. |
| `label` | str \| None | — | Optional discrete tag for logging/debug. |
| `confidence` | float | [0, 1] | Confidence in the estimate. |

> The example latent in `final_use.md` §5.5 / §9 (`valence/arousal/dominance/warmth/
> uncertainty/intensity`) is a strict subset of this; `pace` is added per Phase 9A.

### 3.2 `PersonaState`
Identity-preserving conditioning attached to a turn (Phase 9B).

| Field | Type | Meaning |
|---|---|---|
| `persona_id` | str | Stable assistant identity. |
| `speaker_style_ref` | str \| None | Speaker-style embedding/reference id (consent-gated). |
| `emotion` | EmotionState | Target affect for this turn. |
| `language` | str | `en` \| `hi` \| `hinglish`. |

---

## 4. Routing & latency masking

### 4.1 `RouteDecision`
Output of the local/edge router and filler subsystem (Phase 3). Decides cached filler vs
full stack vs silent wait. Consistent with `final_use.md` §Phase-3 skeleton and the
`RoutingDecision` in `server/pipeline/filler.py`.

| Field | Type | Meaning |
|---|---|---|
| `route` | RouteTarget enum | `cached_filler` \| `full_stack` \| `silent_wait`. |
| `phrase_id` | str \| None | Cached phrase id when `route == cached_filler`. |
| `intent` | str | Detected intent (greeting, ack, complex, …). |
| `confidence` | float [0,1] | Routing confidence. |
| `reason` | str | Human-readable justification (auditable). |
| `emit_filler_then_forward` | bool | Latency-sponge: play filler AND forward to full stack. |

### 4.2 `FallbackDecision`
Failover orchestration between speech-native core and the classic baseline (Phase 13C).
Matches `final_use.md` §Phase-13 `aux/fallback/orchestrator.py::FallbackDecision`.

| Field | Type | Meaning |
|---|---|---|
| `use_fallback` | bool | Route to classic STT→LLM→TTS baseline. |
| `reason` | str | Why fallback was chosen (telemetry). |
| `expected_recovery_ms` | int \| None | Estimated time to recover the primary path. |

---

## 5. Speech runtime service interface

### 5.1 `SpeechRuntime` (Protocol — Phase 6)
The Moshi runtime exposed as a predictable streaming service.

```python
class SpeechRuntime(Protocol):
    async def stream_reply(
        self, session_id: str, chunks: AsyncIterator[CodecChunk]
    ) -> AsyncIterator[CodecChunk]: ...
    async def cancel(self, session_id: str, turn_id: str) -> None: ...
```

Contract:
- consumes **codec tokens + context state**, not text, as its primary interface,
- streams output incrementally (no full-sentence blocking),
- exposes clean **cancellation** and interruption-aware **repair** hooks,
- preserves continuity across turns (speaker state, recent emotion state).

> Matches `final_use.md` §Phase-6 `speech/moshi_runtime/service.py`.

### 5.2 `CodecBridge` (Protocol — Phase 5)
Mimi encode/decode roundtrip behind a stable interface (SNAC/DAC may sit behind it).

```python
class CodecBridge(Protocol):
    def encode(self, frames: Iterable[AudioFrame]) -> Iterable[CodecChunk]: ...
    def decode(self, chunks: Iterable[CodecChunk]) -> Iterable[AudioFrame]: ...
```

---

## 6. Memory

### 6.1 `MemoryWrite`
A write into the tiered memory subsystem (Phase 12). Matches `final_use.md` §Phase-12
`memory/contracts.py::MemoryWrite`.

| Field | Type | Meaning |
|---|---|---|
| `session_id` | str | Session. |
| `kind` | MemoryKind enum | `turn_summary` \| `preference` \| `profile` \| `tool_result`. |
| `content` | dict | Payload to persist. |
| `ts_ms` | int | Write time. |

### 6.2 `MemoryRead`
A bounded retrieval request/response pair.

**Query**

| Field | Type | Meaning |
|---|---|---|
| `session_id` | str | Session. |
| `query` | str | Natural-language or key query. |
| `kinds` | list[MemoryKind] | Restrict to these kinds. |
| `top_k` | int | Max items to return (bounded). |

**Result**

| Field | Type | Meaning |
|---|---|---|
| `session_id` | str | Session. |
| `items` | list[dict] | Retrieved records (each with a relevance score). |
| `latency_ms` | int | Retrieval latency for observability. |

---

## 7. Safety & consent

### 7.1 `VoiceRequest`
Consent-gated voice action request (Phase 11B). Matches `final_use.md`
`safety/voice_policy/contracts.py::VoiceRequest`.

| Field | Type | Meaning |
|---|---|---|
| `voice_ref_id` | str \| None | Reference voice id. |
| `consent_token` | str \| None | Proof of consent; required for non-default voices. |
| `requested_action` | VoiceAction enum | `style_transfer` \| `voice_clone` \| `persona_render`. |

### 7.2 `ModerationDecision`
Output of the moderation gate (Phase 11A).

| Field | Type | Meaning |
|---|---|---|
| `allowed` | bool | Whether the turn may proceed. |
| `category` | str \| None | Risk category if blocked (e.g. `self_harm`, `abuse`). |
| `escalate` | bool | Route to crisis/human review. |
| `reason` | str | Auditable justification. |

---

## 8. Implementation responsibilities (who implements what)

| Contract | Primary implementer | Notes |
|---|---|---|
| `AudioFrame` | `client/`, `edge/`, `server/` gateway | capture, transport, edge ingest |
| `CodecChunk` / `CodecBridge` | `speech/codec/` | Mimi bridge + token stream |
| `TurnState` / `TurnEvent` | `edge/session/` (+ `server/pipeline/turn_state.py` baseline) | explicit state machine |
| `EmotionState` / `PersonaState` | `speech/persona/`, `edge/emotion/` | continuous conditioning |
| `RouteDecision` | `client/router/`, `edge/planner/` | filler + speculation |
| `SpeechRuntime` | `speech/moshi_runtime/` | streaming + cancel + repair |
| `MemoryWrite` / `MemoryRead` | `memory/` | Redis/Postgres/Qdrant tiers |
| `VoiceRequest` / `ModerationDecision` | `safety/` | consent-first, auditable |
| `FallbackDecision` | `aux/fallback/` | classic baseline failover |

Any new cross-subsystem type **must** be added here first, then to `shared/contracts.py`,
then covered by `tests/test_contracts.py`.
