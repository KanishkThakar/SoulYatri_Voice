"""End-to-end *wiring* integration test for the ``evaluate_and_select`` pipeline.

This is a plain ``pytest`` integration test (not a Hypothesis property test). It
runs **one mocked pass** of :func:`roadmap.evaluate_and_select` over a small,
fixed candidate set and asserts that the three decision-logic components — the
mocked :class:`EvaluationHarness`, the :class:`SelectionScorer`, and the
:class:`GateEvaluator` (+ :class:`LicensingRegister`) — are *wired together*
correctly.

It deliberately verifies the **wiring**, not the universal properties: the
per-component invariants (comparable scoring, the selection argmax/minimum gate,
gate overall-pass iff, blocking/remediation, licensing blocks) are each covered
by their own property-based tests (``test_evaluation_harness.py``,
``test_harness_exclusion.py``, ``test_selection.py``, ``test_gate_evaluator.py``,
``test_licensing.py``). Here we only confirm that one pass over a fixed input
produces comparable records, a deterministic selection, exclusion continuation,
and a gate result, with the artifacts flowing correctly between the components.

Validates the integration of Requirements 4.1 (comparable records), 4.5
(per-candidate exclusion continues the run), and 8.4 (a launch gate produces an
overall gate result).
"""

from __future__ import annotations

from roadmap import (
    METRIC_KEYS,
    RETAIN_PHASE_1,
    SELECTION_MINIMUMS,
    Gate,
    GateCriterion,
    GateResult,
    LicensingRegister,
    MockCandidate,
    PipelineResult,
    evaluate_and_select,
)
from roadmap.evaluation_harness import EXCLUSION_CATEGORIES

# --- Fixed test inputs ----------------------------------------------------

# Three distinct model ids: a clear selection winner, an evaluable-but-failing
# runner-up, and an excludable candidate placed *between* the two evaluable ones
# so we can assert the run does not abort on exclusion.
WINNER_ID = "alpha/model-a"
RUNNER_UP_ID = "beta/model-b"
EXCLUDED_ID = "gamma/model-c"

# Per-criterion selection scores. The winner clears every minimum in
# SELECTION_MINIMUMS; the runner-up clears all but one (community_activity is
# below its minimum), so only the winner is selectable. The excluded candidate
# carries no scores because it never reaches the scorer.
_PASS_ALL = {criterion: 90.0 for criterion in SELECTION_MINIMUMS}
_FAIL_ONE = {**{criterion: 90.0 for criterion in SELECTION_MINIMUMS}, "community_activity": 10.0}

SELECTION_SCORES = {
    WINNER_ID: dict(_PASS_ALL),
    RUNNER_UP_ID: dict(_FAIL_ONE),
}

# Launch-gate exit criteria mirroring the design's LEAN demo gate shape: a p50
# first-response latency ceiling and a Hinglish code-switch quality floor.
_LATENCY_METRIC = "latency_ms_p50"
_QUALITY_METRIC = "hinglish_codeswitch_quality"

LAUNCH_GATE = Gate(
    id="LEAN-DEMO",
    kind="launch",
    entry_criteria=[],
    exit_criteria=[
        GateCriterion(metric_name=_LATENCY_METRIC, threshold=300.0, operator="<="),
        GateCriterion(metric_name=_QUALITY_METRIC, threshold=60.0, operator=">="),
    ],
    owner_role="Release Manager",
    fallback_action="remain on LEAN_Track",
)

PASSING_MEASUREMENTS = {_LATENCY_METRIC: 250.0, _QUALITY_METRIC: 75.0}
FAILING_MEASUREMENTS = {_LATENCY_METRIC: 400.0, _QUALITY_METRIC: 75.0}


def _fixed_candidates() -> list[MockCandidate]:
    """Build the small, fixed candidate set.

    Order is ``[winner, excluded, runner-up]`` so the excludable candidate sits
    *between* two evaluable candidates — letting the test assert the pipeline
    continued past the exclusion (Requirement 4.5).
    """
    return [
        MockCandidate(WINNER_ID, "v1", seeds={"latency_ms_p50": 0.1}),
        # Excludable: weights cannot be loaded -> "missing_weights" exclusion.
        MockCandidate(EXCLUDED_ID, "v1", weights_available=False),
        MockCandidate(RUNNER_UP_ID, "v1", seeds={"latency_ms_p50": 0.9}),
    ]


# --- Integration tests ----------------------------------------------------


