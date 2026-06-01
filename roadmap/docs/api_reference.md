# `roadmap` API Reference

Auto-generated API reference for the public API of the `roadmap` tooling package. Generated from live signatures and docstrings; do not edit by hand.

## `PACKAGE_ROOT`

_Constant_ of type `WindowsPath`.

```python
WindowsPath('D:/SoulYatri_Voice/roadmap')
```


## `WORKSPACE_ROOT`

_Constant_ of type `WindowsPath`.

```python
WindowsPath('D:/SoulYatri_Voice')
```


## `ROADMAP_MD_PATH`

_Constant_ of type `WindowsPath`.

```python
WindowsPath('D:/SoulYatri_Voice/roadmap/ROADMAP.md')
```


## `DOCS_DIR`

_Constant_ of type `WindowsPath`.

```python
WindowsPath('D:/SoulYatri_Voice/docs')
```


## `evaluate_and_select`

```python
evaluate_and_select(candidates: 'list[MockCandidate]', *, selection_scores: 'Optional[dict[str, dict[str, float]]]' = None, gate: 'Optional[Gate]' = None, gate_measurements: 'Optional[dict[str, float]]' = None, registry: 'Optional[LicensingRegister]' = None, sample_items: 'int' = 8) -> 'PipelineResult'
```

Run the mocked evaluate → select → gate pipeline over a candidate set.

Wires the three decision-logic components into one cohesive, fully mocked
pass (no GPU/training work — Requirements 4.6, 12.4, 12.5):

1. **Evaluate.** Runs :meth:`EvaluationHarness.evaluate_all` over
   ``candidates``, producing one comparable :class:`HarnessRun` per
   candidate. Candidates that cannot be evaluated (missing weights,
   prohibiting license, insufficient hardware) are recorded as *excluded*
   and the run continues without aborting (Requirements 4.1, 4.5).
2. **Select.** Feeds per-candidate selection scores into
   :meth:`SelectionScorer.select` to produce a :class:`SelectionOutcome`.
   Only **non-excluded** candidates are eligible for selection: an excluded
   candidate cannot be adopted as the Speech-Native Core, so it is omitted
   from the scorer's input. The outcome is :data:`RETAIN_PHASE_1` when no
   eligible candidate passes every per-criterion minimum, otherwise the
   passing candidate with the highest weighted aggregate (Requirements 2.4,
   2.7, 2.9).
3. **Gate.** When a ``gate`` is supplied, evaluates it via
   :meth:`GateEvaluator.evaluate` against ``gate_measurements`` and the
   ``registry`` state, returning the :class:`GateResult`; otherwise the
   result's ``gate_result`` is ``None`` (Requirement 8.4).

Selection-score sourcing (documented choice)
--------------------------------------------
The Evaluation Harness's per-candidate metrics (latency, code-switch
quality, expressiveness) and the Selection Scorer's six *weighted* criteria
(streaming latency, Hinglish capability, full-duplex, license
permissiveness, VRAM footprint, community activity) are deliberately
different measurement axes in the design, so harness metrics are **not**
auto-mapped onto selection criteria. Instead the caller supplies
``selection_scores`` explicitly as ``model_id -> {criterion: score}``. For
each non-excluded candidate the helper builds a
:class:`CandidateScores` from ``selection_scores[model_id]`` (defaulting to
an empty score map when a model id is absent).

When ``selection_scores`` is ``None`` (or omits a candidate), that
candidate is scored with an **empty** score map. Under the scorer's
fail-closed rule a missing criterion scores ``0.0``, so no candidate passes
its minimums and the outcome is :data:`RETAIN_PHASE_1` — the correct
conservative default when no selection evidence is provided (Requirement
2.7).

Args:
    candidates: The mocked Candidate_Models to evaluate, in priority/input
        order. The order is preserved in ``harness_runs`` and defines the
        selection tie-break order (first-wins) among equal top aggregates.
    selection_scores: Optional ``model_id -> {criterion: score}`` mapping of
        per-criterion selection scores (each ``0..100``). When omitted, all
        candidates default to empty score maps (see above).
    gate: Optional launch/decision :class:`Gate` to evaluate after
        selection. When ``None`` no gate is evaluated and
        ``PipelineResult.gate_result`` is ``None``.
    gate_measurements: Optional ``metric_name -> measured value`` mapping for
        the gate's exit criteria. A metric absent here resolves its
        criterion to fail (fail-closed). Ignored when ``gate`` is ``None``.
    registry: Optional :class:`LicensingRegister` consulted during gate
        evaluation; a release is blocked when it carries an unresolved
        compliance warning or a prohibiting license. ``None`` is treated as
        a clean register. Ignored when ``gate`` is ``None``.
    sample_items: Probe-sample size handed to the :class:`EvaluationHarness`
        (``1..MAX_ITEMS``). Defaults to :data:`DEFAULT_SAMPLE_ITEMS`.

Returns:
    A :class:`PipelineResult` bundling the per-candidate ``harness_runs``,
    the ``selection`` outcome, and the optional ``gate_result``.


## class `PipelineResult`

```python
PipelineResult(harness_runs: 'list[HarnessRun]', selection: 'SelectionOutcome', gate_result: 'Optional[GateResult]' = None) -> None
```

The bundled result of one :func:`evaluate_and_select` pipeline pass.

Bundles the three artifacts produced by wiring the mocked harness, the
selection scorer, and (optionally) the gate evaluator into a single pass:

Attributes:
    harness_runs: One :class:`HarnessRun` per input candidate, in input
        order. Non-excluded records share the identical metric key set and
        scale; excluded candidates carry their exclusion category + reason
        (Requirements 4.1, 4.5).
    selection: The :class:`SelectionOutcome` produced by the
        :class:`SelectionScorer` over the *non-excluded* candidates —
        ``RETAIN_PHASE_1`` when none pass every per-criterion minimum, else
        the highest-aggregate passing candidate (Requirements 2.4, 2.7, 2.9).
    gate_result: The :class:`GateResult` from evaluating the launch gate via
        :class:`GateEvaluator` + :class:`LicensingRegister`, or ``None`` when
        no ``gate`` was supplied to the pipeline (Requirement 8.4).


## `Track`

_Constant_ of type `_LiteralGenericAlias`.

```python
typing.Literal['LEAN', 'AMBITIOUS']
```


## `TRACK_VALUES`

_Constant_ of type `tuple`.

```python
('LEAN', 'AMBITIOUS')
```


## `Operator`

_Constant_ of type `_LiteralGenericAlias`.

```python
typing.Literal['<=', '<', '>=', '>', '==']
```


## `OPERATOR_VALUES`

_Constant_ of type `tuple`.

```python
('<=', '<', '>=', '>', '==')
```


## `GateKind`

_Constant_ of type `_LiteralGenericAlias`.

```python
typing.Literal['decision', 'launch']
```


## `GATE_KIND_VALUES`

_Constant_ of type `tuple`.

```python
('decision', 'launch')
```


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


## `RETAIN_PHASE_1`

