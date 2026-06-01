"""Regression suite for the roadmap decision logic.

This is a plain ``pytest`` regression suite (no property-based testing): it
loads the companion ``regression_cases.json`` data file (task 45.1, exposed via
:func:`roadmap.tests.fixtures.load_regression_cases`) and asserts that the real
decision-logic components still reproduce the recorded expected outputs for
every recorded case.

Each decision-logic category is parametrized over its recorded cases (with the
human-readable ``description`` used as the test id) and run against the actual
component:

- ``selection``        → :class:`roadmap.SelectionScorer`
- ``gate_evaluation``  → :class:`roadmap.GateEvaluator`
- ``emotion``          → :class:`roadmap.EmotionPersonaController`
- ``hinglish_score``   → :class:`roadmap.HinglishDataEngine`

The data file also carries ``_schema`` and ``description`` documentation keys;
those are never iterated here — only the known category arrays are. A category
that is missing or empty simply yields no parametrized cases (the test is
skipped rather than hard-failing), while every present case must pass.
"""

from __future__ import annotations

import pytest

from roadmap import (
    CandidateScores,
    EmotionFeatures,
    EmotionPersonaController,
    Gate,
    GateCriterion,
    GateEvaluator,
    HinglishDataEngine,
    SelectionScorer,
)
from roadmap.tests.fixtures import load_regression_cases

# Load the recorded cases once at import time so each category's parametrization
# can pull its own array. The documentation keys ("_schema", "description") are
# never iterated — only the known category arrays below are consumed.
_CASES = load_regression_cases()


def _cases_for(category: str) -> list[dict]:
    """Return the recorded cases for ``category`` (``[]`` when missing/empty)."""
    value = _CASES.get(category, [])
    return value if isinstance(value, list) else []


def _ids(cases: list[dict]) -> list[str]:
    """Build pytest ids from each case's ``description``."""
    return [str(case.get("description", f"case-{i}")) for i, case in enumerate(cases)]


_SELECTION_CASES = _cases_for("selection")
_GATE_CASES = _cases_for("gate_evaluation")
_EMOTION_CASES = _cases_for("emotion")
_HINGLISH_CASES = _cases_for("hinglish_score")


@pytest.mark.parametrize("case", _SELECTION_CASES, ids=_ids(_SELECTION_CASES))
def test_selection_regression(case: dict) -> None:
    """SelectionScorer reproduces each recorded selection outcome.

    Builds one :class:`CandidateScores` per ``model_id`` (preserving the JSON
    object's insertion order, which defines the first-wins tie-break order),
    runs the scorer, and asserts the selected model and the passing set match
    the recorded expectations.
    """
    candidates = [
        CandidateScores(
            model_id=model_id,
            revision="regression",
            scores={criterion: float(score) for criterion, score in scores.items()},
        )
        for model_id, scores in case["candidate_scores"].items()
    ]

    outcome = SelectionScorer().select(candidates)

    assert outcome.selected == case["expected_selected"]
    assert outcome.passing == case["expected_passing"]


@pytest.mark.parametrize("case", _GATE_CASES, ids=_ids(_GATE_CASES))
def test_gate_evaluation_regression(case: dict) -> None:
    """GateEvaluator reproduces each recorded gate outcome (clean register).

    Constructs a launch :class:`Gate` whose ``exit_criteria`` are the recorded
    criteria, evaluates it against the recorded measured values with no
    licensing register (treated as clean), and asserts the overall pass/blocked
    flags match the recorded expectations.
    """
    exit_criteria = [
        GateCriterion(
            metric_name=criterion["metric_name"],
            threshold=float(criterion["threshold"]),
            operator=criterion["operator"],
        )
        for criterion in case["criteria"]
    ]
    gate = Gate(
        id="REGRESSION-GATE",
        kind="launch",
        exit_criteria=exit_criteria,
        owner_role="Release Manager",
        fallback_action="remain on LEAN_Track",
    )
    measured = {metric: float(value) for metric, value in case["measured"].items()}

    result = GateEvaluator().evaluate(gate, measured, registry=None)

    assert result.overall_passed == case["expected_overall_passed"]
    assert result.blocked == case["expected_blocked"]


@pytest.mark.parametrize("case", _EMOTION_CASES, ids=_ids(_EMOTION_CASES))
def test_emotion_regression(case: dict) -> None:
    """EmotionPersonaController reproduces each recorded conditioning mode.

    V/A/D do not affect the mode decision and default to ``0.0`` here, matching
    the data file's documented consuming convention.
    """
    features = EmotionFeatures(
        label=case["label"],
        confidence=float(case["confidence"]),
        valence=0.0,
        arousal=0.0,
        dominance=0.0,
        extraction_ok=bool(case["extraction_ok"]),
    )

    mode = EmotionPersonaController().select_conditioning(features)

    assert mode == case["expected_mode"]


@pytest.mark.parametrize("case", _HINGLISH_CASES, ids=_ids(_HINGLISH_CASES))
def test_hinglish_score_regression(case: dict) -> None:
    """HinglishDataEngine reproduces each recorded within-tolerance decision."""
    within = HinglishDataEngine().score(case["input"], case["output"]).within_tolerance

    assert within == case["expected_within_tolerance"]
