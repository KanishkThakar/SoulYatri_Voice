"""
SoulYatri Speech — Voice Activity Detection (VAD)
===================================================
Silero VAD wrapper with streaming support, pre-roll buffering,
and configurable silence thresholds for turn-end detection.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import torch

from ..utils.logging_config import get_logger
from ..utils.metrics import vad_latency, vad_speech_segments

logger = get_logger(__name__)


@dataclass
class SpeechSegment:
    """Represents a detected speech segment."""

    audio: np.ndarray          # Float32 audio data
    start_time: float          # Segment start timestamp (seconds)
    end_time: float            # Segment end timestamp (seconds)
    sample_rate: int = 16000


@dataclass
class VADConfig:
    """VAD configuration parameters."""

    # Silero VAD parameters
    threshold: float = 0.5            # Speech probability threshold
    min_speech_duration_ms: int = 250  # Minimum speech duration to keep
    min_silence_duration_ms: int = 600 # Silence duration to end a turn
    speech_pad_ms: int = 100           # Padding around speech segments

    # Pre-roll buffer to avoid clipping speech start
    pre_roll_ms: int = 150

    # Audio parameters
    sample_rate: int = 16000
    frame_size_ms: int = 30   # 30ms frames for Silero VAD (512 samples at 16kHz)


class SileroVAD:
    """Streaming Voice Activity Detection using Silero VAD.

    Maintains internal state to track speech/silence transitions
    and accumulates audio for complete speech segments.
    """

    def __init__(self, config: Optional[VADConfig] = None) -> None:
        self.config = config or VADConfig()
        self._model = None
        self._is_speaking = False
        self._speech_buffer: list[np.ndarray] = []
        self._speech_start_time: float = 0.0
        self._silence_frames: int = 0
        self._frame_count: int = 0

        # Pre-roll buffer: stores recent frames before speech starts
        pre_roll_frames = max(
            1, int(self.config.pre_roll_ms / self.config.frame_size_ms)
        )
        self._pre_roll_buffer: deque[np.ndarray] = deque(maxlen=pre_roll_frames)

        # Calculate frame sizes
        self._frame_size = int(
            self.config.sample_rate * self.config.frame_size_ms / 1000
        )
        self._min_speech_frames = int(
            self.config.min_speech_duration_ms / self.config.frame_size_ms
        )
        self._min_silence_frames = int(
            self.config.min_silence_duration_ms / self.config.frame_size_ms
        )

        logger.info(
            "vad_config",
            threshold=self.config.threshold,
            frame_size=self._frame_size,
            min_speech_frames=self._min_speech_frames,
            min_silence_frames=self._min_silence_frames,
        )

    def load_model(self) -> None:
        """Load the Silero VAD model. Call once at startup."""
        logger.info("loading_vad_model")
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self._model.eval()
        logger.info("vad_model_loaded")

    def reset(self) -> None:
        """Reset the VAD state for a new session."""
        self._is_speaking = False
        self._speech_buffer.clear()
        self._pre_roll_buffer.clear()
        self._silence_frames = 0
        self._frame_count = 0
        self._speech_start_time = 0.0
        if self._model is not None:
            self._model.reset_states()

    def process_frame(self, frame: np.ndarray) -> Optional[SpeechSegment]:
        """Process a single audio frame through VAD.

        Args:
            frame: Float32 audio frame (should be ~30ms at 16kHz = 480 samples).
                   Silero VAD accepts 256, 512, or 768 samples at 16kHz.

        Returns:
            A SpeechSegment if a complete utterance is detected, None otherwise.
        """
        if self._model is None:
            raise RuntimeError("VAD model not loaded. Call load_model() first.")

        start = time.perf_counter()

        # Ensure correct frame size — Silero VAD wants 512 samples at 16kHz
        if len(frame) != 512:
            # Pad or truncate to 512
            if len(frame) < 512:
                frame = np.pad(frame, (0, 512 - len(frame)))
            else:
                frame = frame[:512]

        # Run inference
        audio_tensor = torch.from_numpy(frame).float()
        speech_prob = self._model(audio_tensor, self.config.sample_rate).item()

        elapsed = time.perf_counter() - start
        vad_latency.observe(elapsed)

        self._frame_count += 1
        current_time = self._frame_count * self.config.frame_size_ms / 1000.0

        if speech_prob >= self.config.threshold:
            # Speech detected
            if not self._is_speaking:
                # Transition: silence → speech
                self._is_speaking = True
                self._speech_start_time = current_time
                self._silence_frames = 0

                # Include pre-roll buffer to capture speech onset
                self._speech_buffer = list(self._pre_roll_buffer)
                self._pre_roll_buffer.clear()

                logger.debug(
                    "speech_start",
                    time=current_time,
                    prob=round(speech_prob, 3),
                )

            self._speech_buffer.append(frame.copy())
            self._silence_frames = 0

        else:
            # Silence detected
            if self._is_speaking:
                self._silence_frames += 1
                self._speech_buffer.append(frame.copy())  # Keep buffering

                if self._silence_frames >= self._min_silence_frames:
                    # Turn ended — emit the segment
                    speech_frames = len(self._speech_buffer)

                    if speech_frames >= self._min_speech_frames:
                        audio = np.concatenate(self._speech_buffer)
                        segment = SpeechSegment(
                            audio=audio,
                            start_time=self._speech_start_time,
                            end_time=current_time,
                            sample_rate=self.config.sample_rate,
                        )

                        vad_speech_segments.inc()
                        logger.info(
                            "speech_segment",
                            start=round(self._speech_start_time, 2),
                            end=round(current_time, 2),
                            duration=round(current_time - self._speech_start_time, 2),
                            frames=speech_frames,
                        )

                        self._is_speaking = False
                        self._speech_buffer.clear()
                        self._silence_frames = 0

                        return segment
                    else:
                        # Too short, discard
                        logger.debug(
                            "speech_too_short",
                            frames=speech_frames,
                            min_required=self._min_speech_frames,
                        )
                        self._is_speaking = False
                        self._speech_buffer.clear()
                        self._silence_frames = 0
            else:
                # Not speaking — update pre-roll buffer
                self._pre_roll_buffer.append(frame.copy())

        return None

    def process_audio(self, audio: np.ndarray) -> list[SpeechSegment]:
        """Process a block of audio and return any complete speech segments.

        Args:
            audio: Float32 audio block at 16kHz.

        Returns:
            List of detected speech segments (may be empty).
        """
        segments = []
        frame_size = 512  # Silero VAD frame size at 16kHz

        for i in range(0, len(audio), frame_size):
            frame = audio[i : i + frame_size]
            if len(frame) < frame_size:
                frame = np.pad(frame, (0, frame_size - len(frame)))

            segment = self.process_frame(frame)
            if segment is not None:
                segments.append(segment)

        return segments

    @property
    def is_speaking(self) -> bool:
        """Whether the user is currently speaking."""
        return self._is_speaking