_Constant_ of type `str`.

```python
'RETAIN_PHASE_1'
```


## `SELECTION_WEIGHTS`

_Constant_ of type `dict`.

```python
{'streaming_latency': 25, 'hinglish_capability': 25, 'full_duplex': 20, 'license_permissiveness': 15, 'vram_footprint': 10, 'community_activity': 5}
```


## `SELECTION_MINIMUMS`

_Constant_ of type `dict`.

```python
{'streaming_latency': 60, 'hinglish_capability': 60, 'full_duplex': 50, 'license_permissiveness': 70, 'vram_footprint': 40, 'community_activity': 30}
```


## `SELECTION_CRITERIA`

_Constant_ of type `tuple`.

```python
('streaming_latency', 'hinglish_capability', 'full_duplex', 'license_permissiveness', 'vram_footprint', 'community_activity')
```


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


## class `HarnessRun`

```python
HarnessRun(model_id: 'str', revision: 'str', metric_scores: 'dict[str, float]', license_compat: "Literal['compatible', 'restricted', 'prohibited']", hardware: 'dict', excluded: 'bool' = False, exclusion_category: 'Optional[str]' = None, exclusion_reason: 'Optional[str]' = None) -> None
```

A single (mocked) evaluation record for one candidate model.

Every candidate is scored against an identical metric key set and scale so
runs are directly comparable. ``metric_scores`` carries at least
``latency_ms_p50``, ``codeswitch_quality`` and ``expressiveness``.

When a candidate cannot be evaluated (missing weights, license, or
hardware), ``excluded`` is set and ``exclusion_category`` /
``exclusion_reason`` explain why, while the harness continues with the
remaining candidates (Requirement 4.5).


## class `EmotionFeatures`

```python
EmotionFeatures(label: 'Optional[str]', confidence: 'float', valence: 'float', arousal: 'float', dominance: 'float', extraction_ok: 'bool') -> None
```

Speech-emotion features used to pick a persona conditioning mode.

Valence, arousal and dominance are clamped into ``[-1.0, 1.0]`` on
construction so the controller can never receive out-of-range values, even
if an upstream extractor reports an unbounded score (Requirement 6.1).

``label`` may be ``None`` and ``extraction_ok`` ``False`` when emotion
extraction failed or was unavailable; the controller falls back to a
neutral persona in that case while the turn still continues.


## `ConditioningMode`

_Constant_ of type `_LiteralGenericAlias`.

```python
typing.Literal['NEUTRAL', 'EMPATHETIC', 'STANDARD']
```


## class `ConsentRecord`

```python
ConsentRecord(speaker_id: 'str', permitted_use_scope: 'str', timestamp: 'float') -> None
```

A speaker-consent record gating cloning / voice-style transfer.

Consent is considered valid only when all three fields are present and
non-empty (Requirement 10.1). ``timestamp`` is stored as a float epoch
value; ``0.0`` / missing is treated as not present.

### Methods

#### `is_valid`

```python
is_valid(self) -> 'bool'
```

Return ``True`` iff all three consent fields are present and non-empty.

Strings must be non-empty after stripping surrounding whitespace, and
``timestamp`` must be a present, non-empty positive value. A missing
timestamp is represented as ``0.0`` (or ``None``) and is therefore
invalid.


## class `CloningDecision`

```python
CloningDecision(allowed: 'bool', reason: 'str', reference_retained: 'bool') -> None
```

The result of evaluating a cloning / voice-style-transfer request.

When the request is refused (``allowed=False``), ``reference_retained`` must
be ``False`` so no reference audio is kept without valid consent
(Requirement 10.3).


## class `LicenseEntry`

```python
LicenseEntry(component_name: 'str', license_id: 'Optional[str]', constraints: 'list[str]', intended_use_permitted: 'bool', recorded_before_use: 'bool', redistribution_restricted: 'bool' = False, restriction_type: 'Optional[str]' = None) -> None
```

A licensing record for an adopted component, captured before use.

``license_id`` is a recognized OSS identifier, or ``None`` when recording
failed (in which case adoption is allowed but an unresolved
:class:`ComplianceWarning` is retained). ``redistribution_restricted`` and
``restriction_type`` flag datasets that restrict redistribution or require
consent (Requirement 11.2, 11.6).


## class `ComplianceWarning`

```python
ComplianceWarning(component_name: 'str', resolved: 'bool') -> None
```

An outstanding licensing/compliance warning tied to a component.


## class `NormalizationResult`

```python
NormalizationResult(normalized_text: 'str', unmapped_tokens: 'list[str]' = <factory>) -> None
```

The result of Hinglish transliteration normalization.

Tokens with no mapping entry are retained unchanged inside
``normalized_text`` and also reported in ``unmapped_tokens`` so they can be
flagged for review (Requirement 5.8).


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


## `FIRST_PHASE_ID`

_Constant_ of type `str`.

```python
'P1-baseline'
```


## class `LicensingRegister`

```python
LicensingRegister() -> 'None'
```

In-memory register of adopted components, exclusions, and warnings.

All recording happens *before* a component is used in any build, so every
:class:`LicenseEntry` produced here has ``recorded_before_use=True``. A
record whose ``license_id`` could not be resolved to a recognized OSS
identifier is still stored (adoption proceeds) but with ``license_id=None``
and an accompanying unresolved :class:`ComplianceWarning` (Requirement
11.3).

### Methods

#### `record_component`

```python
record_component(self, component_name: 'str', license_id: 'Optional[str]', constraints: 'Optional[list[str]]' = None, *, intended_use_permitted: 'bool' = True, redistribution_restricted: 'bool' = False, restriction_type: 'Optional[str]' = None) -> 'LicenseEntry'
```

Record a component's license before it is used in any build.

Stores ``{component_name, license_id, constraints}`` plus the
intended-use and redistribution flags. ``license_id`` is accepted only
when it is a recognized OSS identifier (see
:data:`RECOGNIZED_OSS_LICENSES`); any other value — including ``None``
or an unrecognised string — is treated as a *failed* license recording:
the entry is still stored with ``license_id=None`` (adoption proceeds)
and an unresolved :class:`ComplianceWarning` is raised and retained for
the component until a recognized identifier is recorded (Requirements
11.1, 11.2, 11.3).

Re-recording the same component with a recognized identifier resolves
any outstanding warning for that component.

Args:
    component_name: The adopted model/dataset/tool name. Must be a
        non-empty string.
    license_id: The OSS license identifier, or ``None`` if unknown.
    constraints: Commercial-use / attribution constraints; defaults to
        an empty list.
    intended_use_permitted: Whether the license permits the intended
        use. ``False`` marks a *prohibiting* license (Requirement 11.7).
    redistribution_restricted: Whether the component's terms restrict
        redistribution or require subject consent (Requirement 11.6).
    restriction_type: The specific restriction type when
        ``redistribution_restricted`` is ``True``.

Returns:
    The stored :class:`LicenseEntry`.

Raises:
    ValueError: If ``component_name`` is empty or blank.

