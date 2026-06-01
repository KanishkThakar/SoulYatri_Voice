"""Tests for the narrative-vs-structured consistency checker (Task 30.2).

These are plain ``pytest`` example-based tests for
:mod:`roadmap.consistency`. They lock in the two halves of the checker's
contract:

1. **A matching pair reports no divergence.** The authored narrative
   ``ROADMAP.md`` and the structured :class:`~roadmap.roadmap_model.Roadmap`
   describe one plan, so :func:`~roadmap.consistency.check_consistency` against
   the real artifacts must return an empty list (Requirements 1.2, 1.7).

2. **An injected mismatch is reported.** Starting from the *real* narrative
   text, a targeted, verified mutation (flip a track label, drop a
   conflict-register row, or break the selection-weight table) makes the two
   representations disagree, and the checker must report the corresponding
   :class:`~roadmap.consistency.Finding` category.

The mutation tests are deliberately defensive: each one first asserts that the
string replacement actually changed the narrative text, so a stale anchor can
never silently turn the test into a vacuous pass. The narrative text is fed to
the checker through the keyword-only ``roadmap_md=`` argument, so the real
``ROADMAP.md`` on disk is never touched.

The reporting tests assert that :func:`render_consistency_report` confirms
consistency for an empty finding list and surfaces the divergence details for a
non-empty one.

**Validates: Requirements 1.2, 1.7**
"""

from __future__ import annotations

import pytest

from roadmap.consistency import (
    Finding,
    check_consistency,
    render_consistency_report,
)
from roadmap.paths import ROADMAP_MD_PATH

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_roadmap_md() -> str:
    """The authored narrative ``ROADMAP.md`` text, read once per module."""
    return ROADMAP_MD_PATH.read_text(encoding="utf-8")


def _categories(findings: list[Finding]) -> set[str]:
    """The set of finding categories present in ``findings``."""
    return {finding.category for finding in findings}


def _replace_once_verified(text: str, old: str, new: str) -> str:
    """Replace every occurrence of ``old`` with ``new`` and verify it changed.

    Asserting that ``old`` is present (and that the result differs) guarantees
    the mutation tests are never vacuous: a stale anchor fails loudly here
    rather than producing a roadmap that still matches the structured model.
    """
    assert old in text, f"mutation anchor not found in ROADMAP.md: {old!r}"
    mutated = text.replace(old, new)
    assert mutated != text, "mutation did not change the narrative text"
    return mutated


def _drop_line_verified(text: str, line_prefix: str) -> str:
    """Drop the single narrative line starting with ``line_prefix``.

    Verifies exactly one line is removed so the "dropped conflict row" test
    cannot silently become a no-op.
    """
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if not line.lstrip().startswith(line_prefix)]
    removed = len(lines) - len(kept)
    assert removed == 1, (
        f"expected to drop exactly one line starting with {line_prefix!r}, "
        f"dropped {removed}"
    )
    return "".join(kept)


# ===========================================================================
# 1. Matching pair -> no findings (the key acceptance test)
# ===========================================================================


def test_matching_pair_reports_no_divergence() -> None:
    """The real ROADMAP.md and the structured Roadmap agree on every check.

    This is the core acceptance assertion: with both default artifacts,
    :func:`check_consistency` returns an empty list (no divergences).

    **Validates: Requirements 1.2, 1.7**
    """
    findings = check_consistency()
    assert findings == [], (
        "authored ROADMAP.md and structured Roadmap diverge: "
        f"{[(f.category, f.detail) for f in findings]}"
    )


def test_matching_pair_via_explicit_text_argument(real_roadmap_md: str) -> None:
    """Passing the real narrative text via ``roadmap_md=`` also yields no findings.

    Establishes the baseline used by the mutation tests: the unmodified text fed
    through the keyword-only ``roadmap_md=`` argument is itself consistent, so
    any finding a mutation produces is attributable to that mutation alone.

    **Validates: Requirements 1.2, 1.7**
    """
    assert check_consistency(roadmap_md=real_roadmap_md) == []


