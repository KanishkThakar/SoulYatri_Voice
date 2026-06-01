"""Property-based round-trip tests for the planning-object serialization codecs.

This module exercises the lossless round-trip invariant of
``roadmap.serialization`` against generated, *valid* instances of every planning
dataclass and the :class:`~roadmap.roadmap_model.Roadmap` aggregate:

    from_dict(type(x), to_dict(x)) == x
    loads_json(type(x), dumps_json(x)) == x
    loads_yaml(type(x), dumps_yaml(x)) == x

This is a *complementary* round-trip invariant — it is intentionally **not** one
of the 15 numbered design correctness properties and is deliberately not tagged
with the ``Property {n}`` comment marker, so the Task 39 property-coverage
report continues to find exactly Properties 1–15. It instead provides broad,
generative confidence that the generic ``to_dict``/``from_dict`` dispatch and
the JSON/YAML string codecs faithfully preserve every planning structure.

Generation notes
----------------
- Every Hypothesis strategy constructs the dataclass through its real
  constructor, so each generated instance already satisfies that dataclass's
  construction-time validation (e.g. a :class:`Phase` always carries >= 1 guide
  section and a non-empty GPU class; a :class:`Gate` carries a valid operator
  set, a non-empty owner role, and a non-empty fallback action).
- :class:`~roadmap.models.runtime.EmotionFeatures` clamps valence/arousal/
  dominance into ``[-1, 1]`` on construction. The strategy deliberately draws
  out-of-range V/A/D so the clamp fires; because the instance ``x`` is built
  first (and is therefore already clamped), the round-trip equality is asserted
  against the constructed/clamped value, which holds (the clamp is idempotent).
- Generating arbitrary valid roadmaps is complex, so the :class:`Roadmap`
  strategy round-trips the canonical seven-phase roadmap and a minimal
  two-phase variant, decorated with optional gates, conflict entries, custom
  track labels, and custom scope statements.

Validates: Requirements 1.1, 12.7.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.models.phases import (
    GATE_KIND_VALUES,
    OPERATOR_VALUES,
    TRACK_VALUES,
    Gate,
    GateCriterion,
    Phase,
)
from roadmap.models.runtime import (
    CloningDecision,
    ComplianceWarning,
    ConsentRecord,
    EmotionFeatures,
    HarnessRun,
    LicenseEntry,
    NormalizationResult,
)
from roadmap.models.selection import (
    CandidateScores,
    CriterionResult,
    GateResult,
    SelectionOutcome,
)
from roadmap.roadmap_model import (
    FIRST_PHASE_ID,
    ConflictEntry,
    Roadmap,
    ScopeStatements,
)
from roadmap.serialization import (
    dumps_json,
    dumps_yaml,
    from_dict,
    loads_json,
    loads_yaml,
    to_dict,
)
from roadmap.tests.fixtures import make_phase, make_valid_roadmap

# ---------------------------------------------------------------------------
# Shared primitive strategies
# ---------------------------------------------------------------------------

#: Non-blank short text: printable ASCII excluding space, so every value is
#: non-empty after ``str.strip()`` (satisfies the dataclasses' non-empty-string
#: validation) while still exercising punctuation/quote/colon characters that
#: the JSON and YAML codecs must escape correctly.
NON_BLANK = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=20,
)

#: Free-form short text (may be empty / contain spaces) for fields with no
#: non-empty constraint (e.g. ``revision``, ``reason``, remediation entries).
TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    max_size=20,
)

#: Any finite float (no NaN/Inf): stdlib ``json`` and ``yaml.safe_*`` both
#: round-trip the float ``repr`` losslessly.
FINITE_FLOAT = st.floats(allow_nan=False, allow_infinity=False)

#: A non-negative compute figure (VRAM in GB).
VRAM_GB = st.floats(min_value=0.0, max_value=1024.0, allow_nan=False, allow_infinity=False)

#: A confidence value on the inclusive ``0..1`` scale.
CONFIDENCE = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

#: An out-of-range V/A/D value (beyond ``[-1, 1]`` on both ends) so the
#: :class:`EmotionFeatures` clamp fires during construction.
OUT_OF_RANGE_VAD = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)

#: A valid comparison operator (used for both ``GateCriterion`` and the plain
#: operator string on ``CriterionResult``).
OPERATOR = st.sampled_from(OPERATOR_VALUES)


# ---------------------------------------------------------------------------
# Strategies — phase models (roadmap.models.phases)
# ---------------------------------------------------------------------------

gate_criterion_strategy = st.builds(
    GateCriterion,
    metric_name=NON_BLANK,
    threshold=FINITE_FLOAT,
    operator=OPERATOR,
)

phase_strategy = st.builds(
    Phase,
    ordinal=st.integers(min_value=1, max_value=50),
    id=NON_BLANK,
    track=st.sampled_from(TRACK_VALUES),
    title=NON_BLANK,
    is_speech_native=st.booleans(),
    guide_sections=st.lists(NON_BLANK, min_size=1, max_size=4),
    compute_min_gpu_class=NON_BLANK,
    compute_min_vram_gb=VRAM_GB,
)

gate_strategy = st.builds(
    Gate,
    id=NON_BLANK,
    kind=st.sampled_from(GATE_KIND_VALUES),
    entry_criteria=st.lists(gate_criterion_strategy, max_size=3),
    exit_criteria=st.lists(gate_criterion_strategy, max_size=3),
    owner_role=NON_BLANK,
    fallback_action=NON_BLANK,
)


# ---------------------------------------------------------------------------
# Strategies — selection / gate-result models (roadmap.models.selection)
# ---------------------------------------------------------------------------

criterion_result_strategy = st.builds(
    CriterionResult,
    metric_name=NON_BLANK,
    measured=FINITE_FLOAT,
    threshold=FINITE_FLOAT,
    operator=OPERATOR,
    passed=st.booleans(),
)

gate_result_strategy = st.builds(
    GateResult,
    gate_id=NON_BLANK,
    criteria_results=st.lists(criterion_result_strategy, max_size=3),
    overall_passed=st.booleans(),
    blocked=st.booleans(),
    remediation=st.lists(TEXT, max_size=3),
)

candidate_scores_strategy = st.builds(
    CandidateScores,
    model_id=NON_BLANK,
    revision=TEXT,
    scores=st.dictionaries(keys=NON_BLANK, values=FINITE_FLOAT, max_size=6),
)

selection_outcome_strategy = st.builds(
    SelectionOutcome,
    selected=NON_BLANK,
    aggregates=st.dictionaries(keys=NON_BLANK, values=FINITE_FLOAT, max_size=6),
    passing=st.lists(NON_BLANK, max_size=6),
)


# ---------------------------------------------------------------------------
# Strategies — runtime models (roadmap.models.runtime)
# ---------------------------------------------------------------------------

harness_run_strategy = st.builds(
    HarnessRun,
    model_id=NON_BLANK,
    revision=TEXT,
    metric_scores=st.dictionaries(keys=NON_BLANK, values=FINITE_FLOAT, max_size=5),
    license_compat=st.sampled_from(["compatible", "restricted", "prohibited"]),
    hardware=st.fixed_dictionaries({"gpu_class": NON_BLANK, "vram_gb": VRAM_GB}),
    excluded=st.booleans(),
    exclusion_category=st.one_of(st.none(), NON_BLANK),
    exclusion_reason=st.one_of(st.none(), TEXT),
)

emotion_features_strategy = st.builds(
    EmotionFeatures,
    label=st.one_of(
        st.none(),
        st.sampled_from(["neutral", "happy", "sad", "angry", "fear", "disgust", "surprise"]),
    ),
    confidence=CONFIDENCE,
    valence=OUT_OF_RANGE_VAD,
    arousal=OUT_OF_RANGE_VAD,
    dominance=OUT_OF_RANGE_VAD,
    extraction_ok=st.booleans(),
)

consent_record_strategy = st.builds(
    ConsentRecord,
    speaker_id=TEXT,
    permitted_use_scope=TEXT,
    timestamp=FINITE_FLOAT,
)

cloning_decision_strategy = st.builds(
    CloningDecision,
    allowed=st.booleans(),
    reason=TEXT,
    reference_retained=st.booleans(),
)

license_entry_strategy = st.builds(
    LicenseEntry,
    component_name=NON_BLANK,
    license_id=st.one_of(st.none(), NON_BLANK),
    constraints=st.lists(TEXT, max_size=4),
    intended_use_permitted=st.booleans(),
    recorded_before_use=st.booleans(),
    redistribution_restricted=st.booleans(),
    restriction_type=st.one_of(st.none(), NON_BLANK),
)

compliance_warning_strategy = st.builds(
    ComplianceWarning,
    component_name=NON_BLANK,
    resolved=st.booleans(),
)

normalization_result_strategy = st.builds(
    NormalizationResult,
    normalized_text=TEXT,
    unmapped_tokens=st.lists(TEXT, max_size=4),
)


# ---------------------------------------------------------------------------
# Strategies — Roadmap aggregate (roadmap.roadmap_model)
# ---------------------------------------------------------------------------

conflict_entry_strategy = st.builds(
    ConflictEntry,
    topic=NON_BLANK,
    superseding_decision=NON_BLANK,
    rationale=NON_BLANK,
    conflicting_document=st.one_of(st.just(""), NON_BLANK),
)

scope_statements_strategy = st.builds(
    ScopeStatements,
    authoritative_supersedes_pdfs=NON_BLANK,
    references_ai_training_docs=NON_BLANK,
    excludes_from_scratch_pretraining=NON_BLANK,
    excludes_gpu_training_execution=NON_BLANK,
    planning_artifact_only=NON_BLANK,
)


def _minimal_roadmap_phases() -> list[Phase]:
    """Fresh phase list for a minimal, valid baseline -> speech-native roadmap."""
    return [
        make_phase(ordinal=1, id=FIRST_PHASE_ID, is_speech_native=False),
        make_phase(
            ordinal=2,
            id="P2-speech-native",
            track="AMBITIOUS",
            title="Speech-native platform",
            is_speech_native=True,
        ),
    ]


@st.composite
def roadmap_strategy(draw: st.DrawFn) -> Roadmap:
    """Draw a valid :class:`Roadmap`: canonical or minimal phases plus extras.

    The phase list is one of two known-valid shapes (the canonical seven-phase
    plan or a minimal two-phase plan), decorated with optionally-empty gate,
    conflict, track-label, and scope-statement variations so the aggregate's
    nested collections are exercised by the round-trip.
    """
    phases = draw(
        st.sampled_from(["canonical", "minimal"]).map(
            lambda shape: make_valid_roadmap().phases
            if shape == "canonical"
            else _minimal_roadmap_phases()
        )
    )
    track_labels = draw(
        st.one_of(
            st.just({"LEAN": "primary", "AMBITIOUS": "optional"}),
            st.fixed_dictionaries({"LEAN": NON_BLANK, "AMBITIOUS": NON_BLANK}),
        )
    )
    return Roadmap(
        phases=phases,
        track_labels=track_labels,
        gates=draw(st.lists(gate_strategy, max_size=2)),
        conflicts=draw(st.lists(conflict_entry_strategy, max_size=2)),
        scope_statements=draw(
            st.one_of(st.builds(ScopeStatements.default), scope_statements_strategy)
        ),
    )


# ---------------------------------------------------------------------------
# Round-trip assertion helper
# ---------------------------------------------------------------------------


def _assert_roundtrips(instance: object) -> None:
    """Assert ``instance`` survives the dict, JSON, and YAML codecs unchanged."""
    cls = type(instance)
    assert from_dict(cls, to_dict(instance)) == instance
    assert loads_json(cls, dumps_json(instance)) == instance
    assert loads_yaml(cls, dumps_yaml(instance)) == instance


# ---------------------------------------------------------------------------
# Round-trip property tests (complementary invariant — NOT a numbered Property)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    instance=st.one_of(
        phase_strategy,
        gate_criterion_strategy,
        gate_strategy,
    )
)
def test_roundtrip_phase_models(instance: object) -> None:
    """Phase / GateCriterion / Gate survive dict + JSON + YAML round-trips.

    Validates: Requirements 1.1, 12.7.
    """
    _assert_roundtrips(instance)


@settings(max_examples=100)
@given(
    instance=st.one_of(
        criterion_result_strategy,
        gate_result_strategy,
        candidate_scores_strategy,
        selection_outcome_strategy,
    )
)
def test_roundtrip_selection_models(instance: object) -> None:
    """CriterionResult / GateResult / CandidateScores / SelectionOutcome round-trip.

    Validates: Requirements 1.1, 12.7.
    """
    _assert_roundtrips(instance)


@settings(max_examples=100)
@given(
    instance=st.one_of(
        harness_run_strategy,
        emotion_features_strategy,
        consent_record_strategy,
        cloning_decision_strategy,
        license_entry_strategy,
        compliance_warning_strategy,
        normalization_result_strategy,
    )
)
def test_roundtrip_runtime_models(instance: object) -> None:
    """Every runtime planning dataclass round-trips losslessly.

    Covers HarnessRun, EmotionFeatures (V/A/D clamped on construction),
    ConsentRecord, CloningDecision, LicenseEntry, ComplianceWarning, and
    NormalizationResult.

    Validates: Requirements 1.1, 12.7.
    """
    _assert_roundtrips(instance)


@settings(max_examples=100)
@given(roadmap=roadmap_strategy())
def test_roundtrip_roadmap_aggregate(roadmap: Roadmap) -> None:
    """The Roadmap aggregate (with phases, gates, conflicts, scope) round-trips.

    Validates: Requirements 1.1, 12.7.
    """
    _assert_roundtrips(roadmap)


# ---------------------------------------------------------------------------
# Explicit example: non-ASCII (Devanagari) text is preserved verbatim
# ---------------------------------------------------------------------------


def test_roundtrip_preserves_non_ascii_text() -> None:
    """Devanagari / non-ASCII field values survive all three codecs unchanged.

    Validates: Requirements 1.1, 12.7.
    """
    result = NormalizationResult(
        normalized_text="नमस्ते, आप कैसे हैं?",
        unmapped_tokens=["कैसे", "हैं"],
    )
    _assert_roundtrips(result)
