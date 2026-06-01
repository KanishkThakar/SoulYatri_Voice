# `roadmap.budget_planner`

Public API of the `roadmap.budget_planner` component. Generated from live signatures and docstrings.

## class `BudgetComputePlanner`

```python
BudgetComputePlanner(phases: 'Optional[Iterable[Phase]]' = None, *, lean_budget: 'Optional[BudgetRange]' = None, ambitious_budget: 'Optional[BudgetRange]' = None) -> 'None'
```

States per-phase compute footprints, budget ranges, and scope decisions.

Footprints are sourced from the :class:`Phase` fields supplied at
construction (Requirement 9.1). The planner is pure: it makes no network or
GPU calls and only reasons about *stated* footprints and budget estimates.

### Methods

#### `phases` _(property)_

The phases this planner reports footprints for.

#### `phase_footprint`

```python
phase_footprint(self, phase: 'Union[Phase, str]') -> 'ComputeFootprint'
```

Return the per-phase compute footprint (Requirement 9.1).

#### `phase_footprints`

```python
phase_footprints(self) -> 'dict[str, ComputeFootprint]'
```

Return ``{phase_id: ComputeFootprint}`` for every known phase.

#### `ambitious_phase_footprints`

```python
ambitious_phase_footprints(self) -> 'dict[str, ComputeFootprint]'
```

Return the per-phase footprints for AMBITIOUS-track phases only.

#### `lean_no_large_scale_training_claim` _(property)_

The structured LEAN feasibility claim (Requirement 9.3).

Returns a structured statement that the LEAN_Track is executable by at
most ``lean_max_team_size`` people *without* large-scale GPU training
runs (multi-GPU / multi-node from-scratch model training).

#### `assert_lean_feasibility`

```python
assert_lean_feasibility(self) -> 'None'
```

Assert the Requirement 9.3 LEAN claim holds.

Raises:
    AssertionError: If the asserted team size exceeds five or the
        no-large-scale-training claim is not held.

#### `ambitious_justification`

```python
ambitious_justification(self, *, approved: 'bool' = False) -> 'AmbitiousJustification'
```

Build the explicit AMBITIOUS justification (Requirement 9.4).

The justification bundles the AMBITIOUS budget range (Requirement 9.2)
and the per-phase compute footprints for the AMBITIOUS phases
(Requirement 9.1).

Args:
    approved: Whether the justification is explicitly approved. The
        AMBITIOUS_Track may only be entered at ``G1`` once this is
        ``True`` (mapped to the ``G1`` exit criterion).

Returns:
    The assembled :class:`AmbitiousJustification`.

#### `require_ambitious_justification`

```python
require_ambitious_justification(self, justification: 'Optional[AmbitiousJustification]') -> 'AmbitiousJustification'
```

Block AMBITIOUS entry unless an explicit justification is present.

Per Requirement 9.4, before the AMBITIOUS_Track is entered at ``G1`` an
explicit justification including the AMBITIOUS budget range and the
per-phase compute footprint must exist and be approved.

Args:
    justification: The justification to validate.

Returns:
    The validated justification (unchanged) when it is complete.

Raises:
    AmbitiousJustificationError: If the justification is missing, lacks a
        budget range, lacks per-phase footprints, or is not approved.

#### `can_enter_ambitious`

```python
can_enter_ambitious(self, justification: 'Optional[AmbitiousJustification]') -> 'bool'
```

Return ``True`` iff a complete, approved justification allows entry.

#### `select_scope`

```python
select_scope(self, phase: 'Union[Phase, str]', available_compute: 'AvailableCompute') -> 'ScopePlan'
```

Select a full- or reduced-scope plan for ``phase`` (Requirement 9.5).

When the confirmed-available compute is below the phase minimum VRAM, is
zero, or is invalid/missing (``None`` / negative / non-numeric), a
reduced-scope alternative is returned whose stated footprint does **not**
exceed the compute confirmed available. When the confirmed-available
compute meets or exceeds the phase minimum, the full-scope plan is
returned. In every case ``result.footprint.vram_gb`` is guaranteed to be
``<= result.confirmed_available_vram_gb`` (the invariant verified by
Task 22.2).

