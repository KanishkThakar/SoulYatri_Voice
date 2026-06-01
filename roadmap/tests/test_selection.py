"""Property-based test for the Speech-Native Core selection logic.

This module holds the Hypothesis property test for
**Property 3: Speech-Native Core selection** (task 8.2). The deterministic
tie-break example tests (task 8.3) live separately in
``test_selection_scorer_tiebreak.py``; function names here are kept specific
(``test_property_3_*``) so the two suites never collide.

Property 3 (design "Correctness Properties")
---------------------------------------------
*For any* set of Candidate_Model scores against the six weighted selection
criteria, the selector scores **every** candidate against **every** criterion;
if **no** candidate meets every per-criterion minimum threshold the selection is
``RETAIN_PHASE_1``; and if at least one candidate meets every minimum the
selection is the candidate with the **highest** weighted aggregate score among
those that meet every minimum.

Validates: Requirements 2.4, 2.7, 2.9
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.models.selection import (
    RETAIN_PHASE_1,
    SELECTION_CRITERIA,
    SELECTION_MINIMUMS,
    SELECTION_WEIGHTS,
    CandidateScores,
)
from roadmap.selection_scorer import SelectionScorer

# The six selection-criterion keys, in canonical order, used both to generate
# candidate scores and to independently recompute expected values below.
_CRITERIA: tuple[str, ...] = tuple(SELECTION_CRITERIA)
_WEIGHT_TOTAL: float = float(sum(SELECTION_WEIGHTS.values()))


def _score() -> st.SearchStrategy[float]:
    """A per-criterion score on the inclusive ``0..100`` scale."""
    return st.floats(
        min_value=0.0,
        max_value=100.0,
        allow_nan=False,
        allow_infinity=False,
    )


@st.composite
def _candidate(draw: st.DrawFn, model_id: str) -> CandidateScores:
    """Generate one ``CandidateScores`` spanning the meaningful input space.

    Three generation modes are mixed so a candidate list reliably contains both
    candidates that clear every per-criterion minimum and candidates that do
    not, while also exercising the scorer's fail-closed handling of absent
    criterion scores:

    - ``"passing"``: every criterion is drawn at or above its minimum, so the
      candidate is guaranteed to pass all minimums.
    - ``"random"``: every criterion is drawn freely in ``0..100`` (may or may
      not pass).
    - ``"partial"``: a random subset of the six criteria is omitted entirely. A
      missing criterion is treated as ``0.0`` (fail-closed), so this candidate
      fails any positive minimum it did not report.
    """
    mode = draw(st.sampled_from(["passing", "random", "partial"]))

    if mode == "passing":
        scores = {
            criterion: draw(
                st.floats(
                    min_value=float(SELECTION_MINIMUMS[criterion]),
                    max_value=100.0,
                    allow_nan=False,
                    allow_infinity=False,
                )
            )
            for criterion in _CRITERIA
        }
    elif mode == "random":
        scores = {criterion: draw(_score()) for criterion in _CRITERIA}
    else:  # "partial" — omit a subset of criteria to exercise fail-closed.
        present = draw(
            st.lists(
                st.sampled_from(_CRITERIA),
                unique=True,
                max_size=len(_CRITERIA),
            )
        )
        scores = {criterion: draw(_score()) for criterion in present}

    return CandidateScores(model_id=model_id, revision="rev-1", scores=scores)


@st.composite
def _candidates(draw: st.DrawFn) -> list[CandidateScores]:
    """Generate a list (possibly empty) of candidates with unique model ids."""
    count = draw(st.integers(min_value=0, max_value=8))
    return [draw(_candidate(model_id=f"model-{index}")) for index in range(count)]


def _expected_aggregate(candidate: CandidateScores) -> float:
    """Recompute the weight-normalized aggregate independently of the scorer.

    ``sum(score[c] * weight[c]) / sum(weights)`` with absent scores treated as
    ``0.0`` — derived from the requirements/design, not the implementation.
    """
    weighted_sum = sum(
        float(candidate.scores.get(criterion, 0.0)) * SELECTION_WEIGHTS[criterion]
        for criterion in _CRITERIA
    )
    return weighted_sum / _WEIGHT_TOTAL


def _expected_passes(candidate: CandidateScores) -> bool:
    """Recompute, independently, whether a candidate meets every minimum."""
    return all(
        float(candidate.scores.get(criterion, 0.0)) >= SELECTION_MINIMUMS[criterion]
        for criterion in _CRITERIA
    )


# Feature: speech-native-voice-roadmap, Property 3: Speech-Native Core selection
@settings(max_examples=100)
@given(candidates=_candidates())
def test_property_3_speech_native_core_selection(
    candidates: list[CandidateScores],
) -> None:
    """Property 3: Speech-Native Core selection.

    Validates: Requirements 2.4, 2.7, 2.9
    """
    scorer = SelectionScorer()
    outcome = scorer.select(candidates)

    model_ids = [candidate.model_id for candidate in candidates]

    # --- Req 2.4: every candidate is scored against every criterion. ---------
    # The aggregates map covers exactly the candidates supplied (one each).
    assert set(outcome.aggregates) == set(model_ids)
    assert len(outcome.aggregates) == len(model_ids)
    # Each aggregate equals an independent weight-normalized recompute, which
    # is only possible if every criterion contributed to every candidate.
    for candidate in candidates:
        assert math.isclose(
            outcome.aggregates[candidate.model_id],
            _expected_aggregate(candidate),
            rel_tol=1e-9,
            abs_tol=1e-9,
        )

    # --- `passing` lists exactly the candidates meeting all minimums. --------
    expected_passing = [c.model_id for c in candidates if _expected_passes(c)]
    assert outcome.passing == expected_passing  # input order preserved

    if not outcome.passing:
        # --- Req 2.7: no qualifying candidate => retain Phase 1. -------------
        assert outcome.selected == RETAIN_PHASE_1
    else:
        # --- Req 2.9: highest weighted aggregate AMONG passing candidates. ---
        assert outcome.selected != RETAIN_PHASE_1
        # No non-passing candidate is ever selected.
        assert outcome.selected in outcome.passing

        best_passing_aggregate = max(
            outcome.aggregates[model_id] for model_id in outcome.passing
        )
        # The selected candidate's aggregate is >= every other passing
        # candidate's aggregate.
        assert outcome.aggregates[outcome.selected] == best_passing_aggregate
        for model_id in outcome.passing:
            assert (
                outcome.aggregates[outcome.selected]
                >= outcome.aggregates[model_id]
            )

        # A non-passing candidate (even one with a strictly higher aggregate)
        # never displaces the passing winner.
        for model_id in set(model_ids) - set(outcome.passing):
            assert outcome.selected != model_id

        # Deterministic tie-break: first passing candidate (input order) that
        # attains the top aggregate (stable first-wins).
        expected_selected = next(
            model_id
            for model_id in outcome.passing
            if outcome.aggregates[model_id] == best_passing_aggregate
        )
        assert outcome.selected == expected_selected
