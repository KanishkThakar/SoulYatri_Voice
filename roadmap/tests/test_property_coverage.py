"""Coverage test asserting all 15 numbered design properties are present.

This is a plain ``pytest`` example-based test (no Hypothesis) for the
:mod:`roadmap.reports.property_coverage` scanner. It locks in the design's
contract that the ``Correctness Properties`` section defines exactly **15
numbered properties** (Properties 1–15) and that the roadmap test suite
implements each of them in exactly one test file, with no missing numbers, no
numbers beyond 15, and no cross-file duplicates.

If any of these assertions fail it is a real finding about the suite's property
coverage (a property is missing, mis-numbered, or implemented in more than one
file) rather than a flaky test — the canonical set must be exactly 1..15.

Requirements: 12.7.
"""

from __future__ import annotations

from roadmap.reports.property_coverage import (
    EXPECTED_PROPERTY_COUNT,
    PROPERTY_NUMBERS,
    duplicate_properties,
    extra_properties,
    find_property_numbers,
    missing_properties,
    render_property_coverage_report,
)


def test_expected_property_count_is_15() -> None:
    """The design mandates exactly 15 numbered properties."""
    assert EXPECTED_PROPERTY_COUNT == 15
    assert PROPERTY_NUMBERS == frozenset(range(1, 16))


def test_all_15_properties_are_present() -> None:
    """Every numbered design property (1..15) is implemented in the suite."""
    assert find_property_numbers() == set(range(1, 16))


def test_no_properties_are_missing() -> None:
    """None of Properties 1–15 are absent from the test suite."""
    assert missing_properties() == []


def test_no_extra_property_numbers() -> None:
    """No property numbers appear beyond the canonical 1–15 range."""
    assert extra_properties() == []


def test_no_cross_file_duplicate_properties() -> None:
    """Each numbered property is implemented in exactly one test file."""
    assert duplicate_properties() == {}


def test_coverage_report_reports_full_coverage() -> None:
    """The rendered report is non-empty, mentions 15, and marks all present."""
    report = render_property_coverage_report()

    assert isinstance(report, str)
    assert report.strip() != ""
    # The expected count is surfaced in the report header.
    assert "15" in report
    # Full coverage with nothing missing.
    assert "Coverage: 15/15 properties present." in report
    assert "Missing properties: none" in report
    # No duplicate or out-of-range notes should be rendered.
    assert "Duplicate properties" not in report
    assert "Out-of-range property numbers" not in report
