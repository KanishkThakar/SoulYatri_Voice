"""Render a human-readable launch/decision-gate report from a ``GateResult``.

This module turns the *output* of :class:`~roadmap.gate_evaluator.GateEvaluator`
— a :class:`~roadmap.models.selection.GateResult` — into a human-readable
Markdown report. It is the presentation counterpart to the gate-evaluation
decision logic and intentionally adds **no** decision-making of its own: it
reports exactly what the ``GateResult`` (and, when supplied, the originating
:class:`~roadmap.models.phases.Gate` and
:class:`~roadmap.licensing.LicensingRegister`) already say.

What the report contains (Requirements 1.4, 1.5, 8.4, 8.5, 11.5, 11.7)
----------------------------------------------------------------------
- A header with the gate id and, when the ``Gate`` is provided, its kind
  (``decision`` / ``launch``).
- A per-criterion table: each criterion's ``metric_name``, measured value
  (a missing/NaN measurement — the ``MISSING_MEASUREMENT`` sentinel — is
  rendered as ``"— (not measured)"``), threshold, operator, and ``PASS``/
  ``FAIL`` (Requirements 1.4, 8.4).
- The overall result (``PASS``/``FAIL``) and the ``blocked`` flag
  (Requirements 8.4, 8.5).
- The remediation list, one line per entry, when present (Requirement 8.5).
- For a Decision_Gate (``gate.kind == "decision"``): the single ``owner_role``
  and the ``fallback_action`` — e.g. "remain on LEAN_Track" (Requirements 1.4,
  1.5).
- When a :class:`LicensingRegister` is provided: a compliance note listing any
  unresolved compliance warnings and/or adopted components whose license
  prohibits the intended use that contribute to a block (Requirements 11.5,
  11.7).

This module performs no I/O and no GPU/training work; it is a pure string
renderer operating on the already-computed planning objects.

Requirements: 1.4, 1.5, 8.4, 8.5, 11.5, 11.7.
"""

from __future__ import annotations

import math
from typing import Optional

from ..licensing import LicensingRegister
from ..models.phases import Gate
from ..models.selection import CriterionResult, GateResult

__all__ = [
    "render_gate_report",
]

#: How a missing / NaN measured value (the ``MISSING_MEASUREMENT`` sentinel) is
#: rendered in the per-criterion table so a reader can distinguish "measured a
#: real value that failed" from "no value was ever measured" (fail-closed).
_NOT_MEASURED = "— (not measured)"


def render_gate_report(
    gate_result: GateResult,
    *,
    gate: Optional[Gate] = None,
    registry: Optional[LicensingRegister] = None,
) -> str:
    """Render a human-readable Markdown report for an evaluated gate.

    Produces a launch/decision-gate report from an already-computed
    :class:`GateResult`. The renderer is pure: it reports exactly what the
    ``gate_result`` (and the optional ``gate`` / ``registry``) contain and makes
    no pass/fail decisions of its own.

    Args:
        gate_result: The :class:`GateResult` produced by the gate evaluator —
            the per-criterion results, the overall pass/fail, the ``blocked``
            flag, and the remediation list.
        gate: The originating :class:`Gate`, when available. Supplying it lets
            the report show the gate ``kind`` in the header and, for a
            Decision_Gate (``kind == "decision"``), the single ``owner_role``
            and the ``fallback_action`` (Requirements 1.4, 1.5).
        registry: The :class:`LicensingRegister` consulted during evaluation,
            when available. Supplying it lets the report note any unresolved
            compliance warnings and/or prohibiting licenses that contribute to a
            block (Requirements 11.5, 11.7).

    Returns:
        A Markdown string. The report always contains the header, the
        per-criterion section, and the overall/blocked summary; the
        remediation, decision-gate, and compliance sections appear only when
        their data is present.
    """
    lines: list[str] = []
    lines.extend(_render_header(gate_result, gate))
    lines.append("")
    lines.extend(_render_criteria(gate_result.criteria_results))
    lines.append("")
    lines.extend(_render_summary(gate_result))

    remediation_section = _render_remediation(gate_result)
    if remediation_section:
        lines.append("")
        lines.extend(remediation_section)

    decision_section = _render_decision_gate(gate)
    if decision_section:
        lines.append("")
        lines.extend(decision_section)

    compliance_section = _render_compliance(registry)
    if compliance_section:
        lines.append("")
        lines.extend(compliance_section)

    return "\n".join(lines) + "\n"


# -- Section renderers -------------------------------------------------------


