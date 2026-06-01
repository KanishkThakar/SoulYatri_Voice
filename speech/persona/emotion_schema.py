"""
speech/persona/emotion_schema.py — Emotion latent schema helpers (final_use.md §9A).
====================================================================================
Phase 9A goal: *define valence/arousal/dominance plus warmth, uncertainty, pace,
intensity controls; controls serialize cleanly and can be attached to turn context.*

This module is a thin, dependency-light helper layer **built on**
``shared.contracts.EmotionState`` — it does NOT redefine the schema. ``EmotionState`` is
the single source of truth (docs/INTERFACES.md §3.1); here we add:

* range metadata (the canonical [-1,1] vs [0,1] split) in one place,
* ``clamp_emotion`` / ``make_emotion`` — build a *valid* state from arbitrary numbers by
  clamping out-of-range values instead of raising (useful when fusing model outputs),
* ``blend`` / ``nudge`` — pure functions for smoothing affect across turns,
* serialization helpers (``to_dict`` / ``from_dict`` / ``to_json`` / ``from_json``) that
  round-trip through pydantic, and
* ``attach_to_turn_context`` — fold an ``EmotionState`` into a turn-context dict so the
  edge/runtime can carry affect alongside ``turn_id`` / ``session_id``.

Everything is CPU-only, pure-Python, and imports without torch/numpy/transformers.
"""

from __future__ import annotations

import json
import math
from typing import Any

from shared.contracts import EmotionState

from .logging_hooks import get_logger

__all__ = [
    "BIPOLAR_FIELDS",
    "UNIPOLAR_FIELDS",
    "EMOTION_FIELDS",
    "field_range",
    "clamp_unit",
    "clamp_value",
    "clamp_emotion",
    "make_emotion",
    "blend",
    "nudge",
    "to_dict",
    "from_dict",
    "to_json",
    "from_json",
    "attach_to_turn_context",
    "emotion_from_turn_context",
]

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Field taxonomy — kept consistent with shared.contracts.EmotionState and the
# V/A/D representation in server/pipeline/emotion.py.
# ---------------------------------------------------------------------------
#: Dimensions in [-1, 1] (the V/A/D core shared with server/pipeline/emotion.py).
BIPOLAR_FIELDS: tuple[str, ...] = ("valence", "arousal", "dominance")

#: Control scalars in [0, 1] (the persona delivery knobs added in Phase 9A).
UNIPOLAR_FIELDS: tuple[str, ...] = ("warmth", "uncertainty", "pace", "intensity", "confidence")

#: All numeric emotion fields, in a stable order for deterministic serialization.
EMOTION_FIELDS: tuple[str, ...] = BIPOLAR_FIELDS + UNIPOLAR_FIELDS


def field_range(field: str) -> tuple[float, float]:
    """Return the valid ``(lo, hi)`` range for an emotion field.

    Bipolar V/A/D dims are [-1, 1]; the control scalars are [0, 1].
    """
    if field in BIPOLAR_FIELDS:
        return (-1.0, 1.0)
    if field in UNIPOLAR_FIELDS:
        return (0.0, 1.0)
    raise KeyError(f"unknown emotion field: {field!r}")


# ---------------------------------------------------------------------------
# Clamping / validation
# ---------------------------------------------------------------------------
def _finite(x: float, default: float) -> float:
    """Coerce NaN / inf to ``default`` so downstream math never explodes."""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return default
    if math.isnan(xf) or math.isinf(xf):
        return default
    return xf


def clamp_unit(x: float) -> float:
    """Clamp a value into [0, 1]."""
    return clamp_value(x, 0.0, 1.0)


def clamp_value(x: float, lo: float, hi: float) -> float:
    """Clamp a (possibly non-finite) value into ``[lo, hi]``."""
    xf = _finite(x, lo)
    if xf < lo:
        return lo
    if xf > hi:
        return hi
    return xf


def clamp_emotion(emotion: EmotionState | dict[str, Any]) -> EmotionState:
    """Return a new ``EmotionState`` with every numeric field clamped into range.

    Unlike ``EmotionState(**raw)`` (which *raises* on out-of-range input), this accepts
    arbitrary numbers — e.g. raw model logits or fused estimates — and squeezes them into
    valid ranges. Out-of-range corrections are logged for observability.

    Args:
        emotion: An ``EmotionState`` or a plain dict of field values.

    Returns:
        A validated ``EmotionState`` guaranteed to be in range.
    """
    raw: dict[str, Any] = (
        emotion.model_dump() if isinstance(emotion, EmotionState) else dict(emotion)
    )

    cleaned: dict[str, Any] = {}
    corrections: dict[str, tuple[float, float]] = {}
    for field in EMOTION_FIELDS:
        if field not in raw or raw[field] is None:
            continue
        lo, hi = field_range(field)
        original = _finite(raw[field], lo)
        clamped = clamp_value(original, lo, hi)
        cleaned[field] = clamped
        if abs(clamped - original) > 1e-9:
            corrections[field] = (original, clamped)

    # Preserve the optional discrete label tag untouched.
    if raw.get("label") is not None:
        cleaned["label"] = raw["label"]

    if corrections:
        log.info(
            "emotion_clamped",
            corrections={k: [round(o, 4), round(c, 4)] for k, (o, c) in corrections.items()},
        )

    return EmotionState(**cleaned)


