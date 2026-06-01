"""
Tests for safety/watermark/audioseal.py (Phase 11C).

Covers: watermark insert + verify on EVERY output path (including the deterministic
fallback), detector-outcome logging, non-compliant flagging when verification fails
(tampering / missing mark / detector error), the compliance hard-gate, and ops tooling.
"""

from __future__ import annotations

import importlib

import pytest

from safety.contracts import WatermarkMarker
from safety.watermark.audioseal import (
    DEFAULT_PAYLOAD,
    DeterministicFallbackBackend,
    WatermarkComplianceError,
    Watermarker,
    ops_status,
)

_SAMPLE = [0.0, 0.2, -0.2, 0.5, -0.5, 0.33, -0.33, 0.1, -0.1, 0.0]


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------
def test_module_imports_clean() -> None:
    mod = importlib.import_module("safety.watermark.audioseal")
    assert hasattr(mod, "Watermarker")


def test_no_heavy_imports() -> None:
    import sys

    importlib.import_module("safety.watermark.audioseal")
    for heavy in ("torch", "transformers", "audioseal", "moshi", "mimi"):
        assert heavy not in sys.modules


# ---------------------------------------------------------------------------
# Insert + verify round-trip (fallback backend = the CPU-only path)
# ---------------------------------------------------------------------------
def test_protect_marks_and_verifies() -> None:
    wm = Watermarker()
    assert wm.backend_name == "deterministic_fallback"
    watermarked, result = wm.protect(_SAMPLE, 24000)
    assert watermarked.compliant is True
    assert result.compliant is True
    assert result.detected is True
    assert result.payload == DEFAULT_PAYLOAD


def test_embed_then_verify_separately() -> None:
    wm = Watermarker()
    watermarked = wm.embed(_SAMPLE, 24000)
    assert isinstance(watermarked.marker, WatermarkMarker)
    result = wm.verify(watermarked.samples, watermarked.sample_rate, watermarked.marker)
    assert result.compliant is True


def test_watermark_changes_samples() -> None:
    backend = DeterministicFallbackBackend()
    watermarked = backend.embed(_SAMPLE, 24000, DEFAULT_PAYLOAD)
    # The marker perturbs the audio deterministically (provably transformed).
    assert watermarked.samples != _SAMPLE
    assert len(watermarked.samples) == len(_SAMPLE)


# ---------------------------------------------------------------------------
# Non-compliant flagging: tampering / wrong payload / detector error
# ---------------------------------------------------------------------------
def test_tampered_audio_flagged_non_compliant() -> None:
    wm = Watermarker()
    watermarked, _ = wm.protect(_SAMPLE, 24000)
    tampered = list(watermarked.samples)
    tampered[0] = 0.999  # edit a sample after watermarking
    result = wm.verify(tampered, watermarked.sample_rate, watermarked.marker)
    assert result.detected is False
    assert result.compliant is False  # must be flagged non-compliant


def test_forged_marker_flagged_non_compliant() -> None:
    wm = Watermarker()
    watermarked, _ = wm.protect(_SAMPLE, 24000)
    forged = watermarked.marker.model_copy(update={"signature": "deadbeef"})
    result = wm.verify(watermarked.samples, watermarked.sample_rate, forged)
    assert result.compliant is False


def test_detector_error_fails_closed() -> None:
    class _BrokenBackend:
        name = "broken"

        def embed(self, samples, sample_rate, payload):  # pragma: no cover - unused
            raise RuntimeError("no embed")

        def detect(self, samples, sample_rate, marker):
            raise RuntimeError("detector exploded")

    wm = Watermarker(backend=_BrokenBackend())
    marker = WatermarkMarker(
        payload="X", signature="y", backend="broken", sample_rate=24000, num_samples=3
    )
    result = wm.verify([0.0, 0.1, 0.2], 24000, marker)
    assert result.compliant is False
    assert "fail_closed" in result.reason


