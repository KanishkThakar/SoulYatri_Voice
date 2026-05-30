"""
Tests for training/data_engine/synthetic.py (Phase 14C).

Covers deterministic Hinglish pair generation, the quality filter, provenance/consent
tagging of synthetic records, and the held-out human-eval split.
"""

from __future__ import annotations

import sys

from training.data_engine.schema import ConsentStatus, DataSplit, SourceType
from training.data_engine.synthetic import (
    DEFAULT_TEMPLATES,
    SyntheticConfig,
    SyntheticHinglishEngine,
)


def test_no_heavy_imports() -> None:
    for heavy in ("torch", "transformers", "moshi", "mimi"):
        assert heavy not in sys.modules


def test_generation_is_deterministic() -> None:
    cfg = SyntheticConfig(seed=42, count=6)
    a = SyntheticHinglishEngine(cfg).generate()
    b = SyntheticHinglishEngine(SyntheticConfig(seed=42, count=6)).generate()
    assert len(a) == len(b) == 6
    assert [r.model_dump(mode="json") for r in a] == [r.model_dump(mode="json") for r in b]


def test_different_seed_changes_output() -> None:
    a = SyntheticHinglishEngine(SyntheticConfig(seed=1, count=6)).generate()
    b = SyntheticHinglishEngine(SyntheticConfig(seed=2, count=6)).generate()
    ids_a = [r.sample_id for r in a]
    ids_b = [r.sample_id for r in b]
    # sample_ids embed the seed, so they differ; content ordering should also differ.
    assert ids_a != ids_b


def test_count_respected() -> None:
    recs = SyntheticHinglishEngine(SyntheticConfig(seed=7, count=4)).generate()
    assert len(recs) == 4


def test_zero_count() -> None:
    recs = SyntheticHinglishEngine(SyntheticConfig(seed=7, count=0)).generate()
    assert recs == []


def test_records_have_provenance_and_consent() -> None:
    recs = SyntheticHinglishEngine(SyntheticConfig(seed=3, count=5)).generate()
    for r in recs:
        assert r.provenance.source_type == SourceType.synthetic
        assert r.consent.status == ConsentStatus.not_applicable
        # synthetic = no human subject -> training eligible but must still be reviewed
        assert r.is_training_eligible is True
        assert r.reviewed is False


def test_pairs_have_both_scripts_and_differ() -> None:
    recs = SyntheticHinglishEngine(SyntheticConfig(seed=9, count=6)).generate()
    for r in recs:
        assert r.romanized_text.strip()
        assert r.native_text.strip()
        assert r.romanized_text != r.native_text  # filter guarantees transliteration


def test_no_duplicates_within_run() -> None:
    recs = SyntheticHinglishEngine(SyntheticConfig(seed=11, count=8)).generate()
    keys = {(r.romanized_text, r.native_text) for r in recs}
    assert len(keys) == len(recs)


def test_human_eval_split_present_when_fraction_high() -> None:
    cfg = SyntheticConfig(seed=5, count=8, human_eval_fraction=1.0)
    recs = SyntheticHinglishEngine(cfg).generate()
    assert all(r.split == DataSplit.test for r in recs)


def test_human_eval_split_absent_when_zero() -> None:
    cfg = SyntheticConfig(seed=5, count=8, human_eval_fraction=0.0, split=DataSplit.train)
    recs = SyntheticHinglishEngine(cfg).generate()
    assert all(r.split == DataSplit.train for r in recs)


def test_generate_dicts_are_json_ready() -> None:
    dicts = SyntheticHinglishEngine(SyntheticConfig(seed=2, count=3)).generate_dicts()
    assert len(dicts) == 3
    for d in dicts:
        assert "provenance" in d and "consent" in d
        assert d["kind"] == "hinglish_pair"


def test_default_templates_nonempty_and_distinct_scripts() -> None:
    assert len(DEFAULT_TEMPLATES) >= 5
    for t in DEFAULT_TEMPLATES:
        assert t.romanized != t.native
