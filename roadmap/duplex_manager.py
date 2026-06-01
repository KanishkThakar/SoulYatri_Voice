"""Duplex Manager barge-in decision logic.

This module is the *roadmap planning* counterpart to the runtime
``server/pipeline/barge_in.py`` + ``server/pipeline/turn_state.py`` components.
The design document ("Duplex Manager") describes the runtime Duplex_Manager as
the evolution of those two files into full-duplex turn-taking; this module is a
fresh, **pure decision-logic** component that captures the *timing rules* of
that design so they can be verified by property-based tests without any real
wall-clock or audio I/O.

Everything here is deterministic and clock-injected. No module-level code reads
the wall clock, sleeps, or touches audio buffers. A caller either:

- injects a *simulated clock* (a zero-argument callable returning "now" in
  milliseconds), or
- passes an explicit ``detection_time_ms`` for each decision.

Time convention
---------------
**All timestamps and durations in this module are expressed in milliseconds
(float).** This mirrors the requirement language directly (150 ms of voiced
speech, suppression within 200 ms, listening transition within 100 ms).

Barge-in rule (Requirements 7.4, 7.5)
-------------------------------------
When at least ``150 ms`` of voiced user speech is detected while the platform is
producing audio (or is in an intermediate/processing state, including while it
is already handling a prior interruption), the manager raises a barge-in:

- output suppression is scheduled to occur **within 200 ms** of detection, and
- the turn state transitions to ``LISTENING`` **within 100 ms** of detection.

The decision is reported as a :class:`BargeInDecision` carrying the scheduled
deadlines and the resulting state, so a property test can assert the deadlines
never exceed their budgets.

.. note::
   Task 18.1 adds *latency-only fallback discrimination* to this same module
   via :meth:`DuplexManager.decide_latency_fallback`. It is a sibling decision
   to the barge-in logic: it reuses the injectable :class:`DuplexConfig` (which
   carries the ``300 ms`` ``first_response_budget_ms``) and does not disturb the
   barge-in rule below. Per Requirement 3.5, that fallback is triggered **only**
   by first-response latency-budget violations and never by non-latency core
   failure types alone.

Validates portions of Requirements 7.4, 7.5, and 3.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

__all__ = [
    "TurnPhase",
    "FallbackTarget",
    "CoreFailureType",
    "LATENCY_FAILURE_TYPES",
    "NON_LATENCY_FAILURE_TYPES",
    "DuplexConfig",
    "BargeInDecision",
    "LatencyFallbackDecision",
    "DuplexManager",
    "DEFAULT_DUPLEX_CONFIG",
]


# ---------------------------------------------------------------------------
# Turn phases
# ---------------------------------------------------------------------------
class TurnPhase(str, Enum):
    """The coarse turn phases the Duplex_Manager reasons about.

    These mirror the intent of ``server/pipeline/turn_state.py`` collapsed to
    the granularity the barge-in timing rules care about:

    - :attr:`IDLE`     — nothing in progress; no audio being produced.
    - :attr:`LISTENING` — the user holds the turn; the platform is capturing.
    - :attr:`THINKING`  — *intermediate/processing* state (the platform is
      working on a response, possibly already handling a prior interruption).
    - :attr:`SPEAKING`  — *active* state; the platform is producing audio.

    ``THINKING`` and ``SPEAKING`` are the states a barge-in can interrupt: the
    platform is either producing audio or processing toward producing it.
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


#: States in which the platform is actively producing audio output.
PRODUCING_AUDIO_STATES: frozenset[TurnPhase] = frozenset({TurnPhase.SPEAKING})

#: Intermediate/processing states (working toward output, or handling a prior
#: interruption). Requirement 7.5 requires the listening transition to work from
#: these too, not only from the actively-speaking state.
PROCESSING_STATES: frozenset[TurnPhase] = frozenset({TurnPhase.THINKING})

