# Code Knowledge Base — Index

> Source-grounded documentation of the SoulYatri codebase (Phase 17B). Every claim here
> is verified against the files listed under **Provenance**. No modules, classes,
> endpoints, or settings are invented. Where a real backend (Mimi/Moshi weights, GPU,
> Redis/Postgres/Qdrant) is absent, the code ships a graceful CPU/no-weights fallback
> (see [DECISIONS.md](../DECISIONS.md) D-008); the docs note this explicitly.

## Documents

| Doc | Scope |
|---|---|
| [architecture_overview.md](architecture_overview.md) | The frozen speech-native loop, the domain-folder map, and how the existing `server/` gateway + Phase-1 baseline fit alongside the new domain folders. |
| [module_reference.md](module_reference.md) | Per-subsystem module reference: real module names, key classes/functions, and their inputs→outputs. |
| [api_protocol_reference.md](api_protocol_reference.md) | The HTTP REST + WebSocket API exposed by `server/main.py`, plus the LiveKit token flow. |
| [configuration_reference.md](configuration_reference.md) | The settings model in `server/config.py` (every `Settings` subclass, env prefix, defaults) and the `.env.example` keys. |

## Provenance (which source files ground each doc)

| Doc | Primary source files |
|---|---|
| architecture_overview.md | [`README.md`](../../README.md), [`docs/DECISIONS.md`](../DECISIONS.md), [`docs/INTERFACES.md`](../INTERFACES.md), [`shared/contracts.py`](../../shared/contracts.py), `server/main.py`, `server/agent.py`, the `edge/`, `speech/`, `aux/`, `memory/`, `safety/`, `infra/`, `evals/` package trees |
| module_reference.md | `shared/contracts.py`; `edge/session/turn_state.py`, `edge/turn_detection/*.py`, `edge/barge_in/detector.py`, `edge/emotion/extractor.py`, `edge/speaker/encoder.py`, `edge/planner/*.py`; `speech/codec/*.py`, `speech/moshi_runtime/*.py`, `speech/decoder/service.py`, `speech/persona/controller.py`; `aux/text_brain/*.py`, `aux/stt/transcript_service.py`, `aux/fallback/orchestrator.py`; `memory/store.py`, `memory/contracts.py`; `safety/moderation/gate.py`, `safety/voice_policy/policy.py`, `safety/watermark/audioseal.py`; `infra/scaling/scheduler.py`, `infra/deploy/regions.py`, `infra/deploy/rollback.py`; `evals/replay/harness.py`, `evals/latency/metrics.py` |
| api_protocol_reference.md | `server/main.py`, `server/config.py`, `server/utils/audio.py` |
| configuration_reference.md | `server/config.py`, [`.env.example`](../../.env.example) |

## Conventions

- **Markdown** (`.md`) is used for prose; **JSONL** (`.jsonl`) for structured training data.
- Type names, class names, and function signatures are taken directly from source.
- Timestamps in contracts are integer milliseconds (`ts_ms`) unless noted; emotion
  scalars follow the ranges in [INTERFACES.md](../INTERFACES.md) §0.
- "Fallback" throughout means the deterministic, dependency-light path that runs without
  GPU or model weights so the repo imports and tests on CPU.
