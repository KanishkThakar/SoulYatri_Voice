# Training Corpus — Index

> A machine-consumable Q&A corpus (Phase 17C) derived from the code knowledge base. Every
> record is grounded in `docs/code/*.md` and the real source files those docs describe.

## Files

| File | Purpose |
|---|---|
| [schema.md](schema.md) | The JSONL record schema (`instruction`, `response`, `source`, `tags`) + conventions. |
| [qa_dataset.jsonl](qa_dataset.jsonl) | Canonical corpus — one JSON object per line. The artifact a fine-tune / RAG pipeline ingests. |
| [qa_dataset.md](qa_dataset.md) | Human-readable mirror of the JSONL, grouped by topic. |

## How to consume

- **RAG:** index each record's `response` keyed by `instruction`; use `source` for citation
  and `tags` for filtering. Because `source` points at real doc/code paths, retrieval can
  surface the grounding document alongside the answer.
- **Instruction fine-tune:** map `instruction → response` directly; the corpus already uses
  the common `instruction`/`response` field names.

## Coverage

The corpus includes worked examples for the topics required by `final_use.md` §17C:

- what the core speech-native runtime is,
- how to start the server,
- the LiveKit token flow,
- the WebSocket audio handshake,
- the turn-state machine,
- the filler / classic-fallback policy,
- safety / consent,
- memory tiers,

plus architecture, module, API, and configuration questions derived from the code docs.

## Validation & acceptance

Validate every line with:

```bash
python scripts/validate_training_jsonl.py
```

Acceptance evidence (file list + validator output) is recorded in
[`runs/phase-17-docs/acceptance.md`](../../runs/phase-17-docs/acceptance.md).
