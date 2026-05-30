"""
speech/moshi_runtime/session_runtime.py — Phase 6B: session continuity + state.
================================================================================

Design note (Phase 6B, final_use.md §Phase-6 / docs/INTERFACES.md §5.1)
-----------------------------------------------------------------------
The speech-native runtime is stateful: "successive turns feel continuous and stateful".
This module owns the per-session memory the runtime carries *across* turns, independent of
whichever backend (real Moshi or CPU fallback) actually generates tokens:

* **conversational state** — a bounded history of recent turns (ids + token digests),
* **speaker state** — the active ``PersonaState`` / speaker-style reference,
* **recent emotion state** — the last few ``EmotionState`` latents with a smoothed view,
* **turn lifecycle** — start/finish/cancel bookkeeping and the *active* turn id, which the
  repair/cancel path keys off of.

It is deliberately pure data + small methods (no async, no model imports) so it is trivial
to test and so the same state survives whether inference ran on GPU or the CPU fallback.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from shared.contracts import CodecChunk, EmotionState, PersonaState

from ..codec._compat import get_logger

log = get_logger(__name__)

__all__ = ["TurnRecord", "SessionState", "SessionStore"]

# How many recent turns / emotion samples to retain per session.
DEFAULT_HISTORY = 16
DEFAULT_EMOTION_WINDOW = 8


@dataclass
class TurnRecord:
    """A compact record of one completed (or cancelled) turn."""

    turn_id: str
    n_in_chunks: int = 0
    n_out_chunks: int = 0
    started_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    ended_ms: int | None = None
    cancelled: bool = False
    emotion: EmotionState | None = None

    def duration_ms(self) -> int:
        if self.ended_ms is None:
            return 0
        return max(0, self.ended_ms - self.started_ms)


@dataclass
class SessionState:
    """All continuity state for one session."""

    session_id: str
    persona: PersonaState = field(default_factory=PersonaState)
    history: deque[TurnRecord] = field(default_factory=lambda: deque(maxlen=DEFAULT_HISTORY))
    emotion_window: deque[EmotionState] = field(
        default_factory=lambda: deque(maxlen=DEFAULT_EMOTION_WINDOW)
    )
    active_turn_id: str | None = None
    turn_counter: int = 0

    # -- emotion continuity ------------------------------------------------
    def push_emotion(self, emotion: EmotionState) -> None:
        self.emotion_window.append(emotion)

    def recent_emotion(self) -> EmotionState:
        """Smoothed view of recent emotion (mean of the window, or persona default)."""
        if not self.emotion_window:
            return self.persona.emotion
        n = len(self.emotion_window)
        return EmotionState(
            valence=sum(e.valence for e in self.emotion_window) / n,
            arousal=sum(e.arousal for e in self.emotion_window) / n,
            dominance=sum(e.dominance for e in self.emotion_window) / n,
            warmth=sum(e.warmth for e in self.emotion_window) / n,
            uncertainty=sum(e.uncertainty for e in self.emotion_window) / n,
            pace=sum(e.pace for e in self.emotion_window) / n,
            intensity=sum(e.intensity for e in self.emotion_window) / n,
            confidence=min(1.0, sum(e.confidence for e in self.emotion_window) / n),
        )

    # -- turn lifecycle ----------------------------------------------------
    def begin_turn(self, turn_id: str) -> TurnRecord:
        self.turn_counter += 1
        self.active_turn_id = turn_id
        record = TurnRecord(turn_id=turn_id)
        self.history.append(record)
        return record

    def current_record(self) -> TurnRecord | None:
        if not self.history:
            return None
        return self.history[-1]

    def end_turn(self, turn_id: str, *, cancelled: bool = False) -> None:
        rec = self.current_record()
        if rec is not None and rec.turn_id == turn_id:
            rec.ended_ms = int(time.time() * 1000)
            rec.cancelled = cancelled
        if self.active_turn_id == turn_id:
            self.active_turn_id = None

    def context_digest(self) -> dict:
        """Compact, JSON-able view of carryover context for the backend prompt/state."""
        return {
            "session_id": self.session_id,
            "persona_id": self.persona.persona_id,
            "language": self.persona.language,
            "n_turns": self.turn_counter,
            "recent_turns": [t.turn_id for t in self.history][-4:],
            "recent_emotion": self.recent_emotion().model_dump(),
        }


class SessionStore:
    """In-memory registry of :class:`SessionState`, keyed by ``session_id``.

    This is the L1 continuity cache for the runtime. Durable tiers (Redis/Postgres) live in
    ``memory/`` and are out of scope for this folder; this store only keeps the live
    conversational state the runtime needs while a session is connected.
    """

    def __init__(
        self,
        *,
        history: int = DEFAULT_HISTORY,
        emotion_window: int = DEFAULT_EMOTION_WINDOW,
    ) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._history = history
        self._emotion_window = emotion_window

    def get_or_create(self, session_id: str, persona: PersonaState | None = None) -> SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(
                session_id=session_id,
                persona=persona or PersonaState(),
                history=deque(maxlen=self._history),
                emotion_window=deque(maxlen=self._emotion_window),
            )
            self._sessions[session_id] = state
            log.info("session_created", session_id=session_id)
        elif persona is not None:
            state.persona = persona
        return state

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        if self._sessions.pop(session_id, None) is not None:
            log.info("session_dropped", session_id=session_id)

    def observe_input(self, session_id: str, chunk: CodecChunk) -> None:
        """Update continuity counters from an inbound user chunk."""
        rec = self.get_or_create(session_id).current_record()
        if rec is not None:
            rec.n_in_chunks += 1

    def observe_output(self, session_id: str, chunk: CodecChunk) -> None:
        """Update continuity counters from an outbound reply chunk."""
        rec = self.get_or_create(session_id).current_record()
        if rec is not None:
            rec.n_out_chunks += 1

    def stats(self) -> dict:
        return {
            "n_sessions": len(self._sessions),
            "sessions": {sid: s.turn_counter for sid, s in self._sessions.items()},
        }
