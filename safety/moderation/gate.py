"""
safety/moderation/gate.py — Text-path AND speech-path moderation gate (Phase 11A).
===================================================================================
Owner: safety agent (final_use.md §4, Phase 11A; DECISIONS.md D-007/D-008).

Responsibilities:
  * Moderate the **text path** (transcripts, tool text, generated text) AND the
    **speech path** (a transcript produced by the aux STT path for a spoken turn).
  * Escalate **crisis / self-harm** turns: when the crisis classifier is at/above
    threshold, surface crisis-support guidance AND flag for human review.
  * Log abuse + every decision to an auditable :class:`AuditLog`.
  * Return a :class:`shared.contracts.ModerationDecision` (auditable).

Design notes:
  * **Fail CLOSED.** Any classifier error → block + escalate (``RiskCategory.error``).
  * **CPU-only / no weights.** A real transformer classifier (e.g. a fine-tuned text
    model from the aux text-brain) is *lazy-loaded* via ``load_classifier`` and is never
    imported at module top-level. When unavailable we fall back to a deterministic,
    keyword/regex lexicon so the gate always works on a fresh checkout (D-008).
  * Speech-path moderation reuses the text classifier over the STT transcript so spoken
    and typed turns get identical safety treatment.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from safety.contracts import (
    AuditLog,
    ModerationDecision,
    ModerationOutcome,
    RiskCategory,
    get_logger,
)

__all__ = [
    "CRISIS_GUIDANCE",
    "ModerationConfig",
    "TextClassifier",
    "ModerationGate",
    "moderate_text",
    "moderate_speech",
]

_log = get_logger("safety.moderation")

# Crisis-support guidance surfaced to the user when self-harm is detected. Generic and
# non-region-locked; ops can override via ModerationConfig.crisis_guidance.
CRISIS_GUIDANCE = (
    "It sounds like you're going through something really painful, and you deserve support "
    "right now. If you might be in danger, please contact your local emergency number. In "
    "the US you can call or text 988 (Suicide & Crisis Lifeline); many countries have free, "
    "confidential helplines too. You don't have to face this alone."
)


# ---------------------------------------------------------------------------
# Deterministic fallback lexicon (used when no ML classifier is loaded)
# ---------------------------------------------------------------------------
# Patterns are intentionally conservative. They are a *floor*, not a ceiling — the gate
# fails closed, so the cost of a false positive (block/escalate) is acceptable for safety.
_CRISIS_PATTERNS = [
    r"\bkill myself\b",
    r"\bkilling myself\b",
    r"\bend my life\b",
    r"\bending my life\b",
    r"\bsuicid",  # suicide / suicidal
    r"\bself[\s-]?harm\b",
    r"\bcut myself\b",
    r"\bcutting myself\b",
    r"\bwant to die\b",
    r"\bdon'?t want to live\b",
    r"\bno reason to live\b",
    r"\boverdose\b",
    r"\btake my (own )?life\b",
]
_CATEGORY_PATTERNS: dict[RiskCategory, list[str]] = {
    RiskCategory.violence: [
        r"\bkill (you|him|her|them|everyone)\b",
        r"\bshoot up\b",
        r"\bhow to (make|build) (a )?(bomb|explosive)\b",
        r"\bhurt (you|him|her|them)\b",
    ],
    RiskCategory.hate: [
        r"\b(racial|ethnic) slur\b",
        r"\bgo back to your country\b",
    ],
    RiskCategory.harassment: [
        r"\bi will find you\b",
        r"\byou should die\b",
        r"\bworthless piece of\b",
    ],
    RiskCategory.sexual: [
        r"\bchild (porn|sexual)\b",  # child-safety: always block
        r"\bcsam\b",
    ],
    RiskCategory.illicit: [
        r"\bhow to (make|cook|synthesize) meth\b",
        r"\bbuy (cocaine|heroin|meth)\b",
    ],
    RiskCategory.abuse: [
        r"\bf+u+c+k+ you\b",
        r"\byou (are|re) (an? )?(idiot|moron|stupid)\b",
    ],
}


class TextClassifier(Protocol):
    """Interface a real moderation model must satisfy (lazy-loaded).

    Returns a mapping of category name → score in [0, 1]. Must include a ``self_harm``
    key for crisis detection. Implementations live behind ``load_classifier`` so heavy
    deps are never imported on a CPU-only box.
    """

    def score(self, text: str) -> dict[str, float]: ...


# Optional hook a deployment can set to inject a real classifier. Kept as a module-level
# callable (not an import) so nothing heavy loads unless explicitly wired.
load_classifier: Callable[[], TextClassifier] | None = None


class ModerationConfig:
    """Tunable thresholds + switches for the gate (fail-closed friendly defaults)."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        fail_closed: bool = True,
        crisis_threshold: float = 0.5,
        block_threshold: float = 0.5,
        crisis_guidance: str = CRISIS_GUIDANCE,
    ) -> None:
        self.enabled = enabled
        self.fail_closed = fail_closed
        self.crisis_threshold = crisis_threshold
        self.block_threshold = block_threshold
        self.crisis_guidance = crisis_guidance


