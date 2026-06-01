"""
speech/persona/relationship.py — Relationship memory store (final_use.md §9C).
==============================================================================
Phase 9C goal: *store user tone preference, preferred response length, calm/stress
trajectory, recent emotional context* such that **future turns adapt audibly to prior
interaction style**.

This is a small, focused per-session store — distinct from the durable tiered memory in
``memory/`` (Phase 12). It keeps just enough relational signal to make the persona layer
adaptive turn-to-turn:

* ``tone_preference``  — exponential-moving-average of warmth/intensity the user responds
  well to (a smoothed target affect),
* ``preferred_response_length`` — EMA of an observed/estimated reply length,
* ``calm_stress_trajectory`` — recent arousal samples (a calm↔stress signal over time),
* ``recent_emotional_context`` — a bounded ring buffer of recent ``EmotionState``s.

Backend is pluggable behind ``RelationshipBackend`` (a Protocol); the default
``InMemoryRelationshipBackend`` is dependency-light and CPU-only. A Redis/Postgres-backed
implementation (Phase 12) can be injected later without touching callers.

The store exposes ``adapt_emotion`` so the persona controller can bias a *target* emotion
toward the learned interaction style — this is the "future turns adapt" behavior.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from shared.contracts import EmotionState

from . import emotion_schema as es
from .logging_hooks import get_logger

__all__ = [
    "RelationshipProfile",
    "RelationshipBackend",
    "InMemoryRelationshipBackend",
    "RelationshipStore",
]

log = get_logger(__name__)

#: How many recent emotions / arousal samples to retain per session.
_DEFAULT_HISTORY = 8
#: EMA smoothing factor for tone + length adaptation (0 slow … 1 instant).
_DEFAULT_ALPHA = 0.3


# ---------------------------------------------------------------------------
# Profile data model (plain dataclass — no pydantic needed, stays light)
# ---------------------------------------------------------------------------
@dataclass
class RelationshipProfile:
    """Per-session relational state that future turns adapt to.

    All fields have safe neutral defaults so a brand-new session behaves predictably.
    """

    session_id: str
    #: Smoothed target affect the user responds well to (warmth/intensity/valence carrier).
    tone_preference: EmotionState = field(default_factory=EmotionState)
    #: EMA of preferred reply length in (approx) words; None until first observation.
    preferred_response_length: float | None = None
    #: Recent arousal samples in chronological order (calm↔stress over time).
    calm_stress_trajectory: list[float] = field(default_factory=list)
    #: Recent emotional context as serialized EmotionState dicts (most recent last).
    recent_emotional_context: list[dict[str, Any]] = field(default_factory=list)
    #: Number of turns observed for this session.
    turns: int = 0

    def stress_level(self) -> float:
        """Mean recent arousal mapped to [0, 1] (0 calm … 1 stressed).

        Arousal is bipolar [-1, 1]; we map to [0, 1]. Empty trajectory → 0.5 (neutral).
        """
        if not self.calm_stress_trajectory:
            return 0.5
        mean_arousal = sum(self.calm_stress_trajectory) / len(self.calm_stress_trajectory)
        return es.clamp_unit((mean_arousal + 1.0) / 2.0)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot of the profile."""
        return {
            "session_id": self.session_id,
            "tone_preference": es.to_dict(self.tone_preference, round_to=4),
            "preferred_response_length": self.preferred_response_length,
            "calm_stress_trajectory": list(self.calm_stress_trajectory),
            "recent_emotional_context": list(self.recent_emotional_context),
            "turns": self.turns,
            "stress_level": round(self.stress_level(), 4),
        }


# ---------------------------------------------------------------------------
# Pluggable backend interface + in-memory default
# ---------------------------------------------------------------------------
@runtime_checkable
class RelationshipBackend(Protocol):
    """Pluggable persistence for :class:`RelationshipProfile` objects.

    A production backend wraps Redis (hot) / Postgres (durable) from Phase 12. The store
    layer holds all adaptation logic, so a backend only needs get/put/clear.
    """

    def get(self, session_id: str) -> RelationshipProfile | None:
        """Return the stored profile for ``session_id`` or None."""
        ...

    def put(self, profile: RelationshipProfile) -> None:
        """Persist ``profile``."""
        ...

    def clear(self, session_id: str) -> None:
        """Remove any stored profile for ``session_id``."""
        ...


class InMemoryRelationshipBackend:
    """Thread-safe, process-local backend. Dependency-light; CPU-only; no weights."""

    def __init__(self) -> None:
        self._data: dict[str, RelationshipProfile] = {}
        self._lock = threading.RLock()

    def get(self, session_id: str) -> RelationshipProfile | None:
        with self._lock:
            return self._data.get(session_id)

    def put(self, profile: RelationshipProfile) -> None:
        with self._lock:
            self._data[profile.session_id] = profile

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)


