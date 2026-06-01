# Acceptance — Phases 2 & 3 (Client Audio + Transport + Local Router/Filler)

Scope: `final_use.md` Phase 2 (client capture, transport, playback) and Phase 3
(local speech router + phrase-bank filler subsystem). Owner: client & transport
deep-dive agent. CPU-only environment.

## Definition of done (final_use.md §3.3)

| Requirement | Status | Evidence |
|---|---|---|
| Code | ✅ | TS modules under `client/src/audio`, `client/src/playback`, `client/src/router`; Python `edge/webrtc_gateway/gateway.py` |
| Tests | ✅ | 23 pytest (gateway) + 28 TS unit tests, all passing |
| Design note / README | ✅ | `client/src/README.md`, `edge/webrtc_gateway/README.md` |
| Structured logging | ✅ | pluggable loggers in every module (events listed in the READMEs) |
| Acceptance recorded | ✅ | this file |

## Files created

### Phase 2 — client audio (TypeScript)
- `client/src/audio/types.ts` — `AudioFrame` + PCM16/float32/wire converters + linear resampler (DOM-free)
- `client/src/audio/capture.ts` — **2A** mic capture, AEC/NS/AGC constraints, device select + permissions, AudioWorklet (ScriptProcessor fallback), clip detection, target sample rate
- `client/src/audio/webrtc.ts` — **2B** `RealtimeTransportClient` (reconnect + backoff + outbound buffering + session metadata), `Transport` abstraction with `WebSocketTransport` / `LoopbackTransport`
- `client/src/playback/stream_player.ts` — **2C** gapless streaming playback, inbound jitter reorder, `fadeOut()` + `hardStop()` cancel
- barrels: `client/src/audio/index.ts`, `client/src/playback/index.ts`

### Phase 2B — transport gateway (Python, server side)
- `edge/webrtc_gateway/gateway.py` — `TransportGateway` / `InMemoryTransportGateway`, `GatewaySession`, `JitterBuffer`, `SessionMetadata`, `ConnectionState`, `probe_webrtc_backend()` (lazy aiortc/livekit)
- `edge/webrtc_gateway/tests/__init__.py`, `edge/webrtc_gateway/tests/test_gateway.py`

### Phase 3 — local router + filler (TypeScript)
- `client/src/router/phrase_schema.ts` — **3A** `PhraseRecord` schema, validation, searchable `PhraseBank` (safe-only by default)
- `client/src/router/phrase_bank.json` — **3A** seed phrases (en/hi/hinglish) + intent keyword tables
- `client/src/router/intent_router.ts` — **3B** `IntentRouter` → `RouteDecision`, confidence thresholds, sherpa-onnx lazy hook + keyword fallback
- `client/src/router/filler_engine.ts` — **3C** `FillerEngine` (immediate / latency-sponge / handoff / disable / safe classes; deterministic + cancellable; never overrides complex turns)
- barrel: `client/src/router/index.ts`

### Tests + tooling (TypeScript)
- `client/src/audio/types.test.ts`, `client/src/router/phrase_schema.test.ts`,
  `client/src/router/intent_router.test.ts`, `client/src/router/filler_engine.test.ts`
- `client/tsconfig.typecheck.json` — self-contained type-check config for the new modules

### Docs
- `client/src/README.md`, `edge/webrtc_gateway/README.md`

## Acceptance checks per micro-phase

| Micro-phase | Acceptance criterion | Met by |
|---|---|---|
| 2A | speech reaches transport at expected sample rate, no major clipping | `capture.ts` target-rate resample + clip detection; `types.test.ts` PCM round-trip/clamp/resample |
| 2B | audio survives reconnects and moderate jitter | gateway reconnect-survival tests; client outbound buffering + resume handshake |
| 2C | assistant audio begins quickly, stops cleanly on cancel | `stream_player.ts` first-chunk scheduling + `fadeOut`/`hardStop` |
| 3A | phrase records validate and are searchable | `phrase_schema.test.ts` (validation, dedupe, search, safety filter) |
| 3B | greetings/acks route to cached paths, low false positives | `intent_router.test.ts` (cached routing + low-confidence escalation + determinism) |
| 3C | filler deterministic, cancellable, does not override complex turns | `filler_engine.test.ts` (deterministic plan, disable, cancel, sponge handoff fades, no-override) |

