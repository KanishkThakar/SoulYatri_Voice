"""Tests for the speculative onset controller (Phase 8B)."""

from __future__ import annotations

from edge.planner.short_turn import ShortTurnClassifier
from edge.planner.speculation import (
    SpeculationController,
    SpeculationMode,
    SpeculationStatus,
    SpeculativePlan,
)
from shared.contracts import RouteDecision, RouteTarget


class FakeClock:
    def __init__(self, start: int = 0) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


def ctrl(clock=None) -> SpeculationController:
    return SpeculationController(min_confidence=0.6, clock=clock or FakeClock(0))


clf = ShortTurnClassifier()


def test_no_speculation_for_uncertain_turn():
    res = clf.classify("garbled audio", asr_confidence=0.1)
    plan = ctrl().decide(res)
    assert plan.mode == SpeculationMode.none


def test_filler_speculation_for_trivial():
    res = clf.classify("hello", asr_confidence=0.95)
    plan = ctrl().decide(res)
    assert plan.mode == SpeculationMode.filler
    assert plan.is_safe is True


def test_empathetic_filler_for_emotional():
    res = clf.classify("i feel so sad", asr_confidence=0.9)
    plan = ctrl().decide(res)
    assert plan.mode == SpeculationMode.empathetic_filler


def test_short_answer_for_short_turn():
    res = clf.classify("what time is it", asr_confidence=0.9)
    plan = ctrl().decide(res)
    assert plan.mode == SpeculationMode.short_answer


def test_start_then_commit_marks_committed():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)
    plan = c.start(c.decide(res))
    assert plan is not None and plan.status == SpeculationStatus.started
    committed = c.commit()
    assert committed is not None
    assert committed.status == SpeculationStatus.committed
    assert c.active is None
    assert c.metrics.committed == 1


def test_cancel_marks_cancelled_and_recoverable():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)
    c.start(c.decide(res))
    cancelled = c.cancel("user_barge_in")
    assert cancelled is not None
    assert cancelled.status == SpeculationStatus.cancelled
    assert cancelled.reason == "user_barge_in"
    assert c.active is None
    assert c.metrics.cancelled == 1
    # Recoverable: a fresh speculation can start after cancellation.
    plan2 = c.start(c.decide(res))
    assert plan2 is not None


def test_cannot_start_two_speculations_at_once():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)
    assert c.start(c.decide(res)) is not None
    # Second start while one is active is rejected.
    assert c.start(c.decide(res)) is None


def test_cancel_is_idempotent():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)
    c.start(c.decide(res))
    assert c.cancel() is not None
    assert c.cancel() is None  # nothing active to cancel.


def test_reconcile_commits_on_compatible_route():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)  # filler speculation
    c.start(c.decide(res))
    final = RouteDecision(route=RouteTarget.cached_filler, intent="greeting", confidence=0.9)
    resolved = c.reconcile(final)
    assert resolved is not None
    assert resolved.status == SpeculationStatus.committed


def test_reconcile_cancels_on_conflicting_route():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)  # filler speculation
    c.start(c.decide(res))
    # Final decision says stay silent → any spoken onset conflicts.
    final = RouteDecision(route=RouteTarget.silent_wait, intent="wait", confidence=0.9)
    resolved = c.reconcile(final)
    assert resolved is not None
    assert resolved.status == SpeculationStatus.cancelled


def test_short_answer_conflicts_with_complex_final():
    c = ctrl()
    res = clf.classify("what time is it", asr_confidence=0.9)  # short_answer
    c.start(c.decide(res))
    final = RouteDecision(route=RouteTarget.full_stack, intent="complex", confidence=0.9)
    resolved = c.reconcile(final)
    assert resolved is not None
    assert resolved.status == SpeculationStatus.cancelled


def test_wrong_rate_metric_tracks_cancellations():
    c = ctrl()
    res = clf.classify("hello", asr_confidence=0.95)
    # 3 started, 1 cancelled → wrong_rate ~ 0.33.
    c.start(c.decide(res))
    c.commit()
    c.start(c.decide(res))
    c.commit()
    c.start(c.decide(res))
    c.cancel()
    assert c.metrics.started == 3
    assert c.metrics.cancelled == 1
    assert round(c.metrics.wrong_rate, 2) == 0.33


def test_cannot_start_unsafe_or_none_mode():
    c = ctrl()
    assert c.start(SpeculativePlan(mode=SpeculationMode.none)) is None


def test_timing_recorded_with_clock():
    clock = FakeClock(100)
    c = ctrl(clock)
    res = clf.classify("hello", asr_confidence=0.95)
    plan = c.start(c.decide(res))
    assert plan.started_ms == 100
    clock.advance(50)
    committed = c.commit()
    assert committed.resolved_ms == 150
