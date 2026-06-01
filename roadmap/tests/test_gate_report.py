"""Unit tests for the gate report renderer (Requirements 8.5, 1.5).

These are plain ``pytest`` example-based tests for
:func:`roadmap.reports.gate_report.render_gate_report`. They build realistic
:class:`~roadmap.models.selection.GateResult` inputs by running the real
:class:`~roadmap.gate_evaluator.GateEvaluator` over gates assembled from the
shared fixtures (``make_gate``, ``make_decision_gate``, ``make_criterion``),
then assert on the rendered Markdown string.

What is covered
---------------
- A **blocked** result lists exactly one remediation line per failing criterion
  (Requirement 8.5).
- A **decision-gate** report shows the single owner role and the
  "remain on LEAN_Track" fallback action (Requirement 1.5).
- A **passing** gate renders an overall ``PASS``, ``Blocked: no``, and no
  remediation section.
- A **missing measurement** is rendered with the "not measured" marker and its
  criterion shows ``FAIL`` (fail-closed).
- When a register with an unresolved warning / prohibiting license is supplied,
  the Compliance section appears.

Assertions check substrings of the rendered string (case-insensitive where
reasonable) so they stay robust to exact spacing while remaining specific.
"""

from __future__ import annotations

from roadmap.gate_evaluator import GateEvaluator
from roadmap.licensing import LicensingRegister
from roadmap.reports.gate_report import render_gate_report
from roadmap.tests.fixtures import make_criterion, make_decision_gate, make_gate


# --- Helpers ---------------------------------------------------------------


def _remediation_lines(report: str) -> list[str]:
    """Return the ``- ...`` bullet lines under the ``## Remediation`` section.

    Collects the bullet lines that follow the ``## Remediation`` header up to
    the next ``## `` section header (or end of report), so the count reflects
    exactly the remediation entries.
    """
    lines = report.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == "## Remediation":
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                out.append(line)
    return out


# --- Blocked result: one remediation line per failing criterion (8.5) ------


def test_blocked_result_has_one_remediation_line_per_failing_criterion() -> None:
    """A BLOCKED gate lists exactly one remediation line per failing criterion.

    Validates: Requirements 8.5
    """
    evaluator = GateEvaluator()
    gate = make_gate(
        id="LEAN-DEMO",
        kind="launch",
        exit_criteria=[
            make_criterion("latency_ms_p50", 300.0, "<="),
            make_criterion("hinglish_codeswitch_quality", 80.0, ">="),
            make_criterion("expressiveness_mos", 4.0, ">="),
        ],
    )
    # latency passes (250 <= 300); the other two fail -> 2 failing criteria.
    measured = {
        "latency_ms_p50": 250.0,
        "hinglish_codeswitch_quality": 55.0,
        "expressiveness_mos": 2.5,
    }
    result = evaluator.evaluate(gate, measured)
    assert result.blocked is True

    report = render_gate_report(result, gate=gate)

    # The report has a remediation section.
    assert "## Remediation" in report
    assert "Remediation".lower() in report.lower()

    remediation_lines = _remediation_lines(report)
    failing_metrics = ["hinglish_codeswitch_quality", "expressiveness_mos"]

    # Exactly one remediation line per failing criterion (no licensing block).
    assert len(remediation_lines) == len(failing_metrics)

    # Each failing metric name appears on exactly one remediation line.
    for metric in failing_metrics:
        matches = [line for line in remediation_lines if metric in line]
        assert len(matches) == 1, (
            f"expected exactly one remediation line for {metric!r}, "
            f"found {len(matches)} in {remediation_lines!r}"
        )

    # The passing metric does not get a remediation line.
    assert not any("latency_ms_p50" in line for line in remediation_lines)

    # Overall result is FAIL and blocked.
    assert "FAIL" in report
    assert "Blocked: yes" in report


# --- Decision gate: owner role + "remain on LEAN_Track" fallback (1.5) -----


def test_decision_gate_report_shows_owner_and_remain_on_lean_track_fallback() -> None:
    """A decision-gate report shows the owner role and the LEAN_Track fallback.

    Validates: Requirements 1.5
    """
    evaluator = GateEvaluator()
    gate = make_decision_gate(
        id="G1",
        owner_role="ML Lead",
        fallback_action="remain on LEAN_Track",
        exit_criteria=[make_criterion("core_quality_score", 80.0, ">=")],
    )
    # Make it fail so the fallback is meaningful in context.
    result = evaluator.evaluate(gate, {"core_quality_score": 40.0})

    report = render_gate_report(result, gate=gate)

    # The header notes the decision kind.
    assert "decision" in report.lower()
    # The single owner role is shown.
    assert "ML Lead" in report
    # The explicitly-allowed fallback action is shown verbatim.
    assert "remain on LEAN_Track" in report
    # A dedicated decision-gate section is rendered.
    assert "## Decision Gate" in report


