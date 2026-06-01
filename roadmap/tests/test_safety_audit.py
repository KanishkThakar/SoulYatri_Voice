"""Unit tests for the safety-audit Markdown report renderer (task 36.2).

These plain-pytest example tests cover
:func:`roadmap.reports.safety_audit.render_safety_audit`, asserting on the
rendered Markdown string. They confirm the three sections the report renders:

- **Consent Log** (Requirement 10.6): the count of product-facing voices in use
  and a per-entry table of ``speaker_id`` / ``permitted_use_scope`` /
  ``timestamp``, plus the "all entries carry the three fields" confirmation; and
  the "no voices in use" note when the consent log is empty.
- **Watermark Compliance** (Requirement 10.2): correct compliant/emitted vs.
  withheld counts and the "every emitted output watermarked: yes" confirmation
  when emission results are supplied; the watermark *policy* statement when
  none are.
- **Crisis Handling** (Requirements 10.4, 10.5): the triggered / below-threshold
  tally when crisis decisions are supplied; the crisis *policy* statement when
  none are.

Validates: Requirements 10.2, 10.3, 10.6
"""

from __future__ import annotations

import re

from roadmap.reports.safety_audit import render_safety_audit
from roadmap.safety_guard import (
    SafetyGuard,
    SynthesizedOutput,
    WatermarkDetector,
)
from roadmap.tests.fixtures import make_consent_record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Collapse runs of whitespace to single spaces for spacing-robust matching."""
    return re.sub(r"\s+", " ", text)


def _contains(haystack: str, needle: str) -> bool:
    """Case-insensitive, spacing-robust substring check."""
    return _normalize(needle).lower() in _normalize(haystack).lower()


class _FailingDetector(WatermarkDetector):
    """A detector that never confirms a watermark.

    Models the "watermark cannot be verified" case so a guard using it withholds
    the output (``emitted=False``), letting us build non-compliant emission
    results for the audit.
    """

    def detect(self, output: SynthesizedOutput) -> bool:  # noqa: D102
        return False


# ---------------------------------------------------------------------------
# Consent Log section (Requirement 10.6)
# ---------------------------------------------------------------------------
def test_consent_log_with_one_voice_lists_count_and_three_fields() -> None:
    """One recorded valid consent → "1" voice in use, the three fields, "yes".

    Validates: Requirements 10.6
    """
    guard = SafetyGuard()
    consent = make_consent_record(
        speaker_id="speaker-001",
        permitted_use_scope="voice-style-transfer",
        timestamp=1_700_000_000.0,
    )
    guard.record_consent(consent)

    report = render_safety_audit(guard)

    assert _contains(report, "Consent Log")
    assert _contains(report, "Product-facing voices in use: 1")
    # The three required fields appear in the entry's table row.
    assert "speaker-001" in report
    assert "voice-style-transfer" in report
    assert "1700000000" in report
    # The "all entries carry the three fields" confirmation says yes.
    assert _contains(
        report,
        "All entries carry the three required fields "
        "(speaker_id, permitted_use_scope, timestamp): yes",
    )


def test_consent_log_with_no_voices_renders_no_voices_note() -> None:
    """A guard with no recorded consent → the "no voices in use" note.

    Validates: Requirements 10.6
    """
    guard = SafetyGuard()

    report = render_safety_audit(guard)

    assert _contains(report, "Product-facing voices in use: 0")
    assert _contains(report, "No product-facing voices are currently in use")


# ---------------------------------------------------------------------------
# Watermark Compliance section (Requirement 10.2)
# ---------------------------------------------------------------------------
def test_watermark_compliance_counts_emitted_and_withheld() -> None:
    """A mix of compliant (emitted) and non-compliant (withheld) outputs.

    Compliant outputs are built by the honest guard; withheld outputs by a guard
    with a failing detector. The report counts them correctly and confirms every
    emitted output was watermarked.

    Validates: Requirements 10.2
    """
    guard = SafetyGuard()
    failing_guard = SafetyGuard(watermark_detector=_FailingDetector())

    emitted_a = guard.guard_output("hello", "speech_native_core")
    emitted_b = guard.guard_output("there", "tts_fallback")
    withheld = failing_guard.guard_output("oops", "phase_1_fallback")

    # Preconditions: the builders produced the emitted/withheld split we expect.
    assert emitted_a.emitted is True and emitted_b.emitted is True
    assert withheld.emitted is False

    report = render_safety_audit(
        guard, emission_results=[emitted_a, withheld, emitted_b]
    )

    assert _contains(report, "Watermark Compliance")
    assert _contains(report, "Outputs audited: 3")
    assert _contains(report, "Compliant / emitted: 2")
    assert _contains(report, "Withheld (non-compliant): 1")
    assert _contains(
        report, "Every emitted output carried a detected watermark: yes"
    )


def test_watermark_compliance_without_results_states_policy() -> None:
    """No emission results → the watermark policy statement is rendered.

    Validates: Requirements 10.2
    """
    guard = SafetyGuard()

    report = render_safety_audit(guard, emission_results=None)

    assert _contains(report, "Watermark Compliance")
    # Policy: every output on every path (incl. fallback) is watermarked, and
    # an unverifiable output is withheld.
    assert _contains(report, "Policy:")
    assert _contains(report, "every synthesized output")
    assert _contains(report, "is withheld")
    assert _contains(report, "No emission results were provided to audit")


# ---------------------------------------------------------------------------
# Crisis Handling section (Requirements 10.4, 10.5)
# ---------------------------------------------------------------------------
def test_crisis_handling_tallies_triggered_and_below_threshold() -> None:
    """One triggering (score >= threshold) and one non-triggering decision.

    The tally reports 1 triggered / 1 below threshold.

    Validates: Requirements 10.4, 10.5
    """
    guard = SafetyGuard()
    triggered = guard.handle_crisis(0.9)
    below = guard.handle_crisis(0.1)

    # Preconditions: the scores produced the triggered/below split we expect.
    assert triggered.triggered is True
    assert below.triggered is False

    report = render_safety_audit(
        guard, crisis_decisions=[triggered, below]
    )

    assert _contains(report, "Crisis Handling")
    assert _contains(report, "Crisis decisions audited: 2")
    assert _contains(
        report,
        "Triggered (guidance surfaced + flagged for human review): 1",
    )
    assert _contains(report, "Below threshold (no action): 1")


def test_crisis_handling_without_decisions_states_policy() -> None:
    """No crisis decisions → the crisis policy statement is rendered.

    Validates: Requirements 10.4, 10.5
    """
    guard = SafetyGuard()

    report = render_safety_audit(guard, crisis_decisions=None)

    assert _contains(report, "Crisis Handling")
    assert _contains(report, "Policy:")
    # Policy: a score at/above threshold surfaces guidance AND flags for review.
    assert _contains(report, "human review")
    assert _contains(report, "No crisis decisions were provided to audit")
