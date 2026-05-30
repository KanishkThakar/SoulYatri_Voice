"""
aux/fallback/classic_baseline.py — Classic STT→LLM→TTS baseline (Phase 13A)
===========================================================================
Wires the classic, non-speech-native path:

    VAD → STT → text-LLM → TTS

as a **baseline / fallback** for logs, bring-up, comparison, and degraded mode
(final_use.md §Phase-13A).

⚠️  This is explicitly a fallback path. The canonical product is the speech-native
    Mimi→Moshi loop (final_use.md §1.2, §2.1). This composition exists so a
    minimal end-to-end product can run during incidents/bring-up and so we have a
    quality/latency reference to compare the speech-native core against.

Composition strategy:
  * Reuse the server pipeline wrappers by *import* where available
    (``server.pipeline.stt``, ``server.pipeline.vad``), without modifying them.
  * Use the auxiliary, CPU-safe components for STT (``aux.stt.transcript_service``)
    and TTS (``aux.fallback.temp_output``) so the whole baseline runs and tests on
    a CPU-only box with no GPU/weights/Ollama.
  * The text step uses ``aux.text_brain`` only as a lightweight reply composer in
    the stub case; in a real deployment this would call the conversational LLM.
    (The text brain remains AUXILIARY — see DECISIONS.md D-002.)

Everything is async and degradation-safe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from auxiliary.fallback.temp_output import SpeechOutput, SpeechOutputAdapter, make_speech_output
from auxiliary.stt.transcript_service import (
    SAMPLE_RATE_16K,
    TranscriberBackend,
    TranscriptResult,
    TranscriptService,
)
from auxiliary.text_brain.obs import get_logger, telemetry

logger = get_logger(__name__)


@dataclass
class BaselineStageTimings:
    """Per-stage wall-clock timings (ms) for observability/comparison."""

    vad_ms: int = 0
    stt_ms: int = 0
    llm_ms: int = 0
    tts_ms: int = 0
    total_ms: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "vad_ms": self.vad_ms,
            "stt_ms": self.stt_ms,
            "llm_ms": self.llm_ms,
            "tts_ms": self.tts_ms,
            "total_ms": self.total_ms,
        }


@dataclass
class BaselineResult:
    """Result of one full pass through the classic baseline."""

    transcript: TranscriptResult
    reply_text: str
    speech: SpeechOutput
    timings: BaselineStageTimings
    is_final_architecture: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript.to_dict(),
            "reply_text": self.reply_text,
            "speech": self.speech.to_dict(),
            "timings": self.timings.to_dict(),
            "is_final_architecture": self.is_final_architecture,
            "notes": self.notes,
        }


class ReplyComposer:
    """Minimal text reply step for the baseline.

    In production this would call the conversational LLM. For CPU-only bring-up we
    compose a short, safe acknowledgement deterministically. Kept separate so it can
    be swapped for a real model client without touching the composition logic.
    """

    async def compose(self, transcript: TranscriptResult) -> str:
        text = (transcript.text or "").strip()
        if not text:
            return "Sorry, I didn't catch that. Could you say it again?"
        # Deterministic, bounded acknowledgement (voice-appropriate, short).
        snippet = text if len(text) <= 80 else text[:77] + "..."
        if transcript.language == "hi":
            return f"Theek hai, samajh gaya: {snippet}"
        return f"Got it — you said: {snippet}"


class ClassicBaseline:
    """The composed VAD→STT→LLM→TTS fallback pipeline.

    Construct with ``await ClassicBaseline.create()`` (or instantiate and use the
    async context manager) so the internal transcript-service workers start/stop
    cleanly.
    """

    def __init__(
        self,
        *,
        stt_service: TranscriptService | None = None,
        tts_adapter: SpeechOutputAdapter | None = None,
        composer: ReplyComposer | None = None,
        prefer_real_components: bool = True,
    ) -> None:
        self._stt = stt_service or TranscriptService(prefer_whisper=prefer_real_components)
        self._tts = tts_adapter or make_speech_output(prefer_real=prefer_real_components)
        self._composer = composer or ReplyComposer()
        self._started = False

    async def start(self) -> None:
        if not self._started:
            await self._stt.start()
            self._started = True

    async def stop(self) -> None:
        if self._started:
            await self._stt.stop()
            self._started = False

    async def __aenter__(self) -> ClassicBaseline:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop()

    @property
    def stt_backend(self) -> str:
        return self._stt.backend_name

    @property
    def tts_backend(self) -> str:
        return self._tts.name

    def detect_segments(self, audio_f32: Any) -> int:
        """Optional VAD step (reuses server SileroVAD if available).

        Returns the number of speech segments found, or -1 when VAD is unavailable
        (the common CPU-only case). The baseline does not require VAD to run; this
        exists for parity/observability when torch + the model are present.
        """
        try:
            from server.pipeline.vad import SileroVAD, VADConfig  # noqa: PLC0415

            vad = SileroVAD(VADConfig())
            vad.load_model()
            segments = vad.process_audio(audio_f32)
            return len(segments)
        except Exception as e:
            logger.info("aux_baseline_vad_skipped", reason=str(e))
            return -1

    async def run(
        self,
        pcm_bytes: bytes,
        *,
        sample_rate: int = SAMPLE_RATE_16K,
        language: str | None = None,
    ) -> BaselineResult:
        """Run one full VAD→STT→LLM→TTS pass over a PCM16 buffer."""
        if not self._started:
            await self.start()

        notes: list[str] = []
        timings = BaselineStageTimings()
        t0 = time.perf_counter()

        # --- STT -----------------------------------------------------------
        t = time.perf_counter()
        transcript = await self._stt.transcribe(
            pcm_bytes, sample_rate=sample_rate, language=language, purpose="fallback"
        )
        timings.stt_ms = int((time.perf_counter() - t) * 1000)
        if transcript.is_stub:
            notes.append("stt:stub")

        # --- LLM (reply composition) --------------------------------------
        t = time.perf_counter()
        reply = await self._composer.compose(transcript)
        timings.llm_ms = int((time.perf_counter() - t) * 1000)

        # --- TTS -----------------------------------------------------------
        t = time.perf_counter()
        speech = await self._tts.synthesize(reply, language=transcript.language)
        timings.tts_ms = int((time.perf_counter() - t) * 1000)
        if speech.is_stub:
            notes.append("tts:stub")

        timings.total_ms = int((time.perf_counter() - t0) * 1000)

        telemetry.record(
            "aux_baseline_run",
            stt_backend=transcript.backend,
            tts_backend=speech.backend,
            total_ms=timings.total_ms,
            degraded=bool(notes),
        )
        logger.info(
            "aux_baseline_complete",
            stt_backend=transcript.backend,
            tts_backend=speech.backend,
            total_ms=timings.total_ms,
            reply_chars=len(reply),
        )

        return BaselineResult(
            transcript=transcript,
            reply_text=reply,
            speech=speech,
            timings=timings,
            is_final_architecture=False,
            notes=notes,
        )

    @classmethod
    async def create(cls, **kwargs: Any) -> ClassicBaseline:
        """Construct and start a baseline ready for ``run``."""
        baseline = cls(**kwargs)
        await baseline.start()
        return baseline


__all__ = [
    "ClassicBaseline",
    "BaselineResult",
    "BaselineStageTimings",
    "ReplyComposer",
    "TranscriberBackend",
]
