# SoulYatri Speech 🎙️

**Speech-Native Realtime Emotional Voice AI — Open Source Only**

A production-grade, low-latency, speech-native, full-duplex conversational voice system supporting Hindi, English, and Hinglish.

---

## Phase 1 — Production Baseline

The current implementation provides a working realtime voice pipeline:

```
Audio → WebRTC → VAD → STT → LLM → TTS → Audio
```

### Stack

| Component | Technology |
|-----------|-----------|
| Transport | LiveKit + WebRTC |
| VAD | Silero VAD |
| STT | faster-whisper |
| LLM | Ollama (Qwen3 / Llama 3.3) |
| TTS | edge-tts (Hindi + English neural voices) |
| Client | Next.js + LiveKit Client SDK |
| Server | Python + FastAPI |
| Monitoring | Prometheus + structlog |

---

## Prerequisites

- **Python 3.10+** (3.12 recommended)
- **Node.js 18+**
- **Docker Desktop**
- **Ollama** — [download](https://ollama.com)
- **NVIDIA GPU + CUDA 12** (for faster-whisper)

---

## Quick Start

### 1. Clone and configure
```bash
cp .env.example .env
# Edit .env with your settings
```

### 2. Pull LLM model
```bash
ollama pull qwen3:8b
```

### 3. Start infrastructure
```bash
docker-compose up -d
```

### 4. Start Python server
```bash
python -m venv venv
venv\Scripts\activate
pip install -r server\requirements.txt
python -m server.main
```

### 5. Start web client
```bash
cd client
npm install
npm run dev
```

### 6. Open browser
Navigate to `http://localhost:3000` and start talking!

---

## Architecture

```
┌─────────────────────────────────────────┐
│              Web Client                 │
│  Microphone → WebRTC → LiveKit Client   │
└────────────────┬────────────────────────┘
                 │ WebRTC
┌────────────────▼────────────────────────┐
│           LiveKit Server                │
│         (Docker Container)              │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│         Python Backend                  │
│  ┌──────┐  ┌──────┐  ┌─────┐  ┌─────┐ │
│  │ VAD  │→ │ STT  │→ │ LLM │→ │ TTS │ │
│  │Silero│  │Whisp.│  │Qwen3│  │Edge │ │
│  └──────┘  └──────┘  └─────┘  └─────┘ │
│                                         │
│  Logging │ Metrics │ Session State      │
└─────────────────────────────────────────┘
```

---

## License

Open source — see individual model licenses for restrictions.
