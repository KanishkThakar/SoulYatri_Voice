"""Property-based test for design **Property 4: Evaluation harness comparability
and record completeness**.

This module holds the Hypothesis property test for task 10.2. Per the design's
``Correctness Properties`` section:

    For any set of evaluated Candidate_Models, every produced run record uses
    the identical metric key set and the identical scoring scale, and each
    record contains the model identifier, the model version/revision, a
    first-response latency (ms, p50), a Hindi/Hinglish code-switch quality
    score, a numeric emotional-expressiveness score, a categorical
    license-compatibility value, and the hardware used expressed as GPU class
    and VRAM in GB.

The comparability + completeness guarantee applies to **non-excluded** records
(an excluded candidate deliberately carries an empty ``metric_scores`` sentinel
and is the subject of Property 5 instead). This test therefore generates
candidates that are *guaranteed evaluable* — ``weights_available=True``,
``license_compat != "prohibited"``, and ``hardware["vram_gb"] >=
REQUIRED_MIN_VRAM_GB`` — so the harness produces a full record for every one.

The project Hypothesis profile ``roadmap`` (``max_examples=100``) is loaded by
``roadmap/tests/conftest.py``; this property test additionally pins
``@settings(max_examples=100)`` because the design mandates at least 100
examples per property.

Validates: Requirements 4.1, 4.2, 4.3.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.evaluation_harness import (
    DEFAULT_SAMPLE_ITEMS,
    EXPRESSIVENESS_SCALE_MAX,
    EXPRESSIVENESS_SCALE_MIN,
    LATENCY_MS_MAX,
    LATENCY_MS_MIN,
    LICENSE_COMPAT_VALUES,
    METRIC_KEYS,
    QUALITY_SCALE_MAX,
    QUALITY_SCALE_MIN,
    REQUIRED_MIN_VRAM_GB,
    CODESWITCH_KEY,
    EXPRESSIVENESS_KEY,
    LATENCY_KEY,
    EvaluationHarness,
    MockCandidate,
)

# The canonical metric key set every non-excluded record must carry, as a set
# for direct equality comparison against each record's ``metric_scores`` keys.
_METRIC_KEY_SET: frozenset[str] = frozenset(METRIC_KEYS)

# ---------------------------------------------------------------------------
# Generators (constrained to the *evaluable* input space)
# ---------------------------------------------------------------------------

#: Non-blank short text used for GPU-class labels. Printable ASCII excluding the
#: space character so every drawn value stays non-empty after ``str.strip()``.
_NON_BLANK_TEXT = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=12,
)


def _numeric_seed() -> st.SearchStrategy[float]:
    """A finite, non-bool numeric measurement seed accepted by ``MockCandidate``."""
    return st.floats(
        min_value=-1_000.0,
        max_value=1_000.0,
        allow_nan=False,
        allow_infinity=False,
    )


def _seeds() -> st.SearchStrategy[dict]:
    """Mock measurement seeds keyed by a subset of :data:`METRIC_KEYS`.

    Drawing the keys from the real metric set (rather than arbitrary strings)
    mirrors how a caller supplies per-metric seeds; a missing metric simply
    defaults to seed ``0.0`` inside the harness. The empty dict is included so
    the "no seeds supplied" boundary is exercised.
    """
    return st.dictionaries(
        keys=st.sampled_from(METRIC_KEYS),
        values=_numeric_seed(),
        max_size=len(METRIC_KEYS),
    )


def _evaluable_hardware() -> st.SearchStrategy[dict]:
    """A hardware descriptor that clears the evaluation VRAM floor.

    ``vram_gb`` is drawn at or above :data:`REQUIRED_MIN_VRAM_GB` so the
    candidate is never excluded under the ``"hardware"`` category, guaranteeing
    a full (non-excluded) record.
    """
    return st.builds(
        lambda gpu_class, vram_gb: {"gpu_class": gpu_class, "vram_gb": vram_gb},
        gpu_class=_NON_BLANK_TEXT,
        vram_gb=st.floats(
            min_value=float(REQUIRED_MIN_VRAM_GB),
            max_value=200.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def _evaluable_candidate(draw: st.DrawFn, model_id: str) -> MockCandidate:
    """Draw a candidate that is guaranteed evaluable (never excluded).

    The three exclusion conditions are all avoided by construction:
    ``weights_available=True`` (no ``missing_weights``), ``license_compat`` in
    ``{compatible, restricted}`` (no ``license``), and ``vram_gb >=
    REQUIRED_MIN_VRAM_GB`` (no ``hardware``). So the harness always produces a
    full comparable record for this candidate.
    """
    return MockCandidate(
        model_id=model_id,
        revision=draw(st.sampled_from(["rev-1", "main", "v2.0", "abcdef0"])),
        seeds=draw(_seeds()),
        # Avoid "prohibited" so the candidate is not license-excluded.
        license_compat=draw(st.sampled_from(["compatible", "restricted"])),
        hardware=draw(_evaluable_hardware()),
        weights_available=True,
    )


@st.composite
def _evaluable_candidates(draw: st.DrawFn) -> list[MockCandidate]:
    """Draw a non-empty list of evaluable candidates with unique model ids.

    Unique ``model_id`` values (``model-0``, ``model-1``, …) match the harness's
    "one record per candidate" contract and let the test key records back to
    their originating candidate unambiguously.
    """
    count = draw(st.integers(min_value=1, max_value=8))
    return [
        draw(_evaluable_candidate(model_id=f"model-{index}"))
        for index in range(count)
    ]


# ---------------------------------------------------------------------------
# Property 4: Evaluation harness comparability and record completeness
# ---------------------------------------------------------------------------


# Feature: speech-native-voice-roadmap, Property 4: Evaluation harness comparability and record completeness
@settings(max_examples=100)
@given(candidates=_evaluable_candidates())
def test_property_4_harness_comparability_and_record_completeness(
    candidates: list[MockCandidate],
) -> None:
    """Property 4: Evaluation harness comparability and record completeness.

    Validates: Requirements 4.1, 4.2, 4.3.
    """
    harness = EvaluationHarness(sample_items=DEFAULT_SAMPLE_ITEMS)
    runs = harness.evaluate_all(candidates)

    # Exactly one record per candidate, preserving input order so each record
    # can be matched back to its originating candidate.
    assert len(runs) == len(candidates)

    for candidate, run in zip(candidates, runs):
        # These candidates are all evaluable: none should be excluded, so each
        # carries a full measured record (the comparability/completeness clause
        # of Property 4 applies to non-excluded records).
        assert run.excluded is False
        assert run.exclusion_category is None
        assert run.exclusion_reason is None

        # --- Req 4.1: identical metric key set on every record. -------------
        assert set(run.metric_scores.keys()) == _METRIC_KEY_SET
        # Exactly the three documented keys — no extras, none missing.
        assert len(run.metric_scores) == len(METRIC_KEYS)

        # --- Req 4.3: model identifier and revision match the candidate. ----
        assert run.model_id == candidate.model_id
        assert run.revision == candidate.revision

        # --- Req 4.2: each metric present, numeric, and on its fixed scale. -
        latency = run.metric_scores[LATENCY_KEY]
        quality = run.metric_scores[CODESWITCH_KEY]
        expressiveness = run.metric_scores[EXPRESSIVENESS_KEY]

        # First-response latency (ms, p50) within its fixed plausible band.
        assert isinstance(latency, float)
        assert LATENCY_MS_MIN <= latency <= LATENCY_MS_MAX

        # Hindi/Hinglish code-switch quality on the fixed 0..100 scale.
        assert isinstance(quality, float)
        assert QUALITY_SCALE_MIN <= quality <= QUALITY_SCALE_MAX

        # Numeric emotional-expressiveness score on the fixed 0..100 scale.
        assert isinstance(expressiveness, float)
        assert EXPRESSIVENESS_SCALE_MIN <= expressiveness <= EXPRESSIVENESS_SCALE_MAX

        # --- Req 4.2: categorical license compatibility in the allowed set. -
        assert run.license_compat in LICENSE_COMPAT_VALUES
        # The recorded value is the candidate's own categorical result.
        assert run.license_compat == candidate.license_compat

        # --- Req 4.3: hardware recorded as GPU class + VRAM in GB. -----------
        assert set(run.hardware.keys()) == {"gpu_class", "vram_gb"}
        assert isinstance(run.hardware["gpu_class"], str)
        assert run.hardware["gpu_class"]  # non-empty label
        assert isinstance(run.hardware["vram_gb"], float)

    # --- Req 4.1: the metric key set is IDENTICAL across all records. -------
    # Comparability means every candidate is scored on the same metric set; the
    # key set of every record equals METRIC_KEYS and therefore equals each
    # other's.
    key_sets = {frozenset(run.metric_scores.keys()) for run in runs}
    assert key_sets == {_METRIC_KEY_SET}
