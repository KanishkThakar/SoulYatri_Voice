# Configuration Reference

> The real settings model. Grounded in `server/config.py` (pydantic-settings) and
> [`.env.example`](../../.env.example). All values load from environment variables / a
> `.env` file. The importable singleton is `settings = Settings()` — "import this
> everywhere" per `server/config.py`.

## Settings model

`server/config.py` defines a root `Settings` class plus nested `BaseSettings` subclasses,
each with its own `env_prefix`. The root reads `.env` (`env_file=".env"`,
`env_file_encoding="utf-8"`, `extra="ignore"`).

### Root — `Settings`

No prefix on the root scalars. Env var name == upper-cased field name.

| Field | Env var | Default |
|---|---|---|
| `server_host` | `SERVER_HOST` | `0.0.0.0` |
| `server_port` | `SERVER_PORT` | `8000` |
| `log_level` | `LOG_LEVEL` | `INFO` |
| `log_format` | `LOG_FORMAT` | `json` |

Nested groups (instantiated as defaults on the root): `livekit`, `ollama`, `whisper`,
`tts`, `session`, `emotion`, `speaker`, `filler`, `barge_in`.

### `LiveKitSettings` — prefix `LIVEKIT_`

| Field | Env var | Default |
|---|---|---|
| `url` | `LIVEKIT_URL` | `ws://localhost:7880` |
| `api_key` | `LIVEKIT_API_KEY` | `devkey` |
| `api_secret` | `LIVEKIT_API_SECRET` | `secret` |

### `OllamaSettings` — prefix `OLLAMA_`

| Field | Env var | Default |
|---|---|---|
| `base_url` | `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `model` | `OLLAMA_MODEL` | `qwen3:8b` |

### `WhisperSettings` — prefix `WHISPER_`

| Field | Env var | Default |
|---|---|---|
| `model_size` | `WHISPER_MODEL_SIZE` | `small` |
| `device` | `WHISPER_DEVICE` | `cuda` |
| `compute_type` | `WHISPER_COMPUTE_TYPE` | `float16` |

### `TTSSettings` — prefix `TTS_`

| Field | Env var | Default |
|---|---|---|
| `voice_hindi` | `TTS_VOICE_HINDI` | `hi-IN-SwaraNeural` |
| `voice_english` | `TTS_VOICE_ENGLISH` | `en-IN-NeerjaNeural` |

### `SessionSettings` — prefix `SESSION_`

| Field | Env var | Default |
|---|---|---|
| `timeout_seconds` | `SESSION_TIMEOUT_SECONDS` | `300` |
| `max_conversation_history` | `SESSION_MAX_CONVERSATION_HISTORY` | `20` |

### `EmotionSettings` — prefix `EMOTION_`

| Field | Env var | Default |
|---|---|---|
| `model_name` | `EMOTION_MODEL_NAME` | `ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition` |
| `device` | `EMOTION_DEVICE` | `cuda` |
| `enabled` | `EMOTION_ENABLED` | `True` |

### `SpeakerSettings` — prefix `SPEAKER_`

| Field | Env var | Default |
|---|---|---|
| `model_source` | `SPEAKER_MODEL_SOURCE` | `speechbrain/spkrec-ecapa-voxceleb` |
| `save_dir` | `SPEAKER_SAVE_DIR` | `models/speaker_encoder` |
| `device` | `SPEAKER_DEVICE` | `cuda` |
| `enabled` | `SPEAKER_ENABLED` | `True` |

### `FillerSettings` — prefix `FILLER_`

| Field | Env var | Default |
|---|---|---|
| `enabled` | `FILLER_ENABLED` | `True` |
| `pre_synthesize` | `FILLER_PRE_SYNTHESIZE` | `True` |
| `phrases_path` | `FILLER_PHRASES_PATH` | `""` |

### `BargeInSettings` — prefix `BARGE_IN_`

| Field | Env var | Default |
|---|---|---|
| `enabled` | `BARGE_IN_ENABLED` | `True` |
| `threshold` | `BARGE_IN_THRESHOLD` | `0.5` |
| `min_speech_duration_ms` | `BARGE_IN_MIN_SPEECH_DURATION_MS` | `200` |
| `cooldown_ms` | `BARGE_IN_COOLDOWN_MS` | `500` |

> Note on prefixing: pydantic-settings prepends the subclass `env_prefix` to each field
> name. So `SessionSettings.timeout_seconds` reads `SESSION_TIMEOUT_SECONDS`. The
> `.env.example` uses `SESSION_TIMEOUT_SECONDS` and `MAX_CONVERSATION_HISTORY`; under the
> `SESSION_` prefix the canonical variable for `max_conversation_history` is
> `SESSION_MAX_CONVERSATION_HISTORY`.

---

## `.env.example` keys

`.env.example` is the environment contract (Phase 1C). It groups the baseline keys consumed
by `server/config.py` above, plus forward-looking service-boundary keys for the
`final_use.md` domain folders. The forward-looking keys are **not** required to import the
foundation on CPU — they configure optional services and pending-human-pin models.

### Baseline keys (consumed by `server/config.py`)

`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`; `OLLAMA_BASE_URL`, `OLLAMA_MODEL`;
`WHISPER_MODEL_SIZE`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`; `TTS_VOICE_HINDI`,
`TTS_VOICE_ENGLISH`; `LOG_LEVEL`, `LOG_FORMAT`; `SERVER_HOST`, `SERVER_PORT`;
`SESSION_TIMEOUT_SECONDS`, `MAX_CONVERSATION_HISTORY`.

