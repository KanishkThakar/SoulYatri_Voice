"""Export the conflict register and the licensing register as reports.

This module is the *presentation* counterpart to two of the roadmap's planning
records:

- the **conflict register** carried on the :class:`~roadmap.roadmap_model.Roadmap`
  aggregate (its ``conflicts`` list of
  :class:`~roadmap.roadmap_model.ConflictEntry`), which records every decision
  that supersedes a strategy PDF together with its topic and rationale
  (Requirement 1.7); and
- the **Licensing Register** (:class:`~roadmap.licensing.LicensingRegister`),
  which holds the :class:`~roadmap.models.runtime.LicenseEntry` recorded for
  every adopted component, the unresolved
  :class:`~roadmap.models.runtime.ComplianceWarning`s, and the
  :class:`~roadmap.licensing.ExclusionRecord` for every excluded candidate
  (Requirements 11.2, 11.4, 11.6).

Both renderers are **pure** functions: they only read the already-computed
planning objects and build strings / plain dicts. They perform no I/O and never
invoke a GPU/model-training run, preserving the import-only / no-training
guarantee shared across the roadmap tooling (Requirement 4.6).

:func:`render_licensing_report` additionally returns a JSON-serializable export
dict built with :func:`roadmap.serialization.to_dict`, so the licensing data
round-trips through the package's serialization layer rather than through an
ad-hoc shape.

Requirements: 1.7, 11.2, 11.4, 11.6.
"""

from __future__ import annotations

from ..licensing import LicensingRegister
from ..roadmap_model import Roadmap
from ..serialization import to_dict

__all__ = [
    "render_conflict_register",
    "render_licensing_report",
]

#: Rendered in a Markdown cell when a value is absent / blank, so an empty cell
#: never silently reads as "no data was expected here".
_EMPTY_CELL = "—"

#: Rendered for a :class:`LicenseEntry` whose ``license_id`` is ``None`` (license
#: recording failed). Pairs with the unresolved compliance warning that the
#: register retains for that component (Requirement 11.3).
_UNRECORDED_LICENSE = "— / unrecorded"


def render_conflict_register(roadmap: Roadmap) -> str:
    """Render the roadmap's conflict register as a Markdown table.

    Emits one row per :class:`~roadmap.roadmap_model.ConflictEntry` in
    ``roadmap.conflicts`` with the conflict topic, the conflicting strategy
    document (when named), the superseding decision, and the rationale
    (Requirement 1.7). The renderer adds no decisions of its own — it reports
    exactly what the register already records.

    Args:
        roadmap: The :class:`Roadmap` aggregate whose ``conflicts`` list is
            rendered.

    Returns:
        A Markdown string. When the register is empty, a short note is returned
        in place of the table so the section renders gracefully.
    """
    lines = ["# Conflict Register", ""]

    if not roadmap.conflicts:
        lines.append("_No conflicts with the strategy documents are recorded._")
        return "\n".join(lines) + "\n"

    lines.append(
        "| Topic | Conflicting document | Superseding decision | Rationale |"
    )
    lines.append("| --- | --- | --- | --- |")
    for entry in roadmap.conflicts:
        lines.append(
            f"| {_cell(entry.topic)} "
            f"| {_cell(entry.conflicting_document)} "
            f"| {_cell(entry.superseding_decision)} "
            f"| {_cell(entry.rationale)} |"
        )

    return "\n".join(lines) + "\n"


