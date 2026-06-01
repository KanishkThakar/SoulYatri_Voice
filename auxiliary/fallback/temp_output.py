"""
aux/fallback/temp_output.py — Temporary speech-output adapter (Phase 13B)
=========================================================================
A temporary text-to-speech output path for the classic baseline / degraded mode.

⚠️  NOT FINAL ARCHITECTURE.
    The canonical SoulYatri product is speech-native (Mimi → Moshi → fast decoder,
    final_use.md §2.1). This adapter exists ONLY so the fallback baseline can emit
    audible audio during bring-up, comparison, and degraded mode. It is XTTS /
    OpenVoice-class output isolated behind a stable interface and must never be
    mistaken for the long-term runtime.

Design:
  * ``SpeechOutputAdapter`` is the stable interface the baseline depends on.
  * ``EdgeTTSAdapter`` wraps the existing ``server/pipeline/tts.py`` (edge-tts) by
    *import*, without modifying it. It is lazy: edge-tts/pydub are only imported
    when synthesis is actually attempted.
  * ``StubSpeechOutput`` is a deterministic, dependency-free adapter that returns
    silent PCM sized to the text, so the path works on a CPU-only box and in tests.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Any, Protocol

from auxiliary.text_brain.obs import get_logger, telemetry

logger = get_logger(__name__)

# Marker constant so other modules / docs can assert the temporary status.
IS_FINAL_ARCHITECTURE = False
ADAPTER_NOTE = (
    "TEMPORARY fallback TTS (XTTS/OpenVoice/edge-tts class). NOT the speech-native "
    "core. See final_use.md §13B and §1.2."
)

DEFAULT_SAMPLE_RATE = 24000  # matches server/pipeline/tts.py output


@dataclass
class SpeechOutput:
    """Synthesized speech result from a fallback adapter."""

    pcm: bytes
    sample_rate: int
    duration_s: float
    voice: str
    language: str
    backend: str
    is_stub: bool = False
    is_final_architecture: bool = False  # always False for this module

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_rate": self.sample_rate,
            "duration_s": self.duration_s,
            "voice": self.voice,
            "language": self.language,
            "backend": self.backend,
            "is_stub": self.is_stub,
            "is_final_architecture": self.is_final_architecture,
            "pcm_bytes": len(self.pcm),
        }


class SpeechOutputAdapter(Protocol):
    """Stable interface for a temporary speech-output backend."""

    name: str

    async def synthesize(self, text: str, language: str | None = None) -> SpeechOutput: ...


def _detect_language(text: str) -> str:
    """Devanagari/Hinglish heuristic, mirroring server EdgeTTS.detect_language."""
    hindi_chars = sum(1 for c in text if "\u0900" <= c <= "\u097f")
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha and (hindi_chars / total_alpha) > 0.3:
        return "hi"
    markers = {"acha", "theek", "haan", "nahi", "kya", "hai", "kaise", "yaar", "bhai"}
    if len(set(text.lower().split()) & markers) >= 2:
        return "hi"
    return "en"


class StubSpeechOutput:
    """Deterministic silent-PCM output adapter (no external deps).

    Produces 16-bit silent PCM whose length is proportional to the text length, at a
    nominal speaking rate. This keeps the fallback path fully exercisable on a
    CPU-only box and in CI without edge-tts/pydub/network.
    """

    name = "stub-tts"

    # ~12 characters per second of speech is a rough but stable estimate.
    _CHARS_PER_SECOND = 12.0

    async def synthesize(self, text: str, language: str | None = None) -> SpeechOutput:
        lang = language or _detect_language(text)
        text = text or ""
        duration_s = round(max(0.0, len(text)) / self._CHARS_PER_SECOND, 3)
        n_samples = int(duration_s * DEFAULT_SAMPLE_RATE)
        # 16-bit silence.
        pcm = struct.pack(f"<{n_samples}h", *([0] * n_samples)) if n_samples else b""
        telemetry.record(
            "aux_fallback_tts", backend=self.name, is_stub=True, duration_s=duration_s, lang=lang
        )
        logger.info("aux_fallback_tts_stub", chars=len(text), duration_s=duration_s, lang=lang)
        return SpeechOutput(
            pcm=pcm,
            sample_rate=DEFAULT_SAMPLE_RATE,
            duration_s=duration_s,
            voice=f"stub-{lang}",
            language=lang,
            backend=self.name,
            is_stub=True,
            is_final_architecture=False,
        )


class EdgeTTSAdapter:
    """Adapter over the existing ``server/pipeline/tts.py`` EdgeTTS (lazy).

    Reuses the server baseline by import; never edits it. If edge-tts / pydub are
    unavailable (or synthesis raises), the caller should fall back to the stub. We
    keep that decision in :func:`make_speech_output`.
    """

    name = "edge-tts"

    def __init__(self) -> None:
        self._engine: Any = None

    def _ensure_engine(self) -> Any:
        if self._engine is None:
            from server.pipeline.tts import EdgeTTS  # noqa: PLC0415 (lazy/optional)

            self._engine = EdgeTTS()
        return self._engine

    async def synthesize(self, text: str, language: str | None = None) -> SpeechOutput:
        engine = self._ensure_engine()
        start = time.perf_counter()
        result = await engine.synthesize(text, language=language)
        telemetry.record(
            "aux_fallback_tts",
            backend=self.name,
            is_stub=False,
            duration_s=result.duration,
            lang=result.language,
        )
        logger.info(
            "aux_fallback_tts_edge",
            chars=len(text),
            duration_s=result.duration,
            voice=result.voice,
            wall_ms=int((time.perf_counter() - start) * 1000),
        )
        return SpeechOutput(
            pcm=result.audio,
            sample_rate=result.sample_rate,
            duration_s=result.duration,
            voice=result.voice,
            language=result.language,
            backend=self.name,
            is_stub=False,
            is_final_architecture=False,
        )


def make_speech_output(prefer_real: bool = True) -> SpeechOutputAdapter:
    """Construct the best available temporary speech-output adapter.

    Falls back to :class:`StubSpeechOutput` when edge-tts/pydub are not importable,
    so the fallback path always yields a usable adapter on CPU-only machines.
    """
    if not prefer_real:
        return StubSpeechOutput()
    try:
        import importlib.util

        if importlib.util.find_spec("edge_tts") is None:
            raise ImportError("edge_tts not installed")
        if importlib.util.find_spec("pydub") is None:
            raise ImportError("pydub not installed")
        return EdgeTTSAdapter()
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning("aux_fallback_tts_stub_selected", error=str(e))
        return StubSpeechOutput()
