# Training Corpus — Schema

> Defines the canonical JSONL record schema for the SoulYatri Q&A training corpus
> (`qa_dataset.jsonl`) so any consumer (fine-tune or RAG pipeline) can parse it without
> guesswork. The schema follows the `final_use.md` §Phase-17 JSONL example.

## Record schema

Each line of `qa_dataset.jsonl` is exactly one JSON object with these keys:

| Field | Type | Required | Description |
|---|---|---|---|
| `instruction` | string | yes | A natural-language question or task about the project. |
| `response` | string | yes | The accurate answer, grounded in the code docs. |
| `source` | array of strings | yes | Real doc/code paths that ground the answer (provenance). |
| `tags` | array of strings | yes | Topic tags for filtering/routing (e.g. `["architecture","runtime"]`). |

### Canonical example (from `final_use.md` §Phase-17)

```json
{"instruction":"What is the core Soulyatri runtime?","response":"A speech-native Mimi→Moshi→decoder loop with auxiliary text services for memory and tools.","source":["docs/code/architecture_overview.md"],"tags":["architecture","runtime"]}
```

## Conventions

- **One JSON object per line.** No array wrapper, no trailing commas, no comments.
- **UTF-8** encoding. Each line must independently `json.loads()` without error.
- `instruction` and `response` are non-empty strings.
- `source` is a non-empty array; every entry is a path that exists in the repo (a doc under
  `docs/` or a source file/module). Provenance lets a RAG pipeline trace each answer back to
  its grounding.
- `tags` is a non-empty array of lowercase topic strings.
- Answers must stay consistent with the corresponding `docs/code/*.md` section — the
  Markdown is the grounding source; the JSONL is the machine-consumable derivative.

## Validation

`scripts/validate_training_jsonl.py` enforces this schema. It parses
`docs/training/qa_dataset.jsonl` line by line and asserts, for every line:

1. the line is valid standalone JSON (an object),
2. all required keys are present (`instruction`, `response`, `source`, `tags`),
3. `instruction` and `response` are non-empty strings,
4. `source` and `tags` are non-empty arrays of strings.

Run it from the repo root:

```bash
python scripts/validate_training_jsonl.py
```

A non-zero exit code means at least one line failed; the script prints the offending line
number and reason. Acceptance output is recorded in
[`runs/phase-17-docs/acceptance.md`](../../runs/phase-17-docs/acceptance.md).

## Relationship to `INTERFACES.md`

This is a **documentation/training** schema, distinct from the runtime contracts in
[INTERFACES.md](../INTERFACES.md) / `shared/contracts.py`. It exists only to package
project knowledge for ingestion; it does not affect runtime behavior.
