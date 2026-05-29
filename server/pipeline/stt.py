"""
SoulYatri Speech — Speech-to-Text (STT)
=========================================
faster-whisper wrapper for transcription with auto language detection.
Supports Hindi, English, and Hinglish (code-switching).
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import settings
from ..utils.audio import pcm_to_wav, SAMPLE_RATE_16K
from ..utils.logging_config import get_logger
from ..utils.metrics import stt_latency, stt_transcriptions, errors_total

logger = get_logger(__name__)


@dataclass
class TranscriptionResult:
    """Result of a speech-to-text transcription."""

    text: str                       # Full transcribed text
    language: str                   # Detected language code (e.g., "hi", "en")
    language_probability: float     # Confidence of language detection
    duration: float                 # Audio duration in seconds
    processing_time: float          # Time taken for transcription
    segments: list[dict]            # Individual segments with timestamps


class WhisperSTT:
    """Speech-to-text using faster-whisper.

    Loads the model once and provides a simple transcribe interface.
    Thread-safe for sequential calls (not concurrent on same instance).
    """

    def __init__(self) -> None:
        self._model = None
        self._model_size = settings.whisper.model_size
        self._device = settings.whisper.device
        self._compute_type = settings.whisper.compute_type

    def load_model(self) -> None:
        """Load the faster-whisper model. Call once at startup."""
        from faster_whisper import WhisperModel

        logger.info(
            "loading_stt_model",
            model_size=self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )

        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )

        logger.info("stt_model_loaded", model_size=self._model_size)

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE_16K,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: Float32 numpy array of audio at the given sample rate.
            sample_rate: Sample rate of the audio.
            language: Optional language hint ("hi", "en"). If None, auto-detects.

        Returns:
            TranscriptionResult with text, language, and timing info.
        """
        if self._model is None:
            raise RuntimeError("STT model not loaded. Call load_model() first.")

        start = time.perf_counter()

        try:
            # faster-whisper expects float32 numpy array at any sample rate
            # but works best with 16kHz
            segments_iter, info = self._model.transcribe(
                audio,
                beam_size=5,
                language=language,
                vad_filter=False,  # We already did VAD
                word_timestamps=False,
                condition_on_previous_text=True,
            )

            # Collect all segments
            segments = []
            full_text_parts = []

            for segment in segments_iter:
                segments.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip(),
                })
                full_text_parts.append(segment.text.strip())

            full_text = " ".join(full_text_parts).strip()
            processing_time = time.perf_counter() - start
            audio_duration = len(audio) / sample_rate

            # Record metrics
            stt_latency.observe(processing_time)
            stt_transcriptions.labels(language=info.language).inc()

            result = TranscriptionResult(
                text=full_text,
                language=info.language,
                language_probability=round(info.language_probability, 3),
                duration=round(audio_duration, 2),
                processing_time=round(processing_time, 3),
                segments=segments,
            )

            logger.info(
                "transcription_complete",
                text=full_text[:100],
                language=info.language,
                lang_prob=round(info.language_probability, 3),
                audio_duration=round(audio_duration, 2),
                processing_time=round(processing_time, 3),
                rtf=round(processing_time / max(audio_duration, 0.01), 2),
            )

            return result

        except Exception as e:
            processing_time = time.perf_counter() - start
            errors_total.labels(component="stt", error_type=type(e).__name__).inc()
            logger.error(
                "transcription_error",
                error=str(e),
                processing_time=round(processing_time, 3),
            )
            raise

    def transcribe_bytes(
        self,
        pcm_bytes: bytes,
        sample_rate: int = SAMPLE_RATE_16K,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe raw PCM bytes.

        Args:
            pcm_bytes: Raw 16-bit PCM audio bytes.
            sample_rate: Sample rate of the audio.
            language: Optional language hint.

        Returns:
            TranscriptionResult.
        """
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return self.transcribe(audio, sample_rate, language)
