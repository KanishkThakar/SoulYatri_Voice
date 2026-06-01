# SoulYatri Speech 🎙️

**Speech-Native Realtime Emotional Voice AI — Open Source Only**

A low-latency, full-duplex conversational voice system for Hindi, English, and Hinglish.
Built entirely on open-source components, designed to feel fast and emotionally aware
rather than like a text bot reading answers aloud.

---

## Project status

The architecture is frozen around a **speech-native loop** (`Audio → codec tokens →
speech-native model → codec tokens → Audio`). The classic cascade below is the
**baseline / fallback shipping path** and is what runs today on commodity hardware.

| Layer | Status |
|-------|--------|
| Phase 1 — classic voice pipeline (VAD → STT → LLM → TTS) | ✅ Runs locally (CPU or GPU) |
| Turn-state machine, filler routing, emotion + speaker features, barge-in | ✅ Implemented |
| Next.js voice client (mic capture, streaming playback, transcript) | ✅ Implemented |
| Speech-native core (Moshi + Mimi), CSM fallback | ⏳ Gated — needs GPU + pinned model weights (`docs/MODEL_LOCKS.md`) |
| Memory (Redis / Postgres / Qdrant), safety, infra scaffolding | ✅ Code-complete, partially gated on external services |

> The speech-native core ships with mock/echo backends until weights are pinned, so on a
> machine without a GPU you get the working Phase-1 cascade.

---

## Current pipeline (Phase 1)

```
Audio → WebRTC/WebSocket → VAD → STT → LLM → TTS → Audio
```

| Component | Technology |
|-----------|-----------|
| Transport | LiveKit + WebRTC (raw-PCM WebSocket fallback) |
| VAD | Silero VAD |
| STT | faster-whisper |
| LLM | Ollama (Qwen3 / Llama 3.3) |
| TTS | edge-tts (Hindi + English neural voices) |
| Client | Next.js |
| Server | Python + FastAPI |
| Monitoring | Prometheus + structlog |

---

## Prerequisites

- **Python 3.10+** (3.12 recommended)
- **Node.js 18+**
- **Ollama** — https://ollama.com (provides the LLM)
- **Docker Desktop** — optional, for LiveKit + Redis
- **NVIDIA GPU + CUDA 12** — optional; without it, run in CPU mode (see below)

---

## Setup

### Option A — automated (Windows PowerShell)

```powershell
.\scripts\setup.ps1
```

This checks your toolchain, creates `server\venv`, installs Python + client
dependencies, and copies `.env.example` to `.env`.

### Option B — manual

```powershell
# 1. Configure environment
Copy-Item .env.example .env      # then edit .env as needed

# 2. Python server
python -m venv server\venv
server\venv\Scripts\activate
pip install -r server\requirements.txt

# 3. Web client
cd client
npm install
cd ..

# 4. Pull an LLM model (~5 GB)
ollama pull qwen3:8b
```

---

## Running

Start each piece in its own terminal.

### 1. Infrastructure (optional — LiveKit + Redis)

```powershell
docker-compose up -d
# or: .\scripts\start_livekit.ps1
```

Skip this to use the raw-PCM WebSocket path with in-memory session state.

### 2. Python server

```powershell
server\venv\Scripts\activate
python -m server.main
```

Serves on `http://localhost:8000` by default (`SERVER_PORT` in `.env`).

**CPU-only?** Override the device settings before starting:

```powershell
$env:WHISPER_DEVICE="cpu"; $env:WHISPER_COMPUTE_TYPE="int8"
$env:EMOTION_DEVICE="cpu"; $env:SPEAKER_DEVICE="cpu"
python -m server.main
```

### 3. Web client

```powershell
cd client
npm run dev
```

Open `http://localhost:3000` and tap the mic to start talking.

> **Port note:** the client connects to `ws://localhost:8000/ws/audio` by default. If you
> run the server on a different port (e.g. port 8000 is already taken), set it for the
> client via `client\.env.local`:
>
> ```
> NEXT_PUBLIC_WS_URL=ws://localhost:8080/ws/audio
> ```
>
> and start the server with `$env:SERVER_PORT=8080; python -m server.main`.

---

## Verify it's up

```powershell
curl http://localhost:8000/health      # {"status":"healthy",...}
curl http://localhost:8000/metrics     # Prometheus exposition
```

---

## Tests

```powershell
# Python (foundation + subsystem suites)
pip install pytest
python -m pytest -q

# Client unit tests / type-check (from client/)
cd client
npm test
npm run typecheck
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│              Web Client                  │
│  Microphone → WebRTC/WS → Audio stream   │
└────────────────┬─────────────────────────┘
                 │ WebRTC / raw-PCM WebSocket
┌────────────────▼─────────────────────────┐
│           LiveKit Server (optional)       │
│              (Docker container)           │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│           Python Backend                  │
│  ┌──────┐  ┌──────┐  ┌─────┐  ┌─────┐    │
│  │ VAD  │→ │ STT  │→ │ LLM │→ │ TTS │    │
│  │Silero│  │Whisp.│  │Qwen3│  │Edge │    │
│  └──────┘  └──────┘  └─────┘  └─────┘    │
│                                           │
│  Turn-state machine · Filler routing      │
│  Emotion + Speaker features · Barge-in    │
│  Logging · Metrics · Session state        │
└───────────────────────────────────────────┘
```

The full speech-native design (Mimi tokenizer → Moshi runtime → emotion/persona →
acoustic decoder) and the 19-phase roadmap live in
`Soulyatri_Final_Speech_Native_Implementation_Guide.md` and `final_use.md`.

---

## Repository layout

| Path | Purpose |
|------|---------|
| `server/` | FastAPI server + Phase-1 voice pipeline |
| `client/` | Next.js voice client |
| `edge/` | Edge runtime: turn detection, features, barge-in, transport gateway |
| `speech/` | Speech-native core (codec, tokenizer, Moshi runtime, decoder, persona) |
| `auxiliary/` | Text brain, auxiliary STT, tool router, fallbacks |
| `memory/` | Redis / Postgres / Qdrant memory tiers + summarizer |
| `safety/` | Moderation, voice policy, watermarking |
| `infra/` | LiveKit, Docker, deploy, monitoring, scaling |
| `evals/` | Replay, latency, audio, Hinglish, emotion evaluations |
| `training/` | Data engine, labeling, SFT, preference tuning |
| `scripts/` | Setup and helper scripts |
| `runs/` | Per-phase acceptance evidence and benchmarks |
| `docs/` | Design notes, decisions, model locks |

---

## License

Open source (Apache-2.0). See individual model licenses for their own restrictions.
