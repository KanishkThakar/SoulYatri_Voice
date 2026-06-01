# `roadmap.models.selection`

Public API of the `roadmap.models.selection` component. Generated from live signatures and docstrings.

## class `CriterionResult`

```python
CriterionResult(metric_name: 'str', measured: 'float', threshold: 'float', operator: 'str', passed: 'bool') -> None
```

The resolved pass/fail outcome of a single gate criterion.

A ``GateCriterion`` plus a measured value resolves to exactly one of these
(Requirement 1.4).

Attributes:
    metric_name: The named metric that was evaluated.
    measured: The measured value compared against the threshold.
    threshold: The numeric threshold the measured value was compared to.
    operator: The comparison operator used, e.g. ``">="`` or ``"<="``.
    passed: Whether the measured value satisfied the criterion.


## class `GateResult`

```python
GateResult(gate_id: 'str', criteria_results: 'list[CriterionResult]' = <factory>, overall_passed: 'bool' = False, blocked: 'bool' = False, remediation: 'list[str]' = <factory>) -> None
```

The aggregate result of evaluating a Decision_Gate or Launch_Gate.

``overall_passed`` is a pure function of ``criteria_results`` and the
Licensing_Register state; it never depends on hidden state. When the gate
does not pass, ``blocked`` is set and ``remediation`` carries one entry per
failing criterion (Requirements 8.4, 8.5).

Attributes:
    gate_id: The identifier of the evaluated gate.
    criteria_results: The per-criterion pass/fail results.
    overall_passed: ``True`` iff every criterion passed and the
        Licensing_Register has no unresolved warning and no prohibiting
        license.
    blocked: ``True`` when the release is blocked (i.e. not passed).
    remediation: One entry naming each failing criterion and its corrective
        action when blocked; empty otherwise.


## class `CandidateScores`

```python
CandidateScores(model_id: 'str', revision: 'str', scores: 'dict[str, float]' = <factory>) -> None
```

A Candidate_Model's per-criterion scores for weighted selection.

Attributes:
    model_id: The Candidate_Model identifier, e.g.
        ``"kyutai/moshiko-pytorch-bf16"``.
    revision: The model version or revision the scores apply to.
    scores: Mapping of selection-criterion name to a score in ``0..100``.


## class `SelectionOutcome`

```python
SelectionOutcome(selected: 'str', aggregates: 'dict[str, float]' = <factory>, passing: 'list[str]' = <factory>) -> None
```

The result of selecting the Speech-Native Core from Candidate_Models.

``selected`` is ``RETAIN_PHASE_1`` exactly when ``passing`` is empty, and is
otherwise the ``argmax`` of ``aggregates`` restricted to ``passing``
(Requirements 2.7, 2.9).

Attributes:
    selected: The selected ``model_id`` or the ``RETAIN_PHASE_1`` sentinel.
    aggregates: Mapping of ``model_id`` to its weighted aggregate score.
    passing: The ``model_id`` values that meet every per-criterion minimum.
