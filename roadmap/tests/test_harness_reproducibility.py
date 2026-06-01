"""Property-based test for Evaluation Harness reproducibility (Property 6).

This module holds the Hypothesis property test for
**Property 6: Harness reproducibility within tolerance** (task 12.2).

Property 6 (design "Correctness Properties")
--------------------------------------------
*For any* Candidate_Model evaluated at least three times on the same (mocked)
inputs and same hardware, the per-metric scores across runs fall within the
documented per-metric tolerance.

Requirement 4.4
---------------
THE Evaluation_Harness SHALL be reproducible such that re-running the harness at
least three times on the same Candidate_Model and same hardware produces, for
each metric, scores within a documented per-metric tolerance expressed as an
absolute value or a percentage.

Because the harness derivation is fully deterministic (SHA-256 over the
candidate identity + seeds), re-runs are byte-identical, so every metric is
trivially within any tolerance and the report is reproducible. This test
asserts the contract holds across a wide input space, recomputing the tolerance
verdict independently via :func:`within_tolerance` rather than trusting the
report's own flags.

Validates: Requirements 4.4
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.evaluation_harness import (
    METRIC_KEYS,
    METRIC_TOLERANCES,
    MIN_REPRODUCIBILITY_RUNS,
    REQUIRED_MIN_VRAM_GB,
    EvaluationHarness,
    MetricReproducibility,
    MockCandidate,
    within_tolerance,
)

# License-compat values that do NOT trigger the "license" exclusion. A
# "prohibited" license would make the candidate excluded, so an *evaluable*
# candidate must carry one of these.
_EVALUABLE_LICENSES: tuple[str, ...] = ("compatible", "restricted")

# Runs are drawn at or above the documented minimum (3) up to a small upper
# bound to keep the property fast while still exercising several re-runs.
_MIN_RUNS = MIN_REPRODUCIBILITY_RUNS
_MAX_RUNS = 6


def _seed_value() -> st.SearchStrategy[float]:
    """A finite numeric measurement seed (never a bool, never NaN/inf)."""
    return st.floats(
        min_value=-1_000.0,
        max_value=1_000.0,
        allow_nan=False,
        allow_infinity=False,
    )


@st.composite
def _evaluable_candidate(draw: st.DrawFn) -> MockCandidate:
    """Generate an *evaluable* ``MockCandidate``.

    Evaluable means none of the documented exclusion conditions fire:
    ``weights_available=True``, ``license_compat`` is not ``"prohibited"``, and
    ``vram_gb`` is at or above :data:`REQUIRED_MIN_VRAM_GB`. Seeds are drawn for
    a random subset of the metric keys (a missing seed defaults to ``0.0`` in
    the harness), so the score derivation spans a meaningful input space.
    """
    model_id = draw(
        st.text(
            alphabet=st.characters(
                min_codepoint=33, max_codepoint=126, blacklist_characters="/"
            ),
            min_size=1,
            max_size=24,
        ).filter(lambda s: s.strip() != "")
    )
    revision = draw(
        st.text(
            alphabet=st.characters(min_codepoint=33, max_codepoint=126),
            min_size=1,
            max_size=12,
        ).filter(lambda s: s.strip() != "")
    )

    present_metrics = draw(
        st.lists(st.sampled_from(METRIC_KEYS), unique=True, max_size=len(METRIC_KEYS))
    )
    seeds = {metric: draw(_seed_value()) for metric in present_metrics}

    license_compat = draw(st.sampled_from(_EVALUABLE_LICENSES))
    gpu_class = draw(st.sampled_from(["L4", "A10G", "A100", "H100"]))
    vram_gb = draw(
        st.floats(
            min_value=REQUIRED_MIN_VRAM_GB,
            max_value=192.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    return MockCandidate(
        model_id=model_id,
        revision=revision,
        seeds=seeds,
        license_compat=license_compat,
        hardware={"gpu_class": gpu_class, "vram_gb": vram_gb},
        weights_available=True,
    )


# Feature: speech-native-voice-roadmap, Property 6: Harness reproducibility within tolerance
@settings(max_examples=100)
@given(candidate=_evaluable_candidate(), runs=st.integers(min_value=_MIN_RUNS, max_value=_MAX_RUNS))
def test_property_6_harness_reproducibility_within_tolerance(
    candidate: MockCandidate, runs: int
) -> None:
    """Property 6: Harness reproducibility within tolerance.

    Validates: Requirements 4.4
    """
    harness = EvaluationHarness()
    report = harness.reproduce(candidate, runs=runs)

    # Identity + run count are carried through faithfully.
    assert report.model_id == candidate.model_id
    assert report.revision == candidate.revision
    assert report.runs == runs

    # An evaluable candidate is measured, not excluded.
    assert report.excluded is False
    assert report.exclusion_category is None

    # One MetricReproducibility per documented metric key, no extras.
    assert set(report.metrics) == set(METRIC_KEYS)
    assert len(report.metrics) == len(METRIC_KEYS)

    for metric_key in METRIC_KEYS:
        record = report.metrics[metric_key]
        assert isinstance(record, MetricReproducibility)
        assert record.metric_key == metric_key

        # One value per run, in run order.
        assert len(record.values) == runs

        # Determinism: byte-identical re-runs => every value equals the first.
        reference = record.values[0]
        assert all(value == reference for value in record.values)

        # The recorded tolerance rule matches the documented per-metric table.
        expected_kind, expected_amount = METRIC_TOLERANCES[metric_key]
        assert record.tolerance_kind == expected_kind
        assert record.tolerance_amount == expected_amount

        # Independently recompute the tolerance verdict rather than trusting
        # the report's own flag: every value stays within the documented
        # tolerance of the reference (first) value.
        assert within_tolerance(metric_key, record.values) is True
        assert record.within_tolerance is True

    # Overall reproducibility holds when every metric is within tolerance.
    assert report.reproducible is True


@pytest.mark.parametrize("runs", [0, 1, 2])
def test_reproduce_rejects_runs_below_minimum(runs: int) -> None:
    """``reproduce`` requires at least ``MIN_REPRODUCIBILITY_RUNS`` (Req 4.4)."""
    candidate = MockCandidate(
        model_id="kyutai/moshiko",
        revision="rev-1",
        seeds={"latency_ms_p50": 1.0},
        license_compat="compatible",
        hardware={"gpu_class": "L4", "vram_gb": 24.0},
    )
    harness = EvaluationHarness()
    with pytest.raises(ValueError):
        harness.reproduce(candidate, runs=runs)


def test_reproduce_excluded_candidate_is_trivially_reproducible() -> None:
    """An excluded candidate yields empty metrics and ``reproducible=True``.

    Exclusion is deterministic, so every run agrees no measurement happened:
    the report carries no measured metrics and is trivially reproducible, with
    the exclusion surfaced so callers can tell it apart from a measured run.
    """
    candidate = MockCandidate(
        model_id="some/unavailable-model",
        revision="rev-1",
        weights_available=False,  # missing-weights exclusion
    )
    harness = EvaluationHarness()
    report = harness.reproduce(candidate, runs=_MIN_RUNS)

    assert report.excluded is True
    assert report.exclusion_category == "missing_weights"
    assert report.metrics == {}
    assert report.reproducible is True
    assert report.runs == _MIN_RUNS
