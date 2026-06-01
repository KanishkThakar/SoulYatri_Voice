# training/ — Data Engine & Adaptation (Phase 14)

Owner: data/training agent (`final_use.md` §4, Phase 14).

This subsystem builds the SoulYatri **data moat** without violating the non-negotiable
**no-scratch-training** rule (`final_use.md` §1.3, DECISIONS.md D-005). It provides the
dataset schema/registry, a synthetic Hinglish prompt engine, a consented collection +
review workflow, and reproducible SFT/LoRA + DPO-lite **adaptation scaffolding** that a
GPU host can later run.

> **Environment note:** this code is built and verified on a **CPU-only machine with no GPU
> and no model weights**. No training is executed here. Every module imports cleanly on CPU
> (no top-level `torch` / `transformers` / `peft` / `trl` / `moshi` / `mimi`), and the
> adaptation scripts expose a `--dry-run` that validates inputs without training.

## Layout

```
training/
  data_engine/
    schema.py        # 14A — dataset schema/registry; provenance + consent enforced
    synthetic.py     # 14C — deterministic synthetic Hinglish (Romanized↔native) engine
    manifest.py      # reproducible run manifests (config, seed, data hash, metrics)
    logging_util.py  # structured logging hooks (structlog when available, stdlib fallback)
    examples/        # tiny example JSONL used by docs and CLI smoke checks
  labeling/
    review.py        # 14C — consented intake + labeling/review state machine
  sft/
    lora_sft.py      # 14B — SFT/LoRA adaptation scaffolding (dry-run capable, gated)
  preference/
    dpo_lite.py      # 14B — DPO-lite preference optimization scaffolding (dry-run capable)
  tests/             # pytest coverage for all of the above
```

## 14A — Dataset schema & registry (`data_engine/schema.py`)

Five record kinds, each a pydantic v2 model with a shared `RecordBase`:

| Kind | Model | Carries |
|---|---|---|
| `asr` | `ASRRecord` | audio path, transcript, duration, `romanized` flag |
| `emotion` | `EmotionRecord` | discrete label and/or continuous V/A/D (compatible with `shared.contracts.EmotionState`) |
| `speaker` | `SpeakerRecord` | speaker id, duration, ECAPA embedding dim |
| `hinglish_pair` | `HinglishPairRecord` | Romanized ↔ native text, intent, emotion, `reviewed` |
| `preference` | `PreferenceRecord` | prompt / chosen / rejected (+ optional margin) for DPO-lite |

**Non-negotiable rule — every record carries provenance + consent.** Both `provenance`
and `consent` are **required** fields (no default), and `build_record()` raises
`ProvenanceError` / `ConsentError` before model coercion if either is missing. Consent
consistency is enforced:

- `granted` → requires a `consent_id` (proof on file);
- `public_license` → requires a `license` string;
- `revoked` / `pending` → **not** training-eligible (`is_training_eligible == False`).

`DatasetManifest.from_records()` summarizes counts by kind/split/consent and computes a
stable `dataset_hash` for reproducibility.

The starter record from `final_use.md` §14 is a strict subset of this schema:

```json
{"sample_id":"...","lang":"hinglish","romanized":true,"emotion":"warm_ack",
 "source":"synthetic_v1","consent":"n/a","split":"train"}
```

## 14C — Synthetic + human mix

**`data_engine/synthetic.py`** — `SyntheticHinglishEngine` produces Romanized↔native
Hinglish pairs from a curated, reviewable fragment bank. It is:

- **deterministic** — same `seed` + `count` ⇒ identical records (per-slot RNG keyed by
  `seed:index`), so a GPU host reproduces the corpus exactly;
- **filtered** — drops blank sides, no-op transliterations, and intra-run duplicates;
- **reviewable + measurable** — every record is `reviewed=False` (must pass review) and a
  deterministic fraction is routed to a held-out `test` split for human-eval comparison.

