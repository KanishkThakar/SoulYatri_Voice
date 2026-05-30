# edge/webrtc_gateway — Transport Gateway (Phase 2B, server side)

Design note for the server-side transport gateway that ingests
`shared.contracts.AudioFrame` packets from the realtime client and **survives
reconnects** under moderate network jitter. Owner: edge/runtime agent
(`final_use.md` §4, Phase 2B).

## What it is

`gateway.py` is a dependency-light, CPU-only transport contract. The realtime
media stack (WebRTC + Opus via `aiortc`, or LiveKit) is **optional** and loaded
lazily — the gateway core needs no native media libraries, so it imports and
tests cleanly on a bare machine.

```
gateway.py
  ConnectionState           new | connected | disconnected | closed
  SessionMetadata           per-session bookkeeping that survives reconnects
  JitterBuffer              bounded reorder buffer; in-order release + dedupe
  GatewaySession            one logical client session (jitter + state + log)
  TransportGateway          manages sessions across connections (reconnect-safe)
  InMemoryTransportGateway  transport test double (records delivered frames)
  probe_webrtc_backend()    lazy detect aiortc/livekit; falls back to in-memory
```

## Key behaviors (acceptance: §Phase-2B)

**Frame ingest.** `TransportGateway.ingest(frame)` validates the frame against
the shared contract, routes it to its session (opening one on demand), and runs
it through a `JitterBuffer`. Frames are released to the sink in monotonic `seq`
order. Out-of-order arrivals are held briefly; duplicates / stale frames (seq
below the cursor) are dropped and counted; a final frame flushes the buffer.

**Reconnect survival.** Session identity is the `session_id`, not the socket.
`disconnect(session_id)` moves a session to `disconnected` but **retains all
state** (metadata, sequence cursor, counters). A later `reconnect()` /
`open_session()` with the same id resumes from the saved cursor and increments
`reconnect_count`; frames arriving after a silent drop implicitly reactivate the
session. State is only released by `close_session()` or `sweep_expired()` (TTL).

**Jitter smoothing.** The reorder window is bounded (`max_pending`); on overflow
the gateway advances past a missing `seq` rather than waiting unboundedly, so a
single lost packet can't stall the stream (graceful degradation).

## Wiring a real transport

A WebRTC/LiveKit backend decodes Opus → PCM and feeds frames into `ingest()`:

```python
from edge.webrtc_gateway.gateway import TransportGateway, probe_webrtc_backend
from shared.contracts import AudioFrame

gw = TransportGateway()
info = probe_webrtc_backend()  # logs which backend (if any) is available
# on each decoded media frame:
gw.ingest(AudioFrame(session_id=sid, seq=n, pcm=samples, sample_rate=16000))
# on transport drop / resume:
gw.disconnect(sid)
gw.reconnect(sid)
```

The gateway complements the existing WebSocket PCM path in `server/main.py`
during bring-up; both speak the same `AudioFrame` contract.

## Logging

Structured single-line logs on every meaningful transition via the
`soulyatri.edge.webrtc_gateway` logger: `gateway_open_session`,
`session_reconnect`, `session_disconnect`, `frame_dropped`, `gateway_sweep`,
`webrtc_backend_detected` / `webrtc_backend_fallback`. Satisfies the
visible-logging requirement of the definition of done (`final_use.md` §3.3).

## Tests

`tests/test_gateway.py` (23 tests) covers the two acceptance behaviors:

- **frame ingest** — in-order delivery, jitter reordering, dedupe/stale drops,
  overflow gap-skip, auto-open, session-id mismatch rejection, final flush
- **reconnect survival** — state retained across drops, resume ordering, reconnect
  via `open_session`, unknown-session recreation, implicit reactivation, clean
  resume after mid-drop frame loss
- lifecycle — close/flush, closed-session guard, TTL sweep, active count, attrs
- import hygiene — no `torch`/`aiortc`/`livekit`/`transformers` pulled in

### Run

```bash
# from repo root
python -c "import edge.webrtc_gateway.gateway"        # import check
python -m pytest edge/webrtc_gateway/tests -q          # 23 passed
```
