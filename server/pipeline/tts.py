"""
SoulYatri Speech — Text-to-Speech (TTS)
=========================================
edge-tts wrapper with async streaming, auto language detection
for voice selection, and MP3-to-PCM conversion for LiveKit output.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import numpy as np

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import tts_latency, tts_requests, errors_total

logger = get_logger(__name__)


@dataclass
class TTSResult:
    """Result from TTS synthesis."""

    audio: bytes               # Raw PCM audio bytes (16-bit, 24kHz mono)
    sample_rate: int           # Sample rate of the output audio
    duration: float            # Audio duration in seconds
    processing_time: float     # Time taken for synthesis
    voice: str                 # Voice used
    language: str              # Language of the text


class EdgeTTS:
    """Text-to-speech using edge-tts.

    Provides both full synthesis and streaming interfaces.
    Automatically selects Hindi or English voice based on text content.
    """

    def __init__(self) -> None:
        self._voice_hindi = settings.tts.voice_hindi
        self._voice_english = settings.tts.voice_english

    def detect_language(self, text: str) -> str:
        """Simple heuristic language detection for voice selection.

        Args:
            text: Input text to analyze.

        Returns:
            "hi" for Hindi/Hinglish, "en" for English.
        """
        # Check for Devanagari characters
        hindi_chars = sum(1 for c in text if "\u0900" <= c <= "\u097F")
        total_alpha = sum(1 for c in text if c.isalpha())

        if total_alpha == 0:
            return "en"

        hindi_ratio = hindi_chars / total_alpha

        # If more than 30% Hindi characters, use Hindi voice
        if hindi_ratio > 0.3:
            return "hi"

        # Check for common Hinglish/Hindi romanized words
        hinglish_markers = {
            "acha", "theek", "haan", "nahi", "kya", "hai", "ho",
            "mein", "tum", "aap", "yeh", "woh", "kaise", "kaisa",
            "kar", "karo", "bolo", "suno", "dekho", "chalo",
            "bahut", "bohot", "accha", "samjha", "batao", "pata",
            "abhi", "yaar", "bhai", "didi", "ji", "arrey",
        }

        words = set(text.lower().split())
        hinglish_count = len(words & hinglish_markers)

        if hinglish_count >= 2:
            return "hi"

        return "en"

    def _get_voice(self, language: str) -> str:
        """Get the appropriate voice for the detected language."""
        if language == "hi":
            return self._voice_hindi
        return self._voice_english

    async def synthesize(
        self,
        text: str,
        language: Optional[str] = None,
    ) -> TTSResult:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize.
            language: Optional language override ("hi" or "en").

        Returns:
            TTSResult with PCM audio data.
        """
        import edge_tts

        if not text.strip():
            return TTSResult(
                audio=b"",
                sample_rate=24000,
                duration=0.0,
                processing_time=0.0,
                voice="",
                language="",
            )

        start = time.perf_counter()
        detected_lang = language or self.detect_language(text)
        voice = self._get_voice(detected_lang)

        try:
            communicate = edge_tts.Communicate(text, voice)

            # Collect all audio chunks (MP3 format from edge-tts)
            mp3_chunks: list[bytes] = []

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_chunks.append(chunk["data"])

            mp3_data = b"".join(mp3_chunks)

            # Convert MP3 to PCM using pydub
            pcm_data, sample_rate = self._mp3_to_pcm(mp3_data)

            processing_time = time.perf_counter() - start
            duration = len(pcm_data) / (sample_rate * 2)  # 16-bit = 2 bytes/sample

            # Record metrics
            tts_latency.observe(processing_time)
            tts_requests.labels(language=detected_lang).inc()

            logger.info(
                "tts_synthesis_complete",
                text_length=len(text),
                language=detected_lang,
                voice=voice,
                duration=round(duration, 2),
                processing_time=round(processing_time, 3),
            )

            return TTSResult(
                audio=pcm_data,
                sample_rate=sample_rate,
                duration=round(duration, 2),
                processing_time=round(processing_time, 3),
                voice=voice,
                language=detected_lang,
            )

        except Exception as e:
            errors_total.labels(component="tts", error_type=type(e).__name__).inc()
            logger.error("tts_synthesis_error", error=str(e), text=text[:50])
            raise

    async def synthesize_stream(
        self,
        text: str,
        language: Optional[str] = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream synthesized audio chunks.

        Yields PCM audio chunks as they become available,
        enabling low-latency playback start.

        Args:
            text: Text to synthesize.
            language: Optional language override.

        Yields:
            PCM audio data chunks (16-bit).
        """
        import edge_tts

        if not text.strip():
            return

        detected_lang = language or self.detect_language(text)
        voice = self._get_voice(detected_lang)
        start = time.perf_counter()

        try:
            communicate = edge_tts.Communicate(text, voice)

            # Buffer MP3 data and convert in chunks
            mp3_buffer = io.BytesIO()
            chunk_count = 0

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_buffer.write(chunk["data"])
                    chunk_count += 1

                    # Convert accumulated MP3 to PCM every N chunks
                    # for streaming output (edge-tts sends small chunks)
                    if chunk_count % 10 == 0 and mp3_buffer.tell() > 4096:
                        mp3_buffer.seek(0)
                        try:
                            pcm_data, _ = self._mp3_to_pcm(mp3_buffer.read())
                            if pcm_data:
                                yield pcm_data
                        except Exception:
                            pass  # Incomplete MP3 frame, keep buffering
                        mp3_buffer = io.BytesIO()
                        chunk_count = 0

            # Flush remaining buffer
            if mp3_buffer.tell() > 0:
                mp3_buffer.seek(0)
                try:
                    pcm_data, _ = self._mp3_to_pcm(mp3_buffer.read())
                    if pcm_data:
                        yield pcm_data
                except Exception:
                    pass

            processing_time = time.perf_counter() - start
            tts_latency.observe(processing_time)
            tts_requests.labels(language=detected_lang).inc()

        except Exception as e:
            errors_total.labels(component="tts", error_type=type(e).__name__).inc()
            logger.error("tts_stream_error", error=str(e))
            raise

    @staticmethod
    def _mp3_to_pcm(mp3_data: bytes) -> tuple[bytes, int]:
        """Convert MP3 audio to 16-bit PCM.

        Args:
            mp3_data: Raw MP3 bytes.

        Returns:
            Tuple of (PCM bytes, sample rate).
        """
        from pydub import AudioSegment

        audio_segment = AudioSegment.from_mp3(io.BytesIO(mp3_data))

        # Convert to mono 24kHz 16-bit
        audio_segment = audio_segment.set_channels(1)
        audio_segment = audio_segment.set_frame_rate(24000)
        audio_segment = audio_segment.set_sample_width(2)

        return audio_segment.raw_data, 24000
