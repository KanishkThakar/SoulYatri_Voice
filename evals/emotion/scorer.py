"""
evals/emotion/scorer.py — emotion-label agreement vs intended affect (§12).
===========================================================================
Deterministic, fixture-based scoring for the emotion dimension of the
evaluation matrix: "agreement with intended affect + human review … continuous
control, not tags only" (final_use.md §12, §9A).

Two complementary signals, both pure-Python (no models, CPU-only):

  * **label agreement** — does the produced discrete emotion label match the
    intended one? Exact match scores 1.0; a small *confusable* map gives partial
    credit for near-misses (e.g. ``warm`` vs ``friendly``) so the metric is not
    brittle to synonym choice.
  * **continuous affect agreement** — agreement in the continuous
    valence/arousal/dominance space from ``shared.contracts.EmotionState``.
    Computed as ``1 - normalized_distance`` so identical affect → 1.0.

The combined score blends both, matching the guide's "continuous control, not
tags only" intent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shared.contracts import EmotionState

__all__ = [
    "CONFUSABLE_EMOTIONS",
    "normalize_label",
    "label_agreement",
    "vad_agreement",
    "EmotionSample",
    "score_emotion",
    "score_samples",
    "load_samples",
]


# Near-synonym emotion clusters. Labels within the same cluster get partial
# credit. Kept explicit + auditable; intentionally small.
CONFUSABLE_EMOTIONS: dict[str, set[str]] = {
    "warm": {"warm", "friendly", "kind", "caring", "empathetic"},
    "neutral": {"neutral", "calm", "flat"},
    "distress": {"distress", "sad", "overwhelmed", "anxious", "worried"},
    "happy": {"happy", "joy", "cheerful", "excited"},
    "angry": {"angry", "frustrated", "annoyed"},
}

# Partial-credit weight for a confusable (same-cluster) near-miss.
_PARTIAL_CREDIT = 0.5


def normalize_label(label: str | None) -> str:
    """Lower-case + strip an emotion label; ``None`` → empty string."""
    return (label or "").strip().casefold()


def _cluster_of(label: str) -> str | None:
    """Return the cluster key whose synonym set contains ``label`` (or None)."""
    for key, members in CONFUSABLE_EMOTIONS.items():
        if label == key or label in members:
            return key
    return None


def label_agreement(produced: str | None, intended: str | None) -> float:
    """Agreement between two discrete emotion labels in [0, 1].

      * exact (normalized) match → 1.0,
      * same confusable cluster → ``_PARTIAL_CREDIT``,
      * otherwise → 0.0.

    If the intended label is empty/None, agreement is defined as 1.0 (nothing to
    disagree with).
    """
    p, i = normalize_label(produced), normalize_label(intended)
    if not i:
        return 1.0
    if p == i:
        return 1.0
    cp, ci = _cluster_of(p), _cluster_of(i)
    if cp is not None and cp == ci:
        return _PARTIAL_CREDIT
    return 0.0


def vad_agreement(produced: EmotionState, intended: EmotionState) -> float:
    """Continuous affect agreement over valence/arousal/dominance in [0, 1].

    Each axis is in [-1, 1], so the max per-axis difference is 2.0 and the max
    Euclidean distance over 3 axes is ``2*sqrt(3)``. Agreement is
    ``1 - distance / max_distance`` → 1.0 for identical affect, 0.0 for the
    polar opposite.
    """
    dv = produced.valence - intended.valence
    da = produced.arousal - intended.arousal
    dd = produced.dominance - intended.dominance
    dist = math.sqrt(dv * dv + da * da + dd * dd)
    max_dist = 2.0 * math.sqrt(3.0)
    return max(0.0, min(1.0, 1.0 - dist / max_dist))


@dataclass
class EmotionSample:
    """One emotion evaluation sample.

    ``intended_label`` / ``produced_label`` drive label agreement. The optional
    ``intended`` / ``produced`` :class:`EmotionState` objects drive continuous
    V/A/D agreement. ``blend`` controls how much weight the continuous component
    receives when both signals are present.
    """

    intended_label: str | None = None
    produced_label: str | None = None
    intended: EmotionState | None = None
    produced: EmotionState | None = None
    blend: float = 0.5


def score_emotion(sample: EmotionSample) -> float:
    """Combined emotion-agreement score in [0, 1] for one sample.

    Combines label agreement and continuous V/A/D agreement. If only one signal
    is available, that signal is used alone. If neither is available, the score
    is 1.0 (nothing asserted).
    """
    has_labels = sample.intended_label is not None or sample.produced_label is not None
    has_vad = sample.intended is not None and sample.produced is not None

    if has_labels and has_vad:
        lab = label_agreement(sample.produced_label, sample.intended_label)
        vad = vad_agreement(sample.produced, sample.intended)  # type: ignore[arg-type]
        blend = max(0.0, min(1.0, sample.blend))
        return (1.0 - blend) * lab + blend * vad
    if has_vad:
        return vad_agreement(sample.produced, sample.intended)  # type: ignore[arg-type]
    if has_labels:
        return label_agreement(sample.produced_label, sample.intended_label)
    return 1.0


def score_samples(samples: list[EmotionSample]) -> float:
    """Mean emotion-agreement score across ``samples`` (1.0 if empty)."""
    if not samples:
        return 1.0
    return sum(score_emotion(s) for s in samples) / len(samples)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------
def _emotion_from_dict(data: dict | None) -> EmotionState | None:
    """Build an :class:`EmotionState` from a partial dict (defaults fill the rest)."""
    if data is None:
        return None
    return EmotionState(**data)


def load_samples(path: str | None = None) -> list[EmotionSample]:
    """Load :class:`EmotionSample` fixtures from a JSON file.

    Defaults to the bundled ``evals/emotion/fixtures.json``.
    """
    import json
    from pathlib import Path

    p = Path(path) if path is not None else Path(__file__).parent / "fixtures.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return [
        EmotionSample(
            intended_label=s.get("intended_label"),
            produced_label=s.get("produced_label"),
            intended=_emotion_from_dict(s.get("intended")),
            produced=_emotion_from_dict(s.get("produced")),
            blend=s.get("blend", 0.5),
        )
        for s in data.get("samples", [])
    ]
