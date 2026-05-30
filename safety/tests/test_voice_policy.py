"""
Tests for safety/voice_policy/policy.py (Phase 11B).

Covers: consent-first refusal, no-retention on refusal, consent-log completeness,
protected-voice admin-review escalation, spoofing checks, scope/expiry/revocation, and
100% policy compliance for non-consensual cloning (never allowed without valid consent).
"""

from __future__ import annotations

import importlib

from safety.contracts import VoiceAction, VoiceRequest, now_ms
from safety.voice_policy.policy import ConsentStore, VoicePolicy


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------
def test_module_imports_clean() -> None:
    mod = importlib.import_module("safety.voice_policy.policy")
    assert hasattr(mod, "VoicePolicy")


def test_no_heavy_imports() -> None:
    import sys

    importlib.import_module("safety.voice_policy.policy")
    for heavy in ("torch", "transformers", "moshi", "mimi"):
        assert heavy not in sys.modules


# ---------------------------------------------------------------------------
# Consent-first refusal + no retention
# ---------------------------------------------------------------------------
def test_clone_without_consent_is_refused() -> None:
    policy = VoicePolicy()
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.refused is True
    assert decision.category == "no_consent"


def test_refused_request_does_not_retain_reference() -> None:
    policy = VoicePolicy()
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.retained is False
    assert policy.store.is_retained("alice_voice") is False  # nothing kept


