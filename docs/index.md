# SoulYatri — Documentation Index

> Top-level entry point for the SoulYatri knowledge base. This index links the
> **frozen governance docs** (Phase 0) and the **code + training knowledge base**
> (Phase 17). Every code doc is grounded in real source files in this repository;
> no modules, endpoints, or settings are invented.

SoulYatri is an open-source, **speech-native**, low-latency, full-duplex, emotional,
Hindi + English + Hinglish conversational voice AI. The canonical runtime loop is
`Audio → Mimi codec tokens → Moshi speech-native runtime → codec tokens → Audio`
(see [DECISIONS.md](DECISIONS.md) D-002).

---

## 1. Governance & architecture freeze (Phase 0)

These documents are the frozen contract. They are **not** modified by Phase 17; the
knowledge base links to and stays consistent with them.

| Doc | Purpose |
|---|---|
| [DECISIONS.md](DECISIONS.md) | Frozen architecture & decision log (D-001 … D-009). |
| [INTERFACES.md](INTERFACES.md) | Single source of truth for cross-subsystem data types; realized in [`shared/contracts.py`](../shared/contracts.py). |
| [MODEL_LOCKS.md](MODEL_LOCKS.md) | Pinned V1 model/artifact manifest. |
| [LATENCY_TARGETS.md](LATENCY_TARGETS.md) | Latency budget and per-stage targets. |
| [ASSUMPTIONS.md](ASSUMPTIONS.md) | Working assumptions. |
| [RISKS.md](RISKS.md) | Risk register. |
| [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) | Unresolved items (instead of improvising). |
| [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md) | Branch/worktree rules, review checklist, definition of done. |

Reference addenda (PDF build bibles, 60-day plan, kill-list, research memo) also live in
this folder and are reference-only — the canonical markdown wins on any conflict.

---

## 2. Code knowledge base (Phase 17B)

Source-grounded documentation of the real codebase. Start at the
[code index](code/index.md).

| Doc | Covers |
|---|---|
| [code/index.md](code/index.md) | Code-docs index + per-doc source provenance. |
| [code/architecture_overview.md](code/architecture_overview.md) | Frozen speech-native loop, domain-folder map, how `server/` gateway + Phase-1 baseline fit. |
| [code/module_reference.md](code/module_reference.md) | Per-subsystem module reference (real names, classes, functions, inputs→outputs). |
| [code/api_protocol_reference.md](code/api_protocol_reference.md) | Real HTTP + WebSocket API from `server/main.py` + the LiveKit token flow. |
| [code/configuration_reference.md](code/configuration_reference.md) | Real settings from `server/config.py` + `.env.example` keys. |

---

## 3. Training corpus (Phase 17C)

A machine-consumable Q&A corpus derived from the code docs. Start at the
[training index](training/index.md).

| File | Purpose |
|---|---|
| [training/index.md](training/index.md) | Training-corpus index + how to consume it. |
| [training/schema.md](training/schema.md) | JSONL record schema + conventions. |
| [training/qa_dataset.jsonl](training/qa_dataset.jsonl) | Canonical Q&A corpus (one JSON object per line). |
| [training/qa_dataset.md](training/qa_dataset.md) | Human-readable mirror of the JSONL. |

Validation: [`scripts/validate_training_jsonl.py`](../scripts/validate_training_jsonl.py)
parses every line and asserts schema conformance. Acceptance is recorded in
[`runs/phase-17-docs/acceptance.md`](../runs/phase-17-docs/acceptance.md).

---

## 4. How to use this knowledge base

- **Humans:** read `code/` for grounded architecture, module, API, and configuration
  references. Read governance docs for *why* the architecture is the way it is.
- **AI pipelines (RAG / fine-tune):** ingest `training/qa_dataset.jsonl`. Each record's
  `source` array points back to the doc/code paths that ground the answer, so retrieval
  and provenance both work without guesswork.
