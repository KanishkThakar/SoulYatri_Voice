"""
evals/latency/metrics.py — metric registry + in-process collector (Phase 15A).
==============================================================================
The canonical metric registry the master guide lists (``final_use.md`` §15A,
§12 evaluation matrix, ``docs/LATENCY_TARGETS.md``) plus a lightweight,
thread-safe, in-process metrics collector with p50/p95/p99 aggregation.

Design rules (final_use.md §3.3 / D-008):
  * pure stdlib — no numpy / prometheus_client / torch. Imports cleanly on a
    bare CPU-only machine.
  * deterministic: percentile math is exact and reproducible.
  * observable: the collector is the source of truth for regression gates
    (``evals/gates.py``) and the Prometheus-style exposition
    (``evals/observability.py``).

Two metric *families* exist:
  * **latency / timing** metrics (e.g. ``time_to_first_audible_ms``) aggregated
    as percentiles over a sample window.
  * **rate** metrics (e.g. ``filler_hit_rate``) aggregated as hits/total ratios.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "MetricKind",
    "MetricSpec",
    "METRICS",
    "METRIC_REGISTRY",
    "STAGE_LATENCY_METRICS",
    "metric_names",
    "Distribution",
    "percentile",
    "MetricsCollector",
]


# ---------------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------------
class MetricKind(str, Enum):
    """How a metric is aggregated and compared by the regression gates."""

    latency_ms = "latency_ms"  # timing in ms; percentile-aggregated; lower is better
    rate = "rate"  # ratio in [0, 1]; mean-aggregated
    score = "score"  # quality score in [0, 1]; mean-aggregated; higher is better
    gauge = "gauge"  # point-in-time value (e.g. gpu_utilization_pct)


@dataclass(frozen=True)
class MetricSpec:
    """Definition of a single tracked metric."""

    name: str
    kind: MetricKind
    unit: str
    description: str
    higher_is_better: bool = False


# The canonical names from final_use.md §15A starter skeleton (kept as a plain
# list for parity with the guide), extended with first-token + per-stage breakdown.
METRICS: list[str] = [
    "time_to_first_audible_ms",
    "turn_end_detection_delay_ms",
    "interruption_recovery_ms",
    "filler_hit_rate",
    "filler_false_positive_rate",
]

# Per-stage latency breakdown so "every delay has a measurable origin"
# (final_use.md §15A acceptance test; docs/LATENCY_TARGETS.md engineering checklist).
STAGE_LATENCY_METRICS: list[str] = [
    "stage_vad_ms",
    "stage_stt_ms",
    "stage_llm_ms",
    "stage_tts_ms",
    "stage_codec_ms",
    "stage_runtime_ms",
    "stage_decoder_ms",
]

_SPECS: list[MetricSpec] = [
    # --- core perceived-latency metrics (LATENCY_TARGETS.md) ---
    MetricSpec(
        "time_to_first_audible_ms",
        MetricKind.latency_ms,
        "ms",
        "End-of-user-turn to first audible assistant audio (TTFA).",
    ),
    MetricSpec(
        "first_token_ms",
        MetricKind.latency_ms,
        "ms",
        "Turn forward to first codec token from the runtime (first_token_time_ms).",
    ),
    MetricSpec(
        "turn_end_detection_delay_ms",
        MetricKind.latency_ms,
        "ms",
        "Actual end-of-speech to detected turn end.",
    ),
    MetricSpec(
        "interruption_recovery_ms",
        MetricKind.latency_ms,
        "ms",
        "Barge-in onset to clean output stop + recoverable state.",
    ),
    # --- filler routing rates ---
    MetricSpec(
        "filler_hit_rate",
        MetricKind.rate,
        "ratio",
        "Fraction of trivial turns correctly served by cached filler.",
        higher_is_better=True,
    ),
    MetricSpec(
        "filler_false_positive_rate",
        MetricKind.rate,
        "ratio",
        "Fraction of non-trivial turns wrongly served by filler.",
    ),
    # --- §12 quality dimensions ---
    MetricSpec(
        "wer",
        MetricKind.score,
        "ratio",
        "Word error rate over intelligibility fixtures (lower is better).",
    ),
    MetricSpec(
        "emotion_agreement",
        MetricKind.score,
        "ratio",
        "Agreement between produced and intended affect (higher is better).",
        higher_is_better=True,
    ),
    MetricSpec(
        "code_switch_score",
        MetricKind.score,
        "ratio",
        "Hinglish code-switch fluency score (higher is better).",
        higher_is_better=True,
    ),
    MetricSpec(
        "naturalness_proxy",
        MetricKind.score,
        "ratio",
        "UTMOS-like naturalness proxy in [0, 1] (higher is better).",
        higher_is_better=True,
    ),
    # --- stability gauge ---
    MetricSpec(
        "gpu_utilization_pct",
        MetricKind.gauge,
        "percent",
        "GPU utilization gauge (recorded for capacity, not gated by default).",
    ),
]

# Add per-stage latency specs to the registry programmatically.
for _stage in STAGE_LATENCY_METRICS:
    _SPECS.append(
        MetricSpec(
            _stage,
            MetricKind.latency_ms,
            "ms",
            f"Per-stage latency breakdown: {_stage.replace('stage_', '').replace('_ms', '')}.",
        )
    )

METRIC_REGISTRY: dict[str, MetricSpec] = {spec.name: spec for spec in _SPECS}


def metric_names() -> list[str]:
    """All registered metric names (sorted, deterministic)."""
    return sorted(METRIC_REGISTRY)


# ---------------------------------------------------------------------------
# Percentile math
# ---------------------------------------------------------------------------
def percentile(values: list[float], q: float) -> float:
    """Exact linear-interpolation percentile (same method as numpy default).

    ``q`` is a percentile in [0, 100]. For an empty input returns 0.0. For a
    single value returns that value. Uses the "linear" interpolation method so
    p50 of an even-length sorted list is the mean of the two central elements.
    """
    if not values:
        return 0.0
    if q <= 0:
        return float(min(values))
    if q >= 100:
        return float(max(values))
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (q / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[int(rank)])
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


@dataclass
class Distribution:
    """Aggregated view of a sample window for one metric."""

    name: str
    count: int
    p50: float
    p95: float
    p99: float
    mean: float
    min: float
    max: float

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "name": self.name,
            "count": self.count,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "mean": self.mean,
            "min": self.min,
            "max": self.max,
        }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
@dataclass
class _Samples:
    values: deque[float] = field(default_factory=lambda: deque(maxlen=4096))


class MetricsCollector:
    """Thread-safe in-process metrics collector.

    Records raw samples per metric name and aggregates them on demand into
    :class:`Distribution` objects (latency / score) or a mean ratio (rate).
    This is the single source of truth that regression gates and the
    Prometheus-style exposition read from. It does **not** require a running
    Prometheus — exposition is a pure render step (see ``evals/observability.py``).
    """

    def __init__(self, window: int = 4096) -> None:
        self._window = window
        self._samples: dict[str, _Samples] = defaultdict(lambda: _Samples(deque(maxlen=window)))
        self._lock = threading.Lock()

    # -- recording --------------------------------------------------------
    def record(self, name: str, value: float) -> None:
        """Record a single observation for ``name``."""
        with self._lock:
            self._samples[name].values.append(float(value))

    def record_many(self, name: str, values: list[float]) -> None:
        with self._lock:
            self._samples[name].values.extend(float(v) for v in values)

    def record_timing(self, name: str, ms: float) -> None:
        """Record a latency observation (alias clarifying units)."""
        self.record(name, ms)

    def record_rate_event(self, name: str, hit: bool) -> None:
        """Record a boolean event for a rate metric (1.0 hit / 0.0 miss)."""
        self.record(name, 1.0 if hit else 0.0)

    # -- inspection -------------------------------------------------------
    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._samples)

    def values(self, name: str) -> list[float]:
        with self._lock:
            samples = self._samples.get(name)
            return list(samples.values) if samples else []

    def count(self, name: str) -> int:
        return len(self.values(name))

    def mean(self, name: str) -> float:
        vals = self.values(name)
        return sum(vals) / len(vals) if vals else 0.0

    def distribution(self, name: str) -> Distribution:
        """Aggregate ``name`` into a percentile distribution."""
        vals = self.values(name)
        if not vals:
            return Distribution(name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return Distribution(
            name=name,
            count=len(vals),
            p50=percentile(vals, 50),
            p95=percentile(vals, 95),
            p99=percentile(vals, 99),
            mean=sum(vals) / len(vals),
            min=float(min(vals)),
            max=float(max(vals)),
        )

    def snapshot(self) -> dict[str, Distribution]:
        """Aggregate every recorded metric into distributions."""
        return {name: self.distribution(name) for name in self.names()}

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()
