"""
evals/audio/scorer.py — intelligibility (WER) + naturalness proxy (§12).
========================================================================
Deterministic, fixture-based scoring for the audio dimension of the evaluation
matrix (final_use.md §12):

  * **intelligibility** — token-level Word Error Rate of a transcript hypothesis
    against the reference, via ``evals.text_metrics.word_error_rate``. The
    fallback STT path supplies the hypothesis in production; in evals we score
    fixed transcript fixtures so the metric is reproducible without models.
  * **naturalness proxy** — a UTMOS-*like* proxy in [0, 1]. Real naturalness
    needs human MOS / a learned UTMOS model (final_use.md §12 "human listening
    tests, UTMOS-like proxy"); neither runs CPU-only-deterministically here, so
    we expose an explicit, documented heuristic over *symbolic* signal features
    (smooth chunk joins, no clipping, stable pacing, no repeated artifacts).

The proxy is intentionally simple and auditable. It is a measurable stand-in for
regression tracking, **not** a claim of true MOS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.text_metrics import word_error_rate

__all__ = [
    "wer",
    "intelligibility",
    "AudioQualityFeatures",
    "naturalness_proxy",
    "WerSample",
    "score_wer_samples",
    "score_naturalness_samples",
    "load_fixtures",
]


def wer(reference: str, hypothesis: str) -> float:
    """Token-level Word Error Rate (delegates to ``evals.text_metrics``)."""
    return word_error_rate(reference, hypothesis)


def intelligibility(reference: str, hypothesis: str) -> float:
    """Intelligibility score = ``1 - min(WER, 1.0)`` in [0, 1] (higher better)."""
    return max(0.0, 1.0 - min(1.0, wer(reference, hypothesis)))


@dataclass
class AudioQualityFeatures:
    """Symbolic, pre-extracted signal features for the naturalness proxy.

    These are deterministic numbers a (mock) decoder/QA stage can emit — they do
    **not** require decoding real waveforms here. All are in [0, 1] unless noted.

      * ``clipping_ratio`` — fraction of samples that clipped (lower better).
      * ``join_discontinuity`` — mean chunk-boundary discontinuity (lower better).
      * ``pace_deviation`` — |actual − target| speaking-rate deviation (lower better).
      * ``repeated_artifact_ratio`` — fraction of repeated/looped frames (lower better).
      * ``silence_ratio`` — fraction of dead air inside the turn (lower better).
    """

    clipping_ratio: float = 0.0
    join_discontinuity: float = 0.0
    pace_deviation: float = 0.0
    repeated_artifact_ratio: float = 0.0
    silence_ratio: float = 0.0

    # Relative weights for each penalty term (sum need not be 1; normalized below).
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "clipping_ratio": 1.5,
            "join_discontinuity": 1.0,
            "pace_deviation": 0.75,
            "repeated_artifact_ratio": 1.25,
            "silence_ratio": 0.5,
        }
    )


def naturalness_proxy(features: AudioQualityFeatures) -> float:
    """UTMOS-like naturalness proxy in [0, 1] (higher is better).

    Computes ``1 - weighted_mean(penalties)``. With all penalties at 0.0 the
    proxy is 1.0 (ideal); as artifacts grow the proxy degrades toward 0.0. The
    weighted mean keeps the result bounded in [0, 1] for inputs in [0, 1].
    """
    penalties = {
        "clipping_ratio": features.clipping_ratio,
        "join_discontinuity": features.join_discontinuity,
        "pace_deviation": features.pace_deviation,
        "repeated_artifact_ratio": features.repeated_artifact_ratio,
        "silence_ratio": features.silence_ratio,
    }
    total_w = sum(features.weights.get(k, 0.0) for k in penalties)
    if total_w <= 0:
        return 1.0
    weighted = sum(
        features.weights.get(k, 0.0) * max(0.0, min(1.0, v)) for k, v in penalties.items()
    )
    score = 1.0 - weighted / total_w
    return max(0.0, min(1.0, score))


@dataclass
class WerSample:
    """One intelligibility sample: a reference transcript + an STT hypothesis."""

    reference: str
    hypothesis: str
    language: str = "en"


def score_wer_samples(samples: list[WerSample]) -> float:
    """Mean WER across ``samples`` (0.0 if empty — perfect by convention)."""
    if not samples:
        return 0.0
    return sum(wer(s.reference, s.hypothesis) for s in samples) / len(samples)


def score_naturalness_samples(samples: list[AudioQualityFeatures]) -> float:
    """Mean naturalness proxy across feature samples (1.0 if empty)."""
    if not samples:
        return 1.0
    return sum(naturalness_proxy(s) for s in samples) / len(samples)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------
def load_fixtures(
    path: str | None = None,
) -> tuple[list[WerSample], list[AudioQualityFeatures]]:
    """Load WER + naturalness fixtures from a JSON file.

    Returns ``(wer_samples, naturalness_samples)``. Defaults to the bundled
    ``evals/audio/fixtures.json``.
    """
    import json
    from pathlib import Path

    p = Path(path) if path is not None else Path(__file__).parent / "fixtures.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    wer_samples = [
        WerSample(
            reference=s["reference"],
            hypothesis=s["hypothesis"],
            language=s.get("language", "en"),
        )
        for s in data.get("wer_samples", [])
    ]
    nat_samples = [
        AudioQualityFeatures(
            clipping_ratio=s.get("clipping_ratio", 0.0),
            join_discontinuity=s.get("join_discontinuity", 0.0),
            pace_deviation=s.get("pace_deviation", 0.0),
            repeated_artifact_ratio=s.get("repeated_artifact_ratio", 0.0),
            silence_ratio=s.get("silence_ratio", 0.0),
        )
        for s in data.get("naturalness_samples", [])
    ]
    return wer_samples, nat_samples
