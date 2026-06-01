"""Shared test fixtures, builders, and strategies for the roadmap test suite.

This module is **not** a test module — it is named ``fixtures.py`` (not
``test_*.py``) so pytest does not collect it as tests. It provides three kinds
of reusable test material consumed by the consolidated edge-case suite
(task 45.2) and the regression suite (task 45.3):

1. **Plain builder functions** (``make_*``) that construct *valid canonical*
   instances of the roadmap planning dataclasses, with sensible defaults that
   callers can override. Every builder respects the construction-time
   validation in the underlying dataclasses (e.g. a :class:`Phase` always
   carries >= 1 guide section and a GPU class; :func:`make_valid_roadmap`
   produces a contiguous ``P1-baseline``..``P7`` roadmap whose first phase is
   ``P1-baseline`` and whose final phase is speech-native).

2. **A few pytest fixtures** that expose the most common canonical instances
   (a valid roadmap, a launch gate, a decision gate, a clean licensing
   register, a Hinglish engine, an emotion controller) for tests that prefer
   dependency-injected fixtures over direct builder calls.

3. **Hypothesis strategies** that exercise the decision-logic input space
   intelligently (out-of-range V/A/D, zero/one/many passing candidates, missing
   gate metrics, partial consent, 0–100% token ratios, zero/invalid compute).

It also exposes :data:`REGRESSION_CASES_PATH` and :func:`load_regression_cases`
so the regression suite (task 45.3) can load ``regression_cases.json`` — the
companion data file of known input→expected-output examples for the decision
logic — without re-resolving the path.

Regression-cases JSON schema
----------------------------
``regression_cases.json`` is a top-level object. Besides the ``_schema`` and
``description`` documentation keys it carries one array per decision-logic
category. Each entry is a self-contained case with a human-readable
``description`` plus the inputs and the *verified* expected outputs:

``selection`` (``roadmap.SelectionScorer``)
    ``{description, candidate_scores: {model_id: {criterion: score}},
       expected_selected: "<model_id>"|"RETAIN_PHASE_1",
       expected_passing: [model_id, ...]}``. ``candidate_scores`` preserves
    insertion order, which defines the scorer's first-wins tie-break order.

``gate_evaluation`` (``roadmap.GateEvaluator``, clean register)
    ``{description, criteria: [{metric_name, threshold, operator}],
       measured: {metric_name: value}, expected_overall_passed: bool,
       expected_blocked: bool}``. A metric absent from ``measured`` is
    fail-closed.

``emotion`` (``roadmap.EmotionPersonaController``)
    ``{description, label: str|null, confidence: float, extraction_ok: bool,
       expected_mode: "NEUTRAL"|"EMPATHETIC"|"STANDARD"}``. V/A/D default to
    ``0.0`` in the consuming test (they do not affect the mode decision).

``hinglish_score`` (``roadmap.HinglishDataEngine``)
    ``{description, input, output, expected_within_tolerance: bool}`` — whether
    ``|output H/E ratio - input H/E ratio| <= 15`` percentage points.

The expected values were verified by reasoning about the actual
implementations (``SELECTION_WEIGHTS``/``SELECTION_MINIMUMS`` for selection, the
operator semantics + fail-closed rule for gates, the distress label/confidence
rule for emotion, and the H/E-ratio definition for Hinglish scoring).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from hypothesis import strategies as st

from roadmap.budget_planner import BudgetComputePlanner
from roadmap.emotion_persona import EmotionPersonaController
from roadmap.evaluation_harness import MockCandidate
from roadmap.gate_evaluator import GateEvaluator
from roadmap.hinglish import HinglishDataEngine
from roadmap.licensing import LicensingRegister
from roadmap.models.phases import Gate, GateCriterion, Phase
from roadmap.models.runtime import (
    ConsentRecord,
    EmotionFeatures,
    LicenseEntry,
)
from roadmap.models.selection import (
    SELECTION_CRITERIA,
    SELECTION_MINIMUMS,
    CandidateScores,
)
from roadmap.roadmap_model import FIRST_PHASE_ID, Roadmap
from roadmap.selection_scorer import SelectionScorer

try:  # pytest is always available in the test env; guard keeps import-only use safe.
    import pytest
except ImportError:  # pragma: no cover - fixtures still importable without pytest
    pytest = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Regression-cases data file
# ---------------------------------------------------------------------------

#: Absolute path to the companion regression-cases data file consumed by the
#: regression suite (task 45.3).
REGRESSION_CASES_PATH: Path = Path(__file__).resolve().parent / "regression_cases.json"


def load_regression_cases() -> dict:
    """Load and return the parsed ``regression_cases.json`` data file.

    Returns:
        The top-level JSON object as a ``dict`` (including the ``_schema`` and
        ``description`` documentation keys and one array per decision-logic
        category).
    """
    with REGRESSION_CASES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Builders — phases, gates, criteria
# ---------------------------------------------------------------------------


def make_criterion(
    metric_name: str = "latency_ms_p50",
    threshold: float = 300.0,
    operator: str = "<=",
) -> GateCriterion:
    """Build a valid :class:`GateCriterion` with overridable fields."""
    return GateCriterion(
        metric_name=metric_name,
        threshold=threshold,
        operator=operator,
    )


def make_phase(
    ordinal: int = 1,
    id: str = FIRST_PHASE_ID,
    *,
    track: str = "LEAN",
    title: Optional[str] = None,
    is_speech_native: bool = False,
    guide_sections: Optional[list[str]] = None,
    compute_min_gpu_class: str = "L4",
    compute_min_vram_gb: float = 24.0,
) -> Phase:
    """Build a valid :class:`Phase`.

    Defaults produce the baseline (ordinal 1, ``P1-baseline``) phase. Every
    default keeps the phase valid: a non-empty title (derived from the ordinal
    when not given), at least one guide section, a non-empty GPU class, and a
    non-negative VRAM figure.
    """
    return Phase(
        ordinal=ordinal,
        id=id,
        track=track,
        title=title if title is not None else f"Phase {ordinal}",
        is_speech_native=is_speech_native,
        guide_sections=(
            list(guide_sections)
            if guide_sections is not None
            else [f"Guide section for {id}"]
        ),
        compute_min_gpu_class=compute_min_gpu_class,
        compute_min_vram_gb=compute_min_vram_gb,
    )


#: The canonical seven-phase plan from the design's phase table: five LEAN
#: phases (``P1-baseline``..``P5-safety-gate``) followed by two optional
#: AMBITIOUS phases (``P6-custom``, ``P7-diff-gate``). The final phase is
#: speech-native. ``(ordinal, id, track, title, is_speech_native)``.
_CANONICAL_PHASES: tuple[tuple[int, str, str, str, bool], ...] = (
    (1, FIRST_PHASE_ID, "LEAN", "Phase_1_Pipeline (existing classic cascade)", False),
    (2, "P2-core-select", "LEAN", "Speech-Native Core selection + Evaluation Harness", False),
    (3, "P3-integrate", "LEAN", "Concurrent integration (core + Phase 1 fallback)", False),
    (4, "P4-moat-duplex", "LEAN", "Hinglish moat + Emotion/Persona + Full-duplex + Latency", False),
    (5, "P5-safety-gate", "LEAN", "Safety/consent/watermark + LEAN Demo Launch Gate", False),
    (6, "P6-custom", "AMBITIOUS", "Custom codec/tokenizer + alignment (DPO/GRPO)", False),
    (7, "P7-diff-gate", "AMBITIOUS", "AMBITIOUS Differentiation Launch Gate (speech-native platform)", True),
)


def make_valid_roadmap() -> Roadmap:
    """Build a valid, canonical seven-phase :class:`Roadmap`.

    Produces the design's ``P1-baseline``..``P7-diff-gate`` plan: ordinals are
    contiguous starting at 1, ids are unique, the first phase is
    ``P1-baseline``, and the final (ordinal-7) phase is speech-native. Each
    phase carries one guide section and a compute footprint, so the aggregate's
    phase-structure invariant is satisfied.
    """
    phases = [
        make_phase(
            ordinal=ordinal,
            id=phase_id,
            track=track,
            title=title,
            is_speech_native=is_speech_native,
            guide_sections=[f"Implementation guide → {phase_id}"],
        )
        for ordinal, phase_id, track, title, is_speech_native in _CANONICAL_PHASES
    ]
    return Roadmap(phases=phases)


def make_gate(
    id: str = "LEAN-DEMO",
    kind: str = "launch",
    *,
    entry_criteria: Optional[list[GateCriterion]] = None,
    exit_criteria: Optional[list[GateCriterion]] = None,
    owner_role: str = "Release Manager",
    fallback_action: str = "remain on LEAN_Track",
) -> Gate:
    """Build a valid :class:`Gate` (a launch gate by default).

    The default exit criteria mirror the design's LEAN demo gate shape: a p50
    first-response latency ceiling (``<= 300 ms``) and a Hinglish code-switch
    quality floor (``>= 80``).
    """
    return Gate(
        id=id,
        kind=kind,
        entry_criteria=list(entry_criteria) if entry_criteria is not None else [],
        exit_criteria=(
            list(exit_criteria)
            if exit_criteria is not None
            else [
                make_criterion("latency_ms_p50", 300.0, "<="),
                make_criterion("hinglish_codeswitch_quality", 80.0, ">="),
            ]
        ),
        owner_role=owner_role,
        fallback_action=fallback_action,
    )


def make_decision_gate(
    id: str = "G1",
    *,
    owner_role: str = "ML Lead",
    fallback_action: str = "remain on LEAN_Track",
    exit_criteria: Optional[list[GateCriterion]] = None,
) -> Gate:
    """Build a valid Decision_Gate (``kind="decision"``) — ``G1`` by default."""
    return make_gate(
        id=id,
        kind="decision",
        owner_role=owner_role,
        fallback_action=fallback_action,
        exit_criteria=exit_criteria,
    )


# ---------------------------------------------------------------------------
# Builders — selection
# ---------------------------------------------------------------------------


def make_passing_selection_scores() -> dict[str, float]:
    """Return a per-criterion score map that clears every ``SELECTION_MINIMUMS``.

    Each criterion is scored 10 points above its minimum (capped at 100), so the
    resulting candidate passes ``passes_all_minimums`` for the canonical table.
    """
    return {
        criterion: min(100.0, float(SELECTION_MINIMUMS[criterion]) + 10.0)
        for criterion in SELECTION_CRITERIA
    }


def make_failing_selection_scores(failing_criterion: str = "community_activity") -> dict[str, float]:
    """Return a score map that clears every minimum except ``failing_criterion``.

    Useful for building a candidate that is evaluable and scores well overall but
    is excluded from selection because a single per-criterion minimum is missed.
    """
    scores = make_passing_selection_scores()
    scores[failing_criterion] = 0.0
    return scores


def make_candidate_scores(
    model_id: str = "kyutai/moshiko-pytorch-bf16",
    revision: str = "bf16",
    scores: Optional[dict[str, float]] = None,
) -> CandidateScores:
    """Build a :class:`CandidateScores`, defaulting to a passing score map."""
    return CandidateScores(
        model_id=model_id,
        revision=revision,
        scores=scores if scores is not None else make_passing_selection_scores(),
    )


def make_mock_candidate(
    model_id: str = "kyutai/moshiko-pytorch-bf16",
    revision: str = "bf16",
    *,
    seeds: Optional[dict[str, float]] = None,
    license_compat: str = "compatible",
    hardware: Optional[dict] = None,
    weights_available: bool = True,
) -> MockCandidate:
    """Build a valid :class:`MockCandidate` for the evaluation harness.

    Defaults to an evaluable candidate (compatible license, ample VRAM, weights
    available) so it produces a scored, non-excluded :class:`HarnessRun`.
    """
    return MockCandidate(
        model_id=model_id,
        revision=revision,
        seeds=dict(seeds) if seeds is not None else {},
        license_compat=license_compat,
        hardware=(
            dict(hardware)
            if hardware is not None
            else {"gpu_class": "L4", "vram_gb": 24.0}
        ),
        weights_available=weights_available,
    )


# ---------------------------------------------------------------------------
# Builders — emotion, safety, licensing
# ---------------------------------------------------------------------------


def make_emotion_features(
    label: Optional[str] = "neutral",
    confidence: float = 0.5,
    *,
    valence: float = 0.0,
    arousal: float = 0.0,
    dominance: float = 0.0,
    extraction_ok: bool = True,
) -> EmotionFeatures:
    """Build :class:`EmotionFeatures` (V/A/D are clamped to ``[-1, 1]``)."""
    return EmotionFeatures(
        label=label,
        confidence=confidence,
        valence=valence,
        arousal=arousal,
        dominance=dominance,
        extraction_ok=extraction_ok,
    )


def make_consent_record(
    speaker_id: str = "speaker-001",
    permitted_use_scope: str = "voice-style-transfer",
    timestamp: float = 1_700_000_000.0,
) -> ConsentRecord:
    """Build a valid (``is_valid() is True``) :class:`ConsentRecord`."""
    return ConsentRecord(
        speaker_id=speaker_id,
        permitted_use_scope=permitted_use_scope,
        timestamp=timestamp,
    )


def make_license_entry(
    component_name: str = "kyutai/moshiko-pytorch-bf16",
    license_id: Optional[str] = "Apache-2.0",
    *,
    constraints: Optional[list[str]] = None,
    intended_use_permitted: bool = True,
    recorded_before_use: bool = True,
    redistribution_restricted: bool = False,
    restriction_type: Optional[str] = None,
) -> LicenseEntry:
    """Build a :class:`LicenseEntry` (a clean, permitted entry by default)."""
    return LicenseEntry(
        component_name=component_name,
        license_id=license_id,
        constraints=list(constraints) if constraints is not None else [],
        intended_use_permitted=intended_use_permitted,
        recorded_before_use=recorded_before_use,
        redistribution_restricted=redistribution_restricted,
        restriction_type=restriction_type,
    )


def make_clean_registry() -> LicensingRegister:
    """Build a :class:`LicensingRegister` with one recorded, permitted component.

    The register has no unresolved compliance warning and no prohibiting
    license, so it does not block an otherwise-passing gate.
    """
    registry = LicensingRegister()
    registry.record_component(
        "kyutai/moshiko-pytorch-bf16",
        license_id="Apache-2.0",
        constraints=[],
        intended_use_permitted=True,
    )
    return registry


def make_budget_planner() -> BudgetComputePlanner:
    """Build a :class:`BudgetComputePlanner` seeded with the canonical phases."""
    return BudgetComputePlanner(phases=make_valid_roadmap().phases)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

#: A finite real number on the unit-ish band, deliberately *out of range* of the
#: V/A/D ``[-1, 1]`` bounds on both ends so tests can assert clamping.
out_of_range_vad = st.floats(
    min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
)

#: A confidence value on the inclusive ``0.0..1.0`` scale.
confidence_value = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

#: The seven discrete emotion tags (or ``None`` for failed/unavailable
#: extraction).
emotion_label = st.sampled_from(
    ["neutral", "happy", "sad", "angry", "fear", "disgust", "surprise", None]
)

#: A per-criterion selection score on the inclusive ``0..100`` scale.
selection_score_value = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

#: A 0–100% token-ratio value (used for code-switch ratio reasoning).
token_ratio_pct = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)


def emotion_features_strategy() -> st.SearchStrategy[EmotionFeatures]:
    """Strategy producing :class:`EmotionFeatures` with out-of-range V/A/D.

    Exercises the controller across failed/successful extraction, every label,
    the full confidence band, and V/A/D values outside ``[-1, 1]`` so clamping
    is covered.
    """
    return st.builds(
        make_emotion_features,
        label=emotion_label,
        confidence=confidence_value,
        valence=out_of_range_vad,
        arousal=out_of_range_vad,
        dominance=out_of_range_vad,
        extraction_ok=st.booleans(),
    )


@st.composite
def _scores_for_mode(draw: st.DrawFn, mode: str) -> dict[str, float]:
    """Draw a per-criterion score map biased toward ``mode``.

    ``"passing"`` draws every criterion at or above its minimum (guaranteed to
    pass); ``"random"`` draws each criterion freely in ``0..100``.
    """
    if mode == "passing":
        return {
            criterion: draw(
                st.floats(
                    min_value=float(SELECTION_MINIMUMS[criterion]),
                    max_value=100.0,
                    allow_nan=False,
                    allow_infinity=False,
                )
            )
            for criterion in SELECTION_CRITERIA
        }
    return {criterion: draw(selection_score_value) for criterion in SELECTION_CRITERIA}


@st.composite
def candidate_scores_strategy(draw: st.DrawFn, model_id: str = "model-x") -> CandidateScores:
    """Draw one :class:`CandidateScores` mixing passing and random score maps."""
    mode = draw(st.sampled_from(["passing", "random"]))
    return CandidateScores(
        model_id=model_id,
        revision="rev-1",
        scores=draw(_scores_for_mode(mode)),
    )


@st.composite
def candidate_list_strategy(draw: st.DrawFn) -> list[CandidateScores]:
    """Draw a list of distinctly-named candidates (zero, one, or many).

    The empty list (zero candidates) and single-candidate lists are reachable so
    the ``RETAIN_PHASE_1`` and single-passing paths are both exercised.
    """
    count = draw(st.integers(min_value=0, max_value=6))
    return [draw(candidate_scores_strategy(model_id=f"model-{i}")) for i in range(count)]


@st.composite
def gate_with_measurements_strategy(
    draw: st.DrawFn,
) -> tuple[Gate, dict[str, float]]:
    """Draw a launch gate plus a measured-values map, sometimes omitting metrics.

    A subset of the gate's metrics may be omitted from the measurements so the
    evaluator's fail-closed handling of missing gate metrics is exercised.
    """
    metric_names = draw(
        st.lists(
            st.sampled_from(
                ["latency_ms_p50", "hinglish_quality", "expressiveness", "vram_gb"]
            ),
            min_size=1,
            max_size=4,
            unique=True,
        )
    )
    criteria = [
        GateCriterion(
            metric_name=name,
            threshold=draw(st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False)),
            operator=draw(st.sampled_from(["<=", "<", ">=", ">", "=="])),
        )
        for name in metric_names
    ]
    gate = make_gate(id="GEN-GATE", kind="launch", exit_criteria=criteria)

    # Provide measurements for a (possibly empty) subset of the metrics so some
    # criteria fail-closed on a missing measured value.
    present = draw(st.lists(st.sampled_from(metric_names), unique=True, max_size=len(metric_names)))
    measured = {
        name: draw(st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False))
        for name in present
    }
    return gate, measured


@st.composite
def consent_record_strategy(draw: st.DrawFn) -> ConsentRecord:
    """Draw a :class:`ConsentRecord` that may be partial (some fields blank/zero).

    Each of the three fields is independently present or absent, so both fully
    valid and partial (invalid) consent records are produced.
    """
    speaker_id = draw(st.sampled_from(["speaker-001", "", "   "]))
    scope = draw(st.sampled_from(["voice-clone", "", "   "]))
    timestamp = draw(st.sampled_from([1_700_000_000.0, 0.0, -1.0]))
    return ConsentRecord(
        speaker_id=speaker_id,
        permitted_use_scope=scope,
        timestamp=timestamp,
    )


#: Compute-availability inputs covering valid, zero, negative, and invalid /
#: missing values, for exercising ``BudgetComputePlanner.select_scope``.
available_compute_strategy = st.one_of(
    st.floats(min_value=0.0, max_value=128.0, allow_nan=False, allow_infinity=False),
    st.sampled_from([0.0, -1.0, -40.0]),
    st.none(),
    st.sampled_from(["not-a-number", "16"]),
    st.dictionaries(
        keys=st.just("vram_gb"),
        values=st.floats(min_value=-10.0, max_value=80.0, allow_nan=False, allow_infinity=False),
        max_size=1,
    ),
)


# ---------------------------------------------------------------------------
# pytest fixtures (optional convenience over the builders)
# ---------------------------------------------------------------------------

if pytest is not None:

    @pytest.fixture
    def valid_roadmap() -> Roadmap:
        """A valid, canonical seven-phase roadmap."""
        return make_valid_roadmap()

    @pytest.fixture
    def launch_gate() -> Gate:
        """A canonical LEAN-demo launch gate."""
        return make_gate()

    @pytest.fixture
    def decision_gate() -> Gate:
        """The canonical ``G1`` LEAN→AMBITIOUS decision gate."""
        return make_decision_gate()

    @pytest.fixture
    def clean_registry() -> LicensingRegister:
        """A licensing register with no warnings and nothing prohibiting."""
        return make_clean_registry()

    @pytest.fixture
    def gate_evaluator() -> GateEvaluator:
        """A stateless gate evaluator."""
        return GateEvaluator()

    @pytest.fixture
    def selection_scorer() -> SelectionScorer:
        """A selection scorer using the canonical weights/minimums."""
        return SelectionScorer()

    @pytest.fixture
    def hinglish_engine() -> HinglishDataEngine:
        """A Hinglish data engine using the built-in default mapping."""
        return HinglishDataEngine()

    @pytest.fixture
    def emotion_controller() -> EmotionPersonaController:
        """An emotion/persona controller using the design's default thresholds."""
        return EmotionPersonaController()

    @pytest.fixture
    def budget_planner() -> BudgetComputePlanner:
        """A budget/compute planner seeded with the canonical phases."""
        return make_budget_planner()

    @pytest.fixture
    def regression_cases() -> dict:
        """The parsed ``regression_cases.json`` data file."""
        return load_regression_cases()


__all__ = [
    # data file
    "REGRESSION_CASES_PATH",
    "load_regression_cases",
    # builders
    "make_criterion",
    "make_phase",
    "make_valid_roadmap",
    "make_gate",
    "make_decision_gate",
    "make_passing_selection_scores",
    "make_failing_selection_scores",
    "make_candidate_scores",
    "make_mock_candidate",
    "make_emotion_features",
    "make_consent_record",
    "make_license_entry",
    "make_clean_registry",
    "make_budget_planner",
    # strategies
    "out_of_range_vad",
    "confidence_value",
    "emotion_label",
    "selection_score_value",
    "token_ratio_pct",
    "emotion_features_strategy",
    "candidate_scores_strategy",
    "candidate_list_strategy",
    "gate_with_measurements_strategy",
    "consent_record_strategy",
    "available_compute_strategy",
]
