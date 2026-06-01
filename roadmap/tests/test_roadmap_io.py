"""Round-trip and structural tests for ``roadmap.roadmap_io`` (Task 29.3).

This module verifies the two responsibilities of ``roadmap/roadmap_io.py``:

1. :func:`~roadmap.roadmap_io.load_roadmap` materializes a **valid**
   :class:`~roadmap.roadmap_model.Roadmap` aggregate from the structured
   ``roadmap/data/roadmap_data.yaml`` source — the canonical seven-phase plan
   (``P1-baseline``..``P7-diff-gate``) with contiguous ordinals starting at 1,
   the first phase ``P1-baseline``, a final speech-native phase, the gates
   (including the ``G1`` decision gate), and the conflict register all present.

2. The ``ROADMAP.md`` Markdown round-trip is *lossless*:
   ``parse_markdown(render_markdown(r)) == r`` (dataclass equality) for the
   loaded roadmap and for hand-built variants, and :func:`render_markdown`
   emits the expected machine-readable section headings/tables.

A Hypothesis-driven round-trip over generated valid roadmaps is included for
broad, generative confidence. It is a *complementary* round-trip invariant —
deliberately **not** one of the 15 numbered design correctness properties — so
it is not tagged with the numbered ``Property {n}`` comment marker.

Validates: Requirements 1.1, 1.6.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.models.phases import (
    GATE_KIND_VALUES,
    OPERATOR_VALUES,
    Gate,
    GateCriterion,
    Phase,
)
from roadmap.roadmap_io import (
    DEFAULT_ROADMAP_DATA_PATH,
    load_roadmap,
    parse_markdown,
    render_markdown,
)
from roadmap.roadmap_model import (
    FIRST_PHASE_ID,
    ConflictEntry,
    Roadmap,
    ScopeStatements,
)
from roadmap.tests.fixtures import make_phase, make_valid_roadmap

# ---------------------------------------------------------------------------
# Expected canonical structure of the loaded roadmap
# ---------------------------------------------------------------------------

#: The seven phase ids the structured data file encodes, in ordinal order.
EXPECTED_PHASE_IDS = [
    "P1-baseline",
    "P2-core-select",
    "P3-integrate",
    "P4-moat-duplex",
    "P5-safety-gate",
    "P6-custom",
    "P7-diff-gate",
]

#: The machine-readable section headings :func:`render_markdown` must emit.
EXPECTED_SECTION_HEADINGS = [
    "## Phases",
    "## Track labels",
    "## Gates",
    "## Gate criteria",
    "## Conflict register",
    "## Scope statements",
]


# ===========================================================================
# 1. load_roadmap produces a valid aggregate
# ===========================================================================


def test_load_roadmap_returns_roadmap_instance() -> None:
    """``load_roadmap()`` builds a :class:`Roadmap` from the default data file.

    Validates: Requirements 1.1, 1.6.
    """
    roadmap = load_roadmap()
    assert isinstance(roadmap, Roadmap)
    # The default data path resolves to the structured YAML source.
    assert DEFAULT_ROADMAP_DATA_PATH.name == "roadmap_data.yaml"
    assert DEFAULT_ROADMAP_DATA_PATH.exists()


def test_load_roadmap_has_seven_canonical_phases() -> None:
    """The loaded roadmap carries the seven canonical phases in ordinal order.

    Validates: Requirements 1.1.
    """
    roadmap = load_roadmap()
    assert [p.id for p in roadmap.phases] == EXPECTED_PHASE_IDS
    assert all(isinstance(p, Phase) for p in roadmap.phases)


def test_load_roadmap_ordinals_contiguous_from_one() -> None:
    """Phase ordinals are contiguous starting at 1 (1..7).

    Validates: Requirements 1.1.
    """
    roadmap = load_roadmap()
    ordinals = [p.ordinal for p in roadmap.phases]
    assert ordinals == list(range(1, len(roadmap.phases) + 1))


def test_load_roadmap_first_phase_is_baseline_and_final_is_speech_native() -> None:
    """First phase is ``P1-baseline``; the final phase is speech-native.

    Validates: Requirements 1.1.
    """
    roadmap = load_roadmap()
    assert roadmap.first_phase.id == FIRST_PHASE_ID == "P1-baseline"
    assert roadmap.first_phase.ordinal == 1
    assert roadmap.first_phase.is_speech_native is False
    assert roadmap.final_phase.id == "P7-diff-gate"
    assert roadmap.final_phase.is_speech_native is True


def test_load_roadmap_every_phase_has_guide_section_and_compute_footprint() -> None:
    """Every phase carries >=1 guide section and a compute footprint.

    Validates: Requirements 1.6.
    """
    roadmap = load_roadmap()
    for phase in roadmap.phases:
        assert len(phase.guide_sections) >= 1
        assert all(s.strip() for s in phase.guide_sections)
        assert phase.compute_min_gpu_class.strip()
        assert phase.compute_min_vram_gb >= 0


def test_load_roadmap_has_gates_including_decision_gate_g1() -> None:
    """The gate set is present and includes the ``G1`` decision gate.

    Validates: Requirements 1.1.
    """
    roadmap = load_roadmap()
    gate_ids = [g.id for g in roadmap.gates]
    assert "G1" in gate_ids
    g1 = next(g for g in roadmap.gates if g.id == "G1")
    assert g1.kind == "decision"
    assert g1.owner_role == "ML Lead"
    assert g1.fallback_action == "remain on LEAN_Track"
    # G1 carries both entry and exit criteria.
    assert len(g1.entry_criteria) >= 1
    assert len(g1.exit_criteria) >= 1


def test_load_roadmap_has_conflict_register() -> None:
    """The conflict register is present with complete rows.

    Validates: Requirements 1.1.
    """
    roadmap = load_roadmap()
    assert len(roadmap.conflicts) >= 1
    for conflict in roadmap.conflicts:
        assert isinstance(conflict, ConflictEntry)
        assert conflict.topic.strip()
        assert conflict.superseding_decision.strip()
        assert conflict.rationale.strip()


# ===========================================================================
# 2. Markdown round-trip equals the loaded roadmap
# ===========================================================================


def test_markdown_roundtrip_equals_loaded_roadmap() -> None:
    """``parse_markdown(render_markdown(r)) == r`` for the loaded roadmap.

    Validates: Requirements 1.1, 1.6.
    """
    roadmap = load_roadmap()
    assert parse_markdown(render_markdown(roadmap)) == roadmap


def test_markdown_roundtrip_equals_canonical_fixture_roadmap() -> None:
    """The canonical fixture roadmap survives the Markdown round-trip unchanged.

    Validates: Requirements 1.1.
    """
    roadmap = make_valid_roadmap()
    assert parse_markdown(render_markdown(roadmap)) == roadmap


def test_markdown_roundtrip_minimal_two_phase_roadmap() -> None:
    """A minimal two-phase baseline -> speech-native roadmap round-trips.

    Validates: Requirements 1.1.
    """
    roadmap = Roadmap(phases=_minimal_phases())
    assert parse_markdown(render_markdown(roadmap)) == roadmap


def test_markdown_roundtrip_with_gates_conflicts_and_custom_scope() -> None:
    """A roadmap with gates, conflicts, and custom scope round-trips exactly.

    Exercises pipe-escaping, the multi-guide-section join, float/bool encoding,
    and the entry/exit gate-criteria grouping all at once.

    Validates: Requirements 1.1, 1.6.
    """
    roadmap = Roadmap(
        phases=[
            make_phase(
                ordinal=1,
                id=FIRST_PHASE_ID,
                is_speech_native=False,
                guide_sections=["A | with pipe", "B \\ with backslash", "C section"],
                compute_min_gpu_class="L4-24GB",
                compute_min_vram_gb=24.5,
            ),
            make_phase(
                ordinal=2,
                id="P2-final",
                track="AMBITIOUS",
                title="Final | speech-native | platform",
                is_speech_native=True,
            ),
        ],
        track_labels={"LEAN": "primary", "AMBITIOUS": "optional"},
        gates=[
            Gate(
                id="G1",
                kind="decision",
                entry_criteria=[GateCriterion("lean_gate_passed", 1.0, "==")],
                exit_criteria=[
                    GateCriterion("competitive_gap_pct", 10.0, ">="),
                    GateCriterion("vram_gb", 80.0, ">="),
                ],
                owner_role="ML Lead",
                fallback_action="remain on LEAN_Track",
            ),
            Gate(
                id="LEAN-DEMO",
                kind="launch",
                exit_criteria=[GateCriterion("latency_ms_p50", 300.0, "<=")],
                owner_role="Release Manager",
                fallback_action="withhold | the | declaration",
            ),
        ],
        conflicts=[
            ConflictEntry(
                topic="Custom | codec first",
                superseding_decision="Use kyutai/mimi as primary codec.",
                rationale="Mimi is production-ready.",
                conflicting_document="SOULYATRI_VOICE_AI_FINAL_BUILD_BIBLE.pdf",
            )
        ],
        scope_statements=ScopeStatements.default(),
    )
    assert parse_markdown(render_markdown(roadmap)) == roadmap


# ===========================================================================
# 3. Structural: render_markdown emits the expected headings/tables
# ===========================================================================


def test_render_markdown_contains_expected_section_headings() -> None:
    """The rendered document contains every machine-readable section heading.

    Validates: Requirements 1.1, 1.6.
    """
    md = render_markdown(load_roadmap())
    for heading in EXPECTED_SECTION_HEADINGS:
        assert heading in md, f"missing section heading {heading!r}"


def test_render_markdown_emits_table_structure() -> None:
    """Each section is followed by a GitHub-flavoured Markdown table.

    Validates: Requirements 1.1.
    """
    md = render_markdown(load_roadmap())
    # The phases table header and its separator row are present.
    assert "| Ordinal | ID | Track | Title |" in md
    assert "|---|---|---|---|---|---|---|---|" in md
    # The other table header rows are present.
    assert "| Track | Label |" in md
    assert "| ID | Kind | Owner role | Fallback action |" in md
    assert "| Gate ID | Criteria set | Metric | Operator | Threshold |" in md
    assert "| Topic | Conflicting document | Superseding decision | Rationale |" in md
    assert "| Key | Statement |" in md


def test_render_markdown_includes_phase_and_gate_content() -> None:
    """The rendered tables carry the canonical phase ids and gate metadata.

    Validates: Requirements 1.1.
    """
    md = render_markdown(load_roadmap())
    for phase_id in EXPECTED_PHASE_IDS:
        assert phase_id in md
    # Track labels and the decision-gate owner/fallback appear in the tables.
    assert "primary" in md
    assert "optional" in md
    assert "ML Lead" in md
    assert "remain on LEAN_Track" in md


# ===========================================================================
# Hypothesis round-trip over generated valid roadmaps
# (complementary invariant — NOT a numbered design Property)
# ===========================================================================

#: Non-blank short text (printable ASCII, no spaces) — always non-empty after
#: ``strip()`` and free of the ``" ; "`` guide-section separator, so it is safe
#: across the Markdown round-trip while still exercising pipe/backslash escaping.
_NON_BLANK = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=20,
)

#: Free-form short text (may be empty / contain spaces) for fields without a
#: non-empty constraint (e.g. ``ConflictEntry.conflicting_document``).
_TEXT = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    max_size=20,
)

#: Any finite float — rendered with ``repr`` and parsed with ``float``, so it
#: round-trips losslessly.
_FINITE_FLOAT = st.floats(allow_nan=False, allow_infinity=False)

#: A non-negative VRAM figure in GB.
_VRAM_GB = st.floats(
    min_value=0.0, max_value=1024.0, allow_nan=False, allow_infinity=False
)

_OPERATOR = st.sampled_from(OPERATOR_VALUES)

_gate_criterion_strategy = st.builds(
    GateCriterion,
    metric_name=_NON_BLANK,
    threshold=_FINITE_FLOAT,
    operator=_OPERATOR,
)

_gate_strategy = st.builds(
    Gate,
    id=_NON_BLANK,
    kind=st.sampled_from(GATE_KIND_VALUES),
    entry_criteria=st.lists(_gate_criterion_strategy, max_size=3),
    exit_criteria=st.lists(_gate_criterion_strategy, max_size=3),
    owner_role=_NON_BLANK,
    fallback_action=_NON_BLANK,
)

_conflict_entry_strategy = st.builds(
    ConflictEntry,
    topic=_NON_BLANK,
    superseding_decision=_NON_BLANK,
    rationale=_NON_BLANK,
    conflicting_document=st.one_of(st.just(""), _NON_BLANK),
)

_scope_statements_strategy = st.builds(
    ScopeStatements,
    authoritative_supersedes_pdfs=_NON_BLANK,
    references_ai_training_docs=_NON_BLANK,
    excludes_from_scratch_pretraining=_NON_BLANK,
    excludes_gpu_training_execution=_NON_BLANK,
    planning_artifact_only=_NON_BLANK,
)


def _minimal_phases() -> list[Phase]:
    """A fresh minimal, valid baseline -> speech-native two-phase list."""
    return [
        make_phase(ordinal=1, id=FIRST_PHASE_ID, is_speech_native=False),
        make_phase(
            ordinal=2,
            id="P2-speech-native",
            track="AMBITIOUS",
            title="Speech-native platform",
            is_speech_native=True,
        ),
    ]


@st.composite
def _roadmap_strategy(draw: st.DrawFn) -> Roadmap:
    """Draw a valid :class:`Roadmap` with decorated, round-trippable content.

    The phase list is one of two known-valid shapes (the canonical seven-phase
    plan or a minimal two-phase plan), decorated with optionally-empty gate,
    conflict, track-label, and scope-statement variations. Gate ids are drawn
    distinct (``unique_by``) so the Markdown criteria table, which groups
    criteria by gate id, reconstructs each gate's criteria unambiguously.
    """
    phases = draw(
        st.sampled_from(["canonical", "minimal"]).map(
            lambda shape: make_valid_roadmap().phases
            if shape == "canonical"
            else _minimal_phases()
        )
    )
    track_labels = draw(
        st.one_of(
            st.just({"LEAN": "primary", "AMBITIOUS": "optional"}),
            st.fixed_dictionaries({"LEAN": _NON_BLANK, "AMBITIOUS": _NON_BLANK}),
        )
    )
    return Roadmap(
        phases=phases,
        track_labels=track_labels,
        gates=draw(st.lists(_gate_strategy, max_size=3, unique_by=lambda g: g.id)),
        conflicts=draw(st.lists(_conflict_entry_strategy, max_size=3)),
        scope_statements=draw(
            st.one_of(st.builds(ScopeStatements.default), _scope_statements_strategy)
        ),
    )


@settings(max_examples=100)
@given(roadmap=_roadmap_strategy())
def test_markdown_roundtrip_property(roadmap: Roadmap) -> None:
    """``parse_markdown(render_markdown(r)) == r`` for any generated roadmap.

    Validates: Requirements 1.1, 1.6.
    """
    assert parse_markdown(render_markdown(roadmap)) == roadmap
