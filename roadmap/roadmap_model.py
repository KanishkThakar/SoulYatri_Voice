"""The ``Roadmap`` aggregate and its phase-structure invariant.

This module defines the top-level planning aggregate for the speech-native
voice roadmap. The :class:`Roadmap` holds the ordered phase list, the track
labels, the gate definitions, the conflict register, and the explicit scope
statements, and it enforces the *phase-structure invariant* on construction.

The phase-structure invariant (design *Property 1*) requires, for any valid
roadmap, that:

- phase ordinals are unique and contiguous starting at 1 (Requirement 1.1),
- phase identifiers are unique (Requirement 1.1),
- the first phase (ordinal 1) is the existing Phase_1_Pipeline, identified by
  ``"P1-baseline"`` (Requirement 1.1),
- the final phase (highest ordinal) is a speech-native platform, i.e.
  ``is_speech_native`` is ``True`` (Requirement 1.1),
- every phase carries at least one implementation-guide section heading
  (Requirement 1.6) and a compute footprint expressed as a minimum GPU class
  and minimum VRAM in GB (Requirement 9.1).

The individual :class:`~roadmap.models.phases.Phase` already validates the
per-phase guide-section and compute-footprint requirements in its own
``__post_init__``; the :class:`Roadmap` re-affirms them at the aggregate level
so a malformed phase can never enter a roadmap even if it were constructed
through a path that bypassed ``Phase`` validation.

Validates: Requirements 1.1, 1.6, 9.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models.phases import TRACK_VALUES, Gate, Phase

# --- The canonical identifier of the first (baseline) phase ---------------

#: The id the first phase (ordinal 1) must carry. This is the existing
#: Phase_1_Pipeline — the classic Silero VAD → faster-whisper → Ollama LLM →
#: edge-tts cascade — which the roadmap begins from (Requirement 1.1).
FIRST_PHASE_ID = "P1-baseline"


@dataclass
class ConflictEntry:
    """One row of the conflict register (roadmap decision vs. a strategy PDF).

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
    """

    topic: str
    superseding_decision: str
    rationale: str
    conflicting_document: str = ""

    def __post_init__(self) -> None:
        if not self.topic or not self.topic.strip():
            raise ValueError("topic must be a non-empty string")
        if not self.superseding_decision or not self.superseding_decision.strip():
            raise ValueError("superseding_decision must be a non-empty string")
        if not self.rationale or not self.rationale.strip():
            raise ValueError("rationale must be a non-empty string")


@dataclass
class ScopeStatements:
    """The explicit scope statements the roadmap carries (Requirement 12).

    These are the authoritative-plan declarations the roadmap must surface: it
    is the authoritative build plan and supersedes the strategy PDFs, it
    references the ``ai-training-docs`` spec as the documentation workstream, it
    excludes from-scratch foundation-model pretraining and the execution of
    GPU-based training runs, and its sole deliverable is a planning artifact.

    Each statement is a non-empty string so the aggregate can never be
    constructed with a blank scope declaration. :meth:`default` supplies the
    canonical statements drawn from the design's *Relationship to existing
    artifacts* and *Scope Summary* sections.
    """

    authoritative_supersedes_pdfs: str
    references_ai_training_docs: str
    excludes_from_scratch_pretraining: str
    excludes_gpu_training_execution: str
    planning_artifact_only: str

    def __post_init__(self) -> None:
        for name in (
            "authoritative_supersedes_pdfs",
            "references_ai_training_docs",
            "excludes_from_scratch_pretraining",
            "excludes_gpu_training_execution",
            "planning_artifact_only",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

    @classmethod
    def default(cls) -> "ScopeStatements":
        """Return the canonical scope statements for the roadmap."""

        return cls(
            authoritative_supersedes_pdfs=(
                "This roadmap is the authoritative build plan for all "
                "build-sequencing decisions and supersedes every strategy PDF "
                "in the docs/ directory."
            ),
            references_ai_training_docs=(
                "This roadmap references the .kiro/specs/ai-training-docs/ spec "
                "as the documentation/knowledge-base workstream and does not "
                "restate its documentation-generation requirements."
            ),
            excludes_from_scratch_pretraining=(
                "From-scratch foundation-model pretraining is out of scope for "
                "this roadmap."
            ),
            excludes_gpu_training_execution=(
                "Executing GPU-based model-training runs is out of scope for "
                "this spec; training execution is downstream work the roadmap "
                "plans but does not perform."
            ),
            planning_artifact_only=(
                "The sole deliverable of this spec is a planning artifact, not "
                "executable model weights or a training run."
            ),
        )


def _default_track_labels() -> dict[str, str]:
    """Return the default track labels: LEAN primary, AMBITIOUS optional.

    Requirement 1.2 labels the LEAN_Track "primary" and the AMBITIOUS_Track
    "optional".
    """

    return {"LEAN": "primary", "AMBITIOUS": "optional"}


@dataclass
class Roadmap:
    """The top-level roadmap planning aggregate.

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
    """

    phases: list[Phase]
    track_labels: dict[str, str] = field(default_factory=_default_track_labels)
    gates: list[Gate] = field(default_factory=list)
    conflicts: list[ConflictEntry] = field(default_factory=list)
    scope_statements: ScopeStatements = field(default_factory=ScopeStatements.default)

    def __post_init__(self) -> None:
        self._validate_collection_types()
        self._validate_track_labels()
        self._validate_phase_structure()

    # --- validation helpers ------------------------------------------------

    def _validate_collection_types(self) -> None:
        if not isinstance(self.phases, list):
            raise TypeError("phases must be a list of Phase")
        if any(not isinstance(p, Phase) for p in self.phases):
            raise TypeError("phases must contain only Phase items")
        if any(not isinstance(g, Gate) for g in self.gates):
            raise TypeError("gates must contain only Gate items")
        if any(not isinstance(c, ConflictEntry) for c in self.conflicts):
            raise TypeError("conflicts must contain only ConflictEntry items")
        if not isinstance(self.scope_statements, ScopeStatements):
            raise TypeError("scope_statements must be a ScopeStatements instance")

    def _validate_track_labels(self) -> None:
        if not isinstance(self.track_labels, dict):
            raise TypeError("track_labels must be a dict of track -> label")
        for track, label in self.track_labels.items():
            if track not in TRACK_VALUES:
                raise ValueError(
                    f"track_labels keys must be one of {TRACK_VALUES}, "
                    f"got {track!r}"
                )
            if not isinstance(label, str) or not label.strip():
                raise ValueError(
                    f"track_labels[{track!r}] must be a non-empty string label"
                )

    def _validate_phase_structure(self) -> None:
        """Enforce the phase-structure invariant (design Property 1)."""

        n = len(self.phases)
        # Requirement 1.1: an ordered sequence of at least two phases (the
        # existing Phase_1_Pipeline plus a final speech-native platform).
        if n < 2:
            raise ValueError(
                "a roadmap must define at least two phases "
                "(the Phase_1_Pipeline and a final speech-native platform) "
                "(Requirement 1.1)"
            )

        ordinals = [p.ordinal for p in self.phases]
        ids = [p.id for p in self.phases]

        # Unique ordinals (Requirement 1.1).
        if len(set(ordinals)) != n:
            raise ValueError(f"phase ordinals must be unique, got {ordinals}")

        # Contiguous starting at 1 (Requirement 1.1).
        if sorted(ordinals) != list(range(1, n + 1)):
            raise ValueError(
                "phase ordinals must be contiguous starting at 1 "
                f"(expected {list(range(1, n + 1))}, got {sorted(ordinals)})"
            )

        # The phase list must be provided in ascending ordinal order so the
        # "ordered phases" contract is explicit and phases[0]/phases[-1] are the
        # first/final phases.
        if ordinals != sorted(ordinals):
            raise ValueError(
                "phases must be provided in ascending ordinal order, "
                f"got ordinals {ordinals}"
            )

        # Unique ids (Requirement 1.1).
        if len(set(ids)) != n:
            raise ValueError(f"phase ids must be unique, got {ids}")

        # First phase (ordinal 1) is the existing Phase_1_Pipeline
        # (Requirement 1.1).
        first_phase = self.phases[0]
        if first_phase.id != FIRST_PHASE_ID:
            raise ValueError(
                f"the first phase (ordinal 1) must have id {FIRST_PHASE_ID!r}, "
                f"got {first_phase.id!r}"
            )

        # Final phase (highest ordinal) is a speech-native platform
        # (Requirement 1.1).
        final_phase = self.phases[-1]
        if not final_phase.is_speech_native:
            raise ValueError(
                "the final phase (highest ordinal) must be speech-native "
                f"(is_speech_native must be True), got phase {final_phase.id!r}"
            )

        # Re-affirm per-phase guide-section and compute-footprint requirements
        # at the aggregate level (Requirements 1.6, 9.1). Phase validates these
        # too, but the roadmap guarantees no malformed phase can enter.
        for phase in self.phases:
            if len(phase.guide_sections) < 1:
                raise ValueError(
                    f"phase {phase.id!r} must map to at least one "
                    "implementation-guide section heading (Requirement 1.6)"
                )
            if any(not s or not s.strip() for s in phase.guide_sections):
                raise ValueError(
                    f"phase {phase.id!r} has an empty guide-section heading "
                    "(Requirement 1.6)"
                )
            if (
                not phase.compute_min_gpu_class
                or not phase.compute_min_gpu_class.strip()
            ):
                raise ValueError(
                    f"phase {phase.id!r} must state a minimum GPU class "
                    "(Requirement 9.1)"
                )
            if phase.compute_min_vram_gb < 0:
                raise ValueError(
                    f"phase {phase.id!r} must state a non-negative minimum VRAM "
                    f"in GB, got {phase.compute_min_vram_gb} (Requirement 9.1)"
                )

    # --- read accessors ----------------------------------------------------

    @property
    def first_phase(self) -> Phase:
        """The first phase in the roadmap (ordinal 1, the Phase_1_Pipeline)."""

        return self.phases[0]

    @property
    def final_phase(self) -> Phase:
        """The final phase in the roadmap (highest ordinal, speech-native)."""

        return self.phases[-1]

    @property
    def guide_section_map(self) -> dict[str, list[str]]:
        """Map each phase id to its implementation-guide section headings.

        Exposes the per-phase guide-section traceability the design requires
        (Requirement 1.6).
        """

        return {p.id: list(p.guide_sections) for p in self.phases}

    def phase_by_id(self, phase_id: str) -> Phase:
        """Return the phase with ``phase_id``.

        Raises:
            KeyError: If no phase has the given id.
        """

        for phase in self.phases:
            if phase.id == phase_id:
                return phase
        raise KeyError(f"no phase with id {phase_id!r}")

    def phases_for_track(self, track: str) -> list[Phase]:
        """Return the phases belonging to ``track``, in ordinal order."""

        return [p for p in self.phases if p.track == track]


__all__ = [
    "FIRST_PHASE_ID",
    "ConflictEntry",
    "ScopeStatements",
    "Roadmap",
]
