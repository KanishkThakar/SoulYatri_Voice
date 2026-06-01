"""
speech/moshi_runtime/repair.py — Phase 6C: cancel / rollback / restart / continuation.
=======================================================================================

Design note (Phase 6C, final_use.md §Phase-6)
---------------------------------------------
Full-duplex speech means a reply in progress can be interrupted (barge-in). The repair
controller is the small, explicit state object that makes interruption *clean and
recoverable* instead of a race:

* **cancel**   — flip the active turn's cooperative cancel flag; the generation loop
  checks it between chunks and stops promptly (no deadlock, no half-emitted chunk).
* **rollback** — record how many chunks were actually emitted before the stop, so the
  conversational state can be trimmed to the truthful "what the user actually heard".
* **restart**  — begin a fresh turn id that supersedes the cancelled one.
* **continuation** — after a clean stop, expose whether/where the runtime may resume
  (interruption-aware continuation hook) so the next turn can acknowledge the interruption
  rather than blindly repeating itself.

The controller holds no audio and no model state — it is a coordination primitive keyed by
``(session_id, turn_id)`` that the service consults on every emitted chunk.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum

from ..codec._compat import get_logger

log = get_logger(__name__)

__all__ = ["RepairAction", "TurnControl", "RepairController"]


class RepairAction(str, Enum):
    """What the repair controller decided for a turn."""

    none = "none"
    cancelled = "cancelled"
    rolled_back = "rolled_back"
    restarted = "restarted"
    continued = "continued"


@dataclass
class TurnControl:
    """Per-turn cancellation + rollback bookkeeping."""

    session_id: str
    turn_id: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    emitted_chunks: int = 0
    last_emitted_seq: int = -1
    started_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    stopped_ms: int | None = None
    action: RepairAction = RepairAction.none
    # When restarted, points at the turn id that supersedes this one.
    superseded_by: str | None = None

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def note_emit(self, seq: int) -> None:
        self.emitted_chunks += 1
        self.last_emitted_seq = seq

    def stop_budget_ms(self) -> int:
        if self.stopped_ms is None:
            return 0
        return max(0, self.stopped_ms - self.started_ms)


class RepairController:
    """Coordinates cancellation, rollback, restart and continuation across turns.

    One controller is shared per runtime instance; it tracks every in-flight turn so that a
    ``cancel(session_id, turn_id)`` from another task (the barge-in detector) reaches the
    generation loop deterministically.
    """

    def __init__(self) -> None:
        self._turns: dict[tuple[str, str], TurnControl] = {}

    # -- registration ------------------------------------------------------
    def register(self, session_id: str, turn_id: str) -> TurnControl:
        key = (session_id, turn_id)
        control = TurnControl(session_id=session_id, turn_id=turn_id)
        self._turns[key] = control
        log.info("repair_turn_registered", session_id=session_id, turn_id=turn_id)
        return control

    def get(self, session_id: str, turn_id: str) -> TurnControl | None:
        return self._turns.get((session_id, turn_id))

    def active_for_session(self, session_id: str) -> list[TurnControl]:
        return [c for (s, _), c in self._turns.items() if s == session_id and not c.cancelled]

    # -- cancel / rollback -------------------------------------------------
    def cancel(self, session_id: str, turn_id: str) -> TurnControl | None:
        """Signal cooperative cancellation for a turn. Idempotent.

        Returns the :class:`TurnControl` (or None if unknown) so the caller can read how
        much was emitted for rollback.
        """
        control = self._turns.get((session_id, turn_id))
        if control is None:
            log.warning("repair_cancel_unknown_turn", session_id=session_id, turn_id=turn_id)
            return None
        if not control.cancel_event.is_set():
            control.cancel_event.set()
            control.stopped_ms = int(time.time() * 1000)
            control.action = RepairAction.cancelled
            log.info(
                "repair_cancelled",
                session_id=session_id,
                turn_id=turn_id,
                emitted=control.emitted_chunks,
                stop_budget_ms=control.stop_budget_ms(),
            )
        return control

    def cancel_session(self, session_id: str) -> list[TurnControl]:
        """Cancel all active turns for a session (e.g. on disconnect)."""
        cancelled = []
        for control in self.active_for_session(session_id):
            self.cancel(session_id, control.turn_id)
            cancelled.append(control)
        return cancelled

    def rollback(self, session_id: str, turn_id: str) -> int:
        """Mark a cancelled turn as rolled back; return chunks that were actually emitted."""
        control = self._turns.get((session_id, turn_id))
        if control is None:
            return 0
        control.action = RepairAction.rolled_back
        log.info(
            "repair_rolled_back",
            session_id=session_id,
            turn_id=turn_id,
            emitted=control.emitted_chunks,
        )
        return control.emitted_chunks

    # -- restart / continuation -------------------------------------------
    def restart(self, session_id: str, old_turn_id: str, new_turn_id: str) -> TurnControl:
        """Supersede a cancelled turn with a fresh one and register the new turn."""
        old = self._turns.get((session_id, old_turn_id))
        if old is not None:
            old.superseded_by = new_turn_id
            old.action = RepairAction.restarted
        new_control = self.register(session_id, new_turn_id)
        log.info(
            "repair_restarted",
            session_id=session_id,
            old_turn_id=old_turn_id,
            new_turn_id=new_turn_id,
        )
        return new_control

    def continuation_point(self, session_id: str, turn_id: str) -> dict:
        """Interruption-aware continuation hook.

        Returns a small descriptor telling the next turn where the interrupted turn
        stopped, so a continuation can acknowledge it ("as I was saying…") instead of
        repeating from scratch. Pure data; the persona layer decides how to use it.
        """
        control = self._turns.get((session_id, turn_id))
        if control is None:
            return {"resumable": False, "reason": "unknown_turn"}
        if not control.cancelled:
            return {"resumable": False, "reason": "not_interrupted"}
        control.action = RepairAction.continued
        return {
            "resumable": True,
            "interrupted_turn_id": turn_id,
            "chunks_already_heard": control.emitted_chunks,
            "resume_after_seq": control.last_emitted_seq,
        }

    # -- cleanup -----------------------------------------------------------
    def release(self, session_id: str, turn_id: str) -> None:
        """Forget a finished turn's control to bound memory."""
        self._turns.pop((session_id, turn_id), None)

    def stats(self) -> dict:
        return {
            "tracked_turns": len(self._turns),
            "cancelled": sum(1 for c in self._turns.values() if c.cancelled),
        }