Args:
    phase: The phase (instance or id) to plan scope for.
    available_compute: Confirmed-available compute, expressed as a VRAM
        number (GB), a :class:`ComputeFootprint`, or a mapping with a
        ``vram_gb`` key. Invalid/missing inputs resolve to zero.

Returns:
    A :class:`ScopePlan` describing the chosen scope and footprint.


## class `BudgetRange`

```python
BudgetRange(lower: 'float', upper: 'float', currency: 'str' = 'USD') -> None
```

A budget range expressed as ``{lower, upper, currency}`` (Requirement 9.2).

Attributes:
    lower: The lower-bound estimate, in ``currency``. Must be ``>= 0``.
    upper: The upper-bound estimate, in ``currency``. Must be ``>= lower``.
    currency: The single stated currency code, e.g. ``"USD"``.

Construction-time validation enforces non-negative bounds, ``lower <= upper``
(Requirement 9.2), and a non-empty currency.

### Methods

#### `as_dict`

```python
as_dict(self) -> 'dict'
```

Return the ``{lower, upper, currency}`` structured form.


## class `ComputeFootprint`

```python
ComputeFootprint(gpu_class: 'str', vram_gb: 'float') -> None
```

A stated compute footprint: a minimum GPU class + minimum VRAM (GB).

This mirrors the per-phase footprint sourced from :class:`Phase`
(Requirement 9.1) and is also used to describe the reduced-scope footprint
returned by :meth:`BudgetComputePlanner.select_scope` (Requirement 9.5).

Attributes:
    gpu_class: The (minimum) GPU class, e.g. ``"L4-24GB"`` or ``"CPU"``.
    vram_gb: The (minimum) VRAM in gigabytes. Must be ``>= 0``.

### Methods

#### `as_dict`

```python
as_dict(self) -> 'dict'
```

Return the ``{gpu_class, vram_gb}`` structured form.


## class `ScopePlan`

```python
ScopePlan(phase_id: 'str', scope: 'ScopeKind', footprint: 'ComputeFootprint', confirmed_available_vram_gb: 'float', rationale: 'str' = '') -> None
```

The result of :meth:`BudgetComputePlanner.select_scope`.

Attributes:
    phase_id: The id of the phase the plan applies to.
    scope: ``"full"`` when the confirmed-available compute meets/exceeds the
        phase minimum, otherwise ``"reduced"``.
    footprint: The stated compute footprint of the returned plan. Its
        ``vram_gb`` never exceeds ``confirmed_available_vram_gb``
        (Requirement 9.5; verified by Task 22.2).
    confirmed_available_vram_gb: The non-negative VRAM (GB) the planner could
        confirm as available. Invalid / missing / negative / zero inputs all
        resolve to ``0.0``.
    rationale: A short human-readable explanation of the decision.

### Methods

#### `is_reduced` _(property)_

``True`` when this is a reduced-scope alternative.

#### `footprint_within_available` _(property)_

``True`` iff the stated footprint does not exceed confirmed-available.

This is the Requirement 9.5 invariant the planner guarantees for every
returned plan.


## class `AmbitiousJustification`

```python
AmbitiousJustification(budget_range: 'BudgetRange', phase_footprints: 'dict[str, ComputeFootprint]' = <factory>, approved: 'bool' = False) -> None
```

An explicit justification required before AMBITIOUS entry at ``G1``.

Per Requirement 9.4 the justification must include the AMBITIOUS budget
range (Requirement 9.2) and the per-phase compute footprint (Requirement
9.1) for the AMBITIOUS phases.

Attributes:
    budget_range: The AMBITIOUS_Track budget range.
    phase_footprints: Mapping of AMBITIOUS phase id -> its compute footprint.
    approved: Whether the justification has been explicitly approved (maps to
        the ``G1`` exit criterion ``ambitious_budget_justification_approved``).

### Methods

#### `is_complete`

```python
is_complete(self) -> 'bool'
```

Return ``True`` iff the justification carries everything 9.4 requires.
