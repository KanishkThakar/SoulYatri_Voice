"""Property-based test for the Emotion/Persona conditioning controller.

This module implements the design's **Property 9: Emotion/persona conditioning
selection** for :class:`roadmap.emotion_persona.EmotionPersonaController`
(``select_conditioning`` / ``select``) operating on
:class:`roadmap.models.runtime.EmotionFeatures`.

Property 9 (design ``Correctness Properties``):

    For any per-turn emotion features, the conditioning selector exposes
    valence, arousal, and dominance values each within the inclusive range
    -1.0 to 1.0; selects neutral conditioning (V/A/D = 0,0,0 with the neutral
    tag) when extraction is unavailable or failed; selects empathetic/calming
    conditioning when the dominant label is a distress label (sad, angry, or
    fear) with confidence at least 0.50; and otherwise selects standard
    conditioning derived from the features -- and in every case the turn is
    allowed to continue.

Generator design (covering the whole input space described by the task):

- ``label`` is drawn from the 7 discrete tags *and* ``None`` (extraction
  failed), so the neutral fallback path is exercised both via ``label is None``
  and via ``extraction_ok=False``.
- ``confidence`` spans ``[0.0, 1.0]`` with extra mass around the inclusive
  ``0.50`` distress threshold, and occasionally drifts slightly outside
  ``[0, 1]`` to confirm the comparison is robust to out-of-nominal-range input.
- ``valence`` / ``arousal`` / ``dominance`` are drawn from a range wider than
  ``[-1, 1]`` so a large fraction land out of range and exercise the clamp that
  :class:`EmotionFeatures` applies on construction; the controller then re-clamps
  the *exposed* conditioning vector, which the property asserts is always
  in-range (Requirement 6.1).
- ``extraction_ok`` is either ``True`` or ``False``.

Validates: Requirements 6.1, 6.3, 6.5, 6.7.
"""

from __future__ import annotations

from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.emotion_persona import (
    DISTRESS_CONFIDENCE_THRESHOLD,
    DISTRESS_LABELS,
    NEUTRAL_TAG,
    EmotionPersonaController,
)
from roadmap.models.runtime import EmotionFeatures

#: The 7 discrete emotion tags the controller understands (Requirement 6.1).
EMOTION_TAGS = ("neutral", "happy", "sad", "angry", "fear", "disgust", "surprise")

#: The only conditioning modes the controller may ever emit.
VALID_MODES = frozenset({"NEUTRAL", "EMPATHETIC", "STANDARD"})


@st.composite
def emotion_features(draw: st.DrawFn) -> EmotionFeatures:
    """Generate diverse :class:`EmotionFeatures` spanning the full input space.

    See the module docstring for the rationale behind each component's range.
    """

    label: Optional[str] = draw(st.one_of(st.none(), st.sampled_from(EMOTION_TAGS)))
    confidence = draw(
        st.one_of(
            st.floats(min_value=0.0, max_value=1.0),
            # Extra density right around the inclusive 0.50 boundary.
            st.floats(min_value=0.48, max_value=0.52),
            # Occasionally drift slightly outside [0, 1] to confirm robustness.
            st.floats(min_value=-0.1, max_value=1.1),
        )
    )
    # Range intentionally exceeds [-1, 1] to verify clamping on construction.
    vad = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)
    return EmotionFeatures(
        label=label,
        confidence=confidence,
        valence=draw(vad),
        arousal=draw(vad),
        dominance=draw(vad),
        extraction_ok=draw(st.booleans()),
    )


# Feature: speech-native-voice-roadmap, Property 9: Emotion/persona conditioning selection
@settings(max_examples=100)
@given(features=emotion_features())
def test_property_9_emotion_persona_conditioning_selection(
    features: EmotionFeatures,
) -> None:
    """Property 9: the controller always returns a valid, in-range conditioning.

    Validates: Requirements 6.1, 6.3, 6.5, 6.7.
    """

    controller = EmotionPersonaController()

    # The turn always continues (Req 6.7): a result is always returned with no
    # exception raised for any input, including failed/unavailable extraction.
    selection = controller.select(features)

    # A valid mode is always produced.
    assert selection.mode in VALID_MODES

    # The bare-mode accessor must agree with the full selection.
    assert controller.select_conditioning(features) == selection.mode

    # Req 6.1: the exposed/effective V/A/D is always clamped into [-1.0, 1.0],
    # even though the generator feeds values well outside that range.
    for component in (selection.valence, selection.arousal, selection.dominance):
        assert -1.0 <= component <= 1.0

    if not features.extraction_ok or features.label is None:
        # Req 6.7: failed/unavailable extraction -> neutral conditioning, with
        # the effective V/A/D pinned to (0, 0, 0) and the neutral tag.
        assert selection.mode == "NEUTRAL"
        assert (selection.valence, selection.arousal, selection.dominance) == (
            0.0,
            0.0,
            0.0,
        )
        assert selection.tag == NEUTRAL_TAG
    elif (
        features.label in DISTRESS_LABELS
        and features.confidence >= DISTRESS_CONFIDENCE_THRESHOLD
    ):
        # Req 6.5: distress label with confidence >= 0.50 (inclusive) -> calming.
        assert selection.mode == "EMPATHETIC"
        assert selection.tag == features.label
    else:
        # Req 6.3: otherwise standard conditioning derived from the features.
        assert selection.mode == "STANDARD"
        assert selection.tag == features.label
