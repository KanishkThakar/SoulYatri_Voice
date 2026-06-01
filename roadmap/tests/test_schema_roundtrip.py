"""Property-based schema-conformance tests for serialized planning objects.

This module exercises a *complementary* invariant tying the two halves of the
roadmap's persistence layer together: for every schema'd planning object ``x``,
the plain dict produced by :func:`roadmap.serialization.to_dict` must satisfy
the JSON Schema mapped to ``x``'s type, i.e.::

    validate(to_dict(x), schema_name_for(x))  # does not raise

This is intentionally **not** one of the 15 numbered design correctness
properties — it is a broad, generative cross-check that the generic
``to_dict`` encoder and the per-model JSON Schemas under ``roadmap/schemas/``
agree on field names, types, enums, and numeric bounds. It is therefore not
tagged with the ``Property {n}`` comment marker, so the Task 39
property-coverage report continues to find exactly Properties 1-15.

Generation reuse
----------------
The valid-instance strategies are imported wholesale from
``test_serialization_roundtrip`` (Task 27.2) rather than re-derived. Those
strategies already construct each dataclass through its real constructor and
constrain inputs to the schema-valid input space:

- ``confidence`` is drawn from ``[0, 1]`` (the ``emotion_features`` bound),
- valence/arousal/dominance are clamped to ``[-1, 1]`` by ``EmotionFeatures``
  on construction, so ``to_dict(x)`` values always satisfy the V/A/D bounds,
- gate / criterion ``operator`` values come from the five-member enum,
- ``track`` / ``kind`` / ``license_compat`` come from their respective enums.

Only the eleven *schema'd* models are generated here (``schema_name_for`` is
mapped for exactly these): Phase, Gate, GateResult, CandidateScores,
SelectionOutcome, HarnessRun, EmotionFeatures, ConsentRecord, LicenseEntry,
NormalizationResult, and the Roadmap aggregate. Models without a mapped schema
(GateCriterion, CriterionResult, CloningDecision, ComplianceWarning) are
deliberately excluded.

Validates: Requirements 1.4, 2.3.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.schema import schema_name_for, validate
from roadmap.serialization import to_dict
from roadmap.tests.test_serialization_roundtrip import (
    candidate_scores_strategy,
    consent_record_strategy,
    emotion_features_strategy,
    gate_result_strategy,
    gate_strategy,
    harness_run_strategy,
    license_entry_strategy,
    normalization_result_strategy,
    phase_strategy,
    roadmap_strategy,
    selection_outcome_strategy,
)

#: The eleven schema'd planning models, each paired with a strategy that yields
#: valid, schema-conformant instances (see module docstring for the constraints
#: each strategy already enforces). ``schema_name_for`` is mapped for exactly
#: these eleven types; models without a schema are intentionally omitted.
SCHEMA_D_MODEL_STRATEGY = st.one_of(
    phase_strategy,
    gate_strategy,
    gate_result_strategy,
    candidate_scores_strategy,
    selection_outcome_strategy,
    harness_run_strategy,
    emotion_features_strategy,
    consent_record_strategy,
    license_entry_strategy,
    normalization_result_strategy,
    roadmap_strategy(),
)


@settings(max_examples=100)
@given(instance=SCHEMA_D_MODEL_STRATEGY)
def test_serialized_model_satisfies_its_schema(instance: object) -> None:
    """``validate(to_dict(x), schema_name_for(x))`` passes for every schema'd model.

    For each generated valid instance of a schema'd planning model, serializing
    it with :func:`to_dict` and validating the resulting dict against the schema
    mapped to its type must not raise :class:`SchemaValidationError`.

    Validates: Requirements 1.4, 2.3.
    """
    validate(to_dict(instance), schema_name_for(instance))
