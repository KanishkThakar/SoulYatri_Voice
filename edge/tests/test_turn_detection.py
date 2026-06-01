"""Tests for streaming turn-end / endpointing detection (Phase 4A/4B).

Validates on synthetic audio that:
* the detector streams per-frame (no full-utterance buffering),
* speech start / provisional end markers fire on the correct edges,
* a turn-end candidate is raised when trailing silence begins,
* a turn-end is *confirmed* only after the silence hangover elapses,
* an isolated blip below ``min_speech_ms`` never confirms a turn end, and
* the endpointing markers line up with the edge turn-state machine.

All deterministic, CPU-only via the energy VAD fallback.
"""

from __future__ import annotations

import math
import types

from edge.session.turn_state import TurnStateMachine
from edge.turn_detection.detector import EndpointDecision, EndpointingDetector
from edge.turn_detection.features import VADProvider
from shared.contracts import TurnState


def sine_frame(n: int = 480, amp: float = 0.4, freq: float = 220.0, sr: int = 16000) -> list[float]:
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]


def silence_frame(n: int = 480) -> list[float]:
    return [0.0] * n


def make_detector(**kw) -> EndpointingDetector:
    params = dict(
        sample_rate=16000,
        frame_ms=30,
        speech_threshold=0.5,
        start_frames=2,
        end_frames=3,
        hangover_ms=300,   # 10 silence frames @ 30ms.
        min_speech_ms=120,  # 4 speech frames @ 30ms.
        vad=VADProvider(use_fallback=True),
    )
    params.update(kw)
    return EndpointingDetector("s1", **params)


def test_uses_deterministic_fallback_on_cpu():
    det = make_detector()
    assert det.using_fallback is True


def test_stream_is_lazy_generator():
    det = make_detector()
    frames = [(silence_frame(), i * 30) for i in range(3)]
    gen = det.stream(frames)
    assert isinstance(gen, types.GeneratorType)
    first = next(gen)
    assert isinstance(first, EndpointDecision)
    assert first.seq == 0


def test_speech_start_marker_fires_once():
    det = make_detector(start_frames=2)
    seq = [silence_frame(), sine_frame(), sine_frame(), sine_frame()]
    decisions = [det.process_frame(f, i * 30) for i, f in enumerate(seq)]
    started = [d for d in decisions if d.speech_started]
    assert len(started) == 1
    # Onset after 2 consecutive speech frames → 2nd speech frame at index 2.
    assert started[0].seq == 2
    assert started[0].is_speech is True


def test_turn_end_candidate_then_confirmed_on_synthetic_audio():
    det = make_detector(start_frames=2, end_frames=3, hangover_ms=300, min_speech_ms=120)
    # 6 speech frames (well past min_speech_ms), then a long silence tail.
    seq = [sine_frame() for _ in range(6)] + [silence_frame() for _ in range(15)]
    decisions = [det.process_frame(f, i * 30) for i, f in enumerate(seq)]

    started = [d for d in decisions if d.speech_started]
    ended = [d for d in decisions if d.speech_ended]
    candidates = [d for d in decisions if d.turn_end_candidate]
    confirmed = [d for d in decisions if d.turn_end_confirmed]

    assert len(started) == 1
    assert len(ended) == 1
    # A candidate is raised as soon as trailing silence begins.
    assert len(candidates) == 1
    # The turn end is confirmed exactly once, after the hangover.
    assert len(confirmed) == 1
    # Candidate must come at or before confirmation.
    assert candidates[0].seq <= confirmed[0].seq
    # Confirmation only after silence ≥ hangover.
    assert confirmed[0].silence_ms >= 300


def test_short_silence_does_not_confirm_turn_end():
    det = make_detector(end_frames=3, hangover_ms=300, min_speech_ms=120)
    # Speech, then only a short silence (below hangover), then speech resumes.
    seq = (
        [sine_frame() for _ in range(6)]
        + [silence_frame() for _ in range(4)]   # 120ms < 300ms hangover
        + [sine_frame() for _ in range(6)]
    )
    decisions = [det.process_frame(f, i * 30) for i, f in enumerate(seq)]
    confirmed = [d for d in decisions if d.turn_end_confirmed]
    assert confirmed == []  # never confirmed because speech resumed in time


def test_isolated_blip_never_confirms_turn_end():
    det = make_detector(start_frames=2, end_frames=3, hangover_ms=300, min_speech_ms=240)
    # Only 2 speech frames (60ms) < min_speech_ms (240ms): a blip/cough.
    seq = [sine_frame() for _ in range(2)] + [silence_frame() for _ in range(15)]
    decisions = [det.process_frame(f, i * 30) for i, f in enumerate(seq)]
    confirmed = [d for d in decisions if d.turn_end_confirmed]
    assert confirmed == []


def test_two_turns_each_confirm_once():
    det = make_detector(start_frames=2, end_frames=3, hangover_ms=300, min_speech_ms=120)
    one_turn = [sine_frame() for _ in range(6)] + [silence_frame() for _ in range(12)]
    decisions = [det.process_frame(f, i * 30) for i, f in enumerate(one_turn + one_turn)]
    confirmed = [d for d in decisions if d.turn_end_confirmed]
    assert len(confirmed) == 2


def test_process_probability_matches_audio_path():
    det_audio = make_detector()
    det_prob = make_detector()
    seq = [sine_frame() for _ in range(6)] + [silence_frame() for _ in range(15)]
    vad = VADProvider(use_fallback=True)
    for i, f in enumerate(seq):
        a = det_audio.process_frame(f, i * 30)
        p = det_prob.process_probability(vad.speech_probability(f), i * 30)
        assert a.is_speech == p.is_speech
        assert a.turn_end_confirmed == p.turn_end_confirmed


def test_reset_clears_state():
    det = make_detector(start_frames=1)
    det.process_frame(sine_frame(), 0)
    assert det.in_speech is True
    det.reset()
    assert det.in_speech is False
    assert det.trailing_silence_ms == 0


def test_decision_to_dict_serializable():
    det = make_detector(start_frames=1)
    d = det.process_frame(sine_frame(), 30).to_dict()
    assert d["session_id"] == "s1"
    assert "turn_end_confirmed" in d
    assert "silence_ms" in d


def test_endpointing_drives_turn_state_machine():
    """The endpointer's markers map cleanly onto the edge turn-state machine."""
    det = make_detector(start_frames=2, end_frames=3, hangover_ms=300, min_speech_ms=120)
    m = TurnStateMachine("s1")
    seq = [sine_frame() for _ in range(6)] + [silence_frame() for _ in range(15)]
    for i, f in enumerate(seq):
        d = det.process_frame(f, i * 30)
        if d.speech_started:
            m.on_speech_start()
            assert m.state == TurnState.listening
        if d.speech_ended:
            m.on_speech_end()
            assert m.state == TurnState.buffering
        if d.turn_end_confirmed:
            m.on_turn_confirmed()
            # Confirmed turn end advances buffering → candidate_filler.
            assert m.state == TurnState.candidate_filler
    assert m.state == TurnState.candidate_filler
