"""Property-based test for the Duplex_Manager barge-in decision logic.

This module implements the design's **Property 10: Barge-in suppression and
listening transition** for
:meth:`roadmap.duplex_manager.DuplexManager.decide_barge_in`.

Property 10 (design ``Correctness Properties``):

    For any turn in which at least 150 milliseconds of voiced user speech is
    detected while the platform is producing audio, the duplex manager schedules
    suppression of the current output within 200 milliseconds of detection and
    transitions the turn state to a listening state within 100 milliseconds of
    detection, regardless of the prior state including intermediate or
    processing states.

The decision rule under test (Requirements 7.4, 7.5):

- A barge-in fires **iff** ``voiced_speech_ms >= min_voiced_ms`` (150 ms) **and**
  ``current_state`` is barge-in eligible -- i.e. the platform is producing audio
  (``SPEAKING``) or in an intermediate/processing state (``THINKING``), which
  includes the case where it is already handling a prior interruption.
- When fired: output suppression is scheduled within 200 ms of detection, the
  turn transitions to ``LISTENING`` within 100 ms of detection, and the
  resulting state is ``LISTENING``.
- When not fired (``voiced_speech_ms < 150`` or the state is ``IDLE`` /
  ``LISTENING``): no barge-in, both deadlines are ``None``, and the resulting
  state is unchanged.

Generator design (covering the whole input space described by the task):

- ``voiced_speech_ms`` is drawn from a 0..several-hundred ms range with extra
  density right around the inclusive 150 ms boundary so both sides of the
  threshold are exercised.
- ``current_state`` is sampled from *all* :class:`TurnPhase` values so the
  eligible states (``SPEAKING``, ``THINKING``) and the non-eligible states
  (``IDLE``, ``LISTENING``) are all covered, satisfying the "regardless of the
  prior state including intermediate or processing states" clause.
- ``detection_time_ms`` is a non-negative float spanning a wide range so the
  absolute deadlines are checked against many detection offsets.

Validates: Requirements 7.4, 7.5.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.duplex_manager import (
    BARGE_IN_ELIGIBLE_STATES,
    DEFAULT_DUPLEX_CONFIG,
    DuplexManager,
    TurnPhase,
)

#: Budgets mandated by the design/requirements (150 / 200 / 100 ms).
_MIN_VOICED_MS = DEFAULT_DUPLEX_CONFIG.min_voiced_ms
_SUPPRESSION_MS = DEFAULT_DUPLEX_CONFIG.suppression_deadline_ms
_LISTENING_MS = DEFAULT_DUPLEX_CONFIG.listening_transition_deadline_ms


def _voiced_speech_ms() -> st.SearchStrategy[float]:
    """Voiced-speech durations spanning the 150 ms threshold (ms, >= 0)."""
    return st.one_of(
        # Broad sweep across the plausible range.
        st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False),
        # Extra density right around the inclusive 150 ms boundary.
        st.floats(min_value=148.0, max_value=152.0, allow_nan=False, allow_infinity=False),
    )


def _detection_time_ms() -> st.SearchStrategy[float]:
    """Non-negative detection timestamps (ms) across a wide range."""
    return st.floats(
        min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
    )


# Feature: speech-native-voice-roadmap, Property 10: Barge-in suppression and listening transition
@settings(max_examples=100)
@given(
    voiced_speech_ms=_voiced_speech_ms(),
    current_state=st.sampled_from(list(TurnPhase)),
    detection_time_ms=_detection_time_ms(),
)
def test_property_10_barge_in_suppression_and_listening_transition(
    voiced_speech_ms: float,
    current_state: TurnPhase,
    detection_time_ms: float,
) -> None:
    """Property 10: barge-in suppression and listening transition deadlines.

    Validates: Requirements 7.4, 7.5.
    """
    manager = DuplexManager()

    decision = manager.decide_barge_in(
        voiced_speech_ms=voiced_speech_ms,
        current_state=current_state,
        detection_time_ms=detection_time_ms,
    )

    # The decision echoes back its inputs faithfully.
    assert decision.detection_time_ms == detection_time_ms
    assert decision.voiced_speech_ms == voiced_speech_ms
    assert decision.from_state == current_state

    voiced_enough = voiced_speech_ms >= _MIN_VOICED_MS
    eligible = current_state in BARGE_IN_ELIGIBLE_STATES

    if voiced_enough and eligible:
        # Req 7.4/7.5: a barge-in fires from any eligible state (SPEAKING or
        # THINKING -- producing audio or processing, including while already
        # handling a prior interruption).
        assert decision.barge_in_triggered is True

        # Req 7.4: output suppression is scheduled within 200 ms of detection.
        assert decision.suppression_deadline_ms is not None
        assert decision.suppression_deadline_ms <= detection_time_ms + _SUPPRESSION_MS
        # And not before detection.
        assert decision.suppression_deadline_ms >= detection_time_ms

        # Req 7.5: the turn reaches LISTENING within 100 ms of detection.
        assert decision.listening_transition_deadline_ms is not None
        assert (
            decision.listening_transition_deadline_ms
            <= detection_time_ms + _LISTENING_MS
        )
        assert decision.listening_transition_deadline_ms >= detection_time_ms

        # Req 7.5: the resulting state is the listening state.
        assert decision.resulting_state == TurnPhase.LISTENING
    else:
        # No barge-in: either not enough voiced speech, or the state is not
        # producing audio / processing (IDLE or LISTENING).
        assert decision.barge_in_triggered is False
        assert decision.suppression_deadline_ms is None
        assert decision.listening_transition_deadline_ms is None
        # The state is left unchanged when no barge-in fires.
        assert decision.resulting_state == current_state
