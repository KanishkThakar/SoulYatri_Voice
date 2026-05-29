"""
SoulYatri Speech — Filler Phrase System
=========================================
Server-side filler router that provides instant cached responses
for trivial turns (greetings, confirmations) and stall phrases
while the full pipeline processes complex requests.

Routing Policy:
- greeting detected → cached greeting (skip pipeline)
- confirmation detected → cached confirmation (skip pipeline)
- farewell detected → cached farewell (skip pipeline)
- complex / ambiguous → play stall filler + route to full pipeline
- emotional distress → empathy filler + route to full pipeline
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import filler_played, filler_hit_rate

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class FillerPhrase:
    """A single cached phrase."""

    id: str
    text: str
    language: str
    category: str  # acknowledgment, stall, greeting, confirmation, empathy, farewell
    tone: str
    intent: str
    priority: int
    min_confidence: float
    audio: Optional[bytes] = None  # Pre-synthesized PCM audio
    audio_sample_rate: int = 24000
    duration: float = 0.0


@dataclass
class RoutingDecision:
    """Decision from the filler router."""

    action: str  # "filler_only", "filler_then_pipeline", "pipeline_only"
    filler_phrase: Optional[FillerPhrase] = None
    intent: str = "unknown"
    confidence: float = 0.0
    reason: str = ""


class FillerPhraseBank:
    """In-memory phrase bank with pre-synthesized audio.

    Loads phrases from a JSON file and optionally pre-generates
    audio via edge-tts at startup for instant playback.
    """

    def __init__(self) -> None:
        self._phrases: list[FillerPhrase] = []
        self._by_category: dict[str, list[FillerPhrase]] = {}
        self._by_language: dict[str, list[FillerPhrase]] = {}
        self._intent_keywords: dict[str, dict[str, list[str]]] = {}
        self._initialized = False

    def load_phrases(self, json_path: Optional[str] = None) -> None:
        """Load phrases from the JSON phrase bank.

        Args:
            json_path: Path to phrases.json. Defaults to server/data/phrases.json.
        """
        if json_path is None:
            json_path = str(
                Path(__file__).parent.parent / "data" / "phrases.json"
            )

        logger.info("loading_phrase_bank", path=json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for phrase_data in data.get("phrases", []):
            phrase = FillerPhrase(
                id=phrase_data["id"],
                text=phrase_data["text"],
                language=phrase_data["language"],
                category=phrase_data["category"],
                tone=phrase_data["tone"],
                intent=phrase_data["intent"],
                priority=phrase_data["priority"],
                min_confidence=phrase_data["min_confidence"],
            )
            self._phrases.append(phrase)

            # Index by category
            if phrase.category not in self._by_category:
                self._by_category[phrase.category] = []
            self._by_category[phrase.category].append(phrase)

            # Index by language
            if phrase.language not in self._by_language:
                self._by_language[phrase.language] = []
            self._by_language[phrase.language].append(phrase)

        # Load intent keywords
        self._intent_keywords = data.get("intent_keywords", {})

        logger.info(
            "phrase_bank_loaded",
            total=len(self._phrases),
            categories=list(self._by_category.keys()),
            languages=list(self._by_language.keys()),
        )
        self._initialized = True

    async def pre_synthesize_audio(self) -> None:
        """Pre-generate TTS audio for all phrases at startup.

        This runs edge-tts for each phrase so playback is instant.
        """
        from ..pipeline.tts import EdgeTTS

        tts = EdgeTTS()
        synthesized = 0

        logger.info("pre_synthesizing_fillers", count=len(self._phrases))

        for phrase in self._phrases:
            try:
                result = await tts.synthesize(
                    text=phrase.text,
                    language=phrase.language,
                )
                if result.audio:
                    phrase.audio = result.audio
                    phrase.audio_sample_rate = result.sample_rate
                    phrase.duration = result.duration
                    synthesized += 1
            except Exception as e:
                logger.warning(
                    "filler_synthesis_failed",
                    phrase_id=phrase.id,
                    error=str(e),
                )

        logger.info(
            "filler_synthesis_complete",
            synthesized=synthesized,
            total=len(self._phrases),
        )

    def get_phrase(
        self,
        category: str,
        language: str = "en",
        tone: Optional[str] = None,
    ) -> Optional[FillerPhrase]:
        """Get a random phrase matching the criteria.

        Args:
            category: Phrase category (greeting, stall, etc.).
            language: Target language.
            tone: Optional tone filter.

        Returns:
            A matching FillerPhrase, or None.
        """
        candidates = self._by_category.get(category, [])

        # Filter by language
        candidates = [p for p in candidates if p.language == language]

        # Filter by tone if specified
        if tone and candidates:
            tone_matches = [p for p in candidates if p.tone == tone]
            if tone_matches:
                candidates = tone_matches

        # Filter to only phrases with pre-synthesized audio
        candidates = [p for p in candidates if p.audio]

        if not candidates:
            # Fallback: try any language
            candidates = [
                p
                for p in self._by_category.get(category, [])
                if p.audio
            ]

        if not candidates:
            return None

        return random.choice(candidates)

    @property
    def phrase_count(self) -> int:
        """Total number of loaded phrases."""
        return len(self._phrases)


class FillerRouter:
    """Classifies user utterances and decides the routing action.

    Uses keyword matching and heuristics to identify trivial turns
    that can be answered with cached phrases, vs. complex turns
    that need the full STT→LLM→TTS pipeline.
    """

    def __init__(self, phrase_bank: FillerPhraseBank) -> None:
        self._phrase_bank = phrase_bank

    def classify(
        self,
        text: str,
        language: str = "en",
        emotion_label: Optional[str] = None,
    ) -> RoutingDecision:
        """Classify a user utterance and decide the response strategy.

        Args:
            text: Transcribed user speech.
            language: Detected language.
            emotion_label: Optional emotion from Phase 2A emotion extractor.

        Returns:
            RoutingDecision with action and optional filler phrase.
        """
        text_lower = text.lower().strip()
        words = set(text_lower.split())
        word_count = len(text_lower.split())

        # --- Emotional distress → empathy filler + pipeline ---
        if emotion_label in ("sad", "angry", "fear"):
            filler = self._phrase_bank.get_phrase("empathy", language)
            return RoutingDecision(
                action="filler_then_pipeline",
                filler_phrase=filler,
                intent="emotional",
                confidence=0.7,
                reason=f"Detected emotion: {emotion_label}",
            )

        # --- Greeting detection ---
        intent_kw = self._phrase_bank._intent_keywords
        greeting_words = set(intent_kw.get("greeting", {}).get(language, []))
        greeting_words.update(intent_kw.get("greeting", {}).get("en", []))
        if words & greeting_words and word_count <= 5:
            filler = self._phrase_bank.get_phrase("greeting", language)
            if filler:
                filler_played.labels(category="greeting").inc()
                return RoutingDecision(
                    action="filler_only",
                    filler_phrase=filler,
                    intent="greeting",
                    confidence=0.85,
                    reason="Greeting keyword match",
                )

        # --- Farewell detection ---
        farewell_words = set(intent_kw.get("farewell", {}).get(language, []))
        farewell_words.update(intent_kw.get("farewell", {}).get("en", []))
        if words & farewell_words and word_count <= 5:
            filler = self._phrase_bank.get_phrase("farewell", language)
            if filler:
                filler_played.labels(category="farewell").inc()
                return RoutingDecision(
                    action="filler_only",
                    filler_phrase=filler,
                    intent="farewell",
                    confidence=0.85,
                    reason="Farewell keyword match",
                )

        # --- Confirmation detection ---
        confirm_words = set(intent_kw.get("confirmation", {}).get(language, []))
        confirm_words.update(intent_kw.get("confirmation", {}).get("en", []))
        if words & confirm_words and word_count <= 3:
            filler = self._phrase_bank.get_phrase("confirmation", language)
            if filler:
                filler_played.labels(category="confirmation").inc()
                return RoutingDecision(
                    action="filler_only",
                    filler_phrase=filler,
                    intent="confirmation",
                    confidence=0.8,
                    reason="Confirmation keyword match",
                )

        # --- Acknowledgment detection ---
        ack_words = set(intent_kw.get("acknowledgment", {}).get(language, []))
        ack_words.update(intent_kw.get("acknowledgment", {}).get("en", []))
        if words & ack_words and word_count <= 2:
            filler = self._phrase_bank.get_phrase("acknowledgment", language)
            if filler:
                filler_played.labels(category="acknowledgment").inc()
                return RoutingDecision(
                    action="filler_only",
                    filler_phrase=filler,
                    intent="acknowledgment",
                    confidence=0.75,
                    reason="Acknowledgment keyword match",
                )

        # --- Default: complex turn → stall filler + full pipeline ---
        stall_filler = self._phrase_bank.get_phrase("stall", language)
        if stall_filler:
            filler_played.labels(category="stall").inc()

        return RoutingDecision(
            action="filler_then_pipeline",
            filler_phrase=stall_filler,
            intent="complex",
            confidence=0.0,
            reason="No trivial match, routing to full pipeline",
        )
