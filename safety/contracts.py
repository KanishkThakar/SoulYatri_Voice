"""
safety/contracts.py — Safety-internal contracts + structured logging/audit hooks.
==================================================================================
Owner: safety agent (final_use.md §4, Phase 11; DECISIONS.md D-007).

This module is the safety subsystem's *local* contract surface. It builds on the
cross-subsystem types in ``shared/contracts.py`` (``VoiceRequest``, ``VoiceAction``,
``ModerationDecision``) and adds the richer types the three safety modules need:

  * moderation     → ``RiskCategory``, ``ModerationOutcome`` (wraps ``ModerationDecision``)
  * voice policy   → ``ConsentRecord``, ``VoicePolicyDecision``
  * watermarking   → ``WatermarkMarker``, ``WatermarkedAudio``, ``WatermarkResult``

It also provides the **structured logging + auditable-decision hooks** required by the
global Definition of Done (final_use.md §3.3): a dependency-light ``AuditLog`` built on
the stdlib ``logging`` module. We deliberately avoid ``structlog`` here so the safety
subsystem imports cleanly on a CPU-only machine with no extra packages (DECISIONS.md
D-008); each ``AuditEvent`` is emitted as a single JSON line.

Hard rules:
  * Fail CLOSED — callers treat uncertainty as "deny / escalate".
  * No GPU / torch / transformers / audioseal imports at module top-level.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# Re-export the shared safety contracts so safety code has a single import surface.
from shared.contracts import ModerationDecision, VoiceAction, VoiceRequest

__all__ = [
    # time / ids / crypto helpers
    "now_ms",
    "new_id",
    "sign",
    "verify_signature",
    # logging / audit
    "get_logger",
    "AuditEvent",
    "AuditLog",
    # moderation
    "RiskCategory",
    "ModerationOutcome",
    # voice policy
    "ConsentRecord",
    "VoicePolicyDecision",
    # watermarking
    "WatermarkMarker",
    "WatermarkedAudio",
    "WatermarkResult",
    # re-exports from shared
    "ModerationDecision",
    "VoiceAction",
    "VoiceRequest",
]


# ---------------------------------------------------------------------------
# Small deterministic, CPU-only helpers (time / ids / HMAC signatures)
# ---------------------------------------------------------------------------
def now_ms() -> int:
    """Current wall-clock time in integer milliseconds (mirrors shared.contracts)."""
    return int(time.time() * 1000)


def new_id(prefix: str = "evt") -> str:
    """A short unique id for correlating audit records and decisions."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _secret() -> bytes:
    """HMAC secret for consent tokens + watermark markers.

    Reads ``SAFETY_HMAC_SECRET`` from the environment with a deterministic dev default so
    everything is reproducible on a fresh CPU-only checkout. Production deployments MUST
    set a real secret (see safety/README.md + .env.example).
    """
    return os.environ.get("SAFETY_HMAC_SECRET", "soulyatri-dev-secret").encode("utf-8")


def sign(*parts: str | bytes) -> str:
    """Deterministic HMAC-SHA256 hex signature over the given parts."""
    mac = hmac.new(_secret(), digestmod=hashlib.sha256)
    for part in parts:
        mac.update(part if isinstance(part, bytes) else str(part).encode("utf-8"))
        mac.update(b"\x1f")  # unit separator so concatenation is unambiguous
    return mac.hexdigest()


def verify_signature(expected: str, *parts: str | bytes) -> bool:
    """Constant-time comparison of a recomputed signature against ``expected``."""
    return hmac.compare_digest(expected, sign(*parts))


# ---------------------------------------------------------------------------
# Structured logging + auditable decision hooks (DoD: structured logging hooks)
# ---------------------------------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """Return a namespaced stdlib logger with a NullHandler attached.

    Attaching a ``NullHandler`` keeps the library quiet by default (no global logging
    config side effects on import); the host app decides how to surface logs.
    """
    logger = logging.getLogger(name)
    if not any(isinstance(h, logging.NullHandler) for h in logger.handlers):
        logger.addHandler(logging.NullHandler())
    return logger


class AuditEvent(BaseModel):
    """A single auditable safety event (JSON round-trippable)."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: new_id("audit"))
    ts_ms: int = Field(default_factory=now_ms)
    component: str = Field(description="e.g. moderation | voice_policy | watermark")
    action: str = Field(description="What was evaluated, e.g. moderate_text / verify_consent")
    outcome: str = Field(description="allow | block | escalate | refuse | compliant | …")
    detail: dict = Field(default_factory=dict, description="Structured, non-PII context.")


