# Acceptance — Phase 14 Data Engine & Training

**Task:** Implement Phase 14 of `final_use.md` (data engine, synthetic generation,
adaptation, fine-tuning policy) FULLY, **without executing any training run** (out of
scope; CPU-only, no GPU/weights). Build the data engine, schemas, and reproducible
adaptation *scripts* a GPU machine could later run.

**Environment:** Windows, Python 3.11.9, pydantic 2.13.4, ruff 0.15.10, pytest 9.0.2.
CPU-only, no GPU, no Moshi/Mimi weights, no torch/transformers/peft/trl installed.

**File ownership respected.** Created/edited only under:
`training/data_engine/`, `training/labeling/`, `training/sft/`, `training/preference/`,
`training/tests/`, `training/README.md`, and this `runs/phase-14-training/acceptance.md`.
`shared/`, `docs/INTERFACES.md`, `pyproject.toml`, `server/`, and other domains were **not**
modified.

## Files created

- `training/data_engine/schema.py` — 14A dataset schema/registry (ASR, emotion, speaker,
  Hinglish pair, preference) + provenance/consent value objects, validators, hashing,
  `DatasetManifest`.
- `training/data_engine/synthetic.py` — 14C deterministic synthetic Hinglish pair engine
  (Romanized↔native), filtered + reviewable + human-eval split.
- `training/data_engine/manifest.py` — reproducible run-manifest helper (config, seed,
  data hash, metrics; `executed=False` for dry-runs).
- `training/data_engine/logging_util.py` — structured logging hooks (structlog when
  available, stdlib JSON-line fallback).
- `training/data_engine/examples/sample_asr.jsonl` — small example dataset (docs + CLI).
- `training/labeling/review.py` — 14C consented intake + labeling/review state machine.
- `training/sft/lora_sft.py` — 14B SFT/LoRA adaptation scaffolding (dry-run capable, gated,
  manifest-recording).
- `training/preference/dpo_lite.py` — 14B DPO-lite preference optimization scaffolding
  (dry-run capable, gated, manifest-recording).
- `training/tests/__init__.py`, `test_schema.py`, `test_synthetic.py`, `test_review.py`,
  `test_adaptation_scripts.py` — pytest coverage.
- `training/README.md` — design note (Definition of Done §3.3).

## Commands run

```text
# 1. Required import smoke test
python -c "import training.data_engine.schema, training.data_engine.synthetic, training.sft.lora_sft, training.preference.dpo_lite"
→ IMPORT OK                              (exit 0)

# 2. Required test suite
python -m pytest training/tests -q
→ 66 passed in 0.45s                     (exit 0)

# 3. Lint (repo quality gate)
ruff check training
→ All checks passed!                     (exit 0)

# 4. Format check (CI parity)
ruff format --check training
→ all files formatted                    (exit 0)

# 5. End-to-end CLI dry-run (no training executed)
python -m training.sft.lora_sft --target aux_stt \
  --dataset training/data_engine/examples/sample_asr.jsonl \
  --candidate-metric 0.92 --baseline-metric 0.85 --dry-run
→ manifest JSON: executed=false, gate_ok=1.0, records_eligible=2, records_rejected=0  (exit 0)
```

## Phase 14 acceptance (14A / 14B / 14C)

### 14A — dataset registry
- All five dataset kinds have a typed schema; **every record carries provenance + consent**
  (both required fields). Validators reject records missing provenance (`ProvenanceError`)
  or consent (`ConsentError`) — covered by `test_record_missing_provenance_rejected`,
  `test_record_missing_consent_rejected`, `test_record_empty_provenance_rejected`,
  `test_record_none_consent_rejected`.
- Consent consistency enforced: `granted`⇒`consent_id`, `public_license`⇒`license`,
  `revoked`/`pending`⇒not training-eligible.
- `DatasetManifest` summarizes counts and a stable `dataset_hash`.

### 14B — adaptation loops
- `lora_sft.py` (targets: `aux_stt`, `emotion_encoder`, `filler_router`, `main_runtime`)
  and `dpo_lite.py` (targets: `aux_text_brain`, `filler_router`, `main_runtime`) both:
  - import cleanly on CPU (no heavy deps loaded — `test_scripts_import_clean_no_heavy_deps`);
  - `--dry-run` validates inputs (provenance/consent/kind/eligibility) **without training**;
  - record a reproducible `RunManifest` (config, seed, data hash, metrics) — stable
    `data_hash` verified by `test_sft_dry_run_reproducible_data_hash`;
  - enforce the **no-scratch-training** rule via a measurable-gain gate (`GatingError`);
  - raise `TrainingUnavailableError` if an actual run is requested on this CPU/no-GPU host.

### 14C — synthetic + human mix
- Synthetic Hinglish engine is **deterministic** (same seed+count ⇒ identical output),
  **filtered** (no blanks / no-op transliterations / intra-run duplicates), and routes a
  deterministic fraction to a held-out human-eval `test` split.
- Synthetic records are `reviewed=False` and gated by the review workflow.
- `ReviewWorkflow` is an explicit, validated state machine; only `approved` +
  consent-eligible records export to training (`approved_records()`).

## Notes for the evals team

- Consume datasets via `training.data_engine.schema.build_record` / `validate_records`;
  the `test` split (incl. the synthetic engine's `human_eval_fraction` slice) is the
  human-eval set for `evals/hinglish/` and `evals/emotion/`.
- Run manifests expose machine-readable metrics in `manifest.json`: `records_total`,
  `records_eligible`, `records_rejected`, `baseline_metric`, `candidate_metric`,
  `measured_gain`, `min_product_gain`, `gate_ok`. SFT default metric `eval_score`;
  DPO-lite default `preference_win_rate`. The evals harness supplies the measured
  baseline/candidate numbers that drive the adaptation gate.

## Out-of-scope / deferred
- No training executed (no GPU/weights). Actual `Trainer`/`DPOTrainer` wiring is left as a
  documented stub on a GPU host (`run()` raises `TrainingUnavailableError`).
- `structlog` is not installed locally; the logging helper falls back to a stdlib JSON-line
  logger, so structured logging works without the optional dependency.