#: The full set of states from which a barge-in may be raised: any active or
#: intermediate/processing state. From ``IDLE``/``LISTENING`` there is no output
#: to interrupt, so a barge-in is not raised.
BARGE_IN_ELIGIBLE_STATES: frozenset[TurnPhase] = (
    PRODUCING_AUDIO_STATES | PROCESSING_STATES
)


# ---------------------------------------------------------------------------
# Latency-only fallback: targets and core failure types (Requirement 3.5)
# ---------------------------------------------------------------------------
class FallbackTarget(str, Enum):
    """Where a turn is completed when the latency fallback fires.

    Requirement 3.5 says that when the Speech_Native_Core misses the
    first-response latency budget, the turn is completed via the
    Phase_1_Pipeline, *or* via a TTS_Fallback when the Phase_1_Pipeline is
    unavailable. When the fallback does **not** fire, the turn stays on the
    core and the target is :attr:`NONE`.

    - :attr:`PHASE_1_PIPELINE` — the classic cascade fallback (preferred).
    - :attr:`TTS_FALLBACK`     — used only when Phase 1 is unavailable.
    - :attr:`NONE`             — no fallback; the core completes the turn.
    """

    PHASE_1_PIPELINE = "phase_1_pipeline"
    TTS_FALLBACK = "tts_fallback"
    NONE = "none"


class CoreFailureType(str, Enum):
    """How the Speech_Native_Core behaved on a turn, for fallback discrimination.

    The latency fallback is discriminated **purely** by whether the core met
    the first-audible-token latency budget. To make that rule explicit (and to
    let a property test sweep the whole failure space), the core's per-turn
    status is modelled as one of these named outcomes:

    - :attr:`NONE` — the core emitted its first audible token; no failure.
    - :attr:`LATENCY_BUDGET_EXCEEDED` — the core *did* (eventually) emit a
      token, but only after the budget had elapsed. This is a **latency**
      violation.
    - :attr:`NO_TOKEN_IN_WINDOW` — the core emitted no first audible token at
      all within the observation window. This is also treated as a **latency**
      violation (the budget was, a fortiori, not met).
    - :attr:`CORE_EXCEPTION` — the core raised/crashed. **Non-latency.**
    - :attr:`CORE_REFUSAL` — the core declined/aborted the turn. **Non-latency.**
    - :attr:`CODEC_ERROR` — a Mimi/codec decode error. **Non-latency.**
    - :attr:`UNKNOWN_ERROR` — any other non-latency failure. **Non-latency.**

    Per Requirement 3.5, the non-latency failure types above do **not** by
    themselves trigger this latency fallback. They are enumerated only so the
    discrimination rule can be stated and tested over the full space; how the
    platform otherwise handles a non-latency core failure is out of scope for
    *this* decision.
    """

    NONE = "none"
    LATENCY_BUDGET_EXCEEDED = "latency_budget_exceeded"
    NO_TOKEN_IN_WINDOW = "no_token_in_window"
    CORE_EXCEPTION = "core_exception"
    CORE_REFUSAL = "core_refusal"
    CODEC_ERROR = "codec_error"
    UNKNOWN_ERROR = "unknown_error"


#: Core failure types that represent a first-response *latency-budget*
#: violation. These — and only these — are eligible to trigger the latency
#: fallback (and only when the budget is actually exceeded).
LATENCY_FAILURE_TYPES: frozenset[CoreFailureType] = frozenset(
    {CoreFailureType.LATENCY_BUDGET_EXCEEDED, CoreFailureType.NO_TOKEN_IN_WINDOW}
)

