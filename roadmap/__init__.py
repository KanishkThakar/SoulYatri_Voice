"""SoulYatri speech-native voice roadmap tooling package.

This package holds the *planning/roadmap* decision-logic tooling and its tests.
It contains pure, testable functions that operate on the roadmap's planning
objects (phases, tracks, gates, selection criteria, budgets, licensing records)
plus the property-based and structural tests that verify them.

No module in this package executes a GPU model-training run; the evaluation
harness is fully mocked (out of scope per Requirements 4.6, 12.4, 12.5).

The narrative planning artifact lives at ``roadmap/ROADMAP.md`` and its location
is exposed as :data:`ROADMAP_MD_PATH` for tests to resolve.

Public API
----------
This module is the cohesive package façade. It re-exports the public planning
dataclasses, the decision-logic components, and a single
:func:`evaluate_and_select` pipeline helper that wires the mocked
:class:`EvaluationHarness`, the :class:`SelectionScorer`, and the
:class:`GateEvaluator` (+ :class:`LicensingRegister`) into one pass:

>>> from roadmap import evaluate_and_select, MockCandidate
>>> result = evaluate_and_select([MockCandidate("kyutai/moshiko-pytorch-bf16", "bf16")])
>>> result.selection.selected  # 'RETAIN_PHASE_1' when no selection scores are given
'RETAIN_PHASE_1'

All imports below are plain Python; none pulls in a GPU/training framework and
none invokes a GPU/model-training run, so the package continues to satisfy the
import-only / no-training AST guarantee enforced by ``test_config_smoke.py``
(Requirement 4.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# --- Filesystem path constants (existing exports) -------------------------
from .paths import DOCS_DIR, PACKAGE_ROOT, ROADMAP_MD_PATH, WORKSPACE_ROOT

# --- Planning data models -------------------------------------------------
from .models.phases import (
    GATE_KIND_VALUES,
    OPERATOR_VALUES,
    TRACK_VALUES,
    Gate,
    GateCriterion,
    GateKind,
    Operator,
    Phase,
    Track,
)
from .models.selection import (
    RETAIN_PHASE_1,
    SELECTION_CRITERIA,
    SELECTION_MINIMUMS,
    SELECTION_WEIGHTS,
    CandidateScores,
    CriterionResult,
    GateResult,
    SelectionOutcome,
)
from .models.runtime import (
    CloningDecision,
    ComplianceWarning,
    ConditioningMode,
    ConsentRecord,
    EmotionFeatures,
    HarnessRun,
    LicenseEntry,
    NormalizationResult,
)

# --- Roadmap aggregate ----------------------------------------------------
from .roadmap_model import (
    FIRST_PHASE_ID,
    ConflictEntry,
    Roadmap,
    ScopeStatements,
)

# --- Decision-logic components --------------------------------------------
from .licensing import (
    RECOGNIZED_OSS_LICENSES,
    ExclusionCategory,
    ExclusionRecord,
    LicensingRegister,
)
from .gate_evaluator import MISSING_MEASUREMENT, DecisionGateResult, GateEvaluator
from .selection_scorer import SelectionScorer
from .evaluation_harness import (
    DEFAULT_SAMPLE_ITEMS,
    MAX_ITEMS,
    METRIC_KEYS,
    EvaluationHarness,
    MetricReproducibility,
    MockCandidate,
    ReproducibilityReport,
    within_tolerance,
)
from .hinglish import BenchmarkResult, CodeSwitchScore, HinglishDataEngine
from .emotion_persona import ConditioningSelection, EmotionPersonaController
from .duplex_manager import (
    BargeInDecision,
    CoreFailureType,
    DuplexConfig,
    DuplexManager,
    FallbackTarget,
    LatencyFallbackDecision,
    TurnPhase,
)
from .safety_guard import (
    ConsentLogEntry,
    CrisisDecision,
    EmissionResult,
    SafetyGuard,
    SynthesizedOutput,
    WatermarkDetector,
)
from .budget_planner import (
    AmbitiousJustification,
    BudgetComputePlanner,
    BudgetRange,
    ComputeFootprint,
    ScopePlan,
)


@dataclass
class PipelineResult:
    """The bundled result of one :func:`evaluate_and_select` pipeline pass.

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
    """

    harness_runs: list[HarnessRun]
    selection: SelectionOutcome
    gate_result: Optional[GateResult] = None


def evaluate_and_select(
    candidates: list[MockCandidate],
    *,
    selection_scores: Optional[dict[str, dict[str, float]]] = None,
    gate: Optional[Gate] = None,
    gate_measurements: Optional[dict[str, float]] = None,
    registry: Optional[LicensingRegister] = None,
    sample_items: int = DEFAULT_SAMPLE_ITEMS,
) -> PipelineResult:
    """Run the mocked evaluate → select → gate pipeline over a candidate set.

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
    """
    harness = EvaluationHarness(sample_items=sample_items)
    harness_runs = harness.evaluate_all(candidates)

    scores_by_model = selection_scores or {}
    candidate_scores = [
        CandidateScores(
            model_id=run.model_id,
            revision=run.revision,
            scores=dict(scores_by_model.get(run.model_id, {})),
        )
        for run in harness_runs
        if not run.excluded
    ]
    selection = SelectionScorer().select(candidate_scores)

    gate_result: Optional[GateResult] = None
    if gate is not None:
        gate_result = GateEvaluator().evaluate(
            gate, gate_measurements or {}, registry
        )

    return PipelineResult(
        harness_runs=harness_runs,
        selection=selection,
        gate_result=gate_result,
    )


__all__ = [
    # -- Filesystem path constants --
    "PACKAGE_ROOT",
    "WORKSPACE_ROOT",
    "ROADMAP_MD_PATH",
    "DOCS_DIR",
    # -- Pipeline façade --
    "evaluate_and_select",
    "PipelineResult",
    # -- Phase / track / gate models --
    "Track",
    "TRACK_VALUES",
    "Operator",
    "OPERATOR_VALUES",
    "GateKind",
    "GATE_KIND_VALUES",
    "Phase",
    "GateCriterion",
    "Gate",
    # -- Selection / gate-result models --
    "RETAIN_PHASE_1",
    "SELECTION_WEIGHTS",
    "SELECTION_MINIMUMS",
    "SELECTION_CRITERIA",
    "CriterionResult",
    "GateResult",
    "CandidateScores",
    "SelectionOutcome",
    # -- Runtime models --
    "HarnessRun",
    "EmotionFeatures",
    "ConditioningMode",
    "ConsentRecord",
    "CloningDecision",
    "LicenseEntry",
    "ComplianceWarning",
    "NormalizationResult",
    # -- Roadmap aggregate --
    "Roadmap",
    "ConflictEntry",
    "ScopeStatements",
    "FIRST_PHASE_ID",
    # -- Licensing register --
    "LicensingRegister",
    "RECOGNIZED_OSS_LICENSES",
    "ExclusionRecord",
    "ExclusionCategory",
    # -- Gate evaluator --
    "GateEvaluator",
    "DecisionGateResult",
    "MISSING_MEASUREMENT",
    # -- Selection scorer --
    "SelectionScorer",
    # -- Evaluation harness --
    "EvaluationHarness",
    "MockCandidate",
    "ReproducibilityReport",
    "MetricReproducibility",
    "within_tolerance",
    "METRIC_KEYS",
    "DEFAULT_SAMPLE_ITEMS",
    "MAX_ITEMS",
    # -- Hinglish data engine --
    "HinglishDataEngine",
    "CodeSwitchScore",
    "BenchmarkResult",
    # -- Emotion / persona controller --
    "EmotionPersonaController",
    "ConditioningSelection",
    # -- Duplex manager --
    "DuplexManager",
    "TurnPhase",
    "CoreFailureType",
    "FallbackTarget",
    "BargeInDecision",
    "LatencyFallbackDecision",
    "DuplexConfig",
    # -- Safety guard --
    "SafetyGuard",
    "SynthesizedOutput",
    "EmissionResult",
    "WatermarkDetector",
    "ConsentLogEntry",
    "CrisisDecision",
    # -- Budget & compute planner --
    "BudgetComputePlanner",
    "BudgetRange",
    "ComputeFootprint",
    "ScopePlan",
    "AmbitiousJustification",
]
