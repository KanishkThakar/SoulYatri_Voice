"""Requirement → task → test traceability generator for the roadmap spec.

This module builds a *traceability matrix* that connects every acceptance
criterion in the spec's ``requirements.md`` to

1. the implementation **task(s)** in ``tasks.md`` whose ``_Requirements:`` (or
   ``Validates: Requirements``) annotation references that criterion, and
2. the **test(s)** under ``roadmap/tests/`` whose ``Validates: Requirements`` /
   ``Requirements:`` annotations (and ``# Feature: …, Property {n}: …`` tags)
   reference that criterion.

It is the data/reporting backbone for Task 38.1 and the deterministic source
the Task 38.2 coverage test asserts against.

Scope / purity
--------------
Unlike the pure *string* renderers elsewhere in :mod:`roadmap.reports`, this
module **reads files** — the spec's ``requirements.md`` / ``tasks.md`` and the
``roadmap/tests/*.py`` sources. Those are plain local file reads only: no
network access, no GPU, and no model-training run is ever invoked, so the
import-only / no-training guarantee enforced across the roadmap tooling
(Requirement 4.6) is preserved. Everything else here is pure text parsing.

Coverage definition (read this — Task 38.2 asserts against it)
--------------------------------------------------------------
A few distinct notions of "covered" are reported, each computed
deterministically so a test can assert against an exact set:

* **Task coverage** — a criterion is *task-covered* iff at least one task in
  ``tasks.md`` references it in a requirement annotation. ``build_traceability``
  returns the per-criterion covering-task lists in ``["tasks"]`` and the list of
  criteria with **no** covering task in ``["uncovered_by_tasks"]``. This is the
  authoritative coverage notion for Task 38.2: *"every requirements criterion
  maps to at least one task; the uncovered-criteria list is empty."* It is the
  realistic notion because the narrative/structural criteria are covered by the
  authoring task (23) and the structural tests (24) even though they are not
  expressed as numbered design properties.

* **Test coverage** — a criterion is *test-covered* iff at least one test file
  carries an annotation referencing it. Reported per-criterion in ``["tests"]``
  and as ``["uncovered_by_tests"]``. This is reported for transparency; it is
  **not** expected to be empty, because some narrative criteria are validated by
  the authored ``ROADMAP.md`` content + structural tests collectively rather
  than by a 1:1 annotated test, and a handful of criteria are documentation /
  scope statements only.

* **Validated set** — ``["validated_criteria"]`` is the union of every criterion
  id that appears in a ``Validates: Requirements …`` / ``Requirements: …``
  annotation across the whole test suite. This is the documented set the test
  suite explicitly *claims* to validate; ``["tests"]`` keys are exactly this
  set.

Return shape of :func:`build_traceability`
------------------------------------------
A plain ``dict`` with these keys (all criterion ids are strings like
``"1.1"``, ``"11.8"``; all lists are sorted unless noted):

``"criteria"``
    ``list[str]`` — every acceptance-criterion id parsed from
    ``requirements.md``, in numeric (requirement, criterion) order.
``"requirements"``
    ``dict[str, list[str]]`` — requirement number (e.g. ``"1"``) → the ordered
    criterion ids belonging to it.
``"tasks"``
    ``dict[str, list[str]]`` — criterion id → sorted list of task ids (e.g.
    ``"23.1"``) whose requirement annotation references it. Criteria with no
    covering task map to an empty list.
``"tests"``
    ``dict[str, list[str]]`` — criterion id → sorted list of test locations
    (``"<file>"`` or ``"<file>::<test_function>"``) that reference it. Only
    criteria with at least one referencing test appear as keys.
``"properties"``
    ``dict[str, list[str]]`` — design-property number (e.g. ``"2"``) → sorted
    test locations carrying that ``# Feature: …, Property {n}: …`` tag.
``"uncovered_by_tasks"``
    ``list[str]`` — criteria with no covering task. **Task 38.2 asserts this is
    empty.**
``"uncovered_by_tests"``
    ``list[str]`` — criteria with no referencing test (informational).
``"validated_criteria"``
    ``list[str]`` — union of every criterion referenced by any test annotation.

Public API
----------
- :func:`build_traceability` — build the matrix dict described above.
- :func:`uncovered_criteria` — the uncovered-criteria list, against ``"tasks"``
  (default) or ``"tests"``.
- :func:`render_traceability_report` — render the matrix as Markdown.

Requirements: 1.6, 12.7.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from ..paths import PACKAGE_ROOT, WORKSPACE_ROOT

__all__ = [
    "SPEC_DIR",
    "DEFAULT_REQUIREMENTS_PATH",
    "DEFAULT_TASKS_PATH",
    "DEFAULT_TESTS_DIR",
    "build_traceability",
    "uncovered_criteria",
    "render_traceability_report",
]

# --- Default path resolution ------------------------------------------------
#
# Resolve the spec directory relative to the workspace root so the generator
# works regardless of the working directory pytest / the CLI is invoked from.

#: The spec directory for this feature, ``.kiro/specs/speech-native-voice-roadmap``.
SPEC_DIR: Path = WORKSPACE_ROOT / ".kiro" / "specs" / "speech-native-voice-roadmap"

#: Default location of the spec's requirements document.
DEFAULT_REQUIREMENTS_PATH: Path = SPEC_DIR / "requirements.md"

#: Default location of the spec's tasks document.
DEFAULT_TASKS_PATH: Path = SPEC_DIR / "tasks.md"

#: Default location of the roadmap test suite scanned for annotations.
DEFAULT_TESTS_DIR: Path = PACKAGE_ROOT / "tests"


# --- Parsing helpers --------------------------------------------------------

#: Matches a criterion id such as ``1.1`` or ``11.8`` (one or more digits, a
#: dot, one or more digits). Lookarounds (rather than ``\b``) ensure the id is
#: not part of a longer dotted/number sequence *and* still match when the id is
#: immediately followed by a markdown italic underscore (e.g. ``_Requirements:
#: 8.6_``) — ``_`` is a word char, so a trailing ``\b`` would fail there.
_CRITERION_RE = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])")

#: Matches a requirement section heading: ``### Requirement 1: …``.
_REQUIREMENT_HEADING_RE = re.compile(r"^#{2,4}\s+Requirement\s+(\d+)\b", re.IGNORECASE)

#: Matches the acceptance-criteria sub-heading that opens a criteria list.
_ACCEPTANCE_HEADING_RE = re.compile(r"^#{2,4}\s+Acceptance\s+Criteria\b", re.IGNORECASE)

#: Matches any markdown ATX heading line (``#`` … ``######``).
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")

#: Matches a numbered list item: ``1. …`` (the leading number is the criterion
#: ordinal within its requirement).
_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+\S")

#: Matches a task / sub-task checkbox line and captures the task id, e.g.
#: ``- [x] 23.1 Author …`` -> ``23.1`` or ``- [ ] 38. Generate …`` -> ``38``.
_TASK_HEADING_RE = re.compile(r"^\s*[-*]\s*\[[ xX~/\-]\]\s*(\d+(?:\.\d+)?)\b")

#: A line that carries a requirement reference: ``_Requirements: …`` or
#: ``**Validates: Requirements …**`` (the word "Requirements" followed shortly
#: by at least one criterion id). Case-insensitive.
_REQ_REF_LINE_RE = re.compile(r"Requirements?\b", re.IGNORECASE)

#: Matches a numbered design-property tag comment, e.g.
#: ``# Feature: speech-native-voice-roadmap, Property 2: …`` -> ``2``.
_PROPERTY_TAG_RE = re.compile(
    r"#\s*Feature:\s*speech-native-voice-roadmap,\s*Property\s+(\d+)\b",
    re.IGNORECASE,
)

#: Matches a test-function definition line, capturing the function name.
_TEST_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(")


def _criterion_ids_in(text: str) -> list[str]:
    """Return all criterion ids (``"r.c"``) found in ``text``, in order."""
    return [f"{m.group(1)}.{m.group(2)}" for m in _CRITERION_RE.finditer(text)]


def _sort_key(criterion_id: str) -> tuple[int, int]:
    """Numeric sort key for a criterion id so ``2.10`` sorts after ``2.9``."""
    req, _, crit = criterion_id.partition(".")
    return (int(req), int(crit))


def _task_sort_key(task_id: str) -> tuple[int, int]:
    """Numeric sort key for a task id, ordering ``38`` before ``38.1``.

    A top-level task such as ``"38"`` (no sub-number) sorts before its
    sub-tasks by treating the missing sub-number as ``-1``.
    """
    major, _, minor = task_id.partition(".")
    return (int(major), int(minor) if minor else -1)


def _sorted_criteria(ids: Iterable[str]) -> list[str]:
    """Return the unique criterion ids sorted in (requirement, criterion) order."""
    return sorted(set(ids), key=_sort_key)


# --- requirements.md --------------------------------------------------------


def _parse_requirements(requirements_path: Path) -> dict[str, list[str]]:
    """Parse ``requirements.md`` into ``{requirement_number: [criterion_ids]}``.

    Only numbered list items that appear under an ``#### Acceptance Criteria``
    heading (and before the next heading) are treated as acceptance criteria, so
    incidental numbered lists elsewhere in the document are ignored. The
    criterion id is built from the active requirement number and the list
    item's own number (``f"{req}.{n}"``).
    """
    text = requirements_path.read_text(encoding="utf-8")
    requirements: dict[str, list[str]] = {}

    current_req: Optional[str] = None
    in_criteria = False

    for line in text.splitlines():
        req_match = _REQUIREMENT_HEADING_RE.match(line)
        if req_match:
            current_req = req_match.group(1)
            requirements.setdefault(current_req, [])
            in_criteria = False
            continue

        if _ACCEPTANCE_HEADING_RE.match(line):
            in_criteria = True
            continue

        # Any other heading closes the current acceptance-criteria block.
        if _ANY_HEADING_RE.match(line):
            in_criteria = False
            continue

        if in_criteria and current_req is not None:
            item_match = _NUMBERED_ITEM_RE.match(line)
            if item_match:
                criterion_id = f"{current_req}.{item_match.group(1)}"
                bucket = requirements.setdefault(current_req, [])
                if criterion_id not in bucket:
                    bucket.append(criterion_id)

    # Drop requirements that yielded no criteria (e.g. headings without a list).
    return {req: crits for req, crits in requirements.items() if crits}


# --- tasks.md ---------------------------------------------------------------


def _parse_tasks(tasks_path: Path) -> dict[str, list[str]]:
    """Parse ``tasks.md`` into ``{criterion_id: [task_ids]}``.

    Walks the document tracking the most recently seen task / sub-task id. Every
    line carrying a requirement reference (a ``_Requirements:`` annotation or a
    ``Validates: Requirements`` line) contributes its criterion ids to the
    current task. Numbered design-property ``**Validates: Requirements …**``
    lines are included too, so a task that documents its coverage only via a
    property tag still counts.
    """
    text = tasks_path.read_text(encoding="utf-8")
    criterion_to_tasks: dict[str, set[str]] = {}

    current_task: Optional[str] = None
    for line in text.splitlines():
        task_match = _TASK_HEADING_RE.match(line)
        if task_match:
            current_task = task_match.group(1)
            # A task heading line may itself not carry requirement refs; fall
            # through so a heading that *does* (unusual) is still captured.

        if current_task is None:
            continue

        if _REQ_REF_LINE_RE.search(line):
            for criterion_id in _criterion_ids_in(line):
                criterion_to_tasks.setdefault(criterion_id, set()).add(current_task)

    return {cid: sorted(tasks, key=_task_sort_key) for cid, tasks in criterion_to_tasks.items()}


# --- roadmap/tests/*.py -----------------------------------------------------


def _function_at(def_lines: list[tuple[int, str]], lineno: int) -> Optional[str]:
    """Return the test function active at ``lineno`` (the nearest preceding def).

    ``def_lines`` is the ascending list of ``(lineno, function_name)`` for the
    file. A reference on a line before the first ``def`` (e.g. in the module
    docstring) returns ``None`` and is treated as a file-level reference.
    """
    active: Optional[str] = None
    for def_lineno, name in def_lines:
        if def_lineno <= lineno:
            active = name
        else:
            break
    return active


def _scan_test_file(
    path: Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Scan one test file for requirement refs and property tags.

    Returns ``(criterion_to_locations, property_to_locations)`` where a location
    is ``"<file>"`` for a module-level (pre-first-def) reference or
    ``"<file>::<test_function>"`` for one inside a test function's body /
    docstring / preceding tag comment.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    name = path.name

    def_lines: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        def_match = _TEST_DEF_RE.match(line)
        if def_match:
            def_lines.append((idx, def_match.group(1)))

    def location_for(idx: int) -> str:
        func = _function_at(def_lines, idx)
        # A property tag comment sits directly *above* its decorated function,
        # so attribute a tag/ref that has no preceding def to the *next* def
        # when one exists (keeps the property mapped to its test function).
        if func is None and def_lines:
            following = next((fn for ln, fn in def_lines if ln > idx), None)
            if following is not None:
                return f"{name}::{following}"
        return f"{name}::{func}" if func is not None else name

    criterion_to_locations: dict[str, set[str]] = {}
    property_to_locations: dict[str, set[str]] = {}

    for idx, line in enumerate(lines):
        prop_match = _PROPERTY_TAG_RE.search(line)
        if prop_match:
            property_to_locations.setdefault(prop_match.group(1), set()).add(
                location_for(idx)
            )

        if _REQ_REF_LINE_RE.search(line):
            ids = _criterion_ids_in(line)
            if not ids:
                continue
            loc = location_for(idx)
            for criterion_id in ids:
                criterion_to_locations.setdefault(criterion_id, set()).add(loc)

    return criterion_to_locations, property_to_locations


def _parse_tests(tests_dir: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Scan every ``test_*.py`` under ``tests_dir`` for refs and property tags.

    Returns ``(criterion_to_tests, property_to_tests)`` with sorted location
    lists. Missing directories yield empty mappings rather than raising.
    """
    criterion_to_tests: dict[str, set[str]] = {}
    property_to_tests: dict[str, set[str]] = {}

    if not tests_dir.is_dir():
        return {}, {}

    for path in sorted(tests_dir.glob("test_*.py")):
        file_criteria, file_properties = _scan_test_file(path)
        for criterion_id, locations in file_criteria.items():
            criterion_to_tests.setdefault(criterion_id, set()).update(locations)
        for prop, locations in file_properties.items():
            property_to_tests.setdefault(prop, set()).update(locations)

    return (
        {cid: sorted(locs) for cid, locs in criterion_to_tests.items()},
        {prop: sorted(locs) for prop, locs in property_to_tests.items()},
    )


