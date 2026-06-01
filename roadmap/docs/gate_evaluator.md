# `roadmap.gate_evaluator`

Public API of the `roadmap.gate_evaluator` component. Generated from live signatures and docstrings.

## class `GateEvaluator`

```python
GateEvaluator()
```

Evaluate a Decision_Gate or Launch_Gate against measured values.

Stateless: every method is a pure function of its arguments. The same gate,
measured values, and registry state always yield an equal result.

### Methods

#### `evaluate`

```python
evaluate(self, gate: 'Gate', measured_values: 'Mapping[str, float]', registry: 'Optional[LicensingRegister]' = None) -> 'GateResult'
```

Evaluate ``gate`` and return a :class:`GateResult`.

Resolves every criterion in ``gate.exit_criteria`` to a single pass/fail
result, computes ``overall_passed`` (criteria + licensing), and, when
the gate does not pass, sets ``blocked`` and builds the per-failure
remediation list.

Args:
    gate: The gate definition to evaluate. Its ``exit_criteria`` are the
        criteria resolved here.
    measured_values: Mapping of ``metric_name`` to measured value. A
        metric absent from this mapping resolves its criterion to fail
        (fail-closed) with a ``float("nan")`` measured sentinel.
    registry: The current Licensing_Register state, or ``None`` to treat
        the register as clean. ``overall_passed`` additionally requires
        the register to have no unresolved compliance warning and no
        adopted component whose license prohibits its intended use
        (Requirements 11.5, 11.7).

Returns:
    A :class:`GateResult` with one :class:`CriterionResult` per exit
    criterion, the overall pass/fail, the blocked flag, and remediation
    entries (one per failing criterion, plus a licensing entry when the
    register blocks the gate).

#### `evaluate_decision_gate`

```python
evaluate_decision_gate(self, gate: 'Gate', measured_values: 'Mapping[str, float]', registry: 'Optional[LicensingRegister]' = None) -> 'DecisionGateResult'
```

Evaluate a Decision_Gate, exposing its owner role and fallback action.

Runs the same evaluation as :meth:`evaluate` and wraps the resulting
:class:`GateResult` in a :class:`DecisionGateResult` that also carries
the gate's single ``owner_role`` and ``fallback_action`` (Requirements
1.4, 1.5). The fallback — e.g. "remain on LEAN_Track" — is what the
caller applies when ``result.overall_passed`` is ``False``.

Args:
    gate: The Decision_Gate to evaluate. Must have ``kind ==
        "decision"``.
    measured_values: Mapping of ``metric_name`` to measured value
        (fail-closed on missing metrics, as in :meth:`evaluate`).
    registry: The current Licensing_Register state, or ``None`` for a
        clean register.

Returns:
    A :class:`DecisionGateResult` composing the ``GateResult`` with the
    gate's ``owner_role`` and ``fallback_action``.

Raises:
    ValueError: If ``gate.kind`` is not ``"decision"``.


## class `DecisionGateResult`

```python
DecisionGateResult(result: 'GateResult', owner_role: 'str', fallback_action: 'str') -> None
```

A :class:`GateResult` paired with a Decision_Gate's owner and fallback.

Composes the canonical, serializable ``GateResult`` with the two
decision-gate-specific fields the design requires a gate evaluation to
surface (Requirements 1.4, 1.5):

Attributes:
    result: The underlying :class:`GateResult` (per-criterion results,
        overall pass/fail, blocked flag, and remediation list).
    owner_role: The single named role responsible for the gate decision,
        taken from ``Gate.owner_role`` (Requirement 1.4).
    fallback_action: The action to take when the exit criteria are not met,
        taken from ``Gate.fallback_action`` — e.g. "remain on LEAN_Track"
        (Requirement 1.5). It is the caller's signal for what to do when
        ``result.overall_passed`` is ``False``.
