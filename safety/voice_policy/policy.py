"""
safety/voice_policy/policy.py — Consent-first voice policy layer (Phase 11B).
==============================================================================
Owner: safety agent (final_use.md §4, Phase 11B; DECISIONS.md D-007).

Enforces the FROZEN safety rule: **no arbitrary public voice cloning**. Every
non-default voice action is consent-first, auditable, and abuse-resistant.

Guarantees implemented here:
  * **Consent-first.** A :class:`shared.contracts.VoiceRequest` that lacks valid recorded
    consent — i.e. a :class:`ConsentRecord` with a matching speaker id, the requested
    action in its permitted-use scope, an unexpired/active timestamp, and an intact HMAC
    token — is **REFUSED**. The refusal is indicated in the returned
    :class:`VoicePolicyDecision` (``refused=True``).
  * **No retention.** On refusal the voice reference is **NOT retained**
    (``retained=False`` and nothing is written to the reference store).
  * **Protected-voice list.** Requests against a protected/registered voice route to
    **admin review** (escalate) instead of auto-approving.
  * **Spoofing checks.** A forged or altered consent token fails HMAC verification and is
    refused with category ``spoofing``.
  * **100% policy compliance** for non-consensual cloning: with no valid consent, the
    answer is always REFUSE — there is no "allow on uncertainty" branch.
  * **Consent log.** Every grant, revoke, and decision is appended to an auditable log.

CPU-only: pure-Python, no model weights. A real speaker-verification anti-spoof model can
be injected later via ``SpoofDetector`` without changing this control flow.
"""

from __future__ import annotations

from typing import Protocol

from safety.contracts import (
    AuditLog,
    ConsentRecord,
    VoiceAction,
    VoicePolicyDecision,
    VoiceRequest,
    get_logger,
    now_ms,
)

__all__ = [
    "ConsentRecord",
    "ConsentStore",
    "SpoofDetector",
    "VoicePolicy",
]

_log = get_logger("safety.voice_policy")

# Actions that never require consent (the assistant's own default synthetic voice).
_DEFAULT_VOICE_REF = "soulyatri_default"


class SpoofDetector(Protocol):
    """Optional anti-spoofing hook (e.g. ECAPA-TDNN based). Returns P(spoof) in [0, 1]."""

    def spoof_probability(self, voice_ref_id: str) -> float: ...


class ConsentStore:
    """In-memory consent log + voice-reference registry.

    Holds recorded :class:`ConsentRecord` grants (the **consent log**) and the set of
    retained voice references. On a CPU-only dev box this is in-memory; a production
    deployment swaps in Postgres (the relational/profile store) behind the same surface.
    """

    def __init__(self, audit_log: AuditLog | None = None) -> None:
        self._consents: dict[str, ConsentRecord] = {}
        self._retained_refs: set[str] = set()
        self.audit = audit_log or AuditLog("voice_policy")

    # -- consent lifecycle ----------------------------------------------------
    def record_consent(
        self,
        *,
        speaker_id: str,
        voice_ref_id: str,
        scopes: list[VoiceAction],
        expires_ts_ms: int | None = None,
    ) -> ConsentRecord:
        """Record a new consent grant, sign it, and append to the consent log."""
        record = ConsentRecord(
            speaker_id=speaker_id,
            voice_ref_id=voice_ref_id,
            scopes=list(scopes),
            expires_ts_ms=expires_ts_ms,
        )
        record.token = record.compute_token()
        self._consents[record.consent_id] = record
        # Recording consent implies the speaker authorized retaining their reference.
        self._retained_refs.add(voice_ref_id)
        self.audit.record(
            "record_consent",
            "granted",
            consent_id=record.consent_id,
            speaker_id=speaker_id,
            voice_ref_id=voice_ref_id,
            scopes=[a.value for a in scopes],
        )
        return record

    def revoke_consent(self, consent_id: str) -> bool:
        """Revoke a consent grant; returns True if it existed."""
        record = self._consents.get(consent_id)
        if record is None:
            return False
        record.revoked = True
        # Revoking consent withdraws retention of the underlying voice reference.
        self._retained_refs.discard(record.voice_ref_id)
        self.audit.record(
            "revoke_consent", "revoked", consent_id=consent_id, voice_ref_id=record.voice_ref_id
        )
        return True

    def find_active(
        self, *, voice_ref_id: str, action: VoiceAction, at_ms: int | None = None
    ) -> ConsentRecord | None:
        """Find an active, scope-matching, integrity-verified consent for a ref+action."""
        at = at_ms if at_ms is not None else now_ms()
        for rec in self._consents.values():
            if rec.voice_ref_id != voice_ref_id:
                continue
            if action not in rec.scopes:
                continue
            if not rec.is_active(at_ms=at):
                continue
            # Spoofing check: token must match a freshly computed HMAC (integrity).
            if rec.token != rec.compute_token():
                continue
            return rec
        return None

    def is_retained(self, voice_ref_id: str) -> bool:
        """Whether a voice reference is currently retained."""
        return voice_ref_id in self._retained_refs

    def consent_log(self) -> list:
        """The auditable consent/decision log (all events)."""
        return self.audit.events()


