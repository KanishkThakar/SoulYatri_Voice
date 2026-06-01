"""Command-line interface for the SoulYatri roadmap tooling.

This module wires the roadmap package's existing, fully-mocked decision-logic
components and report renderers behind a small ``argparse`` CLI so the planning
artifact can be validated, exercised, and reported on from the shell. It adds
**no** new decision logic of its own — every subcommand is a thin adapter over
an existing module:

Subcommands
-----------
- ``validate``       — load the roadmap (``roadmap_io.load_roadmap``) which
                       enforces the Task 5 phase-structure invariants on
                       construction and re-validates the result against the
                       JSON Schema (``schema.validate``). Reports the outcome.
- ``select``         — run the fully-mocked evaluate → select → gate pipeline
                       (``roadmap.evaluate_and_select``: the
                       :class:`~roadmap.EvaluationHarness` →
                       :class:`~roadmap.SelectionScorer` →
                       :class:`~roadmap.GateEvaluator`) over a built-in
                       ``MockCandidate`` fixture and prints the selection.
- ``gate-report``    — evaluate a gate from the roadmap data with the
                       :class:`~roadmap.GateEvaluator` and render it via
                       ``reports.gate_report.render_gate_report``.
- ``eval-report``    — evaluate the built-in candidate fixture with the mocked
                       harness and render
                       ``reports.evaluation_report.render_evaluation_report``.
- ``trace``          — render the requirement → task → test traceability matrix
                       (``reports.traceability.render_traceability_report``).
- ``coverage``       — render the design-property coverage report
                       (``reports.property_coverage.render_property_coverage_report``).
- ``render-roadmap`` — render the roadmap as Markdown via
                       ``roadmap_io.render_markdown`` when available, falling
                       back to the YAML/``to_dict`` form
                       (``serialization.dumps_yaml``) otherwise.

Every subcommand operates on fixture/default data so it runs with no required
arguments, and the CLI is **fully mocked**: it imports no GPU/model-training
framework and invokes no GPU/training run, preserving the import-only /
no-training guarantee enforced by ``roadmap/tests/test_config_smoke.py``
(Requirement 4.6).

Requirements: 2.4, 2.7, 2.9, 8.4, 12.7.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from roadmap import (
    SELECTION_CRITERIA,
    SELECTION_MINIMUMS,
    EvaluationHarness,
    GateEvaluator,
    MockCandidate,
    evaluate_and_select,
)
from roadmap.models.phases import Gate
from roadmap.reports.evaluation_report import render_evaluation_report
from roadmap.reports.gate_report import render_gate_report
from roadmap.reports.property_coverage import render_property_coverage_report
from roadmap.reports.traceability import render_traceability_report
from roadmap.roadmap_io import load_roadmap
from roadmap.roadmap_model import Roadmap
from roadmap.serialization import dumps_yaml

__all__ = ["main", "build_parser"]

#: The gate evaluated by ``gate-report`` when ``--gate`` is not supplied. The
#: LEAN demo launch gate is the canonical gate the roadmap ships behind.
DEFAULT_GATE_ID = "LEAN-DEMO"

#: Built-in sample measurements for the default LEAN demo launch gate so
#: ``gate-report`` produces a meaningful (passing) report with no arguments.
#: These mirror the gate's exit-criteria metric names in the roadmap data.
_DEFAULT_GATE_MEASUREMENTS: dict[str, float] = {
    "latency_ms_p50": 250.0,
    "hinglish_codeswitch_quality": 85.0,
    "emotional_expressiveness": 75.0,
}


# ---------------------------------------------------------------------------
# Built-in fixtures (no required args, fully mocked)
# ---------------------------------------------------------------------------
def _fixture_candidates() -> list[MockCandidate]:
    """Return the built-in ``MockCandidate`` fixture used by select/eval-report.

    A small, representative set of 2026 Candidate_Models: a primary full-duplex
    core, a large any-to-any model, and a reference/fallback generator carrying
    a restricted license. They are pure data carriers — no weights, no GPU.
    """
    return [
        MockCandidate(
            model_id="kyutai/moshiko-pytorch-bf16",
            revision="bf16",
            seeds={
                "latency_ms_p50": 0.1,
                "codeswitch_quality": 0.85,
                "expressiveness": 0.8,
            },
            license_compat="compatible",
            hardware={"gpu_class": "L4", "vram_gb": 24.0},
        ),
        MockCandidate(
            model_id="Qwen/Qwen3-Omni-30B-A3B-Instruct",
            revision="main",
            seeds={
                "latency_ms_p50": 0.4,
                "codeswitch_quality": 0.7,
                "expressiveness": 0.75,
            },
            license_compat="compatible",
            hardware={"gpu_class": "A100-80GB", "vram_gb": 80.0},
        ),
        MockCandidate(
            model_id="sesame/csm-1b",
            revision="main",
            seeds={
                "latency_ms_p50": 0.3,
                "codeswitch_quality": 0.5,
                "expressiveness": 0.6,
            },
            license_compat="restricted",
            hardware={"gpu_class": "L4", "vram_gb": 24.0},
        ),
    ]


def _passing_selection_scores() -> dict[str, float]:
    """Per-criterion scores that clear every ``SELECTION_MINIMUMS`` threshold."""
    return {
        criterion: min(100.0, float(SELECTION_MINIMUMS[criterion]) + 15.0)
        for criterion in SELECTION_CRITERIA
    }


def _below_minimum_selection_scores() -> dict[str, float]:
    """Per-criterion scores that miss one minimum (community activity)."""
    scores = _passing_selection_scores()
    scores["community_activity"] = 0.0
    return scores


def _fixture_selection_scores() -> dict[str, dict[str, float]]:
    """Map the fixture candidates to per-criterion selection scores.

    The primary core clears every minimum (and so is selectable); the others
    miss a minimum, so the documented argmax-among-passing selection resolves to
    the primary core rather than ``RETAIN_PHASE_1``.
    """
    return {
        "kyutai/moshiko-pytorch-bf16": _passing_selection_scores(),
        "Qwen/Qwen3-Omni-30B-A3B-Instruct": _below_minimum_selection_scores(),
        "sesame/csm-1b": _below_minimum_selection_scores(),
    }


def _find_gate(roadmap: Roadmap, gate_id: str) -> Optional[Gate]:
    """Return the gate with ``gate_id`` from the roadmap, or ``None``."""
    for gate in roadmap.gates:
        if gate.id == gate_id:
            return gate
    return None


# ---------------------------------------------------------------------------
# Subcommand handlers (each returns a process exit code)
# ---------------------------------------------------------------------------
def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate the roadmap schema + phase-structure invariants."""
    try:
        roadmap = load_roadmap()
    except Exception as exc:  # noqa: BLE001 - surface any load/validation failure
        print(f"validate: FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "validate: OK — roadmap loaded and validated "
        f"({len(roadmap.phases)} phases, {len(roadmap.gates)} gates). "
        "Phase-structure invariants and JSON Schema both satisfied."
    )
    return 0