## Verification output

Commands run from repo root (`c:\Users\mpstme.student\Downloads\SoulYatri_Voice`).

### 1. Python gateway import
```
$ python -c "import edge.webrtc_gateway.gateway"
import ok
```

### 2. Python gateway tests
```
$ python -m pytest edge/webrtc_gateway/tests -q
23 passed in 0.25s
```

### 3. Full repo suite (no regressions)
```
$ python -m pytest -q
... 408 passed  (all green)
```

### 4. Ruff lint (gateway)
```
$ python -m ruff check edge/webrtc_gateway/
All checks passed!
```

### 5. TypeScript — type-check + unit tests
`client/node_modules` is **not** installed, so the project's own `tsc`/`next`
cannot run until `npm install` (in `client/`). Verification used on-demand tools
via `npx` (Node v20.20.0):

```
# type-check new production modules (DOM lib, no project deps)
$ npx -y -p typescript@5.6.3 tsc -p tsconfig.typecheck.json   # (run in client/)
TS_EXIT=0   # clean

# run unit tests (transpile-on-the-fly + node:test)
$ npx -y tsx --test src/audio/types.test.ts src/router/phrase_schema.test.ts \
    src/router/intent_router.test.ts src/router/filler_engine.test.ts
# tests 28 / pass 28 / fail 0
```

> **npm install required for the full client toolchain.** Once `npm install` is
> run in `client/`, `npx tsc --noEmit` (project tsconfig) and a configured test
> runner cover these files directly. The new modules are written to be
> compatible with the existing strict Next.js tsconfig.

## Notes for the edge team
- `edge/webrtc_gateway/gateway.py` is the server-side counterpart to the client
  transport. It is intentionally media-library-free: wire a real `aiortc`/LiveKit
  backend by decoding Opus → PCM and calling `TransportGateway.ingest(AudioFrame)`;
  call `disconnect()`/`reconnect()` on transport lifecycle events.
- `probe_webrtc_backend()` reports whether `aiortc`/`livekit` is installed and
  falls back to `InMemoryTransportGateway` for bring-up/tests. Keep heavy media
  deps optional and lazy (CPU-only rule).
- The gateway emits `seq`-ordered, de-duplicated frames; downstream turn
  detection / feature extraction (Phase 4) can assume monotonic ordering per
  session and use `reconnect_count` / `frames_dropped` for observability.
- Session TTL sweep (`sweep_expired`) is available but not wired to a timer here;
  the edge session manager should schedule it.

## Notes for the safety team
- Filler playback is **safe-by-construction**: `PhraseBank.search` returns only
  `safetyTag == "safe"` phrases by default, and `FillerEngine` re-checks the tag
  before playing — `needs_review` / `blocked` phrases are never auto-played.
- The filler subsystem is bounded and cannot take over reasoning: complex turns
  always escalate to `full_stack`, and a latency-sponge filler is faded out by
  `handoffToMain()` so the real answer is never suppressed (final_use.md §2.3).
- A global disable switch (`FillerEngine.setEnabled(false)`) turns the latency
  layer into a no-op, useful for incident response.
- `phrase_bank.json` ships a `safetyTag` per record and supports `needs_review` /
  `blocked` states for a future moderation/review workflow; the seed bank is all
  `safe`. Consent/voice-cloning policy (Phase 11) is out of scope here — these are
  fixed, pre-approved phrases, not generated or cloned voices.
- `IntentRouter` carries an `emotion` input and routes distress to an empathy
  filler **plus** full-stack escalation, never filler-only, so sensitive turns
  always reach the main runtime.