#### `flag_dataset`

```python
flag_dataset(self, component_name: 'str', restriction_type: 'str') -> 'LicenseEntry'
```

Flag a dataset as restricting redistribution / requiring consent.

Records the specific ``restriction_type`` on the dataset's
:class:`LicenseEntry` (Requirement 11.6). While the flag is set,
:meth:`redistribution_allowed` returns ``False`` for the dataset
(Requirement 11.8) until :meth:`satisfy_restriction` clears it.

If the dataset has not been recorded yet, a minimal entry is created
with an unresolved compliance warning for its missing license info, so
the flag is never silently lost.

Args:
    component_name: The dataset name.
    restriction_type: The specific restriction, e.g.
        ``"no-redistribution"`` or ``"subject-consent-required"``. Must
        be a non-empty string.

Returns:
    The updated (or newly created) :class:`LicenseEntry`.

Raises:
    ValueError: If ``restriction_type`` is empty or blank.

#### `satisfy_restriction`

```python
satisfy_restriction(self, component_name: 'str') -> 'None'
```

Mark a dataset's redistribution/consent restriction as satisfied.

Clears the redistribution flag so :meth:`redistribution_allowed` returns
``True`` again (Requirement 11.8). The recorded ``restriction_type`` is
preserved on the entry for audit. No-op if the component is unknown.

#### `record_exclusion`

```python
record_exclusion(self, component_name: 'str', reason: 'str', *, licensing_related: 'bool') -> 'ExclusionRecord'
```

Record an excluded Candidate_Model and its exclusion reason.

Captures the exclusion and whether it was for a *licensing* reason (a
license prohibiting the intended use) or a *non-licensing* reason such
as performance or compatibility (Requirement 11.4).

Args:
    component_name: The excluded Candidate_Model identifier. Must be a
        non-empty string.
    reason: The human-readable exclusion reason. Must be non-empty.
    licensing_related: ``True`` if excluded for a licensing reason,
        ``False`` for a non-licensing reason.

Returns:
    The stored :class:`ExclusionRecord`.

Raises:
    ValueError: If ``component_name`` or ``reason`` is empty or blank.

#### `resolve_warning`

```python
resolve_warning(self, component_name: 'str') -> 'None'
```

Resolve any outstanding compliance warning for a component.

Marks the component's warning ``resolved=True`` in place. No-op when no
warning exists for the component. Note that a warning is only truly
cleared once the missing license info is recorded via
:meth:`record_component`; this method exists for explicit resolution
bookkeeping.

#### `redistribution_allowed`

```python
redistribution_allowed(self, component_name: 'str') -> 'bool'
```

Return whether content from ``component_name`` may be redistributed.

Used by the Hinglish Data Engine: returns ``False`` while the component
is flagged as restricting redistribution or requiring subject consent,
and ``True`` once the restriction is satisfied or when the component was
never flagged (Requirement 11.8). An unknown component is treated as
having no recorded restriction and is therefore allowed.

#### `unresolved_warnings`

```python
unresolved_warnings(self) -> 'list[ComplianceWarning]'
```

Return the list of currently unresolved compliance warnings (11.3).

#### `has_unresolved_warnings`

```python
has_unresolved_warnings(self) -> 'bool'
```

Return ``True`` if any compliance warning is unresolved (11.7).

#### `has_prohibiting_license`

```python
has_prohibiting_license(self) -> 'bool'
```

Return ``True`` if any adopted component prohibits its intended use.

Used by the ``GateEvaluator`` at every Launch_Gate review: a recorded
entry with ``intended_use_permitted=False`` is a prohibiting license
and blocks the release (Requirements 11.5, 11.7).

#### `get_entry`

```python
get_entry(self, component_name: 'str') -> 'Optional[LicenseEntry]'
```

Return the recorded :class:`LicenseEntry` for a component, if any.

#### `entries`

```python
entries(self) -> 'list[LicenseEntry]'
```

Return all recorded license entries.

#### `exclusions`

```python
exclusions(self) -> 'list[ExclusionRecord]'
```

Return all recorded Candidate_Model exclusions (11.4).


## `RECOGNIZED_OSS_LICENSES`

_Constant_ of type `frozenset`.

```python
frozenset({'MPL-2.0', 'LGPL-3.0', 'GPL-3.0', 'GPL-2.0', 'Unlicense', 'CC-BY-SA-4.0', 'AGPL-3.0', 'Zlib', 'LGPL-2.1', 'EPL-2.0', 'BSD-2-Clause', 'ISC', 'CC-BY-4.0', 'MIT', 'BSD-3-Clause', 'CC0-1.0', 'A…
```


## class `ExclusionRecord`

```python
ExclusionRecord(component_name: 'str', reason: 'str', category: 'ExclusionCategory') -> None
```

A record of an excluded Candidate_Model and why it was excluded.

Attributes:
    component_name: The excluded Candidate_Model identifier.
    reason: The human-readable exclusion reason.
    category: ``"licensing"`` when the exclusion is because of a license
        prohibiting the intended use, otherwise ``"non-licensing"`` (for
        performance/compatibility/hardware reasons).


## `ExclusionCategory`

_Constant_ of type `_LiteralGenericAlias`.

```python
typing.Literal['licensing', 'non-licensing']
```


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


## `MISSING_MEASUREMENT`

_Constant_ of type `float`.

```python
nan
```


## class `SelectionScorer`

```python
SelectionScorer(weights: 'dict[str, float] | None' = None, minimums: 'dict[str, float] | None' = None) -> 'None'
```

Select the Speech-Native Core via weighted, minimum-gated scoring.

The scorer is configured with the weighted criteria and per-criterion
minimum pass thresholds (defaulting to the canonical
:data:`SELECTION_WEIGHTS` / :data:`SELECTION_MINIMUMS` tables from the
design). It is otherwise stateless: :meth:`select` is a pure function of the
candidate scores passed to it.

### Methods

#### `criteria` _(property)_

The criteria, in canonical evaluation order.

#### `aggregate`

```python
aggregate(self, candidate: 'CandidateScores') -> 'float'
```

Return the weight-normalized aggregate score for one candidate.

Missing criterion scores are treated as ``0.0`` (fail-closed). See the
module docstring for the formula.

Args:
    candidate: The candidate whose scores are aggregated.

Returns:
    The weighted aggregate on the ``0..100`` scale.

#### `passes_all_minimums`

```python
passes_all_minimums(self, candidate: 'CandidateScores') -> 'bool'
```

Return whether a candidate meets every per-criterion minimum.

A criterion absent from the candidate's ``scores`` is treated as ``0.0``
and therefore fails any positive minimum (fail-closed).

Args:
    candidate: The candidate to test.

Returns:
    ``True`` iff ``score[c] >= minimum[c]`` for every criterion ``c``.

#### `select`

```python
select(self, candidates: 'list[CandidateScores]') -> 'SelectionOutcome'
```

Select the Speech-Native Core from a list of scored candidates.

