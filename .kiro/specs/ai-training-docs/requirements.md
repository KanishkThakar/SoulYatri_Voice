# Requirements Document

## Introduction

This feature establishes a dedicated documentation folder (`docs/`) for the SoulYatri Speech project that doubles as a curated knowledge base for AI model training and context. The folder will contain two complementary bodies of content: (1) **code documentation** automatically derived from and kept consistent with the existing codebase (architecture overview, module references, API/protocol specs), and (2) **curated training data** (question/answer pairs and worked examples about the project) suitable for fine-tuning or retrieval-augmented generation (RAG).

The end goal is a well-structured, version-controlled `docs/` folder that is pushed to the project's Git remote (`https://github.com/KanishkThakar/SoulYatri_Voice.git`) so it can be consumed by an AI training/context pipeline.

### Scope Summary
- **In scope:** Creating the `docs/` folder structure, authoring code documentation grounded in the real codebase, authoring curated Q&A training data, defining machine-readable formats, and pushing to a Git branch.
- **Out of scope:** Building or running the actual model fine-tuning pipeline, hosting infrastructure, or modifying application source code in `server/` or `client/`.

## Requirements

### Requirement 1 — Documentation Folder Structure

**User Story:** As a project maintainer, I want a clearly organized `docs/` folder, so that both humans and AI training pipelines can reliably locate documentation and training content.

#### Acceptance Criteria

1. WHEN the feature is implemented THEN the system SHALL create a top-level `docs/` directory in the repository root.
2. THE `docs/` directory SHALL contain a `code/` subdirectory for code documentation and a `training/` subdirectory for curated training data.
3. THE `docs/` directory SHALL contain an `index.md` (or `README.md`) that describes the folder's purpose, structure, and intended use as AI training context.
4. WHERE a subdirectory contains content files, THE subdirectory SHALL include a short index file enumerating its contents.
5. THE folder structure SHALL NOT modify or relocate existing application source files under `server/`, `client/`, or `scripts/`.

### Requirement 2 — Code Documentation Grounded in the Codebase

**User Story:** As an AI model consuming project context, I want accurate documentation of the system architecture and modules, so that generated answers reflect the real implementation.

#### Acceptance Criteria

1. THE `docs/code/` directory SHALL include an architecture overview describing the end-to-end voice pipeline (Audio → VAD → STT → LLM → TTS → Audio) and the Phase 2 turn-state/filler/feature components.
2. THE `docs/code/` directory SHALL include a module reference covering the `server/pipeline/` modules (vad, stt, llm, tts, session, turn_state, filler, features, barge_in, speaker, emotion) and `server/utils/` modules (audio, logging_config, metrics).
3. THE `docs/code/` directory SHALL include an API/protocol reference documenting the FastAPI endpoints (`/health`, `/metrics`, `/api/token`) and the `/ws/audio/{session_id}` WebSocket protocol, including control message formats.
4. THE `docs/code/` directory SHALL document the configuration surface defined in `server/config.py` (settings groups and their environment-variable prefixes).
5. WHEN documenting any module, endpoint, or setting, THE content SHALL accurately reflect the names, signatures, and behavior present in the source files and SHALL NOT invent components that do not exist.
6. WHERE source code includes docstrings or comments, THE documentation SHALL be consistent with them.

### Requirement 3 — Curated Training Data

**User Story:** As an ML engineer, I want curated question/answer pairs and examples about the project, so that I can fine-tune or ground a model on accurate, project-specific knowledge.

#### Acceptance Criteria

1. THE `docs/training/` directory SHALL include curated question/answer pairs covering setup, architecture, configuration, and the request/response protocol.
2. THE training data SHALL be provided in a machine-readable format (JSONL) with a documented schema (e.g., fields for `instruction`/`question`, `response`/`answer`, and optional `source`/`tags`).
3. WHERE a human-readable mirror is useful, THE `docs/training/` directory SHALL also provide a Markdown version of the Q&A content.
4. EACH training entry SHALL be factually consistent with the code documentation produced under Requirement 2.
5. THE training data SHALL include at least one worked example demonstrating a typical interaction or task (e.g., starting the server, generating a token, or the audio streaming handshake).

### Requirement 4 — Format and Schema Definition

**User Story:** As a developer integrating the docs into a training pipeline, I want documented, consistent formats, so that the content can be parsed programmatically without guesswork.

#### Acceptance Criteria

1. THE `docs/` folder SHALL document the format conventions used (Markdown for prose, JSONL for structured training data).
2. THE JSONL schema SHALL be documented with field names, types, and an example record.
3. WHEN a JSONL file is produced, EACH line SHALL be a single valid JSON object conforming to the documented schema.
4. IF a consumer parses the JSONL files line by line THEN every line SHALL parse without error.

### Requirement 5 — Version Control and Push

**User Story:** As a project maintainer, I want the docs committed and pushed to the remote, so that the AI training context is shared and reproducible.

#### Acceptance Criteria

1. WHEN the documentation content is complete THEN the system SHALL stage only the files under `docs/` (and spec files) and create a commit with a descriptive message.
2. THE changes SHALL be pushed to a new branch (not directly to `main`) on the `origin` remote, per repository safety conventions.
3. THE commit SHALL NOT include secrets, `.env` files, credentials, or generated model artifacts.
4. IF files outside `docs/` were unintentionally modified THEN the system SHALL exclude them from the commit unless explicitly approved.
5. WHEN the push completes THEN the system SHALL report the branch name and the remote URL so a pull request can be opened.

### Requirement 6 — Maintainability and Accuracy

**User Story:** As a future contributor, I want the docs to stay easy to update and verify, so that the training context does not drift from the code.

#### Acceptance Criteria

1. THE documentation SHALL note, in the index, which source files each major document is derived from.
2. WHERE practical, THE training/Q&A content SHALL reference the doc section or source file it is grounded in.
3. THE JSONL training files SHALL be validated (every line parses as JSON) before commit.
4. THE documentation SHALL avoid duplicating large blocks of source code; instead it SHALL summarize and reference file paths.
