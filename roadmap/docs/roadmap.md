# `roadmap.roadmap`

Public API of the `roadmap.roadmap` component. Generated from live signatures and docstrings.

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