Args:
    candidates: The Candidate_Models with their per-criterion scores. The
        input order is significant: it defines the tie-break order
        (first-wins) when passing candidates share the top aggregate.

Returns:
    A :class:`SelectionOutcome` whose ``aggregates`` map covers *every*
    candidate, whose ``passing`` list names the candidates meeting every
    minimum (in input order), and whose ``selected`` is either the
    highest-aggregate passing candidate or :data:`RETAIN_PHASE_1` when no
    candidate passes every minimum.


## class `EvaluationHarness`

```python
EvaluationHarness(sample_items: 'int' = 8) -> 'None'
```

Produces comparable, fully mocked :class:`HarnessRun` records.

The harness applies an identical metric key set (:data:`METRIC_KEYS`), an
identical bounded probe sample, and identical scoring scales to every
candidate, so the records it emits are directly comparable
(Requirements 4.1, 4.2). Each record carries the model identifier, the
revision, the three metric scores, the categorical license-compatibility
value, and the hardware used as ``{gpu_class, vram_gb}`` (Requirement 4.3).

The harness is fully mocked: it derives every score deterministically from
the candidate's mocked seeds and identity over an in-memory sample bounded
by :data:`MAX_ITEMS`, and never performs a GPU or model-training run
(Requirement 4.6).

Args:
    sample_items: The size of the small probe sample evaluated per
        candidate. Must be in the inclusive range ``1..MAX_ITEMS``.

### Methods

#### `evaluate`

```python
evaluate(self, candidate: 'MockCandidate') -> 'HarnessRun'
```

Evaluate a single candidate and return its comparable record.

A candidate that *cannot* be evaluated is recorded as **excluded**
instead of being scored (Requirements 4.5, 11.4). The exclusion
conditions are checked in a fixed precedence order
(:meth:`_detect_exclusion`); when one matches, the returned
:class:`HarnessRun` has ``excluded=True``, an ``exclusion_category``
from :data:`EXCLUSION_CATEGORIES`, a descriptive ``exclusion_reason``,
and the documented sentinel **empty** ``metric_scores`` (no measurement
was performed). The candidate's ``license_compat`` and ``hardware`` are
still recorded, since both are known without measurement.

Otherwise the candidate is scored on the happy path, producing a record
with the identical metric key set and scales as every other
non-excluded candidate (Requirements 4.1, 4.2, 4.3).

#### `evaluate_all`

```python
evaluate_all(self, candidates: 'Sequence[MockCandidate]') -> 'list[HarnessRun]'
```

Evaluate every candidate, returning one record per candidate.

Non-excluded records share the identical metric key set and scoring
scale, so they are directly comparable across candidates (Requirement
4.1). A candidate that cannot be evaluated is recorded as excluded and
the loop continues to the remaining candidates without aborting
(Requirements 4.5, 11.4), so the returned list always has exactly one
record per input candidate, preserving order.

#### `reproduce`

```python
reproduce(self, candidate: 'MockCandidate', runs: 'int' = 3) -> 'ReproducibilityReport'
```

Re-run a candidate ``runs`` times and check per-metric reproducibility.

Evaluates ``candidate`` ``runs`` times on the same mocked inputs and
hardware and verifies that, per metric, the scores across runs stay
within the documented tolerance (latency ±10% relative, quality and
expressiveness ±2 points absolute) — Requirement 4.4. The check is
implemented generally via :func:`within_tolerance` (each run compared to
the reference/first run), so it remains meaningful even though the
underlying derivation is fully deterministic and the runs are therefore
byte-identical and trivially within tolerance.

An **excluded** candidate carries no measured metrics: every run yields
the same empty ``metric_scores`` (exclusion is deterministic too), so
the report is returned with empty ``metrics`` and ``reproducible=True``,
with ``excluded`` / ``exclusion_category`` reflecting why no metric was
measured.

Args:
    candidate: The candidate to re-run.
    runs: How many times to evaluate the candidate. Must be
        ``>= MIN_REPRODUCIBILITY_RUNS`` (3); Requirement 4.4 mandates "at
        least three times".

Returns:
    A :class:`ReproducibilityReport` with the per-metric values across
    runs, each metric's ``within_tolerance`` flag, and an overall
    ``reproducible`` flag.

Raises:
    TypeError: If ``candidate`` is not a :class:`MockCandidate` or
        ``runs`` is not an ``int``.
    ValueError: If ``runs`` is below :data:`MIN_REPRODUCIBILITY_RUNS`.


## class `MockCandidate`

```python
MockCandidate(model_id: 'str', revision: 'str', seeds: 'dict[str, float]' = <factory>, license_compat: 'LicenseCompat' = 'compatible', hardware: 'dict' = <factory>, weights_available: 'bool' = True) -> None
```

A mocked Candidate_Model input for the evaluation harness.

A candidate is a small data carrier — never real weights. It supplies the
identity recorded on the run plus deterministic *measurement seeds* the
harness derives scores from.

Attributes:
    model_id: The Candidate_Model identifier, e.g.
        ``"kyutai/moshiko-pytorch-bf16"``.
    revision: The model version/revision the mocked measurements apply to.
    seeds: Mock measurement seeds keyed by metric name (any of
        :data:`METRIC_KEYS`). A missing metric defaults to seed ``0.0``.
        Different seeds yield different (but deterministic) scores.
    license_compat: The categorical license-compatibility result recorded
        on the run (Requirement 4.2). A value of ``"prohibited"`` marks the
        candidate as excludable under the ``"license"`` category.
    hardware: The hardware descriptor ``{"gpu_class": str, "vram_gb": float}``
        recorded on the run (Requirement 4.3). When ``vram_gb`` is below
        :data:`REQUIRED_MIN_VRAM_GB` the candidate is excludable under the
        ``"hardware"`` category.
    weights_available: Whether the candidate's weights can be loaded. The
        explicit marker for the ``"missing_weights"`` exclusion condition:
        ``False`` means the model cannot be evaluated at all
        (Requirements 4.5, 11.4). Defaults to ``True``.


## class `ReproducibilityReport`

```python
ReproducibilityReport(model_id: 'str', revision: 'str', runs: 'int', metrics: 'dict[str, MetricReproducibility]', reproducible: 'bool', excluded: 'bool' = False, exclusion_category: 'str | None' = None) -> None
```

The result of re-running one candidate to check reproducibility.

Produced by :meth:`EvaluationHarness.reproduce`. It records the candidate
identity, the number of runs performed, the per-metric outcomes, and a
single ``reproducible`` flag that is true iff every measured metric stayed
within its documented tolerance across all runs (Requirement 4.4).

An **excluded** candidate has no measured metrics: ``metrics`` is empty and
``reproducible`` is ``True`` (trivially — exclusion is deterministic, so
every run agrees that no measurement was performed). ``excluded`` and
``exclusion_category`` mirror the underlying :class:`HarnessRun` so callers
can tell a trivially-reproducible exclusion apart from a measured one.

