"""Consolidated edge-case suite for the roadmap decision-logic components.

This is a plain ``pytest`` suite (with a few Hypothesis checks) that consolidates
the *boundary / degenerate input* coverage across every decision-logic
component, complementing — not duplicating — the per-component property tests
(Tasks 27–40) and the numbered design properties counted by Task 39.

It deliberately exercises the corners the per-component property tests tend to
under-emphasise: empty / single-element inputs, "exactly at the boundary"
values, all-missing measurements, multiple simultaneous exclusion triggers, and
invalid / missing compute inputs. Every expected value here was verified against
the *actual* implementation behaviour (see the inline notes), not assumed.

Reusable builders and strategies come from ``roadmap/tests/fixtures.py``
(Task 45.1). The Hypothesis checks below use ``@settings(max_examples=100)`` and
plain descriptive comments — they are NOT the numbered design properties, so
they intentionally avoid the ``# Feature: ..., Property {n}:`` comment format.

Requirements exercised: 2.3, 5.4, 6.5, 7.4 (plus the surrounding decision logic).
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings

from roadmap import (
    RETAIN_PHASE_1,
    SELECTION_MINIMUMS,
    BudgetComputePlanner,
    CoreFailureType,
    DuplexManager,
    EmotionPersonaController,
    EvaluationHarness,
    FallbackTarget,
    GateEvaluator,
    HinglishDataEngine,
    SafetyGuard,
    SelectionScorer,
    TurnPhase,
    evaluate_and_select,
)
from roadmap.evaluation_harness import EXCLUSION_MISSING_WEIGHTS
from roadmap.tests import fixtures


# ===========================================================================
# SelectionScorer
# ===========================================================================
def test_selection_empty_candidate_list_retains_phase_1() -> None:
    """An empty candidate list yields RETAIN_PHASE_1 with empty aggregates.

    No candidate can pass every per-criterion minimum when there are no
    candidates at all, so the conservative default holds (Requirement 2.7).
    """
    outcome = SelectionScorer().select([])

    assert outcome.selected == RETAIN_PHASE_1
    assert outcome.aggregates == {}
    assert outcome.passing == []


def test_selection_single_candidate_exactly_at_every_minimum_is_selected() -> None:
    """A lone candidate scoring exactly each minimum passes (inclusive gate).

    ``passes_all_minimums`` uses ``score >= minimum``, so a candidate sitting
    exactly on every per-criterion minimum clears the gate and is selected
    (Requirements 2.3, 2.9).
    """
    exact_scores = {criterion: float(minimum) for criterion, minimum in SELECTION_MINIMUMS.items()}
    candidate = fixtures.make_candidate_scores(model_id="exactly-minimum", scores=exact_scores)

    outcome = SelectionScorer().select([candidate])

    assert outcome.selected == "exactly-minimum"
    assert outcome.passing == ["exactly-minimum"]


def test_selection_all_candidates_failing_one_minimum_retains_phase_1() -> None:
    """Every candidate missing exactly one minimum yields RETAIN_PHASE_1.

    Each candidate is otherwise strong but misses a single per-criterion
    minimum, so none passes and Phase 1 is retained (Requirement 2.7).
    """
    candidates = [
        fixtures.make_candidate_scores(
            model_id=f"miss-{criterion}",
            scores=fixtures.make_failing_selection_scores(failing_criterion=criterion),
        )
        for criterion in ("community_activity", "license_permissiveness", "full_duplex")
    ]

    outcome = SelectionScorer().select(candidates)

    assert outcome.selected == RETAIN_PHASE_1
    assert outcome.passing == []
    # Aggregates are still reported for every candidate (transparency).
    assert set(outcome.aggregates) == {c.model_id for c in candidates}


# ===========================================================================
# GateEvaluator
# ===========================================================================
def test_gate_with_zero_exit_criteria_passes_with_clean_registry() -> None:
    """A gate with no exit criteria passes (vacuous all-pass) on a clean register.

    ``all([])`` is ``True`` and a clean registry adds no block, so
    ``overall_passed`` is ``True`` and the gate is not blocked. This pins the
    actual implementation behaviour for the degenerate empty-criteria gate.
    """
    gate = fixtures.make_gate(exit_criteria=[])

    result = GateEvaluator().evaluate(gate, {}, fixtures.make_clean_registry())

    assert result.criteria_results == []
    assert result.overall_passed is True
    assert result.blocked is False
    assert result.remediation == []


def test_gate_with_all_metrics_missing_is_blocked() -> None:
    """When no measured value is supplied, every criterion fails closed.

    Each criterion whose metric is absent resolves to fail with a NaN measured
    sentinel, so the gate is blocked with one remediation entry per criterion.
    """
    gate = fixtures.make_gate()  # two default exit criteria

    result = GateEvaluator().evaluate(gate, {}, fixtures.make_clean_registry())

    assert result.overall_passed is False
    assert result.blocked is True
    assert all(not r.passed for r in result.criteria_results)
    assert all(math.isnan(r.measured) for r in result.criteria_results)
    assert len(result.remediation) == len(gate.exit_criteria)


# ===========================================================================
# EvaluationHarness
# ===========================================================================
def test_harness_exclusion_precedence_missing_weights_wins() -> None:
    """With several exclusion triggers, missing-weights takes precedence.

    A candidate that simultaneously lacks weights, carries a prohibiting
    license, AND has insufficient VRAM is recorded under ``missing_weights`` —
    the first condition in the fixed precedence order.
    """
    candidate = fixtures.make_mock_candidate(
        weights_available=False,
        license_compat="prohibited",
        hardware={"gpu_class": "L4", "vram_gb": 1.0},
    )

    run = EvaluationHarness().evaluate(candidate)

    assert run.excluded is True
    assert run.exclusion_category == EXCLUSION_MISSING_WEIGHTS
    assert run.metric_scores == {}  # sentinel: no measurement performed


def test_harness_evaluate_all_all_excluded_returns_one_record_each() -> None:
    """``evaluate_all`` over an all-excluded list still emits one record each.

    The run continues past every excluded candidate without aborting, so the
    output length equals the input length and order is preserved (Req 4.5).
    """
    candidates = [
        fixtures.make_mock_candidate(model_id="no-weights", weights_available=False),
        fixtures.make_mock_candidate(model_id="prohibited-lic", license_compat="prohibited"),
        fixtures.make_mock_candidate(
            model_id="tiny-gpu", hardware={"gpu_class": "T4", "vram_gb": 2.0}
        ),
    ]

    runs = EvaluationHarness().evaluate_all(candidates)

    assert [r.model_id for r in runs] == ["no-weights", "prohibited-lic", "tiny-gpu"]
    assert all(r.excluded for r in runs)
    assert [r.exclusion_category for r in runs] == ["missing_weights", "license", "hardware"]


# ===========================================================================
# HinglishDataEngine
# ===========================================================================
def test_hinglish_normalize_empty_string() -> None:
    """Normalizing the empty string yields an empty result with no unmapped tokens."""
    result = HinglishDataEngine().normalize("")

    assert result.normalized_text == ""
    assert result.unmapped_tokens == []


def test_hinglish_normalize_only_unmapped_tokens() -> None:
    """Text of only-unknown tokens is returned unchanged and fully flagged.

    Tokens absent from the mapping are retained verbatim in ``normalized_text``
    and listed (in order) in ``unmapped_tokens`` for review (Requirement 5.8).
    """
    result = HinglishDataEngine().normalize("zzz qqq wibble")

    assert result.normalized_text == "zzz qqq wibble"
    assert result.unmapped_tokens == ["zzz", "qqq", "wibble"]


def test_hinglish_he_ratio_no_classifiable_tokens_is_zero() -> None:
    """Text with no Hindi/English word tokens has an H/E ratio of 0.0.

    Pure digits / punctuation classify as neither Hindi nor English, so the
    denominator is zero and the ratio is the documented 0.0 convention.
    """
    assert HinglishDataEngine().he_ratio("123 456 !!! ?? ...") == 0.0


# ===========================================================================
# EmotionPersonaController
# ===========================================================================
def test_emotion_label_none_with_extraction_ok_is_neutral() -> None:
    """A missing label (even with extraction_ok=True) yields NEUTRAL conditioning."""
    features = fixtures.make_emotion_features(label=None, extraction_ok=True)
    selection = EmotionPersonaController().select(features)

    assert selection.mode == "NEUTRAL"
    assert (selection.valence, selection.arousal, selection.dominance) == (0.0, 0.0, 0.0)
    assert selection.tag == "neutral"


def test_emotion_distress_at_exactly_threshold_is_empathetic() -> None:
    """A distress label at exactly confidence 0.50 selects EMPATHETIC (inclusive)."""
    features = fixtures.make_emotion_features(label="sad", confidence=0.50, extraction_ok=True)

    assert EmotionPersonaController().select_conditioning(features) == "EMPATHETIC"


def test_emotion_out_of_range_vad_is_clamped() -> None:
    """Out-of-range V/A/D requests are clamped into [-1, 1] on the selection.

    ``EmotionFeatures`` clamps on construction and the controller clamps again,
    so the effective conditioning vector can never leave the unit band (Req 6.1).
    """
    features = fixtures.make_emotion_features(
        label="happy", confidence=0.9, valence=5.0, arousal=-9.0, dominance=3.0, extraction_ok=True
    )
    selection = EmotionPersonaController().select(features)

    assert selection.valence == 1.0
    assert selection.arousal == -1.0
    assert selection.dominance == 1.0


# ===========================================================================
# DuplexManager
# ===========================================================================
def test_duplex_voiced_speech_exactly_150ms_from_speaking_triggers() -> None:
    """Exactly 150 ms of voiced speech while SPEAKING triggers a barge-in.

    The ``min_voiced_ms`` threshold is inclusive, and SPEAKING is barge-in
    eligible, so the decision fires and schedules its deadlines (Req 7.4/7.5).
    """
    decision = DuplexManager().decide_barge_in(
        voiced_speech_ms=150.0, current_state=TurnPhase.SPEAKING, detection_time_ms=0.0
    )

    assert decision.barge_in_triggered is True
    assert decision.resulting_state == TurnPhase.LISTENING
    assert decision.suppression_deadline_ms == 200.0
    assert decision.listening_transition_deadline_ms == 100.0


def test_duplex_first_token_exactly_at_budget_is_not_a_latency_violation() -> None:
    """A first token at exactly the 300 ms budget is within budget (no fallback).

    The budget comparison is ``first_token > budget`` (strict), so landing
    exactly on the budget does NOT count as a latency violation (Req 3.5).
    """
    decision = DuplexManager().decide_latency_fallback(first_token_latency_ms=300.0)

    assert decision.latency_violation is False
    assert decision.fallback_triggered is False
    assert decision.fallback_target == FallbackTarget.NONE


def test_duplex_first_token_none_is_a_latency_violation() -> None:
    """No first token within the window is a latency-budget violation.

    With Phase 1 available the turn is completed via the Phase 1 pipeline.
    """
    decision = DuplexManager().decide_latency_fallback(
        first_token_latency_ms=None, core_failure_type=CoreFailureType.NO_TOKEN_IN_WINDOW
    )

    assert decision.latency_violation is True
    assert decision.fallback_triggered is True
    assert decision.fallback_target == FallbackTarget.PHASE_1_PIPELINE


# ===========================================================================
# BudgetComputePlanner.select_scope
# ===========================================================================
def test_budget_available_exactly_at_phase_minimum_is_full_scope() -> None:
    """Available VRAM exactly at the phase minimum yields the full-scope plan.

    The reduced-scope branch fires only when ``confirmed < phase_min`` (or it is
    zero/invalid), so sitting exactly on the minimum runs the full scope (9.5).
    """
    planner = fixtures.make_budget_planner()
    # The canonical P1-baseline phase carries a 24 GB minimum.
    plan = planner.select_scope("P1-baseline", 24.0)

    assert plan.scope == "full"
    assert plan.footprint.vram_gb == 24.0
    assert plan.footprint_within_available is True


def test_budget_invalid_none_available_yields_reduced_cpu_footprint() -> None:
    """A None / invalid availability resolves to a reduced no-GPU footprint.

    Invalid/missing compute confirms 0 GB available, so the planner returns a
    reduced-scope CPU footprint that fits within the (zero) available compute.
    """
    planner = fixtures.make_budget_planner()
    plan = planner.select_scope("P1-baseline", None)

    assert plan.scope == "reduced"
    assert plan.confirmed_available_vram_gb == 0.0
    assert plan.footprint.gpu_class == "CPU"
    assert plan.footprint.vram_gb == 0.0
    assert plan.footprint_within_available is True


# ===========================================================================
# SafetyGuard
# ===========================================================================
def test_safety_none_consent_is_refused_and_not_logged() -> None:
    """A missing consent record refuses cloning and logs nothing (Req 10.1/10.3)."""
    guard = SafetyGuard()
    decision = guard.evaluate_cloning_request(None, product_facing=True)

    assert decision.allowed is False
    assert decision.reference_retained is False
    assert guard.consent_log() == []


def test_safety_valid_consent_is_logged_with_three_fields() -> None:
    """Valid product-facing consent is logged with exactly the three fields (10.6)."""
    guard = SafetyGuard()
    consent = fixtures.make_consent_record(
        speaker_id="spk-9", permitted_use_scope="voice-clone", timestamp=1_700_000_111.0
    )

    decision = guard.evaluate_cloning_request(consent, product_facing=True)

    assert decision.allowed is True
    assert decision.reference_retained is True
    log = guard.consent_log()
    assert len(log) == 1
    entry = log[0]
    assert entry.speaker_id == "spk-9"
    assert entry.permitted_use_scope == "voice-clone"
    assert entry.timestamp == 1_700_000_111.0


def test_safety_crisis_exactly_at_threshold_fires_both_actions() -> None:
    """A crisis score exactly at the threshold surfaces guidance AND flags review."""
    guard = SafetyGuard()
    decision = guard.handle_crisis(0.5, threshold=0.5)

    assert decision.crisis_support_surfaced is True
    assert decision.flagged_for_human_review is True
    assert decision.triggered is True
    assert decision.guidance is not None


# ===========================================================================
# evaluate_and_select pipeline
# ===========================================================================
def test_pipeline_no_selection_scores_retains_phase_1_but_produces_records() -> None:
    """With no selection scores the pipeline retains Phase 1 yet still records runs.

    Each evaluable candidate is scored with an empty (fail-closed) score map, so
    no candidate passes and the outcome is RETAIN_PHASE_1 — but one harness
    record is still produced per candidate (Requirement 2.7).
    """
    candidates = [
        fixtures.make_mock_candidate(model_id="cand-a"),
        fixtures.make_mock_candidate(model_id="cand-b"),
    ]

    result = evaluate_and_select(candidates)

    assert result.selection.selected == RETAIN_PHASE_1
    assert [r.model_id for r in result.harness_runs] == ["cand-a", "cand-b"]
    assert all(not r.excluded for r in result.harness_runs)
    assert result.gate_result is None


# ===========================================================================
# Hypothesis edge-case checks (NOT the numbered design properties)
# ===========================================================================
# These use the fixtures' strategies to sweep degenerate corners of the input
# space. They are descriptive edge-case checks, deliberately NOT tagged with the
# numbered ``# Feature: ..., Property {n}:`` format reserved for the 15 design
# properties.


@settings(max_examples=100)
@given(features=fixtures.emotion_features_strategy())
def test_emotion_effective_vad_always_within_unit_band(features) -> None:
    """For any (even out-of-range) features, the effective V/A/D stays in [-1, 1]."""
    selection = EmotionPersonaController().select(features)

    assert -1.0 <= selection.valence <= 1.0
    assert -1.0 <= selection.arousal <= 1.0
    assert -1.0 <= selection.dominance <= 1.0


@settings(max_examples=100)
@given(candidates=fixtures.candidate_list_strategy())
def test_selection_selected_is_retain_or_a_passing_model(candidates) -> None:
    """The selected core is always RETAIN_PHASE_1 or one of the passing models."""
    outcome = SelectionScorer().select(candidates)

    if outcome.passing:
        assert outcome.selected in outcome.passing
    else:
        assert outcome.selected == RETAIN_PHASE_1


@settings(max_examples=100)
@given(available=fixtures.available_compute_strategy)
def test_budget_scope_footprint_never_exceeds_confirmed_available(available) -> None:
    """For any availability input, the returned footprint fits within confirmed VRAM."""
    planner = fixtures.make_budget_planner()
    plan = planner.select_scope("P1-baseline", available)

    assert plan.footprint.vram_gb <= plan.confirmed_available_vram_gb
    assert plan.footprint_within_available is True
