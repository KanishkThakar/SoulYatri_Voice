"""
Phase 9C tests — relationship-state adaptation across turns.

Covers:
  * observing turns updates tone preference (EMA), preferred response length, calm/stress
    trajectory, and recent emotional context (bounded ring buffers),
  * future turns adapt audibly: adapt_emotion pulls a target toward learned tone,
  * stress de-escalation: sustained high arousal -> calmer/warmer adapted output,
  * pluggable backend interface works (in-memory default + custom backend),
  * reset clears state.
"""

from __future__ import annotations

from shared.contracts import EmotionState
from speech.persona.relationship import (
    InMemoryRelationshipBackend,
    RelationshipBackend,
    RelationshipProfile,
    RelationshipStore,
)


def test_fresh_profile_is_neutral() -> None:
    store = RelationshipStore()
    p = store.get_profile("new-session")
    assert p.turns == 0
    assert p.preferred_response_length is None
    assert p.calm_stress_trajectory == []
    assert p.stress_level() == 0.5  # neutral when no data


def test_observe_turn_updates_all_signals() -> None:
    store = RelationshipStore()
    p = store.observe_turn(
        "s1",
        user_emotion=EmotionState(arousal=0.4, warmth=0.7, valence=0.5),
        response_length=30,
    )
    assert p.turns == 1
    assert p.preferred_response_length == 30
    assert p.calm_stress_trajectory == [0.4]
    assert len(p.recent_emotional_context) == 1


def test_response_length_ema_moves_toward_observations() -> None:
    store = RelationshipStore(alpha=0.5)
    store.observe_turn("s1", response_length=10)
    p = store.observe_turn("s1", response_length=30)
    # EMA: 0.5*10 + 0.5*30 = 20
    assert abs(p.preferred_response_length - 20.0) < 1e-9


def test_tone_preference_ema_across_turns() -> None:
    store = RelationshipStore(alpha=0.5)
    store.observe_turn("s1", user_emotion=EmotionState(warmth=0.2))
    p = store.observe_turn("s1", user_emotion=EmotionState(warmth=1.0))
    # first turn sets tone=0.2, second blends toward 1.0 at weight 0.5 -> 0.6
    assert abs(p.tone_preference.warmth - 0.6) < 1e-9


def test_trajectory_and_context_are_bounded() -> None:
    store = RelationshipStore(history=3)
    for i in range(6):
        store.observe_turn("s1", user_emotion=EmotionState(arousal=(i / 10.0)))
    p = store.get_profile("s1")
    assert len(p.calm_stress_trajectory) == 3  # ring buffer capped
    assert len(p.recent_emotional_context) == 3
    # keeps most recent samples (0.3, 0.4, 0.5)
    assert p.calm_stress_trajectory == [0.3, 0.4, 0.5]


def test_adapt_emotion_without_history_returns_target() -> None:
    store = RelationshipStore()
    target = EmotionState(warmth=0.5, valence=0.0)
    out = store.adapt_emotion("unknown", target)
    assert out == target


def test_future_turns_adapt_toward_learned_tone() -> None:
    store = RelationshipStore(alpha=0.5)
    # User consistently warm/positive -> persona should learn a warm tone preference.
    for _ in range(4):
        store.observe_turn("s1", user_emotion=EmotionState(warmth=1.0, valence=0.8))

    neutral_target = EmotionState(warmth=0.3, valence=0.0)
    adapted = store.adapt_emotion("s1", neutral_target, adapt_weight=0.6)
    # adapted warmth/valence should rise toward the learned warm tone.
    assert adapted.warmth > neutral_target.warmth
    assert adapted.valence > neutral_target.valence


def test_stress_triggers_calming_adaptation() -> None:
    store = RelationshipStore()
    # Sustained high arousal -> high stress level.
    for _ in range(5):
        store.observe_turn("s1", user_emotion=EmotionState(arousal=0.95, warmth=0.5))
    profile = store.get_profile("s1")
    assert profile.stress_level() > 0.6

    target = EmotionState(arousal=0.8, warmth=0.4, intensity=0.7)
    adapted = store.adapt_emotion("s1", target, adapt_weight=0.0)  # isolate stress nudge
    # de-escalation: calmer (lower arousal) and warmer than the target.
    assert adapted.arousal < target.arousal
    assert adapted.warmth > target.warmth


def test_pluggable_backend_interface() -> None:
    backend = InMemoryRelationshipBackend()
    assert isinstance(backend, RelationshipBackend)  # runtime_checkable Protocol
    store = RelationshipStore(backend=backend)
    store.observe_turn("s1", user_emotion=EmotionState(warmth=0.6))
    # state is visible directly through the backend
    stored = backend.get("s1")
    assert stored is not None and stored.turns == 1


def test_custom_backend_is_used() -> None:
    class DictBackend:
        def __init__(self) -> None:
            self.store: dict[str, RelationshipProfile] = {}

        def get(self, session_id: str):
            return self.store.get(session_id)

        def put(self, profile: RelationshipProfile) -> None:
            self.store[profile.session_id] = profile

        def clear(self, session_id: str) -> None:
            self.store.pop(session_id, None)

    backend = DictBackend()
    store = RelationshipStore(backend=backend)
    store.observe_turn("s1", user_emotion=EmotionState(warmth=0.9))
    assert "s1" in backend.store


def test_reset_clears_state() -> None:
    store = RelationshipStore()
    store.observe_turn("s1", user_emotion=EmotionState(warmth=0.6))
    store.reset("s1")
    assert store.get_profile("s1").turns == 0


def test_profile_to_dict_is_json_safe() -> None:
    store = RelationshipStore()
    store.observe_turn("s1", user_emotion=EmotionState(arousal=0.3, warmth=0.7), response_length=25)
    d = store.get_profile("s1").to_dict()
    assert d["session_id"] == "s1"
    assert "tone_preference" in d and isinstance(d["tone_preference"], dict)
    assert "stress_level" in d
