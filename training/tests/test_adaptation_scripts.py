"""
Tests for the adaptation scripts (Phase 14B):
  * training/sft/lora_sft.py
  * training/preference/dpo_lite.py

Covers:
  * clean CPU import (no torch/transformers/peft/trl loaded),
  * --dry-run validates inputs (provenance/consent) WITHOUT invoking training,
  * dry-run rejects records missing consent/provenance and filters by kind/eligibility,
  * the measurable-gain gate blocks an actual run,
  * a real run() raises TrainingUnavailableError on this CPU/no-weights host,
  * run manifests are reproducible (config, seed, data hash, metrics) and not "executed".
"""

from __future__ import annotations

import json
import sys

import pytest

from training.preference import dpo_lite
from training.sft import lora_sft


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------
def test_scripts_import_clean_no_heavy_deps() -> None:
    for heavy in ("torch", "transformers", "peft", "trl", "moshi", "mimi"):
        assert heavy not in sys.modules, f"{heavy} must not be imported by adaptation scripts"


# ---------------------------------------------------------------------------
# Fixtures: write small JSONL datasets
# ---------------------------------------------------------------------------
def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(path)


def _asr_row(sample_id, **kw):
    row = {
        "sample_id": sample_id,
        "kind": "asr",
        "lang": "hinglish",
        "provenance": {"source_type": "public_open", "source_id": "commonvoice_hi"},
        "consent": {"status": "public_license", "license": "CC0"},
        "audio_path": "/d/a.wav",
        "transcript": "namaste",
        "duration_ms": 1000,
    }
    row.update(kw)
    return row


