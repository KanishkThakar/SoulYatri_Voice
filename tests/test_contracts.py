"""
Tests for shared/contracts.py — the central cross-subsystem contract.

These tests guarantee the foundation imports cleanly on a CPU-only machine (no GPU,
no model weights) and that every core type constructs and JSON round-trips.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError

import shared.contracts as C


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------
def test_module_imports_clean() -> None:
    """shared.contracts must import without heavy/GPU deps."""
    mod = importlib.import_module("shared.contracts")
    assert hasattr(mod, "AudioFrame")


def test_no_heavy_imports_loaded() -> None:
    """Importing the contracts must not pull in torch/transformers/moshi/mimi."""
    import sys

    importlib.import_module("shared.contracts")
    for heavy in ("torch", "transformers", "moshi", "mimi"):
        assert heavy not in sys.modules, f"{heavy} should not be imported by shared.contracts"


def test_package_reexports() -> None:
    """The shared package should re-export the core contract types."""
    import shared

    for name in (
        "AudioFrame",
        "CodecChunk",
        "TurnState",
        "EmotionState",
        "RouteDecision",
        "VoiceRequest",
        "FallbackDecision",
        "MemoryWrite",
    ):
        assert hasattr(shared, name), f"shared should re-export {name}"


# ---------------------------------------------------------------------------
# Construction + round-trip
# ---------------------------------------------------------------------------
def _roundtrip(model):
    """Dump a pydantic model to dict/json and rebuild it; assert equality."""
    cls = type(model)
    as_dict = model.model_dump()
    rebuilt = cls.model_validate(as_dict)
    assert rebuilt == model
    as_json = model.model_dump_json()
    rebuilt_json = cls.model_validate_json(as_json)
    assert rebuilt_json == model
    return rebuilt


def test_audio_frame() -> None:
    frame = C.AudioFrame(session_id="s1", seq=0, pcm=[0.0, 0.1, -0.1], sample_rate=16000)
    assert frame.sample_rate == 16000
    assert frame.is_final is False
    _roundtrip(frame)


def test_codec_chunk() -> None:
    chunk = C.CodecChunk(turn_id="t1", seq=3, codec_tokens=[1, 2, 3], is_final=True)
    assert chunk.codec_tokens == [1, 2, 3]
    assert chunk.sample_rate == 24000
    _roundtrip(chunk)


def test_turn_state_enum() -> None:
    # Values must match server/pipeline/turn_state.py and the edge contract.
    expected = {
        "idle",
        "listening",
        "buffering",
        "candidate_filler",
        "forwarding",
        "thinking",
        "speaking",
        "barge_in",
        "repairing",
        "ended",
    }
    assert {s.value for s in C.TurnState} == expected
    assert C.TurnState("speaking") is C.TurnState.speaking


def test_turn_event() -> None:
    event = C.TurnEvent(
        session_id="s1",
        from_state=C.TurnState.idle,
        to_state=C.TurnState.listening,
        trigger="speech_start",
    )
    assert event.from_state is C.TurnState.idle
    rebuilt = _roundtrip(event)
    assert rebuilt.to_state is C.TurnState.listening


def test_emotion_state_defaults_and_bounds() -> None:
    emo = C.EmotionState(
        valence=0.62, arousal=0.31, dominance=0.58, warmth=0.80, uncertainty=0.14, intensity=0.47
    )
    assert -1.0 <= emo.valence <= 1.0
    assert 0.0 <= emo.pace <= 1.0  # default present
    _roundtrip(emo)


def test_emotion_state_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        C.EmotionState(valence=5.0)
    with pytest.raises(ValidationError):
        C.EmotionState(warmth=-1.0)


def test_persona_state_nested_emotion() -> None:
    persona = C.PersonaState(persona_id="soulyatri", emotion=C.EmotionState(warmth=0.9))
    assert persona.emotion.warmth == 0.9
    rebuilt = _roundtrip(persona)
    assert rebuilt.emotion.warmth == 0.9


def test_route_decision() -> None:
    decision = C.RouteDecision(
        route=C.RouteTarget.cached_filler,
        phrase_id="ack_001",
        intent="acknowledgment",
        confidence=0.85,
        reason="keyword match",
    )
    assert decision.route is C.RouteTarget.cached_filler
    _roundtrip(decision)


def test_route_decision_full_stack_default() -> None:
    decision = C.RouteDecision(route=C.RouteTarget.full_stack)
    assert decision.phrase_id is None
    assert decision.emit_filler_then_forward is False
    _roundtrip(decision)


def test_fallback_decision() -> None:
    fb = C.FallbackDecision(
        use_fallback=True, reason="moshi_unavailable", expected_recovery_ms=1500
    )
    assert fb.use_fallback is True
    _roundtrip(fb)


def test_memory_write() -> None:
    mw = C.MemoryWrite(
        session_id="s1",
        kind=C.MemoryKind.preference,
        content={"language": "hinglish"},
    )
    assert mw.kind is C.MemoryKind.preference
    _roundtrip(mw)


def test_memory_read_query_and_result() -> None:
    q = C.MemoryReadQuery(
        session_id="s1", query="user language", kinds=[C.MemoryKind.preference], top_k=3
    )
    assert q.top_k == 3
    _roundtrip(q)
    r = C.MemoryReadResult(
        session_id="s1", items=[{"language": "hinglish", "score": 0.9}], latency_ms=12
    )
    assert r.items[0]["score"] == 0.9
    _roundtrip(r)


def test_voice_request_consent_first() -> None:
    req = C.VoiceRequest(requested_action=C.VoiceAction.voice_clone, consent_token=None)
    # Consent enforcement happens in safety/, but the contract carries the token slot.
    assert req.consent_token is None
    assert req.requested_action is C.VoiceAction.voice_clone
    _roundtrip(req)


def test_moderation_decision() -> None:
    dec = C.ModerationDecision(allowed=False, category="self_harm", escalate=True, reason="crisis")
    assert dec.allowed is False
    assert dec.escalate is True
    _roundtrip(dec)


def test_now_ms_is_int() -> None:
    assert isinstance(C.now_ms(), int)
    assert C.now_ms() > 0


def test_extra_fields_forbidden() -> None:
    """Contracts use extra='forbid' to catch typos in field names early."""
    with pytest.raises(ValidationError):
        C.AudioFrame(session_id="s1", seq=0, bogus_field=123)
