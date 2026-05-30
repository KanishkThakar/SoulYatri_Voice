"""Tests for streaming feature extraction (Phase 4A).

Validates that features stream per-frame (no full-utterance buffering), that speech
start/end markers fire on the right edges, and that the emotion/speaker fallbacks emit
valid, deterministic outputs on CPU with no weights.
"""

from __future__ import annotations

import math
import types

from edge.emotion.extractor import EmotionExtractor
from edge.speaker.encoder import SpeakerEncoder, cosine_similarity
from edge.turn_detection.features import (
    SpeechFeatures,
    StreamingFeatureExtractor,
    VADProvider,
)
from shared.contracts import EmotionState


def sine_frame(n: int = 480, amp: float = 0.3, freq: float = 220.0, sr: int = 16000) -> list[float]:
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]


def silence_frame(n: int = 480) -> list[float]:
    return [0.0] * n


# --- VAD fallback ----------------------------------------------------------
def test_vad_fallback_distinguishes_speech_and_silence():
    vad = VADProvider(use_fallback=True)
    assert vad.using_fallback is True
    speech_prob = vad.speech_probability(sine_frame(amp=0.4))
    silence_prob = vad.speech_probability(silence_frame())
    assert speech_prob > 0.5
    assert silence_prob < 0.5


def test_vad_fallback_is_deterministic():
    vad = VADProvider(use_fallback=True)
    f = sine_frame()
    assert vad.speech_probability(f) == vad.speech_probability(f)


# --- Emotion extractor fallback -------------------------------------------
def test_emotion_extractor_emits_emotion_state():
    ext = EmotionExtractor(use_fallback=True)
    assert ext.using_fallback is True
    state = ext.extract(sine_frame(amp=0.4))
    assert isinstance(state, EmotionState)
    # Ranges from the shared contract are respected.
    assert -1.0 <= state.valence <= 1.0
    assert -1.0 <= state.arousal <= 1.0
    assert 0.0 <= state.confidence <= 1.0
    # JSON round-trip works.
    assert EmotionState.model_validate(state.model_dump()) == state


def test_emotion_extractor_deterministic():
    ext = EmotionExtractor(use_fallback=True)
    f = sine_frame(amp=0.4)
    assert ext.extract(f) == ext.extract(f)


def test_emotion_silence_is_low_confidence():
    ext = EmotionExtractor(use_fallback=True)
    state = ext.extract(silence_frame())
    assert state.confidence < 0.2


# --- Speaker encoder fallback ---------------------------------------------
def test_speaker_encoder_returns_unit_vector():
    enc = SpeakerEncoder(use_fallback=True, embedding_dim=192)
    vec = enc.encode(sine_frame(amp=0.4))
    assert len(vec) == 192
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-6


def test_speaker_encoder_same_input_same_embedding():
    enc = SpeakerEncoder(use_fallback=True)
    f = sine_frame(amp=0.4)
    v1 = enc.encode(f)
    v2 = enc.encode(f)
    assert v1 == v2
    assert cosine_similarity(v1, v2) > 0.999


def test_speaker_encoder_silence_returns_zero_vector():
    enc = SpeakerEncoder(use_fallback=True)
    vec = enc.encode(silence_frame())
    assert all(v == 0.0 for v in vec)


# --- Streaming extractor ---------------------------------------------------
def test_stream_is_lazy_generator():
    ext = StreamingFeatureExtractor(
        "s1",
        vad=VADProvider(use_fallback=True),
        speaker=SpeakerEncoder(use_fallback=True),
        emotion=EmotionExtractor(use_fallback=True),
    )
    frames = [(silence_frame(), i * 30) for i in range(3)]
    gen = ext.stream(frames)
    assert isinstance(gen, types.GeneratorType)
    first = next(gen)
    assert isinstance(first, SpeechFeatures)
    assert first.seq == 0


def test_speech_start_and_end_markers():
    ext = StreamingFeatureExtractor(
        "s1",
        start_frames=2,
        end_frames=3,
        vad=VADProvider(use_fallback=True),
        speaker=SpeakerEncoder(use_fallback=True),
        emotion=EmotionExtractor(use_fallback=True),
    )
    # 2 silence, 4 speech (start should fire on 2nd speech frame), 4 silence (end fires).
    seq = (
        [silence_frame(), silence_frame()]
        + [sine_frame(amp=0.4) for _ in range(4)]
        + [silence_frame() for _ in range(4)]
    )
    feats = [ext.process_frame(f, i * 30) for i, f in enumerate(seq)]

    started = [f for f in feats if f.speech_started]
    ended = [f for f in feats if f.speech_ended]
    assert len(started) == 1
    assert len(ended) == 1
    # Start happens after 2 consecutive speech frames (index 3, the 2nd speech frame).
    assert started[0].seq == 3
    # End happens after 3 consecutive silence frames following speech.
    assert ended[0].seq == 8
    # While speaking, speaker embedding is populated.
    speaking_feats = [f for f in feats if f.is_speech]
    assert speaking_feats and all(f.speaker_embedding for f in speaking_feats)


def test_emotion_emitted_on_speech_start():
    ext = StreamingFeatureExtractor(
        "s1",
        start_frames=1,
        vad=VADProvider(use_fallback=True),
        speaker=SpeakerEncoder(use_fallback=True),
        emotion=EmotionExtractor(use_fallback=True),
        emotion_every_n_frames=100,  # only the start edge should force emotion.
    )
    f = ext.process_frame(sine_frame(amp=0.4), 0)
    assert f.speech_started is True
    assert isinstance(f.emotion, EmotionState)


def test_no_speaker_embedding_during_silence():
    ext = StreamingFeatureExtractor(
        "s1",
        vad=VADProvider(use_fallback=True),
        speaker=SpeakerEncoder(use_fallback=True),
        emotion=EmotionExtractor(use_fallback=True),
    )
    f = ext.process_frame(silence_frame(), 0)
    assert f.is_speech is False
    assert f.speaker_embedding == []


def test_reset_clears_streaming_state():
    ext = StreamingFeatureExtractor("s1", start_frames=1, vad=VADProvider(use_fallback=True))
    ext.process_frame(sine_frame(amp=0.4), 0)
    assert ext.in_speech is True
    ext.reset()
    assert ext.in_speech is False


def test_features_to_dict_serializable():
    ext = StreamingFeatureExtractor(
        "s1",
        start_frames=1,
        vad=VADProvider(use_fallback=True),
        speaker=SpeakerEncoder(use_fallback=True),
        emotion=EmotionExtractor(use_fallback=True),
    )
    f = ext.process_frame(sine_frame(amp=0.4), 30)
    d = f.to_dict()
    assert d["session_id"] == "s1"
    assert d["is_speech"] is True
    assert "speech_probability" in d
