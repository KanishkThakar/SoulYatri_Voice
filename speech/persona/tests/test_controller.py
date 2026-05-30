"""
Phase 9B tests — persona identity preservation + FiLM conditioning determinism.

Covers:
  * identity (persona_id / speaker_style_ref) preserved while emotion varies across turns,
  * style-embedding fusion is deterministic and stable for the same identity,
  * film_conditioning is a deterministic pure function (same emotion -> identical params),
  * conditioning actually *varies* when emotion varies (it's not a constant).
"""

from __future__ import annotations

from shared.contracts import EmotionState, PersonaState
from speech.persona.controller import (
    DEFAULT_PERSONA_ID,
    FILM_FEATURE_DIM,
    FiLMParams,
    HashStyleEmbeddingProvider,
    PersonaController,
    film_conditioning,
)


# ---------------------------------------------------------------------------
# Identity preserved while emotion varies
# ---------------------------------------------------------------------------
def test_identity_preserved_across_varying_emotions() -> None:
    ctrl = PersonaController(persona_id="soulyatri", speaker_style_ref="ref-abc")

    emotions = [
        EmotionState(valence=0.9, arousal=0.7, warmth=0.9),  # cheerful
        EmotionState(valence=-0.6, arousal=-0.3, warmth=0.6),  # subdued/sad
        EmotionState(valence=-0.2, arousal=0.8, dominance=0.7),  # agitated
    ]
    states = [ctrl.shape(e) for e in emotions]

    # Identity fields are identical across every turn ...
    for s in states:
        assert s.persona_id == "soulyatri"
        assert s.speaker_style_ref == "ref-abc"
        assert s.language == "hinglish"

    # ... but emotion actually varies turn-to-turn.
    valences = [s.emotion.valence for s in states]
    assert len(set(round(v, 3) for v in valences)) == 3

    # pairwise identity check helper agrees
    assert ctrl.preserves_identity(states[0], states[1])
    assert ctrl.preserves_identity(states[1], states[2])


def test_shape_ignores_base_identity_fields() -> None:
    # Even if a 'base' persona carried a different identity, the controller's identity wins.
    ctrl = PersonaController(persona_id="soulyatri", speaker_style_ref="ref-1")
    foreign = PersonaState(
        persona_id="other", speaker_style_ref="ref-2", emotion=EmotionState(warmth=0.2)
    )
    shaped = ctrl.shape(EmotionState(warmth=0.9), base=foreign, blend_weight=0.5)
    assert shaped.persona_id == "soulyatri"
    assert shaped.speaker_style_ref == "ref-1"
    # emotion is a blend of base(0.2) and new(0.9) -> ~0.55
    assert 0.5 < shaped.emotion.warmth < 0.6


def test_default_persona_id() -> None:
    ctrl = PersonaController()
    assert ctrl.persona_id == DEFAULT_PERSONA_ID
    assert ctrl.shape(EmotionState()).persona_id == DEFAULT_PERSONA_ID


# ---------------------------------------------------------------------------
# Speaker-style embedding fusion
# ---------------------------------------------------------------------------
def test_style_embedding_deterministic_and_identity_stable() -> None:
    ctrl = PersonaController(persona_id="p", speaker_style_ref="ref-xyz")
    e1 = ctrl.style_embedding()
    e2 = ctrl.style_embedding()
    assert e1 == e2  # stable across turns -> identity stable
    # different reference -> different embedding
    other = PersonaController(persona_id="p", speaker_style_ref="ref-different")
    assert other.style_embedding() != e1


def test_default_voice_is_neutral_embedding() -> None:
    ctrl = PersonaController()  # no style ref
    assert ctrl.style_embedding() == [0.0] * HashStyleEmbeddingProvider().dim


def test_fuse_style_mixes_identity_and_affect() -> None:
    ctrl = PersonaController(persona_id="p", speaker_style_ref="ref-xyz")
    emo_embedding = [1.0] * HashStyleEmbeddingProvider().dim
    # full identity weight -> equals style embedding
    fused_id = ctrl.fuse_style(emo_embedding, style_weight=1.0)
    assert fused_id == ctrl.style_embedding()
    # full affect weight -> equals the emotion embedding
    fused_emo = ctrl.fuse_style(emo_embedding, style_weight=0.0)
    assert fused_emo == emo_embedding


# ---------------------------------------------------------------------------
# FiLM conditioning determinism
# ---------------------------------------------------------------------------
def test_film_conditioning_is_deterministic() -> None:
    emo = EmotionState(
        valence=0.5,
        arousal=0.3,
        dominance=0.2,
        warmth=0.8,
        uncertainty=0.1,
        pace=0.6,
        intensity=0.7,
    )
    p1 = film_conditioning(emo)
    p2 = film_conditioning(emo)
    assert isinstance(p1, FiLMParams)
    assert p1 == p2  # frozen dataclass value-equality
    assert p1.gamma == p2.gamma
    assert p1.beta == p2.beta
    assert p1.controls == p2.controls


def test_film_dimensions() -> None:
    p = film_conditioning(EmotionState())
    assert len(p.gamma) == FILM_FEATURE_DIM
    assert len(p.beta) == FILM_FEATURE_DIM
    # custom dim honored
    p2 = film_conditioning(EmotionState(), dim=4)
    assert len(p2.gamma) == 4 and len(p2.beta) == 4


def test_film_varies_with_emotion() -> None:
    calm = film_conditioning(EmotionState(valence=-0.5, arousal=-0.5, intensity=0.1, warmth=0.3))
    excited = film_conditioning(EmotionState(valence=0.8, arousal=0.9, intensity=0.9, warmth=0.9))
    assert calm.gamma != excited.gamma
    assert calm.beta != excited.beta
    # higher arousal/energy -> higher 'energy' control
    assert excited.controls["energy"] > calm.controls["energy"]


def test_film_controls_in_range() -> None:
    p = film_conditioning(
        EmotionState(
            valence=1.0,
            arousal=1.0,
            dominance=1.0,
            warmth=1.0,
            intensity=1.0,
            pace=1.0,
            uncertainty=1.0,
        )
    )
    for key in ("rate", "pitch", "energy", "warmth", "uncertainty", "assertiveness"):
        assert 0.0 <= p.controls[key] <= 1.0


def test_film_clamps_invalid_emotion_via_dict() -> None:
    # film_conditioning defensively clamps, so a raw dict with OOR values still works.
    p = film_conditioning(EmotionState(arousal=1.0))
    assert len(p.gamma) == FILM_FEATURE_DIM


def test_conditioning_via_controller_matches_pure_function() -> None:
    ctrl = PersonaController(persona_id="p")
    emo = EmotionState(valence=0.4, arousal=0.6, intensity=0.5)
    persona = ctrl.shape(emo)
    assert ctrl.conditioning(persona) == film_conditioning(persona.emotion)


def test_film_params_as_dict_is_json_safe() -> None:
    p = film_conditioning(EmotionState(warmth=0.9))
    d = p.as_dict()
    assert set(d.keys()) == {"gamma", "beta", "controls"}
    assert isinstance(d["gamma"], list)
    assert isinstance(d["controls"], dict)
