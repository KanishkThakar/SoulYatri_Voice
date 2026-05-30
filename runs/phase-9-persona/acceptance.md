# Acceptance — Phase 9: Emotion control, persona continuity, relationship state

**Task:** Implement Phase 9 (§9A/9B/9C) of `final_use.md` in `speech/persona/` —
emotion latent schema, persona controller with FiLM conditioning, and relationship memory.

**Environment:** Windows, Python 3.11.9, pydantic 2.13.4, ruff 0.15.10. CPU-only, no GPU,
no Moshi/Mimi/ECAPA/wav2vec2 weights. `structlog` and `numpy` are **not** installed locally
— the persona layer is written to import and test cleanly without them.

**File ownership (respected):** only files under `speech/persona/` (incl.
`speech/persona/tests/`) and this acceptance note were created/edited. `shared/`,
`docs/INTERFACES.md`, `pyproject.toml`, and `server/` were **not** modified. `EmotionState`
and `PersonaState` are imported from `shared.contracts` (not redefined).

## Files created

```text
speech/persona/__init__.py          # public API re-exports (overwrote scaffold docstring)
speech/persona/emotion_schema.py    # 9A — latent schema helpers (clamp/blend/serialize/attach)
speech/persona/controller.py        # 9B — PersonaController + film_conditioning + style fusion
speech/persona/relationship.py      # 9C — RelationshipStore + pluggable backend
speech/persona/logging_hooks.py     # structured logging hooks (structlog w/ stdlib fallback)
speech/persona/README.md            # design note + FiLM interface for decoder/runtime
speech/persona/tests/__init__.py
speech/persona/tests/test_emotion_schema.py   # 14 tests
speech/persona/tests/test_controller.py       # 13 tests
speech/persona/tests/test_relationship.py     # 12 tests
runs/phase-9-persona/acceptance.md  # this file
```

## Commands run

```text
# 1. Required import smoke test
python -c "import speech.persona.controller, speech.persona.emotion_schema, speech.persona.relationship"
→ persona imports OK            (exit 0)

# 2. Required test suite
python -m pytest speech/persona/tests -q
→ 39 passed in 0.35s            (exit 0)

# 3. Lint (repo CI parity)
python -m ruff check speech/persona
→ All checks passed!            (exit 0)

# 4. Format check (repo CI parity)
python -m ruff format --check speech/persona
→ 9 files already formatted     (exit 0)
```

## Definition of Done (final_use.md §3.3)
- [x] **code** — 9A emotion schema, 9B persona controller + FiLM hook, 9C relationship store.
- [x] **tests** — 39 pytest cases under `speech/persona/tests/` (see coverage below).
- [x] **short design note** — `speech/persona/README.md` (architecture + FiLM interface).
- [x] **structured logging hooks** — `logging_hooks.get_logger` (structlog → stdlib fallback);
      events: `emotion_clamped`, `emotion_attached_to_turn`, `persona_controller_init`,
      `persona_shaped`, `relationship_observed`, `relationship_adapted`, `relationship_reset`.
- [x] **acceptance result recorded** — this file under `runs/`.

## Phase 9 acceptance criteria (from final_use.md §9 table)

### 9A — emotion latent schema → *"controls serialize cleanly and can be attached to turn context"*
- `valence/arousal/dominance` (∈ [-1,1]) + `warmth/uncertainty/pace/intensity` (∈ [0,1])
  exposed via `EMOTION_FIELDS`, built on `shared.contracts.EmotionState`.
- `clamp_emotion`/`make_emotion` keep values in range (incl. NaN/inf coercion) — verified by
  `test_clamp_keeps_values_in_range`, `test_clamp_handles_nan_and_inf`.
- Clean serialization: dict/json round-trips — `test_dict_roundtrip`,
  `test_json_roundtrip_stable_keys`.
- Attach-to-turn-context (non-mutating) + recover — `test_attach_to_turn_context_is_nonmutating`.

### 9B — persona controller → *"output varies in emotion while preserving identity"*
- `test_identity_preserved_across_varying_emotions`: 3 turns with different emotions keep
  identical `persona_id`/`speaker_style_ref`/`language` while `valence` takes 3 distinct values.
- `test_shape_ignores_base_identity_fields`: even a foreign base persona cannot override the
  controller's stable identity.
- Speaker-style embedding fusion is deterministic & identity-stable —
  `test_style_embedding_deterministic_and_identity_stable`, `test_fuse_style_mixes_identity_and_affect`.
- **FiLM conditioning determinism**: `test_film_conditioning_is_deterministic` (identical
  emotion → equal `FiLMParams`), plus `test_film_varies_with_emotion`, `test_film_controls_in_range`,
  `test_conditioning_via_controller_matches_pure_function`.

### 9C — relationship memory → *"future turns adapt audibly to prior interaction style"*
- `test_future_turns_adapt_toward_learned_tone`: after repeated warm/positive user turns, a
  neutral target emotion is pulled warmer/more-positive.
- `test_stress_triggers_calming_adaptation`: sustained high arousal → adapted output is calmer
  (lower arousal) and warmer (de-escalation).
- EMA learning + bounded buffers — `test_response_length_ema_moves_toward_observations`,
  `test_tone_preference_ema_across_turns`, `test_trajectory_and_context_are_bounded`.
- Pluggable backend interface — `test_pluggable_backend_interface`, `test_custom_backend_is_used`.

## CPU/no-weights guard
`test_no_heavy_imports` asserts `torch`/`transformers`/`moshi`/`mimi`/`numpy` are never
imported by the persona layer. Heavy speaker/emotion models stay behind Protocol interfaces
(`StyleEmbeddingProvider`, `RelationshipBackend`) with deterministic fallbacks.

## Notes for downstream teams

**Decoder team (Phase 10) / runtime team (Phase 6):**
- Consume conditioning via `from speech.persona import film_conditioning` →
  `film_conditioning(persona_state.emotion, dim=<decoder_feature_dim>) -> FiLMParams`.
- `FiLMParams` is frozen + value-equal and **deterministic** (same emotion → identical
  params), so it is safe to memoize/cache per emotion.
- Apply as `y = gamma * x + beta` per feature channel (`len(gamma) == len(beta) == dim`,
  default `FILM_FEATURE_DIM = 8`). For a non-FiLM vocoder, use `params.controls`
  (`rate`/`pitch`/`energy`/`warmth`/`uncertainty`/`assertiveness`, all ∈ [0,1]).
- `FiLMParams.as_dict()` is JSON-safe and maps onto the `DecoderRequest.emotion_state` /
  `persona_state` payload sketched in `final_use.md` §10.
- Input emotion is clamped defensively inside `film_conditioning`, so the decode path will
  not crash on out-of-range affect.

**Edge emotion encoder team (Phase 4):**
- Feed detected user affect into `RelationshipStore.observe_turn(session_id, user_emotion=…)`
  and shape the reply target with `RelationshipStore.adapt_emotion(session_id, target)` before
  handing the `PersonaState` to the runtime.
- `attach_to_turn_context(ctx, emotion)` returns a new dict carrying the serialized emotion
  under the `"emotion"` key for passing affect alongside `turn_id`/`session_id`.

**Memory team (Phase 12):**
- `RelationshipStore` accepts any `RelationshipBackend` (get/put/clear). The default is
  in-memory; a Redis (hot) / Postgres (durable) backend can be injected without touching
  the persona controller or callers.
