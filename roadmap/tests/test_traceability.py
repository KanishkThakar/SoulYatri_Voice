"""Coverage tests for the requirement → task → test traceability matrix.

These are plain ``pytest`` example-based tests (no Hypothesis) for the
:mod:`roadmap.reports.traceability` generator built in Task 38.1. They lock in
the documented contract that Task 38.2 cares about: **every** acceptance
criterion parsed from the spec's ``requirements.md`` maps to at least one task
in ``tasks.md``, so the authoritative ``"uncovered_by_tasks"`` list is empty.

Coverage definition (per :mod:`roadmap.reports.traceability`)
-------------------------------------------------------------
The *authoritative* coverage notion is **task coverage** — a criterion is
covered iff at least one task references it in a ``_Requirements:`` annotation.
``build_traceability()["uncovered_by_tasks"]`` is therefore expected to be
empty. *Test* coverage (``"uncovered_by_tests"``) is informational only: some
narrative/scope criteria are covered by the authored ``ROADMAP.md`` plus the
structural tests collectively rather than by a 1:1 annotated test, so it is not
asserted to be empty here.

If ``"uncovered_by_tasks"`` is ever non-empty, that is a real traceability gap
(a criterion in ``requirements.md`` with no covering task annotation in
``tasks.md``) and these tests will fail loudly with the offending ids rather
than papering over it.

All assertions use the generator's default paths, which it resolves relative to
``WORKSPACE_ROOT`` via :mod:`roadmap.paths`, so the tests are independent of the
working directory pytest is invoked from.

Requirements: 1.6, 12.7.
"""

from __future__ import annotations

import re

from roadmap.reports.traceability import (
    build_traceability,
    render_traceability_report,
    uncovered_criteria,
)

#: The documented keys every ``build_traceability`` result must expose.
_EXPECTED_KEYS = {
    "criteria",
    "requirements",
    "tasks",
    "tests",
    "properties",
    "uncovered_by_tasks",
    "uncovered_by_tests",
    "validated_criteria",
}

#: A criterion id looks like ``"<int>.<int>"`` (e.g. ``"1.1"``, ``"11.8"``).
_CRITERION_ID_RE = re.compile(r"^\d+\.\d+$")

#: The canonical set of numbered design properties (Properties 1..15).
_EXPECTED_PROPERTY_NUMBERS = {str(n) for n in range(1, 16)}


def test_build_traceability_returns_documented_keys() -> None:
    """``build_traceability`` returns a dict exposing every documented key."""
    traceability = build_traceability()

    assert isinstance(traceability, dict)
    assert set(traceability) == _EXPECTED_KEYS


def test_criteria_are_non_empty_and_well_formed() -> None:
    """``"criteria"`` is non-empty and every id has the ``<int>.<int>`` shape."""
    traceability = build_traceability()
    criteria = traceability["criteria"]

    assert isinstance(criteria, list)
    assert criteria, "requirements.md must yield at least one acceptance criterion"
    assert all(isinstance(cid, str) for cid in criteria)
    bad = [cid for cid in criteria if not _CRITERION_ID_RE.match(cid)]
    assert bad == [], f"malformed criterion ids: {bad}"


def test_every_criterion_maps_to_at_least_one_task() -> None:
    """FULL CRITERION COVERAGE: no acceptance criterion is task-uncovered.

    This is the core Task 38.2 assertion: the authoritative
    ``"uncovered_by_tasks"`` list is empty, i.e. every criterion in
    ``requirements.md`` is referenced by at least one task in ``tasks.md``.
    """
    traceability = build_traceability()

    uncovered = traceability["uncovered_by_tasks"]
    assert uncovered == [], (
        "These acceptance criteria have no covering task in tasks.md "
        f"(add a _Requirements: annotation referencing them): {uncovered}"
    )

    # Equivalent statement via the public helper (default + prebuilt forms).
    assert uncovered_criteria(traceability, against="tasks") == []
    assert uncovered_criteria(against="tasks") == []


def test_every_criterion_is_a_tasks_key_with_a_non_empty_task_list() -> None:
    """Each criterion appears in ``"tasks"`` mapped to a non-empty task list."""
    traceability = build_traceability()
    criteria = traceability["criteria"]
    tasks_map = traceability["tasks"]

    missing_keys = [cid for cid in criteria if cid not in tasks_map]
    assert missing_keys == [], f"criteria absent from tasks map: {missing_keys}"

    empty = [cid for cid in criteria if not tasks_map[cid]]
    assert empty == [], f"criteria with an empty covering-task list: {empty}"


def test_properties_cover_all_15_design_properties() -> None:
    """The ``"properties"`` mapping includes every numbered property 1..15.

    The roadmap test suite annotates each design property with a
    ``# Feature: …, Property {n}: …`` tag, so the scanned property numbers must
    be a superset of the canonical ``{1..15}`` set (consistent with Task 39 /
    :mod:`roadmap.reports.property_coverage`).
    """
    traceability = build_traceability()
    properties = traceability["properties"]

    found = set(properties)
    missing = sorted(_EXPECTED_PROPERTY_NUMBERS - found, key=int)
    assert missing == [], f"design properties with no tagged test: {missing}"

    # Every reported property maps to at least one test location.
    assert all(properties[prop] for prop in _EXPECTED_PROPERTY_NUMBERS)


def test_render_traceability_report_is_non_empty_markdown() -> None:
    """``render_traceability_report`` returns a non-empty Markdown string."""
    report = render_traceability_report()

    assert isinstance(report, str)
    assert report.strip() != ""
    # The Markdown header is always present.
    assert report.startswith("# Requirement → Task → Test Traceability Matrix")
    # Full task coverage is surfaced as the explicit "every criterion" note.
    assert "Every criterion is mapped to at least one task." in report