# --- Public API -------------------------------------------------------------


def build_traceability(
    *,
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    tests_dir: Path = DEFAULT_TESTS_DIR,
) -> dict:
    """Build the requirement → task → test traceability matrix.

    Parses the spec's ``requirements.md`` to enumerate every acceptance
    criterion, ``tasks.md`` to find the covering task(s) per criterion, and the
    ``roadmap/tests/`` sources to find the validating test(s) and the design
    properties. See the module docstring for the full, documented return shape
    and the precise coverage definitions.

    Args:
        requirements_path: Path to the spec ``requirements.md``.
        tasks_path: Path to the spec ``tasks.md``.
        tests_dir: Directory of ``test_*.py`` files to scan for annotations.

    Returns:
        A ``dict`` with the keys ``"criteria"``, ``"requirements"``, ``"tasks"``,
        ``"tests"``, ``"properties"``, ``"uncovered_by_tasks"``,
        ``"uncovered_by_tests"``, and ``"validated_criteria"`` as documented in
        the module docstring.
    """
    requirements = _parse_requirements(Path(requirements_path))
    tasks_index = _parse_tasks(Path(tasks_path))
    tests_index, properties_index = _parse_tests(Path(tests_dir))

    # Ordered list of every criterion id, in (requirement, criterion) order.
    criteria = _sorted_criteria(
        cid for crits in requirements.values() for cid in crits
    )

    tasks_per_criterion = {cid: tasks_index.get(cid, []) for cid in criteria}
    tests_per_criterion = {
        cid: tests_index[cid] for cid in criteria if cid in tests_index
    }

    uncovered_by_tasks = [cid for cid in criteria if not tasks_per_criterion[cid]]
    uncovered_by_tests = [cid for cid in criteria if cid not in tests_index]

    # The set the test suite explicitly claims to validate (union of refs), then
    # intersected with the enumerated criteria so stray ids never leak in.
    validated_criteria = [cid for cid in criteria if cid in tests_index]

    requirements_sorted = {
        req: list(requirements[req])
        for req in sorted(requirements, key=lambda r: int(r))
    }
    properties_sorted = {
        prop: properties_index[prop]
        for prop in sorted(properties_index, key=lambda p: int(p))
    }

    return {
        "criteria": criteria,
        "requirements": requirements_sorted,
        "tasks": tasks_per_criterion,
        "tests": tests_per_criterion,
        "properties": properties_sorted,
        "uncovered_by_tasks": uncovered_by_tasks,
        "uncovered_by_tests": uncovered_by_tests,
        "validated_criteria": validated_criteria,
    }


