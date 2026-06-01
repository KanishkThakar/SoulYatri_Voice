"""Unit tests for serialization edge cases across the JSON and YAML codecs.

These plain-pytest example tests complement the property-based round-trip
suite by pinning down concrete edge cases the design calls out:

- **YAML <-> JSON equivalence** — the two string codecs are two encodings of
  the same plain :func:`~roadmap.serialization.to_dict` shape, so for a given
  instance both decode back to an equal object and both decode to the same
  intermediate mapping.
- **Unknown-key rejection** — :func:`~roadmap.serialization.from_dict` fails
  loudly (with the offending key named) instead of silently dropping data.
- **Optional / None handling** — ``HarnessRun`` exclusion fields
  (``excluded`` / ``exclusion_category`` / ``exclusion_reason``) and
  ``LicenseEntry.license_id`` / ``restriction_type`` round-trip whether they
  are ``None`` or populated, and an omitted optional field falls back to its
  dataclass default.
- **Float preservation** — ``metric_scores`` floats survive both codecs by
  exact ``==`` comparison.

Validates: Requirements 4.3, 11.2
"""

from __future__ import annotations

import json

import pytest
import yaml

from roadmap.models.runtime import HarnessRun, LicenseEntry
from roadmap.models.selection import CriterionResult, GateResult
from roadmap.serialization import (
    SerializationError,
    dumps_json,
    dumps_yaml,
    from_dict,
    loads_json,
    loads_yaml,
    to_dict,
)


# ---------------------------------------------------------------------------
# Sample instances reused across the equivalence tests.
# ---------------------------------------------------------------------------
def _sample_harness_run() -> HarnessRun:
    return HarnessRun(
        model_id="kyutai/moshiko-pytorch-bf16",
        revision="abc123",
        metric_scores={
            "latency_ms_p50": 180.0,
            "codeswitch_quality": 0.82,
            "expressiveness": 3.5,
        },
        license_compat="compatible",
        hardware={"gpu_class": "A100", "vram_gb": 80.0},
    )


def _sample_license_entry() -> LicenseEntry:
    return LicenseEntry(
        component_name="ai4bharat/IndicF5",
        license_id="Apache-2.0",
        constraints=["attribution"],
        intended_use_permitted=True,
        recorded_before_use=True,
        redistribution_restricted=True,
        restriction_type="consent_required",
    )


def _sample_gate_result() -> GateResult:
    return GateResult(
        gate_id="Decision_Gate_1",
        criteria_results=[
            CriterionResult(
                metric_name="latency_ms_p50",
                measured=180.0,
                threshold=300.0,
                operator="<=",
                passed=True,
            ),
            CriterionResult(
                metric_name="codeswitch_quality",
                measured=0.82,
                threshold=0.7,
                operator=">=",
                passed=True,
            ),
        ],
        overall_passed=True,
        blocked=False,
        remediation=[],
    )


_SAMPLES = [
    pytest.param(HarnessRun, _sample_harness_run(), id="HarnessRun"),
    pytest.param(LicenseEntry, _sample_license_entry(), id="LicenseEntry"),
    pytest.param(GateResult, _sample_gate_result(), id="GateResult"),
]


# ---------------------------------------------------------------------------
# YAML <-> JSON equivalence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cls, instance", _SAMPLES)
def test_json_and_yaml_decode_to_equal_object(cls, instance):
    """Both string codecs decode back to an object equal to the original."""
    via_json = loads_json(cls, dumps_json(instance))
    via_yaml = loads_yaml(cls, dumps_yaml(instance))

    assert via_json == instance
    assert via_yaml == instance
    assert via_json == via_yaml


@pytest.mark.parametrize("cls, instance", _SAMPLES)
def test_json_and_yaml_share_intermediate_mapping(cls, instance):
    """Decoding the JSON/YAML text yields the same plain mapping as ``to_dict``."""
    expected = to_dict(instance)
    from_json_text = json.loads(dumps_json(instance))
    from_yaml_text = yaml.safe_load(dumps_yaml(instance))

    assert from_json_text == from_yaml_text
    assert from_json_text == expected


# ---------------------------------------------------------------------------
# Unknown-key rejection
# ---------------------------------------------------------------------------
def test_from_dict_rejects_unknown_key_on_harness_run():
    """An extra key fails loudly and the error names the offending key."""
    payload = to_dict(_sample_harness_run())
    payload["bogus_key"] = 1

    with pytest.raises(SerializationError) as excinfo:
        from_dict(HarnessRun, payload)

    message = str(excinfo.value)
    assert "bogus_key" in message
    assert "HarnessRun" in message


def test_from_dict_rejects_unknown_key_on_license_entry():
    """Unknown-key rejection also holds for a second dataclass."""
    payload = to_dict(_sample_license_entry())
    payload["not_a_field"] = "x"

    with pytest.raises(SerializationError) as excinfo:
        from_dict(LicenseEntry, payload)

    assert "not_a_field" in str(excinfo.value)


def test_from_dict_rejects_non_mapping_payload():
    """A non-mapping payload for a dataclass target is rejected."""
    with pytest.raises(SerializationError):
        from_dict(HarnessRun, ["not", "a", "mapping"])