# ---------------------------------------------------------------------------
# Relationship store (adaptation logic lives here)
# ---------------------------------------------------------------------------
class RelationshipStore:
    """Tracks and adapts per-session interaction style across turns.

    Usage:
        >>> store = RelationshipStore()
        >>> store.observe_turn("s1", user_emotion=EmotionState(arousal=0.8), response_length=40)
        >>> target = store.adapt_emotion("s1", EmotionState(warmth=0.5))  # biased to history
    """

    def __init__(
        self,
        backend: RelationshipBackend | None = None,
        *,
        history: int = _DEFAULT_HISTORY,
        alpha: float = _DEFAULT_ALPHA,
    ) -> None:
        self._backend: RelationshipBackend = backend or InMemoryRelationshipBackend()
        self._history = max(1, int(history))
        self._alpha = es.clamp_unit(alpha)

    # -- accessors ----------------------------------------------------------
    def get_profile(self, session_id: str) -> RelationshipProfile:
        """Return the existing profile or a fresh neutral one (not yet persisted)."""
        existing = self._backend.get(session_id)
        return existing if existing is not None else RelationshipProfile(session_id=session_id)

    # -- observation / update ----------------------------------------------
    def observe_turn(
        self,
        session_id: str,
        *,
        user_emotion: EmotionState | None = None,
        response_length: float | int | None = None,
        tone_target: EmotionState | None = None,
    ) -> RelationshipProfile:
        """Update the session profile from one interaction and persist it.

        Args:
            session_id: Session key.
            user_emotion: The user's detected affect this turn (drives calm/stress + tone).
            response_length: Observed/preferred reply length (approx words) this turn.
            tone_target: Optional explicit tone preference signal; defaults to
                ``user_emotion`` when omitted.

        Returns:
            The updated, persisted :class:`RelationshipProfile`.
        """
        profile = self.get_profile(session_id)
        profile.turns += 1

        # --- tone preference: EMA toward the observed tone signal ---
        signal = tone_target or user_emotion
        if signal is not None:
            signal = es.clamp_emotion(signal)
            if profile.turns <= 1:
                profile.tone_preference = signal
            else:
                profile.tone_preference = es.blend(
                    profile.tone_preference, signal, weight=self._alpha
                )

        # --- preferred response length: EMA ---
        if response_length is not None:
            length = max(0.0, float(response_length))
            if profile.preferred_response_length is None:
                profile.preferred_response_length = length
            else:
                profile.preferred_response_length = (
                    1.0 - self._alpha
                ) * profile.preferred_response_length + self._alpha * length

        # --- calm/stress trajectory + recent emotional context (ring buffers) ---
        if user_emotion is not None:
            ue = es.clamp_emotion(user_emotion)
            traj = deque(profile.calm_stress_trajectory, maxlen=self._history)
            traj.append(round(ue.arousal, 4))
            profile.calm_stress_trajectory = list(traj)

            recent = deque(profile.recent_emotional_context, maxlen=self._history)
            recent.append(es.to_dict(ue, round_to=4))
            profile.recent_emotional_context = list(recent)

        self._backend.put(profile)
        log.info(
            "relationship_observed",
            session_id=session_id,
            turns=profile.turns,
            stress_level=round(profile.stress_level(), 3),
            preferred_response_length=profile.preferred_response_length,
        )
        return profile

    # -- adaptation ---------------------------------------------------------
    def adapt_emotion(
        self,
        session_id: str,
        target: EmotionState,
        *,
        adapt_weight: float = 0.5,
    ) -> EmotionState:
        """Bias a *target* emotion toward the session's learned tone preference.

        Early on (no history) this returns the target unchanged. As the relationship
        accrues, the returned emotion blends toward the learned tone — and, when the user
        is reading as stressed, nudges warmth up / arousal down to sound calmer. This is the
        audible "future turns adapt to prior interaction style" behavior.

        Pure with respect to inputs given a fixed stored profile; does not mutate state.

        Args:
            session_id: Session key.
            target: The emotion the persona layer wants for this turn.
            adapt_weight: How strongly to pull toward learned tone (0 → ignore history).

        Returns:
            An adapted, clamped :class:`EmotionState`.
        """
        target = es.clamp_emotion(target)
        profile = self._backend.get(session_id)
        if profile is None or profile.turns == 0:
            return target

        adapted = es.blend(target, profile.tone_preference, weight=adapt_weight)

        # If the user has been stressed, lean calmer + warmer (de-escalation).
        stress = profile.stress_level()
        if stress > 0.6:
            calm_strength = (stress - 0.6) / 0.4  # 0..1 over the stressed band
            adapted = es.nudge(
                adapted,
                warmth=+0.2 * calm_strength,
                arousal=-0.3 * calm_strength,
                intensity=-0.1 * calm_strength,
            )

        log.info(
            "relationship_adapted",
            session_id=session_id,
            stress_level=round(stress, 3),
            warmth=round(adapted.warmth, 3),
            arousal=round(adapted.arousal, 3),
        )
        return adapted

    def reset(self, session_id: str) -> None:
        """Forget a session's relationship state."""
        self._backend.clear(session_id)
        log.info("relationship_reset", session_id=session_id)
