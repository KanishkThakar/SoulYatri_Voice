"""Render a consent-log and watermark-compliance safety-audit report.

This module turns the *state* of a :class:`~roadmap.safety_guard.SafetyGuard`
(plus, optionally, the watermarking and crisis-handling decisions it has
produced) into a human-readable Markdown **safety audit**. It is the
presentation counterpart to the safety decision logic and intentionally adds
**no** decision-making of its own: it reports exactly what the guard's consent
log, the supplied :class:`~roadmap.safety_guard.EmissionResult` records, and the
supplied :class:`~roadmap.safety_guard.CrisisDecision` records already say.

What the report contains (Requirements 10.1, 10.2, 10.4, 10.5, 10.6)
--------------------------------------------------------------------
- **Consent log** (Requirement 10.6): the count of product-facing voices in use
  and a table of consent-log entries — ``speaker_id``, ``permitted_use_scope``,
  ``timestamp`` — confirming every retained entry carries the three required
  fields. Pulled from :meth:`SafetyGuard.consent_log`.
- **Watermark compliance** (Requirement 10.2): when ``emission_results`` are
  supplied, the count of compliant/emitted outputs vs. withheld (non-compliant)
  outputs, the per-path breakdown, and an explicit confirmation that every
  *emitted* output carried a detected watermark. When none are supplied, the
  watermark policy is stated (every output on every path is watermarked;
  outputs whose watermark cannot be verified are withheld).
- **Crisis handling** (Requirements 10.4, 10.5): when ``crisis_decisions`` are
  supplied, the tally of decisions that triggered (crisis-support guidance
  surfaced **and** the turn flagged for human review). When none are supplied,
  the crisis policy is stated (a score at or above the decision threshold
  surfaces guidance *and* flags for review).

This module performs no I/O and no GPU/training work; it is a pure string
renderer operating on already-computed planning objects (Requirements 4.6,
12.4, 12.5).

Requirements: 10.1, 10.2, 10.4, 10.5, 10.6.
"""

from __future__ import annotations

from typing import Optional

from ..safety_guard import (
    CrisisDecision,
    EmissionResult,
    SafetyGuard,
)

__all__ = [
    "render_safety_audit",
]


def render_safety_audit(
    guard: SafetyGuard,
    *,
    emission_results: Optional[list[EmissionResult]] = None,
    crisis_decisions: Optional[list[CrisisDecision]] = None,
) -> str:
    """Render a human-readable Markdown safety-audit report.

    Summarises the safety posture of a :class:`SafetyGuard`: its product-facing
    consent log, the watermark-compliance results of any emitted/withheld
    outputs, and any crisis-handling decisions. The renderer is pure: it reports
    exactly what the ``guard`` state and the supplied records contain and makes
    no safety decisions of its own.

    Args:
        guard: The :class:`SafetyGuard` whose consent log is audited. The log is
            read via :meth:`SafetyGuard.consent_log`, which returns a fresh
            snapshot, so this call never mutates the guard.
        emission_results: Optional watermarking outcomes
            (:class:`EmissionResult`) to audit. When provided, the report counts
            compliant/emitted vs. withheld outputs, breaks them down per output
            path, and confirms every emitted output was watermarked
            (Requirement 10.2). When ``None`` (or empty), the watermark *policy*
            is stated instead.
        crisis_decisions: Optional crisis-handling outcomes
            (:class:`CrisisDecision`) to audit. When provided, the report tallies
            how many triggered (guidance surfaced **and** flagged for review)
            (Requirements 10.4, 10.5). When ``None`` (or empty), the crisis
            *policy* is stated instead.

    Returns:
        A Markdown string containing the consent-log, watermark-compliance, and
        crisis-handling sections.
    """
    lines: list[str] = ["# Safety Audit Report", ""]

    lines.extend(_render_consent_log(guard))
    lines.append("")
    lines.extend(_render_watermark_compliance(emission_results))
    lines.append("")
    lines.extend(_render_crisis_handling(crisis_decisions))

    return "\n".join(lines) + "\n"


# -- Section renderers -------------------------------------------------------


def _render_consent_log(guard: SafetyGuard) -> list[str]:
    """Render the product-facing consent-log section (Requirement 10.6).

    Reports the count of voices in product-facing use and a table of the three
    required consent fields per entry, plus an explicit confirmation that every
    retained entry carries all three fields.
    """
    entries = guard.consent_log()
    lines = ["## Consent Log (Requirement 10.6)", ""]
    lines.append(f"- Product-facing voices in use: {len(entries)}")

    if not entries:
        lines.append("")
        lines.append("_No product-facing voices are currently in use._")
        return lines

    # Every retained entry must carry speaker_id, permitted_use_scope, and
    # timestamp; surface that invariant explicitly (Requirement 10.6).
    all_three = all(entry.is_valid() for entry in entries)
    lines.append(
        "- All entries carry the three required fields "
        f"(speaker_id, permitted_use_scope, timestamp): {_yes_no(all_three)}"
    )

    lines.append("")
    lines.append("| Speaker ID | Permitted-Use Scope | Timestamp |")
    lines.append("| --- | --- | --- |")
    for entry in entries:
        lines.append(
            f"| {entry.speaker_id} "
            f"| {entry.permitted_use_scope} "
            f"| {_format_number(entry.timestamp)} |"
        )
    return lines


