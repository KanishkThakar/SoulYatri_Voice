"""Tests for ``BudgetComputePlanner.select_scope`` (Requirement 9.5).

Requirement 9.5 states:

    IF the available compute is below the minimum required for a phase, OR the
    available compute is zero, OR compute-availability data is invalid or
    missing, THEN THE Roadmap SHALL specify, for that phase, a reduced-scope
    alternative whose stated compute footprint (GPU class and VRAM in GB) does
    not exceed the compute confirmed to be available.

This module pins that behaviour for ``select_scope`` across the full spectrum of
availability inputs:

- **sufficient**   (``avail >= phase minimum``)  -> full scope, phase footprint
- **insufficient** (``0 < avail < phase minimum``) -> reduced scope, footprint
  capped at the confirmed-available compute
- **zero / negative / None / non-numeric / NaN / inf / bool** (invalid or
  missing) -> confirmed-available resolves to ``0.0`` and the footprint is the
  no-GPU (``CPU`` / 0 GB) reduced-scope alternative

The KEY universal invariant verified for *every* input is:

    result.footprint.vram_gb <= result.confirmed_available_vram_gb
    and result.footprint_within_available is True

The invariant is checked both as parametrized example tests and as a Hypothesis
property (a complementary invariant — not one of the 15 numbered design
properties).

Requirements: 9.5
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.budget_planner import BudgetComputePlanner, ComputeFootprint, ScopePlan
from roadmap.models.phases import Phase


# --- Fixtures / phases under test -----------------------------------------

#: Three phases with known, distinct compute footprints (24 / 40 / 80 GB VRAM).
PHASES: tuple[Phase, ...] = (
    Phase(
        ordinal=1,
        id="P-24",
        track="LEAN",
        title="Phase needing 24 GB",
        is_speech_native=True,
        guide_sections=["Guide: 24GB phase"],
        compute_min_gpu_class="L4-24GB",
        compute_min_vram_gb=24.0,
    ),
    Phase(
        ordinal=2,
        id="P-40",
        track="AMBITIOUS",
        title="Phase needing 40 GB",
        is_speech_native=True,
        guide_sections=["Guide: 40GB phase"],
        compute_min_gpu_class="A100-40GB",
        compute_min_vram_gb=40.0,
    ),
    Phase(
        ordinal=3,
        id="P-80",
        track="AMBITIOUS",
        title="Phase needing 80 GB",
        is_speech_native=True,
        guide_sections=["Guide: 80GB phase"],
        compute_min_gpu_class="H100-80GB",
        compute_min_vram_gb=80.0,
    ),
)

#: The set of inputs that must all resolve to a confirmed-available 0.0 GB and a
#: no-GPU reduced-scope footprint (invalid / missing / zero / negative).
INVALID_OR_MISSING_INPUTS: tuple[object, ...] = (
    None,
    0,
    0.0,
    -1,
    -0.5,
    -1000.0,
    "not-a-number",
    "24",  # numeric-looking string is still non-numeric
    "",
    float("nan"),
    float("inf"),
    float("-inf"),
    True,  # booleans are not a valid VRAM measurement
    False,
    {"vram_gb": None},
    {"vram_gb": -3.0},
    {"vram_gb": "oops"},
    {},  # mapping without a vram_gb key
)


@pytest.fixture
def planner() -> BudgetComputePlanner:
    """A planner that knows about all three footprint phases."""

    return BudgetComputePlanner(phases=PHASES)


def _assert_key_invariant(result: ScopePlan) -> None:
    """The Requirement 9.5 invariant: footprint never exceeds confirmed-available."""

    assert result.footprint.vram_gb <= result.confirmed_available_vram_gb
    assert result.footprint_within_available is True
    # confirmed-available is always a non-negative, finite number.
    assert result.confirmed_available_vram_gb >= 0.0
    assert math.isfinite(result.confirmed_available_vram_gb)


# --- Example (unit) tests --------------------------------------------------


@pytest.mark.parametrize("phase", PHASES, ids=lambda p: p.id)
def test_sufficient_compute_returns_full_scope(
    planner: BudgetComputePlanner, phase: Phase
) -> None:
    """Availability >= phase minimum -> full scope using the phase footprint."""

    available = phase.compute_min_vram_gb + 8.0
    result = planner.select_scope(phase, available)

    assert result.scope == "full"
    assert result.footprint.gpu_class == phase.compute_min_gpu_class
    assert result.footprint.vram_gb == phase.compute_min_vram_gb
    assert result.confirmed_available_vram_gb == pytest.approx(available)
    _assert_key_invariant(result)


@pytest.mark.parametrize("phase", PHASES, ids=lambda p: p.id)
def test_availability_exactly_at_minimum_is_full_scope(
    planner: BudgetComputePlanner, phase: Phase
) -> None:
    """Availability exactly at the phase minimum is sufficient (inclusive)."""

    result = planner.select_scope(phase, phase.compute_min_vram_gb)

    assert result.scope == "full"
    assert result.footprint.vram_gb == phase.compute_min_vram_gb
    _assert_key_invariant(result)


@pytest.mark.parametrize("phase", PHASES, ids=lambda p: p.id)
def test_insufficient_compute_returns_reduced_scope(
    planner: BudgetComputePlanner, phase: Phase
) -> None:
    """0 < availability < phase minimum -> reduced scope capped at availability."""

    available = phase.compute_min_vram_gb - 1.0  # strictly below the minimum
    result = planner.select_scope(phase, available)

    assert result.scope == "reduced"
    assert result.is_reduced is True
    assert result.confirmed_available_vram_gb == pytest.approx(available)
    # Footprint fits within the confirmed-available compute (the key invariant).
    assert result.footprint.vram_gb <= available
    _assert_key_invariant(result)


@pytest.mark.parametrize("phase", PHASES, ids=lambda p: p.id)
@pytest.mark.parametrize(
    "bad_input",
    INVALID_OR_MISSING_INPUTS,
    ids=lambda v: repr(v),
)
def test_invalid_zero_or_missing_compute_returns_cpu_reduced_scope(
    planner: BudgetComputePlanner, phase: Phase, bad_input: object
) -> None:
    """Zero / negative / None / non-numeric / NaN / inf all resolve to 0.0 GB.

    For every such input the planner must (a) confirm 0.0 GB available, (b)
    return a reduced-scope plan, and (c) return a no-GPU (CPU / 0 GB) footprint
    that does not exceed the confirmed-available compute.
    """

    result = planner.select_scope(phase, bad_input)

    assert result.scope == "reduced"
    assert result.confirmed_available_vram_gb == 0.0
    assert result.footprint.gpu_class == "CPU"
    assert result.footprint.vram_gb == 0.0
    _assert_key_invariant(result)


def test_reduced_footprint_fits_real_gpu_rung(
    planner: BudgetComputePlanner,
) -> None:
    """A reduced plan with room for a real GPU picks a fitting ladder rung."""

    # Phase needs 80 GB; only 30 GB confirmed -> reduced, fitting <= 30 GB.
    result = planner.select_scope("P-80", 30.0)

    assert result.scope == "reduced"
    assert result.confirmed_available_vram_gb == pytest.approx(30.0)
    assert result.footprint.vram_gb <= 30.0
    _assert_key_invariant(result)


def test_compute_footprint_input_form_is_accepted(
    planner: BudgetComputePlanner,
) -> None:
    """``available_compute`` may also be a ComputeFootprint carrying VRAM."""

    result = planner.select_scope("P-24", ComputeFootprint(gpu_class="L4-24GB", vram_gb=24.0))

    assert result.scope == "full"
    assert result.confirmed_available_vram_gb == pytest.approx(24.0)
    _assert_key_invariant(result)


# --- Property-based test (complementary invariant) -------------------------
#
# Feature: speech-native-voice-roadmap, Property: select_scope footprint never exceeds available compute
#
# NOTE: This is a complementary invariant for Requirement 9.5, NOT one of the
# 15 numbered design Properties, so it is deliberately NOT tagged with a
# numbered "# Feature: ..., Property N:" marker the Property-coverage scanner
# (Task 39) expects. The descriptive (non-numbered) tag above is intentional.


@st.composite
def scope_cases(draw):
    """Draw ``(phase, available_compute, kind)`` across the whole input space.

    ``kind`` classifies the input so the property can assert the right
    scope/footprint outcome in addition to the universal invariant.
    """

    phase = draw(st.sampled_from(PHASES))
    phase_min = phase.compute_min_vram_gb
    kind = draw(
        st.sampled_from(
            [
                "sufficient",
                "insufficient",
                "zero",
                "negative",
                "none",
                "string",
                "nan",
                "inf",
                "bool",
            ]
        )
    )

    if kind == "sufficient":
        value = draw(
            st.floats(
                min_value=phase_min,
                max_value=1.0e6,
                allow_nan=False,
                allow_infinity=False,
            )
        )
    elif kind == "insufficient":
        value = draw(
            st.floats(
                min_value=1.0e-6,
                max_value=phase_min,
                exclude_max=True,
                allow_nan=False,
                allow_infinity=False,
            )
        )
    elif kind == "zero":
        value = draw(st.sampled_from([0, 0.0, -0.0]))
    elif kind == "negative":
        value = draw(
            st.floats(
                min_value=-1.0e6,
                max_value=-1.0e-6,
                allow_nan=False,
                allow_infinity=False,
            )
        )
    elif kind == "none":
        value = None
    elif kind == "string":
        value = draw(st.text(max_size=8))
    elif kind == "nan":
        value = float("nan")
    elif kind == "inf":
        value = draw(st.sampled_from([float("inf"), float("-inf")]))
    else:  # bool
        value = draw(st.booleans())

    return phase, value, kind


@settings(max_examples=100)
@given(case=scope_cases())
def test_property_footprint_never_exceeds_confirmed_available(case) -> None:
    """For ANY availability input, the footprint never exceeds confirmed-available.

    This is the key Requirement 9.5 invariant. The test also checks the
    scope/footprint classification implied by each input category.

    Validates: Requirements 9.5
    """

    phase, value, kind = case
    planner = BudgetComputePlanner(phases=PHASES)
    result = planner.select_scope(phase, value)

    # --- KEY universal invariant (holds for every single input) -----------
    assert result.footprint.vram_gb <= result.confirmed_available_vram_gb
    assert result.footprint_within_available is True
    assert result.confirmed_available_vram_gb >= 0.0
    assert math.isfinite(result.confirmed_available_vram_gb)
    assert result.phase_id == phase.id

    if kind == "sufficient":
        # >= phase minimum -> full scope, exact phase footprint preserved.
        assert result.scope == "full"
        assert result.footprint.gpu_class == phase.compute_min_gpu_class
        assert result.footprint.vram_gb == phase.compute_min_vram_gb
        assert result.confirmed_available_vram_gb == pytest.approx(float(value))
    elif kind == "insufficient":
        # 0 < avail < minimum -> reduced scope fitting the confirmed-available.
        assert result.scope == "reduced"
        assert result.confirmed_available_vram_gb == pytest.approx(float(value))
        assert result.footprint.vram_gb <= result.confirmed_available_vram_gb
    else:
        # zero / negative / none / string / nan / inf / bool are all invalid or
        # missing -> 0.0 confirmed and a no-GPU reduced-scope footprint.
        assert result.scope == "reduced"
        assert result.confirmed_available_vram_gb == 0.0
        assert result.footprint.gpu_class == "CPU"
        assert result.footprint.vram_gb == 0.0
