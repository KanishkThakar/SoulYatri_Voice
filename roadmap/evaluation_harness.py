"""Fully mocked Evaluation Harness for Candidate_Model selection.

This module produces **comparable** evaluation records across all
Candidate_Models. "Comparable" means the *same metric key set*, the *same
bounded input sample*, and the *same scoring scale* are applied to every
candidate, exactly as the design's *Evaluation Harness* component specifies
(Requirements 4.1, 4.2, 4.3).

It is **fully mocked** and is intentionally out of scope for any real model
execution (Requirement 4.6, 12.4, 12.5):

- It imports **no** GPU / model-training framework.
- It performs **no** GPU placement and runs **no** training/inference pass
  against real weights.
- Every metric score is *derived deterministically* from a candidate's mocked
  measurement seeds and identity, over a small in-memory probe sample bounded
  by the documented :data:`MAX_ITEMS` constant.

Determinism is a property of the derivation itself: a candidate's record is a
pure function of ``(model_id, revision, seeds, sample_items)``. Re-running the
harness on the same mocked inputs therefore reproduces identical scores, which
is what the reproducibility work (Task 12) builds on.

**Per-candidate exclusion (Requirements 4.5, 11.4).** A candidate that *cannot*
be evaluated is recorded as *excluded* rather than aborting the whole run. The
per-candidate :meth:`EvaluationHarness.evaluate` method detects three documented
exclusion conditions, in this fixed precedence order:

1. ``missing_weights`` — the candidate declares ``weights_available=False`` (its
   weights are unavailable, so it cannot be loaded at all).
2. ``license`` — the candidate's ``license_compat`` is ``"prohibited"`` (a
   prohibiting license means the model cannot be adopted / evaluated for use).
3. ``hardware`` — the candidate's hardware ``vram_gb`` is below the documented
   :data:`REQUIRED_MIN_VRAM_GB` minimum (it cannot be hosted for evaluation).

An excluded candidate yields a :class:`HarnessRun` with ``excluded=True``, an
``exclusion_category`` from :data:`EXCLUSION_CATEGORIES`, and a descriptive
``exclusion_reason``. Its ``metric_scores`` is the documented sentinel **empty
dict** ``{}`` — no measurement was performed, so it carries no metric scores.
The identical-metric-key-set / identical-scale guarantee (Property 4) is therefore
asserted only for **non-excluded** records; excluded records instead carry the
exclusion category + reason (Property 5). The candidate's ``license_compat`` and
``hardware`` are still recorded on an excluded run, since both are known without
any measurement. :meth:`EvaluationHarness.evaluate_all` continues past every
excluded candidate and still evaluates the remaining ones without aborting
(Requirement 4.5).

See the "Components and Interfaces → Evaluation Harness" and "Data Models"
sections of ``design.md`` for the authoritative interface. Requirements:
4.1, 4.2, 4.3, 4.5, 4.6, 11.4.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from statistics import median
from typing import Literal, Sequence

from roadmap.models.runtime import HarnessRun

# ---------------------------------------------------------------------------
# Bounds and scales (identical for every candidate)
# ---------------------------------------------------------------------------

#: Documented maximum item count that bounds the small-sample mocked inputs.
#: The harness never probes more than this many in-memory items per candidate,
#: so a run is cost-bounded and requires no GPU/model-training run
#: (Requirement 4.6).
MAX_ITEMS: int = 32

#: Default size of the small in-memory probe sample used per candidate. Must be
#: in the inclusive range ``1..MAX_ITEMS``.
DEFAULT_SAMPLE_ITEMS: int = 8

# The identical metric key set applied to every candidate (Requirements 4.1,
# 4.2). Authored as module constants so callers and tests reference the same
# canonical keys the records are built with.
LATENCY_KEY: str = "latency_ms_p50"
CODESWITCH_KEY: str = "codeswitch_quality"
EXPRESSIVENESS_KEY: str = "expressiveness"

#: The canonical, ordered metric key set every :class:`HarnessRun` carries.
METRIC_KEYS: tuple[str, ...] = (LATENCY_KEY, CODESWITCH_KEY, EXPRESSIVENESS_KEY)

# Identical scoring scales for every candidate (Requirement 4.1).
#: First-response latency is simulated within this fixed plausible band, in
#: milliseconds; the recorded value is the 50th-percentile (median) over the
#: probe sample (Requirement 4.2).
LATENCY_MS_MIN: float = 120.0
LATENCY_MS_MAX: float = 600.0

#: Hindi/Hinglish code-switch quality is scored on a fixed ``0..100`` scale.
QUALITY_SCALE_MIN: float = 0.0
QUALITY_SCALE_MAX: float = 100.0

#: Emotional expressiveness is scored on a fixed ``0..100`` numeric scale.
EXPRESSIVENESS_SCALE_MIN: float = 0.0
EXPRESSIVENESS_SCALE_MAX: float = 100.0

#: The categorical license-compatibility values a candidate may carry, recorded
#: verbatim on the run (Requirement 4.2).
LicenseCompat = Literal["compatible", "restricted", "prohibited"]
LICENSE_COMPAT_VALUES: tuple[str, ...] = ("compatible", "restricted", "prohibited")

# Default hardware descriptor used when a candidate omits one. Both keys are
# always present on the recorded hardware (Requirement 4.3).
_DEFAULT_GPU_CLASS: str = "L4"
_DEFAULT_VRAM_GB: float = 24.0

# ---------------------------------------------------------------------------
# Exclusion conditions (Requirements 4.5, 11.4)
# ---------------------------------------------------------------------------

#: Documented minimum hardware VRAM (in GB) required to host a candidate for a
#: (mocked) evaluation. A candidate whose ``hardware["vram_gb"]`` is below this
#: floor cannot be evaluated and is recorded with the ``"hardware"`` exclusion
#: category rather than aborting the run.
REQUIRED_MIN_VRAM_GB: float = 8.0

#: The exclusion categories the harness may record on an excluded run. These
#: mirror the design's enumerated conditions: missing weights, a prohibiting
#: license, or insufficient hardware (Requirement 4.5).
EXCLUSION_MISSING_WEIGHTS: str = "missing_weights"
EXCLUSION_LICENSE: str = "license"
EXCLUSION_HARDWARE: str = "hardware"
EXCLUSION_CATEGORIES: tuple[str, ...] = (
    EXCLUSION_MISSING_WEIGHTS,
    EXCLUSION_LICENSE,
    EXCLUSION_HARDWARE,
)

# ---------------------------------------------------------------------------
# Reproducibility tolerances (Requirement 4.4)
# ---------------------------------------------------------------------------

#: Minimum number of re-runs required to assess reproducibility. Requirement
#: 4.4 mandates re-running the harness "at least three times" on the same
#: candidate and hardware, so :meth:`EvaluationHarness.reproduce` rejects any
#: ``runs`` below this floor.
MIN_REPRODUCIBILITY_RUNS: int = 3

# The two tolerance *kinds* a per-metric rule may use (Requirement 4.4 allows a
# tolerance "expressed as an absolute value or a percentage").
#: A *relative* tolerance: each run's value may differ from the reference by at
#: most ``amount`` percent of the reference value.
TOLERANCE_KIND_RELATIVE_PCT: str = "relative_pct"
#: An *absolute* tolerance: each run's value may differ from the reference by at
#: most ``amount`` points, on the metric's own scale.
TOLERANCE_KIND_ABSOLUTE_POINTS: str = "absolute_points"

#: First-response latency reproducibility tolerance: ±10% (relative). Re-runs
#: whose latency stays within ±10% of the reference run are reproducible.
LATENCY_TOLERANCE_PCT: float = 10.0
#: Code-switch quality reproducibility tolerance: ±2 points (absolute) on the
#: ``0..100`` quality scale.
QUALITY_TOLERANCE_POINTS: float = 2.0
#: Expressiveness reproducibility tolerance: ±2 points (absolute) on the
#: ``0..100`` expressiveness scale.
EXPRESSIVENESS_TOLERANCE_POINTS: float = 2.0

#: The authoritative per-metric tolerance rule set, keyed by metric. Each value
#: is ``(tolerance_kind, amount)``. ``within_tolerance`` and
#: :meth:`EvaluationHarness.reproduce` both consult this table so the documented
#: tolerances live in exactly one place (Requirement 4.4):
#:
#: * ``latency_ms_p50`` — relative, ±10%.
#: * ``codeswitch_quality`` — absolute, ±2 points.
#: * ``expressiveness`` — absolute, ±2 points.
METRIC_TOLERANCES: dict[str, tuple[str, float]] = {
    LATENCY_KEY: (TOLERANCE_KIND_RELATIVE_PCT, LATENCY_TOLERANCE_PCT),
    CODESWITCH_KEY: (TOLERANCE_KIND_ABSOLUTE_POINTS, QUALITY_TOLERANCE_POINTS),
    EXPRESSIVENESS_KEY: (
        TOLERANCE_KIND_ABSOLUTE_POINTS,
        EXPRESSIVENESS_TOLERANCE_POINTS,
    ),
}

__all__ = [
    "MAX_ITEMS",
    "DEFAULT_SAMPLE_ITEMS",
    "METRIC_KEYS",
    "LATENCY_KEY",
    "CODESWITCH_KEY",
    "EXPRESSIVENESS_KEY",
    "LATENCY_MS_MIN",
    "LATENCY_MS_MAX",
    "QUALITY_SCALE_MIN",
    "QUALITY_SCALE_MAX",
    "EXPRESSIVENESS_SCALE_MIN",
    "EXPRESSIVENESS_SCALE_MAX",
    "LicenseCompat",
    "LICENSE_COMPAT_VALUES",
    "REQUIRED_MIN_VRAM_GB",
    "EXCLUSION_MISSING_WEIGHTS",
    "EXCLUSION_LICENSE",
    "EXCLUSION_HARDWARE",
    "EXCLUSION_CATEGORIES",
    "MIN_REPRODUCIBILITY_RUNS",
    "TOLERANCE_KIND_RELATIVE_PCT",
    "TOLERANCE_KIND_ABSOLUTE_POINTS",
    "LATENCY_TOLERANCE_PCT",
    "QUALITY_TOLERANCE_POINTS",
    "EXPRESSIVENESS_TOLERANCE_POINTS",
    "METRIC_TOLERANCES",
    "within_tolerance",
    "MetricReproducibility",
    "ReproducibilityReport",
    "MockCandidate",
    "EvaluationHarness",
]


def within_tolerance(metric_key: str, values: Sequence[float]) -> bool:
    """Return whether ``values`` for ``metric_key`` agree within its tolerance.

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
    """
    if metric_key not in METRIC_TOLERANCES:
        raise KeyError(
            f"no documented tolerance for metric {metric_key!r}; "
            f"known metrics: {tuple(METRIC_TOLERANCES)}"
        )

    if len(values) <= 1:
        return True

    kind, amount = METRIC_TOLERANCES[metric_key]
    reference = float(values[0])

    if kind == TOLERANCE_KIND_RELATIVE_PCT:
        # Allowed absolute deviation is ``amount`` percent of the reference's
        # magnitude. A zero reference collapses to an exact-match requirement,
        # which is the strictest correct interpretation of a relative band.
        allowed = abs(reference) * (amount / 100.0)
    elif kind == TOLERANCE_KIND_ABSOLUTE_POINTS:
        allowed = amount
    else:  # pragma: no cover - guarded by METRIC_TOLERANCES authorship
        raise ValueError(f"unknown tolerance kind {kind!r} for {metric_key!r}")

    return all(abs(float(value) - reference) <= allowed for value in values)


@dataclass(frozen=True)
class MetricReproducibility:
    """Per-metric reproducibility outcome across a candidate's re-runs.

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
    """

    metric_key: str
    values: tuple[float, ...]
    tolerance_kind: str
    tolerance_amount: float
    within_tolerance: bool


@dataclass(frozen=True)
class ReproducibilityReport:
    """The result of re-running one candidate to check reproducibility.

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
    """

    model_id: str
    revision: str
    runs: int
    metrics: dict[str, MetricReproducibility]
    reproducible: bool
    excluded: bool = False
    exclusion_category: str | None = None


@dataclass
class MockCandidate:
    """A mocked Candidate_Model input for the evaluation harness.

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
    """

    model_id: str
    revision: str
    seeds: dict[str, float] = field(default_factory=dict)
    license_compat: LicenseCompat = "compatible"
    hardware: dict = field(
        default_factory=lambda: {
            "gpu_class": _DEFAULT_GPU_CLASS,
            "vram_gb": _DEFAULT_VRAM_GB,
        }
    )
    weights_available: bool = True

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        if not self.revision or not self.revision.strip():
            raise ValueError("revision must be a non-empty string")
        if not isinstance(self.seeds, dict):
            raise TypeError("seeds must be a dict of metric_key -> numeric seed")
        for key, value in self.seeds.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("seed keys must be non-empty strings")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(
                    f"seed for {key!r} must be numeric, got {type(value)!r}"
                )
        if self.license_compat not in LICENSE_COMPAT_VALUES:
            raise ValueError(
                f"license_compat must be one of {LICENSE_COMPAT_VALUES}, "
                f"got {self.license_compat!r}"
            )
        if not isinstance(self.hardware, dict):
            raise TypeError("hardware must be a dict with gpu_class and vram_gb")
        if not isinstance(self.weights_available, bool):
            raise TypeError("weights_available must be a bool")


class EvaluationHarness:
    """Produces comparable, fully mocked :class:`HarnessRun` records.

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
    """

    def __init__(self, sample_items: int = DEFAULT_SAMPLE_ITEMS) -> None:
        if isinstance(sample_items, bool) or not isinstance(sample_items, int):
            raise TypeError(
                f"sample_items must be an int, got {type(sample_items)!r}"
            )
        if not 1 <= sample_items <= MAX_ITEMS:
            raise ValueError(
                f"sample_items must be in 1..{MAX_ITEMS}, got {sample_items}"
            )
        self.sample_items = sample_items

    # -- public API --------------------------------------------------------

    def evaluate(self, candidate: MockCandidate) -> HarnessRun:
        """Evaluate a single candidate and return its comparable record.

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
        """
        if not isinstance(candidate, MockCandidate):
            raise TypeError("candidate must be a MockCandidate")

        exclusion = self._detect_exclusion(candidate)
        if exclusion is not None:
            category, reason = exclusion
            return HarnessRun(
                model_id=candidate.model_id,
                revision=candidate.revision,
                metric_scores={},  # documented sentinel: no measurement performed
                license_compat=candidate.license_compat,
                hardware=self._normalized_hardware(candidate.hardware),
                excluded=True,
                exclusion_category=category,
                exclusion_reason=reason,
            )

        metric_scores = {
            LATENCY_KEY: self._latency_p50(candidate),
            CODESWITCH_KEY: self._scaled_metric(
                candidate, CODESWITCH_KEY, QUALITY_SCALE_MIN, QUALITY_SCALE_MAX
            ),
            EXPRESSIVENESS_KEY: self._scaled_metric(
                candidate,
                EXPRESSIVENESS_KEY,
                EXPRESSIVENESS_SCALE_MIN,
                EXPRESSIVENESS_SCALE_MAX,
            ),
        }

        return HarnessRun(
            model_id=candidate.model_id,
            revision=candidate.revision,
            metric_scores=metric_scores,
            license_compat=candidate.license_compat,
            hardware=self._normalized_hardware(candidate.hardware),
        )

    def evaluate_all(
        self, candidates: Sequence[MockCandidate]
    ) -> list[HarnessRun]:
        """Evaluate every candidate, returning one record per candidate.

        Non-excluded records share the identical metric key set and scoring
        scale, so they are directly comparable across candidates (Requirement
        4.1). A candidate that cannot be evaluated is recorded as excluded and
        the loop continues to the remaining candidates without aborting
        (Requirements 4.5, 11.4), so the returned list always has exactly one
        record per input candidate, preserving order.
        """
        return [self.evaluate(candidate) for candidate in candidates]

    def reproduce(
        self, candidate: MockCandidate, runs: int = MIN_REPRODUCIBILITY_RUNS
    ) -> ReproducibilityReport:
        """Re-run a candidate ``runs`` times and check per-metric reproducibility.

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
        """
        if not isinstance(candidate, MockCandidate):
            raise TypeError("candidate must be a MockCandidate")
        if isinstance(runs, bool) or not isinstance(runs, int):
            raise TypeError(f"runs must be an int, got {type(runs)!r}")
        if runs < MIN_REPRODUCIBILITY_RUNS:
            raise ValueError(
                f"runs must be >= {MIN_REPRODUCIBILITY_RUNS} "
                f"(Requirement 4.4 requires at least three re-runs), got {runs}"
            )

        records = [self.evaluate(candidate) for _ in range(runs)]
        first = records[0]

        # An excluded candidate has empty metric_scores on every run. Exclusion
        # is deterministic, so the report is trivially reproducible with no
        # measured metrics (Requirement 4.4 + the exclusion contract).
        if first.excluded:
            return ReproducibilityReport(
                model_id=candidate.model_id,
                revision=candidate.revision,
                runs=runs,
                metrics={},
                reproducible=True,
                excluded=True,
                exclusion_category=first.exclusion_category,
            )

        metrics: dict[str, MetricReproducibility] = {}
        for metric_key in METRIC_KEYS:
            values = tuple(
                float(record.metric_scores[metric_key]) for record in records
            )
            kind, amount = METRIC_TOLERANCES[metric_key]
            metrics[metric_key] = MetricReproducibility(
                metric_key=metric_key,
                values=values,
                tolerance_kind=kind,
                tolerance_amount=amount,
                within_tolerance=within_tolerance(metric_key, values),
            )

        reproducible = all(m.within_tolerance for m in metrics.values())
        return ReproducibilityReport(
            model_id=candidate.model_id,
            revision=candidate.revision,
            runs=runs,
            metrics=metrics,
            reproducible=reproducible,
        )

    @staticmethod
    def _detect_exclusion(
        candidate: MockCandidate,
    ) -> tuple[str, str] | None:
        """Return ``(category, reason)`` if the candidate cannot be evaluated.

        Conditions are checked in a fixed precedence order so the recorded
        category is deterministic when more than one applies:

        1. ``missing_weights`` — ``weights_available is False``.
        2. ``license`` — ``license_compat == "prohibited"``.
        3. ``hardware`` — ``hardware["vram_gb"]`` below
           :data:`REQUIRED_MIN_VRAM_GB`.

        Returns ``None`` when the candidate is evaluable.
        """
        if candidate.weights_available is False:
            return (
                EXCLUSION_MISSING_WEIGHTS,
                f"weights unavailable for {candidate.model_id}@{candidate.revision}: "
                "model cannot be loaded for evaluation",
            )

        if candidate.license_compat == "prohibited":
            return (
                EXCLUSION_LICENSE,
                f"license for {candidate.model_id} is prohibited: the model "
                "cannot be adopted or evaluated for the intended use",
            )

        vram_gb = candidate.hardware.get("vram_gb", _DEFAULT_VRAM_GB)
        try:
            vram_value = float(vram_gb)
        except (TypeError, ValueError):
            vram_value = -1.0  # uninterpretable VRAM is treated as below floor
        if vram_value < REQUIRED_MIN_VRAM_GB:
            return (
                EXCLUSION_HARDWARE,
                f"hardware vram_gb={vram_gb!r} for {candidate.model_id} is below "
                f"the required minimum of {REQUIRED_MIN_VRAM_GB} GB to host the "
                "model for evaluation",
            )

        return None

    # -- deterministic mocked derivation -----------------------------------

    def _latency_p50(self, candidate: MockCandidate) -> float:
        """Median (p50) first-response latency in ms over the probe sample."""
        samples = [
            LATENCY_MS_MIN
            + self._unit(candidate, LATENCY_KEY, index)
            * (LATENCY_MS_MAX - LATENCY_MS_MIN)
            for index in range(self.sample_items)
        ]
        return round(float(median(samples)), 3)

    def _scaled_metric(
        self,
        candidate: MockCandidate,
        metric_key: str,
        scale_min: float,
        scale_max: float,
    ) -> float:
        """Mean derived score over the probe sample, on the metric's scale."""
        units = [
            self._unit(candidate, metric_key, index)
            for index in range(self.sample_items)
        ]
        mean_unit = sum(units) / len(units)
        value = scale_min + mean_unit * (scale_max - scale_min)
        return round(float(value), 3)

    def _unit(
        self, candidate: MockCandidate, metric_key: str, item_index: int
    ) -> float:
        """A stable pseudo-value in ``[0.0, 1.0]`` for one (candidate, metric, item).

        Derived from a SHA-256 digest of the candidate identity, the metric's
        mocked seed, and the probe item index, so it is fully deterministic and
        free of any GPU/model execution (Requirement 4.6).
        """
        seed = candidate.seeds.get(metric_key, 0.0)
        key = (
            f"{candidate.model_id}@{candidate.revision}"
            f"|metric={metric_key}|seed={float(seed)!r}|item={item_index}"
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    @staticmethod
    def _normalized_hardware(hardware: dict) -> dict:
        """Return a hardware dict guaranteeing ``gpu_class`` and ``vram_gb`` keys."""
        gpu_class = hardware.get("gpu_class", _DEFAULT_GPU_CLASS)
        vram_gb = hardware.get("vram_gb", _DEFAULT_VRAM_GB)
        return {"gpu_class": str(gpu_class), "vram_gb": float(vram_gb)}
