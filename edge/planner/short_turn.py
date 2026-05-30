"""
edge/planner/short_turn.py — Short-turn classifier (Phase 8A)
=============================================================
Owner: edge/runtime agent (final_use.md §4, Phase 8A).

Detects trivial / short / emotional / uncertain turns and attaches route confidence,
producing a :class:`shared.contracts.RouteDecision`. The decision feeds the filler /
speculation subsystem so short turns shave time-to-first-audio (TTFA) without a large
error rate.

CPU/no-weights: this is a deterministic lexical + signal classifier. It accepts an
optional partial transcript (from the tiny client ASR/KWS, final_use.md Phase-3) and an
optional :class:`EmotionState` window. No heavy models are required; everything is
explicit and auditable (each decision carries a human-readable ``reason``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from edge.session.logging_hooks import get_logger
from shared.contracts import EmotionState, RouteDecision, RouteTarget

logger = get_logger(__name__)


class TurnClass(str, Enum):
    """Coarse turn categories used to pick a route."""

    trivial = "trivial"          # greetings / acks → cached filler can fully handle it.
    short = "short"              # short factual/closed turn → full stack but fast.
    emotional = "emotional"      # affect-heavy → empathetic handling, do not shortcut.
    uncertain = "uncertain"      # low ASR/intent confidence → forward, no speculation.
    complex = "complex"          # long / multi-clause → full stack, no shortcut.


# Small, bounded keyword banks (English + Hinglish + Hindi transliterations).
_TRIVIAL_PHRASES: frozenset[str] = frozenset(
    {
        "hi", "hello", "hey", "yo", "hii", "helo",
        "namaste", "namaskar",
        "thanks", "thank you", "thx", "shukriya", "dhanyavaad",
        "ok", "okay", "okk", "thik hai", "theek hai", "haan", "ha", "yes",
        "no", "nahi", "nope",
        "bye", "goodbye", "see you", "alvida",
        "good morning", "good night", "good evening",
        "acha", "accha", "great", "cool", "nice",
    }
)

_ACK_TOKENS: frozenset[str] = frozenset(
    {"ok", "okay", "okk", "haan", "ha", "yes", "yeah", "yep", "hmm", "hm", "right", "sure"}
)

_EMOTIONAL_TOKENS: frozenset[str] = frozenset(
    {
        "sad", "happy", "angry", "scared", "afraid", "worried", "anxious", "lonely",
        "depressed", "stressed", "upset", "excited", "love", "hate", "cry", "crying",
        "tired", "frustrated", "udaas", "khush", "pareshaan", "dukhi", "akela",
        "darr", "gussa", "rona", "thak",
    }
)

_QUESTION_MARKERS: frozenset[str] = frozenset(
    {"what", "why", "how", "when", "where", "who", "which", "kya", "kyun", "kaise", "kab", "kaha", "kahan"}
)

# Single-token trivial vocabulary, derived so multi-word phrases (e.g. "thik hai")
# also match when their individual tokens appear in a short turn.
_TRIVIAL_TOKENS: frozenset[str] = frozenset(
    word for phrase in (_TRIVIAL_PHRASES | _ACK_TOKENS) for word in phrase.split()
)


@dataclass
class ShortTurnResult:
    """Classifier output: the category, confidence, and the derived ``RouteDecision``."""

    turn_class: TurnClass
    confidence: float
    route: RouteDecision

    def to_dict(self) -> dict:
        return {
            "turn_class": self.turn_class.value,
            "confidence": round(self.confidence, 4),
            "route": self.route.model_dump(),
        }


class ShortTurnClassifier:
    """Deterministic short-turn classifier feeding ``RouteDecision``.

    Args:
        trivial_max_words: turns at/under this word count are eligible to be "trivial".
        short_max_words: turns at/under this word count (but above trivial) are "short".
        min_asr_confidence: below this, the turn is treated as "uncertain".
        emotional_arousal_gate: emotion arousal/|valence| above this flags "emotional".
    """

    def __init__(
        self,
        *,
        trivial_max_words: int = 3,
        short_max_words: int = 8,
        min_asr_confidence: float = 0.45,
        emotional_arousal_gate: float = 0.55,
    ) -> None:
        self._trivial_max_words = trivial_max_words
        self._short_max_words = short_max_words
        self._min_asr_confidence = min_asr_confidence
        self._emotional_gate = emotional_arousal_gate

    def classify(
        self,
        transcript: str = "",
        *,
        asr_confidence: float = 1.0,
        emotion: EmotionState | None = None,
        speech_duration_ms: int | None = None,
    ) -> ShortTurnResult:
        """Classify a (possibly partial) turn and produce a routing decision.

        Args:
            transcript: Best-effort partial transcript from the tiny local ASR/KWS.
            asr_confidence: Confidence of that transcript in [0, 1].
            emotion: Optional emotion window for the turn.
            speech_duration_ms: Optional measured speech duration.

        Returns:
            A :class:`ShortTurnResult` with category, confidence and ``RouteDecision``.
        """
        normalized = " ".join(transcript.lower().split())
        tokens = normalized.split()
        word_count = len(tokens)
        token_set = set(tokens)

        emotional_signal = self._emotional_signal(token_set, emotion)
        is_question = bool(token_set & _QUESTION_MARKERS) or normalized.endswith("?")

        # 1) Uncertain dominates: if we don't trust the transcript, never shortcut.
        if normalized and asr_confidence < self._min_asr_confidence:
            return self._build(
                TurnClass.uncertain,
                confidence=1.0 - asr_confidence,
                route=RouteTarget.full_stack,
                intent="uncertain",
                reason=f"asr_confidence {asr_confidence:.2f} < {self._min_asr_confidence:.2f}",
            )

        # 2) Strong emotion → empathetic handling via full stack (no trivial shortcut),
        #    but allow an empathetic filler to be emitted while forwarding.
        if emotional_signal >= self._emotional_gate:
            return self._build(
                TurnClass.emotional,
                confidence=min(1.0, emotional_signal),
                route=RouteTarget.full_stack,
                intent="emotional",
                reason=f"emotional_signal {emotional_signal:.2f} >= {self._emotional_gate:.2f}",
                emit_filler_then_forward=True,
            )

        # 3) Trivial: very short AND a known greeting/ack/closer, not a question.
        if word_count > 0 and word_count <= self._trivial_max_words and not is_question:
            if normalized in _TRIVIAL_PHRASES or token_set <= _TRIVIAL_TOKENS:
                intent = "acknowledgement" if token_set & _ACK_TOKENS else "greeting"
                return self._build(
                    TurnClass.trivial,
                    confidence=0.9,
                    route=RouteTarget.cached_filler,
                    intent=intent,
                    reason=f"trivial phrase ({word_count} words, intent={intent})",
                    phrase_id=f"{intent}_default",
                )

        # 4) Short: small turn → full stack but flagged for fast/speculative onset.
        if word_count > 0 and word_count <= self._short_max_words:
            return self._build(
                TurnClass.short,
                confidence=0.7,
                route=RouteTarget.full_stack,
                intent="short_query" if is_question else "short_statement",
                reason=f"short turn ({word_count} words)",
                emit_filler_then_forward=True,
            )

        # 5) Empty transcript but we have audio → forward, let the full stack decide.
        if word_count == 0:
            # Use duration as a weak prior: very short audio is likely trivial/ack.
            if speech_duration_ms is not None and speech_duration_ms <= 600:
                return self._build(
                    TurnClass.trivial,
                    confidence=0.4,
                    route=RouteTarget.cached_filler,
                    intent="acknowledgement",
                    reason=f"no transcript, short audio {speech_duration_ms}ms",
                    phrase_id="acknowledgement_default",
                )
            return self._build(
                TurnClass.uncertain,
                confidence=0.5,
                route=RouteTarget.full_stack,
                intent="unknown",
                reason="no transcript available",
            )

        # 6) Default: complex / long → full stack, no shortcut.
        return self._build(
            TurnClass.complex,
            confidence=0.6,
            route=RouteTarget.full_stack,
            intent="complex",
            reason=f"long/complex turn ({word_count} words)",
        )

    def _emotional_signal(self, token_set: set[str], emotion: EmotionState | None) -> float:
        lexical = 1.0 if token_set & _EMOTIONAL_TOKENS else 0.0
        signal = lexical * 0.6
        if emotion is not None:
            affect = max(abs(emotion.valence), emotion.arousal)
            # Weight by the emotion estimate's own confidence so silence doesn't trip it.
            signal = max(signal, affect * emotion.confidence)
        return signal

    def _build(
        self,
        turn_class: TurnClass,
        *,
        confidence: float,
        route: RouteTarget,
        intent: str,
        reason: str,
        phrase_id: str | None = None,
        emit_filler_then_forward: bool = False,
    ) -> ShortTurnResult:
        decision = RouteDecision(
            route=route,
            phrase_id=phrase_id,
            intent=intent,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            reason=reason,
            emit_filler_then_forward=emit_filler_then_forward,
        )
        logger.debug(
            "short_turn_classified",
            turn_class=turn_class.value,
            intent=intent,
            route=route.value,
            confidence=decision.confidence,
        )
        return ShortTurnResult(turn_class=turn_class, confidence=decision.confidence, route=decision)