Attributes:
    model_id: The re-run candidate's model identifier.
    revision: The re-run candidate's revision.
    runs: The number of evaluations performed (``>= MIN_REPRODUCIBILITY_RUNS``).
    metrics: Per-metric reproducibility records, keyed by metric. Empty when
        the candidate was excluded.
    reproducible: ``True`` iff every metric in ``metrics`` is within
        tolerance (vacuously ``True`` when there are no measured metrics).
    excluded: Whether the candidate was excluded from measurement.
    exclusion_category: The exclusion category when ``excluded`` is true,
        else ``None``.


## class `MetricReproducibility`

```python
MetricReproducibility(metric_key: 'str', values: 'tuple[float, ...]', tolerance_kind: 'str', tolerance_amount: 'float', within_tolerance: 'bool') -> None
```

Per-metric reproducibility outcome across a candidate's re-runs.

Attributes:
    metric_key: The metric this record describes (one of
        :data:`METRIC_KEYS`).
    values: The metric's value from each run, in run order.
    tolerance_kind: The tolerance rule applied — either
        :data:`TOLERANCE_KIND_RELATIVE_PCT` or
        :data:`TOLERANCE_KIND_ABSOLUTE_POINTS`.
    tolerance_amount: The tolerance magnitude (percent for a relative rule,
        points for an absolute rule).
    within_tolerance: Whether every value is within ``tolerance_amount`` of
        the reference (first) run, per :func:`within_tolerance`.


## `within_tolerance`

```python
within_tolerance(metric_key: 'str', values: 'Sequence[float]') -> 'bool'
```

Return whether ``values`` for ``metric_key`` agree within its tolerance.

Applies the documented per-metric reproducibility rule from
:data:`METRIC_TOLERANCES` (Requirement 4.4):

* ``latency_ms_p50`` uses a **relative** tolerance of ±10%: every value must
  lie within ``LATENCY_TOLERANCE_PCT`` percent of the *reference* value (the
  first value in ``values``).
* ``codeswitch_quality`` and ``expressiveness`` use an **absolute** tolerance
  of ±2 points: every value must lie within that many points of the
  reference value, on the metric's own ``0..100`` scale.

The check compares each run against the first run rather than just the
min/max spread so the "reference run ± tolerance" semantics are explicit and
match the design's "re-running … yields … scores within a documented
per-metric tolerance" wording. The first value is the reference.

Args:
    metric_key: One of :data:`METRIC_KEYS`. An unknown key raises
        ``KeyError`` so a typo never silently passes.
    values: The metric's value from each run, in run order. An empty
        sequence is vacuously within tolerance (no runs disagree); a single
        value is trivially within tolerance.

Returns:
    ``True`` iff every value is within the metric's tolerance of the
    reference (first) value.


## `METRIC_KEYS`

_Constant_ of type `tuple`.

```python
('latency_ms_p50', 'codeswitch_quality', 'expressiveness')
```


## `DEFAULT_SAMPLE_ITEMS`

_Constant_ of type `int`.

```python
8
```


## `MAX_ITEMS`

_Constant_ of type `int`.

```python
32
```


## class `HinglishDataEngine`

```python
HinglishDataEngine(mapping: 'dict[str, str] | None' = None) -> 'None'
```

Deterministic Romanized↔Devanagari normalization for Hinglish text.

The engine holds the transliteration mapping in both directions as instance
attributes so the *same* table backs input normalization (Romanized →
Devanagari) and output rendering (Devanagari → Romanized):

- ``self._roman_to_deva``: Romanized token → Devanagari token.
- ``self._deva_to_roman``: Devanagari token → canonical Romanized token
  (first Romanized spelling seen for each Devanagari form).

:meth:`normalize` canonicalizes input to Devanagari: a recognized Romanized
token is replaced by its Devanagari form, a token that is *already* a
recognized Devanagari form is passed through unchanged (it is "mapped", so it
is not flagged), and any token absent from the mapping is retained unchanged
and reported as unmapped (Requirement 5.8).

Determinism (Requirement 5.5) follows from the normalization being a pure,
order-independent dictionary lookup per token with no randomness or mutable
shared state: ``normalize(s)`` always returns the same result for the same
``s``.

### Methods

#### `mapping_size` _(property)_

Number of Romanized → Devanagari entries in the loaded mapping.

#### `normalize`

```python
normalize(self, text: 'str') -> 'NormalizationResult'
```

Normalize ``text`` to its canonical Devanagari form.

Tokenizes ``text`` on whitespace (preserving the original spacing) and,
for each token:

- replaces a recognized Romanized token with its Devanagari form
  (input-normalization direction);
- passes through a token that is already a recognized Devanagari form
  unchanged (it is part of the mapping, so it is *not* flagged);
- otherwise retains the token unchanged in ``normalized_text`` and also
  appends it to ``unmapped_tokens`` for review (Requirement 5.8).

The transformation is a pure per-token dictionary lookup, so the same
input always yields the same output (Requirement 5.5).

Args:
    text: The input string to normalize.

Returns:
    A :class:`NormalizationResult` whose ``normalized_text`` is the
    rebuilt string and whose ``unmapped_tokens`` lists, in order of
    occurrence, every token that had no mapping entry.

#### `he_ratio`

```python
he_ratio(self, text: 'str') -> 'float'
```

Return the Hindi-to-English (H/E) ratio of ``text`` as a percentage.

The ratio is ``100 * hindi / (hindi + english)`` over the classifiable
word tokens of ``text`` (see the module docstring for the definition).
Text with no classifiable Hindi/English tokens has a ratio of ``0.0``.

Args:
    text: The text whose H/E ratio is computed.

Returns:
    The H/E ratio on a ``0.0..100.0`` percentage scale.

#### `score`

```python
score(self, input: 'str', output: 'str') -> 'CodeSwitchScore'
```

Score the code-switch quality of a single (input, output) pair.

A response is **within tolerance** iff the absolute difference between
its H/E ratio and the input's H/E ratio is at most 15 percentage points
(Requirement 5.4). The returned :class:`CodeSwitchScore` carries the
input ratio, the output ratio, the absolute difference in percentage
points, the ``within_tolerance`` boolean, and a per-pair ``quality``
percentage (``100.0`` within tolerance, ``0.0`` otherwise).

Args:
    input: The code-switched user input text.
    output: The system response text.

Returns:
    The structured :class:`CodeSwitchScore` for the pair.

#### `within_tolerance`

```python
within_tolerance(self, input: 'str', output: 'str') -> 'bool'
```

Return whether a single (input, output) pair is within tolerance.

Convenience boolean wrapper over :meth:`score`: a response is **within
tolerance** iff the absolute difference between its H/E ratio and the
input's H/E ratio is at most :data:`TOLERANCE_PCT` (15) percentage points
(Requirement 5.4). Equivalent to ``self.score(input, output)
.within_tolerance`` but returned directly as a ``bool`` for callers that
only need the pass/fail decision.

Args:
    input: The code-switched user input text.
    output: The system response text.

Returns:
    ``True`` iff ``|output H/E ratio - input H/E ratio| <= 15`` pp.

