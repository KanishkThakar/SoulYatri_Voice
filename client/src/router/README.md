# client/router

Owner: client agent (final_use.md §4, §7.1, Phase 3).

Tiny local speech router + phrase-bank filler engine (sherpa-onnx-class). Emits the
RouteDecision contract (see docs/INTERFACES.md §4.1 and shared/contracts.py). Must be
fast, bounded, deterministic, and easy to disable.

Implemented modules:
- `phrase_schema.ts` — **3A** `PhraseRecord` schema + validation + searchable
  `PhraseBank` (safe-only by default).
- `phrase_bank.json` — **3A** seed phrases (en/hi/hinglish) + intent keyword tables.
- `intent_router.ts` — **3B** `IntentRouter` → `RouteDecision`; confidence thresholds;
  pluggable `SpeechRecognizer` with a lazy sherpa-onnx hook and deterministic keyword fallback.
- `filler_engine.ts` — **3C** `FillerEngine`: immediate / latency-sponge / handoff /
  disable switch / safe classes; deterministic + cancellable; never overrides complex turns.
- `index.ts` — barrel.

Design note: `client/src/README.md`.
