"""Unit tests for the distress-confidence boundary of the emotion controller.

These are plain ``pytest`` example tests (kept in a separate file from the
property test in ``test_emotion_persona_property.py`` to avoid collisions). They
pin the *inclusive* confidence boundary described in Requirement 6.5:

    WHILE the detected dominant emotion label is a distress label (sad, angry,
    or fear) with confidence of **at least 0.50**, THE SoulYatri_Platform SHALL
    apply empathetic / calming persona conditioning.

The controller (``roadmap/emotion_persona.py``) implements this as
``confidence >= 0.50``, so exactly ``0.50`` must select ``EMPATHETIC`` while
``0.49`` falls back to ``STANDARD``. A non-distress label at ``0.50`` is also
checked to confirm the boundary only applies to distress labels.

Requirements: 6.5
"""

from __future__ import annotations

import pytest

from roadmap.emotion_persona import DISTRESS_LABELS, EmotionPersonaController
from roadmap.models.runtime import EmotionFeatures

# The three distress labels for which the boundary applies (sad / angry / fear).
DISTRESS = sorted(DISTRESS_LABELS)


def _features(label: str, confidence: float) -> EmotionFeatures:
    """Build a successfully-extracted EmotionFeatures with a neutral V/A/D.

    The V/A/D vector is irrelevant to the boundary decision; it is set to a
    benign in-range value so only ``label`` and ``confidence`` drive the mode.
    """

    return EmotionFeatures(
        label=label,
        confidence=confidence,
        valence=0.0,
        arousal=0.0,
        dominance=0.0,
        extraction_ok=True,
    )


@pytest.fixture
def controller() -> EmotionPersonaController:
    return EmotionPersonaController()


@pytest.mark.parametrize("label", DISTRESS)
def test_distress_at_exactly_threshold_selects_empathetic(
    controller: EmotionPersonaController, label: str
) -> None:
    """Every distress label at confidence == 0.50 selects EMPATHETIC (inclusive)."""
    features = _features(label, 0.50)
    assert controller.select_conditioning(features) == "EMPATHETIC"
    assert controller.select(features).mode == "EMPATHETIC"


@pytest.mark.parametrize("label", DISTRESS)
def test_distress_just_below_threshold_selects_standard(
    controller: EmotionPersonaController, label: str
) -> None:
    """A distress label just below the boundary (0.49) falls back to STANDARD."""
    features = _features(label, 0.49)
    assert controller.select_conditioning(features) == "STANDARD"


@pytest.mark.parametrize("label", DISTRESS)
def test_distress_just_above_threshold_selects_empathetic(
    controller: EmotionPersonaController, label: str
) -> None:
    """A distress label just above the boundary (0.51) selects EMPATHETIC."""
    features = _features(label, 0.51)
    assert controller.select_conditioning(features) == "EMPATHETIC"


def test_non_distress_label_at_threshold_selects_standard(
    controller: EmotionPersonaController,
) -> None:
    """A non-distress label at 0.50 is not empathetic; it selects STANDARD."""
    features = _features("happy", 0.50)
    assert controller.select_conditioning(features) == "STANDARD"
