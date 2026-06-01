"""Unit tests for the budget & compute Markdown report renderer (task 37.2).

These plain-pytest example tests cover
:func:`roadmap.reports.budget_report.render_budget_report`, asserting on the
rendered Markdown string. They confirm the sections the report renders:

- **Budget Ranges** (Requirement 9.2): the LEAN and AMBITIOUS
  ``{lower, upper, currency}`` ranges in the single stated currency (USD), under
  a "Budget Ranges" heading.
- **Per-Phase Compute Footprints** (Requirement 9.1): a row per phase
  (``P1-baseline``..``P7-diff-gate``) carrying its minimum GPU class and minimum
  VRAM (GB).
- **LEAN Feasibility Claim** (Requirement 9.3): the ``<= 5`` people claim and the
  no-large-scale (multi-GPU / multi-node) training exclusion.
- **AMBITIOUS Entry Requirement** (Requirement 9.4): the note that AMBITIOUS
  entry at ``G1`` requires an explicit justification (budget range + per-phase
  footprint).
- **Scope Decisions for Available Compute** (Requirement 9.5): present only when
  ``available_compute`` is supplied, with reduced/full scope rows whose
  footprints never exceed the confirmed-available compute; omitted otherwise.

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5
"""

from __future__ import annotations

import re

from roadmap.reports.budget_report import render_budget_report
from roadmap.tests.fixtures import make_budget_planner, make_valid_roadmap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Collapse runs of whitespace to single spaces for spacing-robust matching."""
    return re.sub(r"\s+", " ", text)


def _contains(haystack: str, needle: str) -> bool:
    """Case-insensitive, spacing-robust substring check."""
    return _normalize(needle).lower() in _normalize(haystack).lower()


def _section(report: str, heading: str) -> str:
    """Return the text of the ``##`` section beginning with ``heading``.

    The slice runs from the matching ``## heading`` line up to (but excluding)
    the next ``## `` heading, or to the end of the report. Returns an empty
    string when no such heading exists.
    """
    lines = report.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and _contains(line, heading):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _table_row(section_text: str, first_cell: str) -> list[str] | None:
    """Return the stripped cells of the Markdown table row whose first data cell
    equals ``first_cell``, or ``None`` if no such row exists."""
    for line in section_text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        # A pipe-delimited row is ['', c1, c2, ..., ''].
        if len(cells) >= 3 and cells[1] == first_cell:
            return cells
    return None


_CANONICAL_PHASE_IDS = (
    "P1-baseline",
    "P2-core-select",
    "P3-integrate",
    "P4-moat-duplex",
    "P5-safety-gate",
    "P6-custom",
    "P7-diff-gate",
)


# ---------------------------------------------------------------------------
# Budget Ranges (Requirement 9.2)
# ---------------------------------------------------------------------------
def test_report_renders_budget_ranges_heading_and_values() -> None:
    """The report shows a Budget Ranges heading with LEAN/AMBITIOUS USD ranges."""
    report = render_budget_report(make_budget_planner())

    assert _contains(report, "Budget Ranges")
    # LEAN range 5,000 .. 50,000 and AMBITIOUS range 50,000 .. 500,000.
    assert _contains(report, "5,000")
    assert _contains(report, "50,000")
    assert _contains(report, "500,000")
    # Single stated currency.
    assert _contains(report, "USD")
    # Both track labels appear.
    assert _contains(report, "LEAN")
    assert _contains(report, "AMBITIOUS")


def test_budget_ranges_use_roadmap_track_labels_when_supplied() -> None:
    """Passing the roadmap still renders both budget rows in the ranges table."""
    roadmap = make_valid_roadmap()
    report = render_budget_report(make_budget_planner(), roadmap)

    ranges = _section(report, "Budget Ranges")
    assert _contains(ranges, "LEAN")
    assert _contains(ranges, "AMBITIOUS")
    assert _contains(ranges, "USD")


# ---------------------------------------------------------------------------
# Per-Phase Compute Footprints (Requirement 9.1)
# ---------------------------------------------------------------------------
def test_report_lists_every_phase_with_gpu_class_and_vram() -> None:
    """Each phase appears with its minimum GPU class and VRAM (GB)."""
    planner = make_budget_planner()
    report = render_budget_report(planner)

    section = _section(report, "Per-Phase Compute Footprints")
    assert section, "expected a per-phase footprint section"

    footprints = planner.phase_footprints()
    for phase_id in _CANONICAL_PHASE_IDS:
        row = _table_row(section, phase_id)
        assert row is not None, f"missing footprint row for {phase_id}"
        footprint = footprints[phase_id]
        # The row carries the phase's stated GPU class and VRAM value.
        assert _contains(" ".join(row), footprint.gpu_class)
        assert str(int(footprint.vram_gb)) in " ".join(row)


def test_p1_baseline_footprint_is_rendered() -> None:
    """P1-baseline's footprint (GPU class + VRAM) is present in the report."""
    planner = make_budget_planner()
    report = render_budget_report(planner)

    p1 = planner.phase_footprints()["P1-baseline"]
    section = _section(report, "Per-Phase Compute Footprints")
    row = _table_row(section, "P1-baseline")

    assert row is not None
    assert _contains(" ".join(row), p1.gpu_class)
    assert str(int(p1.vram_gb)) in " ".join(row)


