"""
edge/planner/speculation.py — Speculative onset controller (Phase 8B)
=====================================================================
Owner: edge/runtime agent (final_use.md §4, Phase 8B).

Starts a safe, cancellable onset early (an acknowledgement, an empathetic filler, or a
short draft) so the user hears something quickly — then **cancels** if later evidence
conflicts. The controller guarantees that speculation is:

* subordinate to the final response (it never becomes the answer by itself),
* safe to cancel at any moment, and
* recoverable (a cancellation always yields a clean reason + state).

"Wrong speculation is rare and recoverable" (final_use.md Phase-8 acceptance): we only
speculate when route confidence clears a threshold and the chosen mode is in the safe
set, and every started speculation can be cancelled or committed exactly once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from edge.planner.short_turn import ShortTurnResult, TurnClass
from edge.session.logging_hooks import get_logger
from shared.contracts import RouteDecision, RouteTarget

logger = get_logger(__name__)

Clock = Callable[[], int]


def _default_clock() -> int:
    import time

    return int(time.monotonic() * 1000)


class SpeculationMode(str, Enum):
    """What kind of early onset to play. ``none`` means do not speculate."""

    none = "none"
    filler = "filler"
    short_answer = "short_answer"
    empathetic_filler = "empathetic_filler"


class SpeculationStatus(str, Enum):
    """Lifecycle of a single speculative onset."""

    started = "started"
    committed = "committed"     # final response confirmed the speculation; keep it.
    cancelled = "cancelled"     # conflicting evidence; roll the speculation back.


# Modes considered safe to start early (never start a long/complex draft speculatively).
_SAFE_MODES: frozenset[SpeculationMode] = frozenset(
    {SpeculationMode.none, SpeculationMode.filler, SpeculationMode.empathetic_filler, SpeculationMode.short_answer}
)


@dataclass
class SpeculativePlan:
    """A decided speculative onset (mirrors final_use.md §8B starter skeleton)."""

    mode: SpeculationMode
    can_cancel: bool = True
    confidence: float = 0.0
    phrase_id: str | None = None
    reason: str = ""
    status: SpeculationStatus = SpeculationStatus.started
    started_ms: int = 0
    resolved_ms: int | None = None

    @property
    def is_active(self) -> bool:
        return self.mode != SpeculationMode.none and self.status == SpeculationStatus.started

    @property
    def is_safe(self) -> bool:
        return self.mode in _SAFE_MODES

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "can_cancel": self.can_cancel,
            "confidence": round(self.confidence, 4),
            "phrase_id": self.phrase_id,
            "reason": self.reason,
            "status": self.status.value,
            "started_ms": self.started_ms,
            "resolved_ms": self.resolved_ms,
        }


@dataclass
class SpeculationMetrics:
    """Counts for observability + the 'wrong speculation is rare' bound."""

    started: int = 0
    committed: int = 0
    cancelled: int = 0

    @property
    def wrong_rate(self) -> float:
        if self.started == 0:
            return 0.0
        return self.cancelled / self.started

    def to_dict(self) -> dict:
        return {
            "started": self.started,
            "committed": self.committed,
            "cancelled": self.cancelled,
            "wrong_rate": round(self.wrong_rate, 4),
        }


class SpeculationController:
    """Decides, tracks, and resolves a single in-flight speculative onset per turn.

    Only one speculation may be active at a time; starting a new one while another is
    active is rejected (returns ``None``) to keep the onset path unambiguous.
    """

    def __init__(
        self,
        *,
        min_confidence: float = 0.6,
        clock: Clock = _default_clock,
    ) -> None:
        self._min_confidence = min_confidence
        self._clock = clock
        self._active: SpeculativePlan | None = None
        self._metrics = SpeculationMetrics()

    @property
    def active(self) -> SpeculativePlan | None:
        return self._active

    @property
    def metrics(self) -> SpeculationMetrics:
        return self._metrics

    def decide(self, result: ShortTurnResult) -> SpeculativePlan:
        """Decide whether/what to speculate from a short-turn classification.

        Does **not** start the speculation; it only computes the plan (so callers can
        inspect it). Use :meth:`start` to commit to playing it.
        """
        route = result.route
        mode = self._mode_for(result)
        if mode == SpeculationMode.none:
            return SpeculativePlan(
                mode=SpeculationMode.none,
                can_cancel=True,
                confidence=result.confidence,
                reason="no safe speculation for this turn",
            )
        return SpeculativePlan(
            mode=mode,
            can_cancel=True,
            confidence=result.confidence,
            phrase_id=route.phrase_id,
            reason=f"{result.turn_class.value} turn, route={route.route.value}",
        )

    def _mode_for(self, result: ShortTurnResult) -> SpeculationMode:
        route = result.route
        # Never speculate when we are uncertain — that is the whole point of the gate.
        if result.turn_class == TurnClass.uncertain:
            return SpeculationMode.none
        if result.confidence < self._min_confidence and route.route != RouteTarget.cached_filler:
            return SpeculationMode.none
        if result.turn_class == TurnClass.emotional:
            return SpeculationMode.empathetic_filler
        if route.route == RouteTarget.cached_filler:
            return SpeculationMode.filler
        if result.turn_class == TurnClass.short:
            return SpeculationMode.short_answer
        if route.emit_filler_then_forward:
            return SpeculationMode.filler
        return SpeculationMode.none

    def start(self, plan: SpeculativePlan) -> SpeculativePlan | None:
        """Begin a speculation. Returns the started plan, or None if it cannot start.

        Rejects starting when: the mode is ``none``, the mode is unsafe, or another
        speculation is already active.
        """
        if plan.mode == SpeculationMode.none or not plan.is_safe:
            return None
        if self._active is not None and self._active.is_active:
            logger.warning("speculation_already_active", active_mode=self._active.mode.value)
            return None
        plan.status = SpeculationStatus.started
        plan.started_ms = self._clock()
        plan.resolved_ms = None
        self._active = plan
        self._metrics.started += 1
        logger.info(
            "speculation_started",
            mode=plan.mode.value,
            confidence=round(plan.confidence, 3),
            phrase_id=plan.phrase_id,
        )
        return plan

    def cancel(self, reason: str = "conflicting_evidence") -> SpeculativePlan | None:
        """Cancel the active speculation (e.g. later evidence conflicts). Idempotent."""
        if self._active is None or not self._active.is_active:
            return None
        plan = self._active
        plan.status = SpeculationStatus.cancelled
        plan.resolved_ms = self._clock()
        plan.reason = reason
        self._metrics.cancelled += 1
        logger.info("speculation_cancelled", mode=plan.mode.value, reason=reason)
        self._active = None
        return plan

    def commit(self) -> SpeculativePlan | None:
        """Commit the active speculation (final response agreed with it). Idempotent."""
        if self._active is None or not self._active.is_active:
            return None
        plan = self._active
        plan.status = SpeculationStatus.committed
        plan.resolved_ms = self._clock()
        self._metrics.committed += 1
        logger.info("speculation_committed", mode=plan.mode.value)
        self._active = None
        return plan

    def reconcile(self, final_route: RouteDecision) -> SpeculativePlan | None:
        """Reconcile the active speculation against the final routing decision.

        If the final route is compatible with what we speculated, commit; otherwise
        cancel. This is the "cancel if later evidence conflicts" rule, made explicit.
        Returns the resolved plan (committed or cancelled), or None if nothing active.
        """
        if self._active is None or not self._active.is_active:
            return None
        spec = self._active
        compatible = self._is_compatible(spec.mode, final_route)
        if compatible:
            return self.commit()
        return self.cancel(reason=f"final_route={final_route.route.value} conflicts with {spec.mode.value}")

    @staticmethod
    def _is_compatible(mode: SpeculationMode, final_route: RouteDecision) -> bool:
        if final_route.route == RouteTarget.silent_wait:
            # The final decision was to stay silent → any spoken onset conflicts.
            return False
        if mode == SpeculationMode.filler:
            return final_route.route in (RouteTarget.cached_filler, RouteTarget.full_stack)
        if mode == SpeculationMode.empathetic_filler:
            return final_route.route in (RouteTarget.cached_filler, RouteTarget.full_stack)
        if mode == SpeculationMode.short_answer:
            # A short answer is only safe to keep if the final answer is also short/full.
            return final_route.route == RouteTarget.full_stack and final_route.intent.startswith("short")
        return False

    def reset(self) -> None:
        """Drop any active speculation without recording a commit/cancel (new turn)."""
        self._active = None
