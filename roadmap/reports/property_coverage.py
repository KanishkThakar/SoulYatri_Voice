"""Scan the roadmap test suite for the 15 numbered design properties.

The design's ``Correctness Properties`` section defines **15 numbered
properties** (Properties 1–15). Each is implemented by a Hypothesis
property-based test tagged with the *exact* comment marker::

    # Feature: speech-native-voice-roadmap, Property {n}: {text}

where ``{n}`` is the property number (1..15) and ``{text}`` is the short
property name. A single property may be exercised from several angles inside
*one* test file (e.g. a positive and a negative generator), so the same number
legitimately appears on multiple lines of the same file.

This module provides a small, stable, pure API that scans the roadmap tests
directory for those numbered markers and reports which of Properties 1–15 are
present, where each is implemented, and which (if any) are missing. It powers
the Task 39.2 coverage test that asserts all 15 properties are present.

Scope / matching rules (important)
----------------------------------
- Only the **exact** numbered marker is matched. Complementary invariant tests
  (serialization round-trip, schema round-trip, the ``budget select_scope``
  invariant, …) are deliberately tagged *without* a number — for example
  ``# Feature: speech-native-voice-roadmap, Property: select_scope …`` — so they
  are **not** counted as design properties.
- "Duplicate" means a property number implemented in **more than one distinct
  test file**. Multiple matching lines within a single file are expected (one
  property, several generators) and are *not* duplicates — the design intends a
  1:1 mapping between a numbered property and a test *file*.

This module performs read-only file I/O over the test *sources* and never
imports the tests, runs Hypothesis, or invokes any GPU/model-training work, so
it preserves the import-only / no-training guarantee of the roadmap tooling.

Requirements: 12.7.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..paths import PACKAGE_ROOT

__all__ = [
    "EXPECTED_PROPERTY_COUNT",
    "PROPERTY_NUMBERS",
    "PROPERTY_TAG_PATTERN",
    "PropertyTag",
    "default_tests_dir",
    "scan_property_tags",
    "find_property_numbers",
    "missing_properties",
    "extra_properties",
    "duplicate_properties",
    "render_property_coverage_report",
]

#: The number of numbered design properties the suite must implement.
EXPECTED_PROPERTY_COUNT = 15

#: The canonical set of expected property numbers (1..15 inclusive).
PROPERTY_NUMBERS: frozenset[int] = frozenset(range(1, EXPECTED_PROPERTY_COUNT + 1))

#: Matches *only* the numbered property marker. ``Property`` must be followed by
#: whitespace and one or more digits, so a non-numbered complementary tag such
#: as ``Property: select_scope …`` is intentionally excluded.
PROPERTY_TAG_PATTERN = re.compile(
    r"# Feature: speech-native-voice-roadmap, Property\s+(\d+):\s*(.*)"
)


@dataclass(frozen=True)
class PropertyTag:
    """A single occurrence of a numbered property marker in a test source.

    Attributes:
        number: The property number parsed from the marker (e.g. ``12``).
        text: The trailing property name/text, stripped of surrounding
            whitespace (e.g. ``"Watermark on every output path"``).
        file: Absolute path to the test file the marker was found in.
        line: 1-based line number of the marker within ``file``.
    """

    number: int
    text: str
    file: Path
    line: int


def default_tests_dir() -> Path:
    """Return the canonical roadmap tests directory (``roadmap/tests``).

    Resolved from :data:`roadmap.paths.PACKAGE_ROOT` so callers and tests locate
    the suite identically regardless of the working directory.
    """
    return PACKAGE_ROOT / "tests"


def _resolve_tests_dir(tests_dir: Optional[Path | str]) -> Path:
    """Coerce ``tests_dir`` to a :class:`Path`, defaulting to ``roadmap/tests``."""
    if tests_dir is None:
        return default_tests_dir()
    return Path(tests_dir)


def _iter_test_sources(tests_dir: Path):
    """Yield the ``.py`` test sources under ``tests_dir`` in a stable order.

    Sorting keeps :func:`scan_property_tags` deterministic so reports and the
    coverage test produce identical output across runs.
    """
    if not tests_dir.is_dir():
        return
    for path in sorted(tests_dir.rglob("*.py")):
        if path.is_file():
            yield path


def scan_property_tags(
    tests_dir: Optional[Path | str] = None,
) -> dict[int, list[PropertyTag]]:
    """Scan the tests directory and map each property number to its occurrences.

    Args:
        tests_dir: Directory to scan. Defaults to ``roadmap/tests`` (resolved via
            :func:`default_tests_dir`).

    Returns:
        A dict mapping each property number found to the list of
        :class:`PropertyTag` occurrences (ordered by file then line number).
        Only the exact numbered marker is matched; non-numbered complementary
        tags are ignored. The returned dict is ordered by ascending property
        number for stable, readable output.
    """
    root = _resolve_tests_dir(tests_dir)
    found: dict[int, list[PropertyTag]] = {}

    for path in _iter_test_sources(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Skip unreadable/binary sources rather than failing the whole scan.
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = PROPERTY_TAG_PATTERN.search(line)
            if match is None:
                continue
            number = int(match.group(1))
            tag_text = match.group(2).strip()
            found.setdefault(number, []).append(
                PropertyTag(number=number, text=tag_text, file=path, line=lineno)
            )

    return {number: found[number] for number in sorted(found)}


def find_property_numbers(tests_dir: Optional[Path | str] = None) -> set[int]:
    """Return the set of property numbers present in the test suite."""
    return set(scan_property_tags(tests_dir).keys())


def missing_properties(tests_dir: Optional[Path | str] = None) -> list[int]:
    """Return the sorted Properties 1–15 that are NOT present in the suite."""
    present = find_property_numbers(tests_dir)
    return sorted(PROPERTY_NUMBERS - present)


def extra_properties(tests_dir: Optional[Path | str] = None) -> list[int]:
    """Return sorted property numbers present but outside the 1–15 range.

    Useful for the Task 39.2 assertion that there are "no numbers beyond 15".
    """
    present = find_property_numbers(tests_dir)
    return sorted(present - PROPERTY_NUMBERS)


def duplicate_properties(tests_dir: Optional[Path | str] = None) -> dict[int, int]:
    """Return property numbers implemented across more than one test FILE.

    The design intends a 1:1 mapping between a numbered property and a single
    test file. Several matching lines inside *one* file (a positive and a
    negative generator for the same property) are expected and are **not**
    flagged. A number is reported here only when it appears in two or more
    distinct files, which would break that 1:1 mapping.

    Returns:
        A dict mapping each offending property number to the count of distinct
        files it was found in (always ``>= 2``). Empty when the mapping is 1:1.
    """
    tags = scan_property_tags(tests_dir)
    duplicates: dict[int, int] = {}
    for number, occurrences in tags.items():
        distinct_files = {occ.file for occ in occurrences}
        if len(distinct_files) > 1:
            duplicates[number] = len(distinct_files)
    return duplicates


def _format_files(tests_dir: Path, occurrences: list[PropertyTag]) -> str:
    """Render the distinct file name(s) for a property's occurrences."""
    names: list[str] = []
    for occ in occurrences:
        try:
            rel = occ.file.relative_to(tests_dir)
        except ValueError:
            rel = occ.file
        name = rel.as_posix()
        if name not in names:
            names.append(name)
    return ", ".join(names)


