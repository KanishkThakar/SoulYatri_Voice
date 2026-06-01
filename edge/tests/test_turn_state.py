"""Tests for the explicit edge turn-state machine (Phase 4B).

Covers valid transitions, explicit rejection of invalid transitions, the
valid-or-explicit-rejection totality rule, event emission, turn counting, and timeouts
with a deterministic injectable clock.
"""

from __future__ import annotations

import pytest

from edge.session.turn_state import (
    STATE_TIMEOUTS_MS,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    TransitionRejected,
    TurnStateMachine,
)
from shared.contracts import TurnEvent, TurnState


class FakeClock:
    """Deterministic millisecond clock for timeout tests."""

    def __init__(self, start: int = 0) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


def drive_to_speaking(m: TurnStateMachine) -> None:
    """Walk the machine through a full happy-path turn up to SPEAKING."""
    m.transition(TurnState.listening, "speech_start")
    m.transition(TurnState.buffering, "speech_end")
    m.transition(TurnState.candidate_filler, "turn_confirmed")
    m.transition(TurnState.forwarding, "pipeline_needed")
    m.transition(TurnState.thinking, "pipeline_start")
    m.transition(TurnState.speaking, "response_ready")


def test_initial_state_is_idle():
    m = TurnStateMachine("s1")
    assert m.state == TurnState.idle
    assert m.previous_state is None
    assert m.turn_id == 0


def test_happy_path_transitions_emit_events():
    m = TurnStateMachine("s1")
    drive_to_speaking(m)
    assert m.state == TurnState.speaking
    # Each transition emits exactly one TurnEvent.
    assert len(m.events) == 6
    assert all(isinstance(e, TurnEvent) for e in m.events)
    # Turn counter incremented once when leaving idle → listening.
    assert m.turn_id == 1
    # The last event ends at speaking.
    assert m.events[-1].to_state == TurnState.speaking
    assert m.events[0].from_state == TurnState.idle


def test_turn_event_uses_shared_contract_fields():
    m = TurnStateMachine("sess-42")
    event = m.transition(TurnState.listening, "speech_start", metadata={"src": "vad"})
    assert isinstance(event, TurnEvent)
    assert event.session_id == "sess-42"
    assert event.from_state == TurnState.idle
    assert event.to_state == TurnState.listening
    assert event.trigger == "speech_start"
    assert event.metadata == {"src": "vad"}
    assert isinstance(event.ts_ms, int)
    # Round-trips through pydantic (wire-compatible).
    assert TurnEvent.model_validate(event.model_dump()) == event


def test_invalid_transition_raises():
    m = TurnStateMachine("s1")
    with pytest.raises(InvalidTransitionError) as exc:
        m.transition(TurnState.speaking, "illegal")
    assert exc.value.rejection.from_state == TurnState.idle
    assert exc.value.rejection.attempted_state == TurnState.speaking
    # State is unchanged after a rejected transition.
    assert m.state == TurnState.idle


def test_try_transition_returns_explicit_rejection_not_exception():
    m = TurnStateMachine("s1")
    result = m.try_transition(TurnState.speaking, "illegal")
    assert isinstance(result, TransitionRejected)
    assert result.reason == "transition_not_allowed"
    assert m.state == TurnState.idle
    # Rejection is recorded for audit.
    assert len(m.rejections) == 1


def test_every_event_is_valid_transition_or_explicit_rejection():
    """Totality rule: from any state, every target yields TurnEvent OR TransitionRejected."""
    for from_state in TurnState:
        for to_state in TurnState:
            m = TurnStateMachine("s1", clock=FakeClock(0))
            m._state = from_state  # position the machine (test-only).
            result = m.try_transition(to_state, "probe")
            if to_state in VALID_TRANSITIONS.get(from_state, set()):
                assert isinstance(result, TurnEvent)
            else:
                assert isinstance(result, TransitionRejected)


def test_barge_in_path_from_speaking():
    m = TurnStateMachine("s1")
    drive_to_speaking(m)
    ev = m.on_speech_start()  # speaking + speech → barge_in
    assert isinstance(ev, TurnEvent)
    assert m.state == TurnState.barge_in
    m.on_repair_start()
    assert m.state == TurnState.repairing
    m.on_repair_done()
    assert m.state == TurnState.listening


def test_speech_resume_from_buffering():
    m = TurnStateMachine("s1")
    m.transition(TurnState.listening, "speech_start")
    m.transition(TurnState.buffering, "speech_end")
    ev = m.on_speech_start()  # buffering + speech → listening (false end)
    assert isinstance(ev, TurnEvent)
    assert ev.trigger == "speech_resume"
    assert m.state == TurnState.listening


def test_ended_is_terminal():
    m = TurnStateMachine("s1")
    m.on_session_end()
    assert m.state == TurnState.ended
    # No transitions allowed out of ended.
    for to_state in TurnState:
        assert isinstance(m.try_transition(to_state, "probe"), TransitionRejected)


def test_transition_callback_fires():
    seen: list[TurnEvent] = []
    m = TurnStateMachine("s1", on_transition=seen.append)
    m.transition(TurnState.listening, "speech_start")
    assert len(seen) == 1
    assert seen[0].to_state == TurnState.listening


def test_rejection_callback_fires():
    rejected: list[TransitionRejected] = []
    m = TurnStateMachine("s1", on_rejection=rejected.append)
    m.try_transition(TurnState.speaking, "illegal")
    assert len(rejected) == 1
    assert rejected[0].attempted_state == TurnState.speaking


def test_timeout_triggers_recovery_with_fake_clock():
    clock = FakeClock(0)
    m = TurnStateMachine("s1", clock=clock)
    m.transition(TurnState.listening, "speech_start")
    m.transition(TurnState.buffering, "speech_end")
    assert m.state == TurnState.buffering
    # Not timed out yet.
    clock.advance(STATE_TIMEOUTS_MS[TurnState.buffering] - 1)
    assert m.check_timeout() is None
    assert m.state == TurnState.buffering
    # Cross the timeout boundary → fail safe to idle.
    clock.advance(2)
    ev = m.check_timeout()
    assert isinstance(ev, TurnEvent)
    assert ev.trigger == "timeout"
    assert m.state == TurnState.idle


def test_barge_in_timeout_recovers_to_repairing():
    clock = FakeClock(0)
    m = TurnStateMachine("s1", clock=clock)
    drive_to_speaking(m)
    m.on_speech_start()  # → barge_in
    assert m.state == TurnState.barge_in
    clock.advance(STATE_TIMEOUTS_MS[TurnState.barge_in] + 1)
    ev = m.check_timeout()
    assert isinstance(ev, TurnEvent)
    assert m.state == TurnState.repairing


def test_idle_has_no_timeout():
    m = TurnStateMachine("s1", clock=FakeClock(0))
    assert m.timeout_ms() is None
    assert m.is_timed_out(now=10**9) is False
    assert m.check_timeout(now=10**9) is None


def test_multiple_turns_increment_turn_id():
    m = TurnStateMachine("s1")
    # Turn 1
    m.transition(TurnState.listening, "speech_start")
    m.transition(TurnState.idle, "error_recovery")
    # Turn 2
    m.transition(TurnState.listening, "speech_start")
    assert m.turn_id == 2
