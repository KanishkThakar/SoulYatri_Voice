"""Load the roadmap aggregate from its structured data file.

This module is the single entry point for materializing the :class:`Roadmap`
aggregate from the structured source data authored in
``roadmap/data/roadmap_data.yaml`` (Task 29.1). It keeps the *structured data
file* and the in-memory aggregate in lock-step so the rest of the tooling reads
one source of truth.

:func:`load_roadmap` performs three steps:

1. **Read.** Parse the YAML document with :func:`yaml.safe_load` (plain scalars
   and containers only — no arbitrary object construction).
2. **Build.** Reconstruct the :class:`Roadmap` aggregate from the parsed mapping
   via :func:`roadmap.serialization.from_dict`. Construction runs every Task 5
   phase-structure invariant in :meth:`Roadmap.__post_init__` (contiguous
   ordinals from 1, unique ids, first phase ``P1-baseline``, final phase
   speech-native, per-phase guide sections + compute footprint), so a malformed
   data file fails loudly here.
3. **Validate.** Re-serialize the built aggregate with
   :func:`roadmap.serialization.to_dict` and validate it against the Task 28
   JSON Schema (schema name ``"roadmap"``) via :func:`roadmap.schema.validate`,
   so the loaded object additionally satisfies the published schema contract.

The module is pure Python (``yaml`` only) and imports no GPU/model-training
framework, preserving the package's import-only / no-training guarantee
(Requirement 4.6).

Note:
    Task 29.2 extends this module with ``render_markdown`` / ``parse_markdown``
    for the ``ROADMAP.md`` round-trip. :func:`load_roadmap` is intentionally
    kept small and stable so that addition does not perturb it.

Validates: Requirements 1.1, 1.6, 1.7, 9.1.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Union

import yaml

from .models.phases import Gate, GateCriterion, Phase
from .paths import DATA_DIR
from .roadmap_model import ConflictEntry, Roadmap, ScopeStatements
from .schema import schema_name_for, validate
from .serialization import from_dict, to_dict

__all__ = [
    "DEFAULT_ROADMAP_DATA_PATH",
    "load_roadmap",
    "render_markdown",
    "parse_markdown",
]

#: The default location of the structured roadmap source data file consumed by
#: :func:`load_roadmap` (``roadmap/data/roadmap_data.yaml``).
DEFAULT_ROADMAP_DATA_PATH: Path = DATA_DIR / "roadmap_data.yaml"


def load_roadmap(path: Union[str, Path] = DEFAULT_ROADMAP_DATA_PATH) -> Roadmap:
    """Load, build, and validate the :class:`Roadmap` from a YAML data file.

    Reads the structured roadmap data file, reconstructs the :class:`Roadmap`
    aggregate (which enforces the Task 5 phase-structure invariants on
    construction), and validates the result against the Task 28 ``"roadmap"``
    JSON Schema before returning it.

    Args:
        path: Path to the YAML data file. Defaults to
            :data:`DEFAULT_ROADMAP_DATA_PATH`
            (``roadmap/data/roadmap_data.yaml``).

    Returns:
        The validated :class:`Roadmap` aggregate (seven phases ``P1-baseline``
        ..``P7-diff-gate``, track labels, gates, conflict register, and scope
        statements).

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        SerializationError: If the parsed document carries an unknown field or a
            structurally wrong payload for the aggregate.
        TypeError | ValueError: If the parsed data violates a Task 5
            phase-structure invariant (raised by ``Roadmap.__post_init__``).
        SchemaValidationError: If the built aggregate violates the ``"roadmap"``
            JSON Schema (Task 28).
    """
    data_path = Path(path)
    raw = data_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise ValueError(
            f"roadmap data file {data_path} must contain a top-level mapping, "
            f"got {type(parsed).__name__}"
        )

    # Build the aggregate. ``Roadmap.__post_init__`` enforces every Task 5
    # phase-structure invariant, so an invalid data file fails here.
    roadmap: Roadmap = from_dict(Roadmap, parsed)

    # Re-affirm the published schema contract (Task 28) on the built aggregate.
    validate(to_dict(roadmap), schema_name_for(roadmap))

    return roadmap


# ===========================================================================
# ROADMAP.md round-trip (Task 29.2)
# ===========================================================================
# ``render_markdown`` serializes a :class:`Roadmap` to a Markdown document whose
# phase / track / gate / conflict / scope tables fully describe the aggregate,
# and ``parse_markdown`` reads that document back into an equal :class:`Roadmap`.
# Together they keep the structured data file and the narrative artifact one
# source of truth: ``parse_markdown(render_markdown(r)) == r`` (dataclass
# equality) for any roadmap built from the canonical data.
#
# The document is rendered as GitHub-flavoured Markdown tables under fixed
# ``## <heading>`` sections. Parsing locates each table by its heading and reads
# columns positionally, so it does not depend on prose between the tables. Cell
# values are pipe-escaped on render and unescaped on parse, and lists/floats/
# bools are encoded with reversible, precision-preserving representations so the
# round-trip reconstructs every field exactly.
#
# Validates: Requirements 1.1, 1.6, 1.7.

#: Delimiter joining the multiple guide-section headings of a phase inside a
#: single Markdown table cell. Chosen so it does not occur within any canonical
#: guide-section heading; ``render``/``parse`` are exact inverses for headings
#: that do not themselves contain this delimiter.
_GUIDE_SECTION_SEP = " ; "

#: Section headings used as machine-readable anchors for each rendered table.
_H_PHASES = "Phases"
_H_TRACK_LABELS = "Track labels"
_H_GATES = "Gates"
_H_GATE_CRITERIA = "Gate criteria"
_H_CONFLICTS = "Conflict register"
_H_SCOPE = "Scope statements"


def _escape_cell(text: str) -> str:
    """Escape a string for safe inclusion in a single Markdown table cell.

    Backslashes are doubled and pipe characters are backslash-escaped so the
    cell never prematurely terminates the column. :func:`_split_table_row` is
    the exact inverse.
    """
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _split_table_row(line: str) -> list[str]:
    """Split one Markdown table row into its trimmed, unescaped cell values.

    Honors backslash escapes (``\\|`` -> ``|``, ``\\\\`` -> ``\\``) so escaped
    pipes do not split a cell, and drops the leading/trailing column pipes.
    """
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]

    cells: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            current.append(s[i + 1])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    cells.append("".join(current))
    return [cell.strip() for cell in cells]


def _fmt_float(value: float) -> str:
    """Render a float losslessly (``float(_fmt_float(x)) == x``)."""
    return repr(float(value))


def _fmt_bool(value: bool) -> str:
    """Render a bool as ``true`` / ``false``."""
    return "true" if value else "false"


def _parse_bool(text: str) -> bool:
    """Parse a ``true`` / ``false`` cell (case-insensitive)."""
    return text.strip().lower() == "true"


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a Markdown table from already-escaped cell strings."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_markdown(roadmap: Roadmap) -> str:
    """Render a :class:`Roadmap` to a round-trippable ``ROADMAP.md`` document.

    Emits Markdown tables for the phases, track labels, gate definitions, gate
    criteria, conflict register, and scope statements. The output is the inverse
    of :func:`parse_markdown`: ``parse_markdown(render_markdown(r)) == r``.

    Args:
        roadmap: The roadmap aggregate to serialize.

    Returns:
        The Markdown document text.
    """
    parts: list[str] = ["# SoulYatri Speech-Native Voice Roadmap"]

    # --- Phases --------------------------------------------------------------
    phase_rows: list[list[str]] = []
    for phase in roadmap.phases:
        guide = _GUIDE_SECTION_SEP.join(phase.guide_sections)
        phase_rows.append(
            [
                str(phase.ordinal),
                _escape_cell(phase.id),
                _escape_cell(phase.track),
                _escape_cell(phase.title),
                _fmt_bool(phase.is_speech_native),
                _escape_cell(guide),
                _escape_cell(phase.compute_min_gpu_class),
                _fmt_float(phase.compute_min_vram_gb),
            ]
        )
    parts.append(f"## {_H_PHASES}\n")
    parts.append(
        _render_table(
            [
                "Ordinal",
                "ID",
                "Track",
                "Title",
                "Speech-native",
                "Guide sections",
                "Min GPU class",
                "Min VRAM (GB)",
            ],
            phase_rows,
        )
    )

    # --- Track labels --------------------------------------------------------
    label_rows = [
        [_escape_cell(track), _escape_cell(label)]
        for track, label in roadmap.track_labels.items()
    ]
    parts.append(f"## {_H_TRACK_LABELS}\n")
    parts.append(_render_table(["Track", "Label"], label_rows))

    # --- Gates ---------------------------------------------------------------
    gate_rows = [
        [
            _escape_cell(gate.id),
            _escape_cell(gate.kind),
            _escape_cell(gate.owner_role),
            _escape_cell(gate.fallback_action),
        ]
        for gate in roadmap.gates
    ]
    parts.append(f"## {_H_GATES}\n")
    parts.append(
        _render_table(["ID", "Kind", "Owner role", "Fallback action"], gate_rows)
    )

    # --- Gate criteria -------------------------------------------------------
    criterion_rows: list[list[str]] = []
    for gate in roadmap.gates:
        for criteria_set, criteria in (
            ("entry", gate.entry_criteria),
            ("exit", gate.exit_criteria),
        ):
            for criterion in criteria:
                criterion_rows.append(
                    [
                        _escape_cell(gate.id),
                        criteria_set,
                        _escape_cell(criterion.metric_name),
                        _escape_cell(criterion.operator),
                        _fmt_float(criterion.threshold),
                    ]
                )
    parts.append(f"## {_H_GATE_CRITERIA}\n")
    parts.append(
        _render_table(
            ["Gate ID", "Criteria set", "Metric", "Operator", "Threshold"],
            criterion_rows,
        )
    )

    # --- Conflict register ---------------------------------------------------
    conflict_rows = [
        [
            _escape_cell(conflict.topic),
            _escape_cell(conflict.conflicting_document),
            _escape_cell(conflict.superseding_decision),
            _escape_cell(conflict.rationale),
        ]
        for conflict in roadmap.conflicts
    ]
    parts.append(f"## {_H_CONFLICTS}\n")
    parts.append(
        _render_table(
            ["Topic", "Conflicting document", "Superseding decision", "Rationale"],
            conflict_rows,
        )
    )

    # --- Scope statements ----------------------------------------------------
    scope_rows = [
        [_escape_cell(f.name), _escape_cell(getattr(roadmap.scope_statements, f.name))]
        for f in fields(roadmap.scope_statements)
    ]
    parts.append(f"## {_H_SCOPE}\n")
    parts.append(_render_table(["Key", "Statement"], scope_rows))

    return "\n\n".join(parts) + "\n"


def _table_rows_under(md: str, heading: str) -> list[list[str]]:
    """Return the data rows (cell lists) of the Markdown table under ``heading``.

    Locates the ``## <heading>`` line, then the first table that follows it, and
    returns each data row split into trimmed, unescaped cells (header and
    separator rows excluded).

    Raises:
        ValueError: If the heading or its table is missing.
    """
    lines = md.splitlines()
    target = f"## {heading}"

    start = None
    for index, line in enumerate(lines):
        if line.strip() == target:
            start = index
            break
    if start is None:
        raise ValueError(f"missing required section heading {target!r}")

    # Advance to the table's header row, stopping if another section starts.
    i = start + 1
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("## "):
            raise ValueError(f"no table found under heading {target!r}")
        i += 1
    if i + 1 >= len(lines):
        raise ValueError(f"no table found under heading {target!r}")

    # lines[i] is the header row, lines[i + 1] the separator; data starts at i+2.
    rows: list[list[str]] = []
    j = i + 2
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        rows.append(_split_table_row(lines[j]))
        j += 1
    return rows


def parse_markdown(md: str) -> Roadmap:
    """Parse a roadmap Markdown document back into a :class:`Roadmap`.

    Inverse of :func:`render_markdown`:
    ``parse_markdown(render_markdown(r)) == r``. Reads the phase, track-label,
    gate, gate-criteria, conflict, and scope tables and reconstructs the
    aggregate, which re-runs every Task 5 phase-structure invariant on
    construction.

    Args:
        md: A Markdown document produced by :func:`render_markdown`.

    Returns:
        The reconstructed :class:`Roadmap`.

    Raises:
        ValueError: If a required section/table is missing or malformed, or if
            the reconstructed aggregate violates a phase-structure invariant.
    """
    # --- Phases --------------------------------------------------------------
    phases: list[Phase] = []
    for row in _table_rows_under(md, _H_PHASES):
        ordinal, pid, track, title, speech_native, guide, gpu_class, vram = row
        guide_sections = (
            [section for section in guide.split(_GUIDE_SECTION_SEP)] if guide else []
        )
        phases.append(
            Phase(
                ordinal=int(ordinal),
                id=pid,
                track=track,
                title=title,
                is_speech_native=_parse_bool(speech_native),
                guide_sections=guide_sections,
                compute_min_gpu_class=gpu_class,
                compute_min_vram_gb=float(vram),
            )
        )

    # --- Track labels --------------------------------------------------------
    track_labels: dict[str, str] = {}
    for track, label in _table_rows_under(md, _H_TRACK_LABELS):
        track_labels[track] = label

    # --- Gate criteria (grouped per gate, order preserved) -------------------
    entry_by_gate: dict[str, list[GateCriterion]] = {}
    exit_by_gate: dict[str, list[GateCriterion]] = {}
    for gate_id, criteria_set, metric, operator, threshold in _table_rows_under(
        md, _H_GATE_CRITERIA
    ):
        criterion = GateCriterion(
            metric_name=metric, threshold=float(threshold), operator=operator
        )
        bucket = entry_by_gate if criteria_set == "entry" else exit_by_gate
        bucket.setdefault(gate_id, []).append(criterion)

    # --- Gates ---------------------------------------------------------------
    gates: list[Gate] = []
    for gate_id, kind, owner_role, fallback_action in _table_rows_under(md, _H_GATES):
        gates.append(
            Gate(
                id=gate_id,
                kind=kind,
                entry_criteria=entry_by_gate.get(gate_id, []),
                exit_criteria=exit_by_gate.get(gate_id, []),
                owner_role=owner_role,
                fallback_action=fallback_action,
            )
        )

    # --- Conflict register ---------------------------------------------------
    conflicts: list[ConflictEntry] = []
    for topic, document, decision, rationale in _table_rows_under(md, _H_CONFLICTS):
        conflicts.append(
            ConflictEntry(
                topic=topic,
                superseding_decision=decision,
                rationale=rationale,
                conflicting_document=document,
            )
        )

    # --- Scope statements ----------------------------------------------------
    scope_kwargs: dict[str, str] = {}
    for key, statement in _table_rows_under(md, _H_SCOPE):
        scope_kwargs[key] = statement
    scope_statements = ScopeStatements(**scope_kwargs)

    return Roadmap(
        phases=phases,
        track_labels=track_labels,
        gates=gates,
        conflicts=conflicts,
        scope_statements=scope_statements,
    )