def render_property_coverage_report(
    tests_dir: Optional[Path | str] = None,
) -> str:
    """Render a Markdown coverage report for Properties 1–15.

    The report has a row per expected property (1..15) with its present/missing
    status, the file(s) implementing it, and the property text, followed by a
    summary line and — when applicable — notes about cross-file duplicates or
    out-of-range property numbers.

    Args:
        tests_dir: Directory to scan. Defaults to ``roadmap/tests``.

    Returns:
        A Markdown string ending with a trailing newline.
    """
    root = _resolve_tests_dir(tests_dir)
    tags = scan_property_tags(root)
    missing = missing_properties(root)

    lines: list[str] = [
        "# Property-Test Coverage Report",
        "",
        f"Feature: speech-native-voice-roadmap — expecting "
        f"{EXPECTED_PROPERTY_COUNT} numbered properties.",
        "",
        "| Property # | Present? | File(s) | Text |",
        "| --- | --- | --- | --- |",
    ]

    for number in range(1, EXPECTED_PROPERTY_COUNT + 1):
        occurrences = tags.get(number)
        if occurrences:
            present = "yes"
            files = _format_files(root, occurrences)
            text = occurrences[0].text
        else:
            present = "**MISSING**"
            files = "—"
            text = "—"
        lines.append(f"| {number} | {present} | {files} | {text} |")

    present_count = sum(1 for n in range(1, EXPECTED_PROPERTY_COUNT + 1) if n in tags)
    lines.append("")
    lines.append(
        f"**Coverage: {present_count}/{EXPECTED_PROPERTY_COUNT} properties present.**"
    )

    if missing:
        joined = ", ".join(str(n) for n in missing)
        lines.append("")
        lines.append(f"- Missing properties: {joined}")
    else:
        lines.append("")
        lines.append("- Missing properties: none")

    duplicates = duplicate_properties(root)
    if duplicates:
        lines.append("")
        lines.append("- Duplicate properties (implemented in >1 file):")
        for number in sorted(duplicates):
            files = _format_files(root, tags[number])
            lines.append(f"  - Property {number}: {duplicates[number]} files ({files})")

    extras = extra_properties(root)
    if extras:
        joined = ", ".join(str(n) for n in extras)
        lines.append("")
        lines.append(f"- Out-of-range property numbers (beyond 15): {joined}")

    return "\n".join(lines) + "\n"
