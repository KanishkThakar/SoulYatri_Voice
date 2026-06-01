"""Cross-check the narrative ``ROADMAP.md`` against the structured ``Roadmap``.

Task 23 authored the narrative planning artifact (``roadmap/ROADMAP.md``) and
Task 29 encoded the same plan as structured data
(``roadmap/data/roadmap_data.yaml`` → :func:`roadmap.roadmap_io.load_roadmap`).
Because both describe one plan, they must agree. This module is the
**consistency checker** that compares the two representations and reports every
divergence as a structured :class:`Finding`.

The checker compares the parts of the plan that appear in *both* artifacts:

- **Phases** — ordinal / id / track of each phase in the narrative
  "Ordered phase table" (Section 1.1) against ``roadmap.phases``
  (Requirement 1.1).
- **Track labels** — the LEAN-"primary" / AMBITIOUS-"optional" labels in the
  narrative phase table against ``roadmap.track_labels`` (Requirement 1.2).
- **Decision_Gate ``G1``** — the owner role and fallback action stated in the
  narrative Section 3 against the structured ``G1`` gate (Requirements 1.1,
  1.2).
- **Conflict register** — every topic / conflicting-document / superseding-
  decision / rationale row in the narrative Section 4 against
  ``roadmap.conflicts`` (Requirements 1.7, 12.1).
- **Selection-weight table** — the six weighted criteria in the narrative
  Section 5.3 against :data:`roadmap.models.selection.SELECTION_WEIGHTS`,
  including that the weights sum to 100 (Requirements 1.1, 12.1).

Parsing is intentionally **tolerant**: the narrative is prose plus
GitHub-flavoured Markdown tables, so the checker locates each table by the
text of its header columns (not by position in the document), reads cells by
header name, and normalizes cell text (stripping backticks, ``**`` bold
markers, and redundant whitespace, and comparing case-insensitively) before
comparing. It never does a whole-document string equality.

The module is pure Python (standard library only). It imports no GPU/model
-training framework and invokes no GPU/training run, preserving the package's
import-only / no-training guarantee (Requirement 4.6).

Validates: Requirements 1.1, 1.2, 1.7, 12.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .models.selection import SELECTION_WEIGHTS
from .paths import ROADMAP_MD_PATH
from .roadmap_io import load_roadmap
from .roadmap_model import Roadmap

__all__ = [
    "Finding",
    "check_consistency",
    "render_consistency_report",
]

#: The structured-model id of the single LEAN → AMBITIOUS decision gate whose
#: owner role and fallback action are cross-checked against the narrative.
DECISION_GATE_ID = "G1"


@dataclass
class Finding:
    """One reported divergence between the narrative and the structured model.

    Attributes:
        category: A short machine-readable category, e.g. ``"phase_track"`` or
            ``"conflict_missing"``, identifying the kind of divergence.
        detail: A human-readable description of the specific divergence.
        expected: The value expected from the structured :class:`Roadmap`
            (the source of truth), when applicable.
        actual: The value found in the narrative ``ROADMAP.md``, when
            applicable.
    """

    category: str
    detail: str
    expected: Optional[str] = None
    actual: Optional[str] = None


# ===========================================================================
# Markdown table extraction helpers (tolerant GFM parsing)
# ===========================================================================


def _is_table_row(line: str) -> bool:
    """Whether ``line`` looks like a Markdown table row (``| ... |``)."""
    return line.strip().startswith("|")


def _is_separator_row(line: str) -> bool:
    """Whether ``line`` is a table header/body separator (``|---|---|``)."""
    s = line.strip()
    if not s.startswith("|"):
        return False
    body = s.strip("|")
    return bool(body) and set(body) <= set("-:| \t") and "-" in body


def _split_row(line: str) -> list[str]:
    """Split one Markdown table row into trimmed cell values."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def _extract_tables(md: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return ``(headers, rows)`` for every GFM table in ``md``.

    A table is a header row immediately followed by a separator row, then zero
    or more body rows. Cells are returned trimmed but otherwise raw (escaping is
    not used in the narrative tables).
    """
    lines = md.splitlines()
    tables: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    n = len(lines)
    while i < n:
        if (
            _is_table_row(lines[i])
            and i + 1 < n
            and _is_separator_row(lines[i + 1])
        ):
            headers = _split_row(lines[i])
            rows: list[list[str]] = []
            j = i + 2
            while j < n and _is_table_row(lines[j]) and not _is_separator_row(lines[j]):
                rows.append(_split_row(lines[j]))
                j += 1
            tables.append((headers, rows))
            i = j
        else:
            i += 1
    return tables


def _norm(text: str) -> str:
    """Strip Markdown decoration (backticks, ``**``) and surrounding space."""
    return text.replace("`", "").replace("**", "").strip()


def _norm_key(text: str) -> str:
    """Normalize for equality comparison: decoration-free, lower, single-space."""
    cleaned = _norm(text)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _parse_int(text: str) -> Optional[int]:
    """Parse the first run of digits from a cell, or ``None`` if absent."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _find_table(
    tables: list[tuple[list[str], list[list[str]]]],
    *required_header_substrings: str,
) -> Optional[tuple[list[str], list[list[str]]]]:
    """Return the first table whose headers contain every required substring.

    Matching is case-insensitive and decoration-free, so a table is located by
    *what its columns mean* rather than by its position in the document.
    """
    wanted = [s.lower() for s in required_header_substrings]
    for headers, rows in tables:
        norm_headers = [_norm_key(h) for h in headers]
        if all(any(w in h for h in norm_headers) for w in wanted):
            return headers, rows
    return None


