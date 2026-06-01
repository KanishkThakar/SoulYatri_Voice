# Live Run — Local bring-up of the SoulYatri Phase-1 pipeline

**Date:** 2026-05-30
**Goal:** Actually boot and run the project end to end on the local CPU-only dev host
(beyond the CPU unit tests), per the user request to "run the full project."

**Environment:** Windows, Python 3.11.9, Node v20.20.0, no GPU, Docker daemon **not
running**, Ollama 0.24.0 running.

> This is an operational run record, not a new build phase. All 18 `final_use.md` build
> phases are code-complete (see `runs/0-1-foundation` … `runs/phase-18-launch`). This file
> documents what was started, what works live, and what remains gated.

---

## Dependencies installed for the live run

The CPU unit-test suite needed no heavy ML deps, but running the **real** Phase-1 pipeline
does. Installed into the active environment:

| Package | Why |
|---|---|
| `torch` (CPU build) | silero-vad + faster-whisper backend |
| `faster-whisper` | STT (small / int8 on CPU) |
| `silero-vad` | VAD speech gating |
| `edge-tts` | TTS (Hindi + English neural voices) |
| `pydub` | filler audio synthesis |
| `numpy`, `structlog`, `prometheus-client` | audio math, logging, metrics |

---

## What is running

| Service | Address | Status | Evidence |
|---|---|---|---|
| FastAPI gateway (`server.main`) | `http://localhost:8080` | **UP** | `/health` → `{"status":"healthy","version":"0.1.0","phase":2}` |
| LiveKit token endpoint | `GET /api/token` | **UP** | returns `{token,url,room,identity}` |
| Prometheus metrics | `GET /metrics` | **UP** | 200, ~10 KB exposition |
| Audio WebSocket | `WS /ws/audio/{session_id}` | **UP** | connect + `config` control frame accepted |
| Next.js client | `http://localhost:3000` | **UP** | 200, serves the voice UI |

Models loaded on CPU at startup (logged `agent_initialized` → `server_ready`):
Silero VAD, faster-whisper `small` (int8), wav2vec2 SER emotion encoder, ECAPA speaker
encoder, filler phrase bank (pre-synthesized via edge-tts).

### Deviations made to run locally (documented, not silent)
- **Port 8080, not 8000.** The IDE's own `kiro-gateway` already listens on 8000, so the
  server was started with `SERVER_PORT=8080` to avoid the collision. The client's
  `VoiceInterface.tsx` `serverUrl` was repointed to `ws://localhost:8080/ws/audio`.
- **CPU device overrides.** Started with `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8`,
  `EMOTION_DEVICE=cpu`, `SPEAKER_DEVICE=cpu` (no GPU present).

---

## What remains gated (honest)

- **Docker infra (LiveKit + Redis) not started** — Docker Desktop daemon is down
  (`//./pipe/dockerDesktopLinuxEngine` not found). The raw-PCM WebSocket path and
  in-memory fallbacks work without it; the LiveKit WebRTC transport and Redis hot-cache do
  not until Docker is started and `docker compose up -d` is run.
- **LLM model** — `server/config.py` default is `qwen3:8b`. Ollama had only
  `minimax-m2.7:cloud` (needs auth → 401) and `gemma4:26b` (too heavy for CPU, load
  timed out), so `ollama pull qwen3:8b` was started. Until it finishes the LLM stage has
  no usable local model.
- **Speech-native core (Moshi/Mimi)** — still mock/echo backends (no weights/GPU), exactly
  as in `docs/launch/LAUNCH_READINESS.md`. The live path here is the **Phase-1 classic
  cascade** (VAD → faster-whisper → Ollama → edge-tts), which `final_use.md` designates as
  the fallback/baseline shipping path.

---

## How to reproduce

```powershell
# 1. Backend (CPU)
$env:SERVER_PORT=8080; $env:WHISPER_DEVICE="cpu"; $env:WHISPER_COMPUTE_TYPE="int8"
$env:EMOTION_DEVICE="cpu"; $env:SPEAKER_DEVICE="cpu"
python -m server.main

# 2. LLM model (one-time, ~5.2 GB)
ollama pull qwen3:8b

# 3. Client
cd client; npm run dev        # serves http://localhost:3000

# 4. (optional) infra — requires Docker Desktop running
docker compose up -d          # LiveKit + Redis
```