# ---------------------------------------------------------------------------
# Deterministic fallback classifier
# ---------------------------------------------------------------------------
class _LexiconClassifier:
    """Deterministic keyword/regex classifier — the CPU-only fallback."""

    def __init__(self) -> None:
        self._crisis = [re.compile(p, re.IGNORECASE) for p in _CRISIS_PATTERNS]
        self._cats = {
            cat: [re.compile(p, re.IGNORECASE) for p in pats]
            for cat, pats in _CATEGORY_PATTERNS.items()
        }

    def score(self, text: str) -> dict[str, float]:
        scores: dict[str, float] = {}
        if any(rx.search(text) for rx in self._crisis):
            scores[RiskCategory.self_harm.value] = 1.0
        for cat, rxs in self._cats.items():
            if any(rx.search(text) for rx in rxs):
                scores[cat.value] = 1.0
        return scores


class ModerationGate:
    """First-class moderation gate for text and speech paths.

    Usage::

        gate = ModerationGate()
        decision = gate.moderate_text("some user text", session_id="s1")
        if not decision.allowed:
            ...  # block / escalate
    """

    def __init__(
        self,
        config: ModerationConfig | None = None,
        *,
        classifier: TextClassifier | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self.config = config or ModerationConfig()
        self._classifier = classifier
        self._classifier_loaded = classifier is not None
        self.audit = audit_log or AuditLog("moderation")

    # -- classifier lazy-load -------------------------------------------------
    def _get_classifier(self) -> TextClassifier:
        """Lazy-load the classifier; fall back to the deterministic lexicon."""
        if not self._classifier_loaded:
            if load_classifier is not None:
                try:
                    self._classifier = load_classifier()
                except Exception as exc:  # pragma: no cover - defensive, fail closed
                    _log.warning("classifier load failed, using lexicon fallback: %s", exc)
                    self._classifier = _LexiconClassifier()
            else:
                self._classifier = _LexiconClassifier()
            self._classifier_loaded = True
        assert self._classifier is not None
        return self._classifier

    # -- public API -----------------------------------------------------------
    def evaluate(self, text: str, *, path: str, session_id: str | None = None) -> ModerationOutcome:
        """Evaluate text on a given path ('text' or 'speech'); fail closed on error."""
        if not self.config.enabled:
            decision = ModerationDecision(allowed=True, reason="moderation_disabled")
            audit = self.audit.record(
                "moderate", "allow", path=path, session_id=session_id, disabled=True
            )
            return ModerationOutcome(decision=decision, path=path, audit_id=audit.audit_id)

        # Classify (fail closed on any classifier exception).
        try:
            scores = self._get_classifier().score(text or "")
        except Exception as exc:
            return self._fail_closed(path, session_id, repr(exc))

        # Crisis / self-harm takes precedence: surface support + escalate to human review.
        crisis_score = scores.get(RiskCategory.self_harm.value, 0.0)
        if crisis_score >= self.config.crisis_threshold:
            decision = ModerationDecision(
                allowed=False,
                category=RiskCategory.self_harm.value,
                escalate=True,
                reason="crisis_self_harm_detected",
            )
            audit = self.audit.record(
                f"moderate_{path}",
                "escalate",
                path=path,
                session_id=session_id,
                category=RiskCategory.self_harm.value,
                score=crisis_score,
            )
            return ModerationOutcome(
                decision=decision,
                path=path,
                scores=scores,
                crisis_guidance=self.config.crisis_guidance,
                audit_id=audit.audit_id,
            )

        # Other risk categories → block (no user-facing crisis guidance).
        flagged = {
            cat: sc
            for cat, sc in scores.items()
            if cat != RiskCategory.self_harm.value and sc >= self.config.block_threshold
        }
        if flagged:
            top = max(flagged, key=lambda k: flagged[k])
            decision = ModerationDecision(
                allowed=False,
                category=top,
                escalate=False,
                reason=f"blocked_{top}",
            )
            # Abuse logging: record the offending category + score for the abuse log.
            audit = self.audit.record(
                f"moderate_{path}",
                "block",
                path=path,
                session_id=session_id,
                category=top,
                score=flagged[top],
            )
            return ModerationOutcome(
                decision=decision, path=path, scores=scores, audit_id=audit.audit_id
            )

        # Clean.
        decision = ModerationDecision(allowed=True, reason="clean")
        audit = self.audit.record(f"moderate_{path}", "allow", path=path, session_id=session_id)
        return ModerationOutcome(
            decision=decision, path=path, scores=scores, audit_id=audit.audit_id
        )

    def _fail_closed(self, path: str, session_id: str | None, err: str) -> ModerationOutcome:
        """Deny + escalate when the classifier fails (uncertainty ⇒ deny)."""
        decision = ModerationDecision(
            allowed=False,
            category=RiskCategory.error.value,
            escalate=True,
            reason="classifier_error_fail_closed",
        )
        audit = self.audit.record(
            f"moderate_{path}",
            "escalate",
            path=path,
            session_id=session_id,
            category=RiskCategory.error.value,
            error=err,
        )
        return ModerationOutcome(
            decision=decision, path=path, crisis_guidance=None, audit_id=audit.audit_id
        )

    # -- convenience wrappers returning the shared contract -------------------
    def moderate_text(self, text: str, *, session_id: str | None = None) -> ModerationDecision:
        """Text-path moderation → shared ``ModerationDecision``."""
        return self.evaluate(text, path="text", session_id=session_id).decision

    def moderate_speech(
        self, transcript: str, *, session_id: str | None = None
    ) -> ModerationDecision:
        """Speech-path moderation over an STT transcript → ``ModerationDecision``.

        The aux STT path (Phase 7A) transcribes spoken turns; the same classifier runs so
        spoken and typed content are held to identical safety standards.
        """
        return self.evaluate(transcript, path="speech", session_id=session_id).decision


# ---------------------------------------------------------------------------
# Module-level convenience (uses a shared default gate)
# ---------------------------------------------------------------------------
_default_gate: ModerationGate | None = None


def _gate() -> ModerationGate:
    global _default_gate
    if _default_gate is None:
        _default_gate = ModerationGate()
    return _default_gate


def moderate_text(text: str, *, session_id: str | None = None) -> ModerationDecision:
    """Module-level text-path moderation using the default gate."""
    return _gate().moderate_text(text, session_id=session_id)


def moderate_speech(transcript: str, *, session_id: str | None = None) -> ModerationDecision:
    """Module-level speech-path moderation using the default gate."""
    return _gate().moderate_speech(transcript, session_id=session_id)
