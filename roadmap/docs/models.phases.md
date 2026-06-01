# `roadmap.models.phases`

Public API of the `roadmap.models.phases` component. Generated from live signatures and docstrings.

## class `Phase`

```python
Phase(ordinal: 'int', id: 'str', track: 'Track', title: 'str', is_speech_native: 'bool', guide_sections: 'list[str]' = <factory>, compute_min_gpu_class: 'str' = '', compute_min_vram_gb: 'float' = 0.0) -> None
```

An ordered phase in the roadmap.

Attributes:
    ordinal: Unique, contiguous position starting at 1 (``P1`` == 1).
    id: Unique phase identifier, e.g. ``"P2-core-select"``.
    track: The track this phase belongs to (``"LEAN"`` or ``"AMBITIOUS"``).
    title: Human-readable phase title.
    is_speech_native: Whether this phase is a speech-native platform phase.
    guide_sections: At least one heading from the implementation guide that
        this phase traces to (Requirement 1.6).
    compute_min_gpu_class: Minimum GPU class to execute the phase,
        e.g. ``"L4"``, ``"A10G"``, ``"A100-40GB"`` (Requirement 9.1).
    compute_min_vram_gb: Minimum VRAM in gigabytes to execute the phase
        (Requirement 9.1).

Construction-time validation enforces a positive ordinal, non-empty
identifier/title, a recognized track, at least one non-empty guide section,
a non-empty GPU class, and a non-negative VRAM figure.


## class `GateCriterion`

```python
GateCriterion(metric_name: 'str', threshold: 'float', operator: 'Operator') -> None
```

A single gate criterion expressed as a metric, threshold, and operator.

A criterion plus a measured value resolves to exactly one pass/fail result
(Requirement 1.4).

Attributes:
    metric_name: The named metric the criterion evaluates.
    threshold: The numeric threshold compared against the measured value.
    operator: One of ``{"<=", "<", ">=", ">", "=="}``.


## class `Gate`

```python
Gate(id: 'str', kind: 'GateKind', entry_criteria: 'list[GateCriterion]' = <factory>, exit_criteria: 'list[GateCriterion]' = <factory>, owner_role: 'str' = '', fallback_action: 'str' = '') -> None
```

A Decision_Gate or Launch_Gate with criteria, an owner, and a fallback.

Attributes:
    id: Unique gate identifier, e.g. ``"G1"``.
    kind: ``"decision"`` or ``"launch"``.
    entry_criteria: Criteria required to enter/evaluate the gate.
    exit_criteria: Criteria required to pass the gate.
    owner_role: Exactly one named role responsible for the gate decision
        (Requirement 1.4).
    fallback_action: The action taken when exit criteria are not met,
        e.g. ``"remain on LEAN_Track"`` (Requirement 1.5).
