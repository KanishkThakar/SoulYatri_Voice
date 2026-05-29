"""
SoulYatri Speech — Prometheus Metrics
=======================================
Exposes key performance and operational metrics for monitoring.
All metrics follow the `soulyatri_` prefix convention.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info


# ---------------------------------------------------------------------------
# Application info
# ---------------------------------------------------------------------------
app_info = Info(
    "soulyatri",
    "SoulYatri Speech application information",
)
app_info.info({"version": "0.1.0", "phase": "2"})

# ---------------------------------------------------------------------------
# Latency histograms — track processing time for each pipeline stage
# ---------------------------------------------------------------------------
vad_latency = Histogram(
    "soulyatri_vad_latency_seconds",
    "Time to process a single VAD frame",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1),
)

stt_latency = Histogram(
    "soulyatri_stt_latency_seconds",
    "Time to transcribe a speech segment",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

llm_ttft = Histogram(
    "soulyatri_llm_ttft_seconds",
    "LLM time-to-first-token",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

llm_total_latency = Histogram(
    "soulyatri_llm_total_latency_seconds",
    "LLM total generation time",
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

tts_latency = Histogram(
    "soulyatri_tts_latency_seconds",
    "Time to generate speech audio from text",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

pipeline_e2e_latency = Histogram(
    "soulyatri_pipeline_e2e_latency_seconds",
    "End-to-end latency from speech-end to first audio output",
    buckets=(0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Counters — track events
# ---------------------------------------------------------------------------
vad_speech_segments = Counter(
    "soulyatri_vad_speech_segments_total",
    "Total number of speech segments detected by VAD",
)

stt_transcriptions = Counter(
    "soulyatri_stt_transcriptions_total",
    "Total number of STT transcriptions completed",
    ["language"],
)

llm_requests = Counter(
    "soulyatri_llm_requests_total",
    "Total number of LLM generation requests",
)

tts_requests = Counter(
    "soulyatri_tts_requests_total",
    "Total number of TTS synthesis requests",
    ["language"],
)

errors_total = Counter(
    "soulyatri_errors_total",
    "Total number of errors by component",
    ["component", "error_type"],
)

# ---------------------------------------------------------------------------
# Gauges — track current state
# ---------------------------------------------------------------------------
active_sessions = Gauge(
    "soulyatri_active_sessions",
    "Number of currently active voice sessions",
)

active_streams = Gauge(
    "soulyatri_active_streams",
    "Number of currently active audio streams",
)

# ---------------------------------------------------------------------------
# Phase 2 — Filler system metrics
# ---------------------------------------------------------------------------
filler_played = Counter(
    "soulyatri_filler_played_total",
    "Total number of filler phrases played",
    ["category"],
)

filler_hit_rate = Counter(
    "soulyatri_filler_hit_rate_total",
    "Total filler-only turns vs pipeline turns",
    ["action"],  # filler_only, filler_then_pipeline, pipeline_only
)

# ---------------------------------------------------------------------------
# Phase 2 — Emotion and speaker metrics
# ---------------------------------------------------------------------------
emotion_latency = Histogram(
    "soulyatri_emotion_latency_seconds",
    "Time to extract emotion features from audio",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
)

speaker_similarity_hist = Histogram(
    "soulyatri_speaker_similarity",
    "Cosine similarity between speaker embeddings",
    buckets=(0.0, 0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0),
)

# ---------------------------------------------------------------------------
# Phase 2 — Turn management and barge-in metrics
# ---------------------------------------------------------------------------
barge_in_total = Counter(
    "soulyatri_barge_in_total",
    "Total number of barge-in events detected",
)

turn_state_transitions = Counter(
    "soulyatri_turn_state_transitions_total",
    "Total state transitions by type",
    ["from_state", "to_state"],
)
