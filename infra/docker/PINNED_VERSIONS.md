# Pinned versions — SoulYatri container stack

> **Scope:** `final_use.md` §16C — "Dockerize services, pin versions". This note records
> the image/runtime versions used by `infra/docker/docker-compose.full.yml` and
> `infra/docker/Dockerfile.server`, and the policy for hardening them further.
>
> This file is **documentation**; the authoritative pins live in the compose file image
> tags and `server/requirements.txt`. Keep them in sync.

## Image tags (pin to digests in production)

| Service | Image tag (compose) | Notes / production action |
|---|---|---|
| LiveKit | `livekit/livekit-server:v1.8` | Pin to a digest: `livekit/livekit-server@sha256:…`. |
| Redis | `redis:7-alpine` | Pin to `redis:7.4-alpine` then a digest. AOF persistence on. |
| Postgres | `postgres:16-alpine` | Pin to `postgres:16.4-alpine` then a digest. Profile/relational store (L4). |
| Qdrant | `qdrant/qdrant:v1.12.1` | Semantic vector store (L3). Already a specific patch tag. |
| Prometheus | `prom/prometheus:v2.54.1` | Scrapes the server `/metrics`. Specific patch tag. |
| Server | built from `Dockerfile.server` | Base `python:3.11-slim`; pin base to a digest in prod. |

> **Policy:** every image MUST be pinned to an immutable digest (`@sha256:…`) before a
> production rollout. The minor-version tags above are the *floor* for local/staging.

## Python runtime pins

The server image installs `server/requirements.txt`, which is already version-bounded
(`>=`). For reproducible builds, generate a fully-pinned lockfile (`pip-compile` /
`uv pip compile`) and `COPY` that instead. Key bounds today:

| Package | Bound | Role |
|---|---|---|
| fastapi | `>=0.115.0` | HTTP app + `/metrics` route |
| uvicorn[standard] | `>=0.32.0` | ASGI server |
| pydantic / pydantic-settings | `>=2.9.0` / `>=2.6.0` | contracts + config |
| prometheus-client | `>=0.21.0` | metrics exposition |
| structlog | `>=24.4.0` | structured logging (server) |
| torch / torchaudio | `>=2.4.0` | audio + models (CPU wheels for CPU nodes) |
| faster-whisper | `>=1.1.0` | STT path |
| edge-tts / pydub | `>=6.1.0` / `>=0.25.1` | TTS path (needs `ffmpeg` in image) |
| redis | `>=5.2.0` | hot cache client |

## GPU vs CPU base image

`Dockerfile.server` defaults to `python:3.11-slim` (CPU-safe). For GPU worker nodes:

1. Switch the base to an NVIDIA CUDA runtime image (e.g. `nvidia/cuda:12.4.1-runtime-ubuntu22.04`)
   plus a matching Python install.
2. Install CUDA-enabled `torch` wheels (the `--index-url` for the right CUDA tag).
3. Set `WHISPER_DEVICE=cuda`, `EMOTION_DEVICE=cuda`, `SPEAKER_DEVICE=cuda`.
4. Size workers with `infra.scaling.GpuEnvelope` (max sessions per GPU class/VRAM).

The CPU default keeps `python -c "import infra"` and the unit tests cluster-free.
