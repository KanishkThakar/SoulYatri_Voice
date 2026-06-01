"""
SoulYatri Speech — Text-to-Speech (TTS)
=========================================
edge-tts wrapper with async streaming, auto language detection
for voice selection, and MP3-to-PCM conversion for LiveKit output.
"""

from __future__ import annotations

import glob
import io
import os
import shutil
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import numpy as np

from ..config import settings
from ..utils.logging_config import get_logger
from ..utils.metrics import tts_latency, tts_requests, errors_total

logger = get_logger(__name__)


def _ensure_ffmpeg_available() -> bool:
    """Locate ffmpeg/ffprobe and configure pydub to use them.

    pydub shells out to ffmpeg/ffprobe to decode edge-tts MP3 output. On
    Windows the binaries may be installed (e.g. via winget) but not yet on the
    PATH of the running process. This resolves them explicitly so MP3->PCM
    conversion works regardless of how the server was launched.

    Returns:
        True if ffmpeg was found and configured, False otherwise.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    # Highest priority: binaries bundled in the repo at server/bin. This is the
    # most reliable location because it is readable regardless of which user
    # runs the server (e.g. Admin vs the installing user) and needs no PATH.
    if not ffmpeg or not ffprobe:
        bundled = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin")
        cand_ffmpeg = os.path.join(bundled, "ffmpeg.exe")
        cand_ffprobe = os.path.join(bundled, "ffprobe.exe")
        if os.path.isfile(cand_ffmpeg) and os.path.isfile(cand_ffprobe):
            ffmpeg = cand_ffmpeg
            ffprobe = cand_ffprobe
            os.environ["PATH"] = bundled + os.pathsep + os.environ.get("PATH", "")

    # Next: explicit override via env var (FFMPEG_BIN points at the directory
    # containing ffmpeg.exe/ffprobe.exe).
    if not ffmpeg or not ffprobe:
        override = os.environ.get("FFMPEG_BIN", "").strip().strip('"')
        if override and os.path.isdir(override):
            cand_ffmpeg = os.path.join(override, "ffmpeg.exe")
            cand_ffprobe = os.path.join(override, "ffprobe.exe")
            if os.path.isfile(cand_ffmpeg) and os.path.isfile(cand_ffprobe):
                ffmpeg = cand_ffmpeg
                ffprobe = cand_ffprobe
                os.environ["PATH"] = override + os.pathsep + os.environ.get("PATH", "")

    # Prefer project-local binaries (server/bin) so the app works regardless of
    # PATH or which Windows user launched it. tts.py lives at server/pipeline/,
    # so server/bin is two levels up.
    local_bin = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin")
    local_ffmpeg = os.path.join(local_bin, "ffmpeg.exe")
    local_ffprobe = os.path.join(local_bin, "ffprobe.exe")
    if os.path.isfile(local_ffmpeg) and os.path.isfile(local_ffprobe):
        ffmpeg, ffprobe = local_ffmpeg, local_ffprobe
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")

    # Fall back to common install locations if not on PATH.
    if not ffmpeg or not ffprobe:
        search_globs = [
            # Current user's winget install.
            os.path.expandvars(
                r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin"
            ),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\ffmpeg*\bin"),
            # Any user profile's winget install (server may run as a different
            # user than the one that installed ffmpeg, e.g. elevated/Admin).
            r"C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin",
            r"C:\Users\*\AppData\Local\Programs\ffmpeg*\bin",
            # Machine-wide / package-manager locations.
            r"C:\ProgramData\chocolatey\bin",
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg*\bin",
            r"C:\Program Files\ffmpeg*\**\bin",
        ]
        for pattern in search_globs:
            for bin_dir in glob.glob(pattern, recursive=True):
                cand_ffmpeg = os.path.join(bin_dir, "ffmpeg.exe")
                cand_ffprobe = os.path.join(bin_dir, "ffprobe.exe")
                if os.path.isfile(cand_ffmpeg) and os.path.isfile(cand_ffprobe):
                    ffmpeg = ffmpeg or cand_ffmpeg
                    ffprobe = ffprobe or cand_ffprobe
                    # Make them discoverable to pydub's own PATH-based lookups.
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                    break
            if ffmpeg and ffprobe:
                break

    if ffmpeg and ffprobe:
        try:
            from pydub import AudioSegment

            AudioSegment.converter = ffmpeg
            AudioSegment.ffmpeg = ffmpeg
            AudioSegment.ffprobe = ffprobe
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("pydub_ffmpeg_config_failed", error=str(e))
            return False
        logger.info("ffmpeg_configured", ffmpeg=ffmpeg, ffprobe=ffprobe)
        return True

    logger.error(
        "ffmpeg_not_found",
        hint="Install ffmpeg (winget install Gyan.FFmpeg) so TTS can decode audio.",
    )
    return False


# Configure ffmpeg for pydub as soon as this module is imported.
_FFMPEG_OK = _ensure_ffmpeg_available()


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
