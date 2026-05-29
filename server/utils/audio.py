"""
SoulYatri Speech — Audio Processing Utilities
===============================================
Helpers for PCM format conversion, resampling, normalization,
and chunk management used across the pipeline.
"""

from __future__ import annotations

import io
import struct
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE_16K = 16000   # Used by VAD and STT
SAMPLE_RATE_24K = 24000   # Used by some TTS models
SAMPLE_RATE_48K = 48000   # WebRTC / Opus default
CHANNELS_MONO = 1
SAMPLE_WIDTH_16BIT = 2    # 16-bit PCM = 2 bytes per sample


def pcm_to_float32(pcm_bytes: bytes, sample_width: int = 2) -> np.ndarray:
    """Convert raw PCM bytes to float32 numpy array normalized to [-1.0, 1.0].

    Args:
        pcm_bytes: Raw PCM audio bytes.
        sample_width: Bytes per sample (1=8bit, 2=16bit, 4=32bit).

    Returns:
        Float32 numpy array in range [-1.0, 1.0].
    """
    if sample_width == 2:
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        return samples.astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(pcm_bytes, dtype=np.int32)
        return samples.astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        samples = np.frombuffer(pcm_bytes, dtype=np.uint8)
        return (samples.astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported sample width: {sample_width}")


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 numpy array to 16-bit PCM bytes.

    Args:
        audio: Float32 numpy array in range [-1.0, 1.0].

    Returns:
        Raw 16-bit PCM bytes.
    """
    # Clip to valid range and convert
    audio = np.clip(audio, -1.0, 1.0)
    samples = (audio * 32767).astype(np.int16)
    return samples.tobytes()


def resample(
    audio: np.ndarray,
    orig_sr: int,
    target_sr: int,
) -> np.ndarray:
    """Resample audio using linear interpolation.

    For production, consider using torchaudio or librosa for higher quality.
    This is a lightweight fallback.

    Args:
        audio: Input audio as float32 numpy array.
        orig_sr: Original sample rate.
        target_sr: Target sample rate.

    Returns:
        Resampled audio as float32 numpy array.
    """
    if orig_sr == target_sr:
        return audio

    # Calculate new length
    duration = len(audio) / orig_sr
    new_length = int(duration * target_sr)

    # Linear interpolation
    indices = np.linspace(0, len(audio) - 1, new_length)
    resampled = np.interp(indices, np.arange(len(audio)), audio)

    return resampled.astype(np.float32)


def normalize_audio(audio: np.ndarray, target_db: float = -20.0) -> np.ndarray:
    """Normalize audio to a target dB level.

    Args:
        audio: Input audio as float32 numpy array.
        target_db: Target RMS level in dB.

    Returns:
        Normalized audio.
    """
    rms = np.sqrt(np.mean(audio ** 2))
    if rms < 1e-10:
        return audio

    current_db = 20 * np.log10(rms)
    gain_db = target_db - current_db
    gain = 10 ** (gain_db / 20)

    normalized = audio * gain
    return np.clip(normalized, -1.0, 1.0).astype(np.float32)


def split_into_chunks(
    audio: np.ndarray,
    chunk_duration_ms: int,
    sample_rate: int,
) -> list[np.ndarray]:
    """Split audio into fixed-duration chunks.

    Args:
        audio: Input audio as float32 numpy array.
        chunk_duration_ms: Chunk duration in milliseconds.
        sample_rate: Audio sample rate.

    Returns:
        List of audio chunks.
    """
    chunk_size = int(sample_rate * chunk_duration_ms / 1000)
    chunks = []

    for i in range(0, len(audio), chunk_size):
        chunk = audio[i : i + chunk_size]
        # Pad last chunk if needed
        if len(chunk) < chunk_size:
            chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
        chunks.append(chunk)

    return chunks


def compute_rms_db(audio: np.ndarray) -> float:
    """Compute RMS level in dB for an audio chunk.

    Args:
        audio: Input audio as float32 numpy array.

    Returns:
        RMS level in dB, or -100.0 for silence.
    """
    rms = np.sqrt(np.mean(audio ** 2))
    if rms < 1e-10:
        return -100.0
    return float(20 * np.log10(rms))


def create_wav_header(
    data_size: int,
    sample_rate: int = SAMPLE_RATE_16K,
    channels: int = CHANNELS_MONO,
    sample_width: int = SAMPLE_WIDTH_16BIT,
) -> bytes:
    """Create a WAV file header for raw PCM data.

    Args:
        data_size: Size of the PCM data in bytes.
        sample_rate: Audio sample rate.
        channels: Number of audio channels.
        sample_width: Bytes per sample.

    Returns:
        44-byte WAV header.
    """
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,      # File size - 8
        b"WAVE",
        b"fmt ",
        16,                  # PCM format chunk size
        1,                   # Audio format (1 = PCM)
        channels,
        sample_rate,
        byte_rate,
        block_align,
        sample_width * 8,    # Bits per sample
        b"data",
        data_size,
    )
    return header


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = SAMPLE_RATE_16K,
    channels: int = CHANNELS_MONO,
    sample_width: int = SAMPLE_WIDTH_16BIT,
) -> bytes:
    """Wrap raw PCM data with a WAV header.

    Args:
        pcm_data: Raw PCM audio bytes.
        sample_rate: Audio sample rate.
        channels: Number of channels.
        sample_width: Bytes per sample.

    Returns:
        Complete WAV file as bytes.
    """
    header = create_wav_header(len(pcm_data), sample_rate, channels, sample_width)
    return header + pcm_data
