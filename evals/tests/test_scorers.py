"""Tests for the §12 dimension scorers on known fixtures (Phase 15 / §12)."""

from __future__ import annotations

import pytest

from evals.audio.scorer import (
    AudioQualityFeatures,
    WerSample,
    intelligibility,
    load_fixtures,
    naturalness_proxy,
    score_naturalness_samples,
    score_wer_samples,
    wer,
)
from evals.emotion.scorer import (
    EmotionSample,
    label_agreement,
    score_emotion,
    vad_agreement,
)
from evals.emotion.scorer import (
    load_samples as load_emotion_samples,
)
from evals.emotion.scorer import (
    score_samples as score_emotion_samples,
)
from evals.hinglish.scorer import (
    CodeSwitchSample,
    classify_token,
    code_switch_ratio,
    language_profile,
    score_code_switch,
    transliteration_robustness,
)
from evals.hinglish.scorer import (
    load_samples as load_hinglish_samples,
)
from evals.text_metrics import character_error_rate, levenshtein, word_error_rate
from shared.contracts import EmotionState


# ---------------------------------------------------------------------------
# text_metrics primitives
# ---------------------------------------------------------------------------
def test_levenshtein_basic():
    assert levenshtein(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert levenshtein(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert levenshtein([], ["a", "b"]) == 2


def test_word_error_rate_known_values():
    assert word_error_rate("the cat sat", "the cat sat") == 0.0
    # one substitution out of three reference words.
    assert word_error_rate("the cat sat", "the dog sat") == pytest.approx(1 / 3)
    # empty reference, empty hyp → 0; empty reference, non-empty hyp → 1.
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "hello") == 1.0


def test_character_error_rate():
    assert character_error_rate("reminder", "reminder") == 0.0
    assert character_error_rate("reminder", "reminer") == pytest.approx(1 / 8)


# ---------------------------------------------------------------------------
# Hinglish scorer
# ---------------------------------------------------------------------------
def test_classify_token_devanagari_and_lexicon():
    assert classify_token("नमस्ते") == "hi"
    assert classify_token("yaar") == "hi"
    assert classify_token("schedule") == "en"


def test_language_profile_counts():
    profile = language_profile("yaar can you help")
    assert profile["tokens"] == 4
    assert profile["hi"] == 1
    assert profile["en"] == 3
    assert profile["hi_fraction"] == pytest.approx(0.25)


def test_code_switch_ratio_monolingual_is_zero():
    assert code_switch_ratio("let us schedule the meeting") == 0.0
    assert code_switch_ratio("") == 0.0
    assert code_switch_ratio("hello") == 0.0


def test_code_switch_ratio_alternating_high():
    # yaar(hi) help(en) yaar(hi) help(en) → 3/3 switches = 1.0
    assert code_switch_ratio("yaar help yaar help") == pytest.approx(1.0)


def test_transliteration_robustness_identical_is_one():
    assert transliteration_robustness("thik hai", "thik hai") == 1.0
    assert transliteration_robustness("thik hai", "theek hai") < 1.0


def test_score_code_switch_expected_mixing():
    mixed = CodeSwitchSample(text="yaar can you help", expect_code_switch=True)
    assert score_code_switch(mixed) == 1.0
    mono_expected_mixed = CodeSwitchSample(text="let us schedule", expect_code_switch=True)
    assert score_code_switch(mono_expected_mixed) == 0.0


def test_hinglish_fixtures_load_and_score_well():
    samples = load_hinglish_samples()
    assert len(samples) >= 3
    # Mean score across curated fixtures should be solidly above the gate floor.
    from evals.hinglish.scorer import score_samples

    assert score_samples(samples) >= 0.7


# ---------------------------------------------------------------------------
# Emotion scorer
# ---------------------------------------------------------------------------
def test_label_agreement_exact_partial_none():
    assert label_agreement("warm", "warm") == 1.0
    assert label_agreement("friendly", "warm") == 0.5  # same cluster
    assert label_agreement("angry", "warm") == 0.0
    assert label_agreement(None, None) == 1.0


def test_vad_agreement_identical_is_one():
    e = EmotionState(valence=0.5, arousal=0.2, dominance=0.1)
    assert vad_agreement(e, e) == pytest.approx(1.0)


def test_vad_agreement_opposite_is_zero():
    pos = EmotionState(valence=1.0, arousal=1.0, dominance=1.0)
    neg = EmotionState(valence=-1.0, arousal=-1.0, dominance=-1.0)
    assert vad_agreement(pos, neg) == pytest.approx(0.0)


def test_score_emotion_combined():
    sample = EmotionSample(
        intended_label="warm",
        produced_label="friendly",
        intended=EmotionState(valence=0.6, arousal=0.3, dominance=0.5),
        produced=EmotionState(valence=0.58, arousal=0.30, dominance=0.5),
        blend=0.5,
    )
    score = score_emotion(sample)
    # label component 0.5 (confusable), vad component near 1.0 → blend ~0.75+.
    assert 0.7 <= score <= 1.0


def test_emotion_fixtures_load_and_score_well():
    samples = load_emotion_samples()
    assert len(samples) >= 3
    assert score_emotion_samples(samples) >= 0.7


# ---------------------------------------------------------------------------
# Audio scorer
# ---------------------------------------------------------------------------
def test_wer_and_intelligibility():
    assert wer("the cat sat", "the cat sat") == 0.0
    assert intelligibility("the cat sat", "the cat sat") == 1.0
    assert intelligibility("the cat sat", "a b c d e") < 0.5


def test_naturalness_proxy_ideal_is_one():
    assert naturalness_proxy(AudioQualityFeatures()) == 1.0


def test_naturalness_proxy_degrades_with_artifacts():
    bad = AudioQualityFeatures(
        clipping_ratio=0.5,
        join_discontinuity=0.5,
        pace_deviation=0.5,
        repeated_artifact_ratio=0.5,
        silence_ratio=0.5,
    )
    assert naturalness_proxy(bad) == pytest.approx(0.5)
    worse = AudioQualityFeatures(
        clipping_ratio=1.0,
        join_discontinuity=1.0,
        pace_deviation=1.0,
        repeated_artifact_ratio=1.0,
        silence_ratio=1.0,
    )
    assert naturalness_proxy(worse) == pytest.approx(0.0)


def test_audio_fixtures_load_and_score():
    wer_samples, nat_samples = load_fixtures()
    assert len(wer_samples) >= 3
    assert isinstance(wer_samples[0], WerSample)
    assert score_wer_samples(wer_samples) <= 0.3  # below gate ceiling
    assert score_naturalness_samples(nat_samples) >= 0.7  # above gate floor
