"""Property-based test for the latency-only fallback discrimination.

This module holds the Hypothesis property test for
**Property 11: Latency-only fallback discrimination** (task 18.2) covering
:meth:`roadmap.duplex_manager.DuplexManager.decide_latency_fallback`.

Property 11 (design "Correctness Properties")
---------------------------------------------
*For any* turn outcome, the platform completes the turn using the
Phase_1_Pipeline (or a TTS_Fallback when Phase 1 is unavailable) **if and only
if** the Speech-Native Core fails to emit its first audible response token
within the 300 millisecond budget; non-latency core failure types alone do not
trigger this latency fallback.

Concretely, for any ``first_token_latency_ms`` (``None`` or a float ``>= 0``),
any :class:`CoreFailureType`, and any ``phase_1_available`` boolean, the
fallback fires iff a first-response latency-budget violation occurred — i.e.:

    first_token_latency_ms is None
    OR first_token_latency_ms > budget (300 ms)
    OR core_failure_type in LATENCY_FAILURE_TYPES

A non-latency failure type alone (with a first token emitted within budget)
does **not** trigger the fallback. When triggered the target is
``PHASE_1_PIPELINE`` if Phase 1 is available else ``TTS_FALLBACK``; when not
triggered the target is ``NONE``.

Validates: Requirements 3.5
"""

from __future__ import annotations

from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.duplex_manager import (
    LATENCY_FAILURE_TYPES,
    NON_LATENCY_FAILURE_TYPES,
    CoreFailureType,
    DuplexManager,
    FallbackTarget,
)

# The first-response latency budget the manager applies (design / Req 3.5).
_BUDGET_MS: float = 300.0

# All CoreFailureType members, used to sweep the entire failure space.
_ALL_FAILURE_TYPES: tuple[CoreFailureType, ...] = tuple(CoreFailureType)


def _latency() -> st.SearchStrategy[Optional[float]]:
    """First-token latency: ``None`` or a float in ``0..600`` ms.

    The ``0..600`` range spans the ``300 ms`` budget boundary on both sides
    (well below, exactly at, just above, and well above), and ``None`` models a
    core that emitted no first audible token within the observation window.
    """
    return st.one_of(
        st.none(),
        st.floats(
            min_value=0.0,
            max_value=600.0,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


def _expected_latency_violation(
    first_token_latency_ms: Optional[float],
    core_failure_type: CoreFailureType,
) -> bool:
    """Independently recompute the latency-budget violation from Req 3.5.

    Derived from the requirement/design wording, NOT from the implementation:
    a violation occurs iff no first token was emitted (``None``), or the
    reported failure type is a latency failure, or the emitted first token
    landed strictly after the budget.
    """
    if core_failure_type in LATENCY_FAILURE_TYPES:
        return True
    if first_token_latency_ms is None:
        return True
    return first_token_latency_ms > _BUDGET_MS


# Feature: speech-native-voice-roadmap, Property 11: Latency-only fallback discrimination
@settings(max_examples=100)
@given(
    first_token_latency_ms=_latency(),
    core_failure_type=st.sampled_from(_ALL_FAILURE_TYPES),
    phase_1_available=st.booleans(),
)
def test_property_11_latency_only_fallback_discrimination(
    first_token_latency_ms: Optional[float],
    core_failure_type: CoreFailureType,
    phase_1_available: bool,
) -> None:
    """Property 11: Latency-only fallback discrimination.

    Validates: Requirements 3.5
    """
    manager = DuplexManager()
    decision = manager.decide_latency_fallback(
        first_token_latency_ms=first_token_latency_ms,
        core_failure_type=core_failure_type,
        phase_1_available=phase_1_available,
    )

    # --- The fallback fires IFF a first-response latency-budget violation. ---
    expected_violation = _expected_latency_violation(
        first_token_latency_ms, core_failure_type
    )
    assert decision.fallback_triggered is expected_violation

    # The reported cause (`latency_violation`) equals the action
    # (`fallback_triggered`): the fallback is driven purely by latency.
    assert decision.latency_violation == decision.fallback_triggered

    # --- CRITICAL discrimination: a NON-latency failure type alone, with a ---
    # first token emitted within budget, must NOT trigger the fallback.
    non_latency_within_budget = (
        core_failure_type in NON_LATENCY_FAILURE_TYPES
        and first_token_latency_ms is not None
        and first_token_latency_ms <= _BUDGET_MS
    )
    if non_latency_within_budget:
        assert decision.fallback_triggered is False
        assert decision.fallback_target == FallbackTarget.NONE

    # --- Target selection follows triggering and Phase 1 availability. -------
    if decision.fallback_triggered:
        expected_target = (
            FallbackTarget.PHASE_1_PIPELINE
            if phase_1_available
            else FallbackTarget.TTS_FALLBACK
        )
        assert decision.fallback_target == expected_target
    else:
        assert decision.fallback_target == FallbackTarget.NONE

    # --- The decision echoes its inputs and the applied budget faithfully. ---
    assert decision.first_token_latency_ms == first_token_latency_ms
    assert decision.core_failure_type == core_failure_type
    assert decision.phase_1_available == phase_1_available
    assert decision.budget_ms == _BUDGET_MS


# Feature: speech-native-voice-roadmap, Property 11: Latency-only fallback discrimination
@settings(max_examples=100)
@given(
    core_failure_type=st.sampled_from(tuple(NON_LATENCY_FAILURE_TYPES)),
    first_token_latency_ms=st.floats(
        min_value=0.0,
        max_value=_BUDGET_MS,
        allow_nan=False,
        allow_infinity=False,
    ),
    phase_1_available=st.booleans(),
)
def test_property_11_non_latency_failure_within_budget_never_falls_back(
    core_failure_type: CoreFailureType,
    first_token_latency_ms: float,
    phase_1_available: bool,
) -> None:
    """A non-latency failure with an in-budget first token never falls back.

    This isolates the discrimination half of Property 11 across every
    non-latency failure type (exception / refusal / codec / unknown): when a
    first audible token was emitted within the 300 ms budget, a non-latency
    failure alone must not trigger the latency fallback.

    Validates: Requirements 3.5
    """
    manager = DuplexManager()
    decision = manager.decide_latency_fallback(
        first_token_latency_ms=first_token_latency_ms,
        core_failure_type=core_failure_type,
        phase_1_available=phase_1_available,
    )

    assert decision.fallback_triggered is False
    assert decision.latency_violation is False
    assert decision.fallback_target == FallbackTarget.NONE