def test_missing_voice_ref_refused() -> None:
    policy = VoicePolicy()
    req = VoiceRequest(voice_ref_id=None, requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.refused is True
    assert decision.category == "no_consent"


# ---------------------------------------------------------------------------
# Valid consent unlocks the action
# ---------------------------------------------------------------------------
def test_valid_consent_allows_clone() -> None:
    policy = VoicePolicy()
    policy.store.record_consent(
        speaker_id="alice",
        voice_ref_id="alice_voice",
        scopes=[VoiceAction.voice_clone],
    )
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is True
    assert decision.refused is False
    assert decision.speaker_id == "alice"
    assert decision.retained is True


def test_default_voice_needs_no_consent() -> None:
    policy = VoicePolicy()
    req = VoiceRequest(voice_ref_id=None, requested_action=VoiceAction.persona_render)
    decision = policy.evaluate(req)
    assert decision.allowed is True
    assert decision.retained is False


# ---------------------------------------------------------------------------
# Scope / expiry / revocation
# ---------------------------------------------------------------------------
def test_scope_mismatch_refused() -> None:
    policy = VoicePolicy()
    policy.store.record_consent(
        speaker_id="alice",
        voice_ref_id="alice_voice",
        scopes=[VoiceAction.style_transfer],  # not voice_clone
    )
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "scope_mismatch"


def test_expired_consent_refused() -> None:
    policy = VoicePolicy()
    policy.store.record_consent(
        speaker_id="alice",
        voice_ref_id="alice_voice",
        scopes=[VoiceAction.voice_clone],
        expires_ts_ms=now_ms() - 1000,  # already expired
    )
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "expired"


def test_revoked_consent_refused_and_not_retained() -> None:
    policy = VoicePolicy()
    rec = policy.store.record_consent(
        speaker_id="alice",
        voice_ref_id="alice_voice",
        scopes=[VoiceAction.voice_clone],
    )
    assert policy.store.is_retained("alice_voice") is True
    policy.store.revoke_consent(rec.consent_id)
    assert policy.store.is_retained("alice_voice") is False
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "revoked"


# ---------------------------------------------------------------------------
# Spoofing checks
# ---------------------------------------------------------------------------
def test_tampered_consent_token_detected() -> None:
    policy = VoicePolicy()
    rec = policy.store.record_consent(
        speaker_id="alice",
        voice_ref_id="alice_voice",
        scopes=[VoiceAction.voice_clone],
    )
    # Tamper with the stored token (forgery / integrity attack).
    rec.token = "forged-token"
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "spoofing"


def test_mismatched_request_token_refused() -> None:
    policy = VoicePolicy()
    policy.store.record_consent(
        speaker_id="alice",
        voice_ref_id="alice_voice",
        scopes=[VoiceAction.voice_clone],
    )
    req = VoiceRequest(
        voice_ref_id="alice_voice",
        requested_action=VoiceAction.voice_clone,
        consent_token="not-the-real-token",
    )
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "spoofing"


class _SpoofDetector:
    def __init__(self, p: float) -> None:
        self._p = p

    def spoof_probability(self, voice_ref_id: str) -> float:
        return self._p


def test_spoof_detector_blocks_high_probability() -> None:
    policy = VoicePolicy(spoof_detector=_SpoofDetector(0.9))
    policy.store.record_consent(
        speaker_id="alice", voice_ref_id="alice_voice", scopes=[VoiceAction.voice_clone]
    )
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "spoofing"
    assert decision.retained is False


def test_spoof_detector_error_fails_closed() -> None:
    class _Broken:
        def spoof_probability(self, voice_ref_id: str) -> float:
            raise RuntimeError("boom")

    policy = VoicePolicy(spoof_detector=_Broken())
    policy.store.record_consent(
        speaker_id="alice", voice_ref_id="alice_voice", scopes=[VoiceAction.voice_clone]
    )
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.category == "error"


# ---------------------------------------------------------------------------
# Protected-voice list → admin review
# ---------------------------------------------------------------------------
def test_protected_voice_routes_to_admin_review() -> None:
    policy = VoicePolicy(protected_voice_ids={"celebrity_voice"})
    req = VoiceRequest(voice_ref_id="celebrity_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.allowed is False
    assert decision.escalate_admin_review is True
    assert decision.category == "protected_voice"
    assert decision.retained is False


def test_protected_voice_not_retained_even_with_consent_attempt() -> None:
    policy = VoicePolicy()
    policy.register_protected_voice("celebrity_voice")
    # Even if a consent record somehow exists, protected list wins (admin review).
    policy.store.record_consent(
        speaker_id="impersonator", voice_ref_id="celebrity_voice", scopes=[VoiceAction.voice_clone]
    )
    req = VoiceRequest(voice_ref_id="celebrity_voice", requested_action=VoiceAction.voice_clone)
    decision = policy.evaluate(req)
    assert decision.escalate_admin_review is True
    assert decision.retained is False
    assert policy.store.is_retained("celebrity_voice") is False


# ---------------------------------------------------------------------------
# 100% policy compliance: many non-consensual clone attempts → all refused
# ---------------------------------------------------------------------------
def test_non_consensual_cloning_blocked_100_percent() -> None:
    policy = VoicePolicy()
    refusals = 0
    attempts = 50
    for i in range(attempts):
        req = VoiceRequest(voice_ref_id=f"victim_{i}", requested_action=VoiceAction.voice_clone)
        decision = policy.evaluate(req)
        if decision.refused and not decision.allowed:
            refusals += 1
        assert decision.retained is False
    assert refusals == attempts  # 100% compliance


# ---------------------------------------------------------------------------
# Consent log completeness
# ---------------------------------------------------------------------------
def test_consent_log_records_grants_and_decisions() -> None:
    store = ConsentStore()
    policy = VoicePolicy(store=store)
    rec = policy.store.record_consent(
        speaker_id="alice", voice_ref_id="alice_voice", scopes=[VoiceAction.voice_clone]
    )
    req = VoiceRequest(voice_ref_id="alice_voice", requested_action=VoiceAction.voice_clone)
    policy.evaluate(req)
    policy.store.revoke_consent(rec.consent_id)

    log = policy.store.consent_log()
    actions = [e.action for e in log]
    assert "record_consent" in actions
    assert "evaluate" in actions
    assert "revoke_consent" in actions
    # Every log entry is JSON round-trippable (auditable export).
    for e in log:
        e.model_validate(e.model_dump())


def test_refusal_is_logged() -> None:
    policy = VoicePolicy()
    req = VoiceRequest(voice_ref_id="x", requested_action=VoiceAction.voice_clone)
    policy.evaluate(req)
    refusals = policy.audit.filter(action="evaluate", outcome="refuse")
    assert len(refusals) == 1
    assert refusals[0].detail["category"] == "no_consent"
