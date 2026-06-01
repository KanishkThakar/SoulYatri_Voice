"""Property-based tests for the Gate Evaluator (Requirements 1.4, 1.5, 8.4, 8.5, 11.5, 11.7).

This module implements **Property 2** from ``design.md`` ("Correctness
Properties") for the :class:`~roadmap.gate_evaluator.GateEvaluator` decision
logic. The evaluator is a pure function of its inputs — a :class:`Gate`
definition, a dict of measured values, and a
:class:`~roadmap.licensing.LicensingRegister` state — so the property runs
without any GPU/training work.

Property 2 (consolidated): *for any* gate definition, *any* set of measured
values, and *any* Licensing_Register state, the gate evaluator

* resolves each criterion to exactly one pass/fail result consistent with its
  operator (a missing metric fails closed, recorded as a NaN measurement);
* yields ``overall_passed`` **iff** every criterion passes **and** the register
  has no unresolved compliance warning and no prohibiting license (verified in
  both directions across clean / warning / prohibiting register states);
* marks the result ``blocked`` with one remediation entry per failing criterion
  when not passed (licensing may add extra entries), and an empty remediation /
  unblocked result when passed; and
* for a Decision_Gate, surfaces the gate's single owner role and fallback
  action (where "remain on LEAN_Track" is an allowed fallback value).
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.gate_evaluator import GateEvaluator
from roadmap.licensing import RECOGNIZED_OSS_LICENSES, LicensingRegister
from roadmap.models.phases import OPERATOR_VALUES, Gate, GateCriterion

# --- Generators -----------------------------------------------------------

# Metric names use a lowercase alphabet so a criterion-remediation entry
# (``"{metric_name}: ..."``) can never collide with a licensing-remediation
# entry (``"Licensing: ..."``), letting the test count the two kinds apart.
_METRIC_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_"
_metric_name = st.text(alphabet=_METRIC_ALPHABET, min_size=1, max_size=12)

# A small mix of "round" values and arbitrary bounded floats so equality-style
# operators (``==``, ``<=``, ``>=``) sometimes pass and sometimes fail, giving
# coverage of both the passing and the blocked branches.
_value = st.one_of(
    st.sampled_from([0.0, 25.0, 50.0, 75.0, 100.0]),
    st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)

_operator = st.sampled_from(OPERATOR_VALUES)
_gate_id = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-", min_size=1, max_size=6)
_owner_role = st.sampled_from(["ML Lead", "Project Lead", "Eval Owner", "Release Manager"])

# The fallback set deliberately includes "remain on LEAN_Track" so the
# explicitly-allowed fallback value (Requirement 1.5) is exercised.
_ALLOWED_FALLBACKS = [
    "remain on LEAN_Track",
    "advance to AMBITIOUS_Track",
    "retain Phase_1_Pipeline",
]
_fallback_action = st.sampled_from(_ALLOWED_FALLBACKS)

_recognized_license = st.sampled_from(sorted(RECOGNIZED_OSS_LICENSES))


@st.composite
def _criterion(draw: st.DrawFn) -> GateCriterion:
    """Generate a single ``{metric_name, threshold, operator}`` criterion."""
    return GateCriterion(
        metric_name=draw(_metric_name),
        threshold=draw(_value),
        operator=draw(_operator),
    )


@st.composite
def _gate_and_measured(draw: st.DrawFn) -> tuple[Gate, dict[str, float]]:
    """Generate a valid gate plus a measured-values dict.

    The measured-values dict intentionally omits some criterion metrics (each
    unique metric name is included only on a coin-flip) so the fail-closed path
    for missing measurements is exercised. Both ``decision`` and ``launch``
    gate kinds are produced, always with a non-empty owner role and fallback
    action.
    """
    criteria = draw(st.lists(_criterion(), min_size=0, max_size=6))
    gate = Gate(
        id=draw(_gate_id),
        kind=draw(st.sampled_from(["decision", "launch"])),
        entry_criteria=[],
        exit_criteria=criteria,
        owner_role=draw(_owner_role),
        fallback_action=draw(_fallback_action),
    )

    measured: dict[str, float] = {}
    for name in {c.metric_name for c in criteria}:
        if draw(st.booleans()):
            measured[name] = draw(_value)
    return gate, measured


@st.composite
def _registry(draw: st.DrawFn) -> tuple[LicensingRegister | None, bool]:
    """Generate a Licensing_Register state and its expected "clean" verdict.

    Produces the four relevant register states with their independently-known
    cleanliness so the overall-pass iff can be checked in both directions:

    * ``none``        -> ``None`` register, treated as clean.
    * ``clean``       -> a recognized license, intended use permitted (clean).
    * ``warning``     -> a failed recording retains an unresolved warning (not clean).
    * ``prohibiting`` -> a recognized license but intended use NOT permitted (not clean).
    """
    kind = draw(st.sampled_from(["none", "clean", "warning", "prohibiting"]))
    if kind == "none":
        return None, True

    register = LicensingRegister()
    if kind == "clean":
        register.record_component(
            "comp-clean", draw(_recognized_license), [], intended_use_permitted=True
        )
        return register, True
    if kind == "warning":
        # Recording with ``None`` fails and retains an unresolved warning (11.3).
        register.record_component("comp-warn", None, [])
        return register, False
    # prohibiting: recognized license recorded, but intended use is prohibited.
    register.record_component(
        "comp-prohibit", draw(_recognized_license), [], intended_use_permitted=False
    )
    return register, False


# --- Independent reference resolution -------------------------------------


def _satisfies(measured: float, operator: str, threshold: float) -> bool:
    """Independently recompute whether ``measured`` satisfies the criterion."""
    if operator == "<=":
        return measured <= threshold
    if operator == "<":
        return measured < threshold
    if operator == ">=":
        return measured >= threshold
    if operator == ">":
        return measured > threshold
    if operator == "==":
        return measured == threshold
    raise AssertionError(f"unexpected operator {operator!r}")


# --- Property 2 -----------------------------------------------------------


# Feature: speech-native-voice-roadmap, Property 2: Gate evaluation, blocking, remediation, and licensing block
# Validates: Requirements 1.4, 1.5, 8.4, 8.5, 11.5, 11.7
@settings(max_examples=100)
@given(gate_and_measured=_gate_and_measured(), registry_and_clean=_registry())
def test_property_2_gate_evaluation_blocking_remediation_and_licensing_block(
    gate_and_measured: tuple[Gate, dict[str, float]],
    registry_and_clean: tuple[LicensingRegister | None, bool],
) -> None:
    """Gate evaluation, overall-pass iff, blocking/remediation, and decision-gate owner/fallback.

    **Validates: Requirements 1.4, 1.5, 8.4, 8.5, 11.5, 11.7**
    """
    gate, measured = gate_and_measured
    registry, registry_clean = registry_and_clean

    evaluator = GateEvaluator()
    result = evaluator.evaluate(gate, measured, registry)

    # 1) Each criterion resolves to EXACTLY one pass/fail result, in order, and
    #    consistent with its operator. A missing metric fails closed and is
    #    recorded with a NaN measurement (Requirements 1.4, 8.4).
    assert len(result.criteria_results) == len(gate.exit_criteria)
    expected_failing = 0
    all_criteria_passed = True
    for criterion, cres in zip(gate.exit_criteria, result.criteria_results):
        assert cres.metric_name == criterion.metric_name
        assert cres.operator == criterion.operator
        assert cres.threshold == criterion.threshold
        assert isinstance(cres.passed, bool)

        if criterion.metric_name in measured:
            expected_pass = _satisfies(
                measured[criterion.metric_name], criterion.operator, criterion.threshold
            )
            assert cres.measured == measured[criterion.metric_name]
        else:
            # Fail-closed: no measured value -> fail, recorded as NaN.
            expected_pass = False
            assert math.isnan(cres.measured)

        assert cres.passed == expected_pass
        if not cres.passed:
            expected_failing += 1
            all_criteria_passed = False

    # 2) overall_passed is True IFF every criterion passes AND the register is
    #    clean (no unresolved warning, no prohibiting license). registry_clean
    #    is derived independently from the generated register kind, so this
    #    verifies the iff in both directions (Requirements 11.5, 11.7).
    expected_overall = all_criteria_passed and registry_clean
    assert result.overall_passed == expected_overall

    # 3) Blocking + remediation (Requirements 8.4, 8.5, 11.7).
    if result.overall_passed:
        # Passed: not blocked and no remediation.
        assert result.blocked is False
        assert result.remediation == []
    else:
        # Not passed: blocked, with exactly one remediation entry per failing
        # criterion. Licensing-caused blocks may append extra "Licensing:"
        # entries, which are excluded from the per-criterion count.
        assert result.blocked is True
        criterion_remediation = [
            r for r in result.remediation if not r.startswith("Licensing:")
        ]
        assert len(criterion_remediation) == expected_failing

    # 4) Decision-gate owner/fallback (Requirements 1.4, 1.5). A decision gate
    #    surfaces its single owner role and fallback action; a launch gate is
    #    rejected by evaluate_decision_gate.
    if gate.kind == "decision":
        decision = evaluator.evaluate_decision_gate(gate, measured, registry)
        assert decision.owner_role == gate.owner_role
        assert decision.fallback_action == gate.fallback_action
        # "remain on LEAN_Track" is an explicitly allowed fallback value.
        assert decision.fallback_action in _ALLOWED_FALLBACKS
        # The wrapped result matches a plain evaluate() call.
        assert decision.result.overall_passed == result.overall_passed
        assert decision.result.blocked == result.blocked
    else:
        with pytest.raises(ValueError):
            evaluator.evaluate_decision_gate(gate, measured, registry)