# ---------------------------------------------------------------------------
# Optional / None handling — HarnessRun exclusion fields
# ---------------------------------------------------------------------------
def test_harness_run_none_exclusion_fields_round_trip():
    """``excluded=False`` with ``None`` exclusion fields preserves the Nones."""
    run = _sample_harness_run()
    assert run.excluded is False
    assert run.exclusion_category is None
    assert run.exclusion_reason is None

    encoded = to_dict(run)
    # to_dict emits the Nones explicitly (they become ``null`` in JSON/YAML).
    assert encoded["exclusion_category"] is None
    assert encoded["exclusion_reason"] is None

    restored = loads_yaml(HarnessRun, dumps_yaml(run))
    assert restored == run
    assert restored.exclusion_category is None
    assert restored.exclusion_reason is None


def test_harness_run_populated_exclusion_fields_round_trip():
    """A populated exclusion record round-trips through both codecs."""
    run = HarnessRun(
        model_id="some/excluded-model",
        revision="rev9",
        metric_scores={
            "latency_ms_p50": 0.0,
            "codeswitch_quality": 0.0,
            "expressiveness": 0.0,
        },
        license_compat="prohibited",
        hardware={"gpu_class": "none", "vram_gb": 0.0},
        excluded=True,
        exclusion_category="license",
        exclusion_reason="license prohibits intended use",
    )

    assert loads_json(HarnessRun, dumps_json(run)) == run
    assert loads_yaml(HarnessRun, dumps_yaml(run)) == run


def test_harness_run_omitted_optional_field_uses_default():
    """Omitting an optional field loads using the dataclass default (None)."""
    payload = to_dict(_sample_harness_run())
    del payload["exclusion_category"]

    restored = from_dict(HarnessRun, payload)
    assert restored.exclusion_category is None


# ---------------------------------------------------------------------------
# Optional / None handling — LicenseEntry.license_id and restriction_type
# ---------------------------------------------------------------------------
def test_license_entry_license_id_none_round_trips():
    """A failed recording (``license_id=None``) keeps ``None`` after round-trip."""
    entry = LicenseEntry(
        component_name="some/unknown-dataset",
        license_id=None,
        constraints=[],
        intended_use_permitted=True,
        recorded_before_use=False,
    )
    assert entry.license_id is None
    assert entry.restriction_type is None

    encoded = to_dict(entry)
    assert encoded["license_id"] is None
    assert encoded["restriction_type"] is None

    assert loads_json(LicenseEntry, dumps_json(entry)) == entry
    assert loads_yaml(LicenseEntry, dumps_yaml(entry)) == entry


def test_license_entry_license_id_set_round_trips():
    """A populated ``license_id`` and ``restriction_type`` round-trip intact."""
    entry = _sample_license_entry()
    assert entry.license_id == "Apache-2.0"
    assert entry.restriction_type == "consent_required"

    assert loads_json(LicenseEntry, dumps_json(entry)) == entry
    assert loads_yaml(LicenseEntry, dumps_yaml(entry)) == entry


def test_license_entry_restriction_type_none_vs_set():
    """``restriction_type`` round-trips both as ``None`` and when populated."""
    unrestricted = LicenseEntry(
        component_name="comp",
        license_id="MIT",
        constraints=[],
        intended_use_permitted=True,
        recorded_before_use=True,
        redistribution_restricted=False,
        restriction_type=None,
    )
    restricted = LicenseEntry(
        component_name="comp",
        license_id="MIT",
        constraints=[],
        intended_use_permitted=True,
        recorded_before_use=True,
        redistribution_restricted=True,
        restriction_type="redistribution_restricted",
    )

    assert loads_yaml(LicenseEntry, dumps_yaml(unrestricted)) == unrestricted
    assert loads_yaml(LicenseEntry, dumps_yaml(restricted)) == restricted
    assert unrestricted != restricted


# ---------------------------------------------------------------------------
# Float preservation
# ---------------------------------------------------------------------------
def test_metric_score_float_survives_both_codecs_exactly():
    """A ``0.1`` metric score survives JSON and YAML round-trips by exact ==."""
    run = HarnessRun(
        model_id="m",
        revision="r",
        metric_scores={
            "latency_ms_p50": 0.1,
            "codeswitch_quality": 0.3,
            "expressiveness": 1.0,
        },
        license_compat="compatible",
        hardware={"gpu_class": "T4", "vram_gb": 16.0},
    )

    via_json = loads_json(HarnessRun, dumps_json(run))
    via_yaml = loads_yaml(HarnessRun, dumps_yaml(run))

    assert via_json.metric_scores["latency_ms_p50"] == 0.1
    assert via_yaml.metric_scores["latency_ms_p50"] == 0.1
    assert isinstance(via_json.metric_scores["latency_ms_p50"], float)
    assert isinstance(via_yaml.metric_scores["latency_ms_p50"], float)
    assert via_json.metric_scores == run.metric_scores
    assert via_yaml.metric_scores == run.metric_scores
