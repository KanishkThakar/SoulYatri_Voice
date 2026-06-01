"""Boundary unit tests for :class:`roadmap.gate_evaluator.GateEvaluator`.

Plain ``pytest`` example tests that pin the boundary behaviour of gate
evaluation described in the requirements:

- **Requirement 8.4** — every gate threshold resolves to one measured/threshold/
  pass-or-fail result, and the overall result passes only when *every* threshold
  passes (here exercised by the fail-closed missing-metric and operator-boundary
  cases).
- **Requirement 8.5** — when any threshold is not met, the release is ``blocked``
  and the ``remediation`` path identifies *each* failing threshold with its
  corrective action (here: exactly one remediation entry per failing criterion).
- **Requirement 11.7** — an unresolved compliance warning *or* an adopted
  component whose license prohibits its intended use blocks an otherwise-passing
  gate, with a dedicated licensing remediation entry.

These complement the property-based suite in ``test_gate_evaluator.py`` by
nailing down specific boundary examples.

Requirements: 8.4, 8.5, 11.7
"""

from __future__ import annotations

import math

import pytest

from roadmap.gate_evaluator import GateEvaluator
from roadmap.licensing import LicensingRegister
from roadmap.models.phases import Gate, GateCriterion


@pytest.fixture
def evaluator() -> GateEvaluator:
    return GateEvaluator()


def _launch_gate(*criteria: GateCriterion) -> Gate:
    """Build a launch gate with the given exit criteria and required metadata."""
    return Gate(
        id="LG1",
        kind="launch",
        entry_criteria=[],
        exit_criteria=list(criteria),
        owner_role="Release Owner",
        fallback_action="withhold ship-ready declaration",
    )


# Three independent exit criteria used by the "one failing criterion" cases.
def _three_criteria() -> list[GateCriterion]:
    return [
        GateCriterion(metric_name="latency_ms_p50", threshold=300.0, operator="<="),
        GateCriterion(metric_name="codeswitch_quality", threshold=60.0, operator=">="),
        GateCriterion(metric_name="expressiveness", threshold=50.0, operator=">="),
    ]


# --- Requirement 8.5: one failing criterion -> exactly one remediation entry ---


def test_one_failing_criterion_produces_exactly_one_remediation(
    evaluator: GateEvaluator,
) -> None:
    """With 3 criteria where exactly one fails, there is exactly one remediation.

    Two criteria pass, one (``expressiveness``) fails. The gate must be blocked,
    not pass overall, and the remediation list must contain exactly one entry —
    the one naming the single failing criterion (Requirement 8.5).
    """
    gate = _launch_gate(*_three_criteria())
    measured = {
        "latency_ms_p50": 250.0,  # 250 <= 300 -> pass
        "codeswitch_quality": 72.0,  # 72 >= 60 -> pass
        "expressiveness": 40.0,  # 40 >= 50 -> FAIL
    }

    result = evaluator.evaluate(gate, measured, registry=None)

    assert result.overall_passed is False
    assert result.blocked is True
    # Exactly one criterion failed -> exactly one remediation entry.
    failing = [r for r in result.criteria_results if not r.passed]
    assert len(failing) == 1
    assert failing[0].metric_name == "expressiveness"
    assert len(result.remediation) == 1
    assert "expressiveness" in result.remediation[0]


# --- Requirement 8.4: missing metric forces overall fail (fail-closed) ---


def test_missing_metric_fails_closed(evaluator: GateEvaluator) -> None:
    """A metric absent from measured values fails closed and blocks the gate.

    The criterion for the missing metric is recorded ``passed=False`` with a
    ``NaN`` measured sentinel, the overall result does not pass, the gate is
    blocked, and the remediation mentions the unmeasured metric (Req 8.4/8.5).
    """
    gate = _launch_gate(*_three_criteria())
    # "expressiveness" deliberately omitted -> fail-closed.
    measured = {
        "latency_ms_p50": 250.0,
        "codeswitch_quality": 72.0,
    }

    result = evaluator.evaluate(gate, measured, registry=None)

    missing = next(
        r for r in result.criteria_results if r.metric_name == "expressiveness"
    )
    assert missing.passed is False
    assert math.isnan(missing.measured)

    assert result.overall_passed is False
    assert result.blocked is True
    assert len(result.remediation) == 1
    assert "expressiveness" in result.remediation[0]
    assert "no measured value provided" in result.remediation[0]


# --- Requirement 11.7: unresolved warning blocks otherwise-passing gate ---


