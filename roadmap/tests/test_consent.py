"""Property-based test for Safety Guard consent gating + consent-log completeness.

This module implements the design's **Property 13: Consent gating and
consent-log completeness** for the consent responsibility of
:class:`roadmap.safety_guard.SafetyGuard` (the LEAN-scope consent decision
logic).

Property 13 (design ``Correctness Properties``):

    For any voice-cloning or voice-style-transfer request, the request is
    allowed if and only if a valid consent record (speaker identifier,
    permitted-use scope, and timestamp all present) exists; when the request is
    refused the refusal is indicated and no voice reference is retained; and
    every voice recorded in the product-facing consent log carries the speaker
    identifier, permitted-use scope, and consent timestamp.

In terms of the implementation under test
(:meth:`SafetyGuard.request_cloning` / :meth:`SafetyGuard.evaluate_cloning_request`
returning a :class:`~roadmap.models.runtime.CloningDecision`):

- ``request_cloning`` is allowed **iff** the supplied consent is non-``None``
  and ``is_valid()`` (all three fields present/non-empty, timestamp > 0)
  (Requirement 10.1).
- When **allowed**: ``reference_retained is True``.
- When **refused**: ``allowed is False``, ``reference_retained is False`` so no
  voice reference is kept without valid consent (Requirement 10.3), and
  ``reason`` is a non-empty string indicating the refusal.
- An invalid / ``None`` consent is **never** added to the consent log.
- When a **valid** consent is used product-facing, the consent log holds an
  entry for that speaker carrying all three fields (speaker_id,
  permitted_use_scope, timestamp present/non-empty), ``is_voice_in_use`` is
  ``True``, and every entry in ``consent_log()`` is valid (Requirement 10.6).
- Retiring the voice (``retire_voice`` / ``mark_voice_not_in_use``) releases it
  from the active retained log (``is_voice_in_use`` ``False`` afterwards).

Generator design (covering the whole input space the task describes):

- The ``valid`` bucket draws all three fields non-blank with ``timestamp > 0``.
- The ``invalid`` bucket corrupts at least one field (blank speaker_id, blank
  scope, and/or non-positive timestamp) so ``is_valid()`` is ``False``.
- The ``none`` bucket supplies ``None`` (no consent recorded).

Each generated consent carries an independently-known ``expected_valid`` flag
(from its bucket, not from calling the code under test), and the test
cross-checks ``consent.is_valid()`` against it before exercising the guard, so
the IFF assertion is not tautological. A fresh :class:`SafetyGuard` is used per
example to keep the consent-log state clean.

Validates: Requirements 10.1, 10.3, 10.6.
"""

from __future__ import annotations

from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.models.runtime import CloningDecision, ConsentRecord
from roadmap.safety_guard import ConsentLogEntry, SafetyGuard

# A non-blank alphabet for the consent string fields, so a "valid" draw is
# always genuinely non-empty after stripping (matching ConsentRecord.is_valid).
_FIELD_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"

#: A genuinely non-blank string (valid speaker_id / permitted_use_scope).
_non_blank = st.text(alphabet=_FIELD_ALPHABET, min_size=1, max_size=24)

#: A blank string: empty, or whitespace-only (both invalid for a consent field).
_blank = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=4),
)

#: A strictly-positive timestamp (a valid consent timestamp, > 0).
_positive_ts = st.floats(
    min_value=1e-6, max_value=2.0e9, allow_nan=False, allow_infinity=False
)

#: A non-positive timestamp: 0.0 or negative (an invalid / missing timestamp).
_nonpositive_ts = st.one_of(
    st.just(0.0),
    st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
)


@st.composite
def _valid_consent(draw: st.DrawFn) -> ConsentRecord:
    """A consent record with all three fields present and non-empty."""
    return ConsentRecord(
        speaker_id=draw(_non_blank),
        permitted_use_scope=draw(_non_blank),
        timestamp=draw(_positive_ts),
    )