def _render_header(gate_result: GateResult, gate: Optional[Gate]) -> list[str]:
    """Render the report header with the gate id and (when known) its kind."""
    if gate is not None:
        title = f"Gate Report: {gate_result.gate_id} ({gate.kind} gate)"
    else:
        title = f"Gate Report: {gate_result.gate_id}"
    return [f"# {title}"]


def _render_criteria(criteria_results: list[CriterionResult]) -> list[str]:
    """Render the per-criterion table (metric/measured/threshold/op/result)."""
    lines = ["## Criteria"]
    if not criteria_results:
        lines.append("")
        lines.append("_No criteria were evaluated for this gate._")
        return lines

    lines.append("")
    lines.append("| Metric | Measured | Operator | Threshold | Result |")
    lines.append("| --- | --- | --- | --- | --- |")
    for result in criteria_results:
        lines.append(
            f"| {result.metric_name} "
            f"| {_format_measured(result.measured)} "
            f"| `{result.operator}` "
            f"| {_format_number(result.threshold)} "
            f"| {_pass_fail(result.passed)} |"
        )
    return lines


def _render_summary(gate_result: GateResult) -> list[str]:
    """Render the overall pass/fail and the blocked flag."""
    return [
        "## Result",
        "",
        f"- Overall: {_pass_fail(gate_result.overall_passed)}",
        f"- Blocked: {_yes_no(gate_result.blocked)}",
    ]


def _render_remediation(gate_result: GateResult) -> list[str]:
    """Render the remediation list (one line per entry) when present (8.5)."""
    if not gate_result.remediation:
        return []
    lines = ["## Remediation", ""]
    lines.extend(f"- {entry}" for entry in gate_result.remediation)
    return lines


def _render_decision_gate(gate: Optional[Gate]) -> list[str]:
    """Render the owner role and fallback action for a Decision_Gate (1.4, 1.5)."""
    if gate is None or gate.kind != "decision":
        return []
    return [
        "## Decision Gate",
        "",
        f"- Owner: {gate.owner_role}",
        f"- Fallback action: {gate.fallback_action}",
    ]


def _render_compliance(registry: Optional[LicensingRegister]) -> list[str]:
    """Render licensing notes that contribute to a block (11.5, 11.7).

    Lists unresolved compliance warnings and adopted components whose license
    prohibits the intended use. Returns an empty section when the register is
    ``None`` or clean.
    """
    if registry is None:
        return []

    has_warnings = registry.has_unresolved_warnings()
    has_prohibiting = registry.has_prohibiting_license()
    if not has_warnings and not has_prohibiting:
        return []

    lines = ["## Compliance", ""]

    if has_warnings:
        names = ", ".join(
            sorted(w.component_name for w in registry.unresolved_warnings())
        )
        lines.append(
            f"- Unresolved compliance warning(s) for: {names}. "
            "This blocks the gate until a recognized open-source license "
            "identifier is recorded (Requirement 11.7)."
        )

    if has_prohibiting:
        names = ", ".join(
            sorted(
                entry.component_name
                for entry in registry.entries()
                if not entry.intended_use_permitted
            )
        )
        lines.append(
            f"- Prohibiting license on adopted component(s): {names}. "
            "This blocks the gate until the component is removed, replaced, or "
            "relicensed (Requirements 11.5, 11.7)."
        )

    return lines


# -- Value formatting --------------------------------------------------------


def _format_measured(measured: float) -> str:
    """Render a measured value, mapping the NaN sentinel to a readable marker.

    The gate evaluator records a missing measurement as ``float("nan")`` (the
    ``MISSING_MEASUREMENT`` sentinel); detect it with :func:`math.isnan` and
    render it as "not measured" rather than the literal ``nan``.
    """
    if isinstance(measured, float) and math.isnan(measured):
        return _NOT_MEASURED
    return _format_number(measured)


def _format_number(value: float) -> str:
    """Render a numeric threshold/measured value without trailing ``.0`` noise.

    Integers-valued floats render without a decimal point (``300`` not
    ``300.0``); other values use their default ``str`` form.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return repr(value) if isinstance(value, float) else str(value)
    return str(value)


def _pass_fail(passed: bool) -> str:
    """Render a boolean pass/fail as ``PASS`` / ``FAIL``."""
    return "PASS" if passed else "FAIL"


def _yes_no(flag: bool) -> str:
    """Render a boolean flag as ``yes`` / ``no``."""
    return "yes" if flag else "no"
