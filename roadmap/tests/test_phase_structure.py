"""Property-based test for design **Property 1: Phase-structure invariant**.

This module verifies the phase-structure invariant the :class:`Roadmap`
aggregate enforces on construction (``roadmap/roadmap_model.py``). Per the
design's ``Correctness Properties`` section:

    For any roadmap phase list, the phase ordinals are unique and contiguous
    starting at 1, the phase identifiers are unique, the first phase is the
    existing Phase_1_Pipeline (id ``"P1-baseline"``), the final phase is
    speech-native, and every phase carries at least one implementation-guide
    section heading and a compute footprint (minimum GPU class and minimum
    VRAM in GB).

The single design property is exercised from both directions so the invariant
is shown to be *enforced* rather than merely documented:

1. A *positive* generator builds VALID roadmaps and asserts the constructed
   :class:`Roadmap` satisfies every clause of the invariant and that its
   accessors (``first_phase``, ``final_phase``, ``guide_section_map``) agree.
2. A *negative* generator builds phase lists that violate exactly one clause
   and asserts the :class:`Roadmap` constructor RAISES ``ValueError`` /
   ``TypeError``.

The project Hypothesis profile ``roadmap`` (``max_examples=100``) is loaded by
``roadmap/tests/conftest.py``; each property test additionally pins
``@settings(max_examples=100)`` because the design mandates at least 100
examples per property.

Validates: Requirements 1.1, 1.6, 9.1.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.models.phases import TRACK_VALUES, Phase
from roadmap.roadmap_model import FIRST_PHASE_ID, Roadmap

# ---------------------------------------------------------------------------
# Generators (constrained to the valid input space, with edge coverage)
# ---------------------------------------------------------------------------

#: Non-blank short text: printable ASCII excluding the space character so every
#: drawn value remains non-empty after ``str.strip()``. Used for id suffixes,
#: titles, guide-section headings, and GPU-class labels.
_NON_BLANK_TEXT = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=16,
)

#: At least one guide-section heading per phase (Requirement 1.6), each
#: non-blank. ``min_size=1`` exercises the boundary of "carries >= 1 section".
_GUIDE_SECTIONS = st.lists(_NON_BLANK_TEXT, min_size=1, max_size=4)

#: A finite, non-negative minimum VRAM figure in GB (Requirement 9.1). The
#: lower bound of 0.0 exercises the "vram >= 0" boundary.
_VRAM_GB = st.floats(
    min_value=0.0, max_value=512.0, allow_nan=False, allow_infinity=False
)


@st.composite
def _valid_phase_list(draw: st.DrawFn, n: int) -> list[Phase]:
    """Draw a structurally valid list of ``n`` phases in ascending ordinal order.

    Guarantees, for the drawn list: ordinals are exactly ``1..n`` (unique and
    contiguous); the ordinal-1 phase carries id ``"P1-baseline"``; every other
    phase id is prefixed with its distinct ordinal so ids are unique and never
    collide with the baseline id; the highest-ordinal phase is speech-native;
    and each phase carries >= 1 guide section, a non-empty GPU class, and a
    non-negative VRAM figure.
    """
    phases: list[Phase] = []
    for ordinal in range(1, n + 1):
        if ordinal == 1:
            phase_id = FIRST_PHASE_ID
            # The baseline phase may or may not be speech-native; only the
            # FINAL phase is constrained to be speech-native.
            is_speech_native = draw(st.booleans())
        else:
            # The "P{ordinal}-" prefix makes ids unique across phases and keeps
            # them distinct from the ordinal-1 baseline id.
            phase_id = f"P{ordinal}-{draw(_NON_BLANK_TEXT)}"
            is_speech_native = True if ordinal == n else draw(st.booleans())

        phases.append(
            Phase(
                ordinal=ordinal,
                id=phase_id,
                track=draw(st.sampled_from(TRACK_VALUES)),
                title=draw(_NON_BLANK_TEXT),
                is_speech_native=is_speech_native,
                guide_sections=draw(_GUIDE_SECTIONS),
                compute_min_gpu_class=draw(_NON_BLANK_TEXT),
                compute_min_vram_gb=draw(_VRAM_GB),
            )
        )
    return phases


@st.composite
def valid_roadmaps(draw: st.DrawFn) -> Roadmap:
    """Draw a VALID :class:`Roadmap` with a varying number of phases (N >= 2)."""
    n = draw(st.integers(min_value=2, max_value=7))
    return Roadmap(phases=draw(_valid_phase_list(n)))


#: Each way a phase list can violate exactly one clause of the invariant.
_INVALID_MUTATIONS = (
    "non_contiguous_ordinals",
    "duplicate_ids",
    "wrong_first_id",
    "non_speech_native_final",
    "empty_guide_sections",
)


@st.composite
def invalid_phase_setups(draw: st.DrawFn) -> tuple[list[Phase], str]:
    """Draw a phase list that violates exactly one clause of the invariant.

    Returns the mutated phase list together with the mutation label so a
    failing counterexample names the clause that was being exercised. Each
    mutation starts from a valid list and breaks a single rule; the underlying
    :class:`Phase` objects stay individually valid (the broken rule is an
    aggregate-level one) except for ``empty_guide_sections``, which the
    aggregate re-affirms at construction time.
    """
    n = draw(st.integers(min_value=2, max_value=6))
    phases = draw(_valid_phase_list(n))
    mutation = draw(st.sampled_from(_INVALID_MUTATIONS))

    if mutation == "non_contiguous_ordinals":
        # Punch a hole in the ordinal sequence: 1..n-1, then n+1.
        phases[-1].ordinal = n + 1
    elif mutation == "duplicate_ids":
        # Make the final phase id collide with the baseline id.
        phases[-1].id = phases[0].id
    elif mutation == "wrong_first_id":
        # The ordinal-1 phase is not the existing Phase_1_Pipeline.
        phases[0].id = "X1-not-baseline"
    elif mutation == "non_speech_native_final":
        # The highest-ordinal phase is not speech-native.
        phases[-1].is_speech_native = False
    elif mutation == "empty_guide_sections":
        # Some phase loses its implementation-guide traceability.
        idx = draw(st.integers(min_value=0, max_value=n - 1))
        phases[idx].guide_sections = []

    return phases, mutation


# ---------------------------------------------------------------------------
# Property 1: Phase-structure invariant
# ---------------------------------------------------------------------------


# Feature: speech-native-voice-roadmap, Property 1: Phase-structure invariant
@settings(max_examples=100)
@given(roadmap=valid_roadmaps())
def test_phase_structure_invariant_holds_for_valid_roadmaps(roadmap: Roadmap) -> None:
    """Every generated VALID roadmap satisfies all clauses of Property 1.

    Validates: Requirements 1.1, 1.6, 9.1.
    """
    phases = roadmap.phases
    n = len(phases)
    ordinals = [p.ordinal for p in phases]
    ids = [p.id for p in phases]

    # At least two phases (Requirement 1.1).
    assert n >= 2

    # Ordinals are unique and contiguous starting at 1, presented in ascending
    # order (Requirement 1.1).
    assert len(set(ordinals)) == n
    assert sorted(ordinals) == list(range(1, n + 1))
    assert ordinals == list(range(1, n + 1))

    # Identifiers are unique (Requirement 1.1).
    assert len(set(ids)) == n

    # First phase (ordinal 1) is the existing Phase_1_Pipeline (Requirement 1.1).
    assert phases[0].id == FIRST_PHASE_ID
    assert roadmap.first_phase.id == FIRST_PHASE_ID

    # Final phase (highest ordinal) is speech-native (Requirement 1.1).
    assert phases[-1].is_speech_native is True
    assert roadmap.final_phase.is_speech_native is True

    # Every phase carries >= 1 implementation-guide section heading
    # (Requirement 1.6) and a compute footprint: a non-empty minimum GPU class
    # and a non-negative minimum VRAM in GB (Requirement 9.1).
    for phase in phases:
        assert len(phase.guide_sections) >= 1
        assert all(s.strip() for s in phase.guide_sections)
        assert phase.compute_min_gpu_class.strip()
        assert phase.compute_min_vram_gb >= 0.0

    # The guide-section map mirrors each phase's traceability (Requirement 1.6).
    guide_map = roadmap.guide_section_map
    assert set(guide_map) == set(ids)
    for phase in phases:
        assert guide_map[phase.id] == list(phase.guide_sections)


# Feature: speech-native-voice-roadmap, Property 1: Phase-structure invariant
@settings(max_examples=100)
@given(setup=invalid_phase_setups())
def test_phase_structure_invariant_rejects_invalid_roadmaps(
    setup: tuple[list[Phase], str],
) -> None:
    """A phase list violating any single clause is REJECTED by ``Roadmap``.

    Confirms the invariant of Property 1 is actually enforced on construction
    rather than merely documented.

    Validates: Requirements 1.1, 1.6, 9.1.
    """
    phases, mutation = setup
    with pytest.raises((ValueError, TypeError)):
        Roadmap(phases=phases)
    # ``mutation`` is carried only so a counterexample names the violated clause.
    assert mutation in _INVALID_MUTATIONS