@st.composite
def _invalid_consent(draw: st.DrawFn) -> ConsentRecord:
    """A consent record with at least one missing/empty field.

    At least one of the three fields is corrupted (blank speaker_id, blank
    scope, or a non-positive timestamp), so ``is_valid()`` is guaranteed
    ``False`` regardless of the other fields' draws.
    """
    bad_speaker = draw(st.booleans())
    bad_scope = draw(st.booleans())
    bad_ts = draw(st.booleans())
    # Guarantee invalidity: if nothing was selected, corrupt the speaker_id.
    if not (bad_speaker or bad_scope or bad_ts):
        bad_speaker = True
    return ConsentRecord(
        speaker_id=draw(_blank) if bad_speaker else draw(_non_blank),
        permitted_use_scope=draw(_blank) if bad_scope else draw(_non_blank),
        timestamp=draw(_nonpositive_ts) if bad_ts else draw(_positive_ts),
    )


@st.composite
def _classified_consent(draw: st.DrawFn) -> tuple[Optional[ConsentRecord], bool]:
    """Draw a consent spanning valid / invalid / None, with its known validity.

    Returns ``(consent, expected_valid)`` where ``expected_valid`` is decided by
    the chosen bucket, independently of the code under test.
    """
    bucket = draw(st.sampled_from(("valid", "invalid", "none")))
    if bucket == "valid":
        return draw(_valid_consent()), True
    if bucket == "invalid":
        return draw(_invalid_consent()), False
    return None, False


def _assert_refused(decision: CloningDecision, guard: SafetyGuard) -> None:
    """Assert the refusal invariants of Property 13 (Requirements 10.1, 10.3)."""
    assert decision.allowed is False
    # No voice reference retained without valid consent (Req 10.3).
    assert decision.reference_retained is False
    # The refusal is indicated: a non-empty reason string.
    assert isinstance(decision.reason, str)
    assert decision.reason.strip() != ""
    # Nothing was added to the product-facing consent log.
    assert guard.consent_log() == []


def _assert_allowed_and_logged(
    decision: CloningDecision, guard: SafetyGuard, consent: ConsentRecord
) -> None:
    """Assert the allow + consent-log invariants (Requirements 10.1, 10.6)."""
    assert decision.allowed is True
    assert decision.reference_retained is True

    sid = consent.speaker_id
    # The voice is now retained as in-use in the product-facing consent log.
    assert guard.is_voice_in_use(sid) is True

    entry = guard.get_consent_log_entry(sid)
    assert entry is not None
    assert isinstance(entry, ConsentLogEntry)
    # The entry carries all three consent fields verbatim (Req 10.6).
    assert entry.speaker_id == consent.speaker_id
    assert entry.permitted_use_scope == consent.permitted_use_scope
    assert entry.timestamp == float(consent.timestamp)
    assert entry.in_use is True

    # Every entry in the log is itself valid and carries non-empty fields.
    log = guard.consent_log()
    assert len(log) == 1
    for e in log:
        assert e.is_valid()
        assert e.speaker_id.strip() != ""
        assert e.permitted_use_scope.strip() != ""
        assert e.timestamp > 0.0


# Feature: speech-native-voice-roadmap, Property 13: Consent gating and consent-log completeness
@settings(max_examples=100)
@given(classified=_classified_consent())
def test_property_13_consent_gating_and_log_completeness(
    classified: tuple[Optional[ConsentRecord], bool],
) -> None:
    """Property 13: cloning allowed iff valid consent; log carries all 3 fields.

    Validates: Requirements 10.1, 10.3, 10.6.
    """
    consent, expected_valid = classified

    # Cross-check the bucket's known validity against ConsentRecord.is_valid so
    # the IFF below is grounded in an independent expectation, not the code path.
    actual_valid = consent is not None and consent.is_valid()
    assert actual_valid is expected_valid

    guard = SafetyGuard()
    decision = guard.request_cloning(consent, product_facing=True)
    assert isinstance(decision, CloningDecision)

    # Core IFF: allowed exactly when a valid consent record exists (Req 10.1).
    assert decision.allowed is expected_valid

    if expected_valid:
        assert consent is not None  # narrows type for the helper
        _assert_allowed_and_logged(decision, guard, consent)

        # Retiring the voice releases it from the active retained log (Req 10.6).
        removed = guard.retire_voice(consent.speaker_id)
        assert removed is True
        assert guard.is_voice_in_use(consent.speaker_id) is False
        assert guard.get_consent_log_entry(consent.speaker_id) is None
        assert guard.consent_log() == []
    else:
        _assert_refused(decision, guard)