def uncovered_criteria(
    traceability: Optional[dict] = None,
    *,
    against: str = "tasks",
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    tests_dir: Path = DEFAULT_TESTS_DIR,
) -> list[str]:
    """Return the criteria with no covering artifact.

    Args:
        traceability: A prebuilt :func:`build_traceability` result. When
            ``None``, the matrix is built from the provided paths.
        against: ``"tasks"`` (default) to return criteria with no covering task
            — the authoritative notion Task 38.2 asserts is empty — or
            ``"tests"`` to return criteria with no validating test.
        requirements_path: Forwarded to :func:`build_traceability` when building.
        tasks_path: Forwarded to :func:`build_traceability` when building.
        tests_dir: Forwarded to :func:`build_traceability` when building.

    Returns:
        The sorted list of uncovered criterion ids.

    Raises:
        ValueError: If ``against`` is not ``"tasks"`` or ``"tests"``.
    """
    if against not in ("tasks", "tests"):
        raise ValueError(
            f"against must be 'tasks' or 'tests', got {against!r}"
        )
    if traceability is None:
        traceability = build_traceability(
            requirements_path=requirements_path,
            tasks_path=tasks_path,
            tests_dir=tests_dir,
        )
    key = "uncovered_by_tasks" if against == "tasks" else "uncovered_by_tests"
    return list(traceability[key])


