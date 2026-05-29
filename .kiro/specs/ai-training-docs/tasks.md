# Implementation Plan

## Overview

This plan builds a `docs/` folder that serves as AI training context for the SoulYatri Voice project. Task 1 scaffolds the folder structure and conventions, tasks 2.x author code documentation grounded in `server/**`, tasks 3.x author curated training data derived from those code docs, task 4 validates the JSONL artifacts, and task 5 commits and pushes the result to a new branch. Each task builds on the previous ones so there is no orphaned content.

## Tasks

- [ ] 1. Scaffold the docs folder structure
  - Create `docs/` with `code/` and `training/` subdirectories
  - Create `docs/README.md` describing purpose, structure, and how to consume the folder as AI training context, including a provenance note that content derives from `server/**`
  - Create `docs/FORMATS.md` documenting Markdown/JSONL conventions and the canonical JSONL schemas (Q&A and worked-example) with field tables and an example record
  - _Requirements: 1.1, 1.2, 1.3, 4.1, 4.2_

- [ ] 2. Author code documentation grounded in the source
- [ ] 2.1 Write the architecture overview
  - Create `docs/code/architecture.md` covering the Phase 1 pipeline (Audio → WebRTC → VAD → STT → LLM → TTS → Audio) and Phase 2 `VoiceAgent` orchestration (turn state machine, filler routing actions, parallel emotion+speaker extraction, barge-in)
  - Include the component-to-technology mapping (Silero VAD, faster-whisper, Ollama Qwen3, edge-tts)
  - Ensure names/behavior match `server/main.py` and `server/agent.py`
  - _Requirements: 2.1, 2.5, 2.6, 6.4_
- [ ] 2.2 Write the module reference
  - Create `docs/code/module-reference.md` covering every `server/pipeline/*` module (vad, stt, llm, tts, session, turn_state, filler, features, emotion, speaker, barge_in) and `server/utils/*` module (audio, metrics, logging_config)
  - Document key public classes/dataclasses and methods using exact names from source; reference file paths instead of pasting large code blocks
  - _Requirements: 2.2, 2.5, 2.6, 6.4_
- [ ] 2.3 Write the API/protocol reference
  - Create `docs/code/api-protocol.md` documenting `GET /health`, `GET /metrics`, `GET /api/token`, and the `WS /ws/audio/{session_id}` protocol (binary PCM frame rates, JSON control messages `config`/`end`, and server events `transcript`/`audio_meta`/`turn_metadata`)
  - Match the exact behavior in `server/main.py`
  - _Requirements: 2.3, 2.5, 6.4_
- [ ] 2.4 Write the configuration reference
  - Create `docs/code/configuration.md` documenting each settings group in `server/config.py` with its env-var prefix (root `SERVER_`/`LOG_`, `LIVEKIT_`, `OLLAMA_`, `WHISPER_`, `TTS_`, `SESSION_`, `EMOTION_`, `SPEAKER_`, `FILLER_`, `BARGE_IN_`), cross-referenced with `.env.example`
  - _Requirements: 2.4, 2.5, 6.4_
- [ ] 2.5 Write the code docs index with provenance
  - Create `docs/code/index.md` listing each code document and the source files it derives from
  - _Requirements: 1.4, 6.1_

- [ ] 3. Author curated training data
- [ ] 3.1 Create the Q&A dataset
  - Create `docs/training/qa.jsonl` with 20+ records conforming to the Q&A schema, spanning setup, architecture, configuration, protocol, and modules
  - Set the `source` field of each record to the doc section/file it is grounded in, and keep every `answer` consistent with `docs/code/*`
  - Create `docs/training/qa.md` as a human-readable mirror grouped by topic
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 6.2_
- [ ] 3.2 Create worked examples
  - Create `docs/training/examples.jsonl` with at least 3 records conforming to the worked-example schema (e.g., quick-start sequence, generating a LiveKit token via `/api/token`, the WebSocket audio handshake)
  - _Requirements: 3.5_
- [ ] 3.3 Write the training index
  - Create `docs/training/index.md` listing the training files and pointing to the schema in `docs/FORMATS.md`
  - _Requirements: 1.4_

- [ ] 4. Validate the data artifacts
  - Write a small validator that reads each `.jsonl` file line by line, asserts each line parses as a standalone JSON object, checks required schema fields are present and non-empty, and verifies `id` uniqueness within each file
  - Run the validator and fix any malformed lines or duplicate IDs
  - _Requirements: 4.3, 4.4, 6.3_

- [ ] 5. Commit and push to a new branch
  - Create and switch to a new branch `docs/ai-training-context`
  - Stage only `docs/**` and `.kiro/specs/**` explicitly (no `git add .`); verify the staged file list excludes `.env`, credentials, and any files outside scope
  - Commit with a descriptive message and push with upstream tracking to `origin`
  - Report the branch name and remote URL so a pull request can be opened
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

## Notes

- Task 1 establishes the folder structure and JSONL conventions that every later task relies on.
- Tasks 2.x author the code documentation that grounds the curated training data in tasks 3.x.
- Task 4 validates the JSONL artifacts produced in tasks 3.x before they are shared.
- Task 5 is the final integration step that commits and pushes the completed docs folder.
- Each task references specific requirements for traceability.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4"] },
    { "id": 4, "tasks": ["5"] }
  ]
}
```
