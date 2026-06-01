"""Unit tests for the latency-budget report renderer (Requirements 7.1, 7.2, 7.3, 7.7).

These are plain ``pytest`` example-based tests for
:func:`roadmap.reports.latency_report.render_latency_report`. The renderer is a
pure string function, so the tests simply render the Markdown and assert on its
content.

What is covered
---------------
- The three p50 targets are always present — practical ``<= 300 ms``, stretch
  ``<= 200 ms``, perceived ``<= 80 ms`` — each with the ``<=`` operator and the
  ``ms`` unit (Requirements 7.1, 7.2, 7.3).
- With no measurement, the report renders the targets and the mitigation
  options but no PASS/FAIL evaluation section.
- A measured p50 that meets practical but not stretch shows practical PASS and
  stretch FAIL; one that misses practical shows both FAIL; one that meets both
  shows both PASS (Requirements 7.1, 7.2).
- The mitigation options (quantization, smaller core, expanded filler coverage)
  are always listed (Requirement 7.7).
- A supplied ``target_profile`` label appears in the report header.

Assertions check substrings of the rendered string (case-insensitive where
reasonable) so they stay robust to exact spacing while remaining specific.
"""

from __future__ import annotations

import re

from roadmap.reports.latency_report import (
    PERCEIVED_TARGET_MS,
    PRACTICAL_TARGET_MS,
    STRETCH_TARGET_MS,
    render_latency_report,
)


# --- Helpers ---------------------------------------------------------------


def _evaluation_section(report: str) -> str:
    """Return the text of the ``## Measured p50 Evaluation`` section, or ``""``.

    Collects the lines from the evaluation header up to the next ``## `` section
    header (or end of report). Returns an empty string when the section is
    absent.
    """
    lines = report.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == "## Measured p50 Evaluation":
            in_section = True
            out.append(line)
            continue
        if in_section:
            if line.startswith("## "):
                break
            out.append(line)
    return "\n".join(out)


def _practical_result(report: str) -> str:
    """Return ``PASS``/``FAIL`` for the practical row in the evaluation section."""
    section = _evaluation_section(report)
    for line in section.splitlines():
        if "practical" in line.lower():
            return "PASS" if "PASS" in line else "FAIL"
    raise AssertionError(f"no practical row found in evaluation section:\n{section}")


def _stretch_result(report: str) -> str:
    """Return ``PASS``/``FAIL`` for the stretch row in the evaluation section."""
    section = _evaluation_section(report)
    for line in section.splitlines():
        if "stretch" in line.lower():
            return "PASS" if "PASS" in line else "FAIL"
    raise AssertionError(f"no stretch row found in evaluation section:\n{section}")


# --- Targets are always present (7.1, 7.2, 7.3) ----------------------------


def test_targets_always_present_with_operator_unit_and_labels() -> None:
    """The three p50 targets render with the <= operator, ms unit, and labels.

    Validates: Requirements 7.1, 7.2, 7.3
    """
    # Sanity-check the module constants match the design (300 / 200 / 80 ms).
    assert PRACTICAL_TARGET_MS == 300.0
    assert STRETCH_TARGET_MS == 200.0
    assert PERCEIVED_TARGET_MS == 80.0

    report = render_latency_report()
    lower = report.lower()

    # The targets table is present and stated at the p50 percentile.
    assert "latency targets" in lower
    assert "p50" in lower

    # The three labels are present.
    assert "practical" in lower
    assert "stretch" in lower
    assert "perceived" in lower

    # The three thresholds (ms) are present without trailing ".0" noise.
    assert "300" in report
    assert "200" in report
    assert "80" in report

    # The <= comparison operator and the ms unit are both stated.
    assert "<=" in report
    assert "ms" in lower


# --- No measurement: targets + mitigations, no evaluation section ----------