def render_traceability_report(
    traceability: Optional[dict] = None,
    *,
    requirements_path: Path = DEFAULT_REQUIREMENTS_PATH,
    tasks_path: Path = DEFAULT_TASKS_PATH,
    tests_dir: Path = DEFAULT_TESTS_DIR,
) -> str:
    """Render the traceability matrix as a Markdown report.

    The report contains a summary of coverage counts, a per-criterion matrix
    table (criterion → covering tasks → validating tests → covered flag), a
    design-property coverage table, and explicit sections flagging any criteria
    with no covering task or no validating test.

    Args:
        traceability: A prebuilt :func:`build_traceability` result. When
            ``None``, the matrix is built from the provided paths.
        requirements_path: Forwarded to :func:`build_traceability` when building.
        tasks_path: Forwarded to :func:`build_traceability` when building.
        tests_dir: Forwarded to :func:`build_traceability` when building.

    Returns:
        A Markdown string ending in a trailing newline.
    """
    if traceability is None:
        traceability = build_traceability(
            requirements_path=requirements_path,
            tasks_path=tasks_path,
            tests_dir=tests_dir,
        )

    criteria: list[str] = traceability["criteria"]
    tasks_map: dict[str, list[str]] = traceability["tasks"]
    tests_map: dict[str, list[str]] = traceability["tests"]
    properties_map: dict[str, list[str]] = traceability["properties"]
    uncovered_tasks: list[str] = traceability["uncovered_by_tasks"]
    uncovered_tests: list[str] = traceability["uncovered_by_tests"]

    total = len(criteria)
    task_covered = total - len(uncovered_tasks)
    test_covered = total - len(uncovered_tests)

    lines: list[str] = []
    lines.append("# Requirement → Task → Test Traceability Matrix")
    lines.append("")
    lines.append(
        "Generated from `requirements.md`, `tasks.md`, and the `roadmap/tests/` "
        "suite. A criterion is *task-covered* when at least one task references "
        "it and *test-covered* when at least one test annotation references it."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Acceptance criteria: {total}")
    lines.append(
        f"- Task-covered: {task_covered}/{total} "
        f"({len(uncovered_tasks)} uncovered)"
    )
    lines.append(
        f"- Test-covered: {test_covered}/{total} "
        f"({len(uncovered_tests)} without a validating test)"
    )
    lines.append(
        f"- Design properties tagged: {len(properties_map)}"
    )
    lines.append("")

    # Matrix table.
    lines.append("## Coverage matrix")
    lines.append("")
    lines.append("| Criterion | Covering tasks | Validating tests | Covered |")
    lines.append("| --- | --- | --- | --- |")
    for criterion_id in criteria:
        task_ids = tasks_map.get(criterion_id, [])
        test_locs = tests_map.get(criterion_id, [])
        tasks_cell = ", ".join(task_ids) if task_ids else "—"
        tests_cell = (
            "<br>".join(f"`{loc}`" for loc in test_locs) if test_locs else "—"
        )
        covered = "yes" if task_ids else "**NO**"
        lines.append(
            f"| {criterion_id} | {tasks_cell} | {tests_cell} | {covered} |"
        )
    lines.append("")

    # Property coverage.
    lines.append("## Design-property coverage")
    lines.append("")
    if properties_map:
        lines.append("| Property | Test location(s) |")
        lines.append("| --- | --- |")
        for prop in sorted(properties_map, key=lambda p: int(p)):
            locs = "<br>".join(f"`{loc}`" for loc in properties_map[prop])
            lines.append(f"| Property {prop} | {locs} |")
    else:
        lines.append("_No numbered design-property tags found._")
    lines.append("")

    # Uncovered sections.
    lines.append("## Uncovered criteria")
    lines.append("")
    if uncovered_tasks:
        lines.append("### Without a covering task")
        lines.append("")
        for criterion_id in uncovered_tasks:
            lines.append(f"- {criterion_id}")
        lines.append("")
    else:
        lines.append("- Every criterion is mapped to at least one task. ✅")
        lines.append("")

    if uncovered_tests:
        lines.append("### Without a validating test (informational)")
        lines.append("")
        lines.append(
            "These criteria are narrative/scope statements covered by the "
            "authored `ROADMAP.md` and the structural tests collectively rather "
            "than by a 1:1 annotated test:"
        )
        lines.append("")
        for criterion_id in uncovered_tests:
            lines.append(f"- {criterion_id}")
        lines.append("")

    return "\n".join(lines) + "\n"