def make_emotion(**values: Any) -> EmotionState:
    """Build a clamped ``EmotionState`` from keyword field values.

    Convenience wrapper over :func:`clamp_emotion` for ad-hoc construction, e.g.
    ``make_emotion(valence=2.0, warmth=0.9)`` → ``valence`` clamped to ``1.0``.
    """
    return clamp_emotion(values)


# ---------------------------------------------------------------------------
# Pure-function affect transforms (used for smoothing across turns)
# ---------------------------------------------------------------------------
def blend(a: EmotionState, b: EmotionState, weight: float = 0.5) -> EmotionState:
    """Linearly interpolate two emotion states.

    ``weight`` is the blend toward ``b`` (0.0 → all ``a``, 1.0 → all ``b``). Out-of-range
    weights are clamped. The result is re-clamped so it always stays valid.

    Pure and deterministic — same inputs always yield the same output.
    """
    w = clamp_unit(weight)
    da, db = a.model_dump(), b.model_dump()
    mixed: dict[str, Any] = {}
    for field in EMOTION_FIELDS:
        av = da.get(field)
        bv = db.get(field)
        if av is None or bv is None:
            continue
        mixed[field] = av * (1.0 - w) + bv * w
    return clamp_emotion(mixed)


def nudge(emotion: EmotionState, **deltas: float) -> EmotionState:
    """Return a copy of ``emotion`` with per-field additive deltas, then re-clamped.

    Example: ``nudge(state, warmth=+0.1, arousal=-0.2)``. Unknown fields raise ``KeyError``
    so typos surface early.
    """
    data = emotion.model_dump()
    for field, delta in deltas.items():
        if field not in EMOTION_FIELDS:
            raise KeyError(f"unknown emotion field: {field!r}")
        data[field] = _finite(data.get(field, 0.0), 0.0) + float(delta)
    return clamp_emotion(data)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def to_dict(emotion: EmotionState, *, round_to: int | None = None) -> dict[str, Any]:
    """Serialize an ``EmotionState`` to a JSON-safe dict.

    Args:
        emotion: The state to serialize.
        round_to: Optional decimal places to round floats to (handy for stable logs).
    """
    data = emotion.model_dump()
    if round_to is not None:
        for field in EMOTION_FIELDS:
            if isinstance(data.get(field), (int, float)):
                data[field] = round(float(data[field]), round_to)
    return data


def from_dict(data: dict[str, Any], *, clamp: bool = True) -> EmotionState:
    """Rebuild an ``EmotionState`` from a dict.

    Args:
        data: Field mapping (e.g. produced by :func:`to_dict`).
        clamp: When True (default) out-of-range values are clamped rather than rejected.
    """
    return clamp_emotion(data) if clamp else EmotionState.model_validate(data)


def to_json(emotion: EmotionState, *, round_to: int | None = None) -> str:
    """Serialize an ``EmotionState`` to a JSON string (stable key order)."""
    return json.dumps(to_dict(emotion, round_to=round_to), sort_keys=True)


def from_json(blob: str, *, clamp: bool = True) -> EmotionState:
    """Parse a JSON string into an ``EmotionState`` (clamped by default)."""
    return from_dict(json.loads(blob), clamp=clamp)


# ---------------------------------------------------------------------------
# Turn-context attachment
# ---------------------------------------------------------------------------
#: Key under which the serialized emotion lives inside a turn-context dict.
TURN_CONTEXT_KEY = "emotion"


def attach_to_turn_context(
    context: dict[str, Any] | None,
    emotion: EmotionState,
    *,
    round_to: int | None = 4,
) -> dict[str, Any]:
    """Fold an ``EmotionState`` into a (copied) turn-context dict.

    Returns a NEW dict (does not mutate the input) so callers can keep an immutable record
    of the per-turn context. The emotion lives under :data:`TURN_CONTEXT_KEY`.

    Args:
        context: Existing turn context (``turn_id``, ``session_id``, …) or None.
        emotion: Affect to attach.
        round_to: Decimal rounding for the serialized emotion (default 4).
    """
    out: dict[str, Any] = dict(context or {})
    out[TURN_CONTEXT_KEY] = to_dict(emotion, round_to=round_to)
    log.debug(
        "emotion_attached_to_turn",
        turn_id=out.get("turn_id"),
        session_id=out.get("session_id"),
    )
    return out


def emotion_from_turn_context(context: dict[str, Any], *, clamp: bool = True) -> EmotionState:
    """Recover the ``EmotionState`` previously stored by :func:`attach_to_turn_context`.

    Falls back to a neutral default ``EmotionState`` if no emotion is present.
    """
    raw = context.get(TURN_CONTEXT_KEY)
    if not raw:
        return EmotionState()
    return from_dict(raw, clamp=clamp)