def _column_index(headers: list[str], substring: str) -> Optional[int]:
    """Index of the first header containing ``substring`` (case-insensitive)."""
    needle = substring.lower()
    for idx, header in enumerate(headers):
        if needle in _norm_key(header):
            return idx
    return None


# ===========================================================================
# Section / prose extraction helpers
# ===========================================================================


def _section_text(md: str, *heading_substrings: str) -> str:
    """Return the text of the first ``## `` section whose heading matches.

    The section runs from its ``## `` heading up to (but not including) the next
    ``## `` heading. Returns an empty string when no heading matches every
    requested substring.
    """
    lines = md.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.startswith("## ") and all(s in line for s in heading_substrings):
            start = idx
            break
    if start is None:
        return ""
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return "\n".join(lines[start:end])


def _labelled_value(section: str, label: str) -> Optional[str]:
    """Return the text after the first ``:`` following ``label`` in a line.

    Markdown bold/backtick decoration is stripped before matching, so a line
    like ``- **Owner role (exactly one):** **ML Lead** — ...`` yields
    ``"ML Lead — ..."``.
    """
    needle = label.lower()
    for raw in section.splitlines():
        clean = raw.replace("**", "").replace("`", "")
        pos = clean.lower().find(needle)
        if pos == -1:
            continue
        colon = clean.find(":", pos)
        if colon == -1:
            continue
        return clean[colon + 1 :].strip()
    return None


# ===========================================================================
# Individual checks
# ===========================================================================


def _check_phases(roadmap: Roadmap, md: str) -> list[Finding]:
    """Compare phase ordinal/id/track between the model and the narrative."""
    findings: list[Finding] = []
    tables = _extract_tables(md)
    table = _find_table(tables, "ordinal", "id", "track label")
    if table is None:
        return [
            Finding(
                category="phase_table_missing",
                detail=(
                    "ROADMAP.md has no ordered phase table (expected a table "
                    "with Ordinal / ID / Track / Track label columns)."
                ),
            )
        ]

    headers, rows = table
    i_ord = _column_index(headers, "ordinal")
    i_id = _column_index(headers, "id")
    i_track = _column_index(headers, "track")  # first "Track" header (not label)

    narrative: dict[int, tuple[str, str]] = {}
    for row in rows:
        if i_ord is None or i_id is None or i_track is None:
            break
        if max(i_ord, i_id, i_track) >= len(row):
            continue
        ordinal = _parse_int(row[i_ord])
        if ordinal is None:
            continue
        narrative[ordinal] = (_norm(row[i_id]), _norm(row[i_track]))

    for phase in roadmap.phases:
        if phase.ordinal not in narrative:
            findings.append(
                Finding(
                    category="phase_missing",
                    detail=(
                        f"phase ordinal {phase.ordinal} ({phase.id}) is in the "
                        "structured model but absent from the narrative phase table."
                    ),
                    expected=f"ordinal {phase.ordinal}: {phase.id} / {phase.track}",
                    actual=None,
                )
            )
            continue
        nid, ntrack = narrative[phase.ordinal]
        if _norm_key(nid) != _norm_key(phase.id):
            findings.append(
                Finding(
                    category="phase_id",
                    detail=(
                        f"phase id mismatch at ordinal {phase.ordinal}."
                    ),
                    expected=phase.id,
                    actual=nid,
                )
            )
        if _norm_key(ntrack) != _norm_key(phase.track):
            findings.append(
                Finding(
                    category="phase_track",
                    detail=(
                        f"phase track mismatch at ordinal {phase.ordinal} "
                        f"({phase.id})."
                    ),
                    expected=phase.track,
                    actual=ntrack,
                )
            )

    structured_ordinals = {p.ordinal for p in roadmap.phases}
    for ordinal in sorted(narrative):
        if ordinal not in structured_ordinals:
            nid, ntrack = narrative[ordinal]
            findings.append(
                Finding(
                    category="phase_extra",
                    detail=(
                        f"narrative phase table has ordinal {ordinal} ({nid}) "
                        "with no matching structured phase."
                    ),
                    expected=None,
                    actual=f"ordinal {ordinal}: {nid} / {ntrack}",
                )
            )
    return findings


