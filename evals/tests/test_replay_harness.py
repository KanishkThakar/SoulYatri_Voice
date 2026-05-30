"""Tests for the replay harness over a mock pipeline + scenarios (Phase 15B)."""

from __future__ import annotations

import json

from evals.latency.metrics import MetricsCollector
from evals.replay.harness import (
    PipelineOutput,
    ReplayHarness,
    Scenario,
    ScenarioTurn,
    load_scenario,
    load_scenarios,
)
from evals.replay.mock_pipeline import make_mock_pipeline, mock_pipeline


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------
def test_load_all_bundled_scenarios():
    scenarios = load_scenarios()
    ids = {s.scenario_id for s in scenarios}
    # All seven required categories must be present (final_use.md §15B).
    expected = {
        "english_basic",
        "hindi_basic",
        "hinglish_codeswitch",
        "interruption_bargein",
        "distress",
        "short_confirmations",
        "noisy_speech",
    }
    assert expected.issubset(ids)


def test_scenarios_cover_required_categories():
    categories = {s.category for s in load_scenarios()}
    for required in {
        "english",
        "hindi",
        "hinglish",
        "interruptions",
        "distress",
        "short_confirmations",
        "noisy",
    }:
        assert required in categories


def test_scenario_json_is_valid_and_has_turns():
    for s in load_scenarios():
        assert s.turns, f"scenario {s.scenario_id} has no turns"


# ---------------------------------------------------------------------------
# Running the harness
# ---------------------------------------------------------------------------
def test_harness_runs_mock_pipeline_over_all_scenarios():
    harness = ReplayHarness(mock_pipeline)
    report = harness.run()
    assert report.total_turns > 0
    assert len(report.scenarios) >= 7
    # Mock echoes expected route/intent for non-trivial turns → high accuracy.
    assert report.route_accuracy == 1.0
    assert report.intent_accuracy == 1.0


def test_harness_captures_timings_into_collector():
    collector = MetricsCollector()
    harness = ReplayHarness(mock_pipeline, collector=collector)
    harness.run()
    # TTFA should have been recorded from the scenario timings.
    assert collector.count("time_to_first_audible_ms") > 0
    assert collector.count("interruption_recovery_ms") >= 1


def test_harness_records_filler_rates():
    collector = MetricsCollector()
    harness = ReplayHarness(mock_pipeline, collector=collector)
    harness.run()
    # Trivial turns from short_confirmations route to cached filler → hit rate high.
    assert collector.mean("filler_hit_rate") == 1.0
    # Non-trivial turns never route to filler in the mock → false-positive rate 0.
    assert collector.mean("filler_false_positive_rate") == 0.0


def test_report_is_json_serializable():
    harness = ReplayHarness(mock_pipeline)
    report = harness.run()
    payload = json.loads(report.to_json())
    assert payload["total_turns"] == report.total_turns
    assert "metrics" in payload


def test_harness_emits_structured_events():
    harness = ReplayHarness(mock_pipeline)
    harness.run()
    assert harness.events.last("replay_scenario") is not None
    assert len(harness.events.events("replay_turn")) == harness.run().total_turns


def test_injected_pipeline_protocol_with_custom_callable():
    def always_filler(turn: ScenarioTurn, scenario: Scenario) -> PipelineOutput:
        return PipelineOutput(route="cached_filler", intent=turn.expected_intent)

    scenario = Scenario(
        scenario_id="custom",
        category="english",
        language="en",
        description="custom",
        turns=[ScenarioTurn(transcript="hi", expected_route="full_stack", is_trivial=False)],
    )
    harness = ReplayHarness(always_filler)
    result = harness.run_scenario(scenario)
    # Route mismatch (filler vs expected full_stack) should be detected.
    assert result.route_accuracy == 0.0


def test_timing_scale_increases_recorded_latency():
    fast = MetricsCollector()
    slow = MetricsCollector()
    ReplayHarness(make_mock_pipeline(timing_scale=1.0), collector=fast).run()
    ReplayHarness(make_mock_pipeline(timing_scale=2.0), collector=slow).run()
    assert slow.mean("time_to_first_audible_ms") > fast.mean("time_to_first_audible_ms")


def test_load_single_scenario(tmp_path):
    payload = {
        "scenario_id": "x",
        "category": "english",
        "language": "en",
        "description": "d",
        "turns": [{"transcript": "hello", "expected_route": "full_stack"}],
    }
    p = tmp_path / "x.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    s = load_scenario(p)
    assert s.scenario_id == "x"
    assert len(s.turns) == 1
