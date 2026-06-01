"""Unit tests for the Hinglish code-switch quality scoring (Task 14.1).

Plain ``pytest`` example/edge-case tests pinning the exact metric definitions
that the property test (Task 14.2) and downstream callers depend on:

- **H/E ratio** = ``100 * hindi / (hindi + english)`` over classifiable word
  tokens, on a ``0.0..100.0`` scale; text with no classifiable tokens is
  ``0.0`` (module docstring of ``roadmap/hinglish.py``).
- **within tolerance** iff ``|output_ratio - input_ratio| <= 15`` pp
  (Requirement 5.4); per-pair ``quality`` is ``100.0`` within tolerance else
  ``0.0``.
- **benchmark pass** iff the evaluation-set score is ``>= 80%`` (Requirement
  5.6); below threshold surfaces the LoRA/adapters adaptation hook (Requirement
  5.7).

The universal/all-inputs guarantees are covered by the Property 7 test in Task
14.2; these tests pin concrete examples and boundaries.

Requirements: 5.4, 5.6, 5.7
"""

from __future__ import annotations

import pytest

from roadmap.hinglish import (
    BENCHMARK_PASS_PCT,
    LORA_ADAPTATION_HOOK,
    TOLERANCE_PCT,
    HinglishDataEngine,
)


@pytest.fixture
def engine() -> HinglishDataEngine:
    return HinglishDataEngine()


# --- H/E ratio definition --------------------------------------------------


def test_he_ratio_all_hindi_is_100(engine: HinglishDataEngine) -> None:
    """All recognized Hindi tokens => ratio 100.0."""
    assert engine.he_ratio("main theek hoon") == 100.0


def test_he_ratio_all_english_is_0(engine: HinglishDataEngine) -> None:
    """All Latin/English tokens => ratio 0.0."""
    assert engine.he_ratio("I am totally fine") == 0.0


def test_he_ratio_no_classifiable_tokens_is_0(engine: HinglishDataEngine) -> None:
    """Pure punctuation/digits/empty classify as neither => 0.0 by convention."""
    assert engine.he_ratio("123 ... !!! 456") == 0.0
    assert engine.he_ratio("") == 0.0


def test_he_ratio_mixed_is_percentage_of_hindi(engine: HinglishDataEngine) -> None:
    """Two Hindi + two English tokens => 50% Hindi."""
    assert engine.he_ratio("main hai good morning") == pytest.approx(50.0)


def test_he_ratio_detects_devanagari_script(engine: HinglishDataEngine) -> None:
    """Devanagari-script tokens are unambiguously Hindi regardless of mapping."""
    assert engine.he_ratio("नमस्ते friend") == pytest.approx(50.0)


def test_he_ratio_ignores_edge_punctuation(engine: HinglishDataEngine) -> None:
    """Edge punctuation does not change the word classification."""
    assert engine.he_ratio("(namaste), hello!") == pytest.approx(50.0)


# --- Per-pair within-tolerance / score -------------------------------------


def test_score_within_tolerance_when_ratios_close(engine: HinglishDataEngine) -> None:
    """Identical ratios => difference 0 pp, within tolerance, quality 100."""
    result = engine.score("main theek hoon", "main accha hoon")
    assert result.input_ratio == 100.0
    assert result.output_ratio == 100.0
    assert result.difference_pp == 0.0
    assert result.within_tolerance is True
    assert result.quality == 100.0


def test_score_outside_tolerance_when_ratios_far(engine: HinglishDataEngine) -> None:
    """All-Hindi input vs all-English output => 100 pp gap, not within tolerance."""
    result = engine.score("main theek hoon", "I am fine thanks")
    assert result.input_ratio == 100.0
    assert result.output_ratio == 0.0
    assert result.difference_pp == 100.0
    assert result.within_tolerance is False
    assert result.quality == 0.0


def test_within_tolerance_boundary_is_inclusive(engine: HinglishDataEngine) -> None:
    """A difference of exactly 15 pp is within tolerance (<= is inclusive).

    Input: 1 Hindi + 1 English => 50.0. Output: chosen so the ratio differs by
    exactly the 15 pp tolerance band.
    """
    assert TOLERANCE_PCT == 15.0
    # input ratio = 50.0 (1 hindi, 1 english)
    # output: 13 hindi + 7 english => 65.0  => |65 - 50| = 15 pp exactly
    out = " ".join(["main"] * 13 + ["dog"] * 7)
    result = engine.score("main dog", out)
    assert result.input_ratio == pytest.approx(50.0)
    assert result.output_ratio == pytest.approx(65.0)
    assert result.difference_pp == pytest.approx(15.0)
    assert result.within_tolerance is True


def test_within_tolerance_helper_matches_score(engine: HinglishDataEngine) -> None:
    """The boolean helper agrees with the structured score's flag."""
    assert engine.within_tolerance("main hai", "aap ho") is True
    assert engine.within_tolerance("main theek hoon", "only english here") is False


# --- Benchmark pass rule & adaptation hook ---------------------------------


def test_benchmark_pass_threshold_is_80(engine: HinglishDataEngine) -> None:
    """A build passes iff the evaluation-set score is >= 80% (Requirement 5.6)."""
    assert BENCHMARK_PASS_PCT == 80.0
    assert engine.benchmark_passes(80.0) is True
    assert engine.benchmark_passes(100.0) is True
    assert engine.benchmark_passes(79.999) is False
    assert engine.benchmark_passes(0.0) is False


def test_evaluate_benchmark_aggregates_and_passes(engine: HinglishDataEngine) -> None:
    """4 of 5 pairs within tolerance => 80% => passes, no adaptation hook."""
    pairs = [
        ("main theek hoon", "main accha hoon"),   # 100 vs 100 => within
        ("aap kaise ho", "main theek hai"),         # 100 vs 100 => within
        ("hello there", "goodbye now"),             # 0 vs 0 => within
        ("namaste dost", "hello friend"),           # 100 vs 0 => NOT within
        ("main hai dog", "main hai cat"),           # 66.7 vs 66.7 => within
    ]
    result = engine.evaluate_benchmark(pairs)
    assert result.total == 5
    assert result.within_tolerance_count == 4
    assert result.eval_set_score == pytest.approx(80.0)
    assert result.passes is True
    assert result.adaptation_hook is None


def test_evaluate_benchmark_below_threshold_surfaces_lora_hook(
    engine: HinglishDataEngine,
) -> None:
    """Below 80% => does not pass, and surfaces the LoRA/adapters hook (5.7)."""
    pairs = [
        ("main theek hoon", "I am english only"),  # NOT within
        ("aap kaise ho", "main theek hai"),          # within
    ]
    result = engine.evaluate_benchmark(pairs)
    assert result.eval_set_score == pytest.approx(50.0)
    assert result.passes is False
    assert result.adaptation_hook == LORA_ADAPTATION_HOOK


def test_evaluate_benchmark_empty_set_does_not_pass(
    engine: HinglishDataEngine,
) -> None:
    """An empty evaluation set scores 0.0 and does not pass."""
    result = engine.evaluate_benchmark([])
    assert result.total == 0
    assert result.eval_set_score == 0.0
    assert result.passes is False
    assert result.adaptation_hook == LORA_ADAPTATION_HOOK
