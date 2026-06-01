"""
evals/replay/mock_pipeline.py — deterministic mock pipeline for the harness.
============================================================================
A reference :class:`evals.replay.harness.PipelineFn` implementation used by the
tests and as a worked example in ``evals/README.md``. It contains **no models
and no audio** — it derives a :class:`PipelineOutput` purely from the scenario
fixture (transcript flags + synthetic timing), so replays are deterministic on a
bare CPU-only machine (final_use.md §15B).

The real edge/speech pipeline implements the same ``PipelineFn`` Protocol; the
harness is identical for mock and production injections.
"""

from __future__ import annotations

from evals.replay.harness import PipelineOutput, Scenario, ScenarioTurn

__all__ = ["mock_pipeline", "make_mock_pipeline"]


def mock_pipeline(turn: ScenarioTurn, scenario: Scenario) -> PipelineOutput:
    """Deterministic mock: echoes the scenario's intended route/intent/emotion.

    Routing logic mirrors the bounded-filler rule (final_use.md §2.3 / Phase-3):
    only *trivial, non-distress* turns may take the cached-filler route; every
    other turn goes full-stack. Timings are taken straight from the fixture so
    the harness exercises the metric collector deterministically.
    """
    route = turn.expected_route
    if turn.is_trivial and not turn.is_distress:
        route = "cached_filler"
    elif turn.is_interruption:
        route = "full_stack"

    return PipelineOutput(
        route=route,
        intent=turn.expected_intent,
        emotion=turn.expected_emotion,
        timings=dict(turn.timing),
    )


def make_mock_pipeline(
    *,
    force_route: str | None = None,
    timing_scale: float = 1.0,
):
    """Build a configurable mock pipeline (used to drive regression scenarios).

    ``force_route`` overrides the derived route (useful to simulate a filler
    false-positive regression). ``timing_scale`` multiplies every reported
    timing (useful to simulate a latency regression — e.g. 2.0 doubles TTFA).
    """

    def _pipeline(turn: ScenarioTurn, scenario: Scenario) -> PipelineOutput:
        base = mock_pipeline(turn, scenario)
        route = force_route if force_route is not None else base.route
        timings = {k: v * timing_scale for k, v in base.timings.items()}
        return PipelineOutput(
            route=route,
            intent=base.intent,
            emotion=base.emotion,
            timings=timings,
        )

    return _pipeline
