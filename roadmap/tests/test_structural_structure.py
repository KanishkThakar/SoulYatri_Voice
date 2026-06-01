"""Structural/example tests for the narrative roadmap (``roadmap/ROADMAP.md``).

These are plain ``pytest`` tests (no Hypothesis) that read the authored
planning artifact via the :data:`roadmap.paths.ROADMAP_MD_PATH` constant and
assert that the required *track/gate structure* and *scope statements* are
present in the document text.

Covers the narrative acceptance criteria for Task 24.1:

* Req 1.2 — LEAN_Track labeled "primary", AMBITIOUS_Track labeled "optional",
  with the AMBITIOUS_Track positioned **after** the decision gate.
* Req 1.3 — at least one Decision_Gate positioned **between** the LEAN and
  AMBITIOUS tracks.
* Req 1.7 — a conflict register whose rows are complete (topic, conflicting
  PDF, superseding decision, rationale).
* Req 12.1 — an explicit authoritative/supersedes statement (this roadmap is
  the authoritative build plan superseding the ``docs/`` strategy PDFs).
* Req 12.2 — a reference to ``.kiro/specs/ai-training-docs/`` as the
  documentation / knowledge-base workstream.
* Req 12.3 — that reference does **not** restate the doc-generation
  requirements (the document declares it does not restate/duplicate them).
* Req 12.4 — explicit exclusion of from-scratch foundation-model pretraining.
* Req 12.5 — explicit exclusion of executing GPU-based model-training runs.
* Req 12.7 — a planning-artifact-only declaration (the sole deliverable is a
  planning artifact).

Assertions are intentionally robust: they match case-insensitively against a
whitespace-normalized copy of the document (with Markdown emphasis ``*`` and
backtick characters stripped) using bounded-gap regular expressions, rather
than relying on brittle exact-line matching. They remain specific enough to be
meaningful.
"""

from __future__ import annotations

import re

import pytest

from roadmap.paths import ROADMAP_MD_PATH


# ---------------------------------------------------------------------------
# Fixtures: load the authored artifact via the ROADMAP_MD_PATH constant.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def roadmap_raw() -> str:
    """Raw text of ``ROADMAP.md`` (structure preserved, e.g. tables)."""
    assert ROADMAP_MD_PATH.exists(), (
        f"Narrative planning artifact not found at {ROADMAP_MD_PATH}. "
        "Task 23 must author roadmap/ROADMAP.md before these structural "
        "tests can verify it."
    )
    return ROADMAP_MD_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def roadmap_norm(roadmap_raw: str) -> str:
    """Lower-cased text with Markdown emphasis/backticks removed and whitespace
    collapsed to single spaces, for robust substring/regex matching.

    Underscores are preserved so identifiers such as ``LEAN_Track`` and the
    path ``ai-training-docs`` survive normalization.
    """
    stripped = re.sub(r"[`*]", "", roadmap_raw)
    collapsed = re.sub(r"\s+", " ", stripped)
    return collapsed.lower()


def _matches_any(text: str, patterns: list[str]) -> bool:
    """True when at least one regex in ``patterns`` matches ``text``."""
    return any(re.search(p, text) is not None for p in patterns)


# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------
def test_roadmap_md_exists_and_nonempty(roadmap_raw: str) -> None:
    """The artifact resolves via ROADMAP_MD_PATH and has substantive content."""
    assert len(roadmap_raw.strip()) > 500, (
        "ROADMAP.md is unexpectedly short; the narrative artifact appears "
        "incomplete."
    )


# ---------------------------------------------------------------------------
# Requirement 1.2 — track labels + AMBITIOUS positioned after the gate
# ---------------------------------------------------------------------------
def test_lean_labeled_primary_and_ambitious_labeled_optional(
    roadmap_norm: str,
) -> None:
    """Req 1.2: LEAN_Track is labeled 'primary', AMBITIOUS_Track 'optional'."""
    lean_primary_patterns = [
        r"lean_track.{0,40}\bprimary\b",  # "LEAN_Track — labeled primary"
        r"lean\s*\|\s*primary",           # phase table row cell
    ]
    ambitious_optional_patterns = [
        r"ambitious_track.{0,40}\boptional\b",
        r"ambitious\s*\|\s*optional",
    ]

    assert _matches_any(roadmap_norm, lean_primary_patterns), (
        "Req 1.2: the roadmap must explicitly label the LEAN_Track as "
        "'primary'."
    )
    assert _matches_any(roadmap_norm, ambitious_optional_patterns), (
        "Req 1.2: the roadmap must explicitly label the AMBITIOUS_Track as "
        "'optional'."
    )