def render_licensing_report(registry: LicensingRegister) -> tuple[str, dict]:
    """Render the Licensing Register as Markdown plus a JSON export dict.

    Produces a human-readable Markdown report and a machine-readable export:

    - **Markdown** — a table of every recorded
      :class:`~roadmap.models.runtime.LicenseEntry` (component name, license id
      — rendered as ``"— / unrecorded"`` when ``None`` — constraints,
      intended-use-permitted flag, and the redistribution-restricted flag with
      its restriction type), followed by a section flagging every unresolved
      :class:`~roadmap.models.runtime.ComplianceWarning` and a section listing
      every excluded candidate with its category and reason (Requirements 11.2,
      11.4, 11.6).
    - **JSON export** — a JSON-serializable ``dict`` with ``"entries"``,
      ``"unresolved_warnings"``, and ``"exclusions"`` keys, where the license
      entries and warnings are serialized via
      :func:`roadmap.serialization.to_dict` so the export round-trips through
      the package's serialization layer.

    The renderer is pure: it reports exactly what the ``registry`` already holds
    and makes no compliance decisions of its own.

    Args:
        registry: The :class:`LicensingRegister` to export.

    Returns:
        A ``(markdown, json_export)`` tuple.
    """
    entries = registry.entries()
    warnings = registry.unresolved_warnings()
    exclusions = registry.exclusions()

    markdown = _render_licensing_markdown(entries, warnings, exclusions)
    json_export = {
        "entries": [to_dict(entry) for entry in entries],
        "unresolved_warnings": [to_dict(warning) for warning in warnings],
        "exclusions": [to_dict(record) for record in exclusions],
    }
    return markdown, json_export


# -- Section renderers -------------------------------------------------------


def _render_licensing_markdown(entries, warnings, exclusions) -> str:
    """Assemble the licensing Markdown report from its three sections."""
    lines: list[str] = ["# Licensing Register", ""]
    lines.extend(_render_entries_section(entries))
    lines.append("")
    lines.extend(_render_warnings_section(warnings))
    lines.append("")
    lines.extend(_render_exclusions_section(exclusions))
    return "\n".join(lines) + "\n"


def _render_entries_section(entries) -> list[str]:
    """Render the recorded-component table (Requirements 11.2, 11.6)."""
    lines = ["## Adopted components", ""]
    if not entries:
        lines.append("_No components have been recorded._")
        return lines

    lines.append(
        "| Component | License | Constraints | Intended use permitted "
        "| Redistribution restricted | Restriction type |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for entry in entries:
        license_id = entry.license_id if entry.license_id else _UNRECORDED_LICENSE
        constraints = ", ".join(entry.constraints) if entry.constraints else _EMPTY_CELL
        restriction_type = (
            _cell(entry.restriction_type)
            if entry.redistribution_restricted
            else _EMPTY_CELL
        )
        lines.append(
            f"| {_cell(entry.component_name)} "
            f"| {_cell(license_id)} "
            f"| {constraints} "
            f"| {_yes_no(entry.intended_use_permitted)} "
            f"| {_yes_no(entry.redistribution_restricted)} "
            f"| {restriction_type} |"
        )
    return lines


def _render_warnings_section(warnings) -> list[str]:
    """Render the unresolved-compliance-warning section (Requirement 11.3)."""
    lines = ["## Unresolved compliance warnings", ""]
    if not warnings:
        lines.append("_No unresolved compliance warnings._")
        return lines

    for warning in warnings:
        lines.append(
            f"- ⚠️ {_cell(warning.component_name)}: missing a recognized "
            "open-source license identifier (unresolved)."
        )
    return lines


def _render_exclusions_section(exclusions) -> list[str]:
    """Render the excluded-candidate section with category + reason (11.4)."""
    lines = ["## Excluded candidates", ""]
    if not exclusions:
        lines.append("_No candidates have been excluded._")
        return lines

    lines.append("| Candidate | Category | Reason |")
    lines.append("| --- | --- | --- |")
    for record in exclusions:
        lines.append(
            f"| {_cell(record.component_name)} "
            f"| {_cell(record.category)} "
            f"| {_cell(record.reason)} |"
        )
    return lines


# -- Value formatting --------------------------------------------------------


def _cell(value) -> str:
    """Render a value for a Markdown cell, mapping blank/None to a marker.

    Escapes the pipe character so a value containing ``|`` cannot break the
    table layout.
    """
    if value is None:
        return _EMPTY_CELL
    text = str(value).strip()
    if not text:
        return _EMPTY_CELL
    return text.replace("|", "\\|")


def _yes_no(flag: bool) -> str:
    """Render a boolean flag as ``yes`` / ``no``."""
    return "yes" if flag else "no"
