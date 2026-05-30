# API & Protocol Reference

> The real HTTP REST + WebSocket API exposed by the gateway. Grounded in `server/main.py`,
> `server/config.py`, and `server/utils/audio.py`. The app is a FastAPI application titled
> **"SoulYatri Speech"**, version `0.1.0`, defined in `server/main.py`.

## Server bootstrap

- ASGI app: `app = FastAPI(title="SoulYatri Speech", version="0.1.0", lifespan=lifespan)`.
- Lifespan (`lifespan`) calls `setup_logging()`, then `agent.initialize()` (loads models)
  on startup and `agent.shutdown()` on shutdown. A single global `agent = VoiceAgent()` is
  shared across requests.
- CORS: `CORSMiddleware` allows origins `http://localhost:3000` and
  `http://127.0.0.1:3000` (the Next.js client) with all methods/headers and credentials.
- Entry point: `python -m server.main` runs `uvicorn.run("server.main:app", host=
  settings.server_host, port=settings.server_port, ws_max_size=16*1024*1024)`. Default host
  `0.0.0.0`, port `8000` (see [configuration_reference.md](configuration_reference.md)).

---

## REST endpoints

### `GET /health`

Health check. Returns JSON:

```json
{"status": "healthy", "version": "0.1.0", "phase": 2}
```

### `GET /metrics`

Prometheus metrics exposition (`PlainTextResponse`). Returns `generate_latest()` from
`prometheus_client` with content type `CONTENT_TYPE_LATEST`. Metric names use the
`soulyatri_` prefix (defined in `server/utils/metrics.py`), e.g.
`soulyatri_pipeline_e2e_latency_seconds`, `soulyatri_llm_ttft_seconds`,
`soulyatri_active_sessions`, `soulyatri_filler_hit_rate_total`,
`soulyatri_barge_in_total`, `soulyatri_errors_total`.

### `GET /api/token`

Generates a LiveKit access token for the client.

- **Query params:** `room` (default `"soulyatri-room"`), `identity` (default `"user"`).
- **Behavior:** builds a JWT via `livekit.api.AccessToken(settings.livekit.api_key,
  settings.livekit.api_secret).with_identity(identity).with_grants(VideoGrants(
  room_join=True, room=room)).to_jwt()`.
- **Success response:**

  ```json
  {"token": "<jwt>", "url": "ws://localhost:7880", "room": "soulyatri-room", "identity": "user"}
  ```

  `url` comes from `settings.livekit.url`.
- **Fallbacks / errors:** if `livekit-api` is not installed (`ImportError`), it logs
  `livekit_api_not_available` and returns a dummy token `"dev-token"` (same JSON shape).
  Any other exception returns HTTP `500` with the error detail.

> Security note: this token generator is described in code as "a simplified token generator
> for development." It performs no authentication of the caller — in production it must be
> placed behind proper auth before issuing room-join grants.

---

## WebSocket — real-time audio streaming

### `WS /ws/audio/{session_id}`

Full-duplex audio channel. The path parameter `session_id` is the correlation key for the
turn machine, callbacks, and session cleanup.

**Handshake / lifecycle:**
1. Server calls `websocket.accept()` and logs `ws_connected`.
2. The handler registers three agent callbacks: `set_audio_callback(on_audio_response)`,
   `set_transcript_callback(on_transcript)`, `set_turn_metadata_callback(on_turn_metadata)`.
3. It then loops on `websocket.receive()`, dispatching by frame type.
4. On disconnect / `end` / error it calls `agent.handle_session_end(session_id)` in
   `finally`.

### Client → server frames

| Frame type | Payload | Meaning |
|---|---|---|
| **binary** | raw 16-bit PCM, **16 kHz mono** (default) | Audio. Forwarded to `agent.handle_audio_frame(session_id, audio_bytes, sample_rate=client_sample_rate)`. |
| **text (JSON)** | `{"type": "config", "sample_rate": 16000}` | Updates the server's `client_sample_rate` for subsequent binary frames; logs `ws_config_update`. |
| **text (JSON)** | `{"type": "end"}` | Client signals end of stream; server logs `ws_client_end` and breaks the loop. |

Invalid control JSON is logged as `ws_invalid_control` and ignored (the connection stays
open). The default `client_sample_rate` is `SAMPLE_RATE_16K` (16000) from
`server/utils/audio.py`.

### Server → client frames

| Frame | Payload | Emitted by |
|---|---|---|
| **binary** | raw 16-bit PCM, **24 kHz mono** | `on_audio_response` — synthesized assistant audio (`websocket.send_bytes`). |
| **text (JSON)** | `{"type": "audio_meta", "sample_rate": <int>, "size": <bytes>, "metadata": {…}}` | `on_audio_response` — accompanies each audio chunk. |
| **text (JSON)** | `{"type": "transcript", "role": <str>, "text": <str>, "timestamp": <epoch>}` | `on_transcript` — transcript updates. |
| **text (JSON)** | `{"type": "turn_metadata", "metadata": {…}}` | `on_turn_metadata` — per-turn feature metadata (emotion/speaker/etc.). |

> Sample-rate contract (from the `audio_websocket` docstring + `server/utils/audio.py`):
> **client → server is 16 kHz**, **server → client is 24 kHz**, both raw 16-bit PCM mono.
> Send errors are logged (`ws_send_error`, `ws_transcript_error`, `ws_turn_metadata_error`)
> without tearing down the socket.

---

## LiveKit token flow (end to end)

```text
Client                         Server (FastAPI)                 LiveKit
  |  GET /api/token?room=&identity=  |                              |
  |--------------------------------->|                              |
  |                                  |  AccessToken(api_key,        |
  |                                  |    api_secret)               |
  |                                  |  .with_identity(identity)    |
  |                                  |  .with_grants(VideoGrants(   |
  |                                  |     room_join=True, room))   |
  |                                  |  .to_jwt()                   |
  |   {token, url, room, identity}   |                              |
  |<---------------------------------|                              |
  |  connect(url, token)  ----------------------------------------->|
  |  (WebRTC media session in the LiveKit room)                     |
```

The token's `url` (`settings.livekit.url`, default `ws://localhost:7880`) and credentials
come from the LiveKit settings (env prefix `LIVEKIT_`). The raw-PCM WebSocket
(`/ws/audio/{session_id}`) is the in-repo streaming path used by the Phase-1/2 baseline;
the LiveKit token flow is the transport path the client uses for WebRTC media.

## Quick reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + version/phase. |
| GET | `/metrics` | Prometheus exposition (`soulyatri_*`). |
| GET | `/api/token` | LiveKit room-join JWT (`room`, `identity` query params). |
| WS | `/ws/audio/{session_id}` | Bidirectional PCM (16 kHz up / 24 kHz down) + JSON control. |
