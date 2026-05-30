"""
Tests for training/labeling/review.py (Phase 14C).

Covers the collection intake (provenance/consent enforcement at the front door) and the
review workflow state machine (valid + invalid transitions, approved-records export).
"""

from __future__ import annotations

import pytest

from training.data_engine.schema import ConsentError, build_record
from training.labeling.review import (
    ALLOWED_TRANSITIONS,
    CollectionIntake,
    ReviewAction,
    ReviewState,
    ReviewTransitionError,
    ReviewWorkflow,
)


def _hinglish(sample_id="hg_1", **prov_consent):
    data = {
        "sample_id": sample_id,
        "kind": "hinglish_pair",
        "provenance": {"source_type": "synthetic", "source_id": "synthetic_v1"},
        "consent": {"status": "not_applicable"},
        "romanized_text": "namaste",
        "native_text": "नमस्ते",
        "intent": "greeting",
        "emotion": "warm_ack",
    }
    data.update(prov_consent)
    return build_record(data)


# ---------------------------------------------------------------------------
# Collection intake
# ---------------------------------------------------------------------------
def test_intake_accepts_valid_synthetic() -> None:
    intake = CollectionIntake()
    rec = intake.submit(
        {
            "sample_id": "hg_1",
            "kind": "hinglish_pair",
            "provenance": {"source_type": "synthetic", "source_id": "synthetic_v1"},
            "consent": {"status": "not_applicable"},
            "romanized_text": "namaste",
            "native_text": "नमस्ते",
        }
    )
    assert rec.sample_id == "hg_1"
    assert len(intake.accepted) == 1


def test_intake_rejects_missing_consent() -> None:
    intake = CollectionIntake()
    with pytest.raises(ConsentError):
        intake.submit(
            {
                "sample_id": "hg_2",
                "kind": "hinglish_pair",
                "provenance": {"source_type": "synthetic", "source_id": "v1"},
                "romanized_text": "namaste",
                "native_text": "नमस्ते",
            }
        )
    assert len(intake.rejected) == 1


def test_intake_rejects_unconsented_real_utterance() -> None:
    intake = CollectionIntake()
    with pytest.raises(ConsentError):
        intake.submit(
            {
                "sample_id": "real_1",
                "kind": "asr",
                "provenance": {"source_type": "real_consented", "source_id": "collect_b1"},
                "consent": {"status": "pending"},  # collected but not yet confirmed
                "audio_path": "/d/a.wav",
                "transcript": "namaste",
                "duration_ms": 1000,
            }
        )


def test_intake_accepts_consented_real_utterance() -> None:
    intake = CollectionIntake()
    rec = intake.submit(
        {
            "sample_id": "real_2",
            "kind": "asr",
            "provenance": {"source_type": "real_consented", "source_id": "collect_b1"},
            "consent": {"status": "granted", "consent_id": "consent-9", "subject_id": "subj-1"},
            "audio_path": "/d/a.wav",
            "transcript": "namaste",
            "duration_ms": 1000,
        }
    )
    assert rec.is_training_eligible is True


# ---------------------------------------------------------------------------
# Review workflow state machine
# ---------------------------------------------------------------------------
def test_enqueue_starts_pending() -> None:
    wf = ReviewWorkflow()
    item = wf.add(_hinglish())
    assert item.state is ReviewState.pending
    assert len(wf) == 1


def test_happy_path_approve() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("hg_a"))
    wf.apply("hg_a", ReviewAction.claim, reviewer="alice")
    item = wf.apply("hg_a", ReviewAction.approve, reviewer="alice", note="looks good")
    assert item.state is ReviewState.approved
    assert item.reviewer == "alice"
    assert "looks good" in item.notes
    # history records the transitions
    assert (ReviewState.pending, ReviewAction.claim, ReviewState.in_review) in item.history


def test_reject_path() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("hg_r"))
    wf.apply("hg_r", ReviewAction.claim)
    item = wf.apply("hg_r", ReviewAction.reject, note="bad transliteration")
    assert item.state is ReviewState.rejected


def test_needs_changes_then_resubmit_cycle() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("hg_c"))
    wf.apply("hg_c", ReviewAction.claim)
    wf.apply("hg_c", ReviewAction.request_changes, note="fix emotion tag")
    assert wf.get("hg_c").state is ReviewState.needs_changes
    wf.apply("hg_c", ReviewAction.resubmit)
    assert wf.get("hg_c").state is ReviewState.pending
    wf.apply("hg_c", ReviewAction.claim)
    item = wf.apply("hg_c", ReviewAction.approve)
    assert item.state is ReviewState.approved


def test_invalid_transition_rejected() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("hg_x"))
    # cannot approve directly from pending
    with pytest.raises(ReviewTransitionError):
        wf.apply("hg_x", ReviewAction.approve)


def test_terminal_state_rejects_actions() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("hg_t"))
    wf.apply("hg_t", ReviewAction.claim)
    wf.apply("hg_t", ReviewAction.reject)
    with pytest.raises(ReviewTransitionError):
        wf.apply("hg_t", ReviewAction.claim)


def test_duplicate_sample_id_rejected() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("dup"))
    with pytest.raises(ValueError):
        wf.add(_hinglish("dup"))


def test_approved_records_export_gated_by_consent() -> None:
    wf = ReviewWorkflow()
    # eligible synthetic record
    wf.add(_hinglish("ok"))
    wf.apply("ok", ReviewAction.claim)
    wf.apply("ok", ReviewAction.approve)

    # approved but consent revoked -> must NOT be exported
    revoked = build_record(
        {
            "sample_id": "revoked",
            "kind": "asr",
            "provenance": {"source_type": "real_consented", "source_id": "c1"},
            "consent": {"status": "revoked", "consent_id": "x"},
            "audio_path": "/d/a.wav",
            "transcript": "x",
            "duration_ms": 100,
        }
    )
    wf.add(revoked)
    wf.apply("revoked", ReviewAction.claim)
    wf.apply("revoked", ReviewAction.approve)

    exported = wf.approved_records()
    ids = {r.sample_id for r in exported}
    assert "ok" in ids
    assert "revoked" not in ids


def test_summary_counts() -> None:
    wf = ReviewWorkflow()
    wf.add(_hinglish("s1"))
    wf.add(_hinglish("s2"))
    wf.apply("s1", ReviewAction.claim)
    summary = wf.summary()
    assert summary["pending"] == 1
    assert summary["in_review"] == 1


def test_transition_table_terminal_states_have_no_exits() -> None:
    assert ALLOWED_TRANSITIONS[ReviewState.approved] == {}
    assert ALLOWED_TRANSITIONS[ReviewState.rejected] == {}