def _cmd_select(args: argparse.Namespace) -> int:
    """Run the mocked harness → SelectionScorer → gate pipeline and print it."""
    candidates = _fixture_candidates()
    roadmap = load_roadmap()
    gate = _find_gate(roadmap, DEFAULT_GATE_ID)

    result = evaluate_and_select(
        candidates,
        selection_scores=_fixture_selection_scores(),
        gate=gate,
        gate_measurements=dict(_DEFAULT_GATE_MEASUREMENTS),
    )

    selection = result.selection
    print("select: Speech-Native Core selection")
    print(f"  selected: {selection.selected}")
    print(f"  passing : {', '.join(selection.passing) if selection.passing else '(none)'}")
    print("  weighted aggregates:")
    for model_id, aggregate in selection.aggregates.items():
        print(f"    - {model_id}: {aggregate:.3f}")

    if result.gate_result is not None:
        gate_result = result.gate_result
        verdict = "PASS" if gate_result.overall_passed else "FAIL"
        print(f"  gate {gate_result.gate_id}: {verdict} (blocked={gate_result.blocked})")

    return 0


def _cmd_gate_report(args: argparse.Namespace) -> int:
    """Evaluate a gate from the roadmap data and render its report."""
    roadmap = load_roadmap()
    gate = _find_gate(roadmap, args.gate)
    if gate is None:
        available = ", ".join(g.id for g in roadmap.gates)
        print(
            f"gate-report: unknown gate {args.gate!r}; available: {available}",
            file=sys.stderr,
        )
        return 1

    # Use the built-in sample measurements for the default gate; any metric not
    # supplied is fail-closed by the evaluator, which the report renders cleanly.
    measurements = (
        dict(_DEFAULT_GATE_MEASUREMENTS)
        if gate.id == DEFAULT_GATE_ID
        else {}
    )
    gate_result = GateEvaluator().evaluate(gate, measurements)
    print(render_gate_report(gate_result, gate=gate), end="")
    return 0


