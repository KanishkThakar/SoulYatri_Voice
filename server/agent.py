"""
SoulYatri Speech — Voice Agent
=================================
Orchestrates the full voice pipeline: VAD → STT → LLM → TTS.
Connects to a LiveKit room as a participant, subscribes to user audio,
processes it through the pipeline, and publishes audio responses.

This is a standalone WebSocket-based agent that works with LiveKit
for WebRTC transport, but can also operate independently for testing.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import numpy as np

from .config import settings
from .pipeline.vad import SileroVAD, VADConfig
from .pipeline.stt import WhisperSTT
from .pipeline.llm import OllamaLLM
from .pipeline.tts import EdgeTTS
from .pipeline.session import SessionManager, SessionState
from .utils.audio import (
    pcm_to_float32,
    float32_to_pcm16,
    resample,
    SAMPLE_RATE_16K,
    SAMPLE_RATE_48K,
)
from .utils.logging_config import get_logger
from .utils.metrics import (
    pipeline_e2e_latency,
    active_streams,
    errors_total,
)

logger = get_logger(__name__)


class VoiceAgent:
    """Main voice agent that orchestrates the full pipeline.

    Lifecycle:
        1. initialize() — load all models
        2. handle_audio_frame() — process incoming audio frames
        3. shutdown() — cleanup resources

    The agent maintains per-session state and processes audio
    through VAD → STT → LLM → TTS in sequence.
    """

    def __init__(self) -> None:
        # Pipeline components
        self._vad = SileroVAD(VADConfig())
        self._stt = WhisperSTT()
        self._llm = OllamaLLM()
        self._tts = EdgeTTS()
        self._session_manager = SessionManager()

        # State
        self._initialized = False
        self._processing_lock = asyncio.Lock()

        # Audio response callback — set by the server
        self._on_audio_response: Optional[callable] = None
        self._on_transcript: Optional[callable] = None

    async def initialize(self) -> None:
        """Initialize all pipeline components. Call once at startup."""
        logger.info("agent_initializing")

        # Load models (these are CPU/GPU bound, run in executor)
        loop = asyncio.get_event_loop()

        # Load VAD and STT in parallel (they're independent)
        await asyncio.gather(
            loop.run_in_executor(None, self._vad.load_model),
            loop.run_in_executor(None, self._stt.load_model),
        )

        # Initialize async LLM client
        await self._llm.initialize()

        self._initialized = True
        logger.info("agent_initialized")

    async def shutdown(self) -> None:
        """Shutdown and cleanup resources."""
        logger.info("agent_shutting_down")
        await self._llm.close()
        self._initialized = False
        logger.info("agent_shutdown_complete")

    def set_audio_callback(self, callback: callable) -> None:
        """Set callback for audio responses.

        Args:
            callback: async function(session_id: str, audio_bytes: bytes, sample_rate: int)
        """
        self._on_audio_response = callback

    def set_transcript_callback(self, callback: callable) -> None:
        """Set callback for transcript updates.

        Args:
            callback: async function(session_id: str, role: str, text: str)
        """
        self._on_transcript = callback

    async def handle_audio_frame(
        self,
        session_id: str,
        audio_bytes: bytes,
        sample_rate: int = SAMPLE_RATE_48K,
    ) -> None:
        """Process an incoming audio frame from a user.

        This is the main entry point called for each audio frame
        received from the WebRTC connection.

        Args:
            session_id: Unique session/participant identifier.
            audio_bytes: Raw 16-bit PCM audio bytes.
            sample_rate: Sample rate of the incoming audio.
        """
        if not self._initialized:
            return

        # Convert to float32 and resample to 16kHz for VAD/STT
        audio = pcm_to_float32(audio_bytes)

        if sample_rate != SAMPLE_RATE_16K:
            audio = resample(audio, sample_rate, SAMPLE_RATE_16K)

        # Get or create session
        session = self._session_manager.get_or_create_session(session_id)

        # Run VAD on the full audio chunk (may contain multiple 512-sample frames)
        segments = self._vad.process_audio(audio)

        for segment in segments:
            # Speech segment detected — process through pipeline
            active_streams.inc()
            try:
                await self._process_speech_segment(session, segment.audio)
            finally:
                active_streams.dec()

    async def _process_speech_segment(
        self,
        session: SessionState,
        audio: np.ndarray,
    ) -> None:
        """Process a complete speech segment through STT → LLM → TTS.

        Args:
            session: Current session state.
            audio: Float32 audio data at 16kHz.
        """
        pipeline_start = time.perf_counter()

        try:
            # === Step 1: STT ===
            logger.info("pipeline_stt_start", session_id=session.session_id)

            loop = asyncio.get_event_loop()
            transcription = await loop.run_in_executor(
                None, self._stt.transcribe, audio
            )

            if not transcription.text.strip():
                logger.debug("pipeline_empty_transcript", session_id=session.session_id)
                return

            # Notify transcript callback
            if self._on_transcript:
                await self._on_transcript(
                    session.session_id, "user", transcription.text
                )

            # Record user turn
            session.add_turn(
                role="user",
                content=transcription.text,
                language=transcription.language,
            )

            logger.info(
                "pipeline_stt_complete",
                session_id=session.session_id,
                text=transcription.text[:80],
                language=transcription.language,
            )

            # === Step 2: LLM ===
            logger.info("pipeline_llm_start", session_id=session.session_id)

            # For Phase 1, collect full response before TTS
            # (Phase 2+ will stream LLM → TTS for lower latency)
            llm_response = await self._llm.generate(
                user_message=transcription.text,
                conversation_history=session.get_llm_history()[:-1],  # Exclude current turn
            )

            if not llm_response.text.strip():
                logger.warning("pipeline_empty_llm_response", session_id=session.session_id)
                return

            # Notify transcript callback
            if self._on_transcript:
                await self._on_transcript(
                    session.session_id, "assistant", llm_response.text
                )

            # Record assistant turn
            session.add_turn(
                role="assistant",
                content=llm_response.text,
                language=transcription.language,  # Match user's language
            )

            logger.info(
                "pipeline_llm_complete",
                session_id=session.session_id,
                text=llm_response.text[:80],
                ttft=llm_response.ttft,
                total_time=llm_response.total_time,
            )

            # === Step 3: TTS ===
            logger.info("pipeline_tts_start", session_id=session.session_id)

            tts_result = await self._tts.synthesize(
                text=llm_response.text,
                language=transcription.language,
            )

            if tts_result.audio and self._on_audio_response:
                await self._on_audio_response(
                    session.session_id,
                    tts_result.audio,
                    tts_result.sample_rate,
                )

            logger.info(
                "pipeline_tts_complete",
                session_id=session.session_id,
                duration=tts_result.duration,
                voice=tts_result.voice,
            )

            # === Record end-to-end latency ===
            e2e_time = time.perf_counter() - pipeline_start
            pipeline_e2e_latency.observe(e2e_time)

            logger.info(
                "pipeline_complete",
                session_id=session.session_id,
                e2e_latency=round(e2e_time, 3),
                stt_time=transcription.processing_time,
                llm_time=llm_response.total_time,
                tts_time=tts_result.processing_time,
                user_text=transcription.text[:50],
                ai_text=llm_response.text[:50],
            )

        except Exception as e:
            errors_total.labels(component="pipeline", error_type=type(e).__name__).inc()
            logger.error(
                "pipeline_error",
                session_id=session.session_id,
                error=str(e),
                elapsed=round(time.perf_counter() - pipeline_start, 3),
                exc_info=True,
            )

    async def handle_session_end(self, session_id: str) -> None:
        """Handle a session ending (user disconnects).

        Args:
            session_id: Session identifier.
        """
        self._session_manager.remove_session(session_id)
        self._vad.reset()
        logger.info("session_ended", session_id=session_id)