def test_pipeline_wires_records_selection_and_passing_gate() -> None:
    """One pass wires comparable records, a deterministic selection, and a gate.

    Verifies the components are connected correctly (not the universal
    properties): comparable harness records (4.1), exclusion continuation (4.5),
    a deterministic selection flowing from those records, and an overall gate
    result from the launch gate + clean register (8.4).
    """
    candidates = _fixed_candidates()
    registry = LicensingRegister()  # clean register: no warnings, nothing prohibiting

    result = evaluate_and_select(
        candidates,
        selection_scores=SELECTION_SCORES,
        gate=LAUNCH_GATE,
        gate_measurements=PASSING_MEASUREMENTS,
        registry=registry,
    )

    assert isinstance(result, PipelineResult)

    # -- Comparable records (Requirement 4.1) ------------------------------
    # Exactly one record per candidate, preserving input order.
    assert len(result.harness_runs) == len(candidates)
    assert [run.model_id for run in result.harness_runs] == [
        WINNER_ID,
        EXCLUDED_ID,
        RUNNER_UP_ID,
    ]
    # Every NON-excluded record shares the identical metric key set.
    for run in result.harness_runs:
        if not run.excluded:
            assert set(run.metric_scores.keys()) == set(METRIC_KEYS)

    # -- Exclusion continuation (Requirement 4.5) --------------------------
    runs_by_id = {run.model_id: run for run in result.harness_runs}
    excluded_run = runs_by_id[EXCLUDED_ID]
    assert excluded_run.excluded is True
    assert excluded_run.exclusion_category in EXCLUSION_CATEGORIES
    assert excluded_run.exclusion_reason  # a descriptive, non-empty reason
    assert excluded_run.metric_scores == {}  # no measurement performed
    # The run did NOT abort: both evaluable candidates are still present, and
    # the one *after* the exclusion was evaluated normally.
    assert runs_by_id[WINNER_ID].excluded is False
    assert runs_by_id[RUNNER_UP_ID].excluded is False

    # -- Deterministic selection (selection wiring) ------------------------
    selection = result.selection
    # Only the winner clears every per-criterion minimum -> it is selected.
    assert selection.selected == WINNER_ID
    assert selection.passing == [WINNER_ID]
    # The runner-up was scored but did not pass; the excluded candidate never
    # reached the scorer at all.
    assert RUNNER_UP_ID in selection.aggregates
    assert RUNNER_UP_ID not in selection.passing
    assert EXCLUDED_ID not in selection.aggregates
    assert EXCLUDED_ID not in selection.passing
    assert selection.selected != EXCLUDED_ID

    # -- Gate result (Requirement 8.4) -------------------------------------
    gate_result = result.gate_result
    assert isinstance(gate_result, GateResult)
    assert gate_result.gate_id == LAUNCH_GATE.id
    assert gate_result.overall_passed is True
    assert gate_result.blocked is False
    # One per-criterion result per exit criterion, all passing.
    assert len(gate_result.criteria_results) == len(LAUNCH_GATE.exit_criteria)
    assert all(c.passed for c in gate_result.criteria_results)


def test_pipeline_gate_blocks_on_failing_measurement() -> None:
    """A failing launch-gate measurement flows through to a blocked gate result.

    Confirms the gate-evaluation wiring also surfaces the negative path: a
    measurement that violates an exit criterion yields ``overall_passed=False``
    and ``blocked=True`` (Requirement 8.4).
    """
    result = evaluate_and_select(
        _fixed_candidates(),
        selection_scores=SELECTION_SCORES,
        gate=LAUNCH_GATE,
        gate_measurements=FAILING_MEASUREMENTS,
        registry=None,  # clean register treated as no warnings / nothing prohibiting
    )

    # Selection is unaffected by the gate outcome.
    assert result.selection.selected == WINNER_ID

    gate_result = result.gate_result
    assert isinstance(gate_result, GateResult)
    assert gate_result.overall_passed is False
    assert gate_result.blocked is True
    # The failing latency criterion is reported and has a remediation entry.
    failing = [c for c in gate_result.criteria_results if not c.passed]
    assert any(c.metric_name == _LATENCY_METRIC for c in failing)
    assert gate_result.remediation  # at least one corrective-action entry


def test_pipeline_without_gate_has_no_gate_result() -> None:
    """With no gate supplied, the pipeline still evaluates + selects, gate=None.

    Confirms the gate stage is correctly optional in the wiring: the harness and
    selection still run, and ``gate_result`` is ``None`` (Requirement 8.4 path
    where no gate is evaluated).
    """
    result = evaluate_and_select(
        _fixed_candidates(),
        selection_scores=SELECTION_SCORES,
    )

    assert result.gate_result is None
    # Evaluate + select still produced their artifacts.
    assert len(result.harness_runs) == 3
    assert result.selection.selected == WINNER_ID


def test_pipeline_retains_phase_1_when_no_scores_supplied() -> None:
    """Without selection scores, no candidate passes -> RETAIN_PHASE_1.

    Confirms the conservative default flows through the wiring: with empty score
    maps every candidate fails its minimums (fail-closed), so the selection is
    the ``RETAIN_PHASE_1`` sentinel while the harness records are still produced.
    """
    result = evaluate_and_select(_fixed_candidates())

    assert result.selection.selected == RETAIN_PHASE_1
    assert result.selection.passing == []
    # Records are still produced, one per candidate (exclusion preserved).
    assert len(result.harness_runs) == 3
