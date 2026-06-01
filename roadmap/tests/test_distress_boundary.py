"""Unit tests for the distress-confidence boundary (Requirement 6.5).

Plain ``pytest`` example tests for
:meth:`roadmap.emotion_persona.EmotionPersonaController.select_conditioning`.
They pin the *inclusive* confidence boundary described in Requirement 6.5:

    WHILE the detected dominant emotion label is a distress label (sad, angry,
    or fear) with confidence of **at least 0.50**, THE SoulYatri_Platform SHALL
    apply empathetic or calming persona conditioning to every response turn for
    the duration of that state.

The controller implements this as
``confidence >= DISTRESS_CONFIDENCE_THRESHOLD`` with
``DISTRESS_CONFIDENCE_THRESHOLD == 0.50``, so:

- exactly ``0.50`` with a distress label selects ``EMPATHETIC`` (inclusive),
- just below (``0.49``) falls back to ``STANDARD``,
- just above (``0.51``) selects ``EMPATHETIC``,
- a non-distress label at ``0.50`` selects ``STANDARD`` (the confidence
  threshold only applies to distress labels).

All cases use ``extraction_ok=True`` and a valid label so only ``label`` and
``confidence`` drive the decision.

Requirements: 6.5
"""

from __future__ import annotations

import pytest

from roadmap.emotion_persona import DISTRESS_LABELS, EmotionPersonaController
from roadmap.models.runtime import EmotionFeatures

# The three distress labels for which the inclusive boundary applies.
DISTRESS = sorted(DISTRESS_LABELS)


def _features(label: str, confidence: float) -> EmotionFeatures:
    """Build a successfully-extracted EmotionFeatures with a benign V/A/D.

    The V/A/D vector does not affect the boundary decision; it is fixed to an
    in-range neutral value so only ``label`` and ``confidence`` drive the mode.
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


def test_distress_at_exactly_threshold_selects_empathetic(
    controller: EmotionPersonaController,
) -> None:
    """A distress label ("sad") at exactly confidence 0.50 selects EMPATHETIC.

    This is the core boundary assertion: the threshold is inclusive, so 0.50
    itself must select the empathetic / calming mode.
    """
    features = _features("sad", 0.50)
    assert controller.select_conditioning(features) == "EMPATHETIC"


def test_distress_just_below_threshold_selects_standard(
    controller: EmotionPersonaController,
) -> None:
    """A distress label just below the boundary (0.49) selects STANDARD."""
    features = _features("sad", 0.49)
    assert controller.select_conditioning(features) == "STANDARD"


def test_distress_just_above_threshold_selects_empathetic(
    controller: EmotionPersonaController,
) -> None:
    """A distress label just above the boundary (0.51) selects EMPATHETIC."""
    features = _features("sad", 0.51)
    assert controller.select_conditioning(features) == "EMPATHETIC"


@pytest.mark.parametrize("label", DISTRESS)
def test_all_distress_labels_at_threshold_select_empathetic(
    controller: EmotionPersonaController, label: str
) -> None:
    """Each of sad / angry / fear at confidence 0.50 selects EMPATHETIC."""
    features = _features(label, 0.50)
    assert controller.select_conditioning(features) == "EMPATHETIC"


def test_non_distress_label_at_threshold_selects_standard(
    controller: EmotionPersonaController,
) -> None:
    """A non-distress label ("happy") at 0.50 selects STANDARD.

    The confidence threshold only gates distress labels, so a high-confidence
    non-distress label must not trigger empathetic conditioning.
    """
    features = _features("happy", 0.50)
    assert controller.select_conditioning(features) == "STANDARD"