#### `benchmark_passes`

```python
benchmark_passes(eval_set_score: 'float') -> 'bool'
```

Return whether an evaluation-set score passes the Hinglish benchmark.

A build passes iff the evaluation-set score is at or above the 80%
threshold (Requirement 5.6). When this returns ``False``, the roadmap's
remediation is lightweight adaptation (LoRA/adapters) on the
Hinglish_Data_Engine output before any custom-model work (Requirement
5.7); see :data:`LORA_ADAPTATION_HOOK`.

Args:
    eval_set_score: The evaluation-set score as a percentage
        (``0.0..100.0``).

Returns:
    ``True`` iff ``eval_set_score >= 80.0``.

#### `evaluate_benchmark`

```python
evaluate_benchmark(self, pairs: 'Iterable[tuple[str, str]]') -> 'BenchmarkResult'
```

Aggregate per-pair code-switch results into a benchmark result.

Each ``(input, output)`` pair is scored with :meth:`score`; the
evaluation-set score is the percentage of pairs within tolerance, and
the build passes iff that score is ``>= 80%`` (Requirement 5.6). When
the build does not pass, ``adaptation_hook`` names the
lightweight-adaptation (LoRA/adapters) remediation applied before any
custom-model work (Requirement 5.7).

Args:
    pairs: An iterable of ``(input, output)`` text pairs.

Returns:
    A :class:`BenchmarkResult` with the per-pair scores, the
    within-tolerance count, the total, the evaluation-set percentage,
    the pass flag, and the adaptation hook (``None`` when passing).


## class `CodeSwitchScore`

```python
CodeSwitchScore(input_ratio: 'float', output_ratio: 'float', difference_pp: 'float', within_tolerance: 'bool', quality: 'float') -> None
```

The code-switch quality result for one (input, output) pair.

Ratios are H/E percentages on a ``0.0..100.0`` scale (see the module
docstring for the H/E ratio definition). ``difference_pp`` is the absolute
gap between the two ratios expressed in **percentage points**.

Attributes:
    input_ratio: The input text's H/E ratio (percentage).
    output_ratio: The response text's H/E ratio (percentage).
    difference_pp: ``abs(output_ratio - input_ratio)`` in percentage points.
    within_tolerance: ``True`` iff ``difference_pp <= 15.0`` (Requirement
        5.4).
    quality: The per-pair quality score as a percentage — ``100.0`` when
        within tolerance, ``0.0`` otherwise — on the same scale as the
        evaluation-set aggregate.


## class `BenchmarkResult`

```python
BenchmarkResult(per_pair: 'list[CodeSwitchScore]', within_tolerance_count: 'int', total: 'int', eval_set_score: 'float', passes: 'bool', adaptation_hook: 'str | None') -> None
```

The aggregate Hinglish code-switch benchmark result over a pair set.

Attributes:
    per_pair: The per-pair :class:`CodeSwitchScore` results, in input order.
    within_tolerance_count: Number of pairs that were within tolerance.
    total: Total number of pairs evaluated.
    eval_set_score: The evaluation-set score as a percentage —
        ``100 * within_tolerance_count / total`` (``0.0`` for an empty set).
    passes: ``True`` iff ``eval_set_score >= 80.0`` (Requirement 5.6).
    adaptation_hook: Human-readable designation of the next remediation step
        when the benchmark does **not** pass: lightweight LoRA/adapter
        adaptation on the Hinglish_Data_Engine output, applied *before* any
        custom-model work (Requirement 5.7). ``None`` when the build passes.


## class `EmotionPersonaController`

```python
EmotionPersonaController(*, distress_labels: 'FrozenSet[str]' = frozenset({'fear', 'sad', 'angry'}), distress_confidence_threshold: 'float' = 0.5) -> 'None'
```

Selects a persona-conditioning mode from per-turn emotion features.

The controller is stateless; a single instance can be reused across turns.
The distress label set and confidence threshold are configurable for
testing/tuning but default to the design's values.

### Methods

#### `select_conditioning`

```python
select_conditioning(self, features: 'EmotionFeatures') -> 'ConditioningMode'
```

Return the :data:`ConditioningMode` to apply for this turn.

This is the core decision output (Requirements 6.3, 6.5, 6.7). The turn
always continues regardless of the outcome; failed/unavailable
extraction simply yields ``NEUTRAL`` rather than interrupting the turn.

#### `select`

```python
select(self, features: 'EmotionFeatures') -> 'ConditioningSelection'
```

Return the full :class:`ConditioningSelection` for this turn.

Exposes the effective, clamped conditioning V/A/D and discrete tag
alongside the mode (Requirement 6.1 — never emit out-of-range values).


## class `ConditioningSelection`

```python
ConditioningSelection(mode: 'ConditioningMode', valence: 'float', arousal: 'float', dominance: 'float', tag: 'str') -> None
```

The full result of a conditioning decision.

``mode`` is the core output (see :data:`ConditioningMode`). The
``valence`` / ``arousal`` / ``dominance`` fields carry the *effective*
conditioning vector that should be injected for the turn — always clamped to
``[-1.0, 1.0]`` — and ``tag`` is the dominant discrete label applied.

For ``NEUTRAL`` the vector is ``(0.0, 0.0, 0.0)`` with the ``"neutral"`` tag.


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


## class `SafetyGuard`

```python
SafetyGuard(watermark_detector: 'Optional[WatermarkDetector]' = None) -> 'None'
```

LEAN-scope safety subsystem.

This class implements the **watermarking** responsibility (Requirement
10.2), the **consent gating + consent log** responsibility (Requirements
10.1, 10.3, 10.6), and the **crisis handling** responsibility (Requirements
10.4, 10.5). Each responsibility is an independent method group; crisis
handling was added purely additively and shares no mutable state with the
other groups.

Args:
    watermark_detector: The detector used to verify an applied watermark.
        Defaults to a fresh :class:`WatermarkDetector`. Injectable so the
        guard can be exercised against a detector that reports failure (the
        "watermark cannot be verified" path).

### Methods

#### `watermark_detector` _(property)_

The detector this guard uses to verify applied watermarks.

#### `apply_watermark`

```python
apply_watermark(self, output: 'SynthesizedOutput') -> 'SynthesizedOutput'
```

Apply a watermark to ``output`` regardless of which path produced it.

Watermarking is unconditional: it is applied on *every* output path,
including the Phase 1 and TTS fallback paths (Requirement 10.2). The
watermark token is derived deterministically from the output's content
and path, so re-applying is idempotent. The same ``output`` instance is
returned with its ``watermark`` field populated.

#### `guard_output`

```python
guard_output(self, content: 'str', path: 'str') -> 'EmissionResult'
```

Watermark a synthesized output and gate its emission on verification.

On every path (core or fallback) the output is watermarked, then the
watermark detector is asked to verify it. If the watermark is reported
as detected the output is compliant and emittable; if it cannot be
verified the output is flagged non-compliant and withheld rather than
emitted (Requirement 10.2).

