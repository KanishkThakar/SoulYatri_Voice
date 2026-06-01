"""Unit tests for the register exports (Requirements 1.7, 11.3, 11.6).

Plain ``pytest`` example-based tests for the two pure renderers in
:mod:`roadmap.reports.registers_report`:

- :func:`~roadmap.reports.registers_report.render_conflict_register` — the
  Markdown conflict register built from a :class:`~roadmap.roadmap_model.Roadmap`
  aggregate's ``conflicts`` list (Requirement 1.7).
- :func:`~roadmap.reports.registers_report.render_licensing_report` — the
  ``(markdown, json_export)`` pair built from a
  :class:`~roadmap.licensing.LicensingRegister`. The Markdown flags
  redistribution-restricted datasets with their restriction type (Requirement
  11.6) and surfaces unresolved compliance warnings (Requirement 11.3); the
  JSON export round-trips through :mod:`roadmap.serialization`.

Inputs are built from the shared fixtures (``make_valid_roadmap``) and the real
``LicensingRegister``/``Roadmap`` classes — no mocking — so the tests exercise
the genuine rendering + serialization paths. Assertions check substrings
(case-insensitive where reasonable) so they stay robust to exact spacing while
remaining specific.
"""

from __future__ import annotations

from roadmap.licensing import LicensingRegister
from roadmap.models.runtime import ComplianceWarning, LicenseEntry
from roadmap.reports.registers_report import (
    render_conflict_register,
    render_licensing_report,
)
from roadmap.roadmap_model import ConflictEntry, Roadmap
from roadmap.serialization import from_dict
from roadmap.tests.fixtures import make_valid_roadmap


# --- Helpers ---------------------------------------------------------------


def _roadmap_with_conflicts(*conflicts: ConflictEntry) -> Roadmap:
    """Build a valid roadmap carrying the supplied conflict-register entries.

    Reuses the canonical phase list from ``make_valid_roadmap`` (which has no
    conflicts by default) and attaches the given :class:`ConflictEntry` rows so
    the phase-structure invariant stays satisfied.
    """
    return Roadmap(phases=make_valid_roadmap().phases, conflicts=list(conflicts))


# --- render_conflict_register (Requirement 1.7) ----------------------------


def test_conflict_register_renders_topic_document_decision_and_rationale() -> None:
    """A roadmap with a conflict renders its topic/document/decision/rationale.

    Validates: Requirements 1.7
    """
    conflict = ConflictEntry(
        topic="Build custom model up front",
        superseding_decision="Adopt an existing speech-native core first",
        rationale="A clean-room build up front is too slow and too risky",
        conflicting_document="SOULYATRI_MASTER_BIBLE.pdf",
    )
    roadmap = _roadmap_with_conflicts(conflict)

    markdown = render_conflict_register(roadmap)

    # The four recorded fields all appear verbatim in the rendered table.
    assert conflict.topic in markdown
    assert conflict.conflicting_document in markdown
    assert conflict.superseding_decision in markdown
    assert conflict.rationale in markdown
    # The section header column labels are present.
    assert "Topic" in markdown
    assert "Conflicting document" in markdown
    assert "Superseding decision" in markdown
    assert "Rationale" in markdown


def test_conflict_register_renders_multiple_rows() -> None:
    """Every conflict in the register gets its own rendered row.

    Validates: Requirements 1.7
    """
    first = ConflictEntry(
        topic="Up-front custom training",
        superseding_decision="Defer to AMBITIOUS_Track",
        rationale="Lean path ships value sooner",
        conflicting_document="VOX_OMEGA_FINAL_VERIFIED_60_DAY_PLAN.pdf",
    )
    second = ConflictEntry(
        topic="Single monolithic pipeline",
        superseding_decision="Keep Phase_1 fallback concurrent",
        rationale="Fallback de-risks the speech-native migration",
    )
    roadmap = _roadmap_with_conflicts(first, second)

    markdown = render_conflict_register(roadmap)

    for entry in (first, second):
        assert entry.topic in markdown
        assert entry.superseding_decision in markdown
        assert entry.rationale in markdown
    # The first entry's named document is rendered.
    assert first.conflicting_document in markdown


def test_conflict_register_empty_renders_graceful_note() -> None:
    """An empty conflict register renders a graceful note, not an empty table.

    Validates: Requirements 1.7
    """
    roadmap = make_valid_roadmap()  # no conflicts by default
    assert roadmap.conflicts == []

    markdown = render_conflict_register(roadmap)

    # A human-readable note is present and no data rows are rendered.
    assert "no conflicts" in markdown.lower()
    # The table divider row is absent because there is no table.
    assert "| --- |" not in markdown


# --- render_licensing_report: flagging (Requirements 11.3, 11.6) -----------


def test_licensing_report_flags_redistribution_restricted_dataset() -> None:
    """A flagged dataset is shown as redistribution-restricted with its type.

    Validates: Requirements 11.6
    """
    registry = LicensingRegister()
    registry.record_component(
        "voice-corpus", license_id="CC-BY-4.0", constraints=["attribution"]
    )
    registry.flag_dataset("voice-corpus", "subject-consent-required")

    markdown, _json_export = render_licensing_report(registry)

    lower = markdown.lower()
    # The component appears in the report.
    assert "voice-corpus" in markdown
    # It is flagged as redistribution-restricted.
    assert "redistribution restricted" in lower
    # The specific restriction type is recorded in the report.
    assert "subject-consent-required" in markdown


