# Acceptance — Edge Phases 4 & 8

**Scope:** Edge feature extraction + turn detection + state machine (Phase 4) and
response planning + speculation + perceived-latency control (Phase 8).
**Environment:** Windows, Python 3.11.9, CPU-only, no GPU / no model weights.
`numpy`, `torch`, `transformers`, `structlog` are **not** installed — all heavy models
are lazy-loaded with deterministic fallbacks, so everything imports and tests on CPU.

## Files created

Phase 4
- `edge/turn_detection/features.py` — streaming per-frame features (VAD + speaker +
  emotion + timestamps + speech start/end markers); generator-based, no full-utterance
  buffering. Includes `VADProvider` (lazy Silero + energy/ZCR fallback).
- `edge/turn_detection/detector.py` — streaming `EndpointingDetector` (VAD-driven,
  hangover-based) emitting per-frame `speech_started` / `speech_ended` /
  `turn_end_candidate` / `turn_end_confirmed` markers that map 1:1 onto the turn-state
  machine; `min_speech_ms` floor suppresses turn-ends from a single blip/cough. Shares
  the lazy Silero/energy `VADProvider`, so endpointing adds no extra model cost.
- `edge/emotion/extractor.py` — `EmotionExtractor`, lazy wav2vec2-class SER → `EmotionState`
  with a deterministic signal-based fallback (consistent label space + V/A/D with
  `server/pipeline/emotion.py`).
- `edge/speaker/encoder.py` — `SpeakerEncoder`, lazy ECAPA-TDNN with a deterministic
  L2-normalized fallback embedding + `cosine_similarity` helper.
- `edge/session/turn_state.py` — explicit `TurnStateMachine` over canonical `TurnState`;
  single transition table, guards/timeouts (injectable clock), emits `TurnEvent`, returns
  explicit `TransitionRejected` for invalid events.
- `edge/barge_in/detector.py` — `BargeInDetector` emitting cancel/repair `BargeInEvent`s
  with `BargeInMetrics` (timing + bounded false positives).
- `edge/session/logging_hooks.py` — structured logging hook (structlog or stdlib fallback).

Phase 8 (`edge/planner/`, new subfolder + `__init__.py`)
- `edge/planner/short_turn.py` — `ShortTurnClassifier` → `RouteDecision` (trivial / short /
  emotional / uncertain / complex) with route confidence.
- `edge/planner/speculation.py` — `SpeculationController` (start / commit / cancel /
  reconcile) with `SpeculationMetrics.wrong_rate`.
- `edge/planner/handoff.py` — `HandoffController` onset/handoff policy with duplicate
  suppression (no double responses).

Tests (`edge/tests/`, new)
- `test_turn_state.py` (15), `test_barge_in.py` (10), `test_features.py` (14),
  `test_turn_detection.py` (11), `test_short_turn.py` (13), `test_speculation.py` (14),
  `test_handoff.py` (14) — 91 tests total for the Phase 4 + Phase 8 edge work.

Docs
- `edge/README.md` — design note + structured-logging hook inventory + team notes.
- `runs/phase-4-8-edge/acceptance.md` — this file.

## Verification

**Environment confirmed:** Windows, Python 3.11.x, CPU-only. Heavy deps (`torch`,
`transformers`, `speechbrain`, `silero`) are not required at import time — every model is
lazy-loaded behind a capability check with a deterministic fallback (DECISIONS.md D-008).

Import check (required) — both the package and every Phase 4/8 submodule import cleanly:

```
$ python -c "import edge"
import edge OK

$ python -c "import edge.session.turn_state, edge.barge_in.detector, edge.planner.speculation, edge.planner.short_turn, edge.planner.handoff, edge.turn_detection.features, edge.turn_detection.detector, edge.emotion.extractor, edge.speaker.encoder, edge.session.logging_hooks"
all edge submodules import OK
```

Test run (required):

```
$ python -m pytest edge -q
........................................................................ [ 63%]
..........................................                               [100%]
114 passed in 0.48s
```

(91 tests cover the Phase 4 + Phase 8 edge modules under `edge/tests/`; the remaining 23
are the pre-existing `edge/webrtc_gateway/tests/` suite, run together for a clean
whole-folder pass.)

Lint (repo quality gate):

```
$ python -m ruff check edge
All checks passed!
```

## Acceptance criteria mapping (final_use.md §6 Phase 4 / Phase 8)

