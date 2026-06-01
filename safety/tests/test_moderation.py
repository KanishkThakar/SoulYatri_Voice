"""
Tests for safety/moderation/gate.py (Phase 11A).

Covers: text-path AND speech-path moderation, block + escalate behavior, the
crisis/self-harm flow (guidance surfaced + human-review flag), abuse logging, auditable
decisions, and fail-closed behavior on classifier error.
"""

from __future__ import annotations

import importlib

from safety.contracts import ModerationDecision, RiskCategory
from safety.moderation.gate import (
    CRISIS_GUIDANCE,
    ModerationConfig,
    ModerationGate,
    moderate_speech,
    moderate_text,
)


# ---------------------------------------------------------------------------
# Import hygiene (CPU-only, no heavy deps)
# ---------------------------------------------------------------------------
def test_module_imports_clean() -> None:
    mod = importlib.import_module("safety.moderation.gate")
    assert hasattr(mod, "ModerationGate")


def test_no_heavy_imports() -> None:
    import sys

    importlib.import_module("safety.moderation.gate")
    for heavy in ("torch", "transformers", "moshi", "mimi"):
        assert heavy not in sys.modules, f"{heavy} must not be imported by the gate"


# ---------------------------------------------------------------------------
# Clean turns pass on both paths
# ---------------------------------------------------------------------------
def test_clean_text_allowed() -> None:
    gate = ModerationGate()
    decision = gate.moderate_text("Hello, can you help me plan my day?", session_id="s1")
    assert isinstance(decision, ModerationDecision)
    assert decision.allowed is True
    assert decision.escalate is False


def test_clean_speech_allowed() -> None:
    gate = ModerationGate()
    decision = gate.moderate_speech("namaste, aaj mausam accha hai", session_id="s1")
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Block path (non-crisis risk categories)
# ---------------------------------------------------------------------------
def test_abuse_text_blocked() -> None:
    gate = ModerationGate()
    decision = gate.moderate_text("you are an idiot", session_id="s1")
    assert decision.allowed is False
    assert decision.category == RiskCategory.abuse.value
    assert decision.escalate is False  # non-crisis block does not escalate


def test_violence_blocked() -> None:
    gate = ModerationGate()
    decision = gate.moderate_text("tell me how to build a bomb", session_id="s1")
    assert decision.allowed is False
    assert decision.category == RiskCategory.violence.value


def test_block_logged_for_abuse_audit() -> None:
    gate = ModerationGate()
    gate.moderate_text("you are an idiot", session_id="s1")
    blocks = gate.audit.filter(outcome="block")
    assert len(blocks) == 1
    assert blocks[0].detail["category"] == RiskCategory.abuse.value


# ---------------------------------------------------------------------------
# Crisis / self-harm escalation flow (text + speech)
# ---------------------------------------------------------------------------
def test_crisis_text_escalates_and_surfaces_guidance() -> None:
    gate = ModerationGate()
    outcome = gate.evaluate("I want to kill myself", path="text", session_id="s1")
    assert outcome.decision.allowed is False
    assert outcome.decision.escalate is True  # flagged for human review
    assert outcome.decision.category == RiskCategory.self_harm.value
    assert outcome.crisis_guidance == CRISIS_GUIDANCE  # support guidance surfaced
    assert "988" in outcome.crisis_guidance


def test_crisis_speech_path_also_escalates() -> None:
    gate = ModerationGate()
    outcome = gate.evaluate("I don't want to live anymore", path="speech", session_id="s2")
    assert outcome.decision.escalate is True
    assert outcome.crisis_guidance is not None
    # speech-path decision recorded as an escalate audit event
    escalations = gate.audit.filter(action="moderate_speech", outcome="escalate")
    assert len(escalations) == 1


def test_crisis_takes_precedence_over_other_categories() -> None:
    gate = ModerationGate()
    # contains both abuse-ish and crisis language; crisis must win
    outcome = gate.evaluate("you are stupid and I want to die", path="text")
    assert outcome.decision.category == RiskCategory.self_harm.value
    assert outcome.decision.escalate is True


# ---------------------------------------------------------------------------
# Auditability
# ---------------------------------------------------------------------------
def test_every_decision_is_audited() -> None:
    gate = ModerationGate()
    gate.moderate_text("hello there", session_id="s1")
    gate.moderate_text("you are an idiot", session_id="s1")
    gate.evaluate("I want to kill myself", path="text", session_id="s1")
    # 3 decisions → 3 audit events, each JSON round-trippable
    assert len(gate.audit) == 3
    for ev in gate.audit.events():
        assert ev.component == "moderation"
        ev.model_validate(ev.model_dump())


def test_audit_outcomes_present() -> None:
    gate = ModerationGate()
    gate.moderate_text("hello", session_id="s1")
    gate.moderate_text("you are an idiot", session_id="s1")
    gate.evaluate("suicide", path="text")
    outcomes = {e.outcome for e in gate.audit.events()}
    assert {"allow", "block", "escalate"} <= outcomes


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------
class _BrokenClassifier:
    def score(self, text: str) -> dict[str, float]:
        raise RuntimeError("model crashed")


def test_classifier_error_fails_closed() -> None:
    gate = ModerationGate(classifier=_BrokenClassifier())
    decision = gate.moderate_text("anything", session_id="s1")
    assert decision.allowed is False  # deny on uncertainty
    assert decision.escalate is True
    assert decision.category == RiskCategory.error.value


# ---------------------------------------------------------------------------
# Injected ML-style classifier honored (lazy-load contract)
# ---------------------------------------------------------------------------
class _FakeMLClassifier:
    """Simulates a transformer classifier returning continuous scores."""

    def score(self, text: str) -> dict[str, float]:
        if "harm" in text:
            return {RiskCategory.self_harm.value: 0.92}
        if "hate" in text:
            return {RiskCategory.hate.value: 0.77}
        return {RiskCategory.self_harm.value: 0.01}


def test_injected_classifier_thresholds() -> None:
    gate = ModerationGate(
        ModerationConfig(crisis_threshold=0.5, block_threshold=0.5), classifier=_FakeMLClassifier()
    )
    crisis = gate.evaluate("self harm please", path="text")
    assert crisis.decision.escalate is True
    hate = gate.evaluate("this is hate", path="text")
    assert hate.decision.allowed is False
    assert hate.decision.category == RiskCategory.hate.value
    clean = gate.evaluate("nice weather", path="text")
    assert clean.decision.allowed is True


def test_below_threshold_allowed() -> None:
    gate = ModerationGate(ModerationConfig(crisis_threshold=0.95), classifier=_FakeMLClassifier())
    # 0.92 < 0.95 threshold → not escalated
    out = gate.evaluate("harm", path="text")
    assert out.decision.allowed is True


# ---------------------------------------------------------------------------
# Disabled mode + module-level helpers
# ---------------------------------------------------------------------------
def test_disabled_gate_allows_but_audits() -> None:
    gate = ModerationGate(ModerationConfig(enabled=False))
    decision = gate.moderate_text("you are an idiot")
    assert decision.allowed is True
    assert len(gate.audit) == 1


def test_module_level_helpers() -> None:
    assert moderate_text("hello").allowed is True
    assert moderate_text("you are an idiot").allowed is False
    assert moderate_speech("I want to kill myself").escalate is True