def test_launch_gate_report_has_no_decision_gate_section() -> None:
    """A launch gate (non-decision) does not render the Decision Gate section."""
    evaluator = GateEvaluator()
    gate = make_gate(id="LEAN-DEMO", kind="launch")
    result = evaluator.evaluate(
        gate,
        {"latency_ms_p50": 100.0, "hinglish_codeswitch_quality": 95.0},
    )

    report = render_gate_report(result, gate=gate)

    assert "## Decision Gate" not in report
    assert "launch" in report.lower()


# --- Passing gate: overall PASS, not blocked, no remediation ---------------


def test_passing_gate_renders_pass_not_blocked_and_no_remediation() -> None:
    """A passing gate renders an overall PASS, not blocked, and no remediation."""
    evaluator = GateEvaluator()
    gate = make_gate(
        id="LEAN-DEMO",
        kind="launch",
        exit_criteria=[
            make_criterion("latency_ms_p50", 300.0, "<="),
            make_criterion("hinglish_codeswitch_quality", 80.0, ">="),
        ],
    )
    measured = {"latency_ms_p50": 220.0, "hinglish_codeswitch_quality": 92.0}
    result = evaluator.evaluate(gate, measured)
    assert result.overall_passed is True

    report = render_gate_report(result, gate=gate)

    assert "Overall: PASS" in report
    assert "Blocked: no" in report
    # No remediation section for a passing gate.
    assert "## Remediation" not in report
    assert _remediation_lines(report) == []


# --- Missing measurement: rendered as not-measured marker + FAIL -----------


def test_missing_measurement_renders_not_measured_marker_and_fail() -> None:
    """A missing measurement renders the not-measured marker and FAILs (fail-closed)."""
    evaluator = GateEvaluator()
    gate = make_gate(
        id="LEAN-DEMO",
        kind="launch",
        exit_criteria=[
            make_criterion("latency_ms_p50", 300.0, "<="),
            make_criterion("never_measured_metric", 80.0, ">="),
        ],
    )
    # Only provide one of the two metrics; the other is fail-closed.
    measured = {"latency_ms_p50": 150.0}
    result = evaluator.evaluate(gate, measured)
    assert result.blocked is True

    report = render_gate_report(result, gate=gate)

    # The unmeasured criterion is rendered with the readable marker, not "nan".
    assert "not measured" in report.lower()
    assert "nan" not in report.lower()
    # The unmeasured criterion appears, fails, and is remediated.
    assert "never_measured_metric" in report
    assert "FAIL" in report
    remediation_lines = _remediation_lines(report)
    assert any("never_measured_metric" in line for line in remediation_lines)


# --- Compliance section appears for a register that blocks the gate --------


def test_compliance_section_appears_for_unresolved_warning() -> None:
    """A register with an unresolved compliance warning renders the Compliance section."""
    evaluator = GateEvaluator()
    gate = make_gate(
        id="LEAN-DEMO",
        kind="launch",
        exit_criteria=[make_criterion("latency_ms_p50", 300.0, "<=")],
    )
    registry = LicensingRegister()
    # Recording with an unrecognized/None license retains an unresolved warning.
    registry.record_component("mystery-dataset", license_id=None, constraints=[])

    measured = {"latency_ms_p50": 100.0}  # criterion passes; register blocks.
    result = evaluator.evaluate(gate, measured, registry)
    assert result.blocked is True

    report = render_gate_report(result, gate=gate, registry=registry)

    assert "## Compliance" in report
    assert "mystery-dataset" in report


def test_compliance_section_appears_for_prohibiting_license() -> None:
    """A register with a prohibiting license renders the Compliance section."""
    evaluator = GateEvaluator()
    gate = make_gate(
        id="LEAN-DEMO",
        kind="launch",
        exit_criteria=[make_criterion("latency_ms_p50", 300.0, "<=")],
    )
    registry = LicensingRegister()
    registry.record_component(
        "prohibited-model",
        license_id="GPL-3.0",
        constraints=[],
        intended_use_permitted=False,
    )

    measured = {"latency_ms_p50": 100.0}
    result = evaluator.evaluate(gate, measured, registry)
    assert result.blocked is True

    report = render_gate_report(result, gate=gate, registry=registry)

    assert "## Compliance" in report
    assert "prohibited-model" in report


def test_clean_registry_renders_no_compliance_section() -> None:
    """A clean register (no warnings, nothing prohibiting) renders no Compliance section."""
    evaluator = GateEvaluator()
    gate = make_gate(
        id="LEAN-DEMO",
        kind="launch",
        exit_criteria=[make_criterion("latency_ms_p50", 300.0, "<=")],
    )
    registry = LicensingRegister()
    registry.record_component(
        "clean-model", license_id="Apache-2.0", constraints=[], intended_use_permitted=True
    )

    result = evaluator.evaluate(gate, {"latency_ms_p50": 100.0}, registry)
    report = render_gate_report(result, gate=gate, registry=registry)

    assert "## Compliance" not in report