| Criterion | Where verified | Result |
|---|---|---|
| 4A features stream without waiting for full utterances | `test_features.py::test_stream_is_lazy_generator`, `test_speech_start_and_end_markers` | PASS |
| 4A emotion provider emits `EmotionState` (fallback, CPU) | `test_features.py::test_emotion_extractor_emits_emotion_state` | PASS |
| 4A streaming endpointing markers (start/end, no full-utterance block) | `test_turn_detection.py::test_stream_is_lazy_generator`, `test_speech_start_marker_fires_once`, `test_turn_end_candidate_then_confirmed_on_synthetic_audio` | PASS |
| 4A/4B endpointing markers drive the turn-state machine | `test_turn_detection.py::test_endpointing_drives_turn_state_machine` | PASS |
| 4A/4C blip below `min_speech_ms` never confirms a turn end | `test_turn_detection.py::test_isolated_blip_never_confirms_turn_end`, `test_short_silence_does_not_confirm_turn_end` | PASS |
| 4B every event → valid transition OR explicit rejection | `test_turn_state.py::test_every_event_is_valid_transition_or_explicit_rejection` | PASS |
| 4B invalid transition rejected (no state change) | `test_turn_state.py::test_invalid_transition_raises`, `test_try_transition_returns_explicit_rejection_not_exception` | PASS |
| 4B guards/timeouts fire safely | `test_turn_state.py::test_timeout_triggers_recovery_with_fake_clock`, `test_barge_in_timeout_recovers_to_repairing` | PASS |
| 4C interruption fires reliably with timing | `test_barge_in.py::test_barge_in_fires_after_min_consecutive_frames`, `test_detection_latency_is_measured` | PASS |
| 4C bounded false positives | `test_barge_in.py::test_isolated_noise_does_not_trigger_false_positive`, `test_false_positive_rate_bound_under_clean_input`, `test_cooldown_prevents_rapid_double_detection` | PASS |
| 8A short-turn routing with confidence | `test_short_turn.py` (greeting/ack/emotional/short/complex/uncertain cases) | PASS |
| 8B wrong speculation rare + recoverable | `test_speculation.py::test_cancel_marks_cancelled_and_recoverable`, `test_reconcile_cancels_on_conflicting_route`, `test_wrong_rate_metric_tracks_cancellations` | PASS |
| 8C smooth onset, no awkward double responses | `test_handoff.py::test_main_fully_duplicated_is_suppressed`, `test_no_duplicate_content_in_spoken_text`, `test_filler_then_main_stops_filler` | PASS |

## Definition-of-done checklist (final_use.md §3.3)

- [x] code (Phase 4A/4B/4C, Phase 8A/8B/8C)
- [x] tests (`edge/tests/`, 91 passing; 114 with the gateway suite)
- [x] short design note / README (`edge/README.md`)
- [x] structured logging hooks (`edge/session/logging_hooks.py` + structured events across modules)
- [x] explicit acceptance result recorded in `runs/` (this file)

## File-ownership compliance

Only files under `edge/turn_detection/`, `edge/emotion/`, `edge/speaker/`,
`edge/barge_in/`, `edge/session/`, `edge/planner/` (new), `edge/tests/` (new) and
`runs/phase-4-8-edge/acceptance.md` were created/edited. No changes to `shared/`,
`docs/INTERFACES.md`, `pyproject.toml`, `server/`, `client/`, or `edge/webrtc_gateway/`.

## Notes for adjacent teams

- **Client / router team:** `ShortTurnClassifier.classify(transcript, asr_confidence=,
  emotion=, speech_duration_ms=)` returns a `shared.contracts.RouteDecision`. Cached-filler
  decisions carry `phrase_id` (`greeting_default` / `acknowledgement_default`) to map onto
  the Phase-3 phrase bank; `emit_filler_then_forward=True` is the latency-sponge signal.
- **Speech / runtime team:** wire `BargeInEvent.cancel` → `SpeechRuntime.cancel(...)`, and
  `BargeInEvent.repair` → turn machine `barge_in → repairing`. Call
  `SpeculationController.reconcile(final_route)` with the runtime's final `RouteDecision`
  so any early onset is committed or cancelled at/just before first real audio.
- **Speech team (turn state):** edge `TurnStateMachine` standardizes on the shared
  lowercase `TurnState` + `TurnEvent(ts_ms=...)`; events are wire-compatible with
  `server/pipeline/turn_state.py` (which uses float `timestamp`). If unifying, prefer the
  shared `ts_ms` contract.
