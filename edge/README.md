# edge/ — Edge Runtime (Phases 4 & 8)

Low-latency conversational interpretation close to the user. This README is the design
note (final_use.md §3.3 "definition of done") for the **Phase 4** feature-extraction /
turn-state / barge-in work and the **Phase 8** response-planning / speculation /
perceived-latency work.

All edge code imports the canonical contracts from `shared.contracts`
(`TurnState`, `TurnEvent`, `EmotionState`, `RouteDecision`, `RouteTarget`) and runs on a
**CPU-only machine with no model weights** — heavy models (Silero VAD, wav2vec2 SER,
ECAPA-TDNN) are lazy-loaded behind capability checks with deterministic fallbacks
(DECISIONS.md D-008).

## Module map

| Phase | Module | Responsibility |
|---|---|---|
| 4A | `turn_detection/features.py` | Streaming per-frame speech features: VAD + speaker embedding + emotion + timestamps + speech start/end markers. Generator-based — never buffers a full utterance. |
| 4A/4B | `turn_detection/detector.py` | Streaming turn-end / endpointing detector (VAD-driven, hangover-based). Emits speech-start / speech-end / turn-end-candidate / turn-end-confirmed markers that map 1:1 onto turn-state transitions. Lazy Silero + energy fallback; suppresses turn-ends from sub-`min_speech_ms` blips. |
| 4A | `emotion/extractor.py` | Lazy wav2vec2-class SER provider → `EmotionState`. Deterministic signal-based fallback (RMS + ZCR → continuous V/A/D + persona scalars). |
| 4A | `speaker/encoder.py` | Lazy ECAPA-TDNN speaker embedding provider. Deterministic L2-normalized fallback embedding for same-speaker continuity. |
| 4B | `session/turn_state.py` | Explicit turn-state machine over the canonical `TurnState`. Single transition table, explicit guards/timeouts, emits `TurnEvent`; every event → valid transition **or** explicit `TransitionRejected`. |
| 4C | `barge_in/detector.py` | Detects user speech over the AI; emits cancel/repair `BargeInEvent`s with timing metrics and bounded false positives (consecutive-frame debounce + hysteresis decay + cooldown). |
| 8A | `planner/short_turn.py` | Classifies trivial/short/emotional/uncertain/complex turns and produces a `RouteDecision` with route confidence. |
| 8B | `planner/speculation.py` | Speculative onset controller: start a safe, cancellable onset early; commit/cancel based on later evidence (`reconcile`). Wrong-speculation rate is tracked. |
| 8C | `planner/handoff.py` | Onset/handoff policy: filler → real output takeover, duplicate suppression, smooth crossfade — no double responses. |
| — | `session/logging_hooks.py` | Structured logging hook. Uses `structlog` when present; falls back to a stdlib `key=value` adapter so edge code stays dependency-light on CPU. |

## Design decisions

**Explicit state machine, no if-else sprawl (4B).** `VALID_TRANSITIONS` is the single
source of truth. `transition()` raises `InvalidTransitionError`; `try_transition()`
returns either a `TurnEvent` or a `TransitionRejected` — making the
"valid-transition-or-explicit-rejection" rule *total* (a test exhaustively checks all
state × state pairs). Timeouts use an **injectable clock** and a poll-based
`check_timeout()` so no event loop is needed and behavior is deterministic in tests. The
machine standardizes on the shared lowercase `TurnState` and `TurnEvent` (with `ts_ms`),
keeping edge events wire-compatible with `server/pipeline/turn_state.py`.

**Streaming features (4A).** `StreamingFeatureExtractor.stream()` is a generator that
yields one `SpeechFeatures` per input frame, proving features stream without waiting for
a full utterance. Speech start/end use hysteresis (`start_frames` / `end_frames`) to
debounce. Heavy speaker/emotion features are computed only while speech is active and
emotion on a cadence, so the per-frame VAD/marker path stays cheap.

