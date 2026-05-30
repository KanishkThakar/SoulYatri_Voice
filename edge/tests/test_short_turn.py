"""Tests for the short-turn classifier (Phase 8A)."""

from __future__ import annotations

from edge.planner.short_turn import ShortTurnClassifier, ShortTurnResult, TurnClass
from shared.contracts import EmotionState, RouteDecision, RouteTarget


def clf() -> ShortTurnClassifier:
    return ShortTurnClassifier()


def test_greeting_is_trivial_cached_filler():
    res = clf().classify("hello", asr_confidence=0.95)
    assert res.turn_class == TurnClass.trivial
    assert res.route.route == RouteTarget.cached_filler
    assert res.route.phrase_id is not None
    assert res.route.intent == "greeting"


def test_hinglish_greeting_trivial():
    res = clf().classify("namaste", asr_confidence=0.9)
    assert res.turn_class == TurnClass.trivial
    assert res.route.route == RouteTarget.cached_filler


def test_acknowledgement_is_trivial():
    res = clf().classify("ok thik hai", asr_confidence=0.9)
    assert res.turn_class == TurnClass.trivial
    assert res.route.intent == "acknowledgement"


def test_low_confidence_is_uncertain_full_stack():
    res = clf().classify("something muffled", asr_confidence=0.2)
    assert res.turn_class == TurnClass.uncertain
    assert res.route.route == RouteTarget.full_stack


def test_emotional_turn_routes_full_stack_with_filler():
    emo = EmotionState(valence=-0.7, arousal=0.8, confidence=0.9)
    res = clf().classify("i feel so sad today", asr_confidence=0.9, emotion=emo)
    assert res.turn_class == TurnClass.emotional
    assert res.route.route == RouteTarget.full_stack
    assert res.route.emit_filler_then_forward is True


def test_emotional_lexical_only_detected():
    res = clf().classify("i am so worried", asr_confidence=0.9)
    assert res.turn_class == TurnClass.emotional


def test_short_question_is_short_full_stack():
    res = clf().classify("what time is it", asr_confidence=0.9)
    assert res.turn_class == TurnClass.short
    assert res.route.route == RouteTarget.full_stack
    assert res.route.intent == "short_query"
    assert res.route.emit_filler_then_forward is True


def test_long_turn_is_complex():
    text = "i was thinking about the project plan and whether we should refactor the entire module before the release deadline next week"
    res = clf().classify(text, asr_confidence=0.95)
    assert res.turn_class == TurnClass.complex
    assert res.route.route == RouteTarget.full_stack
    assert res.route.emit_filler_then_forward is False


def test_empty_transcript_short_audio_is_trivial_ack():
    res = clf().classify("", asr_confidence=1.0, speech_duration_ms=400)
    assert res.turn_class == TurnClass.trivial
    assert res.route.route == RouteTarget.cached_filler


def test_empty_transcript_long_audio_is_uncertain():
    res = clf().classify("", asr_confidence=1.0, speech_duration_ms=4000)
    assert res.turn_class == TurnClass.uncertain
    assert res.route.route == RouteTarget.full_stack


def test_question_short_phrase_not_misclassified_as_trivial():
    # "ok?" is a question, must not be trivial cached filler.
    res = clf().classify("why?", asr_confidence=0.9)
    assert res.turn_class != TurnClass.trivial


def test_result_is_serializable_route_decision():
    res = clf().classify("hi", asr_confidence=0.95)
    assert isinstance(res, ShortTurnResult)
    assert isinstance(res.route, RouteDecision)
    dumped = res.route.model_dump()
    assert RouteDecision.model_validate(dumped) == res.route
    assert "turn_class" in res.to_dict()


def test_confidence_within_bounds():
    for text in ["hi", "what is the weather", "i feel sad", "", "a very long complex sentence about stuff and things here"]:
        res = clf().classify(text, asr_confidence=0.8)
        assert 0.0 <= res.confidence <= 1.0
        assert 0.0 <= res.route.confidence <= 1.0