# ---------------------------------------------------------------------------
# LEAN Feasibility Claim (Requirement 9.3)
# ---------------------------------------------------------------------------
def test_report_renders_lean_feasibility_claim() -> None:
    """The LEAN claim states <=5 people and excludes large-scale GPU training."""
    report = render_budget_report(make_budget_planner())

    claim = _section(report, "LEAN Feasibility Claim")
    assert claim, "expected a LEAN feasibility section"
    assert "5" in claim  # at most five people
    assert _contains(claim, "people")
    assert _contains(claim, "large-scale")
    # Multi-GPU / multi-node from-scratch training is the excluded definition.
    assert _contains(claim, "multi-GPU")
    assert _contains(claim, "multi-node")


# ---------------------------------------------------------------------------
# AMBITIOUS Entry Requirement (Requirement 9.4)
# ---------------------------------------------------------------------------
def test_report_renders_ambitious_justification_requirement() -> None:
    """The AMBITIOUS note requires a justification (budget range + footprint) at G1."""
    report = render_budget_report(make_budget_planner())

    note = _section(report, "AMBITIOUS Entry Requirement")
    assert note, "expected an AMBITIOUS entry-requirement section"
    assert _contains(note, "G1")
    assert _contains(note, "justification")
    # The justification must reference the AMBITIOUS budget range...
    assert _contains(note, "budget range")
    assert _contains(note, "50,000")
    assert _contains(note, "500,000")
    assert _contains(note, "USD")
    # ...and the per-phase compute footprint.
    assert _contains(note, "per-phase compute footprint")


# ---------------------------------------------------------------------------
# Scope Decisions for Available Compute (Requirement 9.5)
# ---------------------------------------------------------------------------
def test_scope_section_omitted_when_no_available_compute() -> None:
    """With available_compute=None the Scope Decisions section is omitted."""
    report = render_budget_report(make_budget_planner())

    assert not _contains(report, "Scope Decisions")
    assert _section(report, "Scope Decisions") == ""


def test_scope_section_shows_reduced_and_full_decisions() -> None:
    """Supplying available compute adds a Scope Decisions section with rows whose
    footprints do not exceed the confirmed-available compute (Requirement 9.5)."""
    planner = make_budget_planner()
    available = {"P1-baseline": 8.0, "P6-custom": 80.0}

    report = render_budget_report(planner, available_compute=available)

    section = _section(report, "Scope Decisions")
    assert section, "expected a Scope Decisions section"

    # P1-baseline: 8 GB is below the 24 GB phase minimum -> reduced scope.
    p1_plan = planner.select_scope("P1-baseline", 8.0)
    assert p1_plan.scope == "reduced"
    p1_row = _table_row(section, "P1-baseline")
    assert p1_row is not None
    assert _contains(" ".join(p1_row), "reduced")

    # P6-custom: 80 GB meets/exceeds the phase minimum -> full scope.
    p6_plan = planner.select_scope("P6-custom", 80.0)
    assert p6_plan.scope == "full"
    p6_row = _table_row(section, "P6-custom")
    assert p6_row is not None
    assert _contains(" ".join(p6_row), "full")

    # Both scope kinds are visible in the section.
    assert _contains(section, "reduced")
    assert _contains(section, "full")


def test_scope_footprints_never_exceed_available_compute() -> None:
    """Every rendered scope row's footprint VRAM is <= its confirmed-available VRAM."""
    planner = make_budget_planner()
    available = {"P1-baseline": 8.0, "P6-custom": 80.0}

    report = render_budget_report(planner, available_compute=available)
    section = _section(report, "Scope Decisions")

    for phase_id, avail in available.items():
        row = _table_row(section, phase_id)
        assert row is not None, f"missing scope row for {phase_id}"
        # Row cells: ['', phase, scope, gpu_class, footprint_vram, confirmed, '']
        footprint_vram = float(row[4])
        confirmed_vram = float(row[5])
        assert footprint_vram <= confirmed_vram
        assert confirmed_vram <= avail