def _check_track_labels(roadmap: Roadmap, md: str) -> list[Finding]:
    """Compare the LEAN/AMBITIOUS labels in the phase table to the model."""
    findings: list[Finding] = []
    tables = _extract_tables(md)
    table = _find_table(tables, "ordinal", "track label")
    if table is None:
        return [
            Finding(
                category="track_label_table_missing",
                detail="ROADMAP.md phase table has no 'Track label' column.",
            )
        ]

    headers, rows = table
    i_track = _column_index(headers, "track")
    i_label = _column_index(headers, "track label")

    narrative_labels: dict[str, set[str]] = {}
    for row in rows:
        if i_track is None or i_label is None:
            break
        if max(i_track, i_label) >= len(row):
            continue
        track = _norm(row[i_track])
        label = _norm(row[i_label])
        if not track or not label:
            continue
        narrative_labels.setdefault(_norm_key(track), set()).add(label)

    for track, expected_label in roadmap.track_labels.items():
        seen = narrative_labels.get(_norm_key(track))
        if not seen:
            findings.append(
                Finding(
                    category="track_label_missing",
                    detail=(
                        f"track {track!r} has no label in the narrative phase table."
                    ),
                    expected=expected_label,
                    actual=None,
                )
            )
            continue
        normalized_seen = {_norm_key(label) for label in seen}
        if _norm_key(expected_label) not in normalized_seen:
            findings.append(
                Finding(
                    category="track_label",
                    detail=(
                        f"track {track!r} label mismatch in the narrative phase table."
                    ),
                    expected=expected_label,
                    actual=", ".join(sorted(seen)),
                )
            )
    return findings


def _check_decision_gate(roadmap: Roadmap, md: str) -> list[Finding]:
    """Compare the G1 owner role and fallback action to the narrative."""
    findings: list[Finding] = []
    gate = next((g for g in roadmap.gates if g.id == DECISION_GATE_ID), None)
    section = _section_text(md, "Decision_Gate", DECISION_GATE_ID)

    if gate is None:
        if section:
            findings.append(
                Finding(
                    category="gate_extra",
                    detail=(
                        f"narrative describes Decision_Gate {DECISION_GATE_ID} "
                        "but the structured model has no such gate."
                    ),
                )
            )
        return findings

    if not section:
        return [
            Finding(
                category="gate_section_missing",
                detail=(
                    f"structured model defines gate {DECISION_GATE_ID} but the "
                    "narrative has no matching Decision_Gate section."
                ),
                expected=DECISION_GATE_ID,
            )
        ]

    owner_value = _labelled_value(section, "owner role")
    if owner_value is not None:
        # Trim a trailing dash-introduced clause, e.g. "ML Lead — the single...".
        owner_value = re.split(r"\s[—–-]\s", owner_value, maxsplit=1)[0].strip()
    if owner_value is None or _norm_key(owner_value) != _norm_key(gate.owner_role):
        findings.append(
            Finding(
                category="gate_owner",
                detail=f"Decision_Gate {DECISION_GATE_ID} owner role mismatch.",
                expected=gate.owner_role,
                actual=owner_value,
            )
        )

    fallback_value = _labelled_value(section, "fallback action")
    if fallback_value is not None:
        fallback_value = fallback_value.rstrip(". ").strip()
    if fallback_value is None or _norm_key(fallback_value) != _norm_key(
        gate.fallback_action
    ):
        findings.append(
            Finding(
                category="gate_fallback",
                detail=f"Decision_Gate {DECISION_GATE_ID} fallback action mismatch.",
                expected=gate.fallback_action,
                actual=fallback_value,
            )
        )
    return findings


