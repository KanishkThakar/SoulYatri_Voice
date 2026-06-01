"""Tests for barge-in detection (Phase 4C): timing + bounded false positives."""

from __future__ import annotations

from edge.barge_in.detector import BargeInDetector, BargeInEvent


class FakeClock:
    def __init__(self, start: int = 0) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


def make_detector(clock: FakeClock, **kw) -> BargeInDetector:
    return BargeInDetector(
        frame_ms=30,
        min_speech_duration_ms=200,  # → 6 frames at 30ms
        cooldown_ms=500,
        threshold=0.5,
        clock=clock,
        **kw,
    )


def feed_speech_frames(det: BargeInDetector, clock: FakeClock, n: int, prob: float = 0.9):
    events = []
    for _ in range(n):
        ev = det.check("s1", prob)
        if ev is not None:
            events.append(ev)
        clock.advance(30)
    return events


def test_no_detection_when_agent_not_speaking():
    clock = FakeClock(0)
    det = make_detector(clock)
    events = feed_speech_frames(det, clock, 20, prob=0.99)
    assert events == []
    assert det.metrics.detections == 0


def test_barge_in_fires_after_min_consecutive_frames():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    # 5 frames < 6 required → no detection.
    assert feed_speech_frames(det, clock, 5, prob=0.9) == []
    # The 6th consecutive speech frame triggers.
    ev = det.check("s1", 0.9)
    assert isinstance(ev, BargeInEvent)
    assert ev.cancel is True and ev.repair is True
    assert det.metrics.detections == 1


def test_detection_latency_is_measured():
    clock = FakeClock(1000)
    det = make_detector(clock)
    det.set_agent_speaking(True, now=1000)
    # 6 consecutive frames; onset at first speech frame.
    ev = None
    for i in range(6):
        ev = det.check("s1", 0.9)
        if i < 5:
            clock.advance(30)
    assert isinstance(ev, BargeInEvent)
    # onset at t=1000, confirmed at t=1000+5*30=1150 → latency 150ms.
    assert ev.detection_latency_ms == 150
    assert ev.time_since_agent_started_ms == 150


def test_isolated_noise_does_not_trigger_false_positive():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    # Alternate speech/silence: the hysteresis decay keeps the run below threshold.
    for _ in range(40):
        det.check("s1", 0.9)
        clock.advance(30)
        det.check("s1", 0.0)
        clock.advance(30)
    assert det.metrics.detections == 0
    assert det.metrics.false_positive_rate == 0.0


def test_cooldown_prevents_rapid_double_detection():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    # First detection.
    feed_speech_frames(det, clock, 5, prob=0.9)
    ev1 = det.check("s1", 0.9)
    assert isinstance(ev1, BargeInEvent)
    # Immediately feed more speech within the cooldown window → suppressed.
    suppressed = feed_speech_frames(det, clock, 6, prob=0.9)
    assert suppressed == []
    assert det.metrics.detections == 1


def test_detection_after_cooldown_elapsed():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    feed_speech_frames(det, clock, 5, prob=0.9)
    assert isinstance(det.check("s1", 0.9), BargeInEvent)
    # Wait out the cooldown.
    clock.advance(600)
    second = feed_speech_frames(det, clock, 6, prob=0.9)
    assert len(second) == 1
    assert det.metrics.detections == 2


def test_set_agent_speaking_false_resets_run():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    feed_speech_frames(det, clock, 5, prob=0.9)  # build a partial run
    det.set_agent_speaking(False)
    det.set_agent_speaking(True)
    # Run was reset; a single frame must not immediately fire.
    assert det.check("s1", 0.9) is None


def test_false_positive_rate_bound_under_clean_input():
    """With clean alternating noise the FP rate must stay at 0 (bounded)."""
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    for _ in range(100):
        det.check("s1", 0.3)  # below threshold = silence
        clock.advance(30)
    assert det.metrics.detections == 0
    assert det.metrics.false_positive_rate <= 0.05


def test_mark_false_positive_updates_metrics():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    feed_speech_frames(det, clock, 5, prob=0.9)
    assert isinstance(det.check("s1", 0.9), BargeInEvent)
    det.mark_false_positive()
    assert det.metrics.false_positive_candidates == 1
    assert det.metrics.false_positive_rate == 1.0  # 1 fp / 1 detection


def test_metrics_to_dict_serializable():
    clock = FakeClock(0)
    det = make_detector(clock)
    det.set_agent_speaking(True)
    feed_speech_frames(det, clock, 6, prob=0.9)
    d = det.metrics.to_dict()
    assert set(d) >= {"frames_seen", "speech_frames", "detections", "false_positive_rate"}
    assert d["detections"] >= 1
