"""Render a human-readable evaluation report from ``HarnessRun`` records.

This module turns the *output* of
:class:`~roadmap.evaluation_harness.EvaluationHarness` — a list of
:class:`~roadmap.models.runtime.HarnessRun` records — into a human-readable
Markdown report. It is the presentation counterpart to the evaluation-harness
decision logic and intentionally adds **no** measurement or decision-making of
its own: it reports exactly what the already-computed ``HarnessRun`` records
contain.

What the report contains (Requirements 4.1, 4.2, 4.3, 4.5)
----------------------------------------------------------
- An **evaluated candidates** table for the non-excluded runs, with the
  identical comparable columns for every candidate (Requirements 4.1, 4.2,
  4.3): model id, revision, first-response latency (ms, p50), code-switch
  quality, expressiveness, license-compatibility, and the hardware used as
  ``gpu_class`` and ``vram_gb``. Metric values are read from
  ``run.metric_scores`` keyed by the canonical
  :data:`~roadmap.evaluation_harness.METRIC_KEYS`, and hardware from
  ``run.hardware``.
- An **excluded candidates** table for runs with ``excluded=True``, in a
  separate section, showing the model id, revision, exclusion category, and
  exclusion reason (Requirement 4.5). Excluded runs carry no metric scores
  (their ``metric_scores`` is the documented empty ``{}`` sentinel), so they
  are reported by category + reason instead of metric columns.

This module performs no I/O and no GPU/training work; it is a pure string
renderer operating on the already-computed planning objects, preserving the
import-only / no-training guarantee enforced across the roadmap tooling
(Requirement 4.6).

Requirements: 4.1, 4.2, 4.3, 4.5.
"""

from __future__ import annotations

from ..evaluation_harness import CODESWITCH_KEY, EXPRESSIVENESS_KEY, LATENCY_KEY
from ..models.runtime import HarnessRun

__all__ = [
    "render_evaluation_report",
]

#: Rendered for a value that is absent from a record (a missing metric key or a
#: missing hardware field), so a reader can distinguish "no value present" from
#: a real measured value.
_MISSING = "—"


def render_evaluation_report(runs: list[HarnessRun]) -> str:
    """Render a human-readable Markdown report for a set of evaluation runs.

    Produces an evaluation report from already-computed :class:`HarnessRun`
    records. The renderer is pure: it reports exactly what the ``runs`` contain
    and performs no measurement or selection of its own.

    The report has two sections. The **evaluated candidates** table lists every
    non-excluded run with the identical comparable columns (model id, revision,
    latency p50, code-switch quality, expressiveness, license-compat, GPU class,
    VRAM) so the candidates are directly comparable (Requirements 4.1, 4.2,
    4.3). The **excluded candidates** table lists every run with
    ``excluded=True`` by its exclusion category and reason instead (Requirement
    4.5), since an excluded run carries no metric scores.

    Args:
        runs: The :class:`HarnessRun` records to report. An empty list is
            handled gracefully (each section shows an explanatory placeholder).

    Returns:
        A Markdown string. The report always contains both the evaluated and
        excluded sections; each shows a placeholder line when it has no rows.
    """
    evaluated = [run for run in runs if not run.excluded]
    excluded = [run for run in runs if run.excluded]

    lines: list[str] = ["# Candidate Model Evaluation Report", ""]
    lines.extend(_render_evaluated(evaluated))
    lines.append("")
    lines.extend(_render_excluded(excluded))

    return "\n".join(lines) + "\n"


# -- Section renderers -------------------------------------------------------


def _render_evaluated(runs: list[HarnessRun]) -> list[str]:
    """Render the evaluated-candidate table with identical comparable columns."""
    lines = ["## Evaluated Candidates"]
    if not runs:
        lines.append("")
        lines.append("_No candidates were evaluated._")
        return lines

    lines.append("")
    lines.append(
        "| Model ID | Revision | Latency (ms, p50) | Code-switch quality "
        "| Expressiveness | License-compat | GPU class | VRAM (GB) |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for run in runs:
        lines.append(
            f"| {_text(run.model_id)} "
            f"| {_text(run.revision)} "
            f"| {_metric(run, LATENCY_KEY)} "
            f"| {_metric(run, CODESWITCH_KEY)} "
            f"| {_metric(run, EXPRESSIVENESS_KEY)} "
            f"| {_text(run.license_compat)} "
            f"| {_hardware(run, 'gpu_class')} "
            f"| {_hardware(run, 'vram_gb')} |"
        )
    return lines


def _render_excluded(runs: list[HarnessRun]) -> list[str]:
    """Render the excluded-candidate table by category + reason (4.5)."""
    lines = ["## Excluded Candidates"]
    if not runs:
        lines.append("")
        lines.append("_No candidates were excluded._")
        return lines

    lines.append("")
    lines.append("| Model ID | Revision | Exclusion category | Exclusion reason |")
    lines.append("| --- | --- | --- | --- |")
    for run in runs:
        lines.append(
            f"| {_text(run.model_id)} "
            f"| {_text(run.revision)} "
            f"| {_text(run.exclusion_category)} "
            f"| {_text(run.exclusion_reason)} |"
        )
    return lines


# -- Value formatting --------------------------------------------------------


def _metric(run: HarnessRun, metric_key: str) -> str:
    """Render a metric value from ``run.metric_scores``, defensively.

    Reads the value keyed by ``metric_key`` and renders it via
    :func:`_format_number`. A missing key (e.g. an excluded run's empty
    ``metric_scores``) renders as :data:`_MISSING`.
    """
    scores = run.metric_scores
    if not isinstance(scores, dict) or metric_key not in scores:
        return _MISSING
    return _format_number(scores[metric_key])


def _hardware(run: HarnessRun, key: str) -> str:
    """Render a hardware field from ``run.hardware``, defensively.

    ``vram_gb`` is rendered as a number; ``gpu_class`` as text. A missing field
    or non-dict ``hardware`` renders as :data:`_MISSING`.
    """
    hardware = run.hardware
    if not isinstance(hardware, dict) or key not in hardware:
        return _MISSING
    value = hardware[key]
    if key == "vram_gb":
        return _format_number(value)
    return _text(value)


def _text(value: object) -> str:
    """Render a textual cell value, mapping ``None``/empty to :data:`_MISSING`."""
    if value is None:
        return _MISSING
    text = str(value).strip()
    return text if text else _MISSING


def _format_number(value: object) -> str:
    """Render a numeric value without trailing ``.0`` noise.

    Integer-valued numbers render without a decimal point (``24`` not
    ``24.0``); other floats use their default ``str`` form. Non-numeric values
    fall back to :func:`_text` so a malformed score never crashes the renderer.
    """
    if isinstance(value, bool):
        return _text(value)
    if isinstance(value, (int, float)):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return str(value)
    return _text(value)
