"""Render a human-readable budget & compute report from a planner.

This module turns a :class:`~roadmap.budget_planner.BudgetComputePlanner` — the
*output* of the design's *Budget & Compute Planner* (Requirement 9) — into a
human-readable Markdown report. Like the other renderers in this package it is a
**pure string function**: it performs no I/O, reads no files, and never invokes a
GPU / model-training run. It reports exactly what the planner already states and
makes no planning decisions of its own.

What the report contains (Requirements 9.1, 9.2, 9.3, 9.4, 9.5)
---------------------------------------------------------------
- **Budget ranges (9.2).** A small table of the LEAN and AMBITIOUS budget
  ranges as ``{lower, upper, currency}`` in the single stated currency, with
  ``lower <= upper`` (guaranteed by :class:`~roadmap.budget_planner.BudgetRange`).
- **Per-phase compute footprints (9.1).** A table of every phase's id, track,
  minimum GPU class, and minimum VRAM (GB), sourced from
  :meth:`~roadmap.budget_planner.BudgetComputePlanner.phase_footprints`.
- **LEAN feasibility claim (9.3).** The assertion that the LEAN_Track is
  executable by at most ``lean_max_team_size`` people without large-scale GPU
  training, read from
  :attr:`~roadmap.budget_planner.BudgetComputePlanner.lean_no_large_scale_training_claim`.
- **AMBITIOUS justification requirement (9.4).** A note that AMBITIOUS entry at
  ``G1`` requires an explicit justification (the AMBITIOUS budget range plus the
  per-phase compute footprint).
- **Reduced-scope alternatives (9.5).** When per-phase available-compute inputs
  are supplied, a table of the
  :meth:`~roadmap.budget_planner.BudgetComputePlanner.select_scope` decisions,
  each showing the chosen scope and a footprint that does not exceed the
  confirmed-available compute.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5.
"""

from __future__ import annotations

from typing import Mapping, Optional

from ..budget_planner import (
    AvailableCompute,
    BudgetComputePlanner,
    BudgetRange,
)
from ..roadmap_model import Roadmap

__all__ = [
    "render_budget_report",
]


def render_budget_report(
    planner: BudgetComputePlanner,
    roadmap: Optional[Roadmap] = None,
    *,
    available_compute: Optional[Mapping[str, AvailableCompute]] = None,
) -> str:
    """Render a human-readable Markdown budget & compute report.

    The renderer is pure: it reports exactly what ``planner`` (and the optional
    ``roadmap`` / ``available_compute``) contain and makes no planning decisions
    of its own.

    Args:
        planner: The :class:`~roadmap.budget_planner.BudgetComputePlanner` whose
            per-phase footprints, LEAN/AMBITIOUS budget ranges, LEAN feasibility
            claim, and AMBITIOUS-justification requirement are reported.
        roadmap: The originating :class:`~roadmap.roadmap_model.Roadmap`, when
            available. Supplying it lets the report use the roadmap's track
            labels (e.g. "primary" / "optional") in the budget table; it is
            otherwise unused (the planner already carries the phases). The
            two-argument form ``render_budget_report(planner, roadmap)`` is
            supported for callers that pass both.
        available_compute: Optional mapping of ``phase_id -> available compute``
            (a VRAM number in GB, a :class:`~roadmap.budget_planner.ComputeFootprint`,
            or a mapping with a ``vram_gb`` key). When provided, the report adds a
            reduced-scope-alternatives section built from
            :meth:`~roadmap.budget_planner.BudgetComputePlanner.select_scope`
            (Requirement 9.5).

    Returns:
        A Markdown string. The report always contains the header, the budget
        ranges, the per-phase footprint table, the LEAN feasibility claim, and
        the AMBITIOUS-justification note; the reduced-scope section appears only
        when ``available_compute`` is supplied.
    """
    lines: list[str] = ["# Budget & Compute Report", ""]
    lines.extend(_render_budget_ranges(planner, roadmap))
    lines.append("")
    lines.extend(_render_phase_footprints(planner))
    lines.append("")
    lines.extend(_render_lean_claim(planner))
    lines.append("")
    lines.extend(_render_ambitious_note(planner))

    scope_section = _render_reduced_scope(planner, available_compute)
    if scope_section:
        lines.append("")
        lines.extend(scope_section)

    return "\n".join(lines) + "\n"


# -- Section renderers -------------------------------------------------------