def test_no_measurement_renders_targets_and_mitigations_without_evaluation() -> None:
    """With no measurement, the report has targets + mitigations but no PASS/FAIL.

    Validates: Requirements 7.1, 7.2, 7.3, 7.7
    """
    report = render_latency_report()
    lower = report.lower()

    # Targets and mitigation options are present.
    assert "latency targets" in lower
    assert "mitigation options" in lower

    # No measured-evaluation section, and no PASS/FAIL verdicts at all.
    assert "measured p50 evaluation" not in lower
    assert _evaluation_section(report) == ""
    assert "PASS" not in report
    assert "FAIL" not in report


# --- Measured p50 meets practical but not stretch (250) --------------------


def test_measured_meets_practical_but_not_stretch() -> None:
    """A 250 ms p50 passes practical (<=300) but fails stretch (<=200).

    Validates: Requirements 7.1, 7.2
    """
    report = render_latency_report(250.0)
    lower = report.lower()

    # The evaluation section is rendered.
    assert "measured p50 evaluation" in lower
    assert _evaluation_section(report) != ""

    assert _practical_result(report) == "PASS"
    assert _stretch_result(report) == "FAIL"


# --- Measured p50 misses practical (420): both FAIL + mitigations framed ----


def test_measured_misses_practical_fails_both_and_frames_mitigations() -> None:
    """A 420 ms p50 fails practical and stretch, and lists the mitigations.

    Validates: Requirements 7.1, 7.2, 7.7
    """
    report = render_latency_report(420.0)

    assert _practical_result(report) == "FAIL"
    assert _stretch_result(report) == "FAIL"

    # Mitigations are present and framed as applicable (the practical target
    # was missed).
    lower = report.lower()
    assert "mitigation options" in lower
    assert "missed" in lower
    assert "quantization" in lower
    assert "smaller" in lower
    assert "filler" in lower


# --- Measured p50 meets both targets (150): both PASS ----------------------


def test_measured_meets_both_targets() -> None:
    """A 150 ms p50 passes practical (<=300) and stretch (<=200).

    Validates: Requirements 7.1, 7.2
    """
    report = render_latency_report(150.0)

    assert _practical_result(report) == "PASS"
    assert _stretch_result(report) == "PASS"


# --- Boundary: exactly on the targets passes (<=) --------------------------


def test_measured_exactly_on_targets_passes() -> None:
    """Measured p50 exactly equal to a target passes (operator is ``<=``).

    Validates: Requirements 7.1, 7.2
    """
    # Exactly on the practical target: practical PASS, stretch FAIL.
    practical_boundary = render_latency_report(PRACTICAL_TARGET_MS)
    assert _practical_result(practical_boundary) == "PASS"
    assert _stretch_result(practical_boundary) == "FAIL"

    # Exactly on the stretch target: both PASS.
    stretch_boundary = render_latency_report(STRETCH_TARGET_MS)
    assert _practical_result(stretch_boundary) == "PASS"
    assert _stretch_result(stretch_boundary) == "PASS"


# --- Mitigation options always listed (7.7) --------------------------------


def test_mitigation_options_always_listed() -> None:
    """The mitigation options are listed both with and without a measurement.

    Validates: Requirements 7.7
    """
    for report in (
        render_latency_report(),
        render_latency_report(150.0),  # met
        render_latency_report(250.0),  # practical met, stretch missed
        render_latency_report(420.0),  # practical missed
    ):
        lower = report.lower()
        assert "mitigation options" in lower
        assert "quantization" in lower
        assert "smaller" in lower
        assert "filler" in lower


# --- target_profile label appears in the header ----------------------------


def test_target_profile_label_appears_in_header() -> None:
    """A supplied target_profile label appears in the report header."""
    report = render_latency_report(target_profile="L4")

    # The first line is the header; the profile label appears in it.
    header = report.splitlines()[0]
    assert "L4" in header
    # Robust to spacing/case: the header mentions the profile in context.
    assert re.search(r"#\s*Latency Budget Report", header) is not None


def test_default_target_profile_label_appears_in_header() -> None:
    """The default profile label ("default") appears in the header when omitted."""
    report = render_latency_report()
    header = report.splitlines()[0]
    assert "default" in header.lower()