### Forward-looking service-boundary keys (Phase 1C+)

| Group | Keys | Notes |
|---|---|---|
| Memory: Postgres (L4) | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Profile / relational store. |
| Memory: Qdrant (L3) | `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` | Semantic vector store. |
| Memory: Redis (L2) | `REDIS_URL` | Hot session cache (used by docker-compose). |
| Memory: Embeddings | `EMBEDDINGS_MODEL` (`intfloat/multilingual-e5-base`), `EMBEDDINGS_DEVICE` (`cpu`) | multilingual-e5. |
| Speech core: Mimi | `MIMI_MODEL_PATH`, `MIMI_SAMPLE_RATE` (`24000`), `MIMI_DEVICE` (`cpu`) | pending-human-pin (see [MODEL_LOCKS.md](../MODEL_LOCKS.md)). |
| Speech core: Moshi | `MOSHI_MODEL_PATH`, `MOSHI_DEVICE` (`cpu`), `MOSHI_ENABLED` (`false`) | Fallbacks when disabled. |
| Fallback speech: CSM | `CSM_MODEL_PATH`, `CSM_ENABLED` (`false`) | Reference speech generation. |
| Client helper | `SHERPA_ONNX_MODEL_PATH` | Tiny local ASR/KWS/intent router. |
| Safety: watermark | `WATERMARK_ENABLED` (`false`), `WATERMARK_MODEL_PATH`, `WATERMARK_DETECT_THRESHOLD` (`0.5`) | AudioSeal or equivalent. |
| Safety: voice policy | `VOICE_CONSENT_REQUIRED` (`true`), `PROTECTED_VOICE_LIST_PATH` | Consent-first. |
| Safety: moderation | `MODERATION_ENABLED` (`true`), `MODERATION_FAIL_CLOSED` (`true`) | Fail-closed default. |
| Indic STT fallback | `INDIC_STT_MODEL_PATH`, `INDIC_STT_ENABLED` (`false`) | IndicConformer or equivalent. |
| Observability (15A) | `OTEL_EXPORTER_OTLP_ENDPOINT`, `PROMETHEUS_ENABLED` (`true`) | Tracing/metrics export. |

> Because the root `Settings` uses `extra="ignore"`, the forward-looking keys in `.env` are
> read by the subsystems that own them (e.g. `memory/`, `safety/`) rather than rejected by
> the root model.

---

## Usage

```python
from server.config import settings

host = settings.server_host          # "0.0.0.0"
port = settings.server_port          # 8000
model = settings.ollama.model        # "qwen3:8b"
whisper_size = settings.whisper.model_size   # "small"
livekit_url = settings.livekit.url   # "ws://localhost:7880"
```

To configure a deployment: `cp .env.example .env` and edit values (see
[README.md](../../README.md) Quick Start). Never commit `.env`.
