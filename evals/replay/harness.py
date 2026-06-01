"""
evals/replay/harness.py — deterministic replay runner (Phase 15B).
==================================================================
Loads fixed conversation scenarios (English, Hindi, Hinglish, interruptions,
distress, short confirmations, noisy speech) from small JSON fixtures and runs
each through an **injected pipeline callable**, capturing metrics into a
:class:`evals.latency.metrics.MetricsCollector`.

Key properties (final_use.md §15B):
  * Scenarios are *data files* — transcripts + expected route/labels + synthetic
    timing. **No real audio, no models, no GPU.**
  * The pipeline is an injected interface (``PipelineFn`` Protocol), so the same
    harness runs against mocks here and a real edge/speech pipeline in CI.
  * Reproducible: a fixed scenario produces a deterministic report.

Reports are JSON-serializable so they can be recorded under ``runs/``
(final_use.md §3.3 acceptance recording).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from evals.latency.metrics import MetricsCollector
from evals.observability import EventLog

__all__ = [
    "Scenario",
    "ScenarioTurn",
    "PipelineOutput",
    "PipelineFn",
    "TurnResult",
    "ScenarioResult",
    "ReplayReport",
    "SCENARIOS_DIR",
    "load_scenario",
    "load_scenarios",
    "ReplayHarness",
]

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


# ---------------------------------------------------------------------------
# Scenario data model (mirrors the JSON fixtures)
# ---------------------------------------------------------------------------
@dataclass
class ScenarioTurn:
    """A single user turn within a scenario."""

    transcript: str
    language: str = "en"
    expected_route: str = "full_stack"  # cached_filler | full_stack | silent_wait
    expected_intent: str = "unknown"
    expected_emotion: str | None = None
    is_trivial: bool = False
    is_interruption: bool = False
    is_distress: bool = False
    noisy: bool = False
    # Synthetic timing budget for this turn (ms). Used to drive the mock pipeline.
    timing: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioTurn:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Scenario:
    """A named replay scenario loaded from a JSON fixture."""

    scenario_id: str
    category: str
    language: str
    description: str
    turns: list[ScenarioTurn] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        return cls(
            scenario_id=data["scenario_id"],
            category=data["category"],
            language=data.get("language", "en"),
            description=data.get("description", ""),
            turns=[ScenarioTurn.from_dict(t) for t in data.get("turns", [])],
        )


# ---------------------------------------------------------------------------
# Injected pipeline interface
# ---------------------------------------------------------------------------
@dataclass
class PipelineOutput:
    """What an injected pipeline returns for one turn.

    The harness compares these against the scenario's expectations and records
    the reported timings into the metrics collector.
    """

    route: str
    intent: str = "unknown"
    emotion: str | None = None
    # Reported timings (ms). Keys should be metric names from the registry, e.g.
    # ``time_to_first_audible_ms``, ``first_token_ms``, ``interruption_recovery_ms``,
    # ``turn_end_detection_delay_ms`` and per-stage ``stage_*_ms`` breakdowns.
    timings: dict[str, float] = field(default_factory=dict)


class PipelineFn(Protocol):
    """An injectable pipeline: turn (+ scenario) -> PipelineOutput."""

    def __call__(self, turn: ScenarioTurn, scenario: Scenario) -> PipelineOutput: ...


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass
class TurnResult:
    """Outcome of replaying one turn through the pipeline."""

    transcript: str
    expected_route: str
    actual_route: str
    route_match: bool
    expected_intent: str
    actual_intent: str
    intent_match: bool
    timings: dict[str, float] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    """Outcome of replaying one scenario."""

    scenario_id: str
    category: str
    language: str
    turns: list[TurnResult] = field(default_factory=list)

    @property
    def route_accuracy(self) -> float:
        if not self.turns:
            return 1.0
        return sum(1 for t in self.turns if t.route_match) / len(self.turns)

    @property
    def intent_accuracy(self) -> float:
        if not self.turns:
            return 1.0
        return sum(1 for t in self.turns if t.intent_match) / len(self.turns)


@dataclass
class ReplayReport:
    """Aggregate report across all replayed scenarios."""

    scenarios: list[ScenarioResult] = field(default_factory=list)
    metrics: dict[str, dict[str, float | int | str]] = field(default_factory=dict)

    @property
    def total_turns(self) -> int:
        return sum(len(s.turns) for s in self.scenarios)

    @property
    def route_accuracy(self) -> float:
        results = [t for s in self.scenarios for t in s.turns]
        if not results:
            return 1.0
        return sum(1 for t in results if t.route_match) / len(results)

    @property
    def intent_accuracy(self) -> float:
        results = [t for s in self.scenarios for t in s.turns]
        if not results:
            return 1.0
        return sum(1 for t in results if t.intent_match) / len(results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_scenarios": len(self.scenarios),
            "total_turns": self.total_turns,
            "route_accuracy": self.route_accuracy,
            "intent_accuracy": self.intent_accuracy,
            "scenarios": [asdict(s) for s in self.scenarios],
            "metrics": self.metrics,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------
def load_scenario(path: str | Path) -> Scenario:
    """Load a single scenario JSON fixture."""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return Scenario.from_dict(data)


def load_scenarios(directory: str | Path | None = None) -> list[Scenario]:
    """Load all ``*.json`` scenario fixtures from ``directory`` (sorted)."""
    base = Path(directory) if directory is not None else SCENARIOS_DIR
    scenarios = [load_scenario(p) for p in sorted(base.glob("*.json"))]
    return scenarios


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class ReplayHarness:
    """Runs scenarios through an injected pipeline and captures metrics."""

    def __init__(
        self,
        pipeline: PipelineFn,
        collector: MetricsCollector | None = None,
        event_log: EventLog | None = None,
    ) -> None:
        self._pipeline = pipeline
        self.collector = collector or MetricsCollector()
        self.events = event_log or EventLog()

    def run_turn(self, turn: ScenarioTurn, scenario: Scenario) -> TurnResult:
        output = self._pipeline(turn, scenario)
        # Record every reported timing into the collector for later aggregation.
        for metric_name, value in output.timings.items():
            self.collector.record(metric_name, value)
        # Record filler routing as rate events when the scenario marks triviality.
        if turn.is_trivial:
            self.collector.record_rate_event(
                "filler_hit_rate", output.route == "cached_filler"
            )
        else:
            self.collector.record_rate_event(
                "filler_false_positive_rate", output.route == "cached_filler"
            )
        result = TurnResult(
            transcript=turn.transcript,
            expected_route=turn.expected_route,
            actual_route=output.route,
            route_match=output.route == turn.expected_route,
            expected_intent=turn.expected_intent,
            actual_intent=output.intent,
            intent_match=output.intent == turn.expected_intent,
            timings=dict(output.timings),
        )
        self.events.emit(
            "replay_turn",
            scenario=scenario.scenario_id,
            route=output.route,
            route_match=result.route_match,
            intent_match=result.intent_match,
        )
        return result

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        result = ScenarioResult(
            scenario_id=scenario.scenario_id,
            category=scenario.category,
            language=scenario.language,
        )
        for turn in scenario.turns:
            result.turns.append(self.run_turn(turn, scenario))
        self.events.emit(
            "replay_scenario",
            scenario=scenario.scenario_id,
            route_accuracy=result.route_accuracy,
            intent_accuracy=result.intent_accuracy,
        )
        return result

    def run(self, scenarios: Iterable[Scenario] | None = None) -> ReplayReport:
        """Replay every scenario and return an aggregate report.

        When ``scenarios`` is None, all bundled fixtures are loaded and used.
        """
        scenario_list = list(scenarios) if scenarios is not None else load_scenarios()
        report = ReplayReport()
        for scenario in scenario_list:
            report.scenarios.append(self.run_scenario(scenario))
        report.metrics = {
            name: dist.to_dict() for name, dist in self.collector.snapshot().items()
        }
        return report