#: Core failure types that are explicitly **not** latency violations. Per
#: Requirement 3.5 these alone never trigger the latency fallback.
NON_LATENCY_FAILURE_TYPES: frozenset[CoreFailureType] = frozenset(
    {
        CoreFailureType.CORE_EXCEPTION,
        CoreFailureType.CORE_REFUSAL,
        CoreFailureType.CODEC_ERROR,
        CoreFailureType.UNKNOWN_ERROR,
    }
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DuplexConfig:
    """Timing budgets for the Duplex_Manager decisions (all in milliseconds).

    Kept as an injectable, frozen value so the budgets are explicit and so
    later tasks (e.g. the Task 18.1 latency-only fallback) can extend this
    config with additional budgets without changing call sites.

    Attributes:
        min_voiced_ms: Minimum duration of voiced user speech that constitutes a
            barge-in while the platform is producing/processing audio
            (Requirement 7.4 — ``150 ms``).
        suppression_deadline_ms: Maximum time after detection by which the
            current audio output must be suppressed (Requirement 7.4 —
            ``200 ms``).
        listening_transition_deadline_ms: Maximum time after detection by which
            the turn state must reach ``LISTENING`` (Requirement 7.5 —
            ``100 ms``).
        first_response_budget_ms: First-response latency budget — the maximum
            time the Speech_Native_Core has to emit its first audible response
            token before the turn is completed via the latency fallback
            (Requirement 3.5 / 7.1 — the practical ``300 ms`` first-response
            target). A core that does not emit within this budget is a
            latency-budget violation.
    """

    min_voiced_ms: float = 150.0
    suppression_deadline_ms: float = 200.0
    listening_transition_deadline_ms: float = 100.0
    first_response_budget_ms: float = 300.0

    def __post_init__(self) -> None:
        if self.min_voiced_ms < 0:
            raise ValueError(
                f"min_voiced_ms must be >= 0, got {self.min_voiced_ms}"
            )
        if self.suppression_deadline_ms < 0:
            raise ValueError(
                "suppression_deadline_ms must be >= 0, got "
                f"{self.suppression_deadline_ms}"
            )
        if self.listening_transition_deadline_ms < 0:
            raise ValueError(
                "listening_transition_deadline_ms must be >= 0, got "
                f"{self.listening_transition_deadline_ms}"
            )
        if self.first_response_budget_ms < 0:
            raise ValueError(
                "first_response_budget_ms must be >= 0, got "
                f"{self.first_response_budget_ms}"
            )


#: The default budgets mandated by the design/requirements (150/200/100 ms).
DEFAULT_DUPLEX_CONFIG = DuplexConfig()


# ---------------------------------------------------------------------------
# Decision object
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BargeInDecision:
    """The outcome of evaluating a possible barge-in.

    Attributes:
        barge_in_triggered: ``True`` iff at least ``min_voiced_ms`` of voiced
            speech was detected while in a barge-in-eligible state.
        detection_time_ms: The detection timestamp the decision was made at.
        voiced_speech_ms: The voiced-speech duration that was evaluated.
        from_state: The turn phase at the moment of detection.
        resulting_state: The phase the turn should hold after the decision —
            ``LISTENING`` when a barge-in is triggered, otherwise unchanged.
        suppression_deadline_ms: Absolute time by which output suppression must
            occur (``<= detection_time_ms + suppression_deadline_ms``), or
            ``None`` when no barge-in is triggered.
        listening_transition_deadline_ms: Absolute time by which the turn must
            reach ``LISTENING`` (``<= detection_time_ms +
            listening_transition_deadline_ms``), or ``None`` when no barge-in is
            triggered.
        reason: Human-readable explanation of the decision.
    """

    barge_in_triggered: bool
    detection_time_ms: float
    voiced_speech_ms: float
    from_state: TurnPhase
    resulting_state: TurnPhase
    suppression_deadline_ms: Optional[float]
    listening_transition_deadline_ms: Optional[float]
    reason: str


@dataclass(frozen=True)
class LatencyFallbackDecision:
    """The outcome of the latency-only fallback discrimination (Requirement 3.5).

    The single discrimination rule is: the latency fallback fires **iff** the
    Speech_Native_Core failed to emit its first audible response token within
    the ``first_response_budget_ms`` budget (a *latency-budget violation*).
    Non-latency core failure types alone never trigger this fallback.

    Attributes:
        fallback_triggered: ``True`` iff a latency-budget violation occurred —
            i.e. the core did not emit its first audible token within budget.
        fallback_target: Where the turn is completed. When triggered this is
            :attr:`FallbackTarget.PHASE_1_PIPELINE` if Phase 1 is available,
            else :attr:`FallbackTarget.TTS_FALLBACK`. When not triggered it is
            :attr:`FallbackTarget.NONE` (the core completes the turn).
        first_token_latency_ms: The core's observed first-audible-token latency
            in ms, or ``None`` if no first token was emitted within the
            observation window.
        budget_ms: The first-response latency budget that applied (ms).
        latency_violation: ``True`` iff a latency-budget violation was detected
            (equal to ``fallback_triggered``); exposed explicitly so callers can
            distinguish the *cause* from the *action*.
        core_failure_type: The core's reported per-turn failure status.
        phase_1_available: Whether the Phase_1_Pipeline was available to take
            the turn (drives the target choice).
        reason: Human-readable explanation of the decision.
    """

    fallback_triggered: bool
    fallback_target: FallbackTarget
    first_token_latency_ms: Optional[float]
    budget_ms: float
    latency_violation: bool
    core_failure_type: CoreFailureType
    phase_1_available: bool
    reason: str


# ---------------------------------------------------------------------------
# Duplex manager
# ---------------------------------------------------------------------------
class DuplexManager:
    """Pure, clock-injected decision logic for full-duplex turn-taking.

    The manager holds an optional simulated ``clock`` and a current
    :class:`TurnPhase`. Its core barge-in decision (:meth:`decide_barge_in`) is
    a pure function of its inputs and is what property tests exercise;
    :meth:`on_voiced_speech` is a thin stateful wrapper that resolves the
    detection time (from the injected clock when not given) and applies the
    resulting state.

    Args:
        config: Timing budgets to use. Defaults to :data:`DEFAULT_DUPLEX_CONFIG`
            (the design-mandated 150/200/100 ms budgets).
        clock: Optional zero-argument callable returning the current time in
            milliseconds. Inject a *simulated* clock in tests; never a real
            wall-clock that sleeps. When omitted, callers must pass an explicit
            ``detection_time_ms`` to :meth:`on_voiced_speech`.
        initial_state: The turn phase the manager starts in.
    """

    def __init__(
        self,
        *,
        config: DuplexConfig = DEFAULT_DUPLEX_CONFIG,
        clock: Optional[Callable[[], float]] = None,
        initial_state: TurnPhase = TurnPhase.IDLE,
    ) -> None:
        if not isinstance(config, DuplexConfig):
            raise TypeError(f"config must be a DuplexConfig, got {type(config)!r}")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be a callable returning milliseconds")
        if not isinstance(initial_state, TurnPhase):
            raise TypeError(
                f"initial_state must be a TurnPhase, got {type(initial_state)!r}"
            )
        self._config = config
        self._clock = clock
        self._state = initial_state

    # --- state access ---
    @property
    def config(self) -> DuplexConfig:
        """The timing budgets in effect."""
        return self._config

    @property
    def state(self) -> TurnPhase:
        """The current turn phase."""
        return self._state

    def set_state(self, state: TurnPhase) -> None:
        """Set the current turn phase.

        Args:
            state: The phase to move to.
        """
        if not isinstance(state, TurnPhase):
            raise TypeError(f"state must be a TurnPhase, got {type(state)!r}")
        self._state = state

    # --- classification helpers ---
    @staticmethod
    def is_producing_audio(state: TurnPhase) -> bool:
        """Return ``True`` iff the platform is actively producing audio."""
        return state in PRODUCING_AUDIO_STATES

    @staticmethod
    def is_processing(state: TurnPhase) -> bool:
        """Return ``True`` iff the platform is in an intermediate/processing state."""
        return state in PROCESSING_STATES

    @staticmethod
    def is_barge_in_eligible(state: TurnPhase) -> bool:
        """Return ``True`` iff a barge-in may be raised from ``state``.

        A barge-in is eligible from any active (producing audio) or
        intermediate/processing state, including when the platform is already
        handling a prior interruption (Requirement 7.5).
        """
        return state in BARGE_IN_ELIGIBLE_STATES

    # --- core decision (pure) ---
    def decide_barge_in(
        self,
        *,
        voiced_speech_ms: float,
        current_state: TurnPhase,
        detection_time_ms: float,
    ) -> BargeInDecision:
        """Decide whether a barge-in fires and schedule its deadlines.

        This is a pure function: it reads no clock and mutates no state.

        A barge-in is triggered iff ``voiced_speech_ms`` is at least
        ``config.min_voiced_ms`` **and** ``current_state`` is barge-in eligible
        (the platform is producing audio or processing — Requirements 7.4/7.5).

        When triggered, the returned decision schedules:

        - ``suppression_deadline_ms = detection_time_ms +
          config.suppression_deadline_ms`` (output suppressed within 200 ms),
        - ``listening_transition_deadline_ms = detection_time_ms +
          config.listening_transition_deadline_ms`` (``LISTENING`` within
          100 ms),

        and sets ``resulting_state`` to ``LISTENING``. When not triggered, both
        deadlines are ``None`` and ``resulting_state`` equals ``current_state``.

        Args:
            voiced_speech_ms: Duration of voiced user speech detected (ms).
            current_state: The turn phase at the moment of detection.
            detection_time_ms: The detection timestamp (ms).

        Returns:
            A :class:`BargeInDecision` describing the outcome and deadlines.

        Raises:
            TypeError: If ``current_state`` is not a :class:`TurnPhase`.
            ValueError: If ``voiced_speech_ms`` is negative.
        """
        if not isinstance(current_state, TurnPhase):
            raise TypeError(
                f"current_state must be a TurnPhase, got {type(current_state)!r}"
            )
        if voiced_speech_ms < 0:
            raise ValueError(
                f"voiced_speech_ms must be >= 0, got {voiced_speech_ms}"
            )

        voiced_enough = voiced_speech_ms >= self._config.min_voiced_ms
        eligible = current_state in BARGE_IN_ELIGIBLE_STATES
        triggered = voiced_enough and eligible

        if triggered:
            return BargeInDecision(
                barge_in_triggered=True,
                detection_time_ms=detection_time_ms,
                voiced_speech_ms=voiced_speech_ms,
                from_state=current_state,
                resulting_state=TurnPhase.LISTENING,
                suppression_deadline_ms=(
                    detection_time_ms + self._config.suppression_deadline_ms
                ),
                listening_transition_deadline_ms=(
                    detection_time_ms
                    + self._config.listening_transition_deadline_ms
                ),
                reason=(
                    f">={self._config.min_voiced_ms:g} ms voiced speech "
                    f"({voiced_speech_ms:g} ms) while in {current_state.value!r}: "
                    "suppress output and transition to LISTENING"
                ),
            )

        if not eligible:
            reason = (
                f"no barge-in: state {current_state.value!r} is not producing "
                "audio or processing"
            )
        else:
            reason = (
                f"no barge-in: voiced speech {voiced_speech_ms:g} ms is below the "
                f"{self._config.min_voiced_ms:g} ms threshold"
            )
        return BargeInDecision(
            barge_in_triggered=False,
            detection_time_ms=detection_time_ms,
            voiced_speech_ms=voiced_speech_ms,
            from_state=current_state,
            resulting_state=current_state,
            suppression_deadline_ms=None,
            listening_transition_deadline_ms=None,
            reason=reason,
        )

    # --- latency-only fallback decision (pure) ---
    def _resolve_latency_violation(
        self,
        *,
        first_token_latency_ms: Optional[float],
        core_failure_type: CoreFailureType,
        budget_ms: float,
    ) -> bool:
        """Return ``True`` iff the turn is a first-response latency-budget violation.

        A latency-budget violation occurs when the core did **not** emit its
        first audible token within ``budget_ms``. That is the case when either:

        - no first token was emitted within the observation window
          (``first_token_latency_ms is None``, or the reported failure type is a
          latency failure such as :attr:`CoreFailureType.NO_TOKEN_IN_WINDOW` /
          :attr:`CoreFailureType.LATENCY_BUDGET_EXCEEDED`), **or**
        - a first token *was* emitted, but its latency strictly exceeded the
          budget (``first_token_latency_ms > budget_ms``).

        Crucially, a *non-latency* failure type (exception, refusal, codec
        error, unknown) does **not** by itself make this ``True`` — per
        Requirement 3.5 such failures alone do not trigger the latency fallback.
        If the core emitted within budget, there is no latency violation
        regardless of any non-latency failure type reported.
        """
        # Explicit latency failure types are latency violations by definition.
        if core_failure_type in LATENCY_FAILURE_TYPES:
            return True
        # No first token within the window => budget could not have been met.
        if first_token_latency_ms is None:
            return True
        # A token was emitted: violation only if it landed after the budget.
        # Non-latency failure types reach here and do NOT trigger the fallback
        # as long as the (eventual) first token met the budget.
        return first_token_latency_ms > budget_ms

    def decide_latency_fallback(
        self,
        *,
        first_token_latency_ms: Optional[float],
        core_failure_type: CoreFailureType = CoreFailureType.NONE,
        phase_1_available: bool = True,
    ) -> LatencyFallbackDecision:
        """Decide whether to complete the turn via the latency fallback (Req 3.5).

        This is a pure function: it reads no clock and mutates no state. It
        implements the *single* discrimination rule of Requirement 3.5:

            The turn is completed via the Phase_1_Pipeline (or a TTS_Fallback
            when Phase 1 is unavailable) **if and only if** the Speech_Native_Core
            fails to emit its first audible response token within the
            ``config.first_response_budget_ms`` (``300 ms``) budget. Non-latency
            core failure types alone do **not** trigger this fallback.

        Modelling of "latency violation vs other failure types":

        - ``first_token_latency_ms`` is the core's observed first-audible-token
          latency in ms, or ``None`` when the core emitted no token within the
          observation window.
        - ``core_failure_type`` describes *how* the core behaved
          (:class:`CoreFailureType`). Latency failure types
          (``LATENCY_BUDGET_EXCEEDED``, ``NO_TOKEN_IN_WINDOW``) are latency
          violations; the rest (``CORE_EXCEPTION``, ``CORE_REFUSAL``,
          ``CODEC_ERROR``, ``UNKNOWN_ERROR``) are explicitly **not** latency
          violations.
        - The fallback fires iff a latency-budget violation is detected — i.e.
          the first token was absent or arrived after the budget. A non-latency
          failure that nonetheless produced a first token within budget does
          **not** fire this fallback.

        Target selection when triggered: :attr:`FallbackTarget.PHASE_1_PIPELINE`
        when ``phase_1_available`` is ``True``, otherwise
        :attr:`FallbackTarget.TTS_FALLBACK`. When not triggered the target is
        :attr:`FallbackTarget.NONE`.

        Args:
            first_token_latency_ms: First-audible-token latency (ms), or ``None``
                if the core emitted no first token within the observation window.
            core_failure_type: The core's per-turn failure status. Defaults to
                :attr:`CoreFailureType.NONE` (the core emitted normally).
            phase_1_available: Whether the Phase_1_Pipeline can take the turn.
                When ``False`` the fallback target is the TTS_Fallback.

        Returns:
            A :class:`LatencyFallbackDecision` describing the outcome.

        Raises:
            TypeError: If ``core_failure_type`` is not a :class:`CoreFailureType`.
            ValueError: If ``first_token_latency_ms`` is negative.
        """
        if not isinstance(core_failure_type, CoreFailureType):
            raise TypeError(
                "core_failure_type must be a CoreFailureType, got "
                f"{type(core_failure_type)!r}"
            )
        if first_token_latency_ms is not None and first_token_latency_ms < 0:
            raise ValueError(
                "first_token_latency_ms must be >= 0 or None, got "
                f"{first_token_latency_ms}"
            )

        budget_ms = self._config.first_response_budget_ms
        latency_violation = self._resolve_latency_violation(
            first_token_latency_ms=first_token_latency_ms,
            core_failure_type=core_failure_type,
            budget_ms=budget_ms,
        )

        if not latency_violation:
            if core_failure_type in NON_LATENCY_FAILURE_TYPES:
                reason = (
                    "no latency fallback: core emitted within the "
                    f"{budget_ms:g} ms budget; the {core_failure_type.value!r} "
                    "failure is non-latency and does not trigger this fallback "
                    "(Requirement 3.5)"
                )
            else:
                latency_text = (
                    f"{first_token_latency_ms:g} ms"
                    if first_token_latency_ms is not None
                    else "n/a"
                )
                reason = (
                    "no latency fallback: core emitted its first audible token "
                    f"within the {budget_ms:g} ms budget ({latency_text})"
                )
            return LatencyFallbackDecision(
                fallback_triggered=False,
                fallback_target=FallbackTarget.NONE,
                first_token_latency_ms=first_token_latency_ms,
                budget_ms=budget_ms,
                latency_violation=False,
                core_failure_type=core_failure_type,
                phase_1_available=phase_1_available,
                reason=reason,
            )

        target = (
            FallbackTarget.PHASE_1_PIPELINE
            if phase_1_available
            else FallbackTarget.TTS_FALLBACK
        )
        if first_token_latency_ms is None:
            cause = (
                "core emitted no first audible token within the observation "
                "window"
            )
        else:
            cause = (
                f"core first-token latency {first_token_latency_ms:g} ms "
                f"exceeded the {budget_ms:g} ms budget"
            )
        reason = (
            f"latency fallback: {cause}; completing the turn via "
            f"{target.value!r}"
            + ("" if phase_1_available else " (Phase 1 unavailable)")
        )
        return LatencyFallbackDecision(
            fallback_triggered=True,
            fallback_target=target,
            first_token_latency_ms=first_token_latency_ms,
            budget_ms=budget_ms,
            latency_violation=True,
            core_failure_type=core_failure_type,
            phase_1_available=phase_1_available,
            reason=reason,
        )

    # --- stateful wrapper ---
    def on_voiced_speech(
        self,
        voiced_speech_ms: float,
        detection_time_ms: Optional[float] = None,
    ) -> BargeInDecision:
        """Evaluate voiced speech against the current state and apply the result.

        Resolves the detection time from ``detection_time_ms`` when given,
        otherwise from the injected simulated clock. When a barge-in fires, the
        manager's current state is moved to the decision's ``resulting_state``
        (``LISTENING``).

        Args:
            voiced_speech_ms: Duration of voiced user speech detected (ms).
            detection_time_ms: Explicit detection timestamp (ms). When ``None``,
                the injected ``clock`` is read instead.

        Returns:
            The :class:`BargeInDecision` for this detection.

        Raises:
            RuntimeError: If no ``detection_time_ms`` is given and no clock was
                injected.
        """
        if detection_time_ms is None:
            if self._clock is None:
                raise RuntimeError(
                    "no detection_time_ms provided and no simulated clock was "
                    "injected; pass detection_time_ms or construct with a clock"
                )
            detection_time_ms = self._clock()

        decision = self.decide_barge_in(
            voiced_speech_ms=voiced_speech_ms,
            current_state=self._state,
            detection_time_ms=detection_time_ms,
        )
        if decision.barge_in_triggered:
            self._state = decision.resulting_state
        return decision