def test_unresolved_warning_blocks_passing_gate(evaluator: GateEvaluator) -> None:
    """All criteria pass, but an unresolved compliance warning blocks the gate.

    Recording a component with an unrecognized/None license id leaves an
    unresolved compliance warning. Even though every criterion passes, the gate
    must not pass overall, must be blocked, and must carry a licensing
    remediation entry (Requirement 11.7).
    """
    gate = _launch_gate(*_three_criteria())
    measured = {
        "latency_ms_p50": 250.0,
        "codeswitch_quality": 72.0,
        "expressiveness": 80.0,
    }

    registry = LicensingRegister()
    # Unrecognized license id -> recording fails -> unresolved warning retained.
    registry.record_component("some-tts-model", license_id=None)
    assert registry.has_unresolved_warnings() is True

    result = evaluator.evaluate(gate, measured, registry=registry)

    # Every criterion passes on its own.
    assert all(r.passed for r in result.criteria_results)
    # But the unresolved warning blocks the gate.
    assert result.overall_passed is False
    assert result.blocked is True
    licensing_entries = [m for m in result.remediation if m.startswith("Licensing:")]
    assert len(licensing_entries) == 1
    assert "some-tts-model" in licensing_entries[0]


# --- Requirement 11.7: prohibiting license blocks otherwise-passing gate ---


def test_prohibiting_license_blocks_passing_gate(evaluator: GateEvaluator) -> None:
    """An adopted component whose license prohibits its use blocks the gate.

    The component is recorded with a recognized license (no warning) but
    ``intended_use_permitted=False``. All criteria pass, yet the prohibiting
    license must block the otherwise-passing gate and add a licensing
    remediation entry (Requirement 11.7).
    """
    gate = _launch_gate(*_three_criteria())
    measured = {
        "latency_ms_p50": 250.0,
        "codeswitch_quality": 72.0,
        "expressiveness": 80.0,
    }

    registry = LicensingRegister()
    registry.record_component(
        "non-commercial-model",
        license_id="GPL-3.0",
        intended_use_permitted=False,
    )
    # Recognized license -> no unresolved warning, but a prohibiting license.
    assert registry.has_unresolved_warnings() is False
    assert registry.has_prohibiting_license() is True

    result = evaluator.evaluate(gate, measured, registry=registry)

    assert all(r.passed for r in result.criteria_results)
    assert result.overall_passed is False
    assert result.blocked is True
    licensing_entries = [m for m in result.remediation if m.startswith("Licensing:")]
    assert len(licensing_entries) == 1
    assert "non-commercial-model" in licensing_entries[0]
    assert "prohibits" in licensing_entries[0]


# --- Fully-passing gate with clean registry -> pass, not blocked ---


def test_passing_gate_clean_registry_none(evaluator: GateEvaluator) -> None:
    """All criteria pass and registry is ``None`` -> pass, not blocked, no remediation."""
    gate = _launch_gate(*_three_criteria())
    measured = {
        "latency_ms_p50": 250.0,
        "codeswitch_quality": 72.0,
        "expressiveness": 80.0,
    }

    result = evaluator.evaluate(gate, measured, registry=None)

    assert all(r.passed for r in result.criteria_results)
    assert result.overall_passed is True
    assert result.blocked is False
    assert result.remediation == []


def test_passing_gate_clean_registry_instance(evaluator: GateEvaluator) -> None:
    """A clean (recognized-license) registry does not block a passing gate."""
    gate = _launch_gate(*_three_criteria())
    measured = {
        "latency_ms_p50": 250.0,
        "codeswitch_quality": 72.0,
        "expressiveness": 80.0,
    }

    registry = LicensingRegister()
    registry.record_component("clean-model", license_id="Apache-2.0")
    assert registry.has_unresolved_warnings() is False
    assert registry.has_prohibiting_license() is False

    result = evaluator.evaluate(gate, measured, registry=registry)

    assert result.overall_passed is True
    assert result.blocked is False
    assert result.remediation == []


# --- Operator boundary checks (Requirement 8.4) ---


def test_ge_operator_at_threshold_passes(evaluator: GateEvaluator) -> None:
    """``>=`` at exactly the threshold passes (inclusive boundary)."""
    gate = _launch_gate(
        GateCriterion(metric_name="codeswitch_quality", threshold=60.0, operator=">=")
    )
    result = evaluator.evaluate(gate, {"codeswitch_quality": 60.0}, registry=None)

    assert result.criteria_results[0].passed is True
    assert result.overall_passed is True
    assert result.blocked is False


def test_gt_operator_at_threshold_fails(evaluator: GateEvaluator) -> None:
    """``>`` at exactly the threshold fails (exclusive boundary)."""
    gate = _launch_gate(
        GateCriterion(metric_name="codeswitch_quality", threshold=60.0, operator=">")
    )
    result = evaluator.evaluate(gate, {"codeswitch_quality": 60.0}, registry=None)

    assert result.criteria_results[0].passed is False
    assert result.overall_passed is False
    assert result.blocked is True
    assert len(result.remediation) == 1


def test_le_operator_at_threshold_passes(evaluator: GateEvaluator) -> None:
    """``<=`` at exactly the threshold passes (inclusive boundary)."""
    gate = _launch_gate(
        GateCriterion(metric_name="latency_ms_p50", threshold=300.0, operator="<=")
    )
    result = evaluator.evaluate(gate, {"latency_ms_p50": 300.0}, registry=None)

    assert result.criteria_results[0].passed is True
    assert result.overall_passed is True
    assert result.blocked is False
