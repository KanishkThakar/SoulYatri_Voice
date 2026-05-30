# SoulYatri Client — Audio, Transport, Playback & Router (Phases 2–3)

Design note for the client-side speech I/O loop. Implements `final_use.md`
Phase 2 (capture → transport → playback) and Phase 3 (local router + filler).
All modules are framework-agnostic TypeScript that the Next.js app under
`src/app` / `src/components` / `src/hooks` can import without breaking the
existing `useVoiceStream.ts` bring-up path.

## Module map

```
src/
  audio/
    types.ts          AudioFrame + PCM16/float32/wire converters + resampler (DOM-free)
    capture.ts        2A — mic PCM capture, AEC/NS/AGC, device select, AudioWorklet
    webrtc.ts         2B — reconnect-survivable realtime transport (WS/WebRTC/loopback)
    index.ts          barrel
  playback/
    stream_player.ts  2C — gapless streaming playback, fadeout + hard-stop cancel
    index.ts          barrel
  router/
    phrase_schema.ts  3A — phrase metadata schema, validation, searchable PhraseBank
    phrase_bank.json  3A — seed phrases (en/hi/hinglish) + intent keyword tables
    intent_router.ts  3B — local route classifier → RouteDecision (+ sherpa-onnx hook)
    filler_engine.ts  3C — bounded, cancellable filler policy with safe handoff
    index.ts          barrel
```

## Contract alignment

The TS types mirror `shared/contracts.py` / `docs/INTERFACES.md`:

| TS | Python contract |
|---|---|
| `AudioFrame { pcm, tsMs, seq?, sessionId?, sampleRate?, isFinal? }` | `AudioFrame` (§1.1) — `frameToWire()` produces the exact JSON shape |
| `RouteDecision` (camelCase) | `RouteDecision` (§4.1) — `toWire()` emits `route/phrase_id/intent/confidence/reason/emit_filler_then_forward` |
| `PhraseRecord` | server `FillerPhrase` superset (+ transcript, audioPath, emotion, duration, safetyTag) |

## Phase 2 — capture / transport / playback

**2A capture (`capture.ts`).** Requests `getUserMedia` with
`echoCancellation` / `noiseSuppression` / `autoGainControl` track constraints so
the browser's native DSP does AEC + NS (CPU-light). Captures via `AudioWorklet`
when available, falling back to `ScriptProcessorNode`. Emits fixed-size
`AudioFrame`s at a target sample rate (default 16 kHz) with linear resampling
from the device/context rate. Detects clipping (`|sample| ≥ 0.99`) and reports
it. Device selection (`listInputDevices`) and permission probing
(`queryMicPermission`) are exposed.

**2B transport (`webrtc.ts`).** `RealtimeTransportClient` owns *session*
identity, not socket identity. The underlying channel is pluggable via the
`Transport` interface: `WebSocketTransport` (bring-up path, matches
`useVoiceStream.ts`), a future WebRTC/Opus or LiveKit transport, and
`LoopbackTransport` (tests). On drop it buffers outbound frames (bounded ring)
and reconnects with exponential backoff; on reconnect it re-sends the session
config (`resume: true`) and flushes the buffer, so audio survives reconnects and
jitter. The matching server contract is `edge/webrtc_gateway/gateway.py`.

**2C playback (`stream_player.ts`).** Schedules chunks back-to-back on the
`AudioContext` clock (`nextStartTime` cursor) for gapless, low-buffer streaming
that starts on the first chunk. A small reorder buffer smooths inbound jitter.
`fadeOut()` ramps a master gain to zero (clean, no click) for soft stops;
`hardStop()` cancels instantly for barge-in.

## Phase 3 — local router + filler

**3A schema (`phrase_schema.ts` + `phrase_bank.json`).** `PhraseRecord` carries
text, transcript, audioPath, language, tone, intent, emotion, category,
duration, confidence, priority, and `safetyTag`. `validatePhrase[Bank]` returns
structured issues and enforces id uniqueness. `PhraseBank` indexes by category
and supports filtered, priority-sorted search; **only `safe` phrases are
returned by default**.

**3B router (`intent_router.ts`).** `IntentRouter.classifyText` produces a
`RouteDecision`-shaped result: trivial keyword turns (greeting / farewell /
confirmation / acknowledgment) → `cached_filler`; emotional turns → empathy
filler + forward; everything else → `full_stack` with a stall sponge. Confidence
thresholds (`base × asrConfidence ≥ threshold`) gate cached routing to keep
false positives low. Recognition is pluggable via `SpeechRecognizer`;
`tryLoadSherpaRecognizer()` lazily loads sherpa-onnx if present, otherwise the
deterministic keyword path (or `NullKeywordRecognizer`) is used.

**3C filler (`filler_engine.ts`).** `FillerEngine` is bounded, safe, and
cancellable. `plan()` is pure/deterministic and returns `immediate` (trivial
turn — filler *is* the answer), `latency_sponge` (complex turn — buys 300–700 ms
then **hands off** to main output), or `skipped` (disabled / unsafe / too long /
no phrase). `handoffToMain()` fades a sponge so the real answer is **never**
overridden. `setEnabled(false)` is the global disable switch. Unsafe phrases and
phrases exceeding `maxFillerMs` are never played.

## Logging

Every module logs structured events through a pluggable logger (default
`console.*`), e.g. `capture_started`, `transport_reconnected`, `flush_outbound`,
`player_fadeout`, `router_cached_route`, `filler_handoff`. This satisfies the
visible-logging requirement of the definition of done (`final_use.md` §3.3).

## Tests

Lightweight unit tests use Node's built-in runner (`node:test`) and cover the
DOM-free logic (capture/transport/playback classes that touch WebAudio are
exercised in the browser; their pure helpers are tested here):

- `audio/types.test.ts` — PCM16 round-trip, clamping, wire shape, resampling
- `router/phrase_schema.test.ts` — validation, dedupe, search, safety filter
- `router/intent_router.test.ts` — routing + thresholds + determinism
- `router/filler_engine.test.ts` — plan/play, disable, cancel, no-override handoff

### Running

`client/node_modules` is **not** committed, so the project's own `tsc`/`next`
are unavailable until `npm install`. The tests and type-check were validated
with on-demand tooling via `npx`:

```bash
# from client/
# 1) run the unit tests (transpile-on-the-fly + node:test)
npx -y tsx --test src/audio/types.test.ts src/router/phrase_schema.test.ts \
  src/router/intent_router.test.ts src/router/filler_engine.test.ts

# 2) type-check the production modules (DOM lib, no project deps required)
npx -y -p typescript@5.6.3 tsc -p tsconfig.typecheck.json
```

After a normal `npm install`, `npx tsc --noEmit` (project tsconfig) also covers
these files. `tsconfig.typecheck.json` is a self-contained config used to verify
the new modules without the full Next.js toolchain.