def _check_conflicts(roadmap: Roadmap, md: str) -> list[Finding]:
    """Compare every conflict-register row to ``roadmap.conflicts``."""
    findings: list[Finding] = []
    tables = _extract_tables(md)
    table = _find_table(tables, "superseding decision", "rationale")
    if table is None:
        return [
            Finding(
                category="conflict_table_missing",
                detail="ROADMAP.md has no conflict-register table.",
            )
        ]

    headers, rows = table
    i_topic = _column_index(headers, "topic")
    i_doc = _column_index(headers, "conflicting")
    i_decision = _column_index(headers, "superseding")
    i_rationale = _column_index(headers, "rationale")

    narrative_rows: dict[str, dict[str, str]] = {}
    for row in rows:
        if i_topic is None or i_topic >= len(row):
            continue
        topic = _norm(row[i_topic])
        if not topic:
            continue
        narrative_rows[_norm_key(topic)] = {
            "topic": topic,
            "document": _norm(row[i_doc]) if i_doc is not None and i_doc < len(row) else "",
            "decision": _norm(row[i_decision])
            if i_decision is not None and i_decision < len(row)
            else "",
            "rationale": _norm(row[i_rationale])
            if i_rationale is not None and i_rationale < len(row)
            else "",
        }

    structured_keys: set[str] = set()
    for conflict in roadmap.conflicts:
        key = _norm_key(conflict.topic)
        structured_keys.add(key)
        narrative = narrative_rows.get(key)
        if narrative is None:
            findings.append(
                Finding(
                    category="conflict_missing",
                    detail=(
                        f"conflict-register row for topic {conflict.topic!r} is in "
                        "the structured model but absent from the narrative."
                    ),
                    expected=conflict.topic,
                    actual=None,
                )
            )
            continue
        if conflict.conflicting_document and _norm_key(
            conflict.conflicting_document
        ) != _norm_key(narrative["document"]):
            findings.append(
                Finding(
                    category="conflict_document",
                    detail=(
                        f"conflict {conflict.topic!r}: conflicting-document mismatch."
                    ),
                    expected=conflict.conflicting_document,
                    actual=narrative["document"],
                )
            )
        if _norm_key(conflict.superseding_decision) != _norm_key(
            narrative["decision"]
        ):
            findings.append(
                Finding(
                    category="conflict_decision",
                    detail=(
                        f"conflict {conflict.topic!r}: superseding-decision mismatch."
                    ),
                    expected=conflict.superseding_decision,
                    actual=narrative["decision"],
                )
            )
        if _norm_key(conflict.rationale) != _norm_key(narrative["rationale"]):
            findings.append(
                Finding(
                    category="conflict_rationale",
                    detail=f"conflict {conflict.topic!r}: rationale mismatch.",
                    expected=conflict.rationale,
                    actual=narrative["rationale"],
                )
            )

    for key, narrative in narrative_rows.items():
        if key not in structured_keys:
            findings.append(
                Finding(
                    category="conflict_extra",
                    detail=(
                        f"narrative conflict-register row {narrative['topic']!r} has "
                        "no matching structured conflict entry."
                    ),
                    expected=None,
                    actual=narrative["topic"],
                )
            )
    return findings


def _check_selection_weights(md: str) -> list[Finding]:
    """Compare the narrative selection-weight table to ``SELECTION_WEIGHTS``."""
    findings: list[Finding] = []
    tables = _extract_tables(md)
    table = _find_table(tables, "criterion", "weight")
    if table is None:
        return [
            Finding(
                category="selection_weight_table_missing",
                detail="ROADMAP.md has no weighted selection-criteria table.",
            )
        ]

    headers, rows = table
    i_crit = _column_index(headers, "criterion")
    i_weight = _column_index(headers, "weight")

    narrative_weights: dict[str, int] = {}
    for row in rows:
        if i_crit is None or i_weight is None:
            break
        if max(i_crit, i_weight) >= len(row):
            continue
        criterion = _norm_key(row[i_crit])
        weight = _parse_int(row[i_weight])
        if criterion in SELECTION_WEIGHTS and weight is not None:
            narrative_weights[criterion] = weight

    for criterion, expected_weight in SELECTION_WEIGHTS.items():
        if criterion not in narrative_weights:
            findings.append(
                Finding(
                    category="selection_weight_missing",
                    detail=(
                        f"selection criterion {criterion!r} is missing from the "
                        "narrative selection-weight table."
                    ),
                    expected=str(expected_weight),
                    actual=None,
                )
            )
        elif narrative_weights[criterion] != expected_weight:
            findings.append(
                Finding(
                    category="selection_weight_mismatch",
                    detail=f"selection weight mismatch for {criterion!r}.",
                    expected=str(expected_weight),
                    actual=str(narrative_weights[criterion]),
                )
            )

    narrative_total = sum(narrative_weights.values())
    if narrative_weights and narrative_total != 100:
        findings.append(
            Finding(
                category="selection_weight_sum",
                detail=(
                    "narrative selection-weight table does not sum to 100."
                ),
                expected="100",
                actual=str(narrative_total),
            )
        )
    return findings