**Streaming endpointing, no full-utterance blocking (4A/4B).** `EndpointingDetector`
turns a VAD probability stream into explicit turn-end markers. It debounces with two
hysteresis windows (`start_frames` onset, `end_frames` offset) and a trailing-silence
**hangover** (`hangover_ms`): a `turn_end_candidate` is raised the moment trailing
silence begins (so a filler can pre-warm) and a `turn_end_confirmed` fires only once the
silence holds for the hangover. A `min_speech_ms` floor suppresses turn-ends from a
single cough/blip. The boolean edge flags are non-sticky so a consumer maps them 1:1 onto
`TurnStateMachine` events (`speech_started → listening`, `speech_ended → buffering`,
`turn_end_confirmed → candidate_filler`). It shares the same lazy Silero/energy
`VADProvider` as the feature extractor (`process_probability` reuses an existing VAD
score), so endpointing adds no extra model cost.

**Bounded false positives (4C).** A barge-in requires `min_speech_duration_ms` of
*consecutive* speech frames; isolated frames decay (hysteresis) instead of accumulating;
a cooldown blocks rapid re-triggers. `BargeInMetrics` exposes `false_positive_rate` and
`mean_detection_latency_ms` for observability and tuning.

**Speculation is subordinate and recoverable (8B).** We only speculate above a
confidence gate and only in a *safe* mode set (`filler`, `empathetic_filler`,
`short_answer`). Each speculation can be committed or cancelled exactly once;
`reconcile(final_route)` commits when compatible and cancels otherwise. `wrong_rate`
(cancelled / started) makes "wrong speculation is rare" measurable.

**No double responses (8C).** `HandoffController` tracks what was already spoken and
strips a duplicated leading filler from the real output (punctuation/case-insensitive,
word-aligned). If the real output is fully contained in the filler it is suppressed
(`suppress_main`); otherwise it hard-stops or crossfades the filler into the deduped
main output.

## Structured logging hooks

Every module logs structured events via `edge.session.logging_hooks.get_logger`:
`turn_transition`, `transition_rejected`, `turn_state_timeout`, `speech_started`,
`speech_ended`, `barge_in_detected`, `barge_in_false_positive`, `short_turn_classified`,
`speculation_started/committed/cancelled`, `filler_started`, `handoff_*`. These render as
JSON under structlog (server parity) or `key=value` lines under the stdlib fallback.

## Running

```bash
# import check (must succeed on CPU with no weights)
python -c "import edge.session.turn_state, edge.barge_in.detector, edge.planner.speculation, edge.turn_detection.features, edge.turn_detection.detector"

# tests
python -m pytest edge/tests -q
```

Acceptance results: `runs/phase-4-8-edge/acceptance.md`.

## Notes for adjacent teams

- **Client / router team:** `planner/short_turn.py` consumes a partial transcript +
  `asr_confidence` (your tiny sherpa-onnx/KWS output) and an optional `EmotionState`, and
  returns a `RouteDecision` consistent with `client/router/`. `cached_filler` decisions
  carry a `phrase_id` (`greeting_default` / `acknowledgement_default`) you can map to the
  Phase-3 phrase bank. `emit_filler_then_forward=True` is the latency-sponge signal.
- **Speech / runtime team:** `BargeInEvent.cancel` maps to `SpeechRuntime.cancel(...)`;
  `BargeInEvent.repair` should drive the turn machine into `barge_in → repairing`.
  `SpeculationController.reconcile()` should be called with the runtime's final route so a
  speculative onset is committed or cancelled before/at first real audio.
- **Client / speech teams (turn-end events):** `turn_detection/detector.py` emits, per
  frame, `speech_started` / `speech_ended` / `turn_end_candidate` / `turn_end_confirmed`.
  Treat `turn_end_candidate` as the cue to pre-warm a filler (still cancellable if speech
  resumes) and `turn_end_confirmed` as the authoritative end-of-turn that forwards the
  turn to the full stack. The markers are designed to be fed straight into the
  `TurnStateMachine` convenience methods (`on_speech_start`, `on_speech_end`,
  `on_turn_confirmed`) with no extra glue.
