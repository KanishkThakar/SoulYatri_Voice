"""
Tests for training/data_engine/schema.py (Phase 14A).

Covers the non-negotiable rule: every dataset record must carry provenance + consent, and
the validators reject records missing either. Also covers per-kind construction, consent
eligibility, and the dataset manifest summary.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from pydantic import ValidationError

import training.data_engine.schema as S


# ---------------------------------------------------------------------------
# Import hygiene (CPU / no-weights)
# ---------------------------------------------------------------------------
def test_schema_imports_clean() -> None:
    mod = importlib.import_module("training.data_engine.schema")
    assert hasattr(mod, "DatasetRecord")


def test_no_heavy_imports() -> None:
    importlib.import_module("training.data_engine.schema")
    for heavy in ("torch", "transformers", "moshi", "mimi", "peft", "trl"):
        assert heavy not in sys.modules, f"{heavy} must not be imported by schema"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _prov(**kw):
    base = {"source_type": "synthetic", "source_id": "synthetic_v1"}
    base.update(kw)
    return base


def _consent(**kw):
    base = {"status": "not_applicable"}
    base.update(kw)
    return base


def _asr(**kw):
    base = {
        "sample_id": "asr_1",
        "kind": "asr",
        "lang": "hinglish",
        "provenance": _prov(source_type="public_open", source_id="commonvoice_hi_1"),
        "consent": _consent(status="public_license", license="CC0"),
        "audio_path": "/data/a.wav",
        "transcript": "namaste",
        "duration_ms": 1200,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Provenance + consent ENFORCEMENT (core rule)
# ---------------------------------------------------------------------------
def test_record_missing_provenance_rejected() -> None:
    data = _asr()
    del data["provenance"]
    with pytest.raises(S.ProvenanceError):
        S.build_record(data)


def test_record_missing_consent_rejected() -> None:
    data = _asr()
    del data["consent"]
    with pytest.raises(S.ConsentError):
        S.build_record(data)


def test_record_empty_provenance_rejected() -> None:
    data = _asr()
    data["provenance"] = {}
    with pytest.raises(S.ProvenanceError):
        S.build_record(data)


def test_record_none_consent_rejected() -> None:
    data = _asr()
    data["consent"] = None
    with pytest.raises(S.ConsentError):
        S.build_record(data)


def test_granted_consent_requires_consent_id() -> None:
    data = _asr(
        provenance=_prov(source_type="real_consented", source_id="collect_b1"),
        consent={"status": "granted"},  # no consent_id
    )
    with pytest.raises((ValidationError, S.ConsentError)):
        S.build_record(data)


def test_granted_consent_with_id_ok() -> None:
    data = _asr(
        provenance=_prov(source_type="real_consented", source_id="collect_b1"),
        consent={"status": "granted", "consent_id": "consent-001", "subject_id": "subj-7"},
    )
    rec = S.build_record(data)
    assert rec.is_training_eligible is True


def test_public_license_requires_license_string() -> None:
    data = _asr(consent={"status": "public_license"})
    with pytest.raises((ValidationError, S.ConsentError)):
        S.build_record(data)


def test_revoked_consent_not_training_eligible() -> None:
    data = _asr(
        provenance=_prov(source_type="real_consented", source_id="c1"),
        consent={"status": "revoked", "consent_id": "x"},
    )
    rec = S.build_record(data)
    assert rec.is_training_eligible is False


def test_pending_consent_not_training_eligible() -> None:
    data = _asr(
        provenance=_prov(source_type="real_consented", source_id="c1"),
        consent={"status": "pending"},
    )
    rec = S.build_record(data)
    assert rec.is_training_eligible is False


# ---------------------------------------------------------------------------
# Per-kind construction
# ---------------------------------------------------------------------------
def test_build_asr_record() -> None:
    rec = S.build_record(_asr())
    assert isinstance(rec, S.ASRRecord)
    assert rec.kind is S.DataKind.asr
    assert rec.transcript == "namaste"


def test_build_emotion_record_requires_label_or_vad() -> None:
    base = {
        "sample_id": "emo_1",
        "kind": "emotion",
        "provenance": _prov(),
        "consent": _consent(),
    }
    with pytest.raises((ValidationError, ValueError)):
        S.build_record(base)  # no label, no V/A/D
    ok = dict(base, label="warm_ack")
    rec = S.build_record(ok)
    assert isinstance(rec, S.EmotionRecord)
    vad = dict(base, valence=0.5, arousal=0.1)
    rec2 = S.build_record(vad)
    assert rec2.valence == 0.5


def test_build_speaker_record() -> None:
    data = {
        "sample_id": "spk_1",
        "kind": "speaker",
        "provenance": _prov(source_type="public_open", source_id="voxceleb1"),
        "consent": _consent(status="public_license", license="CC-BY"),
        "audio_path": "/d/s.wav",
        "speaker_id": "spk-42",
        "duration_ms": 3000,
    }
    rec = S.build_record(data)
    assert isinstance(rec, S.SpeakerRecord)
    assert rec.speaker_id == "spk-42"


def test_build_hinglish_pair_record() -> None:
    data = {
        "sample_id": "hg_1",
        "kind": "hinglish_pair",
        "provenance": _prov(),
        "consent": _consent(),
        "romanized_text": "namaste",
        "native_text": "नमस्ते",
        "intent": "greeting",
        "emotion": "warm_ack",
    }
    rec = S.build_record(data)
    assert isinstance(rec, S.HinglishPairRecord)
    assert rec.native_text == "नमस्ते"


def test_build_preference_record_chosen_differs() -> None:
    base = {
        "sample_id": "pref_1",
        "kind": "preference",
        "provenance": _prov(),
        "consent": _consent(),
        "prompt": "kaise ho?",
        "chosen": "main theek hoon, aap?",
        "rejected": "theek",
    }
    rec = S.build_record(base)
    assert isinstance(rec, S.PreferenceRecord)
    same = dict(base, chosen="same", rejected="same")
    with pytest.raises((ValidationError, ValueError)):
        S.build_record(same)


def test_unknown_kind_rejected() -> None:
    data = _asr(kind="not_a_kind")
    with pytest.raises(ValueError):
        S.build_record(data)


def test_missing_kind_rejected() -> None:
    data = _asr()
    del data["kind"]
    with pytest.raises(ValueError):
        S.build_record(data)


# ---------------------------------------------------------------------------
# Batch validation + hashing + manifest
# ---------------------------------------------------------------------------
def test_validate_records_separates_valid_and_rejected() -> None:
    good = _asr(sample_id="g1")
    bad = _asr(sample_id="b1")
    del bad["consent"]
    valid, rejected = S.validate_records([good, bad])
    assert len(valid) == 1
    assert len(rejected) == 1
    assert rejected[0]["index"] == 1


def test_record_hash_deterministic() -> None:
    rec = S.build_record(_asr())
    assert S.record_hash(rec) == S.record_hash(rec)
    other = S.build_record(_asr(transcript="alag"))
    assert S.record_hash(rec) != S.record_hash(other)


def test_dataset_manifest_summary() -> None:
    recs = [
        S.build_record(_asr(sample_id="a1")),
        S.build_record(_asr(sample_id="a2")),
    ]
    m = S.DatasetManifest.from_records("ds-1", recs, description="test")
    assert m.record_count == 2
    assert m.counts_by_kind["asr"] == 2
    assert m.training_eligible_count == 2
    assert len(m.dataset_hash) == 64


def test_round_trip_json() -> None:
    rec = S.build_record(_asr())
    dumped = rec.model_dump(mode="json")
    rebuilt = S.build_record(dumped)
    assert rebuilt == rec
