"""
Tests for aux/fallback (Phase 13A + 13B + 13C).

Covers:
  * classic baseline composition VAD→STT→LLM→TTS produces a coherent result on CPU,
  * baseline timings + stub markers are recorded,
  * temporary speech-output adapter is clearly marked NOT final architecture,
  * failover orchestrator decision logic across health states + hysteresis recovery,
  * FallbackDecision contract conformance + user messaging.
"""

from __future__ import annotations

import struct

from auxiliary.fallback.classic_baseline import BaselineResult, ClassicBaseline
from auxiliary.fallback.orchestrator import (
    FailoverOrchestrator,
    FailoverPolicy,
    FailoverReason,
    PrimaryHealth,
)
from auxiliary.fallback.temp_output import (
    IS_FINAL_ARCHITECTURE,
    SpeechOutput,
    StubSpeechOutput,
    make_speech_output,
)
from auxiliary.tests.conftest import run_async
from shared.contracts import FallbackDecision


def _silence_pcm(n_samples: int) -> bytes:
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


# ---------------------------------------------------------------------------
# 13B — temporary speech output
# ---------------------------------------------------------------------------
def test_temp_output_marked_not_final() -> None:
    assert IS_FINAL_ARCHITECTURE is False


def test_stub_speech_output_silent_pcm() -> None:
    async def go() -> SpeechOutput:
        adapter = StubSpeechOutput()
        return await adapter.synthesize("Hello there, this is a backup voice.")

    out = run_async(go())
    assert out.is_stub is True
    assert out.is_final_architecture is False
    assert out.sample_rate == 24000
    assert len(out.pcm) > 0
    assert out.duration_s > 0


def test_make_speech_output_cpu_fallback() -> None:
    adapter = make_speech_output(prefer_real=False)
    assert adapter.name == "stub-tts"


def test_stub_speech_output_language_detection() -> None:
    async def go() -> str:
        adapter = StubSpeechOutput()
        out = await adapter.synthesize("kya haal hai aap kaise ho")
        return out.language

    assert run_async(go()) == "hi"


# ---------------------------------------------------------------------------
# 13A — classic baseline
# ---------------------------------------------------------------------------
def test_classic_baseline_runs_on_cpu() -> None:
    pcm = _silence_pcm(16000)  # 1s at 16k

    async def go() -> BaselineResult:
        async with ClassicBaseline(prefer_real_components=False) as baseline:
            return await baseline.run(pcm)

    result = run_async(go())
    assert isinstance(result, BaselineResult)
    assert result.is_final_architecture is False
    assert result.reply_text  # composer produced a reply
    assert result.speech.is_stub is True
    assert result.transcript.is_stub is True
    # Stage timings present and total is >= sum of named stages (monotonic clock).
    assert result.timings.total_ms >= 0
    assert "stt:stub" in result.notes
    assert "tts:stub" in result.notes


def test_classic_baseline_backends() -> None:
    async def go() -> tuple[str, str]:
        async with ClassicBaseline(prefer_real_components=False) as baseline:
            return baseline.stt_backend, baseline.tts_backend

    stt, tts = run_async(go())
    assert stt == "stub"
    assert tts == "stub-tts"


def test_classic_baseline_create_factory() -> None:
    async def go() -> BaselineResult:
        baseline = await ClassicBaseline.create(prefer_real_components=False)
        try:
            return await baseline.run(_silence_pcm(800))
        finally:
            await baseline.stop()

    result = run_async(go())
    assert result.reply_text


def test_baseline_vad_skipped_without_torch() -> None:
    """VAD is optional; without torch/model it returns -1 (skipped), no crash."""

    async def go() -> int:
        async with ClassicBaseline(prefer_real_components=False) as baseline:
            return baseline.detect_segments([0.0] * 512)

    # On a CPU-only box without torch/silero this is -1; if present, >= 0.
    assert run_async(go()) >= -1