def test_licensing_report_flags_unresolved_warning_for_unrecorded_license() -> None:
    """A failed license recording surfaces an unresolved warning + lists the component.

    Validates: Requirements 11.3
    """
    registry = LicensingRegister()
    # Recording with license_id=None is a failed recording: adoption proceeds
    # but an unresolved ComplianceWarning is retained for the component.
    registry.record_component("mystery-model", license_id=None, constraints=[])

    markdown, _json_export = render_licensing_report(registry)

    lower = markdown.lower()
    # The unresolved-warning section flags the component.
    assert "unresolved" in lower
    assert "mystery-model" in markdown
    # The component is also listed in the adopted-components table with the
    # "unrecorded" license marker (recording failed).
    assert "unrecorded" in lower


def test_licensing_report_lists_exclusion_with_category_and_reason() -> None:
    """A recorded exclusion appears with its category and reason.

    Validates: Requirements 11.4
    """
    registry = LicensingRegister()
    registry.record_exclusion(
        "proprietary-tts",
        "license prohibits commercial redistribution",
        licensing_related=True,
    )

    markdown, _json_export = render_licensing_report(registry)

    lower = markdown.lower()
    # An excluded-candidates section exists and names the candidate.
    assert "excluded" in lower
    assert "proprietary-tts" in markdown
    # Its category (licensing) and reason are shown.
    assert "licensing" in lower
    assert "license prohibits commercial redistribution" in markdown


def test_licensing_report_unresolved_and_restricted_appear_together() -> None:
    """An unresolved warning and a redistribution-restricted dataset both flag.

    This mirrors the task's acceptance scenario: one component recorded without
    a license (unresolved warning) and one dataset flagged as
    redistribution-restricted both appear flagged in the same report.

    Validates: Requirements 11.3, 11.6
    """
    registry = LicensingRegister()
    registry.record_component("unlicensed-model", license_id=None, constraints=[])
    registry.record_component("speech-set", license_id="CC-BY-SA-4.0")
    registry.flag_dataset("speech-set", "no-redistribution")

    markdown, _json_export = render_licensing_report(registry)

    lower = markdown.lower()
    # Unresolved warning is flagged (11.3).
    assert "unresolved" in lower
    assert "unlicensed-model" in markdown
    # Redistribution restriction is flagged with its type (11.6).
    assert "speech-set" in markdown
    assert "redistribution restricted" in lower
    assert "no-redistribution" in markdown


# --- JSON export round-trips through serialization -------------------------


def test_json_export_entries_round_trip_through_serialization() -> None:
    """``export["entries"]`` reconstruct into LicenseEntry objects equal to source.

    Validates: Requirements 11.6
    """
    registry = LicensingRegister()
    registry.record_component(
        "moshiko", license_id="Apache-2.0", constraints=["attribution"]
    )
    registry.record_component("unlicensed-model", license_id=None, constraints=[])
    registry.record_component("speech-set", license_id="CC-BY-SA-4.0")
    registry.flag_dataset("speech-set", "no-redistribution")

    _markdown, json_export = render_licensing_report(registry)

    # Match exported entries to source entries by component_name (order-robust).
    source_by_name = {e.component_name: e for e in registry.entries()}
    assert set(source_by_name) == {
        "moshiko",
        "unlicensed-model",
        "speech-set",
    }

    assert len(json_export["entries"]) == len(source_by_name)
    for exported in json_export["entries"]:
        reconstructed = from_dict(LicenseEntry, exported)
        assert isinstance(reconstructed, LicenseEntry)
        assert reconstructed == source_by_name[reconstructed.component_name]

    # The flagged dataset round-trips with its restriction recorded.
    speech_set = next(
        from_dict(LicenseEntry, e)
        for e in json_export["entries"]
        if e["component_name"] == "speech-set"
    )
    assert speech_set.redistribution_restricted is True
    assert speech_set.restriction_type == "no-redistribution"


def test_json_export_warnings_round_trip_through_serialization() -> None:
    """``export["unresolved_warnings"]`` reconstruct into equal ComplianceWarnings.

    Validates: Requirements 11.3
    """
    registry = LicensingRegister()
    registry.record_component("good-model", license_id="MIT")
    registry.record_component("bad-model", license_id=None)

    _markdown, json_export = render_licensing_report(registry)

    source_warnings = {w.component_name: w for w in registry.unresolved_warnings()}
    # Only the unrecorded-license component carries an unresolved warning.
    assert set(source_warnings) == {"bad-model"}

    assert len(json_export["unresolved_warnings"]) == len(source_warnings)
    for exported in json_export["unresolved_warnings"]:
        reconstructed = from_dict(ComplianceWarning, exported)
        assert isinstance(reconstructed, ComplianceWarning)
        assert reconstructed == source_warnings[reconstructed.component_name]
        assert reconstructed.resolved is False


def test_json_export_has_all_three_sections() -> None:
    """The JSON export carries entries, unresolved_warnings, and exclusions keys."""
    registry = LicensingRegister()
    registry.record_component("kept-model", license_id="Apache-2.0")
    registry.record_component("warn-model", license_id=None)
    registry.record_exclusion(
        "slow-model", "too slow on target hardware", licensing_related=False
    )

    _markdown, json_export = render_licensing_report(registry)

    assert set(json_export) == {"entries", "unresolved_warnings", "exclusions"}
    assert len(json_export["entries"]) == 2
    assert len(json_export["unresolved_warnings"]) == 1
    assert len(json_export["exclusions"]) == 1
    # The exclusion carries its non-licensing category and reason.
    exclusion = json_export["exclusions"][0]
    assert exclusion["component_name"] == "slow-model"
    assert exclusion["category"] == "non-licensing"
    assert exclusion["reason"] == "too slow on target hardware"
