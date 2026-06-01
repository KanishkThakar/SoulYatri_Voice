"""Unit tests for the dependency-free schema validator (``roadmap/schema.py``).

These plain-pytest example tests pin down the concrete validation behaviour the
design and requirements call out:

- **Valid documents pass.** For several planning models (``Phase``,
  ``EmotionFeatures``, ``Gate``, ``HarnessRun``, ``ConsentRecord``, and the full
  ``Roadmap`` aggregate) a canonical instance, serialized via
  :func:`roadmap.serialization.to_dict`, validates against the schema named by
  :func:`roadmap.schema.schema_name_for` without raising.
- **A missing required field fails** with the missing field named in the error
  (e.g. dropping ``ordinal`` from a phase, or ``speaker_id`` from a consent
  record).
- **An out-of-range V/A/D fails** (Requirement 6.1): an ``emotion_features``
  document with ``valence`` outside ``[-1.0, 1.0]`` is rejected with an error
  that mentions the violated bound.
- **A bad comparison operator fails** (Requirement 1.4): a gate (or gate-result
  criterion) ``operator`` outside ``{<=, <, >=, >, ==}`` is rejected with an
  error about the operator enum.
- **The selection-weight key set** is enforced exactly by
  :func:`roadmap.schema.validate_selection_weights`.
- **Multiple violations are collected at once** — a document with several
  problems yields a ``SchemaValidationError`` whose ``errors`` list has more
  than one entry.

Validates: Requirements 1.4, 6.1
"""

from __future__ import annotations

import pytest

from roadmap.models.runtime import ConsentRecord, EmotionFeatures, HarnessRun
from roadmap.models.selection import SELECTION_WEIGHTS, CriterionResult, GateResult
from roadmap.schema import (
    SchemaValidationError,
    schema_name_for,
    validate,
    validate_selection_weights,
)
from roadmap.serialization import to_dict
from roadmap.tests.fixtures import (
    make_gate,
    make_phase,
    make_valid_roadmap,
)


# ---------------------------------------------------------------------------
# Builders for valid sample documents.
# ---------------------------------------------------------------------------
def _valid_emotion_features() -> EmotionFeatures:
    """A valid, in-range ``EmotionFeatures`` instance (V/A/D within [-1, 1])."""
    return EmotionFeatures(
        label="happy",
        confidence=0.8,
        valence=0.5,
        arousal=-0.25,
        dominance=0.0,
        extraction_ok=True,
    )


def _valid_harness_run() -> HarnessRun:
    """A valid, non-excluded ``HarnessRun`` record."""
    return HarnessRun(
        model_id="kyutai/moshiko-pytorch-bf16",
        revision="bf16",
        metric_scores={
            "latency_ms_p50": 180.0,
            "codeswitch_quality": 82.0,
            "expressiveness": 3.5,
        },
        license_compat="compatible",
        hardware={"gpu_class": "L4", "vram_gb": 24.0},
    )


def _valid_consent_record() -> ConsentRecord:
    """A valid (all three fields present) ``ConsentRecord``."""
    return ConsentRecord(
        speaker_id="speaker-001",
        permitted_use_scope="voice-style-transfer",
        timestamp=1_700_000_000.0,
    )


def _valid_gate_result() -> GateResult:
    """A valid ``GateResult`` carrying one passing criterion result."""
    return GateResult(
        gate_id="LEAN-DEMO",
        criteria_results=[
            CriterionResult(
                metric_name="latency_ms_p50",
                measured=180.0,
                threshold=300.0,
                operator="<=",
                passed=True,
            )
        ],
        overall_passed=True,
        blocked=False,
        remediation=[],
    )


# Each entry: (id, instance) — used to assert valid documents validate cleanly.
_VALID_SAMPLES = [
    pytest.param(make_phase(), id="Phase"),
    pytest.param(_valid_emotion_features(), id="EmotionFeatures"),
    pytest.param(make_gate(), id="Gate"),
    pytest.param(_valid_harness_run(), id="HarnessRun"),
    pytest.param(_valid_consent_record(), id="ConsentRecord"),
    pytest.param(_valid_gate_result(), id="GateResult"),
    pytest.param(make_valid_roadmap(), id="Roadmap"),
]


# ---------------------------------------------------------------------------
# Valid documents pass.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("instance", _VALID_SAMPLES)
def test_valid_document_passes(instance):
    """A canonical instance serialized via ``to_dict`` validates cleanly."""
    document = to_dict(instance)
    schema_name = schema_name_for(instance)

    # ``validate`` returns None and must not raise for a valid document.
    assert validate(document, schema_name) is None


def test_full_roadmap_with_nested_phases_and_gates_passes():
    """The full ``Roadmap`` aggregate (nested phases + gates) validates."""
    roadmap = make_valid_roadmap()
    # Attach a gate so the nested gate/criterion subschemas are exercised too.
    roadmap.gates.append(make_gate())

    document = to_dict(roadmap)
    assert validate(document, "roadmap") is None


