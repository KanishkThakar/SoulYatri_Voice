"""Property-based test for Evaluation Harness per-candidate exclusion.

This module holds the Hypothesis property test for
**Property 5: Exclusion recording without abort** (task 11.2).

Property 5 (design "Correctness Properties" / Requirements 4.5, 11.4)
--------------------------------------------------------------------
*For any* set of Candidate_Models in which some cannot be evaluated (missing
weights, a prohibiting license, or insufficient hardware) and some can,
:meth:`EvaluationHarness.evaluate_all` records each excludable candidate with an
``exclusion_category`` and ``exclusion_reason`` and **continues** evaluating the
remaining candidates without aborting. The returned list therefore always
carries exactly one record per input candidate, in input order; each excluded
record carries the documented category + reason and the empty-``metric_scores``
sentinel, while each evaluable candidate still produces a complete record with
the full metric key set.

The expected exclusion category is recomputed independently from each
candidate's fields using the documented fixed precedence
(``missing_weights`` -> ``license`` -> ``hardware``), derived from the
requirements/design rather than the implementation.

Validates: Requirements 4.5, 11.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.evaluation_harness import (
    EXCLUSION_CATEGORIES,
    EXCLUSION_HARDWARE,
    EXCLUSION_LICENSE,
    EXCLUSION_MISSING_WEIGHTS,
    METRIC_KEYS,
    REQUIRED_MIN_VRAM_GB,
    EvaluationHarness,
    MockCandidate,
)

# License values that do NOT trigger the "license" exclusion (anything but the
# single prohibiting value), used when a candidate must stay evaluable on the
# license axis.
_NON_PROHIBITED_LICENSES: tuple[str, ...] = ("compatible", "restricted")
_GPU_CLASSES: tuple[str, ...] = ("T4", "L4", "A10G", "A100", "H100")


def _seed_value() -> st.SearchStrategy[float]:
    """A finite numeric mock measurement seed."""
    return st.floats(
        min_value=-1_000.0,
        max_value=1_000.0,
        allow_nan=False,
        allow_infinity=False,
    )


def _seeds() -> st.SearchStrategy[dict]:
    """An optional, partial mapping of metric key -> numeric mock seed."""
    return st.dictionaries(
        keys=st.sampled_from(METRIC_KEYS),
        values=_seed_value(),
        max_size=len(METRIC_KEYS),
    )


def _evaluable_vram() -> st.SearchStrategy[float]:
    """VRAM at or above the required floor (does not trigger ``hardware``)."""
    return st.floats(
        min_value=REQUIRED_MIN_VRAM_GB,
        max_value=80.0,
        allow_nan=False,
        allow_infinity=False,
    )


def _insufficient_vram() -> st.SearchStrategy[float]:
    """VRAM strictly below the required floor (triggers ``hardware``)."""
    return st.floats(
        min_value=0.0,
        max_value=REQUIRED_MIN_VRAM_GB,
        exclude_max=True,
        allow_nan=False,
        allow_infinity=False,
    )


@st.composite
def _candidate(draw: st.DrawFn, model_id: str, kind: str) -> MockCandidate:
    """Generate one ``MockCandidate`` forced to be evaluable or excludable.

    - ``"evaluable"``: weights available, a non-prohibiting license, and VRAM at
      or above :data:`REQUIRED_MIN_VRAM_GB`, so no exclusion condition fires.
    - ``"excludable"``: a non-empty subset of the three exclusion triggers is
      activated (weights unavailable, a prohibiting license, and/or
      insufficient VRAM). More than one trigger may be set at once so the fixed
      precedence (``missing_weights`` -> ``license`` -> ``hardware``) is
      exercised; the expected category is recomputed from the resulting fields.
    """
    revision = draw(st.sampled_from(["rev-1", "rev-2", "main", "v1.0"]))
    seeds = draw(_seeds())
    gpu_class = draw(st.sampled_from(_GPU_CLASSES))

    if kind == "evaluable":
        weights_available = True
        license_compat = draw(st.sampled_from(_NON_PROHIBITED_LICENSES))
        vram_gb = draw(_evaluable_vram())
    else:  # "excludable" — activate at least one exclusion trigger.
        triggers = draw(
            st.lists(
                st.sampled_from(["weights", "license", "hardware"]),
                unique=True,
                min_size=1,
                max_size=3,
            )
        )
        weights_available = "weights" not in triggers
        license_compat = (
            "prohibited"
            if "license" in triggers
            else draw(st.sampled_from(_NON_PROHIBITED_LICENSES))
        )
        vram_gb = (
            draw(_insufficient_vram())
            if "hardware" in triggers
            else draw(_evaluable_vram())
        )

    return MockCandidate(
        model_id=model_id,
        revision=revision,
        seeds=seeds,
        license_compat=license_compat,
        hardware={"gpu_class": gpu_class, "vram_gb": vram_gb},
        weights_available=weights_available,
    )


@st.composite
def _mixed_candidates(draw: st.DrawFn) -> list[MockCandidate]:
    """Generate a candidate list guaranteed to contain both kinds.

    At least one evaluable and at least one excludable candidate are produced,
    then interleaved in a drawn order, so every example exercises the "some
    excludable, some evaluable" mix and the no-abort continuation across them.
    Model ids are unique so a positional match confirms order preservation.
    """
    n_evaluable = draw(st.integers(min_value=1, max_value=4))
    n_excludable = draw(st.integers(min_value=1, max_value=4))
    kinds = draw(
        st.permutations(["evaluable"] * n_evaluable + ["excludable"] * n_excludable)
    )
    return [
        draw(_candidate(model_id=f"model-{index}", kind=kind))
        for index, kind in enumerate(kinds)
    ]


def _expected_exclusion_category(candidate: MockCandidate) -> str | None:
    """Recompute the expected exclusion category from the documented precedence.

    Mirrors Requirement 4.5's three conditions in their fixed precedence order,
    independently of the harness implementation:

    1. ``missing_weights`` when ``weights_available is False``;
    2. ``license`` when ``license_compat == "prohibited"``;
    3. ``hardware`` when ``vram_gb`` is below :data:`REQUIRED_MIN_VRAM_GB`.

    Returns ``None`` when the candidate is evaluable.
    """
    if candidate.weights_available is False:
        return EXCLUSION_MISSING_WEIGHTS
    if candidate.license_compat == "prohibited":
        return EXCLUSION_LICENSE
    if float(candidate.hardware["vram_gb"]) < REQUIRED_MIN_VRAM_GB:
        return EXCLUSION_HARDWARE
    return None


# Feature: speech-native-voice-roadmap, Property 5: Exclusion recording without abort
@settings(max_examples=100)
@given(candidates=_mixed_candidates())
def test_property_5_exclusion_recording_without_abort(
    candidates: list[MockCandidate],
) -> None:
    """Property 5: Exclusion recording without abort.

    Validates: Requirements 4.5, 11.4
    """
    harness = EvaluationHarness()
    runs = harness.evaluate_all(candidates)

    # --- Req 4.5: no abort — exactly one record per candidate, in order. -----
    assert len(runs) == len(candidates)

    for run, candidate in zip(runs, candidates):
        # Order preserved: the positional record is for this exact candidate.
        assert run.model_id == candidate.model_id
        assert run.revision == candidate.revision

        expected_category = _expected_exclusion_category(candidate)

        if expected_category is not None:
            # --- Excludable: recorded as excluded with category + reason. ----
            # (Req 4.5 records exclusion category/reason; Req 11.4 records the
            # exclusion and its reason.)
            assert run.excluded is True
            assert run.exclusion_category in EXCLUSION_CATEGORIES
            # Independently recomputed precedence matches the recorded category.
            assert run.exclusion_category == expected_category
            # A descriptive, non-empty reason is recorded.
            assert isinstance(run.exclusion_reason, str)
            assert run.exclusion_reason.strip() != ""
            # Documented empty-metric_scores sentinel: no measurement performed.
            assert run.metric_scores == {}
        else:
            # --- Evaluable: still a complete record despite excluded peers. --
            assert run.excluded is False
            assert run.exclusion_category is None
            assert run.exclusion_reason is None
            # Identical, complete metric key set (Req 4.1/4.2 comparability).
            assert set(run.metric_scores.keys()) == set(METRIC_KEYS)
            assert len(run.metric_scores) == len(METRIC_KEYS)

    # --- The mix is genuinely exercised: both kinds appear in every run. -----
    assert any(run.excluded for run in runs)
    assert any(not run.excluded for run in runs)