class AuditLog:
    """An append-only in-memory audit trail that also emits structured log lines.

    Backs the moderation **abuse log**, the voice-policy **consent/decision log**, and the
    watermark **detector-outcome log**. Kept in-memory + log-emitting so it works with no
    external store on a CPU-only dev box; a production sink can subscribe to the logger.
    """

    def __init__(self, component: str, *, logger: logging.Logger | None = None) -> None:
        self.component = component
        self._logger = logger or get_logger(f"safety.{component}")
        self._events: list[AuditEvent] = []

    def record(self, action: str, outcome: str, **detail: object) -> AuditEvent:
        """Append + emit a structured audit event; returns it for correlation."""
        event = AuditEvent(
            component=self.component, action=action, outcome=outcome, detail=dict(detail)
        )
        self._events.append(event)
        # Single JSON line keeps logs greppable and machine-parseable.
        self._logger.info(event.model_dump_json())
        return event

    def events(self) -> list[AuditEvent]:
        """All recorded events (chronological)."""
        return list(self._events)

    def filter(self, *, action: str | None = None, outcome: str | None = None) -> list[AuditEvent]:
        """Events matching an optional action and/or outcome."""
        return [
            e
            for e in self._events
            if (action is None or e.action == action) and (outcome is None or e.outcome == outcome)
        ]

    def __len__(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
# 11A — Moderation contracts
# ---------------------------------------------------------------------------
class RiskCategory(str, Enum):
    """Closed set of moderation risk categories."""

    none = "none"
    self_harm = "self_harm"  # crisis / suicidal ideation → escalate, surface support
    abuse = "abuse"
    harassment = "harassment"
    hate = "hate"
    sexual = "sexual"
    violence = "violence"
    illicit = "illicit"
    error = "error"  # classifier failure → fail closed


class ModerationOutcome(BaseModel):
    """Rich moderation result. ``decision`` is the shared ``ModerationDecision``.

    ``moderate_text`` / ``moderate_speech`` return ``ModerationDecision`` directly; the
    ``evaluate_*`` variants return this wrapper so callers can also surface crisis support
    guidance and the per-category scores that justified the decision (auditable).
    """

    model_config = ConfigDict(extra="forbid")

    decision: ModerationDecision
    path: str = Field(description="text | speech")
    scores: dict[str, float] = Field(default_factory=dict)
    crisis_guidance: str | None = Field(
        default=None, description="Crisis-support message surfaced when self-harm is detected."
    )
    audit_id: str = Field(default="")


# ---------------------------------------------------------------------------
# 11B — Voice policy / consent contracts
# ---------------------------------------------------------------------------
class ConsentRecord(BaseModel):
    """A recorded grant of consent: speaker id + permitted-use scope + timestamp.

    A valid recorded consent is the *only* thing that unlocks a non-default voice action.
    The ``token`` is an HMAC signature over the immutable fields so a forged/altered token
    fails verification (spoofing check).
    """

    model_config = ConfigDict(extra="forbid")

    consent_id: str = Field(default_factory=lambda: new_id("consent"))
    speaker_id: str = Field(description="Identity of the consenting speaker.")
    voice_ref_id: str = Field(description="The voice reference this consent authorizes.")
    scopes: list[VoiceAction] = Field(
        default_factory=list, description="Permitted-use scope (which actions are allowed)."
    )
    granted_ts_ms: int = Field(default_factory=now_ms, description="When consent was recorded.")
    expires_ts_ms: int | None = Field(default=None, description="Optional expiry (ms epoch).")
    revoked: bool = Field(default=False)
    token: str = Field(default="", description="HMAC token proving this record's integrity.")

    def compute_token(self) -> str:
        """Deterministic token = HMAC over the immutable consent fields."""
        scope_str = ",".join(sorted(a.value for a in self.scopes))
        return sign(
            self.consent_id, self.speaker_id, self.voice_ref_id, scope_str, str(self.granted_ts_ms)
        )

    def is_active(self, *, at_ms: int | None = None) -> bool:
        """True if not revoked and not expired at the given time."""
        if self.revoked:
            return False
        if self.expires_ts_ms is None:
            return True
        return (at_ms if at_ms is not None else now_ms()) < self.expires_ts_ms


class VoicePolicyDecision(BaseModel):
    """Outcome of a consent-first voice-policy evaluation (Phase 11B)."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    requested_action: VoiceAction
    speaker_id: str | None = None
    voice_ref_id: str | None = None
    refused: bool = Field(default=False, description="True when the request was refused.")
    escalate_admin_review: bool = Field(
        default=False, description="Protected-voice requests route to admin review."
    )
    retained: bool = Field(
        default=False, description="Whether the voice reference was retained (False on refusal)."
    )
    category: str | None = Field(
        default=None,
        description="Refusal reason code: no_consent | spoofing | scope_mismatch | "
        "expired | revoked | ref_mismatch | protected_voice | error.",
    )
    reason: str = ""
    audit_id: str = ""


# ---------------------------------------------------------------------------
# 11C — Watermarking contracts
# ---------------------------------------------------------------------------
class WatermarkMarker(BaseModel):
    """Provenance marker carried with watermarked audio.

    For the real AudioSeal backend this is the detector-recoverable payload; for the
    deterministic fallback it is an HMAC signature over (payload + audio bytes) so any
    tampering or missing mark fails verification.
    """

    model_config = ConfigDict(extra="forbid")

    payload: str = Field(description="Watermark payload, e.g. 'SOULYATRI'.")
    signature: str = Field(description="HMAC signature (fallback) or detector tag.")
    backend: str = Field(description="audioseal | deterministic_fallback")
    sample_rate: int = Field(gt=0)
    num_samples: int = Field(ge=0)
    created_ts_ms: int = Field(default_factory=now_ms)


class WatermarkedAudio(BaseModel):
    """Audio plus its watermark marker and compliance flag."""

    model_config = ConfigDict(extra="forbid")

    samples: list[float] = Field(default_factory=list, description="PCM mono samples in [-1, 1].")
    sample_rate: int = Field(gt=0)
    marker: WatermarkMarker
    compliant: bool = Field(
        default=False, description="True only after a successful self-verify; gate emission on it."
    )


class WatermarkResult(BaseModel):
    """Outcome of a watermark verification / detector pass (logged)."""

    model_config = ConfigDict(extra="forbid")

    detected: bool
    score: float = Field(ge=0.0, le=1.0)
    payload: str | None = None
    backend: str = ""
    compliant: bool = Field(
        default=False, description="False ⇒ output must be flagged non-compliant, not emitted."
    )
    reason: str = ""
    audit_id: str = ""


# Convenience: JSON helper used by ops tooling.
def to_json(model: BaseModel) -> str:
    """Compact JSON for a contract model (ops/CLI friendly)."""
    return json.dumps(model.model_dump(), separators=(",", ":"), default=str)