def _render_watermark_compliance(
    emission_results: Optional[list[EmissionResult]],
) -> list[str]:
    """Render the watermark-compliance section (Requirement 10.2).

    With results, counts compliant/emitted vs. withheld outputs, breaks them
    down per path, and confirms every emitted output was watermark-detected.
    Without results, states the watermark policy.
    """
    lines = ["## Watermark Compliance (Requirement 10.2)", ""]

    if not emission_results:
        lines.append(
            "- Policy: every synthesized output, on every output path "
            "(including fallback paths), is watermarked; an output whose "
            "watermark cannot be verified is withheld rather than emitted."
        )
        lines.append("- No emission results were provided to audit.")
        return lines

    total = len(emission_results)
    emitted = [r for r in emission_results if r.emitted]
    withheld = [r for r in emission_results if not r.emitted]

    lines.append(f"- Outputs audited: {total}")
    lines.append(f"- Compliant / emitted: {len(emitted)}")
    lines.append(f"- Withheld (non-compliant): {len(withheld)}")

    # Requirement 10.2: every emitted output must carry a detected watermark.
    every_emitted_watermarked = all(
        r.watermark_detected and r.output.is_watermarked for r in emitted
    )
    lines.append(
        "- Every emitted output carried a detected watermark: "
        f"{_yes_no(every_emitted_watermarked)}"
    )

    # Per-path breakdown so each output path can be confirmed individually.
    lines.append("")
    lines.append("| Output Path | Audited | Emitted | Withheld |")
    lines.append("| --- | --- | --- | --- |")
    for path in _ordered_paths(emission_results):
        path_results = [r for r in emission_results if r.output.path == path]
        path_emitted = sum(1 for r in path_results if r.emitted)
        path_withheld = len(path_results) - path_emitted
        lines.append(
            f"| {path} "
            f"| {len(path_results)} "
            f"| {path_emitted} "
            f"| {path_withheld} |"
        )

    if withheld:
        lines.append("")
        lines.append("### Withheld outputs")
        lines.append("")
        for result in withheld:
            lines.append(
                f"- path `{result.output.path}`: {result.reason}"
            )

    return lines


def _render_crisis_handling(
    crisis_decisions: Optional[list[CrisisDecision]],
) -> list[str]:
    """Render the crisis-handling section (Requirements 10.4, 10.5).

    With decisions, tallies how many triggered (guidance surfaced **and**
    flagged for review). Without decisions, states the crisis policy.
    """
    lines = ["## Crisis Handling (Requirements 10.4, 10.5)", ""]

    if not crisis_decisions:
        lines.append(
            "- Policy: when the crisis-classifier score is at or above its "
            "decision threshold, crisis-support guidance is surfaced to the "
            "user AND the turn is flagged for human review; below the "
            "threshold neither action fires."
        )
        lines.append("- No crisis decisions were provided to audit.")
        return lines

    total = len(crisis_decisions)
    triggered = [d for d in crisis_decisions if d.triggered]

    lines.append(f"- Crisis decisions audited: {total}")
    lines.append(
        f"- Triggered (guidance surfaced + flagged for human review): "
        f"{len(triggered)}"
    )
    lines.append(f"- Below threshold (no action): {total - len(triggered)}")

    # Requirement 10.4/10.5: the two actions always move together. Confirm the
    # audited decisions are internally consistent with that guarantee.
    consistent = all(
        d.crisis_support_surfaced == d.flagged_for_human_review
        for d in crisis_decisions
    )
    lines.append(
        "- Guidance and human-review flag fired together on every triggered "
        f"decision: {_yes_no(consistent)}"
    )

    return lines


# -- Helpers -----------------------------------------------------------------


def _ordered_paths(emission_results: list[EmissionResult]) -> list[str]:
    """Return the distinct output paths in first-seen order (stable rendering)."""
    seen: list[str] = []
    for result in emission_results:
        path = result.output.path
        if path not in seen:
            seen.append(path)
    return seen


def _format_number(value: float) -> str:
    """Render a numeric value without trailing ``.0`` noise.

    Integer-valued floats render without a decimal point (``1700000000`` not
    ``1700000000.0``); other values use their default ``str`` form.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return str(value)
    return str(value)


def _yes_no(flag: bool) -> str:
    """Render a boolean flag as ``yes`` / ``no``."""
    return "yes" if flag else "no"