# ===========================================================================
# 2. Injected mismatches are reported
# ===========================================================================


def test_injected_track_label_mismatch_is_reported(real_roadmap_md: str) -> None:
    """Flipping the AMBITIOUS track label to "primary" is reported.

    Both AMBITIOUS phase rows are relabeled ``optional`` -> ``primary`` so the
    narrative no longer carries the expected ``optional`` label for the
    AMBITIOUS track, which the checker must flag as a ``track_label`` divergence.

    **Validates: Requirements 1.2**
    """
    mutated = _replace_once_verified(
        real_roadmap_md,
        "| AMBITIOUS | optional |",
        "| AMBITIOUS | primary |",
    )

    findings = check_consistency(roadmap_md=mutated)

    assert "track_label" in _categories(findings), (
        "expected a 'track_label' finding after flipping the AMBITIOUS label; "
        f"got {[(f.category, f.detail) for f in findings]}"
    )


def test_injected_dropped_conflict_row_is_reported(real_roadmap_md: str) -> None:
    """Dropping a conflict-register row is reported as ``conflict_missing``.

    The "Custom neural codec is a prerequisite" row is present in the structured
    model but removed from the narrative, so the checker must report that the
    row is missing from the narrative.

    **Validates: Requirements 1.7**
    """
    mutated = _drop_line_verified(
        real_roadmap_md,
        "| Custom neural codec is a prerequisite",
    )

    findings = check_consistency(roadmap_md=mutated)

    assert "conflict_missing" in _categories(findings), (
        "expected a 'conflict_missing' finding after dropping a conflict row; "
        f"got {[(f.category, f.detail) for f in findings]}"
    )


def test_injected_selection_weight_change_is_reported(real_roadmap_md: str) -> None:
    """Breaking the selection-weight table is reported as ``selection_weight_*``.

    Changing the ``streaming_latency`` weight from 25 to 20 both mismatches the
    structured weight and breaks the sum-to-100 invariant, so the checker must
    report a selection-weight divergence.

    **Validates: Requirements 1.2**
    """
    mutated = _replace_once_verified(
        real_roadmap_md,
        "| `streaming_latency` | 25 |",
        "| `streaming_latency` | 20 |",
    )

    categories = _categories(check_consistency(roadmap_md=mutated))

    assert "selection_weight_mismatch" in categories, (
        "expected a 'selection_weight_mismatch' finding after changing a "
        f"weight; got categories {sorted(categories)}"
    )
    # The altered table also no longer sums to 100.
    assert "selection_weight_sum" in categories


# ===========================================================================
# 3. render_consistency_report
# ===========================================================================


def test_render_report_empty_confirms_consistency() -> None:
    """An empty finding list renders a "consistent / no divergences" confirmation.

    **Validates: Requirements 1.2, 1.7**
    """
    report = render_consistency_report([])

    assert isinstance(report, str)
    lowered = report.lower()
    assert "consistent" in lowered
    assert "no divergence" in lowered


def test_render_report_nonempty_includes_divergence_details(
    real_roadmap_md: str,
) -> None:
    """A non-empty finding list renders the divergence details.

    Uses real findings produced by a dropped conflict row and asserts the report
    surfaces the divergence count, the finding category, and the offending topic.

    **Validates: Requirements 1.7**
    """
    mutated = _drop_line_verified(
        real_roadmap_md,
        "| Custom neural codec is a prerequisite",
    )
    findings = check_consistency(roadmap_md=mutated)
    assert findings, "precondition: the mutation must produce at least one finding"

    report = render_consistency_report(findings)

    assert isinstance(report, str)
    assert "divergence" in report.lower()
    # The category and the offending conflict topic appear in the report body.
    assert "conflict_missing" in report
    assert "Custom neural codec is a prerequisite" in report
