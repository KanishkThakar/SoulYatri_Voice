"""Unit tests for the selection-scorer tie-break behavior (task 8.3).

These are plain ``pytest`` example tests, kept SEPARATE from the property test
for Property 3 (``test_selection.py`` / task 8.2). They pin the
documented tie-break rule of ``roadmap/selection_scorer.py``
(``SelectionScorer.select``):

    When two or more PASSING candidates share the single highest weighted
    aggregate, the winner is the one that appears FIRST in the input order
    (stable first-wins). Aggregates are kept exact (no rounding), so ties occur
    only on genuinely equal scores. The rule is fully deterministic for a given
    input ordering.

This complements Requirement 2.9, which mandates selecting the candidate with
the highest weighted aggregate among those passing every per-criterion minimum.
The requirement is silent on exact ties; the design fixes first-wins as the
deterministic tie-break, and these tests exercise that contract directly.

Requirements: 2.9
"""

from __future__ import annotations

from roadmap.models.selection import (
    RETAIN_PHASE_1,
    SELECTION_CRITERIA,
    SELECTION_MINIMUMS,
    CandidateScores,
)
from roadmap.selection_scorer import SelectionScorer


def _uniform_scores(value: float) -> dict[str, float]:
    """A score map assigning ``value`` to every selection criterion.

    Using an identical score for every criterion yields a clean, exactly
    reproducible weighted aggregate equal to ``value`` (independent of the
    individual weights, since ``sum(value * w) / sum(w) == value``). Choosing
    ``value`` at or above the largest per-criterion minimum guarantees the
    candidate passes every minimum.
    """
    return {criterion: value for criterion in SELECTION_CRITERIA}


def _passing_scores() -> dict[str, float]:
    """A score map that clears every per-criterion minimum with margin.

    ``80.0`` is >= every value in ``SELECTION_MINIMUMS`` (max minimum is 70),
    so the map passes all minimums and yields an exact aggregate of ``80.0``.
    """
    return _uniform_scores(80.0)


def _failing_full_duplex_scores() -> dict[str, float]:
    """A high-scoring map that nonetheless FAILS one per-criterion minimum.

    Every criterion is 100.0 except ``full_duplex`` which is set just below its
    minimum. This produces a weighted aggregate strictly *higher* than the
    passing candidates above, proving a non-passing candidate never wins a tie
    even with a superior aggregate (Requirement 2.9 restricts selection to
    passing candidates).
    """
    scores = {criterion: 100.0 for criterion in SELECTION_CRITERIA}
    scores["full_duplex"] = SELECTION_MINIMUMS["full_duplex"] - 1.0
    return scores


def test_tie_break_picks_first_candidate_in_input_order() -> None:
    """Two passing candidates with identical scores -> the first one wins."""
    scorer = SelectionScorer()
    candidate_a = CandidateScores("model-a", "r1", _passing_scores())
    candidate_b = CandidateScores("model-b", "r1", _passing_scores())

    outcome = scorer.select([candidate_a, candidate_b])

    # Both candidates pass and share the exact same aggregate (a genuine tie).
    assert outcome.passing == ["model-a", "model-b"]
    assert outcome.aggregates["model-a"] == outcome.aggregates["model-b"]
    # First-wins: the candidate appearing first in the input order is selected.
    assert outcome.selected == "model-a"


def test_tie_break_is_by_input_order_not_id() -> None:
    """Reversing the input order changes the winner accordingly.

    Confirms the tie-break is driven by *input order* (deterministic
    first-wins) and not by model id, alphabetical order, or any hidden state.
    """
    scorer = SelectionScorer()
    candidate_a = CandidateScores("model-a", "r1", _passing_scores())
    candidate_b = CandidateScores("model-b", "r1", _passing_scores())

    assert scorer.select([candidate_a, candidate_b]).selected == "model-a"
    # Reverse the input order: now the other candidate appears first and wins.
    assert scorer.select([candidate_b, candidate_a]).selected == "model-b"


def test_three_way_tie_picks_first_in_input_order() -> None:
    """A three-way tie still resolves to whichever passing candidate is first."""
    scorer = SelectionScorer()
    first = CandidateScores("model-x", "r1", _passing_scores())
    second = CandidateScores("model-y", "r1", _passing_scores())
    third = CandidateScores("model-z", "r1", _passing_scores())

    outcome = scorer.select([second, third, first])

    assert outcome.passing == ["model-y", "model-z", "model-x"]
    agg = outcome.aggregates
    assert agg["model-x"] == agg["model-y"] == agg["model-z"]
    assert outcome.selected == "model-y"


def test_first_among_tied_top_wins_not_absolute_first() -> None:
    """The first AMONG the tied-top is selected, not the absolute-first item.

    A lower-aggregate *passing* candidate appears first in the list, followed
    by two tied top-aggregate passing candidates. Selection must pick the first
    of the tied-top group (``top-a``), not the absolute-first list element
    (``low-pass``, which passes but has a lower aggregate) and not the second
    tied-top candidate (``top-b``).
    """
    scorer = SelectionScorer()
    low_pass = CandidateScores("low-pass", "r1", _uniform_scores(70.0))  # agg 70
    top_a = CandidateScores("top-a", "r1", _uniform_scores(90.0))        # agg 90
    top_b = CandidateScores("top-b", "r1", _uniform_scores(90.0))        # agg 90

    outcome = scorer.select([low_pass, top_a, top_b])

    # All three pass every minimum (uniform 70.0 clears the max minimum of 70).
    assert outcome.passing == ["low-pass", "top-a", "top-b"]
    # The two top candidates are genuinely tied above the first list element.
    assert outcome.aggregates["top-a"] == outcome.aggregates["top-b"]
    assert outcome.aggregates["top-a"] > outcome.aggregates["low-pass"]
    # First among the tied-top wins; the lower-aggregate absolute-first loses.
    assert outcome.selected == "top-a"


def test_non_passing_candidate_with_higher_aggregate_never_wins_tie() -> None:
    """A non-passing candidate with a higher aggregate does not win the tie.

    The non-passing candidate has a strictly higher weighted aggregate than the
    two tied passing candidates, yet selection is restricted to passing
    candidates, so the first passing candidate in input order still wins.
    """
    scorer = SelectionScorer()
    passing_first = CandidateScores("pass-a", "r1", _passing_scores())
    non_passing = CandidateScores("fail-hi", "r1", _failing_full_duplex_scores())
    passing_second = CandidateScores("pass-b", "r1", _passing_scores())

    # Place the higher-aggregate non-passing candidate in the middle.
    outcome = scorer.select([passing_first, non_passing, passing_second])

    # The non-passing candidate genuinely has the highest aggregate of the set.
    assert outcome.aggregates["fail-hi"] > outcome.aggregates["pass-a"]
    # ...but it is excluded from `passing` and is never selected.
    assert "fail-hi" not in outcome.passing
    assert outcome.passing == ["pass-a", "pass-b"]
    assert outcome.selected == "pass-a"
    assert outcome.selected != RETAIN_PHASE_1