def _cmd_eval_report(args: argparse.Namespace) -> int:
    """Evaluate the built-in candidate fixture and render the eval report."""
    runs = EvaluationHarness().evaluate_all(_fixture_candidates())
    print(render_evaluation_report(runs), end="")
    return 0


def _cmd_trace(args: argparse.Namespace) -> int:
    """Render the requirement → task → test traceability matrix."""
    print(render_traceability_report(), end="")
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    """Render the design-property (1–15) coverage report."""
    print(render_property_coverage_report(), end="")
    return 0


def _cmd_render_roadmap(args: argparse.Namespace) -> int:
    """Render the roadmap as Markdown, falling back to the YAML/to_dict form."""
    roadmap = load_roadmap()

    # Prefer roadmap_io.render_markdown (added by Task 29.2). Resolve it at
    # runtime so this CLI works whether or not that function exists yet.
    import roadmap.roadmap_io as roadmap_io

    render_markdown = getattr(roadmap_io, "render_markdown", None)
    if callable(render_markdown):
        print(render_markdown(roadmap), end="")
    else:
        # Fallback: print the YAML/to_dict form (serialization.dumps_yaml is the
        # to_dict-backed YAML codec).
        print(dumps_yaml(roadmap), end="")
    return 0


# ---------------------------------------------------------------------------
# Parser construction + entry point
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build the ``argparse`` parser with one subparser per subcommand."""
    parser = argparse.ArgumentParser(
        prog="roadmap",
        description=(
            "SoulYatri speech-native voice roadmap tooling. All subcommands run "
            "on fixture/default data and are fully mocked (no GPU/training run)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "validate",
        help="Validate the roadmap schema and phase-structure invariants.",
    ).set_defaults(func=_cmd_validate)

    subparsers.add_parser(
        "select",
        help="Run the mocked harness → SelectionScorer → gate pipeline.",
    ).set_defaults(func=_cmd_select)

    gate_report_parser = subparsers.add_parser(
        "gate-report",
        help="Render a launch/decision-gate report from the roadmap data.",
    )
    gate_report_parser.add_argument(
        "--gate",
        default=DEFAULT_GATE_ID,
        help=f"Gate id to evaluate (default: {DEFAULT_GATE_ID}).",
    )
    gate_report_parser.set_defaults(func=_cmd_gate_report)

    subparsers.add_parser(
        "eval-report",
        help="Render the candidate-model evaluation report (mocked harness).",
    ).set_defaults(func=_cmd_eval_report)

    subparsers.add_parser(
        "trace",
        help="Render the requirement → task → test traceability matrix.",
    ).set_defaults(func=_cmd_trace)

    subparsers.add_parser(
        "coverage",
        help="Render the design-property (1–15) coverage report.",
    ).set_defaults(func=_cmd_coverage)

    subparsers.add_parser(
        "render-roadmap",
        help="Render the roadmap as Markdown (YAML/to_dict fallback).",
    ).set_defaults(func=_cmd_render_roadmap)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        A process exit code: ``0`` on success, non-zero on failure.
    """
    _force_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


def _force_utf8_streams() -> None:
    """Reconfigure stdout/stderr to UTF-8 so reports never fail to encode.

    The roadmap reports contain non-ASCII characters (``→``, ``—``, ``✅``).
    On platforms whose console encoding is not UTF-8 (e.g. Windows ``cp1252``),
    printing them to a redirected stream raises ``UnicodeEncodeError`` and the
    process would exit non-zero. Reconfiguring to UTF-8 here keeps every
    subcommand's output encodable and the exit code ``0``. The call is guarded
    so it is a no-op on streams that do not support ``reconfigure`` (e.g. a test
    harness's captured stream).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # pragma: no cover - defensive
                pass


if __name__ == "__main__":
    raise SystemExit(main())
