# `roadmap.duplex_manager`

Public API of the `roadmap.duplex_manager` component. Generated from live signatures and docstrings.

## class `DuplexManager`

```python
DuplexManager(*, config: 'DuplexConfig' = DuplexConfig(min_voiced_ms=150.0, suppression_deadline_ms=200.0, listening_transition_deadline_ms=100.0, first_response_budget_ms=300.0), clock: 'Optional[Callable[[], float]]' = None, initial_state: 'TurnPhase' = <TurnPhase.IDLE: 'idle'>) -> 'None'
```

Pure, clock-injected decision logic for full-duplex turn-taking.

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

### Methods

#### `config` _(property)_

The timing budgets in effect.

#### `state` _(property)_

The current turn phase.

#### `set_state`

```python
set_state(self, state: 'TurnPhase') -> 'None'
```

Set the current turn phase.

Args:
    state: The phase to move to.

#### `is_producing_audio`

```python
is_producing_audio(state: 'TurnPhase') -> 'bool'
```

Return ``True`` iff the platform is actively producing audio.

#### `is_processing`

```python
is_processing(state: 'TurnPhase') -> 'bool'
```

Return ``True`` iff the platform is in an intermediate/processing state.

#### `is_barge_in_eligible`

```python
is_barge_in_eligible(state: 'TurnPhase') -> 'bool'
```

Return ``True`` iff a barge-in may be raised from ``state``.

A barge-in is eligible from any active (producing audio) or
intermediate/processing state, including when the platform is already
handling a prior interruption (Requirement 7.5).

#### `decide_barge_in`

```python
decide_barge_in(self, *, voiced_speech_ms: 'float', current_state: 'TurnPhase', detection_time_ms: 'float') -> 'BargeInDecision'
```

Decide whether a barge-in fires and schedule its deadlines.

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

#### `decide_latency_fallback`

```python
decide_latency_fallback(self, *, first_token_latency_ms: 'Optional[float]', core_failure_type: 'CoreFailureType' = <CoreFailureType.NONE: 'none'>, phase_1_available: 'bool' = True) -> 'LatencyFallbackDecision'
```

Decide whether to complete the turn via the latency fallback (Req 3.5).

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

#### `on_voiced_speech`

```python
on_voiced_speech(self, voiced_speech_ms: 'float', detection_time_ms: 'Optional[float]' = None) -> 'BargeInDecision'
```

Evaluate voiced speech against the current state and apply the result.

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


## class `TurnPhase`

```python
TurnPhase(value, names=None, *, module=None, qualname=None, type=None, start=1)
```

The coarse turn phases the Duplex_Manager reasons about.

These mirror the intent of ``server/pipeline/turn_state.py`` collapsed to
the granularity the barge-in timing rules care about:

- :attr:`IDLE`     — nothing in progress; no audio being produced.
- :attr:`LISTENING` — the user holds the turn; the platform is capturing.
- :attr:`THINKING`  — *intermediate/processing* state (the platform is
  working on a response, possibly already handling a prior interruption).
- :attr:`SPEAKING`  — *active* state; the platform is producing audio.

``THINKING`` and ``SPEAKING`` are the states a barge-in can interrupt: the
platform is either producing audio or processing toward producing it.


## class `CoreFailureType`

```python
CoreFailureType(value, names=None, *, module=None, qualname=None, type=None, start=1)
```

How the Speech_Native_Core behaved on a turn, for fallback discrimination.

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


## class `FallbackTarget`

```python
FallbackTarget(value, names=None, *, module=None, qualname=None, type=None, start=1)
```

Where a turn is completed when the latency fallback fires.

Requirement 3.5 says that when the Speech_Native_Core misses the
first-response latency budget, the turn is completed via the
Phase_1_Pipeline, *or* via a TTS_Fallback when the Phase_1_Pipeline is
unavailable. When the fallback does **not** fire, the turn stays on the
core and the target is :attr:`NONE`.

- :attr:`PHASE_1_PIPELINE` — the classic cascade fallback (preferred).
- :attr:`TTS_FALLBACK`     — used only when Phase 1 is unavailable.
- :attr:`NONE`             — no fallback; the core completes the turn.


## class `BargeInDecision`

```python
BargeInDecision(barge_in_triggered: 'bool', detection_time_ms: 'float', voiced_speech_ms: 'float', from_state: 'TurnPhase', resulting_state: 'TurnPhase', suppression_deadline_ms: 'Optional[float]', listening_transition_deadline_ms: 'Optional[float]', reason: 'str') -> None
```

The outcome of evaluating a possible barge-in.

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


## class `LatencyFallbackDecision`

```python
LatencyFallbackDecision(fallback_triggered: 'bool', fallback_target: 'FallbackTarget', first_token_latency_ms: 'Optional[float]', budget_ms: 'float', latency_violation: 'bool', core_failure_type: 'CoreFailureType', phase_1_available: 'bool', reason: 'str') -> None
```

The outcome of the latency-only fallback discrimination (Requirement 3.5).

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


## class `DuplexConfig`

```python
DuplexConfig(min_voiced_ms: 'float' = 150.0, suppression_deadline_ms: 'float' = 200.0, listening_transition_deadline_ms: 'float' = 100.0, first_response_budget_ms: 'float' = 300.0) -> None
```

Timing budgets for the Duplex_Manager decisions (all in milliseconds).

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