def test_ambitious_track_positioned_after_decision_gate(
    roadmap_norm: str,
) -> None:
    """Req 1.2: AMBITIOUS_Track is positioned after the Decision_Gate."""
    patterns = [
        # "...AMBITIOUS_Track ... after Decision_Gate G1"
        r"ambitious_track.{0,120}\bafter\b.{0,40}(decision_gate|decision gate|\bg1\b)",
        # "...AMBITIOUS_Track gated behind ... decision gate"
        r"ambitious_track.{0,120}\bbehind\b.{0,60}(decision_gate|decision gate|\bg1\b)",
    ]
    assert _matches_any(roadmap_norm, patterns), (
        "Req 1.2: the roadmap must position the AMBITIOUS_Track after the "
        "decision gate (e.g. after Decision_Gate G1)."
    )


# ---------------------------------------------------------------------------
# Requirement 1.3 — at least one Decision_Gate between the tracks
# ---------------------------------------------------------------------------
def test_at_least_one_decision_gate_between_the_tracks(
    roadmap_norm: str,
) -> None:
    """Req 1.3: >= 1 Decision_Gate positioned between LEAN and AMBITIOUS."""
    # A decision gate is named and described.
    assert "decision_gate" in roadmap_norm or "decision gate" in roadmap_norm, (
        "Req 1.3: the roadmap must define a Decision_Gate."
    )
    assert re.search(r"\bg1\b", roadmap_norm), (
        "Req 1.3: the decision gate (G1) must be named."
    )
    # It is described as a decision-kind gate.
    assert re.search(r"kind:?\s*decision", roadmap_norm), (
        "Req 1.3: the gate must be identified as kind 'decision'."
    )
    # It sits between the two tracks.
    between_patterns = [
        r"(decision_gate|decision gate|\bg1\b).{0,80}between.{0,60}lean_track.{0,60}ambitious_track",
        r"between.{0,40}lean_track.{0,40}ambitious_track",
    ]
    assert _matches_any(roadmap_norm, between_patterns), (
        "Req 1.3: the Decision_Gate must be positioned between the LEAN_Track "
        "and the AMBITIOUS_Track."
    )


# ---------------------------------------------------------------------------
# Requirement 1.7 — conflict register with complete rows
# ---------------------------------------------------------------------------
def _extract_section(raw: str, heading_regex: str) -> str:
    """Return the text of the Markdown section whose heading matches, up to the
    next level-2 (``## ``) heading or end-of-document."""
    lines = raw.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(heading_regex, line.strip(), flags=re.IGNORECASE):
            start = i
            break
    assert start is not None, (
        f"Could not locate a section heading matching {heading_regex!r}."
    )
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _table_rows(section: str) -> list[list[str]]:
    """Parse Markdown table data rows (excluding header + separator) into lists
    of trimmed cell strings."""
    table_lines = [
        ln.strip()
        for ln in section.splitlines()
        if ln.strip().startswith("|")
    ]
    rows: list[list[str]] = []
    for ln in table_lines:
        # Separator rows like |---|---| are skipped.
        if re.fullmatch(r"\|[\s:\-|]+\|", ln):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def test_conflict_register_present_with_complete_rows(roadmap_raw: str) -> None:
    """Req 1.7: a conflict register exists whose rows each carry a topic, a
    conflicting PDF, a superseding decision, and a rationale."""
    section = _extract_section(roadmap_raw, r"#{2,3}\s.*conflict register")
    rows = _table_rows(section)

    assert len(rows) >= 1, "Req 1.7: the conflict register table is missing."

    header = [c.lower() for c in rows[0]]
    header_text = " ".join(header)
    assert len(header) == 4, (
        "Req 1.7: the conflict register must have four columns "
        f"(topic, conflicting PDF, superseding decision, rationale); got {header}."
    )
    assert "topic" in header_text, "Req 1.7: missing 'topic' column."
    assert ("pdf" in header_text or "document" in header_text), (
        "Req 1.7: missing 'conflicting PDF/document' column."
    )
    assert ("superseding" in header_text or "decision" in header_text), (
        "Req 1.7: missing 'superseding decision' column."
    )
    assert "rationale" in header_text, "Req 1.7: missing 'rationale' column."

    data_rows = rows[1:]
    assert len(data_rows) >= 3, (
        "Req 1.7: the conflict register should record the known conflicts; "
        f"expected at least 3 data rows, got {len(data_rows)}."
    )
    for idx, row in enumerate(data_rows):
        assert len(row) == 4, (
            f"Req 1.7: conflict-register row {idx} must have four cells "
            f"(topic, PDF, decision, rationale); got {row}."
        )
        for col, cell in zip(
            ("topic", "conflicting PDF", "superseding decision", "rationale"),
            row,
        ):
            assert cell, (
                f"Req 1.7: conflict-register row {idx} has an empty "
                f"'{col}' cell: {row}."
            )

    # The known superseded PDFs appear within the register (each row names a
    # conflicting PDF file).
    section_lower = section.lower()
    assert "soulyatri_master_bible.pdf" in section_lower, (
        "Req 1.7: the SOULYATRI_MASTER_BIBLE.pdf conflict row is missing."
    )
    assert "vox_omega_final_verified_60_day_plan.pdf" in section_lower, (
        "Req 1.7: the VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN.pdf conflict row "
        "is missing."
    )
    # Every data row's PDF cell names a .pdf file.
    for idx, row in enumerate(data_rows):
        assert ".pdf" in row[1].lower(), (
            f"Req 1.7: conflict-register row {idx} must name a conflicting "
            f"PDF in its second column; got {row[1]!r}."
        )


