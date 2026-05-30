# speech/persona — Emotion control, persona continuity & relationship state (Phase 9)

> Owner: speech/runtime agent. Implements **Phase 9** of `final_use.md` (§9A/9B/9C).
> Builds on the shared contracts `EmotionState` and `PersonaState` from
> [`shared/contracts.py`](../../shared/contracts.py) — it does **not** redefine them.

## Intent

Make the assistant sound like a **stable character with adaptive delivery**: emotion is
continuous conditioning (not brittle one-word tags), the persona identity stays the same
across turns, and the system learns each user's interaction style over time.

## Architecture at a glance

```text
user affect (edge emotion encoder)  ┐
                                    ├─► RelationshipStore.observe_turn(...)  (9C)
turn outcome (length, tone)         ┘            │ learns tone/length/stress
                                                 ▼
target EmotionState ──► RelationshipStore.adapt_emotion(...) (9C)  ──► adapted EmotionState
                                                 │
                                                 ▼
                          PersonaController.shape(emotion) (9B)
                          • stable persona_id + speaker_style_ref (identity)
                          • varying EmotionState (affect)
                                                 │
                                                 ▼
                          PersonaController.conditioning(...) ──► FiLMParams (9B)
                          film_conditioning(EmotionState) = pure fn
                                                 │
                                                 ▼
                          downstream Fast Acoustic Decoder / Moshi runtime (Phase 10/6)
```

## Modules

### 9A — `emotion_schema.py` (latent schema helpers)
Thin helper layer over `shared.contracts.EmotionState`.

- **Field taxonomy**: `BIPOLAR_FIELDS` (`valence/arousal/dominance` ∈ [-1, 1]) and
  `UNIPOLAR_FIELDS` (`warmth/uncertainty/pace/intensity/confidence` ∈ [0, 1]). Consistent
  with the V/A/D representation in `server/pipeline/emotion.py`.
- **Validation / clamping**: `clamp_emotion` / `make_emotion` squeeze arbitrary numbers
  (including NaN/inf) into valid ranges instead of raising — useful when fusing raw model
  outputs. Out-of-range corrections are logged (`emotion_clamped`).
- **Pure transforms**: `blend(a, b, weight)` (lerp), `nudge(state, **deltas)` (additive).
- **Serialization**: `to_dict` / `from_dict` / `to_json` / `from_json` (stable key order).
- **Turn context**: `attach_to_turn_context(ctx, emotion)` returns a *new* dict carrying
  the serialized emotion under the `"emotion"` key; `emotion_from_turn_context` recovers it.

### 9B — `controller.py` (persona controller + FiLM hook)
- **Identity vs affect split**: identity = `persona_id` + `speaker_style_ref` (stable);
  affect = `EmotionState` (varies per turn). `PersonaController.shape(...)` never changes
  identity while shaping emotion → same assistant character, adaptive delivery.
- **Speaker-style embedding fusion**: `StyleEmbeddingProvider` Protocol + deterministic
  `HashStyleEmbeddingProvider` fallback (no ECAPA weights needed on CPU). `fuse_style`
  mixes a stable identity embedding with a per-turn emotion embedding.
- **FiLM conditioning hook**: `film_conditioning(emotion) -> FiLMParams` is a **pure,
  deterministic** function (`EmotionState → gamma/beta/controls`). See the interface note
  below.

### 9C — `relationship.py` (relationship memory store)
Per-session relational state, distinct from durable Phase-12 `memory/`.

- `RelationshipProfile`: `tone_preference` (EMA EmotionState), `preferred_response_length`
  (EMA), `calm_stress_trajectory` (bounded arousal ring buffer), `recent_emotional_context`
  (bounded EmotionState ring buffer), `turns`, `stress_level()`.
- `RelationshipStore.observe_turn(...)` updates the profile each interaction;
  `adapt_emotion(target)` biases a target emotion toward the learned tone and applies a
  **stress de-escalation** nudge (calmer/warmer) when recent arousal is high.
- **Pluggable backend**: `RelationshipBackend` Protocol + `InMemoryRelationshipBackend`
  default (thread-safe). A Redis/Postgres backend (Phase 12) drops in without changing
  callers.

## FiLM conditioning interface (for decoder / runtime teams)

`film_conditioning(emotion: EmotionState, *, dim=FILM_FEATURE_DIM) -> FiLMParams`

`FiLMParams` is a frozen, value-equal dataclass:

| Field | Type | Meaning |
|---|---|---|
| `gamma` | `tuple[float, …]` (len `dim`, default 8) | Per-channel **scale**, centered ~1.0. Driven by `intensity` + `arousal`. Apply as `y = gamma * x + beta`. |
| `beta` | `tuple[float, …]` (len `dim`) | Per-channel **shift**. Driven by `valence` + `warmth`. |
| `controls` | `dict[str, float]` | Named delivery knobs in [0, 1] for non-FiLM consumers: `rate`, `pitch`, `energy`, `warmth`, `uncertainty`, `assertiveness`. |

Guarantees:
- **Deterministic & pure**: identical `EmotionState` → byte-identical `FiLMParams`
  (asserted by tests). Safe to cache/memoize.
- **Defensive**: input emotion is clamped before mapping, so out-of-range inputs never
  crash the decode path.
- **Stable shape**: `dim` defaults to `FILM_FEATURE_DIM = 8`; pass `dim=` to match the
  decoder's feature width. `gamma`/`beta` always have length `dim`.
- `FiLMParams.as_dict()` gives a JSON-safe payload to cross the decoder service boundary
  (see the `DecoderRequest.persona_state/emotion_state` skeleton in `final_use.md` §10).

Recommended consumption in the decoder:
```python
from speech.persona import film_conditioning
params = film_conditioning(persona_state.emotion, dim=decoder_feature_dim)
features = features * tensor(params.gamma) + tensor(params.beta)   # FiLM modulation
# or use params.controls["rate"/"pitch"/"energy"] for a non-FiLM vocoder
```

## CPU / no-weights stance (DECISIONS.md D-008)
No top-level `torch` / `transformers` / `moshi` / `mimi` / `numpy` imports. Heavy speaker /
emotion models live behind Protocol interfaces with deterministic fallbacks, so the whole
package imports and tests run on a CPU-only machine with no model weights. A test asserts
none of those heavy modules get pulled in.

## Logging hooks
`logging_hooks.get_logger(__name__)` returns a `structlog` bound logger when available and
otherwise a stdlib-backed adapter exposing the same `log.info("event", key=value)` shape.
Emitted events: `emotion_clamped`, `emotion_attached_to_turn`, `persona_controller_init`,
`persona_shaped`, `relationship_observed`, `relationship_adapted`, `relationship_reset`.

## Tests
`speech/persona/tests/` (run `python -m pytest speech/persona/tests -q`):
- `test_emotion_schema.py` — clamping (incl. NaN/inf), blend/nudge, dict/json round-trips,
  turn-context attach/recover.
- `test_controller.py` — identity preserved while emotion varies, deterministic style
  fusion, **FiLM conditioning determinism** + range checks.
- `test_relationship.py` — EMA tone/length learning, bounded trajectories, **adaptation
  across turns**, stress de-escalation, pluggable backend.
