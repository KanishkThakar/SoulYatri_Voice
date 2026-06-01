# `roadmap.roadmap_model`

Public API of the `roadmap.roadmap_model` component. Generated from live signatures and docstrings.

## class `Roadmap`

```python
Roadmap(phases: 'list[Phase]', track_labels: 'dict[str, str]' = <factory>, gates: 'list[Gate]' = <factory>, conflicts: 'list[ConflictEntry]' = <factory>, scope_statements: 'ScopeStatements' = <factory>) -> None
```

The top-level roadmap planning aggregate.

Holds the ordered phase list, the per-track labels, the gate definitions,
the conflict register, and the explicit scope statements, and enforces the
phase-structure invariant on construction.

Attributes:
    phases: The ordered phases, in ascending ordinal order. Ordinals must be
        unique and contiguous starting at 1; ids must be unique; the
        ordinal-1 phase must be ``"P1-baseline"``; the highest-ordinal phase
        must be speech-native (Requirement 1.1).
    track_labels: Mapping of track name to its label, defaulting to
        ``{"LEAN": "primary", "AMBITIOUS": "optional"}`` (Requirement 1.2).
    gates: The Decision_Gate / Launch_Gate definitions.
    conflicts: The conflict register (Requirement 1.7).
    scope_statements: The explicit scope statements (Requirement 12).

Raises:
    TypeError: If ``phases`` / ``gates`` / ``conflicts`` contain items of the
        wrong type.
    ValueError: If the phase-structure invariant is violated.

### Methods

#### `first_phase` _(property)_

The first phase in the roadmap (ordinal 1, the Phase_1_Pipeline).

#### `final_phase` _(property)_

The final phase in the roadmap (highest ordinal, speech-native).

#### `guide_section_map` _(property)_

Map each phase id to its implementation-guide section headings.

Exposes the per-phase guide-section traceability the design requires
(Requirement 1.6).

#### `phase_by_id`

```python
phase_by_id(self, phase_id: 'str') -> 'Phase'
```

Return the phase with ``phase_id``.

Raises:
    KeyError: If no phase has the given id.

#### `phases_for_track`

```python
phases_for_track(self, track: 'str') -> 'list[Phase]'
```

Return the phases belonging to ``track``, in ordinal order.


## class `ConflictEntry`

```python
ConflictEntry(topic: 'str', superseding_decision: 'str', rationale: 'str', conflicting_document: 'str' = '') -> None
```

One row of the conflict register (roadmap decision vs. a strategy PDF).

Whenever the roadmap makes a decision that conflicts with the
``SOULYATRI_MASTER_BIBLE`` or ``VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN``
documents (or any other strategy PDF), it records the conflict topic, the
superseding decision, and the rationale (Requirement 1.7).

Attributes:
    topic: The subject of the conflict, e.g. "Build custom model up front".
    superseding_decision: The decision the roadmap makes that supersedes
        the conflicting document's position.
    rationale: Why the superseding decision is made.
    conflicting_document: Optional exact file name of the conflicting
        strategy PDF (e.g. ``"SOULYATRI_MASTER_BIBLE.pdf"``); empty when the
        conflict is not tied to a single named document.


## class `ScopeStatements`

```python
ScopeStatements(authoritative_supersedes_pdfs: 'str', references_ai_training_docs: 'str', excludes_from_scratch_pretraining: 'str', excludes_gpu_training_execution: 'str', planning_artifact_only: 'str') -> None
```

The explicit scope statements the roadmap carries (Requirement 12).

These are the authoritative-plan declarations the roadmap must surface: it
is the authoritative build plan and supersedes the strategy PDFs, it
references the ``ai-training-docs`` spec as the documentation workstream, it
excludes from-scratch foundation-model pretraining and the execution of
GPU-based training runs, and its sole deliverable is a planning artifact.

Each statement is a non-empty string so the aggregate can never be
constructed with a blank scope declaration. :meth:`default` supplies the
canonical statements drawn from the design's *Relationship to existing
artifacts* and *Scope Summary* sections.

### Methods

#### `default`

```python
default() -> "'ScopeStatements'"
```

Return the canonical scope statements for the roadmap.
