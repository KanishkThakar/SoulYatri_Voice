"""
speech/persona/controller.py — Persona controller + FiLM conditioning (final_use.md §9B).
=========================================================================================
Phase 9B goal: *implement persona IDs, speaker-style embedding fusion, response-style
shaping* such that **output varies in emotion while preserving identity**.

Design split:

* **Identity** (who the assistant *is*) is carried by ``PersonaState.persona_id`` +
  ``speaker_style_ref`` (a consent-gated speaker-style embedding reference). It is stable
  across turns.
* **Affect** (how the assistant *sounds right now*) is carried by ``EmotionState`` and
  varies turn-to-turn.

The controller never mutates ``persona_id`` while shaping emotion, which is exactly the
"same character, adaptive delivery" property Phase 9 requires.

Heavy speaker-embedding models (ECAPA-TDNN) are **not** imported here. Instead we define a
``StyleEmbeddingProvider`` interface and ship a deterministic, dependency-light
``HashStyleEmbeddingProvider`` fallback so everything imports and tests run on CPU with no
weights (DECISIONS.md D-008). A real ECAPA provider can be injected later behind the same
interface.

FiLM conditioning
-----------------
``film_conditioning(emotion)`` is a **pure function** ``EmotionState → FiLMParams`` that a
downstream decoder/runtime can consume. FiLM ("Feature-wise Linear Modulation") applies an
affine transform ``y = gamma * x + beta`` per feature channel. We map the affect latents to
deterministic ``gamma`` (scale) and ``beta`` (shift) vectors plus a small set of named
delivery controls (rate/pitch/energy). Same emotion in → identical params out.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from shared.contracts import EmotionState, PersonaState

from . import emotion_schema as es
from .logging_hooks import get_logger

__all__ = [
    "DEFAULT_PERSONA_ID",
    "FILM_FEATURE_DIM",
    "StyleEmbeddingProvider",
    "HashStyleEmbeddingProvider",
    "FiLMParams",
    "film_conditioning",
    "PersonaController",
]

log = get_logger(__name__)

#: The stable default assistant identity (matches PersonaState's default).
DEFAULT_PERSONA_ID = "default"

#: Dimensionality of the FiLM gamma/beta vectors the decoder consumes. Kept small and
#: fixed so the conditioning contract is stable for the decoder/runtime teams.
FILM_FEATURE_DIM = 8

#: Dimensionality of the deterministic fallback style embedding.
_STYLE_EMBED_DIM = 16


# ---------------------------------------------------------------------------
# Speaker-style embedding fusion: interface + deterministic fallback
# ---------------------------------------------------------------------------
@runtime_checkable
class StyleEmbeddingProvider(Protocol):
    """Maps a ``speaker_style_ref`` id to a fixed-length style embedding.

    A real implementation wraps ECAPA-TDNN (final_use.md §2.2). The reference id is
    consent-gated upstream by ``safety/voice_policy`` — this layer only consumes the id.
    """

    @property
    def dim(self) -> int:
        """Embedding dimensionality."""
        ...

    def embed(self, style_ref: str | None) -> list[float]:
        """Return the style embedding for ``style_ref`` (neutral vector if None)."""
        ...


class HashStyleEmbeddingProvider:
    """Deterministic, CPU-only fallback ``StyleEmbeddingProvider``.

    Produces a stable pseudo-embedding from a hash of the reference id. It carries **no**
    real speaker information (so it is privacy-safe and needs no weights), but it is
    deterministic: the same ``style_ref`` always yields the same vector, which is enough to
    exercise fusion logic and keep identity stable across turns.
    """

    def __init__(self, dim: int = _STYLE_EMBED_DIM) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, style_ref: str | None) -> list[float]:
        if not style_ref:
            # Neutral (zero) embedding for the default voice.
            return [0.0] * self._dim
        digest = hashlib.sha256(style_ref.encode("utf-8")).digest()
        vec: list[float] = []
        for i in range(self._dim):
            # Map each byte to [-1, 1] deterministically.
            b = digest[i % len(digest)]
            vec.append((b / 255.0) * 2.0 - 1.0)
        return vec


# ---------------------------------------------------------------------------
# FiLM conditioning (pure EmotionState → params mapping)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FiLMParams:
    """Feature-wise Linear Modulation params for the downstream decoder/runtime.

    The decoder applies ``y = gamma * x + beta`` per channel. ``controls`` exposes a few
    human-readable delivery knobs derived from the same affect latents so a non-FiLM
    decoder can still consume something meaningful.

    Frozen + value-equal: two FiLMParams built from the same emotion compare equal, which
    is what the determinism test asserts.
    """

    gamma: tuple[float, ...]
    beta: tuple[float, ...]
    controls: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """JSON-safe serialization for logging / passing across the decoder boundary."""
        return {
            "gamma": list(self.gamma),
            "beta": list(self.beta),
            "controls": dict(self.controls),
        }


def _spread(value: float, dim: int, phase: float) -> list[float]:
    """Spread a scalar across ``dim`` channels deterministically with a cosine pattern.

    This gives each FiLM channel a distinct but reproducible response to the scalar,
    avoiding a flat vector while remaining a pure function of the inputs.
    """
    out: list[float] = []
    for i in range(dim):
        # Cosine basis keeps values bounded in [-value, value]; phase de-correlates fields.
        out.append(value * math.cos(phase + (math.pi * i) / dim))
    return out


def film_conditioning(emotion: EmotionState, *, dim: int = FILM_FEATURE_DIM) -> FiLMParams:
    """Pure function mapping an ``EmotionState`` to :class:`FiLMParams`.

    Deterministic and side-effect free: identical ``emotion`` always yields identical
    params (asserted by the conditioning-determinism test). The mapping is intentionally
    simple and documented so the decoder/runtime teams can rely on it:

    * ``gamma`` (scale) is driven by **intensity** and **arousal** — more activation →
      wider feature scaling, centered around 1.0.
    * ``beta`` (shift) is driven by **valence** and **warmth** — pleasantness/warmth shift
      the feature bias positive.
    * ``controls`` exposes named delivery knobs (rate/pitch/energy/warmth/uncertainty)
      derived from pace/arousal/valence/dominance for non-FiLM consumers.

    Args:
        emotion: Target affect for the turn (clamped defensively before use).
        dim: FiLM feature dimensionality (defaults to :data:`FILM_FEATURE_DIM`).

    Returns:
        Deterministic :class:`FiLMParams`.
    """
    e = es.clamp_emotion(emotion)

    # Scale around 1.0: neutral emotion → gamma ~ 1.0 (identity-ish modulation).
    scale_mag = 0.5 * (e.intensity + (e.arousal + 1.0) / 2.0)  # in [0, 1]
    gamma = tuple(1.0 + s for s in _spread(scale_mag, dim, phase=0.0))

    # Shift driven by valence + warmth: positive affect → positive bias.
    shift_mag = 0.5 * (e.valence + (e.warmth * 2.0 - 1.0))  # in [-1, 1]
    beta = tuple(_spread(shift_mag, dim, phase=math.pi / 4.0))

    controls = {
        # Speaking rate target: pace plus a touch of arousal energy → [0, 1].
        "rate": es.clamp_unit(0.5 * e.pace + 0.5 * ((e.arousal + 1.0) / 2.0)),
        # Pitch lift from arousal+valence, mapped to [0, 1] around 0.5 neutral.
        "pitch": es.clamp_unit(0.5 + 0.25 * e.arousal + 0.25 * e.valence),
        # Vocal energy from intensity+arousal.
        "energy": es.clamp_unit(0.5 * e.intensity + 0.5 * ((e.arousal + 1.0) / 2.0)),
        # Pass-through delivery knobs the decoder may use directly.
        "warmth": e.warmth,
        "uncertainty": e.uncertainty,
        # Assertiveness from dominance, mapped to [0, 1].
        "assertiveness": es.clamp_unit((e.dominance + 1.0) / 2.0),
    }
    controls = {k: round(v, 6) for k, v in controls.items()}

    return FiLMParams(
        gamma=tuple(round(g, 6) for g in gamma),
        beta=tuple(round(b, 6) for b in beta),
        controls=controls,
    )


# ---------------------------------------------------------------------------
# Persona controller
# ---------------------------------------------------------------------------
class PersonaController:
    """Shapes per-turn delivery while preserving a stable assistant identity.

    Responsibilities (Phase 9B):

    * own the stable ``persona_id`` and (consent-gated) ``speaker_style_ref``,
    * fuse a speaker-style embedding via an injectable :class:`StyleEmbeddingProvider`
      (deterministic hash fallback by default),
    * shape response style by attaching/blending an ``EmotionState`` onto a
      ``PersonaState`` **without ever changing the identity fields**, and
    * expose :meth:`conditioning` → :class:`FiLMParams` for the decoder/runtime.
    """

    def __init__(
        self,
        persona_id: str = DEFAULT_PERSONA_ID,
        *,
        speaker_style_ref: str | None = None,
        language: str = "hinglish",
        style_provider: StyleEmbeddingProvider | None = None,
    ) -> None:
        self.persona_id = persona_id
        self.speaker_style_ref = speaker_style_ref
        self.language = language
        self._style_provider: StyleEmbeddingProvider = (
            style_provider or HashStyleEmbeddingProvider()
        )
        log.info(
            "persona_controller_init",
            persona_id=persona_id,
            has_style_ref=speaker_style_ref is not None,
            language=language,
        )

    # -- speaker-style embedding fusion ------------------------------------
    def style_embedding(self) -> list[float]:
        """Return the (fused) speaker-style embedding for this persona's identity."""
        return self._style_provider.embed(self.speaker_style_ref)

    def fuse_style(
        self, emotion_embedding: Sequence[float], *, style_weight: float = 0.5
    ) -> list[float]:
        """Fuse a per-turn emotion embedding with the stable speaker-style embedding.

        The identity (style) component is a fixed function of ``speaker_style_ref`` and the
        same on every turn; only the emotion component varies. ``style_weight`` controls the
        identity/affect mix and is clamped to [0, 1].

        Returns a vector of length ``max(len(style), len(emotion_embedding))`` (zero-padded).
        """
        w = es.clamp_unit(style_weight)
        style = self.style_embedding()
        emo = list(emotion_embedding)
        n = max(len(style), len(emo))
        style += [0.0] * (n - len(style))
        emo += [0.0] * (n - len(emo))
        return [w * style[i] + (1.0 - w) * emo[i] for i in range(n)]

    # -- response-style shaping --------------------------------------------
    def shape(
        self,
        emotion: EmotionState | None = None,
        *,
        base: PersonaState | None = None,
        blend_weight: float | None = None,
    ) -> PersonaState:
        """Produce a ``PersonaState`` for a turn with the given target ``emotion``.

        Identity is always taken from this controller (``persona_id`` / ``speaker_style_ref``
        / ``language``) regardless of any identity fields on ``base`` — so emotion can vary
        freely while the assistant stays the same character.

        Args:
            emotion: Target affect (defaults to neutral). Clamped defensively.
            base: Optional previous ``PersonaState`` to blend emotion from (continuity).
            blend_weight: When ``base`` is given, weight toward the new ``emotion``
                (0 → keep base affect, 1 → all new). Defaults to a full switch (1.0).

        Returns:
            A new ``PersonaState`` with stable identity and shaped emotion.
        """
        target = es.clamp_emotion(emotion) if emotion is not None else EmotionState()

        if base is not None and blend_weight is not None:
            target = es.blend(base.emotion, target, weight=blend_weight)

        shaped = PersonaState(
            persona_id=self.persona_id,
            speaker_style_ref=self.speaker_style_ref,
            emotion=target,
            language=self.language,
        )
        log.info(
            "persona_shaped",
            persona_id=shaped.persona_id,
            valence=round(shaped.emotion.valence, 3),
            arousal=round(shaped.emotion.arousal, 3),
            warmth=round(shaped.emotion.warmth, 3),
        )
        return shaped

    def preserves_identity(self, a: PersonaState, b: PersonaState) -> bool:
        """True iff two persona states share this controller's stable identity."""
        return (
            a.persona_id == b.persona_id == self.persona_id
            and a.speaker_style_ref == b.speaker_style_ref == self.speaker_style_ref
        )

    # -- decoder/runtime conditioning hook ---------------------------------
    def conditioning(self, persona: PersonaState, *, dim: int = FILM_FEATURE_DIM) -> FiLMParams:
        """Return FiLM conditioning for a shaped ``PersonaState`` (decoder/runtime hook)."""
        return film_conditioning(persona.emotion, dim=dim)