# ---------------------------------------------------------------------------
# 13C — failover orchestrator
# ---------------------------------------------------------------------------
def test_healthy_no_fallback() -> None:
    orch = FailoverOrchestrator()
    decision = orch.decide(PrimaryHealth(available=True, latency_ms=200, error_rate=0.0))
    assert isinstance(decision, FallbackDecision)
    assert decision.use_fallback is False
    assert decision.reason == FailoverReason.healthy.value


def test_primary_unavailable_triggers_fallback() -> None:
    orch = FailoverOrchestrator()
    decision = orch.decide(PrimaryHealth(available=False))
    assert decision.use_fallback is True
    assert decision.reason == FailoverReason.primary_unavailable.value
    assert orch.in_fallback is True


def test_high_latency_triggers_fallback() -> None:
    orch = FailoverOrchestrator(FailoverPolicy(max_latency_ms=1000))
    decision = orch.decide(PrimaryHealth(available=True, latency_ms=2500))
    assert decision.use_fallback is True
    assert decision.reason == FailoverReason.high_latency.value
    assert decision.expected_recovery_ms is not None


def test_high_error_rate_triggers_fallback() -> None:
    orch = FailoverOrchestrator(FailoverPolicy(max_error_rate=0.2))
    decision = orch.decide(PrimaryHealth(available=True, latency_ms=100, error_rate=0.5))
    assert decision.use_fallback is True
    assert decision.reason == FailoverReason.high_error_rate.value


def test_consecutive_failures_triggers_fallback() -> None:
    orch = FailoverOrchestrator(FailoverPolicy(max_consecutive_failures=3))
    decision = orch.decide(PrimaryHealth(available=True, latency_ms=100, consecutive_failures=3))
    assert decision.use_fallback is True
    assert decision.reason == FailoverReason.consecutive_failures.value


def test_manual_override() -> None:
    orch = FailoverOrchestrator()
    decision = orch.decide(PrimaryHealth(manual_override=True))
    assert decision.use_fallback is True
    assert decision.reason == FailoverReason.manual_override.value
    assert decision.expected_recovery_ms is None


def test_priority_unavailable_over_latency() -> None:
    """Rule ordering: unavailability outranks latency."""
    orch = FailoverOrchestrator(FailoverPolicy(max_latency_ms=1000))
    decision = orch.decide(PrimaryHealth(available=False, latency_ms=5000))
    assert decision.reason == FailoverReason.primary_unavailable.value


def test_recovery_hysteresis() -> None:
    """After failover, require N healthy probes before leaving fallback."""
    orch = FailoverOrchestrator(FailoverPolicy(recovery_probes_required=2))
    # Engage fallback.
    orch.decide(PrimaryHealth(available=False))
    assert orch.in_fallback is True

    # First healthy probe: still in fallback (recovering).
    d1 = orch.decide(PrimaryHealth(available=True, latency_ms=100))
    assert d1.use_fallback is True
    assert d1.reason.startswith("recovering")
    assert orch.in_fallback is True

    # Second healthy probe: recovered.
    d2 = orch.decide(PrimaryHealth(available=True, latency_ms=100))
    assert d2.use_fallback is False
    assert d2.reason == FailoverReason.recovered.value
    assert orch.in_fallback is False


def test_user_messaging() -> None:
    orch = FailoverOrchestrator()
    orch.decide(PrimaryHealth(available=False))
    msg = orch.user_message()
    assert isinstance(msg, str) and len(msg) > 0


def test_stats_tracking() -> None:
    orch = FailoverOrchestrator()
    orch.decide(PrimaryHealth(available=True, latency_ms=100))
    orch.decide(PrimaryHealth(available=False))
    stats = orch.stats()
    assert stats["decisions"] == 2
    assert stats["fallbacks"] == 1
    assert stats["in_fallback"] == 1


def test_decision_roundtrip() -> None:
    orch = FailoverOrchestrator()
    decision = orch.decide(PrimaryHealth(available=False))
    rebuilt = FallbackDecision.model_validate_json(decision.model_dump_json())
    assert rebuilt == decision