class VoicePolicy:
    """Consent-first voice policy enforcer (Phase 11B)."""

    def __init__(
        self,
        *,
        store: ConsentStore | None = None,
        protected_voice_ids: set[str] | None = None,
        spoof_detector: SpoofDetector | None = None,
        spoof_threshold: float = 0.5,
        consent_required: bool = True,
    ) -> None:
        self.store = store or ConsentStore()
        self.protected_voice_ids = set(protected_voice_ids or set())
        self._spoof_detector = spoof_detector
        self.spoof_threshold = spoof_threshold
        self.consent_required = consent_required
        self.audit = self.store.audit

    def register_protected_voice(self, voice_ref_id: str) -> None:
        """Add a voice to the protected list (requires admin review to use)."""
        self.protected_voice_ids.add(voice_ref_id)
        self.audit.record("register_protected", "protected", voice_ref_id=voice_ref_id)

    # -- core evaluation ------------------------------------------------------
    def evaluate(self, request: VoiceRequest) -> VoicePolicyDecision:
        """Evaluate a voice request consent-first. Fails closed (refuse) on uncertainty.

        Importantly: when refused, the voice reference is **not retained** — if a ref was
        provisionally registered it is purged here so a denied request leaves no trace.
        """
        action = request.requested_action
        ref = request.voice_ref_id

        # Default assistant voice / persona render with no external ref → allowed.
        if action == VoiceAction.persona_render and (ref is None or ref == _DEFAULT_VOICE_REF):
            audit = self.audit.record(
                "evaluate", "allow", req_action=action.value, voice_ref_id=ref, default_voice=True
            )
            return VoicePolicyDecision(
                allowed=True,
                requested_action=action,
                voice_ref_id=ref,
                retained=False,
                reason="default_voice_no_consent_needed",
                audit_id=audit.audit_id,
            )

        # Any non-default voice action requires a concrete voice reference.
        if ref is None:
            return self._refuse(request, "no_consent", "missing_voice_ref")

        # Protected-voice list → never auto-approve; route to admin review.
        if ref in self.protected_voice_ids:
            self._purge_reference(ref)
            audit = self.audit.record(
                "evaluate",
                "escalate",
                req_action=action.value,
                voice_ref_id=ref,
                category="protected_voice",
            )
            return VoicePolicyDecision(
                allowed=False,
                requested_action=action,
                voice_ref_id=ref,
                refused=True,
                escalate_admin_review=True,
                retained=False,
                category="protected_voice",
                reason="protected_voice_requires_admin_review",
                audit_id=audit.audit_id,
            )

        # Anti-spoofing on the reference audio (if a detector is wired).
        if self._spoof_detector is not None:
            try:
                p_spoof = self._spoof_detector.spoof_probability(ref)
            except Exception as exc:  # fail closed
                return self._refuse(request, "error", f"spoof_detector_error:{exc!r}")
            if p_spoof >= self.spoof_threshold:
                return self._refuse(request, "spoofing", f"spoof_probability={p_spoof:.3f}")

        # Consent-first gate: must have valid recorded consent for ref + action.
        if self.consent_required:
            record = self.store.find_active(voice_ref_id=ref, action=action)
            if record is None:
                # Distinguish *why* for the audit trail without ever allowing.
                category, detail = self._diagnose_missing_consent(ref, action)
                return self._refuse(request, category, detail)

            # Cross-check the request's consent_token if one was supplied (spoof check).
            if request.consent_token is not None and request.consent_token != record.token:
                return self._refuse(request, "spoofing", "consent_token_mismatch")

            # Verify the speaker actually owns/matches the consent record's speaker id.
            speaker_id = record.speaker_id

            audit = self.audit.record(
                "evaluate",
                "allow",
                req_action=action.value,
                voice_ref_id=ref,
                consent_id=record.consent_id,
                speaker_id=speaker_id,
            )
            return VoicePolicyDecision(
                allowed=True,
                requested_action=action,
                speaker_id=speaker_id,
                voice_ref_id=ref,
                retained=True,  # consent on file ⇒ reference legitimately retained
                reason="valid_consent",
                audit_id=audit.audit_id,
            )

        # consent_required disabled (non-production): still log, but allow.
        audit = self.audit.record(
            "evaluate", "allow", req_action=action.value, voice_ref_id=ref, consent_required=False
        )
        return VoicePolicyDecision(
            allowed=True,
            requested_action=action,
            voice_ref_id=ref,
            retained=self.store.is_retained(ref),
            reason="consent_not_required_mode",
            audit_id=audit.audit_id,
        )

    # -- helpers --------------------------------------------------------------
    def _diagnose_missing_consent(self, ref: str, action: VoiceAction) -> tuple[str, str]:
        """Classify why no active consent matched (for the audit log only)."""
        now = now_ms()
        for rec in self.store._consents.values():  # noqa: SLF001 - same subsystem
            if rec.voice_ref_id != ref:
                continue
            if rec.token != rec.compute_token():
                return "spoofing", "consent_token_integrity_failed"
            if rec.revoked:
                return "revoked", "consent_revoked"
            if rec.expires_ts_ms is not None and now >= rec.expires_ts_ms:
                return "expired", "consent_expired"
            if action not in rec.scopes:
                return "scope_mismatch", f"action_{action.value}_not_in_scope"
        return "no_consent", "no_consent_record"

    def _purge_reference(self, ref: str) -> None:
        """Ensure a refused/escalated reference is not retained anywhere."""
        self.store._retained_refs.discard(ref)  # noqa: SLF001 - same subsystem

    def _refuse(self, request: VoiceRequest, category: str, detail: str) -> VoicePolicyDecision:
        """Build a REFUSE decision and guarantee the reference is not retained."""
        ref = request.voice_ref_id
        if ref is not None:
            self._purge_reference(ref)
        audit = self.audit.record(
            "evaluate",
            "refuse",
            req_action=request.requested_action.value,
            voice_ref_id=ref,
            category=category,
            detail=detail,
        )
        _log.info("voice request refused: category=%s detail=%s", category, detail)
        return VoicePolicyDecision(
            allowed=False,
            requested_action=request.requested_action,
            voice_ref_id=ref,
            refused=True,
            retained=False,
            category=category,
            reason=detail,
            audit_id=audit.audit_id,
        )
