"""Tests for the onset/handoff policy (Phase 8C): smooth onset, no double responses."""

from __future__ import annotations

from edge.planner.handoff import (
    HandoffController,
    HandoffKind,
    OnsetState,
    _strip_leading_duplicate,
)


def test_direct_main_when_no_filler():
    h = HandoffController()
    action = h.handoff_to_main("here is your answer")
    assert action.kind == HandoffKind.play_main
    assert action.text == "here is your answer"
    assert h.state == OnsetState.main_playing


def test_filler_then_main_stops_filler():
    h = HandoffController()
    start = h.begin_filler("okay")
    assert start.kind == HandoffKind.start_filler
    action = h.handoff_to_main("okay, here's what I found", filler_done=True)
    assert action.kind == HandoffKind.stop_filler
    # Leading "okay" duplicated by filler is removed.
    assert action.text == "here's what I found"


def test_filler_then_main_crossfade_when_filler_not_done():
    h = HandoffController()
    h.begin_filler("hmm")
    action = h.handoff_to_main("hmm let me check that for you", filler_done=False)
    assert action.kind == HandoffKind.crossfade
    assert action.crossfade_ms > 0
    assert action.text == "let me check that for you"


def test_main_fully_duplicated_is_suppressed():
    h = HandoffController()
    h.begin_filler("okay got it")
    action = h.handoff_to_main("okay got it", filler_done=True)
    assert action.kind == HandoffKind.suppress_main
    assert action.text == ""


def test_no_duplicate_content_in_spoken_text():
    h = HandoffController()
    h.begin_filler("sure")
    h.handoff_to_main("sure, the meeting is at 3pm", filler_done=True)
    spoken = h.spoken_text
    # "sure" should appear once (from the filler), not twice.
    assert spoken.lower().split().count("sure") == 1
    assert "the meeting is at 3pm" in spoken


def test_suppress_filler_when_main_ready_first():
    h = HandoffController()
    action = h.suppress_filler("main_ready_first")
    assert action.kind == HandoffKind.suppress_filler_start
    # State stays idle so main can play directly.
    main = h.handoff_to_main("the answer is 42")
    assert main.kind == HandoffKind.play_main


def test_begin_filler_twice_is_noop():
    h = HandoffController()
    h.begin_filler("okay")
    second = h.begin_filler("okay again")
    assert second.kind == HandoffKind.noop


def test_handoff_after_main_playing_is_noop():
    h = HandoffController()
    h.handoff_to_main("answer")
    again = h.handoff_to_main("answer again")
    assert again.kind == HandoffKind.noop


def test_reset_returns_to_idle():
    h = HandoffController()
    h.begin_filler("ok")
    h.handoff_to_main("ok done", filler_done=True)
    h.reset()
    assert h.state == OnsetState.idle
    assert h.spoken_text == ""


# --- dedup helper ----------------------------------------------------------
def test_strip_leading_duplicate_partial():
    assert _strip_leading_duplicate("okay", "okay here we go") == "here we go"


def test_strip_leading_duplicate_none():
    assert _strip_leading_duplicate("okay", "completely different") == "completely different"


def test_strip_leading_duplicate_full():
    assert _strip_leading_duplicate("okay got it", "okay got it") == ""


def test_strip_leading_duplicate_empty_filler():
    assert _strip_leading_duplicate("", "anything") == "anything"


def test_strip_punctuation_at_seam():
    # filler "okay", main "okay, here" → comma trimmed.
    assert _strip_leading_duplicate("okay", "okay, here is more") == "here is more"
