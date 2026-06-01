"""Property-based tests for the Licensing Register (Requirement 11).

This module implements the single correctness property for the
:class:`~roadmap.licensing.LicensingRegister` decision logic as specified in
``design.md`` ("Correctness Properties" — Property 15). The register is pure
in-memory decision logic, so the property runs without any GPU/training work.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.licensing import RECOGNIZED_OSS_LICENSES, LicensingRegister

# A small, non-blank alphabet for component names and restriction types so the
# generated values are always valid (the register rejects empty/blank input)
# while still exercising a wide range of distinct identifiers.
_NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"

# Non-blank text usable as a component name or restriction type.
_non_blank_text = st.text(alphabet=_NAME_ALPHABET, min_size=1, max_size=24)

# A recognized OSS license identifier (the "recording succeeds" branch).
_recognized_license = st.sampled_from(sorted(RECOGNIZED_OSS_LICENSES))

# An identifier the register does NOT recognize, plus ``None`` (the "recording
# fails" branch). Any non-empty string outside the allow-list, or ``None``.
_unrecognized_license = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=16).filter(lambda s: s not in RECOGNIZED_OSS_LICENSES),
)

# The license id for one component: a mix of recognized ids and
# unrecognized/None values so both recording outcomes are covered.
_license_choice = st.one_of(_recognized_license, _unrecognized_license)

# Zero or more free-form constraint strings (commercial-use/attribution notes).
_constraints = st.lists(st.text(max_size=12), max_size=4)


@st.composite
def _component_spec(draw: st.DrawFn) -> dict:
    """Generate one component's recording plan.

    Produces a license id (recognized / unrecognized / ``None``), constraints,
    and an optional redistribution restriction (with an optional later
    "satisfy" step) so the dataset-flagging branch is exercised too. When the
    initial license id is unrecognized/``None``, an optional later re-recording
    with a recognized id exercises the warning-resolution clause of 11.3.
    """
    flagged = draw(st.booleans())
    license_id = draw(_license_choice)
    initially_recognized = license_id in RECOGNIZED_OSS_LICENSES
    # Only an initially-failed recording can be "fixed" by re-recording; pick a
    # recognized id to record on the second pass.
    re_record_license = (
        draw(_recognized_license) if (not initially_recognized and draw(st.booleans())) else None
    )
    return {
        "license_id": license_id,
        "constraints": draw(_constraints),
        "flagged": flagged,
        "restriction_type": draw(_non_blank_text) if flagged else None,
        "satisfy": draw(st.booleans()) if flagged else False,
        "re_record_license": re_record_license,
    }


@st.composite
def _register_plan(draw: st.DrawFn) -> dict:
    """Generate a mapping of unique component names to their recording plans.

    Using a dict keyed by name guarantees unique component names, matching the
    register's "latest recording wins" semantics without ambiguity.
    """
    names = draw(st.lists(_non_blank_text, max_size=8, unique=True))
    return {name: draw(_component_spec()) for name in names}


# Feature: speech-native-voice-roadmap, Property 15: Licensing register and redistribution exclusion
# Validates: Requirements 11.1, 11.2, 11.3, 11.6, 11.8
@settings(max_examples=100)
@given(plan=_register_plan())
def test_property_15_licensing_register_and_redistribution_exclusion(plan: dict) -> None:
    """Recording, warning retention, restriction flagging, and redistribution.

    For any set of adopted components:

    * Recording with a recognized OSS id stores the entry before use with that
      id and leaves NO unresolved warning for it (11.1, 11.2).
    * Recording with ``None`` / an unrecognized id still stores the entry
      (adoption proceeds) with ``license_id is None`` AND retains an unresolved
      ``ComplianceWarning`` for that component (11.2, 11.3).
    * Re-recording a previously-failed component with a recognized id resolves
      its outstanding warning (11.3).
    * A dataset flagged with a restriction type records that exact type and
      makes ``redistribution_allowed`` ``False``; satisfying the restriction
      flips it back to ``True`` (11.6, 11.8).
    * A never-recorded component is allowed to redistribute (11.8).

    **Validates: Requirements 11.1, 11.2, 11.3, 11.6, 11.8**
    """
    register = LicensingRegister()

    # Apply the generated plan to a fresh register.
    for name, spec in plan.items():
        register.record_component(name, spec["license_id"], spec["constraints"])
        # A previously-failed recording can be fixed by re-recording with a
        # recognized id, which must resolve the retained warning (11.3). Do this
        # before flagging so the restriction below applies to the final entry
        # (re-recording stores a fresh entry with no redistribution flag).
        if spec["re_record_license"] is not None:
            register.record_component(
                name, spec["re_record_license"], spec["constraints"]
            )
        if spec["flagged"]:
            register.flag_dataset(name, spec["restriction_type"])
            if spec["satisfy"]:
                register.satisfy_restriction(name)

    unresolved_names = {w.component_name for w in register.unresolved_warnings()}

    for name, spec in plan.items():
        entry = register.get_entry(name)

        # 11.2: every adopted component is recorded before use.
        assert entry is not None
        assert entry.recorded_before_use is True

        fixed = spec["re_record_license"] is not None
        recognized = spec["license_id"] in RECOGNIZED_OSS_LICENSES
        if recognized:
            # 11.1: recognized id is stored verbatim; recording succeeded so no
            # unresolved warning is retained for this component.
            assert entry.license_id == spec["license_id"]
            assert name not in unresolved_names
        elif fixed:
            # 11.3 (resolution): an initially-failed recording that was later
            # re-recorded with a recognized id stores that id and clears the
            # previously-retained unresolved warning.
            assert entry.license_id == spec["re_record_license"]
            assert name not in unresolved_names
        else:
            # 11.3: recording failed -> adoption proceeds with license_id None
            # and an unresolved compliance warning is retained for the name.
            assert entry.license_id is None
            assert name in unresolved_names

        if spec["flagged"]:
            # 11.6: the specific restriction type is recorded on the entry.
            assert entry.restriction_type == spec["restriction_type"]
            if spec["satisfy"]:
                # 11.8: once satisfied, redistribution is allowed again.
                assert register.redistribution_allowed(name) is True
                assert entry.redistribution_restricted is False
            else:
                # 11.8: while flagged, redistribution is blocked.
                assert register.redistribution_allowed(name) is False
                assert entry.redistribution_restricted is True
        else:
            # Never restricted -> redistribution allowed.
            assert register.redistribution_allowed(name) is True

    # 11.8: an unknown (never-recorded) component has no recorded restriction
    # and is therefore allowed to redistribute.
    unknown = "unrecorded-component"
    while unknown in plan:
        unknown += "x"
    assert register.redistribution_allowed(unknown) is True
