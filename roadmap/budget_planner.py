"""Budget & Compute Planner for the speech-native voice roadmap.

This module implements the :class:`BudgetComputePlanner` described in the
design document's *Budget & Compute Planner* section and Requirement 9. It is a
pure, testable planning component — it executes no GPU work, it only reasons
about *stated* compute footprints and budget estimates.

Responsibilities (Requirement 9):

- **9.1** State, per phase, a compute footprint as a minimum GPU class plus a
  minimum VRAM (GB). Footprints are sourced directly from the :class:`Phase`
  fields ``compute_min_gpu_class`` and ``compute_min_vram_gb``.
- **9.2** State a LEAN budget range and a separate AMBITIOUS budget range, each
  as ``{lower, upper, currency}`` in a single stated currency (USD), validating
  ``lower <= upper``. Modeled by :class:`BudgetRange`.
- **9.3** Assert that the LEAN_Track is executable by at most five people
  without large-scale GPU training runs (multi-GPU / multi-node from-scratch
  training). Exposed via :attr:`BudgetComputePlanner.lean_max_team_size`,
  :attr:`BudgetComputePlanner.lean_excludes_large_scale_training`, and
  :meth:`BudgetComputePlanner.assert_lean_feasibility`.
- **9.4** Require an explicit AMBITIOUS justification (the AMBITIOUS budget range
  plus the per-phase compute footprint) *before* the AMBITIOUS_Track is entered
  at Decision_Gate ``G1``. See :meth:`BudgetComputePlanner.ambitious_justification`
  and :meth:`BudgetComputePlanner.require_ambitious_justification`.
- **9.5** ``select_scope(phase, available_compute)`` returns a reduced-scope
  alternative whose stated footprint does **not** exceed the compute confirmed
  available whenever availability is below the phase minimum, is zero, or is
  invalid/missing (``None`` / negative / non-numeric); otherwise it returns the
  full-scope plan for the phase. The returned footprint never exceeds the
  confirmed-available compute (the key invariant verified by Task 22.2).

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional, Union

from .models.phases import Phase

__all__ = [
    "DEFAULT_CURRENCY",
    "LEAN_MAX_TEAM_SIZE",
    "GPU_VRAM_LADDER",
    "DEFAULT_LEAN_BUDGET",
    "DEFAULT_AMBITIOUS_BUDGET",
    "BudgetRange",
    "ComputeFootprint",
    "ScopePlan",
    "AmbitiousJustification",
    "AmbitiousJustificationError",
    "BudgetComputePlanner",
]


#: The single stated currency the roadmap expresses every budget range in
#: (Requirement 9.2).
DEFAULT_CURRENCY = "USD"

#: The maximum LEAN_Track team size the roadmap asserts (Requirement 9.3).
LEAN_MAX_TEAM_SIZE = 5

#: An ordered ladder of representative GPU classes and their VRAM (GB). Used by
#: :meth:`BudgetComputePlanner.select_scope` to pick the largest *real* GPU
#: class that fits inside the confirmed-available compute when a reduced-scope
#: alternative is required. ``"CPU"`` (0 GB) is the no-GPU floor, guaranteeing a
#: fitting rung always exists for any non-negative availability.
GPU_VRAM_LADDER: tuple[tuple[str, float], ...] = (
    ("CPU", 0.0),
    ("T4-16GB", 16.0),
    ("L4-24GB", 24.0),
    ("A10G-24GB", 24.0),
    ("A100-40GB", 40.0),
    ("A100-80GB", 80.0),
    ("H100-80GB", 80.0),
)


# --- Budget range ---------------------------------------------------------


@dataclass
class BudgetRange:
    """A budget range expressed as ``{lower, upper, currency}`` (Requirement 9.2).

    Attributes:
        lower: The lower-bound estimate, in ``currency``. Must be ``>= 0``.
        upper: The upper-bound estimate, in ``currency``. Must be ``>= lower``.
        currency: The single stated currency code, e.g. ``"USD"``.

    Construction-time validation enforces non-negative bounds, ``lower <= upper``
    (Requirement 9.2), and a non-empty currency.
    """

    lower: float
    upper: float
    currency: str = DEFAULT_CURRENCY

    def __post_init__(self) -> None:
        for name, value in (("lower", self.lower), ("upper", self.upper)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric, got {type(value)!r}")
            if math.isnan(value) or math.isinf(value):
                raise ValueError(f"{name} must be a finite number, got {value!r}")
        if self.lower < 0:
            raise ValueError(f"lower must be >= 0, got {self.lower}")
        if self.upper < self.lower:
            raise ValueError(
                f"upper ({self.upper}) must be >= lower ({self.lower}) "
                "(Requirement 9.2)"
            )
        if not self.currency or not str(self.currency).strip():
            raise ValueError("currency must be a non-empty string")

    def as_dict(self) -> dict:
        """Return the ``{lower, upper, currency}`` structured form."""

        return {"lower": self.lower, "upper": self.upper, "currency": self.currency}


#: The roadmap's LEAN_Track budget range. LEAN is the low-cost, adopt-and-ship
#: path executable by a small team without large-scale training (Requirement 9.3).
DEFAULT_LEAN_BUDGET = BudgetRange(lower=5_000.0, upper=50_000.0, currency=DEFAULT_CURRENCY)

#: The roadmap's AMBITIOUS_Track budget range. AMBITIOUS funds custom codec /
#: tokenizer / alignment work and is materially more expensive than LEAN.
DEFAULT_AMBITIOUS_BUDGET = BudgetRange(
    lower=50_000.0, upper=500_000.0, currency=DEFAULT_CURRENCY
)


# --- Compute footprint ----------------------------------------------------


@dataclass
class ComputeFootprint:
    """A stated compute footprint: a minimum GPU class + minimum VRAM (GB).

    This mirrors the per-phase footprint sourced from :class:`Phase`
    (Requirement 9.1) and is also used to describe the reduced-scope footprint
    returned by :meth:`BudgetComputePlanner.select_scope` (Requirement 9.5).

    Attributes:
        gpu_class: The (minimum) GPU class, e.g. ``"L4-24GB"`` or ``"CPU"``.
        vram_gb: The (minimum) VRAM in gigabytes. Must be ``>= 0``.
    """

    gpu_class: str
    vram_gb: float

    def __post_init__(self) -> None:
        if not self.gpu_class or not str(self.gpu_class).strip():
            raise ValueError("gpu_class must be a non-empty string")
        if isinstance(self.vram_gb, bool) or not isinstance(self.vram_gb, (int, float)):
            raise TypeError(f"vram_gb must be numeric, got {type(self.vram_gb)!r}")
        if math.isnan(self.vram_gb) or math.isinf(self.vram_gb):
            raise ValueError(f"vram_gb must be finite, got {self.vram_gb!r}")
        if self.vram_gb < 0:
            raise ValueError(f"vram_gb must be >= 0, got {self.vram_gb}")

    def as_dict(self) -> dict:
        """Return the ``{gpu_class, vram_gb}`` structured form."""

        return {"gpu_class": self.gpu_class, "vram_gb": self.vram_gb}


# --- Scope plan -----------------------------------------------------------

ScopeKind = Literal["full", "reduced"]


@dataclass
class ScopePlan:
    """The result of :meth:`BudgetComputePlanner.select_scope`.

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
    """

    phase_id: str
    scope: ScopeKind
    footprint: ComputeFootprint
    confirmed_available_vram_gb: float
    rationale: str = ""

    @property
    def is_reduced(self) -> bool:
        """``True`` when this is a reduced-scope alternative."""

        return self.scope == "reduced"

    @property
    def footprint_within_available(self) -> bool:
        """``True`` iff the stated footprint does not exceed confirmed-available.

        This is the Requirement 9.5 invariant the planner guarantees for every
        returned plan.
        """

        return self.footprint.vram_gb <= self.confirmed_available_vram_gb


# --- AMBITIOUS justification ----------------------------------------------


class AmbitiousJustificationError(RuntimeError):
    """Raised when AMBITIOUS entry is attempted without a complete justification."""


@dataclass
class AmbitiousJustification:
    """An explicit justification required before AMBITIOUS entry at ``G1``.

    Per Requirement 9.4 the justification must include the AMBITIOUS budget
    range (Requirement 9.2) and the per-phase compute footprint (Requirement
    9.1) for the AMBITIOUS phases.

    Attributes:
        budget_range: The AMBITIOUS_Track budget range.
        phase_footprints: Mapping of AMBITIOUS phase id -> its compute footprint.
        approved: Whether the justification has been explicitly approved (maps to
            the ``G1`` exit criterion ``ambitious_budget_justification_approved``).
    """

    budget_range: BudgetRange
    phase_footprints: dict[str, ComputeFootprint] = field(default_factory=dict)
    approved: bool = False

    def is_complete(self) -> bool:
        """Return ``True`` iff the justification carries everything 9.4 requires."""

        return (
            isinstance(self.budget_range, BudgetRange)
            and bool(self.phase_footprints)
            and self.approved is True
        )


# --- Planner --------------------------------------------------------------


AvailableCompute = Union[int, float, "ComputeFootprint", dict, None]


class BudgetComputePlanner:
    """States per-phase compute footprints, budget ranges, and scope decisions.

    Footprints are sourced from the :class:`Phase` fields supplied at
    construction (Requirement 9.1). The planner is pure: it makes no network or
    GPU calls and only reasons about *stated* footprints and budget estimates.
    """

    #: Class-level mirror of the asserted maximum LEAN team size (Requirement 9.3).
    LEAN_MAX_TEAM_SIZE: int = LEAN_MAX_TEAM_SIZE

    def __init__(
        self,
        phases: Optional[Iterable[Phase]] = None,
        *,
        lean_budget: Optional[BudgetRange] = None,
        ambitious_budget: Optional[BudgetRange] = None,
    ) -> None:
        """Construct the planner.

        Args:
            phases: The roadmap phases whose footprints this planner reports.
                Each must be a :class:`Phase`; ids must be unique.
            lean_budget: The LEAN_Track budget range; defaults to
                :data:`DEFAULT_LEAN_BUDGET`.
            ambitious_budget: The AMBITIOUS_Track budget range; defaults to
                :data:`DEFAULT_AMBITIOUS_BUDGET`.

        Raises:
            TypeError: If any supplied phase is not a :class:`Phase`.
            ValueError: If phase ids are not unique, or the two budget ranges do
                not share a single stated currency (Requirement 9.2).
        """

        phase_list = list(phases) if phases is not None else []
        for phase in phase_list:
            if not isinstance(phase, Phase):
                raise TypeError(
                    f"phases must contain only Phase instances, got {type(phase)!r}"
                )
        ids = [p.id for p in phase_list]
        if len(ids) != len(set(ids)):
            raise ValueError("phase ids must be unique")

        self._phases: list[Phase] = phase_list
        self._phases_by_id: dict[str, Phase] = {p.id: p for p in phase_list}

        self.lean_budget: BudgetRange = lean_budget or DEFAULT_LEAN_BUDGET
        self.ambitious_budget: BudgetRange = ambitious_budget or DEFAULT_AMBITIOUS_BUDGET
        if self.lean_budget.currency != self.ambitious_budget.currency:
            raise ValueError(
                "LEAN and AMBITIOUS budgets must use a single stated currency "
                f"(Requirement 9.2); got {self.lean_budget.currency!r} and "
                f"{self.ambitious_budget.currency!r}"
            )

        # Requirement 9.3 claims, exposed as attributes.
        self.lean_max_team_size: int = LEAN_MAX_TEAM_SIZE
        self.lean_excludes_large_scale_training: bool = True

    # --- Phases / footprints (Requirement 9.1) ----------------------------

    @property
    def phases(self) -> list[Phase]:
        """The phases this planner reports footprints for."""

        return list(self._phases)

    @staticmethod
    def _footprint_of(phase: Phase) -> ComputeFootprint:
        """Source a :class:`ComputeFootprint` from a :class:`Phase`'s fields."""

        return ComputeFootprint(
            gpu_class=phase.compute_min_gpu_class,
            vram_gb=float(phase.compute_min_vram_gb),
        )

    def _resolve_phase(self, phase: Union[Phase, str]) -> Phase:
        """Resolve a :class:`Phase` instance or a phase id to a :class:`Phase`."""

        if isinstance(phase, Phase):
            return phase
        if isinstance(phase, str):
            try:
                return self._phases_by_id[phase]
            except KeyError as exc:
                raise KeyError(f"unknown phase id {phase!r}") from exc
        raise TypeError(f"phase must be a Phase or phase id str, got {type(phase)!r}")

    def phase_footprint(self, phase: Union[Phase, str]) -> ComputeFootprint:
        """Return the per-phase compute footprint (Requirement 9.1)."""

        return self._footprint_of(self._resolve_phase(phase))

    def phase_footprints(self) -> dict[str, ComputeFootprint]:
        """Return ``{phase_id: ComputeFootprint}`` for every known phase."""

        return {p.id: self._footprint_of(p) for p in self._phases}

    def ambitious_phase_footprints(self) -> dict[str, ComputeFootprint]:
        """Return the per-phase footprints for AMBITIOUS-track phases only."""

        return {
            p.id: self._footprint_of(p)
            for p in self._phases
            if p.track == "AMBITIOUS"
        }

    # --- LEAN feasibility claim (Requirement 9.3) -------------------------

    @property
    def lean_no_large_scale_training_claim(self) -> dict:
        """The structured LEAN feasibility claim (Requirement 9.3).

        Returns a structured statement that the LEAN_Track is executable by at
        most ``lean_max_team_size`` people *without* large-scale GPU training
        runs (multi-GPU / multi-node from-scratch model training).
        """

        return {
            "max_team_size": self.lean_max_team_size,
            "excludes_large_scale_training": self.lean_excludes_large_scale_training,
            "large_scale_training_definition": (
                "multi-GPU or multi-node from-scratch model training"
            ),
        }

    def assert_lean_feasibility(self) -> None:
        """Assert the Requirement 9.3 LEAN claim holds.

        Raises:
            AssertionError: If the asserted team size exceeds five or the
                no-large-scale-training claim is not held.
        """

        assert self.lean_max_team_size <= LEAN_MAX_TEAM_SIZE, (
            "LEAN_Track must be executable by at most five people "
            "(Requirement 9.3)"
        )
        assert self.lean_excludes_large_scale_training is True, (
            "LEAN_Track must not require large-scale GPU training runs "
            "(Requirement 9.3)"
        )

    # --- AMBITIOUS justification (Requirement 9.4) ------------------------

    def ambitious_justification(self, *, approved: bool = False) -> AmbitiousJustification:
        """Build the explicit AMBITIOUS justification (Requirement 9.4).

        The justification bundles the AMBITIOUS budget range (Requirement 9.2)
        and the per-phase compute footprints for the AMBITIOUS phases
        (Requirement 9.1).

        Args:
            approved: Whether the justification is explicitly approved. The
                AMBITIOUS_Track may only be entered at ``G1`` once this is
                ``True`` (mapped to the ``G1`` exit criterion).

        Returns:
            The assembled :class:`AmbitiousJustification`.
        """

        return AmbitiousJustification(
            budget_range=self.ambitious_budget,
            phase_footprints=self.ambitious_phase_footprints(),
            approved=approved,
        )

    def require_ambitious_justification(
        self, justification: Optional[AmbitiousJustification]
    ) -> AmbitiousJustification:
        """Block AMBITIOUS entry unless an explicit justification is present.

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
        """

        if justification is None:
            raise AmbitiousJustificationError(
                "AMBITIOUS_Track requires an explicit justification (AMBITIOUS "
                "budget range + per-phase compute footprint) before entry at G1 "
                "(Requirement 9.4); none was provided."
            )
        if not isinstance(justification.budget_range, BudgetRange):
            raise AmbitiousJustificationError(
                "AMBITIOUS justification must include the AMBITIOUS budget range "
                "(Requirement 9.4/9.2)."
            )
        if not justification.phase_footprints:
            raise AmbitiousJustificationError(
                "AMBITIOUS justification must include the per-phase compute "
                "footprint (Requirement 9.4/9.1)."
            )
        if justification.approved is not True:
            raise AmbitiousJustificationError(
                "AMBITIOUS justification must be explicitly approved before "
                "entry at G1 (Requirement 9.4)."
            )
        return justification

    def can_enter_ambitious(
        self, justification: Optional[AmbitiousJustification]
    ) -> bool:
        """Return ``True`` iff a complete, approved justification allows entry."""

        return justification is not None and justification.is_complete()

    # --- Scope selection (Requirement 9.5) --------------------------------

    @staticmethod
    def _confirm_available_vram(available_compute: AvailableCompute) -> float:
        """Resolve an availability input to a confirmed, non-negative VRAM (GB).

        Invalid or missing data — ``None``, negative numbers, ``NaN`` / ``inf``,
        booleans, strings, and other non-numeric values — all resolve to
        ``0.0`` (i.e. *no* compute can be confirmed), per Requirement 9.5.

        Accepts a plain VRAM number, a :class:`ComputeFootprint`, or a mapping
        carrying a ``vram_gb`` key.
        """

        if isinstance(available_compute, ComputeFootprint):
            value: AvailableCompute = available_compute.vram_gb
        elif isinstance(available_compute, dict):
            value = available_compute.get("vram_gb")
        else:
            value = available_compute

        # Booleans are not a valid VRAM measurement.
        if isinstance(value, bool):
            return 0.0
        if not isinstance(value, (int, float)):
            return 0.0
        if math.isnan(value) or math.isinf(value):
            return 0.0
        if value <= 0:
            return 0.0
        return float(value)

    @staticmethod
    def _best_fit_footprint(available_vram_gb: float) -> ComputeFootprint:
        """Return the largest GPU-ladder rung whose VRAM fits in ``available``.

        Guarantees the returned ``vram_gb`` never exceeds ``available_vram_gb``;
        falls back to the ``"CPU"`` (0 GB) rung when nothing else fits.
        """

        best = ComputeFootprint(gpu_class="CPU", vram_gb=0.0)
        for gpu_class, vram in GPU_VRAM_LADDER:
            if vram <= available_vram_gb and vram >= best.vram_gb:
                best = ComputeFootprint(gpu_class=gpu_class, vram_gb=vram)
        return best

    def select_scope(
        self, phase: Union[Phase, str], available_compute: AvailableCompute
    ) -> ScopePlan:
        """Select a full- or reduced-scope plan for ``phase`` (Requirement 9.5).

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
        """

        resolved = self._resolve_phase(phase)
        full_footprint = self._footprint_of(resolved)
        confirmed = self._confirm_available_vram(available_compute)
        phase_min = full_footprint.vram_gb

        # Zero / invalid / missing availability, or availability below the phase
        # minimum -> reduced scope capped at the confirmed-available compute.
        if confirmed <= 0.0 or confirmed < phase_min:
            reduced = self._best_fit_footprint(confirmed)
            if confirmed <= 0.0:
                rationale = (
                    "No compute could be confirmed available (zero, invalid, or "
                    "missing); falling back to a no-GPU reduced-scope footprint."
                )
            else:
                rationale = (
                    f"Confirmed-available VRAM ({confirmed:g} GB) is below the "
                    f"phase minimum ({phase_min:g} GB); using a reduced-scope "
                    f"footprint that fits within the available compute."
                )
            return ScopePlan(
                phase_id=resolved.id,
                scope="reduced",
                footprint=reduced,
                confirmed_available_vram_gb=confirmed,
                rationale=rationale,
            )

        # Confirmed-available compute meets or exceeds the phase minimum.
        return ScopePlan(
            phase_id=resolved.id,
            scope="full",
            footprint=full_footprint,
            confirmed_available_vram_gb=confirmed,
            rationale=(
                f"Confirmed-available VRAM ({confirmed:g} GB) meets or exceeds the "
                f"phase minimum ({phase_min:g} GB); running the full-scope plan."
            ),
        )
