"""Licensing Register decision logic for the speech-native voice roadmap.

The :class:`LicensingRegister` is the maintained record of every adopted model,
dataset, and tool together with its open-source license and usage constraints.
It is one of the roadmap's pure decision-logic components (see the "Licensing
Register" section of ``design.md``) and is consumed downstream by both the
``GateEvaluator`` (which blocks a release when an unresolved warning or a
prohibiting license is present) and the Hinglish Data Engine (which must not
redistribute content sourced from a flagged dataset).

Responsibilities (Requirement 11):

- Record ``{component_name, license_id, constraints}`` **before use** for every
  adopted component; only *recognized* open-source license identifiers are
  permitted (11.1, 11.2).
- If license recording fails — the supplied ``license_id`` is ``None`` or is not
  a recognized OSS identifier — adoption is still allowed to proceed, but an
  unresolved :class:`~roadmap.models.runtime.ComplianceWarning` identifying the
  component is raised and retained until the missing license information is
  recorded (11.3).
- Record every excluded Candidate_Model with its exclusion reason, categorised
  as *licensing* or *non-licensing* (performance/compatibility) (11.4).
- Flag any dataset whose terms restrict redistribution or require subject
  consent, recording the specific restriction type (11.6).
- Expose :meth:`redistribution_allowed`, used by the Hinglish Data Engine, which
  returns ``False`` while a dataset remains flagged as restricting
  redistribution / requiring consent, until the restriction is satisfied (11.8).
- Expose queries for unresolved warnings and for whether any adopted component
  carries a license prohibiting its intended use, used by the ``GateEvaluator``
  at every Launch_Gate review (11.5, 11.7).

This module contains no I/O and no GPU/training work; it is a pure in-memory
register operating on the dataclasses defined in ``roadmap/models/runtime.py``.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.6, 11.8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .models.runtime import ComplianceWarning, LicenseEntry

__all__ = [
    "RECOGNIZED_OSS_LICENSES",
    "ExclusionCategory",
    "ExclusionRecord",
    "LicensingRegister",
]


#: The set of recognized open-source license identifiers (SPDX-style) the
#: register accepts as a valid recording. Anything outside this set — including
#: ``None`` — counts as a *failed* license recording and retains an unresolved
#: compliance warning (Requirement 11.1, 11.3). This is intentionally a curated
#: allow-list rather than a free-form string so that adoption can never silently
#: proceed on an unrecognised or fabricated identifier.
RECOGNIZED_OSS_LICENSES: frozenset[str] = frozenset(
    {
        # Permissive
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Zlib",
        "Unlicense",
        "CC0-1.0",
        # Weak copyleft
        "MPL-2.0",
        "LGPL-2.1",
        "LGPL-3.0",
        "EPL-2.0",
        # Strong copyleft
        "GPL-2.0",
        "GPL-3.0",
        "AGPL-3.0",
        # Creative Commons (datasets/docs)
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
    }
)

#: Categories used when recording a Candidate_Model exclusion (Requirement
#: 11.4). ``"licensing"`` covers a license that prohibits the intended use;
#: ``"non-licensing"`` covers everything else (performance, compatibility,
#: missing weights, hardware limits).
ExclusionCategory = Literal["licensing", "non-licensing"]


@dataclass
class ExclusionRecord:
    """A record of an excluded Candidate_Model and why it was excluded.

    Attributes:
        component_name: The excluded Candidate_Model identifier.
        reason: The human-readable exclusion reason.
        category: ``"licensing"`` when the exclusion is because of a license
            prohibiting the intended use, otherwise ``"non-licensing"`` (for
            performance/compatibility/hardware reasons).
    """

    component_name: str
    reason: str
    category: ExclusionCategory


class LicensingRegister:
    """In-memory register of adopted components, exclusions, and warnings.

    All recording happens *before* a component is used in any build, so every
    :class:`LicenseEntry` produced here has ``recorded_before_use=True``. A
    record whose ``license_id`` could not be resolved to a recognized OSS
    identifier is still stored (adoption proceeds) but with ``license_id=None``
    and an accompanying unresolved :class:`ComplianceWarning` (Requirement
    11.3).
    """

    def __init__(self) -> None:
        # component_name -> LicenseEntry (latest recording wins)
        self._entries: dict[str, LicenseEntry] = {}
        # component_name -> ComplianceWarning (resolved flag flips in place)
        self._warnings: dict[str, ComplianceWarning] = {}
        # component_name -> ExclusionRecord
        self._exclusions: dict[str, ExclusionRecord] = {}

    # -- Recording -----------------------------------------------------------

    def record_component(
        self,
        component_name: str,
        license_id: Optional[str],
        constraints: Optional[list[str]] = None,
        *,
        intended_use_permitted: bool = True,
        redistribution_restricted: bool = False,
        restriction_type: Optional[str] = None,
    ) -> LicenseEntry:
        """Record a component's license before it is used in any build.

        Stores ``{component_name, license_id, constraints}`` plus the
        intended-use and redistribution flags. ``license_id`` is accepted only
        when it is a recognized OSS identifier (see
        :data:`RECOGNIZED_OSS_LICENSES`); any other value — including ``None``
        or an unrecognised string — is treated as a *failed* license recording:
        the entry is still stored with ``license_id=None`` (adoption proceeds)
        and an unresolved :class:`ComplianceWarning` is raised and retained for
        the component until a recognized identifier is recorded (Requirements
        11.1, 11.2, 11.3).

        Re-recording the same component with a recognized identifier resolves
        any outstanding warning for that component.

        Args:
            component_name: The adopted model/dataset/tool name. Must be a
                non-empty string.
            license_id: The OSS license identifier, or ``None`` if unknown.
            constraints: Commercial-use / attribution constraints; defaults to
                an empty list.
            intended_use_permitted: Whether the license permits the intended
                use. ``False`` marks a *prohibiting* license (Requirement 11.7).
            redistribution_restricted: Whether the component's terms restrict
                redistribution or require subject consent (Requirement 11.6).
            restriction_type: The specific restriction type when
                ``redistribution_restricted`` is ``True``.

        Returns:
            The stored :class:`LicenseEntry`.

        Raises:
            ValueError: If ``component_name`` is empty or blank.
        """
        if not isinstance(component_name, str) or not component_name.strip():
            raise ValueError("component_name must be a non-empty string")

        recognized = license_id is not None and license_id in RECOGNIZED_OSS_LICENSES
        recorded_license = license_id if recognized else None

        entry = LicenseEntry(
            component_name=component_name,
            license_id=recorded_license,
            constraints=list(constraints) if constraints else [],
            intended_use_permitted=intended_use_permitted,
            recorded_before_use=True,
            redistribution_restricted=redistribution_restricted,
            restriction_type=restriction_type,
        )
        self._entries[component_name] = entry

        if recorded_license is None:
            # License recording failed: retain an unresolved warning (11.3).
            self._warnings[component_name] = ComplianceWarning(
                component_name=component_name, resolved=False
            )
        else:
            # Recording succeeded: any prior warning is now resolved (11.3).
            existing = self._warnings.get(component_name)
            if existing is not None:
                existing.resolved = True

        return entry

    def flag_dataset(self, component_name: str, restriction_type: str) -> LicenseEntry:
        """Flag a dataset as restricting redistribution / requiring consent.

        Records the specific ``restriction_type`` on the dataset's
        :class:`LicenseEntry` (Requirement 11.6). While the flag is set,
        :meth:`redistribution_allowed` returns ``False`` for the dataset
        (Requirement 11.8) until :meth:`satisfy_restriction` clears it.

        If the dataset has not been recorded yet, a minimal entry is created
        with an unresolved compliance warning for its missing license info, so
        the flag is never silently lost.

        Args:
            component_name: The dataset name.
            restriction_type: The specific restriction, e.g.
                ``"no-redistribution"`` or ``"subject-consent-required"``. Must
                be a non-empty string.

        Returns:
            The updated (or newly created) :class:`LicenseEntry`.

        Raises:
            ValueError: If ``restriction_type`` is empty or blank.
        """
        if not isinstance(restriction_type, str) or not restriction_type.strip():
            raise ValueError("restriction_type must be a non-empty string")

        entry = self._entries.get(component_name)
        if entry is None:
            # Flagging a not-yet-recorded dataset still records the restriction;
            # the missing license recording retains an unresolved warning.
            entry = self.record_component(component_name, license_id=None, constraints=[])

        entry.redistribution_restricted = True
        entry.restriction_type = restriction_type
        return entry

    def satisfy_restriction(self, component_name: str) -> None:
        """Mark a dataset's redistribution/consent restriction as satisfied.

        Clears the redistribution flag so :meth:`redistribution_allowed` returns
        ``True`` again (Requirement 11.8). The recorded ``restriction_type`` is
        preserved on the entry for audit. No-op if the component is unknown.
        """
        entry = self._entries.get(component_name)
        if entry is not None:
            entry.redistribution_restricted = False

    def record_exclusion(
        self,
        component_name: str,
        reason: str,
        *,
        licensing_related: bool,
    ) -> ExclusionRecord:
        """Record an excluded Candidate_Model and its exclusion reason.

        Captures the exclusion and whether it was for a *licensing* reason (a
        license prohibiting the intended use) or a *non-licensing* reason such
        as performance or compatibility (Requirement 11.4).

        Args:
            component_name: The excluded Candidate_Model identifier. Must be a
                non-empty string.
            reason: The human-readable exclusion reason. Must be non-empty.
            licensing_related: ``True`` if excluded for a licensing reason,
                ``False`` for a non-licensing reason.

        Returns:
            The stored :class:`ExclusionRecord`.

        Raises:
            ValueError: If ``component_name`` or ``reason`` is empty or blank.
        """
        if not isinstance(component_name, str) or not component_name.strip():
            raise ValueError("component_name must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")

        category: ExclusionCategory = "licensing" if licensing_related else "non-licensing"
        record = ExclusionRecord(
            component_name=component_name, reason=reason, category=category
        )
        self._exclusions[component_name] = record
        return record

    def resolve_warning(self, component_name: str) -> None:
        """Resolve any outstanding compliance warning for a component.

        Marks the component's warning ``resolved=True`` in place. No-op when no
        warning exists for the component. Note that a warning is only truly
        cleared once the missing license info is recorded via
        :meth:`record_component`; this method exists for explicit resolution
        bookkeeping.
        """
        warning = self._warnings.get(component_name)
        if warning is not None:
            warning.resolved = True

    # -- Queries -------------------------------------------------------------

    def redistribution_allowed(self, component_name: str) -> bool:
        """Return whether content from ``component_name`` may be redistributed.

        Used by the Hinglish Data Engine: returns ``False`` while the component
        is flagged as restricting redistribution or requiring subject consent,
        and ``True`` once the restriction is satisfied or when the component was
        never flagged (Requirement 11.8). An unknown component is treated as
        having no recorded restriction and is therefore allowed.
        """
        entry = self._entries.get(component_name)
        if entry is None:
            return True
        return not entry.redistribution_restricted

    def unresolved_warnings(self) -> list[ComplianceWarning]:
        """Return the list of currently unresolved compliance warnings (11.3)."""
        return [w for w in self._warnings.values() if not w.resolved]

    def has_unresolved_warnings(self) -> bool:
        """Return ``True`` if any compliance warning is unresolved (11.7)."""
        return any(not w.resolved for w in self._warnings.values())

    def has_prohibiting_license(self) -> bool:
        """Return ``True`` if any adopted component prohibits its intended use.

        Used by the ``GateEvaluator`` at every Launch_Gate review: a recorded
        entry with ``intended_use_permitted=False`` is a prohibiting license
        and blocks the release (Requirements 11.5, 11.7).
        """
        return any(not e.intended_use_permitted for e in self._entries.values())

    def get_entry(self, component_name: str) -> Optional[LicenseEntry]:
        """Return the recorded :class:`LicenseEntry` for a component, if any."""
        return self._entries.get(component_name)

    def entries(self) -> list[LicenseEntry]:
        """Return all recorded license entries."""
        return list(self._entries.values())

    def exclusions(self) -> list[ExclusionRecord]:
        """Return all recorded Candidate_Model exclusions (11.4)."""
        return list(self._exclusions.values())