def _render_budget_ranges(
    planner: BudgetComputePlanner, roadmap: Optional[Roadmap]
) -> list[str]:
    """Render the LEAN / AMBITIOUS budget ranges as a ``{lower, upper, currency}`` table (9.2)."""
    track_labels = roadmap.track_labels if roadmap is not None else {}
    lean_label = track_labels.get("LEAN", "primary")
    ambitious_label = track_labels.get("AMBITIOUS", "optional")

    lines = [
        "## Budget Ranges",
        "",
        "| Track | Lower | Upper | Currency |",
        "| --- | --- | --- | --- |",
        _budget_row(f"LEAN ({lean_label})", planner.lean_budget),
        _budget_row(f"AMBITIOUS ({ambitious_label})", planner.ambitious_budget),
    ]
    return lines


def _render_phase_footprints(planner: BudgetComputePlanner) -> list[str]:
    """Render the per-phase compute-footprint table: id, track, GPU class, VRAM (9.1)."""
    lines = ["## Per-Phase Compute Footprints", ""]

    footprints = planner.phase_footprints()
    if not footprints:
        lines.append("_No phases were supplied to the planner._")
        return lines

    track_by_id = {p.id: p.track for p in planner.phases}

    lines.append("| Phase | Track | Min GPU class | Min VRAM (GB) |")
    lines.append("| --- | --- | --- | --- |")
    for phase in planner.phases:
        footprint = footprints[phase.id]
        lines.append(
            f"| {phase.id} "
            f"| {track_by_id.get(phase.id, '')} "
            f"| {footprint.gpu_class} "
            f"| {_format_number(footprint.vram_gb)} |"
        )
    return lines


def _render_lean_claim(planner: BudgetComputePlanner) -> list[str]:
    """Render the LEAN feasibility claim (<= N people, no large-scale training) (9.3)."""
    claim = planner.lean_no_large_scale_training_claim
    max_team = claim["max_team_size"]
    excludes = claim["excludes_large_scale_training"]
    definition = claim["large_scale_training_definition"]

    return [
        "## LEAN Feasibility Claim",
        "",
        f"- The LEAN_Track is executable by at most {_format_number(max_team)} "
        "people.",
        f"- Large-scale GPU training is {'excluded' if excludes else 'NOT excluded'} "
        f"from the LEAN_Track (large-scale training = {definition}).",
    ]


def _render_ambitious_note(planner: BudgetComputePlanner) -> list[str]:
    """Render the note that AMBITIOUS entry requires an explicit justification (9.4)."""
    budget = planner.ambitious_budget
    return [
        "## AMBITIOUS Entry Requirement",
        "",
        "- Entering the AMBITIOUS_Track at decision gate `G1` requires an "
        "explicit justification.",
        "- The justification must include the AMBITIOUS budget range "
        f"({_format_amount(budget.lower)}–{_format_amount(budget.upper)} "
        f"{budget.currency}) and the per-phase compute footprint.",
    ]


def _render_reduced_scope(
    planner: BudgetComputePlanner,
    available_compute: Optional[Mapping[str, AvailableCompute]],
) -> list[str]:
    """Render the ``select_scope`` decisions for the supplied availability inputs (9.5)."""
    if not available_compute:
        return []

    lines = [
        "## Scope Decisions for Available Compute",
        "",
        "| Phase | Scope | Footprint GPU class | Footprint VRAM (GB) | "
        "Confirmed available (GB) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for phase_id, available in available_compute.items():
        plan = planner.select_scope(phase_id, available)
        lines.append(
            f"| {plan.phase_id} "
            f"| {plan.scope} "
            f"| {plan.footprint.gpu_class} "
            f"| {_format_number(plan.footprint.vram_gb)} "
            f"| {_format_number(plan.confirmed_available_vram_gb)} |"
        )
    return lines


# -- Value formatting --------------------------------------------------------


def _budget_row(label: str, budget: BudgetRange) -> str:
    """Render a single budget-range table row."""
    return (
        f"| {label} "
        f"| {_format_amount(budget.lower)} "
        f"| {_format_amount(budget.upper)} "
        f"| {budget.currency} |"
    )


def _format_amount(value: float) -> str:
    """Render a currency amount with thousands separators and no trailing ``.0``."""
    as_float = float(value)
    if as_float.is_integer():
        return f"{int(as_float):,}"
    return f"{as_float:,.2f}"


def _format_number(value: float) -> str:
    """Render a numeric value without trailing ``.0`` noise (e.g. ``24`` not ``24.0``)."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return str(value)
    return str(value)