Synthetic records are tagged `source_type=synthetic` + `consent=not_applicable` (no human
subject), so they are training-eligible by consent **but still gated by human review**.

**`labeling/review.py`** — two pieces:

- `CollectionIntake` — the front door for consented real-utterance collection; rejects any
  record missing provenance/consent and any `real_consented` record that is not yet
  consent-eligible (e.g. `pending`).
- `ReviewWorkflow` — an explicit, validated state machine (no hidden if-else sprawl):

  ```
  pending --claim--> in_review --approve--> approved (terminal)
                              --reject--> rejected (terminal)
                              --request_changes--> needs_changes --resubmit--> pending
  ```

  `approved_records()` is the **only** export path to training and double-gates on
  `state == approved` **and** `is_training_eligible` (consent).

## 14B — Adaptation scaffolding

Reproducible, metric-recording, **dry-run-capable** scripts. Both gate adaptation on a
**measurable product gain** (`candidate_metric - baseline_metric >= min_product_gain`),
honoring the no-scratch-training rule and `final_use.md` §13.3 priority order.

**`sft/lora_sft.py`** — SFT/LoRA for `aux_stt`, `emotion_encoder`, `filler_router`, and
(cautiously) `main_runtime` adapters.

**`preference/dpo_lite.py`** — DPO-lite preference optimization (applied *after* SFT) for
`aux_text_brain`, `filler_router`, `main_runtime`.

Both expose the same flow:

```bash
# Validate config + dataset (provenance/consent) WITHOUT training:
python -m training.sft.lora_sft --target aux_stt \
  --dataset training/data_engine/examples/sample_asr.jsonl \
  --candidate-metric 0.92 --baseline-metric 0.85 --dry-run

python -m training.preference.dpo_lite --target aux_text_brain \
  --dataset path/to/preferences.jsonl --dry-run
```

`dry_run()` returns a `RunManifest` (`executed=False`) capturing config, seed, data hash,
record counts, the gate result, and metrics; `--runs-dir` writes a `manifest.json` +
`manifest.md` note. Calling `run()` (no `--dry-run`):

1. validates inputs, then
2. enforces the gate (`GatingError` if the gain is insufficient), then
3. lazily imports the heavy training stack — which is absent here, so it raises
   `TrainingUnavailableError` instead of pretending to train.

## Structured logging

`data_engine/logging_util.get_logger()` returns a `structlog` logger when available (repo
standard, see `server/utils/logging_config.py`) and falls back to a stdlib JSON-line shim
otherwise, so the subsystem logs structured events without requiring optional deps.

## Verification

```bash
python -c "import training.data_engine.schema, training.data_engine.synthetic, training.sft.lora_sft, training.preference.dpo_lite"
python -m pytest training/tests -q       # 66 passed
ruff check training                      # All checks passed!
```

See `runs/phase-14-training/acceptance.md` for recorded acceptance evidence.

## Notes for the evals team

- **Dataset schema → evals contract.** Held-out evaluation should consume `DatasetRecord`s
  via `training.data_engine.schema.build_record` / `validate_records`. The `test` split
  (including the synthetic engine's `human_eval_fraction` slice) is the human-eval set for
  Hinglish/emotion measurement (`evals/hinglish/`, `evals/emotion/`).
- **Metrics recorded in run manifests** (machine-readable in `manifest.json`):
  `records_total`, `records_eligible`, `records_rejected`, `baseline_metric`,
  `candidate_metric`, `measured_gain`, `min_product_gain`, `gate_ok`. SFT default metric is
  `eval_score`; DPO-lite default is `preference_win_rate`. These map onto the
  `final_use.md` §12 evaluation matrix (intelligibility/WER, emotion agreement, code-switch
  fluency) — the evals harness supplies the actual measured numbers that fill
  `baseline_metric`/`candidate_metric` so the gate reflects real product gain.
- **Consent gating is structural.** Only `approved_records()` and training-eligible consent
  states reach adaptation; `revoked`/`pending` are excluded automatically.
