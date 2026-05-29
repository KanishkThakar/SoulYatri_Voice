"""
SoulYatri Speech — Voice Agent (Phase 2)
============================================
Orchestrates the full voice pipeline with turn state management,
filler routing, emotion/speaker features, and barge-in detection.

Architecture:
    Audio → VAD → Turn State Machine → Filler Router
                                          ├── filler_only → play cached phrase
                                          ├── filler_then_pipeline → play filler + STT→LLM→TTS
                                          └── pipeline_only → STT→LLM→TTS

The turn state machine is the central coordinator. Feature extraction
(emotion + speaker) runs in parallel with the main pipeline.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional, Callable, Any

import numpy as np

from .config import settings
from .pipeline.vad import SileroVAD, VADConfig
from .pipeline.stt import WhisperSTT
from .pipeline.llm import OllamaLLM
from .pipeline.tts import EdgeTTS
from .pipeline.session import SessionManager, SessionState
from .pipeline.turn_state import TurnStateMachine, TurnState, TurnEvent
from .pipeline.filler import FillerPhraseBank, FillerRouter, RoutingDecision
from .pipeline.features import FeatureExtractor, TurnMetadata
from .pipeline.barge_in import BargeInDetector
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
    filler_hit_rate,
)

logger = get_logger(__name__)


class VoiceAgent:
    """Main voice agent with turn management, filler routing, and features.

    Phase 2 upgrades over Phase 1:
    - Explicit turn state machine (replaces ad-hoc processing)
    - Filler phrase routing (instant responses for trivial turns)
    - Emotion + speaker feature extraction per turn
    - Barge-in detection (interrupt handling)

    Lifecycle:
        1. initialize() — load all models, pre-synthesize fillers
        2. handle_audio_frame() — process incoming audio frames
        3. shutdown() — cleanup resources
    """

    def __init__(self) -> None:
        # --- Phase 1 pipeline components ---
        self._vad = SileroVAD(VADConfig())
        self._stt = WhisperSTT()
        self._llm = OllamaLLM()
        self._tts = EdgeTTS()
        self._session_manager = SessionManager()

        # --- Phase 2 components ---
        self._phrase_bank = FillerPhraseBank()
        self._filler_router: Optional[FillerRouter] = None
        self._feature_extractor = FeatureExtractor()
        self._barge_in_detector = BargeInDetector(
            min_speech_duration_ms=settings.barge_in.min_speech_duration_ms,
            cooldown_ms=settings.barge_in.cooldown_ms,
        )

        # Per-session turn state machines
        self._turn_machines: dict[str, TurnStateMachine] = {}

        # State
        self._initialized = False
        self._processing_lock = asyncio.Lock()

        # Callbacks — set by the server
        self._on_audio_response: Optional[Callable] = None
        self._on_transcript: Optional[Callable] = None
        self._on_turn_metadata: Optional[Callable] = None

    async def initialize(self) -> None:
        """Initialize all pipeline components. Call once at startup."""
        logger.info("agent_initializing", phase=2)

        loop = asyncio.get_event_loop()

        # --- Load Phase 1 models (parallel where possible) ---
        await asyncio.gather(
            loop.run_in_executor(None, self._vad.load_model),
            loop.run_in_executor(None, self._stt.load_model),
        )

        # Initialize LLM client
        await self._llm.initialize()

        # --- Load Phase 2: Filler phrase bank ---
        if settings.filler.enabled:
            self._phrase_bank.load_phrases(
                settings.filler.phrases_path or None
            )
            self._filler_router = FillerRouter(self._phrase_bank)

            if settings.filler.pre_synthesize:
                await self._phrase_bank.pre_synthesize_audio()

        # --- Load Phase 2: Feature extraction models ---
        # These are heavy, load in executor to avoid blocking
        if settings.emotion.enabled or settings.speaker.enabled:
            await loop.run_in_executor(
                None, self._feature_extractor.load_models
            )

        self._initialized = True
        logger.info("agent_initialized", phase=2)

    async def shutdown(self) -> None:
        """Shutdown and cleanup resources."""
        logger.info("agent_shutting_down")
        await self._llm.close()
        self._initialized = False
        logger.info("agent_shutdown_complete")

    # --- Callback setters ---

    def set_audio_callback(self, callback: Callable) -> None:
        """Set callback for audio responses.

        Args:
            callback: async function(session_id, audio_bytes, sample_rate)
        """
        self._on_audio_response = callback

    def set_transcript_callback(self, callback: Callable) -> None:
        """Set callback for transcript updates.

        Args:
            callback: async function(session_id, role, text)
        """
        self._on_transcript = callback

    def set_turn_metadata_callback(self, callback: Callable) -> None:
        """Set callback for turn metadata (emotion, speaker, etc).

        Args:
            callback: async function(session_id, metadata_dict)
        """
        self._on_turn_metadata = callback

    # --- Turn machine management ---

    def _get_turn_machine(self, session_id: str) -> TurnStateMachine:
        """Get or create a turn state machine for a session."""
        if session_id not in self._turn_machines:
            self._turn_machines[session_id] = TurnStateMachine(session_id)
        return self._turn_machines[session_id]

    # --- Main audio handler ---

    async def handle_audio_frame(
        self,
        session_id: str,
        audio_bytes: bytes,
        sample_rate: int = SAMPLE_RATE_48K,
    ) -> None:
        """Process an incoming audio frame from a user.

        This is the main entry point called for each audio frame
        received from the WebSocket/WebRTC connection.

        The flow is:
        1. Convert audio to float32 + resample
        2. Run VAD to detect speech segments
        3. On segment detected → turn state machine transitions
        4. Route through filler or full pipeline

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

        # Get session and turn machine
        session = self._session_manager.get_or_create_session(session_id)
        turn_machine = self._get_turn_machine(session_id)

        # --- Barge-in check ---
        # If agent is speaking and user starts talking, handle barge-in
        if settings.barge_in.enabled and turn_machine.is_agent_speaking:
            # Quick VAD check for barge-in (we don't need full segment detection)
            barge_event = self._barge_in_detector.check_barge_in(
                session_id=session_id,
                speech_probability=self._quick_vad_check(audio),
            )
            if barge_event:
                turn_machine.on_speech_start()  # Triggers BARGE_IN transition
                turn_machine.on_barge_in_handled()  # → LISTENING
                logger.info(
                    "barge_in_handled",
                    session_id=session_id,
                    time_into_response=barge_event.time_since_agent_started,
                )

        # --- VAD: detect speech segments ---
        segments = self._vad.process_audio(audio)

        for segment in segments:
            # Speech segment detected — process it
            active_streams.inc()
            try:
                await self._process_speech_segment(
                    session=session,
                    turn_machine=turn_machine,
                    audio=segment.audio,
                )
            finally:
                active_streams.dec()

    def _quick_vad_check(self, audio: np.ndarray) -> float:
        """Quick VAD probability check for barge-in detection.

        Uses the VAD model to get a speech probability without
        full segment tracking. Returns the max probability across
        sub-frames.
        """
        import torch

        if self._vad._model is None:
            return 0.0

        max_prob = 0.0
        for i in range(0, len(audio), 512):
            frame = audio[i:i + 512]
            if len(frame) < 512:
                frame = np.pad(frame, (0, 512 - len(frame)))
            tensor = torch.from_numpy(frame).float()
            prob = self._vad._model(tensor, 16000).item()
            max_prob = max(max_prob, prob)

        return max_prob

    async def _process_speech_segment(
        self,
        session: SessionState,
        turn_machine: TurnStateMachine,
        audio: np.ndarray,
    ) -> None:
        """Process a complete speech segment through the Phase 2 pipeline.

        Flow:
        1. Turn machine: IDLE → LISTENING → BUFFERING → CANDIDATE_FILLER
        2. STT: Transcribe the audio
        3. Feature extraction: Emotion + speaker (parallel with step 4)
        4. Filler routing: Decide if filler can handle this
        5a. Filler only: Play cached phrase → IDLE
        5b. Filler + pipeline: Play stall filler, then STT→LLM→TTS → IDLE

        Args:
            session: Current session state.
            turn_machine: Turn state machine for this session.
            audio: Float32 audio data at 16kHz.
        """
        pipeline_start = time.perf_counter()

        # --- State transitions for segment detection ---
        if turn_machine.state == TurnState.IDLE:
            turn_machine.on_speech_start()
        turn_machine.try_transition(TurnState.BUFFERING, "segment_complete")
        turn_machine.on_turn_confirmed()

        try:
            # === Step 1: STT (always needed for routing) ===
            logger.info("pipeline_stt_start", session_id=session.session_id)

            loop = asyncio.get_event_loop()
            transcription = await loop.run_in_executor(
                None, self._stt.transcribe, audio
            )

            if not transcription.text.strip():
                logger.debug("pipeline_empty_transcript", session_id=session.session_id)
                turn_machine.on_error()
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

            # === Step 2: Feature extraction (parallel, non-blocking) ===
            turn_id = f"turn-{turn_machine.turn_id}"
            feature_task: Optional[asyncio.Future] = None

            if settings.emotion.enabled or settings.speaker.enabled:
                feature_task = loop.run_in_executor(
                    None,
                    self._feature_extractor.extract_features,
                    session.session_id,
                    turn_id,
                    audio,
                    SAMPLE_RATE_16K,
                    transcription.language,
                )

            # === Step 3: Filler routing ===
            emotion_label = None
            if feature_task:
                # Quick check if features are ready (don't block)
                if feature_task.done():
                    metadata = feature_task.result()
                    emotion_label = metadata.emotion.label if metadata and metadata.emotion else None

            routing: Optional[RoutingDecision] = None
            if self._filler_router:
                routing = self._filler_router.classify(
                    text=transcription.text,
                    language=transcription.language,
                    emotion_label=emotion_label,
                )
                filler_hit_rate.labels(action=routing.action).inc()

                logger.info(
                    "filler_routing_decision",
                    session_id=session.session_id,
                    action=routing.action,
                    intent=routing.intent,
                    confidence=routing.confidence,
                    reason=routing.reason,
                )

            # === Step 4: Execute the routing decision ===

            if routing and routing.action == "filler_only":
                # --- Filler-only: play cached phrase, skip pipeline ---
                turn_machine.on_filler_selected()

                if routing.filler_phrase and routing.filler_phrase.audio:
                    self._barge_in_detector.set_agent_speaking(True)
                    if self._on_audio_response:
                        await self._on_audio_response(
                            session.session_id,
                            routing.filler_phrase.audio,
                            routing.filler_phrase.audio_sample_rate,
                            {
                                "source": "filler",
                                "text": routing.filler_phrase.text,
                                "category": routing.filler_phrase.category,
                            },
                        )
                    self._barge_in_detector.set_agent_speaking(False)
                    if self._on_transcript:
                        await self._on_transcript(
                            session.session_id,
                            "assistant",
                            routing.filler_phrase.text,
                        )

                    # Record assistant turn
                    session.add_turn(
                        role="assistant",
                        content=routing.filler_phrase.text,
                        language=routing.filler_phrase.language,
                    )

                e2e_time = time.perf_counter() - pipeline_start
                pipeline_e2e_latency.observe(e2e_time)

                logger.info(
                    "filler_only_complete",
                    session_id=session.session_id,
                    e2e_latency=round(e2e_time, 3),
                    filler_text=routing.filler_phrase.text if routing.filler_phrase else "",
                )

            else:
                # --- Full pipeline (with optional leading filler) ---

                # Play stall filler immediately while pipeline runs
                if routing and routing.filler_phrase and routing.filler_phrase.audio:
                    turn_machine.on_pipeline_needed()

                    self._barge_in_detector.set_agent_speaking(True)
                    if self._on_audio_response:
                        await self._on_audio_response(
                            session.session_id,
                            routing.filler_phrase.audio,
                            routing.filler_phrase.audio_sample_rate,
                            {
                                "source": "filler",
                                "text": routing.filler_phrase.text,
                                "category": routing.filler_phrase.category,
                            },
                        )
                    self._barge_in_detector.set_agent_speaking(False)

                    logger.info(
                        "stall_filler_played",
                        session_id=session.session_id,
                        filler_text=routing.filler_phrase.text,
                    )
                else:
                    turn_machine.on_pipeline_needed()

                turn_machine.on_pipeline_start()

                # --- LLM ---
                logger.info("pipeline_llm_start", session_id=session.session_id)

                llm_response = await self._llm.generate(
                    user_message=transcription.text,
                    conversation_history=session.get_llm_history()[:-1],
                )

                if not llm_response.text.strip():
                    logger.warning("pipeline_empty_llm_response", session_id=session.session_id)
                    turn_machine.on_error()
                    return

                if self._on_transcript:
                    await self._on_transcript(
                        session.session_id, "assistant", llm_response.text
                    )

                session.add_turn(
                    role="assistant",
                    content=llm_response.text,
                    language=transcription.language,
                )

                logger.info(
                    "pipeline_llm_complete",
                    session_id=session.session_id,
                    text=llm_response.text[:80],
                    ttft=llm_response.ttft,
                    total_time=llm_response.total_time,
                )

                # --- TTS ---
                logger.info("pipeline_tts_start", session_id=session.session_id)

                tts_result = await self._tts.synthesize(
                    text=llm_response.text,
                    language=transcription.language,
                )

                # Transition to speaking
                turn_machine.on_response_ready()
                self._barge_in_detector.set_agent_speaking(True)

                if tts_result.audio and self._on_audio_response:
                    await self._on_audio_response(
                        session.session_id,
                        tts_result.audio,
                        tts_result.sample_rate,
                        {
                            "source": "response",
                            "voice": tts_result.voice,
                        },
                    )

                # Done speaking
                self._barge_in_detector.set_agent_speaking(False)
                turn_machine.on_speaking_done()

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

            # === Await and log feature extraction results ===
            if feature_task and not feature_task.done():
                try:
                    metadata = await asyncio.wait_for(feature_task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("feature_extraction_timeout", session_id=session.session_id)
                    metadata = None

            if feature_task and feature_task.done():
                try:
                    metadata = feature_task.result()
                    # Store emotion in session
                    session.add_emotion(metadata.emotion)
                    session.add_turn_metadata(metadata.to_dict())

                    # Send metadata to client
                    if self._on_turn_metadata and metadata:
                        await self._on_turn_metadata(
                            session.session_id, metadata.to_dict()
                        )

                    logger.info(
                        "turn_features",
                        session_id=session.session_id,
                        emotion=metadata.emotion.label if metadata.emotion else "unknown",
                        speaker_id=metadata.speaker_embedding_id,
                        extraction_time=metadata.extraction_time,
                    )
                except Exception as e:
                    logger.warning("feature_result_error", error=str(e))

        except Exception as e:
            errors_total.labels(component="pipeline", error_type=type(e).__name__).inc()
            logger.error(
                "pipeline_error",
                session_id=session.session_id,
                error=str(e),
                elapsed=round(time.perf_counter() - pipeline_start, 3),
                exc_info=True,
            )
            turn_machine.on_error()

    async def handle_session_end(self, session_id: str) -> None:
        """Handle a session ending (user disconnects).

        Args:
            session_id: Session identifier.
        """
        # End the turn machine
        if session_id in self._turn_machines:
            self._turn_machines[session_id].on_session_end()
            del self._turn_machines[session_id]

        # Clear feature caches
        self._feature_extractor.clear_session_cache(session_id)

        # Clean up session
        self._session_manager.remove_session(session_id)
        self._vad.reset()
        self._barge_in_detector.reset()

        logger.info("session_ended", session_id=session_id)