# Feature: speech-native-voice-roadmap, Property 13: Consent gating and consent-log completeness
@settings(max_examples=100)
@given(classified=_classified_consent())
def test_property_13_evaluate_request_and_non_product_facing(
    classified: tuple[Optional[ConsentRecord], bool],
) -> None:
    """Property 13 holds via ``evaluate_cloning_request`` and the not-in-use path.

    Exercises the second public entry point, the ``mark_voice_not_in_use``
    retirement alias, and the non-product-facing branch: a valid consent is
    still allowed (reference retained) but is NOT added to the product-facing
    consent log.

    Validates: Requirements 10.1, 10.3, 10.6.
    """
    consent, expected_valid = classified

    # --- Product-facing path via evaluate_cloning_request. -----------------
    guard = SafetyGuard()
    decision = guard.evaluate_cloning_request(consent, product_facing=True)
    assert decision.allowed is expected_valid

    if expected_valid:
        assert consent is not None
        _assert_allowed_and_logged(decision, guard, consent)
        # mark_voice_not_in_use releases the retained entry (Req 10.6).
        assert guard.mark_voice_not_in_use(consent.speaker_id) is True
        assert guard.is_voice_in_use(consent.speaker_id) is False
        assert guard.consent_log() == []
    else:
        _assert_refused(decision, guard)

    # --- Non-product-facing path: allowed but never logged. ----------------
    guard2 = SafetyGuard()
    decision2 = guard2.evaluate_cloning_request(consent, product_facing=False)
    assert decision2.allowed is expected_valid
    if expected_valid:
        assert consent is not None
        assert decision2.reference_retained is True
        # Not product-facing -> nothing enters the retained consent log.
        assert guard2.is_voice_in_use(consent.speaker_id) is False
        assert guard2.consent_log() == []
    else:
        _assert_refused(decision2, guard2)


def test_consent_gating_concrete_examples() -> None:
    """Concrete examples around the consent gate complementing the property.

    Validates: Requirements 10.1, 10.3, 10.6.
    """
    guard = SafetyGuard()

    # Valid consent, product-facing -> allowed, retained, and logged.
    valid = ConsentRecord(
        speaker_id="spk-1", permitted_use_scope="narration", timestamp=1700000000.0
    )
    decision = guard.request_cloning(valid, product_facing=True)
    assert decision.allowed is True
    assert decision.reference_retained is True
    assert guard.is_voice_in_use("spk-1") is True
    entry = guard.get_consent_log_entry("spk-1")
    assert entry is not None
    assert entry.speaker_id == "spk-1"
    assert entry.permitted_use_scope == "narration"
    assert entry.timestamp == 1700000000.0

    # Retiring releases the entry.
    assert guard.retire_voice("spk-1") is True
    assert guard.is_voice_in_use("spk-1") is False
    assert guard.consent_log() == []

    # No consent (None) -> refused, nothing retained or logged.
    refused = guard.request_cloning(None, product_facing=True)
    assert refused.allowed is False
    assert refused.reference_retained is False
    assert refused.reason.strip() != ""
    assert guard.consent_log() == []

    # Invalid consent (missing timestamp) -> refused.
    invalid = ConsentRecord(
        speaker_id="spk-2", permitted_use_scope="narration", timestamp=0.0
    )
    refused2 = guard.request_cloning(invalid, product_facing=True)
    assert refused2.allowed is False
    assert refused2.reference_retained is False
    assert guard.consent_log() == []
