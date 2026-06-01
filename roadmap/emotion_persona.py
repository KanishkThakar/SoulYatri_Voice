"""Emotion / persona conditioning controller for the speech-native roadmap.

This module implements the pure decision logic of the design's
"Emotion/Persona Controller" (`design.md` section 6). It carries forward the
valence/arousal/dominance (V/A/D) representation produced upstream by
``server/pipeline/emotion.py`` and decides which persona-conditioning mode to
apply to a turn.

The controller is intentionally side-effect free: it inspects an
:class:`~roadmap.models.runtime.EmotionFeatures` value and returns a
:data:`~roadmap.models.runtime.ConditioningMode` (plus, optionally, the
effective conditioning vector). The actual FiLM-style injection into the output
path is out of scope here — this is planning/decision tooling.

Decision rules (Requirements 6.1, 6.3, 6.5, 6.7):

- If per-turn extraction failed/unavailable (``extraction_ok`` is ``False`` or
  ``label`` is ``None``) → ``NEUTRAL`` conditioning with V/A/D = ``(0, 0, 0)``
  and the ``"neutral"`` tag; the turn continues uninterrupted (Req 6.7).
- Else if the dominant label is a distress label (``sad`` / ``angry`` /
  ``fear``) with confidence **>= 0.50** → ``EMPATHETIC`` (calming) conditioning
  (Req 6.5). The boundary is inclusive: exactly ``0.50`` selects ``EMPATHETIC``.
- Else → ``STANDARD`` conditioning derived from the V/A/D vector and dominant
  label (Req 6.3).

The exposed conditioning V/A/D is always clamped into ``[-1.0, 1.0]`` so the
controller can never emit out-of-range values, even though
:class:`EmotionFeatures` already clamps on construction (Req 6.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

from .models.runtime import ConditioningMode, EmotionFeatures

__all__ = [
    "DISTRESS_LABELS",
    "DISTRESS_CONFIDENCE_THRESHOLD",
    "NEUTRAL_TAG",
    "ConditioningSelection",
    "EmotionPersonaController",
]

#: Discrete emotion tags that count as "distress" for empathetic conditioning.
DISTRESS_LABELS: FrozenSet[str] = frozenset({"sad", "angry", "fear"})

#: Inclusive confidence threshold for distress → ``EMPATHETIC`` (Req 6.5).
DISTRESS_CONFIDENCE_THRESHOLD: float = 0.50

#: Discrete tag used for neutral conditioning.
NEUTRAL_TAG: str = "neutral"


def _clamp_unit(value: float) -> float:
    """Clamp ``value`` into the closed interval ``[-1.0, 1.0]``."""

    if value < -1.0:
        return -1.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True)
class ConditioningSelection:
    """The full result of a conditioning decision.

    ``mode`` is the core output (see :data:`ConditioningMode`). The
    ``valence`` / ``arousal`` / ``dominance`` fields carry the *effective*
    conditioning vector that should be injected for the turn — always clamped to
    ``[-1.0, 1.0]`` — and ``tag`` is the dominant discrete label applied.

    For ``NEUTRAL`` the vector is ``(0.0, 0.0, 0.0)`` with the ``"neutral"`` tag.
    """

    mode: ConditioningMode
    valence: float
    arousal: float
    dominance: float
    tag: str


class EmotionPersonaController:
    """Selects a persona-conditioning mode from per-turn emotion features.

    The controller is stateless; a single instance can be reused across turns.
    The distress label set and confidence threshold are configurable for
    testing/tuning but default to the design's values.
    """

    def __init__(
        self,
        *,
        distress_labels: FrozenSet[str] = DISTRESS_LABELS,
        distress_confidence_threshold: float = DISTRESS_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.distress_labels = frozenset(distress_labels)
        self.distress_confidence_threshold = distress_confidence_threshold

    def select_conditioning(self, features: EmotionFeatures) -> ConditioningMode:
        """Return the :data:`ConditioningMode` to apply for this turn.

        This is the core decision output (Requirements 6.3, 6.5, 6.7). The turn
        always continues regardless of the outcome; failed/unavailable
        extraction simply yields ``NEUTRAL`` rather than interrupting the turn.
        """

        return self.select(features).mode

    def select(self, features: EmotionFeatures) -> ConditioningSelection:
        """Return the full :class:`ConditioningSelection` for this turn.

        Exposes the effective, clamped conditioning V/A/D and discrete tag
        alongside the mode (Requirement 6.1 — never emit out-of-range values).
        """

        # Req 6.7: failed/unavailable extraction → neutral conditioning, turn
        # continues uninterrupted. A missing label is treated the same way.
        if not features.extraction_ok or features.label is None:
            return ConditioningSelection(
                mode="NEUTRAL",
                valence=0.0,
                arousal=0.0,
                dominance=0.0,
                tag=NEUTRAL_TAG,
            )

        # Req 6.5: distress label with confidence >= 0.50 (inclusive) → calming.
        if (
            features.label in self.distress_labels
            and features.confidence >= self.distress_confidence_threshold
        ):
            mode: ConditioningMode = "EMPATHETIC"
        else:
            # Req 6.3: condition from the V/A/D vector and dominant label.
            mode = "STANDARD"

        return ConditioningSelection(
            mode=mode,
            valence=_clamp_unit(features.valence),
            arousal=_clamp_unit(features.arousal),
            dominance=_clamp_unit(features.dominance),
            tag=features.label,
        )
