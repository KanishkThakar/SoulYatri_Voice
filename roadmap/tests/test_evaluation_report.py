"""Unit tests for the evaluation report renderer (Requirements 4.1, 4.5).

These are plain ``pytest`` example-based tests for
:func:`roadmap.reports.evaluation_report.render_evaluation_report`. They build
realistic :class:`~roadmap.models.runtime.HarnessRun` inputs by running the real
:class:`~roadmap.evaluation_harness.EvaluationHarness` over candidates assembled
from the shared :func:`~roadmap.tests.fixtures.make_mock_candidate` builder, then
assert on the rendered Markdown string.

What is covered
---------------
- **Identical metric columns for every non-excluded row (Requirement 4.1):**
  the Evaluated Candidates table renders a single fixed header
  (Latency, Code-switch quality, Expressiveness, License-compat, GPU class,
  VRAM), so every non-excluded candidate inherently shares the same comparable
  columns. Each evaluable candidate's ``model_id`` appears as a row in the
  evaluated section.
- **Excluded candidates carry category + reason (Requirement 4.5):** an
  excludable candidate (``weights_available=False`` -> ``missing_weights``)
  appears in the Excluded Candidates section with its model id, the exclusion
  category, and part of the exclusion reason — and does *not* appear in the
  evaluated table.
- An evaluable candidate's metric values render in the evaluated table.
- An empty ``runs`` list renders both sections gracefully with placeholders.

Assertions check substrings of the rendered string so they stay robust to exact
spacing while remaining specific.
"""

from __future__ import annotations

from roadmap.evaluation_harness import (
    EXCLUSION_MISSING_WEIGHTS,
    EvaluationHarness,
)
from roadmap.reports.evaluation_report import render_evaluation_report
from roadmap.tests.fixtures import make_mock_candidate


# --- Helpers ---------------------------------------------------------------


def _section(report: str, header: str) -> str:
    """Return the text of the ``## <header>`` section, up to the next ``## ``.

    Lets assertions target a single section (e.g. only the evaluated table or
    only the excluded table) instead of the whole report.
    """
    lines = report.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == f"## {header}":
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            out.append(line)
    return "\n".join(out)


def _evaluated_section(report: str) -> str:
    return _section(report, "Evaluated Candidates")


def _excluded_section(report: str) -> str:
    return _section(report, "Excluded Candidates")


# --- Requirement 4.1: identical metric columns across non-excluded rows ----


def test_evaluated_table_header_has_identical_comparable_columns() -> None:
    """The evaluated table renders one fixed header of comparable columns.

    Because the table has a single fixed header, every non-excluded row
    inherently shares the identical metric columns (Requirement 4.1).

    Validates: Requirements 4.1
    """
    harness = EvaluationHarness()
    runs = harness.evaluate_all(
        [
            make_mock_candidate(model_id="kyutai/moshiko", revision="bf16"),
            make_mock_candidate(model_id="org/another-core", revision="v2"),
        ]
    )

    report = render_evaluation_report(runs)
    evaluated = _evaluated_section(report)

    # The single fixed header carries every comparable column.
    assert "Model ID" in evaluated
    assert "Revision" in evaluated
    assert "Latency" in evaluated
    assert "Code-switch quality" in evaluated
    assert "Expressiveness" in evaluated
    assert "License-compat" in evaluated
    assert "GPU class" in evaluated
    assert "VRAM" in evaluated


def test_every_non_excluded_candidate_appears_as_evaluated_row() -> None:
    """Each non-excluded candidate's model_id appears in the evaluated section.

    Validates: Requirements 4.1
    """
    harness = EvaluationHarness()
    candidates = [
        make_mock_candidate(model_id="kyutai/moshiko", revision="bf16"),
        make_mock_candidate(model_id="org/another-core", revision="v2"),
        make_mock_candidate(model_id="lab/third-core", revision="r3"),
    ]
    runs = harness.evaluate_all(candidates)
    assert all(not run.excluded for run in runs)

    report = render_evaluation_report(runs)
    evaluated = _evaluated_section(report)

    for candidate in candidates:
        assert candidate.model_id in evaluated, (
            f"expected {candidate.model_id!r} as an evaluated row"
        )


def test_evaluable_candidate_metric_values_render_in_evaluated_table() -> None:
    """An evaluable candidate's measured metric values render in its row.

    Validates: Requirements 4.1
    """
    harness = EvaluationHarness()
    candidate = make_mock_candidate(
        model_id="kyutai/moshiko",
        revision="bf16",
        seeds={
            "latency_ms_p50": 0.4,
            "codeswitch_quality": 0.7,
            "expressiveness": 0.6,
        },
        hardware={"gpu_class": "A100", "vram_gb": 40.0},
    )
    [run] = harness.evaluate_all([candidate])
    assert not run.excluded

    report = render_evaluation_report([run])
    evaluated = _evaluated_section(report)

    # The model id, license, and hardware are reported verbatim.
    assert "kyutai/moshiko" in evaluated
    assert "compatible" in evaluated
    assert "A100" in evaluated
    assert "40" in evaluated

    # The measured numeric scores appear in the rendered row (no missing markers
    # for an evaluable candidate's metrics).
    latency = run.metric_scores["latency_ms_p50"]
    expected_latency = (
        str(int(latency)) if float(latency).is_integer() else str(latency)
    )
    assert expected_latency in evaluated


# --- Requirement 4.5: excluded candidates carry category + reason ----------


def test_excluded_candidate_appears_with_category_and_reason() -> None:
    """An excludable candidate appears in the excluded section with category + reason.

    Validates: Requirements 4.5
    """
    harness = EvaluationHarness()
    evaluable = make_mock_candidate(model_id="kyutai/moshiko", revision="bf16")
    excludable = make_mock_candidate(
        model_id="org/no-weights",
        revision="r0",
        weights_available=False,
    )
    runs = harness.evaluate_all([evaluable, excludable])

    report = render_evaluation_report(runs)
    excluded_section = _excluded_section(report)
    evaluated_section = _evaluated_section(report)

    # The excluded candidate shows its model id, the exclusion category, and
    # part of the exclusion reason.
    assert "org/no-weights" in excluded_section
    assert EXCLUSION_MISSING_WEIGHTS in excluded_section
    assert "weights unavailable" in excluded_section

    # It does NOT appear in the evaluated table...
    assert "org/no-weights" not in evaluated_section
    # ...and the evaluable candidate does NOT appear in the excluded table.
    assert "kyutai/moshiko" in evaluated_section
    assert "kyutai/moshiko" not in excluded_section


def test_excluded_section_header_columns_present() -> None:
    """The excluded table header names the exclusion category and reason columns.

    Validates: Requirements 4.5
    """
    harness = EvaluationHarness()
    excludable = make_mock_candidate(
        model_id="org/no-weights",
        revision="r0",
        weights_available=False,
    )
    runs = harness.evaluate_all([excludable])

    excluded_section = _excluded_section(render_evaluation_report(runs))

    assert "Model ID" in excluded_section
    assert "Revision" in excluded_section
    assert "Exclusion category" in excluded_section
    assert "Exclusion reason" in excluded_section


# --- Empty runs: both sections render gracefully with placeholders ---------


def test_empty_runs_renders_both_sections_with_placeholders() -> None:
    """An empty runs list renders both sections gracefully with placeholders."""
    report = render_evaluation_report([])

    # Both section headers are always present.
    assert "## Evaluated Candidates" in report
    assert "## Excluded Candidates" in report

    # Each section shows an explanatory placeholder instead of a table.
    assert "_No candidates were evaluated._" in report
    assert "_No candidates were excluded._" in report