Args:
    content: Opaque stand-in for the synthesized audio payload.
    path: The output path that produced the output (e.g. one of
        :data:`OUTPUT_PATHS`).

Returns:
    An :class:`EmissionResult` describing the watermarked output, the
    compliance decision, and whether the output is emitted.

#### `evaluate_output`

```python
evaluate_output(self, output: 'SynthesizedOutput') -> 'EmissionResult'
```

Watermark an existing output (if needed) and gate its emission.

Equivalent to :meth:`guard_output` but for a pre-built
:class:`SynthesizedOutput`; the watermark is (re)applied so the
every-path guarantee holds even for outputs handed in already-formed.

#### `evaluate_cloning_request`

```python
evaluate_cloning_request(self, consent: 'Optional[ConsentRecord]', *, product_facing: 'bool' = True) -> 'CloningDecision'
```

Decide a cloning / voice-style-transfer request against consent.

The request is allowed **if and only if** a *valid*
:class:`~roadmap.models.runtime.ConsentRecord` is supplied — i.e.
``speaker_id``, ``permitted_use_scope`` and ``timestamp`` are all
present and non-empty, as reported by
:meth:`ConsentRecord.is_valid` (Requirement 10.1).

- **Valid consent →** returns ``CloningDecision(allowed=True, ...,
  reference_retained=True)``. When ``product_facing`` is ``True`` the
  consent is also recorded into the product-facing consent log so the
  three fields are retained while the voice is in use (Requirement
  10.6).
- **Missing/invalid consent →** the request is refused: returns
  ``CloningDecision(allowed=False, ...)`` with a reason that indicates
  the refusal, and ``reference_retained=False`` so no voice reference is
  kept without valid consent (Requirement 10.3). Nothing is added to the
  consent log.

Args:
    consent: The consent record for the speaker, or ``None`` when no
        consent was recorded.
    product_facing: Whether this voice is being used in a product-facing
        capacity. Only product-facing, validly consented voices are
        added to the retained consent log (Requirement 10.6).

Returns:
    The :class:`~roadmap.models.runtime.CloningDecision` for the request.

#### `request_cloning`

```python
request_cloning(self, consent: 'Optional[ConsentRecord]', *, speaker_id: 'Optional[str]' = None, product_facing: 'bool' = True) -> 'CloningDecision'
```

Request cloning / voice-style transfer for a speaker's voice.

Thin, task-facing entry point that names the operation the way a caller
thinks about it ("request to clone this voice"); it delegates to
:meth:`evaluate_cloning_request`, which holds the authoritative
consent-gating logic (Requirements 10.1, 10.3, 10.6).

The request is allowed **if and only if** a *valid*
:class:`~roadmap.models.runtime.ConsentRecord` is supplied — all three
fields (``speaker_id``, ``permitted_use_scope``, ``timestamp``) present
and non-empty. Otherwise it is refused: the returned
:class:`~roadmap.models.runtime.CloningDecision` has ``allowed=False``,
a ``reason`` that indicates the refusal, and ``reference_retained=False``
so no voice reference is kept without valid consent (Requirement 10.3).
When allowed and ``product_facing`` is true, the consent is recorded
into the retained product-facing consent log (Requirement 10.6).

Args:
    consent: The consent record for the speaker, or ``None`` when no
        consent was recorded.
    speaker_id: Optional speaker identifier for the requested voice. When
        supplied alongside a valid ``consent`` whose ``speaker_id``
        differs, the request is refused (the consent does not cover the
        requested speaker), and no reference is retained.
    product_facing: Whether this voice is being used in a product-facing
        capacity; only product-facing, validly consented voices enter the
        retained consent log.

Returns:
    The :class:`~roadmap.models.runtime.CloningDecision` for the request.

#### `record_consent`

```python
record_consent(self, consent: 'ConsentRecord') -> 'ConsentLogEntry'
```

Record a valid consent into the product-facing consent log.

Adds (or refreshes) the entry for the consenting speaker and marks the
voice as in use, so the three consent fields are retained while the
voice remains in product-facing use (Requirement 10.6). Every logged
entry is itself valid — an invalid consent record is rejected before it
can enter the log.

Args:
    consent: A valid consent record for a product-facing voice.

Returns:
    The :class:`ConsentLogEntry` now retained in the log.

Raises:
    ValueError: If ``consent`` is not valid (any field missing/empty).

#### `mark_voice_not_in_use`

```python
mark_voice_not_in_use(self, speaker_id: 'str') -> 'bool'
```

Mark a voice as no longer in product-facing use and drop its entry.

Enforces the "retained while in use" half of Requirement 10.6: once a
voice is no longer product-facing, its consent-log entry is released
from the active retained log.

Args:
    speaker_id: The speaker whose voice is no longer in use.

Returns:
    ``True`` if an entry was present and removed, ``False`` otherwise.

#### `retire_voice`

```python
retire_voice(self, speaker_id: 'str') -> 'bool'
```

Retire a product-facing voice: drop its retained consent-log entry.

Task-facing alias for :meth:`mark_voice_not_in_use`. Named the way a
caller thinks about ending a voice's product-facing life ("retire this
voice"); it performs exactly the same retention release, enforcing the
"retained *while in use*" half of Requirement 10.6 — once retired, the
voice's three consent fields are no longer held in the active log.

Args:
    speaker_id: The speaker whose voice is being retired.

Returns:
    ``True`` if an entry was present and removed, ``False`` otherwise.

#### `is_voice_in_use`

```python
is_voice_in_use(self, speaker_id: 'str') -> 'bool'
```

Return ``True`` iff a retained consent-log entry exists for the voice.

#### `get_consent_log_entry`

```python
get_consent_log_entry(self, speaker_id: 'str') -> 'Optional[ConsentLogEntry]'
```

Return the retained consent-log entry for ``speaker_id``, if any.

#### `consent_log`

```python
consent_log(self) -> 'list[ConsentLogEntry]'
```

Return the current product-facing consent log as a list.

Every returned entry carries the three consent fields (speaker id,
permitted-use scope, timestamp) and is valid; only voices currently in
product-facing use are present (Requirement 10.6). The returned list is
a fresh snapshot, so callers cannot mutate the guard's internal state.

#### `handle_crisis`

```python
handle_crisis(self, crisis_score: 'float', *, threshold: 'float' = 0.5, guidance: 'str' = "It sounds like you may be going through something really difficult. You don't have to face this alone — please consider reaching out to a trusted person or a local crisis/helpline service right now. If you are in immediate danger, contact your local emergency number.") -> 'CrisisDecision'
```

Apply the crisis decision to an (upstream) classifier score.

The crisis classifier is upstream and out of scope here; this method
owns only the *decision* applied to its real-valued ``crisis_score``.
The threshold comparison is **inclusive** at the boundary:

- ``crisis_score >= threshold`` → both required actions fire together:
  crisis-support guidance is surfaced to the user **and** the turn is
  flagged for human review (Requirements 10.4, 10.5). The returned
  :class:`CrisisDecision` has ``crisis_support_surfaced=True``,
  ``flagged_for_human_review=True`` and carries the ``guidance`` text.
