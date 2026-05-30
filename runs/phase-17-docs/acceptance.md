# Phase 17 — Documentation Knowledge Base & Training Corpus — Acceptance

**Phase:** 17 (Documentation knowledge base, training corpus, docs-folder requirements)
**Scope:** `docs/code/`, `docs/training/`, `docs/index.md`, and a JSONL validator under
`scripts/`. No source folders (`server/`, `client/`, `edge/`, `speech/`, `aux/`, `memory/`,
`safety/`, `infra/`, `evals/`, `training/`, `shared/`) were modified — they were read-only
inputs used to ground the docs. Existing Phase-0 governance docs in `docs/` were not
overwritten; new files were added alongside them and linked from `docs/index.md`.

## Deliverables (Definition of Done §3.3)

### Code knowledge base (Phase 17B)
- `docs/index.md` — top-level index linking governance docs + code/training docs.
- `docs/code/index.md` — code-docs index with per-doc source provenance.
- `docs/code/architecture_overview.md` — frozen speech-native loop, domain-folder map,
  how `server/` gateway + Phase-1 baseline fits.
- `docs/code/module_reference.md` — per-subsystem module reference (real names verified).
- `docs/code/api_protocol_reference.md` — real HTTP + WebSocket API + LiveKit token flow.
- `docs/code/configuration_reference.md` — real `server/config.py` settings + `.env.example`.

### Training corpus (Phase 17C)
- `docs/training/index.md` — corpus index + consumption notes.
- `docs/training/schema.md` — JSONL record schema + conventions.
- `docs/training/qa_dataset.jsonl` — 58 records, one JSON object per line.
- `docs/training/qa_dataset.md` — human-readable mirror (generated from the JSONL).

### Validation
- `scripts/validate_training_jsonl.py` — line-by-line JSONL validator.

## Validation step (required acceptance result)

Command (run from repo root):

```
python scripts/validate_training_jsonl.py
```

Output:

```
Validating: C:\Users\mpstme.student\Downloads\SoulYatri_Voice\docs\training\qa_dataset.jsonl
OK: 58 line(s) validated, all conform to the schema.
```

Exit code: `0`.

The validator asserts, for every non-blank line: (1) the line is valid standalone JSON and
is an object, (2) the required keys `instruction`, `response`, `source`, `tags` are present,
(3) `instruction`/`response` are non-empty strings, and (4) `source`/`tags` are non-empty
arrays of strings. All 58 records pass.

## Grounding (no invented modules/endpoints/settings)

Each doc section was grounded by reading the real files:

| Doc | Grounded in |
|---|---|
| architecture_overview.md | `README.md`, `docs/DECISIONS.md`, `docs/INTERFACES.md`, `shared/contracts.py`, `server/main.py`, `server/agent.py`, and the `edge/ speech/ aux/ memory/ safety/ infra/ evals/` trees. |
| module_reference.md | `shared/contracts.py`; `edge/session/turn_state.py`, `edge/turn_detection/*`, `edge/barge_in/detector.py`, `edge/emotion/extractor.py`, `edge/speaker/encoder.py`, `edge/planner/*`; `speech/codec/*`, `speech/moshi_runtime/*`, `speech/decoder/service.py`, `speech/persona/controller.py`; `aux/text_brain/*`, `aux/stt/transcript_service.py`, `aux/fallback/orchestrator.py`; `memory/store.py`, `memory/contracts.py`; `safety/moderation/gate.py`, `safety/voice_policy/policy.py`, `safety/watermark/audioseal.py`; `infra/scaling/scheduler.py`, `infra/deploy/regions.py`, `infra/deploy/rollback.py`; `evals/replay/harness.py`, `evals/latency/metrics.py`; `server/pipeline/*`, `server/utils/*`. |
| api_protocol_reference.md | `server/main.py` (`/health`, `/metrics`, `/api/token`, `/ws/audio/{session_id}`), `server/config.py`, `server/utils/audio.py`. |
| configuration_reference.md | `server/config.py` (every `Settings` subclass + env prefix + defaults), `.env.example`. |

Key verified facts:
- Endpoints `/health`, `/metrics`, `/api/token`, `WS /ws/audio/{session_id}` exist in `server/main.py`.
- Audio handshake: client→server raw PCM16 @ 16 kHz, server→client raw PCM16 @ 24 kHz
  (`SAMPLE_RATE_16K=16000`, `SAMPLE_RATE_24K=24000` in `server/utils/audio.py`).
- Settings subclasses and env prefixes (`LIVEKIT_`, `OLLAMA_`, `WHISPER_`, `TTS_`,
  `SESSION_`, `EMOTION_`, `SPEAKER_`, `FILLER_`, `BARGE_IN_`) match `server/config.py`.
- `TurnState` values match `shared/contracts.py` / `edge/session/turn_state.py`.
- Fallback backends (`MockCodecBackend`, `EchoTransformBackend`, in-memory memory tiers)
  reflect the real CPU/no-weights behavior (DECISIONS.md D-008).
- The `source` array of every JSONL record references a real doc/code path.

## Notes
- The markdown mirror was generated from the JSONL with a throwaway script, then validated
  for consistency and the script removed (no leftover temp files).
- Phase-0 governance docs (`DECISIONS.md`, `INTERFACES.md`, `MODEL_LOCKS.md`,
  `LATENCY_TARGETS.md`, `ASSUMPTIONS.md`, `RISKS.md`, `OPEN_QUESTIONS.md`,
  `AGENT_PROTOCOL.md`) were left untouched and are linked from `docs/index.md`.