# ---------------------------------------------------------------------------
# A missing required field fails with the field named.
# ---------------------------------------------------------------------------
def test_missing_required_field_on_phase_fails():
    """Dropping the required ``ordinal`` key fails and names the field."""
    document = to_dict(make_phase())
    del document["ordinal"]

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "phase")

    error = excinfo.value
    assert error.schema_name == "phase"
    assert any("ordinal" in message for message in error.errors)


def test_missing_required_field_on_consent_record_fails():
    """Dropping the required ``speaker_id`` key fails and names the field."""
    document = to_dict(_valid_consent_record())
    del document["speaker_id"]

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "consent_record")

    error = excinfo.value
    assert any("speaker_id" in message for message in error.errors)
    # The descriptive message also calls out that it was a *required* field.
    assert any("required" in message for message in error.errors)


# ---------------------------------------------------------------------------
# An out-of-range V/A/D fails (Requirement 6.1).
# ---------------------------------------------------------------------------
def test_out_of_range_valence_above_maximum_fails():
    """A valence above the +1.0 bound is rejected, mentioning the maximum."""
    # Build the dict by hand so the dataclass clamping does not mask the value.
    document = to_dict(_valid_emotion_features())
    document["valence"] = 1.5

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "emotion_features")

    error = excinfo.value
    assert error.schema_name == "emotion_features"
    assert any("valence" in message for message in error.errors)
    assert any(
        "maximum" in message or "above" in message for message in error.errors
    )


def test_out_of_range_dominance_below_minimum_fails():
    """A dominance below the -1.0 bound is rejected, mentioning the minimum."""
    document = to_dict(_valid_emotion_features())
    document["dominance"] = -2.0

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "emotion_features")

    error = excinfo.value
    assert any("dominance" in message for message in error.errors)
    assert any(
        "minimum" in message or "below" in message for message in error.errors
    )


# ---------------------------------------------------------------------------
# A bad comparison operator fails (Requirement 1.4).
# ---------------------------------------------------------------------------
def test_bad_operator_on_gate_criterion_fails():
    """A gate exit-criterion operator of '!=' is rejected via the enum."""
    document = to_dict(make_gate())
    document["exit_criteria"][0]["operator"] = "!="

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "gate")

    error = excinfo.value
    assert error.schema_name == "gate"
    assert any("operator" in message for message in error.errors)
    # The descriptive message names the offending value and the enum location.
    assert any("'!='" in message or "!=" in message for message in error.errors)


def test_bad_operator_on_gate_result_criterion_fails():
    """A gate-result criterion operator outside the enum is rejected."""
    document = to_dict(_valid_gate_result())
    document["criteria_results"][0]["operator"] = "=<"

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "gate_result")

    error = excinfo.value
    assert any("operator" in message for message in error.errors)


# ---------------------------------------------------------------------------
# Selection-weight key-set enforcement.
# ---------------------------------------------------------------------------
def test_validate_selection_weights_accepts_canonical_keys():
    """The canonical six-key ``SELECTION_WEIGHTS`` map validates cleanly."""
    assert validate_selection_weights(dict(SELECTION_WEIGHTS)) is None


def test_validate_selection_weights_reports_missing_and_extra_keys():
    """A wrong key set names both the missing and the unexpected keys."""
    weights = dict(SELECTION_WEIGHTS)
    del weights["full_duplex"]  # drop a required key
    weights["bogus_criterion"] = 10  # add an unexpected key

    with pytest.raises(SchemaValidationError) as excinfo:
        validate_selection_weights(weights)

    error = excinfo.value
    assert error.schema_name == "selection_weights"
    assert any("full_duplex" in message for message in error.errors)
    assert any("bogus_criterion" in message for message in error.errors)


# ---------------------------------------------------------------------------
# Multiple violations are collected at once.
# ---------------------------------------------------------------------------
def test_validate_collects_multiple_violations():
    """Several simultaneous problems are all reported in ``errors``."""
    document = to_dict(make_phase())
    del document["ordinal"]  # missing required field
    del document["title"]  # a second missing required field
    document["track"] = "SIDEWAYS"  # value not in the track enum

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "phase")

    error = excinfo.value
    assert len(error.errors) > 1
    assert any("ordinal" in message for message in error.errors)
    assert any("title" in message for message in error.errors)
    assert any("track" in message or "SIDEWAYS" in message for message in error.errors)


def test_emotion_features_multiple_out_of_range_collected():
    """All three out-of-range V/A/D dimensions are reported together."""
    document = to_dict(_valid_emotion_features())
    document["valence"] = 2.0
    document["arousal"] = -3.0
    document["dominance"] = 5.0

    with pytest.raises(SchemaValidationError) as excinfo:
        validate(document, "emotion_features")

    error = excinfo.value
    assert len(error.errors) >= 3
    assert any("valence" in message for message in error.errors)
    assert any("arousal" in message for message in error.errors)
    assert any("dominance" in message for message in error.errors)
