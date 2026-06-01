"""Property-based test for the Hinglish code-switch quality scoring (Task 14.2).

This module holds the Hypothesis property test for
**Property 7: Code-switch quality scoring and pass threshold**. The concrete
example/edge-case tests (Task 14.1) live separately in
``test_hinglish_scoring.py``; the function names here are kept specific
(``test_property_7_*``) so the two suites never collide.

Property 7 (design "Correctness Properties")
--------------------------------------------
*For any* code-switched input and the corresponding response, the code-switch
quality decision is "within tolerance" **if and only if** the absolute
difference between the response's Hindi-to-English token ratio and the input's
Hindi-to-English token ratio is at most 15 percentage points; and *for any*
evaluation-set score, the build passes the Hinglish benchmark **if and only if**
the score is at least 80 percent.

The generators compose tokens from a small vocabulary that mixes:

- recognized Romanized Hinglish-Hindi keys (from
  ``DEFAULT_ROMANIZED_TO_DEVANAGARI``) — classify as Hindi,
- native-script Devanagari words (the mapping values) — classify as Hindi,
- plain English words absent from the mapping — classify as English,
- punctuation/digit tokens — classify as neither (ignored by the ratio),

so the input/output H/E ratios span the full ``0..100`` range and the
within-tolerance decision is exercised on both sides of the 15 pp band. Lists of
such ``(input, output)`` pairs — including the empty list — drive the benchmark
aggregate.

Validates: Requirements 5.4, 5.6
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.hinglish import (
    BENCHMARK_PASS_PCT,
    DEFAULT_ROMANIZED_TO_DEVANAGARI,
    LORA_ADAPTATION_HOOK,
    TOLERANCE_PCT,
    HinglishDataEngine,
)

# A single shared engine: the scoring logic is pure and stateless, so one
# instance backs every example.
_ENGINE = HinglishDataEngine()

# --- Token vocabulary spanning every classification bucket -----------------

# Recognized Romanized Hinglish-Hindi keys (classify as Hindi via the mapping).
_HINDI_ROMAN = sorted(DEFAULT_ROMANIZED_TO_DEVANAGARI.keys())

# Native-script Devanagari words (classify as Hindi via Devanagari characters).
_HINDI_DEVANAGARI = sorted(set(DEFAULT_ROMANIZED_TO_DEVANAGARI.values()))

# Plain English words that are NOT keys of the mapping (classify as English).
# Guarded by the assertion below so a future mapping change cannot silently turn
# one of these into a recognized Hindi token.
_ENGLISH_WORDS = [
    "hello",
    "world",
    "dog",
    "cat",
    "good",
    "morning",
    "friend",
    "please",
    "thanks",
    "water",
    "food",
    "love",
]
assert not (set(_ENGLISH_WORDS) & set(DEFAULT_ROMANIZED_TO_DEVANAGARI)), (
    "English vocabulary must not overlap the Hindi mapping keys"
)

# Tokens that classify as NEITHER (no Devanagari and no Latin letters): pure
# digits and pure punctuation. These are ignored by the H/E ratio entirely.
_NEITHER_TOKENS = ["123", "456", "...", "!!!", "?", "42", "---", ":)"]


@st.composite
def _text(draw: st.DrawFn) -> str:
    """Generate a whitespace-joined text spanning the full H/E ratio range.

    Independently draws a count of Hindi-Romanized, Hindi-Devanagari, English,
    and neither tokens (each ``0..4``), shuffles them together, and joins on
    single spaces. Varying the Hindi/English counts makes the resulting H/E
    ratio (``100 * hindi / (hindi + english)``) take values across ``0..100``
    including both endpoints and the no-classifiable-token case (``0.0``).
    """
    hindi_roman = draw(st.lists(st.sampled_from(_HINDI_ROMAN), max_size=4))
    hindi_deva = draw(st.lists(st.sampled_from(_HINDI_DEVANAGARI), max_size=4))
    english = draw(st.lists(st.sampled_from(_ENGLISH_WORDS), max_size=4))
    neither = draw(st.lists(st.sampled_from(_NEITHER_TOKENS), max_size=3))

    tokens = hindi_roman + hindi_deva + english + neither
    tokens = draw(st.permutations(tokens))
    return " ".join(tokens)


@st.composite
def _pair(draw: st.DrawFn) -> tuple[str, str]:
    """Generate one ``(input, output)`` text pair."""
    return draw(_text()), draw(_text())


# Feature: speech-native-voice-roadmap, Property 7: Code-switch quality scoring and pass threshold
@settings(max_examples=100)
@given(input_text=_text(), output_text=_text())
def test_property_7_within_tolerance_iff_ratio_gap_within_15pp(
    input_text: str,
    output_text: str,
) -> None:
    """Property 7 (per-pair): within-tolerance iff H/E ratio gap <= 15 pp.

    Validates: Requirements 5.4
    """
    # he_ratio is always a percentage on the inclusive 0..100 scale.
    input_ratio = _ENGINE.he_ratio(input_text)
    output_ratio = _ENGINE.he_ratio(output_text)
    assert 0.0 <= input_ratio <= 100.0
    assert 0.0 <= output_ratio <= 100.0

    score = _ENGINE.score(input_text, output_text)

    # The score reports exactly the independently computed H/E ratios.
    assert score.input_ratio == input_ratio
    assert score.output_ratio == output_ratio

    # difference_pp is the absolute gap between the two ratios.
    assert score.difference_pp == abs(output_ratio - input_ratio)

    # Core IFF: within tolerance exactly when the gap is at most 15 pp,
    # recomputed independently from he_ratio.
    expected_within = abs(output_ratio - input_ratio) <= TOLERANCE_PCT
    assert score.within_tolerance == expected_within

    # Per-pair quality is the pass/fail mapped onto the 0..100 scale.
    assert score.quality == (100.0 if expected_within else 0.0)

    # The boolean helper agrees with the structured score's flag.
    assert _ENGINE.within_tolerance(input_text, output_text) == score.within_tolerance


# Feature: speech-native-voice-roadmap, Property 7: Code-switch quality scoring and pass threshold
@settings(max_examples=100)
@given(pairs=st.lists(_pair(), max_size=8))
def test_property_7_benchmark_pass_iff_eval_set_score_at_least_80(
    pairs: list[tuple[str, str]],
) -> None:
    """Property 7 (aggregate): benchmark passes iff eval-set score >= 80%.

    Validates: Requirements 5.6
    """
    result = _ENGINE.evaluate_benchmark(pairs)

    total = len(pairs)
    assert result.total == total
    assert len(result.per_pair) == total

    # Independently recompute the within-tolerance count from per-pair scores.
    expected_within_count = sum(
        1 for inp, out in pairs if _ENGINE.score(inp, out).within_tolerance
    )
    assert result.within_tolerance_count == expected_within_count

    # eval_set_score == 100 * within / total, and 0.0 for the empty set.
    expected_score = 100.0 * expected_within_count / total if total else 0.0
    assert math.isclose(
        result.eval_set_score, expected_score, rel_tol=1e-9, abs_tol=1e-9
    )

    # Core IFF: passes exactly when the eval-set score is at least 80%, and this
    # agrees with the standalone benchmark_passes rule.
    expected_passes = result.eval_set_score >= BENCHMARK_PASS_PCT
    assert result.passes == expected_passes
    assert result.passes == _ENGINE.benchmark_passes(result.eval_set_score)

    # The LoRA/adapters adaptation hook is surfaced exactly when not passing.
    if result.passes:
        assert result.adaptation_hook is None
    else:
        assert result.adaptation_hook == LORA_ADAPTATION_HOOK