# ===========================================================================
# Public API
# ===========================================================================


def check_consistency(
    roadmap: Optional[Roadmap] = None,
    roadmap_md_path: Union[str, Path] = ROADMAP_MD_PATH,
    *,
    roadmap_md: Optional[str] = None,
) -> list[Finding]:
    """Compare the narrative ``ROADMAP.md`` against the structured ``Roadmap``.

    Loads the structured roadmap (via :func:`roadmap.roadmap_io.load_roadmap`
    when ``roadmap`` is not supplied) and the narrative artifact (from
    ``roadmap_md_path``, or from ``roadmap_md`` when given), then cross-checks
    the parts present in both: phase ordinals/ids/tracks, the
    LEAN-"primary"/AMBITIOUS-"optional" track labels, Decision_Gate ``G1``'s
    owner role and fallback action, the conflict-register rows, and the
    selection-weight table (including that the weights sum to 100).

    Args:
        roadmap: The structured roadmap to check against. When ``None`` the
            canonical roadmap is loaded with :func:`load_roadmap`.
        roadmap_md_path: Path to the narrative ``ROADMAP.md``. Defaults to
            :data:`roadmap.paths.ROADMAP_MD_PATH`. Ignored when ``roadmap_md``
            is given.
        roadmap_md: Optional narrative Markdown text supplied directly (useful
            for tests). Takes precedence over ``roadmap_md_path`` when not
            ``None``.

    Returns:
        An empty list when the narrative and the structured model agree on every
        checked element; otherwise one :class:`Finding` per divergence.
    """
    if roadmap is None:
        roadmap = load_roadmap()
    if roadmap_md is None:
        roadmap_md = Path(roadmap_md_path).read_text(encoding="utf-8")

    findings: list[Finding] = []
    findings.extend(_check_phases(roadmap, roadmap_md))
    findings.extend(_check_track_labels(roadmap, roadmap_md))
    findings.extend(_check_decision_gate(roadmap, roadmap_md))
    findings.extend(_check_conflicts(roadmap, roadmap_md))
    findings.extend(_check_selection_weights(roadmap_md))
    return findings


def render_consistency_report(findings: list[Finding]) -> str:
    """Render a human-readable report from a list of :class:`Finding`.

    Args:
        findings: The findings returned by :func:`check_consistency`.

    Returns:
        A Markdown string. When ``findings`` is empty, a short confirmation that
        the narrative and the structured model are consistent is returned.
    """
    if not findings:
        return (
            "# Roadmap consistency report\n\n"
            "✅ The narrative ROADMAP.md and the structured Roadmap are "
            "consistent — no divergences found.\n"
        )

    lines = [
        "# Roadmap consistency report",
        "",
        f"❌ Found {len(findings)} divergence(s) between ROADMAP.md and the "
        "structured Roadmap:",
        "",
        "| # | Category | Detail | Expected (structured) | Actual (narrative) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, finding in enumerate(findings, start=1):
        expected = "—" if finding.expected is None else str(finding.expected)
        actual = "—" if finding.actual is None else str(finding.actual)
        lines.append(
            f"| {index} "
            f"| {_report_cell(finding.category)} "
            f"| {_report_cell(finding.detail)} "
            f"| {_report_cell(expected)} "
            f"| {_report_cell(actual)} |"
        )
    return "\n".join(lines) + "\n"


def _report_cell(value: str) -> str:
    """Escape a value for safe inclusion in a Markdown report table cell."""
    return str(value).replace("|", "\\|").strip()
