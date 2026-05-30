"""
Phase 9A tests — emotion latent schema clamping + serialization.

Covers: clamp keeps values in range, NaN/inf coercion, make_emotion, blend/nudge,
dict/json round-trips, and attach/recover from turn context.
"""

from __future__ import annotations

import math

import pytest

from shared.contracts import EmotionState
from speech.persona import emotion_schema as es


# ---------------------------------------------------------------------------
# Import hygiene — must stay CPU-only / no heavy deps (DECISIONS.md D-008).
# ---------------------------------------------------------------------------
def test_no_heavy_imports() -> None:
    import sys

    for heavy in ("torch", "transformers", "moshi", "mimi", "numpy"):
        assert heavy not in sys.modules, f"{heavy} must not be imported by the persona layer"


# ---------------------------------------------------------------------------
# Field taxonomy / ranges
# ---------------------------------------------------------------------------
def test_field_ranges() -> None:
    assert es.field_range("valence") == (-1.0, 1.0)
    assert es.field_range("arousal") == (-1.0, 1.0)
    assert es.field_range("dominance") == (-1.0, 1.0)
    assert es.field_range("warmth") == (0.0, 1.0)
    assert es.field_range("pace") == (0.0, 1.0)
    with pytest.raises(KeyError):
        es.field_range("nope")


# ---------------------------------------------------------------------------
# Clamping
# ---------------------------------------------------------------------------
def test_clamp_keeps_values_in_range() -> None:
    # Out-of-range values are squeezed in (not rejected).
    emo = es.make_emotion(
        valence=5.0,  # -> 1.0
        arousal=-9.0,  # -> -1.0
        dominance=0.3,  # in range
        warmth=2.0,  # -> 1.0
        uncertainty=-1.0,  # -> 0.0
        pace=0.7,  # in range
        intensity=10.0,  # -> 1.0
        confidence=0.9,
    )
    assert emo.valence == 1.0
    assert emo.arousal == -1.0
    assert emo.dominance == 0.3
    assert emo.warmth == 1.0
    assert emo.uncertainty == 0.0
    assert emo.pace == 0.7
    assert emo.intensity == 1.0
    # All fields satisfy the contract's own validation.
    assert -1.0 <= emo.valence <= 1.0
    assert 0.0 <= emo.warmth <= 1.0


def test_clamp_handles_nan_and_inf() -> None:
    emo = es.make_emotion(valence=float("nan"), arousal=float("inf"), warmth=float("-inf"))
    assert not math.isnan(emo.valence) and not math.isinf(emo.valence)
    assert -1.0 <= emo.arousal <= 1.0
    assert 0.0 <= emo.warmth <= 1.0


def test_clamp_emotion_accepts_emotion_state() -> None:
    base = EmotionState(valence=0.4, warmth=0.6)
    clamped = es.clamp_emotion(base)
    assert clamped == base  # already valid -> unchanged


def test_clamp_preserves_label() -> None:
    emo = es.make_emotion(valence=2.0, label="happy")
    assert emo.label == "happy"
    assert emo.valence == 1.0


# ---------------------------------------------------------------------------
# blend / nudge (pure transforms)
# ---------------------------------------------------------------------------
def test_blend_is_linear_and_clamped() -> None:
    a = EmotionState(valence=-1.0, warmth=0.0)
    b = EmotionState(valence=1.0, warmth=1.0)
    mid = es.blend(a, b, weight=0.5)
    assert abs(mid.valence - 0.0) < 1e-9
    assert abs(mid.warmth - 0.5) < 1e-9
    # weight 0 -> a, weight 1 -> b
    assert es.blend(a, b, weight=0.0).valence == a.valence
    assert es.blend(a, b, weight=1.0).valence == b.valence
    # out-of-range weight is clamped
    assert es.blend(a, b, weight=5.0).valence == b.valence


def test_nudge_adds_then_clamps() -> None:
    emo = EmotionState(warmth=0.5, arousal=0.0)
    out = es.nudge(emo, warmth=+0.9, arousal=-0.5)
    assert out.warmth == 1.0  # 0.5 + 0.9 clamped to 1.0
    assert abs(out.arousal - (-0.5)) < 1e-9
    with pytest.raises(KeyError):
        es.nudge(emo, bogus=0.1)


# ---------------------------------------------------------------------------
# Serialization round-trips
# ---------------------------------------------------------------------------
def test_dict_roundtrip() -> None:
    emo = EmotionState(
        valence=0.62,
        arousal=0.31,
        dominance=0.58,
        warmth=0.8,
        uncertainty=0.14,
        pace=0.5,
        intensity=0.47,
    )
    d = es.to_dict(emo)
    rebuilt = es.from_dict(d)
    assert rebuilt == emo


def test_json_roundtrip_stable_keys() -> None:
    emo = EmotionState(valence=0.62, warmth=0.8)
    blob = es.to_json(emo, round_to=4)
    # JSON keys are sorted for deterministic logs.
    assert blob.index('"arousal"') < blob.index('"valence"')
    rebuilt = es.from_json(blob)
    assert abs(rebuilt.valence - emo.valence) < 1e-3
    assert abs(rebuilt.warmth - emo.warmth) < 1e-3


def test_to_dict_rounding() -> None:
    emo = EmotionState(valence=0.123456789)
    d = es.to_dict(emo, round_to=3)
    assert d["valence"] == 0.123


# ---------------------------------------------------------------------------
# Turn-context attach / recover
# ---------------------------------------------------------------------------
def test_attach_to_turn_context_is_nonmutating() -> None:
    ctx = {"turn_id": "t1", "session_id": "s1"}
    emo = EmotionState(valence=0.5, warmth=0.9)
    out = es.attach_to_turn_context(ctx, emo)
    # original untouched
    assert "emotion" not in ctx
    # new dict carries identifiers + emotion
    assert out["turn_id"] == "t1"
    assert out["session_id"] == "s1"
    assert "emotion" in out
    recovered = es.emotion_from_turn_context(out)
    assert abs(recovered.valence - 0.5) < 1e-3
    assert abs(recovered.warmth - 0.9) < 1e-3


def test_attach_to_turn_context_none_base() -> None:
    out = es.attach_to_turn_context(None, EmotionState())
    assert "emotion" in out


def test_emotion_from_empty_context_is_neutral() -> None:
    assert es.emotion_from_turn_context({}) == EmotionState()