- ``crisis_score < threshold`` → **neither** action fires: both booleans
  are ``False`` and ``guidance`` is ``None``.

A score exactly equal to ``threshold`` therefore triggers both actions
(the boundary is inclusive).

Args:
    crisis_score: The crisis classifier's score for the turn (a real
        number; conventionally in ``[0.0, 1.0]`` but not required to be).
    threshold: The decision threshold to compare against, inclusive at
        the boundary. Defaults to :data:`CRISIS_DECISION_THRESHOLD`.
    guidance: The crisis-support guidance text to surface when the
        decision triggers. Defaults to :data:`CRISIS_SUPPORT_GUIDANCE`.

Returns:
    A frozen :class:`CrisisDecision` recording whether each action fired,
    the ``crisis_score`` and ``threshold`` it was decided on, and the
    surfaced ``guidance`` (or ``None`` when below threshold).


## class `SynthesizedOutput`

```python
SynthesizedOutput(content: 'str', path: 'str', watermark: 'Optional[str]' = None) -> None
```

An abstract synthesized audio output payload.

The audio itself is modelled opaquely as ``content`` (any string stand-in
for the synthesized waveform/token stream). ``path`` records which output
path produced it so the watermark guarantee can be asserted per path, and
``watermark`` holds the applied watermark token (``None`` until a watermark
has been applied).

Attributes:
    content: Opaque stand-in for the synthesized audio payload.
    path: The output path that produced this output (e.g. one of
        :data:`OUTPUT_PATHS`); must be a non-empty identifier.
    watermark: The applied watermark token, or ``None`` if not yet applied.

### Methods

#### `is_watermarked` _(property)_

``True`` iff a non-empty watermark token has been applied.


## class `EmissionResult`

```python
EmissionResult(output: 'SynthesizedOutput', compliant: 'bool', emitted: 'bool', watermark_detected: 'bool', reason: 'str' = '') -> None
```

The outcome of watermarking and compliance-checking an output.

An output is emittable only when its watermark is verified as detected. When
verification fails, the output is flagged non-compliant and withheld
(``emitted=False``) rather than released (Requirement 10.2).

Attributes:
    output: The (watermarked) :class:`SynthesizedOutput`.
    compliant: ``True`` iff the watermark was verified as detected.
    emitted: ``True`` iff the output is released; equals ``compliant``.
    watermark_detected: The raw detector verdict for the output.
    reason: Human-readable explanation of the decision.


## class `WatermarkDetector`

```python
WatermarkDetector()
```

A deterministic, mocked watermark detector.

Stands in for a real audio-watermark detector. It verifies that an output
carries the expected watermark token for its content under
:data:`WATERMARK_SCHEME`. Detection succeeds only when a watermark is
present *and* matches the token that :meth:`expected_watermark` derives from
the output's content and path, so a missing or tampered watermark is
correctly reported as *not detected*.

The detector is intentionally injectable into :class:`SafetyGuard` so the
guard can re-verify what it just embedded, and so tests can substitute a
detector that fails to model the "watermark cannot be verified" case.

### Methods

#### `expected_watermark`

```python
expected_watermark(self, content: 'str', path: 'str') -> 'str'
```

Return the canonical watermark token for ``content`` on ``path``.

The token is a deterministic function of the content and path, so the
same output always yields the same watermark and the detector can
recompute and compare it without any shared mutable state.

#### `detect`

```python
detect(self, output: 'SynthesizedOutput') -> 'bool'
```

Return ``True`` iff ``output`` carries a verifiable watermark.


## class `ConsentLogEntry`

```python
ConsentLogEntry(speaker_id: 'str', permitted_use_scope: 'str', timestamp: 'float', in_use: 'bool' = True) -> None
```

One product-facing consent-log record for a voice in use.

The consent log is the product-facing record the design's *Safety Guard*
requires for **every** voice used in a product-facing capacity. Each entry
carries exactly the three consent fields — ``speaker_id``,
``permitted_use_scope`` and ``timestamp`` — and is retained while the voice
remains in product-facing use (Requirement 10.6).

Retention semantics: an entry is kept (``in_use=True``) for as long as the
voice it describes is in product-facing use. Marking the voice as no longer
in use flips ``in_use`` to ``False``, which the :class:`SafetyGuard` uses to
drop the entry from the active retained log — so "retained while in use" is
enforced explicitly rather than by indefinite accumulation.

Every entry is itself valid: it is only ever constructed from a valid
:class:`~roadmap.models.runtime.ConsentRecord` (all three fields present and
non-empty), and :meth:`is_valid` re-checks that invariant.

Attributes:
    speaker_id: The consenting speaker's identifier (non-empty).
    permitted_use_scope: The scope the speaker consented to (non-empty).
    timestamp: The consent timestamp as a float epoch value (> 0).
    in_use: ``True`` while the voice remains in product-facing use.

### Methods

#### `from_consent`

```python
from_consent(consent: 'ConsentRecord', *, in_use: 'bool' = True) -> "'ConsentLogEntry'"
```

Build a log entry from a (valid) consent record.

Raises:
    ValueError: If ``consent`` is not valid (any of the three fields
        missing/empty), so an invalid entry can never enter the log.

#### `is_valid`

```python
is_valid(self) -> 'bool'
```

Return ``True`` iff all three consent fields are present and non-empty.


## class `CrisisDecision`

```python
CrisisDecision(crisis_support_surfaced: 'bool', flagged_for_human_review: 'bool', score: 'float', threshold: 'float', guidance: 'Optional[str]' = None) -> None
```

The outcome of applying the crisis decision to a classifier score.

Crisis handling is an all-or-nothing pair of actions tied to a single
threshold comparison (Requirements 10.4, 10.5):

- When the crisis-classifier ``score`` is **at or above** the decision
  ``threshold`` (``score >= threshold`` — the boundary is *inclusive*), both
  actions fire together: crisis-support guidance is surfaced to the user
  (``crisis_support_surfaced=True``, with the guidance in ``guidance``) and
  the turn is flagged for human review (``flagged_for_human_review=True``).
- When ``score`` is **strictly below** ``threshold`` neither action fires:
  both booleans are ``False`` and ``guidance`` is ``None``.

The two booleans therefore always move together, and :meth:`triggered`
reports that shared verdict. The instance is frozen so a recorded decision
cannot be mutated after the fact.

Attributes:
    crisis_support_surfaced: ``True`` iff crisis-support guidance was
        surfaced to the user.
    flagged_for_human_review: ``True`` iff the turn was flagged for human
        review.
    score: The crisis-classifier score the decision was made on.
    threshold: The decision threshold compared against (inclusive).
    guidance: The crisis-support guidance text surfaced, or ``None`` when
        the decision did not trigger.

### Methods

#### `triggered` _(property)_

``True`` iff crisis handling fired (both actions occurred together).


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