def test_embed_error_fails_closed_no_emit() -> None:
    class _NoEmbed:
        name = "noembed"

        def embed(self, samples, sample_rate, payload):
            raise RuntimeError("embed failed")

        def detect(self, samples, sample_rate, marker):  # pragma: no cover - unused
            raise RuntimeError

    wm = Watermarker(backend=_NoEmbed())
    watermarked, result = wm.protect(_SAMPLE, 24000)
    assert result.compliant is False
    assert watermarked.compliant is False
    assert watermarked.samples == []  # nothing emittable


# ---------------------------------------------------------------------------
# Compliance hard-gate for emit paths
# ---------------------------------------------------------------------------
def test_assert_compliant_passes_for_good_audio() -> None:
    wm = Watermarker()
    _, result = wm.protect(_SAMPLE, 24000)
    wm.assert_compliant(result)  # should not raise


def test_assert_compliant_raises_for_bad_audio() -> None:
    wm = Watermarker()
    watermarked, _ = wm.protect(_SAMPLE, 24000)
    bad = wm.verify([0.0] * len(watermarked.samples), watermarked.sample_rate, watermarked.marker)
    with pytest.raises(WatermarkComplianceError):
        wm.assert_compliant(bad)


# ---------------------------------------------------------------------------
# "Every output path" — empty audio + fallback path are still watermarked
# ---------------------------------------------------------------------------
def test_empty_audio_still_watermarked_and_verifiable() -> None:
    wm = Watermarker()
    watermarked, result = wm.protect([], 24000)
    assert result.compliant is True  # empty stream still gets a verifiable marker
    assert watermarked.marker.num_samples == 0


def test_fallback_path_audio_is_watermarked() -> None:
    # Simulates the classic STT->LLM->TTS fallback (Phase 13) routing through the same API.
    wm = Watermarker()
    fallback_tts_pcm = [0.05 * ((i % 7) - 3) for i in range(200)]
    watermarked, result = wm.protect(fallback_tts_pcm, 24000)
    assert result.compliant is True
    assert watermarked.compliant is True


# ---------------------------------------------------------------------------
# Detector-outcome logging (auditable)
# ---------------------------------------------------------------------------
def test_verify_outcomes_are_logged() -> None:
    wm = Watermarker()
    watermarked, _ = wm.protect(_SAMPLE, 24000)
    wm.verify(watermarked.samples, watermarked.sample_rate, watermarked.marker)  # compliant
    wm.verify([0.0] * len(watermarked.samples), watermarked.sample_rate, watermarked.marker)  # not
    verify_events = wm.audit.filter(action="verify")
    outcomes = {e.outcome for e in verify_events}
    assert "compliant" in outcomes
    assert "non_compliant" in outcomes
    for e in verify_events:
        e.model_validate(e.model_dump())  # JSON round-trippable


# ---------------------------------------------------------------------------
# Lazy AudioSeal backend hook honored
# ---------------------------------------------------------------------------
def test_injected_audioseal_backend_used() -> None:
    class _FakeAudioSeal:
        name = "audioseal"

        def embed(self, samples, sample_rate, payload):
            from safety.contracts import WatermarkedAudio

            marker = WatermarkMarker(
                payload=payload,
                signature="seal",
                backend=self.name,
                sample_rate=sample_rate,
                num_samples=len(list(samples)),
            )
            return WatermarkedAudio(
                samples=list(samples), sample_rate=sample_rate, marker=marker, compliant=False
            )

        def detect(self, samples, sample_rate, marker):
            from safety.contracts import WatermarkResult

            return WatermarkResult(
                detected=True, score=0.98, payload=marker.payload, backend=self.name, compliant=True
            )

    wm = Watermarker(backend=_FakeAudioSeal())
    assert wm.backend_name == "audioseal"
    _, result = wm.protect(_SAMPLE, 24000)
    assert result.compliant is True
    assert result.score == pytest.approx(0.98)


# ---------------------------------------------------------------------------
# Ops tooling
# ---------------------------------------------------------------------------
def test_ops_status_self_check() -> None:
    status = ops_status()
    assert status["backend"] == "deterministic_fallback"
    assert status["self_check_compliant"] is True
    assert status["self_check_score"] == 1.0
    assert status["audit_events"] >= 1