def _pref_row(sample_id, **kw):
    row = {
        "sample_id": sample_id,
        "kind": "preference",
        "provenance": {"source_type": "real_consented", "source_id": "collect_b1"},
        "consent": {"status": "granted", "consent_id": "c-1"},
        "prompt": "kaise ho?",
        "chosen": "main theek hoon, aap?",
        "rejected": "theek",
    }
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# SFT dry-run
# ---------------------------------------------------------------------------
def test_sft_dry_run_validates_without_training(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1"), _asr_row("a2")])
    cfg = lora_sft.LoraSFTConfig(target="aux_stt", candidate_metric=0.5, baseline_metric=0.4)
    manifest = lora_sft.dry_run(cfg, ds)
    assert manifest.executed is False
    assert manifest.method == "sft_lora"
    assert manifest.record_count == 2
    assert manifest.metrics["records_eligible"] == 2.0
    assert manifest.metrics["gate_ok"] == 1.0
    assert len(manifest.data_hash) == 64


def test_sft_dry_run_rejects_missing_consent(tmp_path) -> None:
    bad = _asr_row("a1")
    del bad["consent"]
    ds = _write_jsonl(tmp_path / "asr.jsonl", [bad, _asr_row("a2")])
    cfg = lora_sft.LoraSFTConfig(target="aux_stt")
    manifest = lora_sft.dry_run(cfg, ds)
    # one valid, one rejected for missing consent
    assert manifest.metrics["records_eligible"] == 1.0
    assert manifest.metrics["records_rejected"] == 1.0


def test_sft_dry_run_filters_wrong_kind(tmp_path) -> None:
    # emotion record fed to an aux_stt target -> rejected by kind filter
    emo = {
        "sample_id": "e1",
        "kind": "emotion",
        "provenance": {"source_type": "synthetic", "source_id": "v1"},
        "consent": {"status": "not_applicable"},
        "label": "warm_ack",
    }
    ds = _write_jsonl(tmp_path / "mix.jsonl", [_asr_row("a1"), emo])
    cfg = lora_sft.LoraSFTConfig(target="aux_stt")
    manifest = lora_sft.dry_run(cfg, ds)
    assert manifest.metrics["records_eligible"] == 1.0
    assert manifest.metrics["records_rejected"] == 1.0


def test_sft_dry_run_reproducible_data_hash(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1"), _asr_row("a2")])
    cfg = lora_sft.LoraSFTConfig(target="aux_stt", seed=99)
    m1 = lora_sft.dry_run(cfg, ds)
    m2 = lora_sft.dry_run(lora_sft.LoraSFTConfig(target="aux_stt", seed=99), ds)
    assert m1.data_hash == m2.data_hash
    assert m1.seed == m2.seed == 99


def test_sft_dry_run_writes_manifest_note(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1")])
    runs = tmp_path / "runs"
    cfg = lora_sft.LoraSFTConfig(target="aux_stt", candidate_metric=0.5, baseline_metric=0.4)
    lora_sft.dry_run(cfg, ds, runs_dir=str(runs))
    written = list(runs.rglob("manifest.json"))
    assert written, "dry-run should write a manifest.json note"
    assert (written[0].parent / "manifest.md").exists()


def test_sft_run_blocked_by_gate(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1")])
    # candidate not better than baseline -> gate blocks
    cfg = lora_sft.LoraSFTConfig(
        target="aux_stt", baseline_metric=0.5, candidate_metric=0.5, min_product_gain=0.01
    )
    with pytest.raises(lora_sft.GatingError):
        lora_sft.run(cfg, ds)


def test_sft_run_raises_training_unavailable(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1")])
    # gate passes, but no GPU/training stack present -> TrainingUnavailableError
    cfg = lora_sft.LoraSFTConfig(
        target="aux_stt", baseline_metric=0.4, candidate_metric=0.9, min_product_gain=0.01
    )
    with pytest.raises(lora_sft.TrainingUnavailableError):
        lora_sft.run(cfg, ds)


def test_sft_cli_dry_run(tmp_path, capsys) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1")])
    rc = lora_sft.main(["--target", "aux_stt", "--dataset", ds, "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["executed"] is False
    assert out["method"] == "sft_lora"


def test_sft_cli_real_run_returns_error_code(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "asr.jsonl", [_asr_row("a1")])
    # no --dry-run, gate fails by default (0.0 vs 0.0 < 0.01) -> non-zero exit
    rc = lora_sft.main(["--target", "aux_stt", "--dataset", ds])
    assert rc == 2


def test_sft_invalid_target_rejected() -> None:
    with pytest.raises(ValueError):
        lora_sft.LoraSFTConfig(target="nonexistent")


# ---------------------------------------------------------------------------
# DPO-lite dry-run
# ---------------------------------------------------------------------------
def test_dpo_dry_run_validates_without_training(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "pref.jsonl", [_pref_row("p1"), _pref_row("p2")])
    cfg = dpo_lite.DPOLiteConfig(target="aux_text_brain", baseline_metric=0.5, candidate_metric=0.6)
    manifest = dpo_lite.dry_run(cfg, ds)
    assert manifest.executed is False
    assert manifest.method == "dpo_lite"
    assert manifest.record_count == 2
    assert manifest.metrics["gate_ok"] == 1.0


def test_dpo_dry_run_rejects_missing_provenance(tmp_path) -> None:
    bad = _pref_row("p1")
    del bad["provenance"]
    ds = _write_jsonl(tmp_path / "pref.jsonl", [bad, _pref_row("p2")])
    cfg = dpo_lite.DPOLiteConfig(target="aux_text_brain")
    manifest = dpo_lite.dry_run(cfg, ds)
    assert manifest.metrics["records_eligible"] == 1.0
    assert manifest.metrics["records_rejected"] == 1.0


def test_dpo_run_blocked_by_gate(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "pref.jsonl", [_pref_row("p1")])
    cfg = dpo_lite.DPOLiteConfig(
        target="aux_text_brain", baseline_metric=0.5, candidate_metric=0.5, min_product_gain=0.02
    )
    with pytest.raises(dpo_lite.GatingError):
        dpo_lite.run(cfg, ds)


def test_dpo_run_raises_training_unavailable(tmp_path) -> None:
    ds = _write_jsonl(tmp_path / "pref.jsonl", [_pref_row("p1")])
    cfg = dpo_lite.DPOLiteConfig(
        target="aux_text_brain", baseline_metric=0.4, candidate_metric=0.9, min_product_gain=0.02
    )
    with pytest.raises(dpo_lite.TrainingUnavailableError):
        dpo_lite.run(cfg, ds)


def test_dpo_cli_dry_run(tmp_path, capsys) -> None:
    ds = _write_jsonl(tmp_path / "pref.jsonl", [_pref_row("p1")])
    rc = dpo_lite.main(["--target", "aux_text_brain", "--dataset", ds, "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["executed"] is False
    assert out["method"] == "dpo_lite"


def test_dpo_invalid_beta_rejected() -> None:
    with pytest.raises(ValueError):
        dpo_lite.DPOLiteConfig(beta=2.0)


def test_dpo_missing_dataset_raises(tmp_path) -> None:
    cfg = dpo_lite.DPOLiteConfig(target="aux_text_brain")
    with pytest.raises(FileNotFoundError):
        dpo_lite.dry_run(cfg, tmp_path / "nope.jsonl")
