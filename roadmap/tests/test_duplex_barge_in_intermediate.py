"""Unit tests for barge-in from an intermediate/processing state (Req 7.5).

Plain ``pytest`` example tests for
:meth:`roadmap.duplex_manager.DuplexManager.decide_barge_in` and its stateful
wrapper :meth:`roadmap.duplex_manager.DuplexManager.on_voiced_speech`.

They pin the part of Requirement 7.5 that the property test (Task 17.2) covers
across all inputs, but here as focused, human-readable examples for the
*intermediate* case:

    WHEN a barge-in is detected, THE Duplex_Manager SHALL transition the turn
    state to a listening state within 100 milliseconds, **including when the
    SoulYatri_Platform is already processing a prior interruption or is in an
    intermediate state**, so that the new user utterance is captured.

The manager models the intermediate/processing state as
:attr:`TurnPhase.THINKING`. With the design-mandated budgets
(min_voiced_ms=150, suppression_deadline_ms=200,
listening_transition_deadline_ms=100), a barge-in from ``THINKING`` with at
least 150 ms of voiced speech must:

- trigger (``barge_in_triggered`` is ``True``),
- resolve to ``resulting_state == LISTENING``,
- schedule the listening transition at ``detection_time_ms + 100`` (within the
  100 ms budget), and
- schedule output suppression at ``detection_time_ms + 200``.

For contrast we confirm the same holds from the active ``SPEAKING`` state, that
a sub-threshold (``< 150 ms``) utterance from ``THINKING`` does **not** trigger,
and that the stateful wrapper actually moves the manager into ``LISTENING``.

Requirements: 7.5
"""

from __future__ import annotations

import pytest

from roadmap.duplex_manager import (
    DEFAULT_DUPLEX_CONFIG,
    BargeInDecision,
    DuplexManager,
    TurnPhase,
)

# A non-zero detection timestamp so the absolute deadline arithmetic
# (detection + budget) is exercised meaningfully rather than starting at 0.
DETECTION_MS = 1_000.0


@pytest.fixture
def manager() -> DuplexManager:
    """A manager using the design-mandated 150/200/100 ms budgets."""
    return DuplexManager()


def _assert_reaches_listening_within_budget(
    decision: BargeInDecision, *, from_state: TurnPhase, detection_ms: float
) -> None:
    """Assert a triggered barge-in reaches LISTENING within the 100 ms budget."""
    budget = DEFAULT_DUPLEX_CONFIG.listening_transition_deadline_ms
    suppression = DEFAULT_DUPLEX_CONFIG.suppression_deadline_ms

    assert decision.barge_in_triggered is True
    assert decision.from_state is from_state
    assert decision.resulting_state is TurnPhase.LISTENING
    # Reaches LISTENING within the 100 ms budget (exact scheduled deadline).
    assert decision.listening_transition_deadline_ms == detection_ms + budget
    assert (
        decision.listening_transition_deadline_ms - detection_ms <= budget
    )
    # Output suppression scheduled within the 200 ms budget.
    assert decision.suppression_deadline_ms == detection_ms + suppression


def test_barge_in_from_thinking_reaches_listening_within_budget(
    manager: DuplexManager,
) -> None:
    """>=150 ms voiced speech from THINKING reaches LISTENING within 100 ms.

    This is the core Requirement 7.5 assertion for the intermediate state: a
    barge-in raised while the platform is processing must transition to
    LISTENING within the 100 ms budget and schedule suppression within 200 ms.
    """
    decision = manager.decide_barge_in(
        voiced_speech_ms=150.0,
        current_state=TurnPhase.THINKING,
        detection_time_ms=DETECTION_MS,
    )
    _assert_reaches_listening_within_budget(
        decision, from_state=TurnPhase.THINKING, detection_ms=DETECTION_MS
    )


def test_barge_in_from_speaking_reaches_listening_within_budget(
    manager: DuplexManager,
) -> None:
    """For contrast: the same holds from the active SPEAKING state."""
    decision = manager.decide_barge_in(
        voiced_speech_ms=150.0,
        current_state=TurnPhase.SPEAKING,
        detection_time_ms=DETECTION_MS,
    )
    _assert_reaches_listening_within_budget(
        decision, from_state=TurnPhase.SPEAKING, detection_ms=DETECTION_MS
    )


def test_thinking_barge_in_via_wrapper_transitions_state_to_listening(
    manager: DuplexManager,
) -> None:
    """The stateful wrapper moves a THINKING manager into LISTENING.

    ``on_voiced_speech`` is the thin stateful wrapper around
    ``decide_barge_in``; when a barge-in fires from THINKING it must apply the
    resulting state, leaving the manager in LISTENING.
    """
    manager.set_state(TurnPhase.THINKING)
    assert manager.state is TurnPhase.THINKING

    decision = manager.on_voiced_speech(150.0, detection_time_ms=DETECTION_MS)

    assert decision.barge_in_triggered is True
    assert decision.resulting_state is TurnPhase.LISTENING
    # The manager's own state was advanced to LISTENING by the wrapper.
    assert manager.state is TurnPhase.LISTENING


def test_thinking_while_handling_prior_interruption_still_reaches_listening(
    manager: DuplexManager,
) -> None:
    """Already in THINKING from a prior interruption: a new barge-in still wins.

    Requirement 7.5 calls out the case where the platform "is already
    processing a prior interruption". We simulate that by leaving the manager
    in THINKING and raising a fresh barge-in at a later detection time; it must
    still reach LISTENING within the 100 ms budget.
    """
    manager.set_state(TurnPhase.THINKING)
    later_detection_ms = DETECTION_MS + 500.0

    decision = manager.on_voiced_speech(
        200.0, detection_time_ms=later_detection_ms
    )

    _assert_reaches_listening_within_budget(
        decision, from_state=TurnPhase.THINKING, detection_ms=later_detection_ms
    )
    assert manager.state is TurnPhase.LISTENING


def test_subthreshold_voiced_speech_from_thinking_does_not_trigger(
    manager: DuplexManager,
) -> None:
    """<150 ms voiced speech from THINKING does NOT trigger a barge-in.

    The state stays THINKING and both deadlines are ``None`` because no
    barge-in was raised.
    """
    decision = manager.decide_barge_in(
        voiced_speech_ms=149.0,
        current_state=TurnPhase.THINKING,
        detection_time_ms=DETECTION_MS,
    )

    assert decision.barge_in_triggered is False
    assert decision.resulting_state is TurnPhase.THINKING
    assert decision.suppression_deadline_ms is None
    assert decision.listening_transition_deadline_ms is None


def test_subthreshold_via_wrapper_leaves_manager_in_thinking(
    manager: DuplexManager,
) -> None:
    """The wrapper leaves the manager in THINKING when no barge-in fires."""
    manager.set_state(TurnPhase.THINKING)

    decision = manager.on_voiced_speech(149.0, detection_time_ms=DETECTION_MS)

    assert decision.barge_in_triggered is False
    # No state change applied by the wrapper.
    assert manager.state is TurnPhase.THINKING