# ---------------------------------------------------------------------------
# Requirement 12.1 — authoritative / supersedes statement
# ---------------------------------------------------------------------------
def test_authoritative_supersedes_statement(roadmap_norm: str) -> None:
    """Req 12.1: the roadmap declares itself the authoritative build plan that
    supersedes the docs/ strategy PDFs."""
    assert "authoritative build plan" in roadmap_norm, (
        "Req 12.1: the roadmap must declare itself the authoritative build "
        "plan."
    )
    supersede_patterns = [
        r"supersed\w+.{0,60}(strategy )?pdf",
        r"supersed\w+.{0,60}docs/",
        r"supersed\w+ (that|every|the) pdf",
    ]
    assert _matches_any(roadmap_norm, supersede_patterns), (
        "Req 12.1: the roadmap must state it supersedes the docs/ strategy "
        "PDFs."
    )


# ---------------------------------------------------------------------------
# Requirement 12.2 / 12.3 — reference ai-training-docs without restating docs
# ---------------------------------------------------------------------------
def test_references_ai_training_docs_spec(roadmap_norm: str) -> None:
    """Req 12.2: the roadmap references the ai-training-docs spec as the
    documentation/knowledge-base workstream."""
    assert ".kiro/specs/ai-training-docs/" in roadmap_norm, (
        "Req 12.2: the roadmap must reference the "
        "`.kiro/specs/ai-training-docs/` spec."
    )
    role_patterns = [
        r"documentation\s*/\s*knowledge-base workstream",
        r"knowledge-base workstream",
        r"documentation.{0,40}workstream",
    ]
    assert _matches_any(roadmap_norm, role_patterns), (
        "Req 12.2: the ai-training-docs spec must be referenced as the "
        "documentation / knowledge-base workstream."
    )


def test_does_not_restate_doc_generation_requirements(roadmap_norm: str) -> None:
    """Req 12.3: the roadmap declares it does not restate/duplicate the
    ai-training-docs documentation-generation requirements."""
    patterns = [
        r"does not.{0,60}(restate|redefine|duplicate).{0,80}documentation",
        r"(restate|redefine|duplicate).{0,80}documentation-generation",
    ]
    assert _matches_any(roadmap_norm, patterns), (
        "Req 12.3: the roadmap must state it does not restate or duplicate the "
        "ai-training-docs documentation-generation requirements."
    )


# ---------------------------------------------------------------------------
# Requirement 12.4 / 12.5 — scope exclusions
# ---------------------------------------------------------------------------
def test_excludes_from_scratch_pretraining(roadmap_norm: str) -> None:
    """Req 12.4: explicit exclusion of from-scratch foundation-model
    pretraining."""
    patterns = [
        r"from-scratch[\s\w-]{0,40}pretraining[\s\w-]{0,20}exclud",
        r"exclud\w+[\s\w-]{0,40}from-scratch[\s\w-]{0,40}pretraining",
    ]
    assert _matches_any(roadmap_norm, patterns), (
        "Req 12.4: the roadmap must explicitly exclude from-scratch "
        "foundation-model pretraining."
    )


def test_excludes_gpu_based_training_runs(roadmap_norm: str) -> None:
    """Req 12.5: explicit exclusion of executing GPU-based model-training
    runs."""
    patterns = [
        r"gpu-based[\s\w-]{0,40}training[\s\w-]{0,20}exclud",
        r"gpu-based[\s\w-]{0,40}exclud",
        r"exclud\w+[\s\w-]{0,40}gpu-based[\s\w-]{0,40}training",
    ]
    assert _matches_any(roadmap_norm, patterns), (
        "Req 12.5: the roadmap must explicitly exclude executing GPU-based "
        "model-training runs."
    )
    # It frames training execution as planned-but-not-performed downstream work.
    downstream_patterns = [
        r"downstream work.{0,60}(plans|planned).{0,40}(but )?(does not|not) perform",
        r"plans but does not perform",
    ]
    assert _matches_any(roadmap_norm, downstream_patterns), (
        "Req 12.5: the roadmap must identify training execution as downstream "
        "work it plans but does not perform."
    )


# ---------------------------------------------------------------------------
# Requirement 12.7 — planning-artifact-only declaration
# ---------------------------------------------------------------------------
def test_planning_artifact_only_declaration(roadmap_norm: str) -> None:
    """Req 12.7: the sole deliverable is declared to be a planning artifact."""
    patterns = [
        r"sole deliverable[\s\w'`-]{0,40}planning artifact",
        r"deliverable[\s\w'`-]{0,30}is[\s\w'`-]{0,20}planning artifact",
    ]
    assert _matches_any(roadmap_norm, patterns), (
        "Req 12.7: the roadmap must declare that its sole deliverable is a "
        "planning artifact."
    )
