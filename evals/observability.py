"""
evals/observability.py — structured logging + Prometheus-style exposition (Phase 15A).
======================================================================================
"Every delay has a measurable origin." This module turns a
:class:`evals.latency.metrics.MetricsCollector` snapshot into:

  * **structured logs** (``logger.info("event", key=value)``) — degrades cleanly
    to stdlib logging when ``structlog`` is unavailable, mirroring
    ``aux/text_brain/obs.py`` and ``server/utils/logging_config.py``.
  * a **Prometheus-style text exposition** — a pure ``render`` function. It does
    NOT require (or start) a Prometheus server; ``infra/`` owns real scraping
    (final_use.md §15A). We only expose the text format so dashboards/tests can
    read it.

Pure stdlib only (no prometheus_client). CPU-only, deterministic.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from evals.latency.metrics import METRIC_REGISTRY, Distribution, MetricsCollector

__all__ = [
    "get_logger",
    "StructuredEvent",
    "EventLog",
    "render_prometheus",
    "render_structured_lines",
    "log_snapshot",
]


# ---------------------------------------------------------------------------
# Structured logging (structlog if present, stdlib adapter otherwise)
# ---------------------------------------------------------------------------
class _StdlibStructLogger:
    """Minimal structlog-style adapter over stdlib :mod:`logging`.

    Supports ``logger.info("event_name", key=value, ...)`` so call-sites are
    identical whether or not ``structlog`` is installed.
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    @staticmethod
    def _render(event: str, fields: dict[str, Any]) -> str:
        if not fields:
            return event
        kv = " ".join(f"{k}={v!r}" for k, v in fields.items())
        return f"{event} {kv}"

    def debug(self, event: str, **fields: Any) -> None:
        self._log.debug(self._render(event, fields))

    def info(self, event: str, **fields: Any) -> None:
        self._log.info(self._render(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._log.warning(self._render(event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self._log.error(self._render(event, fields))


def get_logger(name: str = "evals") -> Any:
    """Return a structured logger (structlog if available, stdlib adapter else)."""
    try:
        import structlog  # noqa: PLC0415 (intentional lazy/optional import)

        return structlog.get_logger(name)
    except Exception:  # pragma: no cover - exercised only without structlog
        return _StdlibStructLogger(name)


# ---------------------------------------------------------------------------
# In-memory structured event log (observable hook for tests + ops)
# ---------------------------------------------------------------------------
@dataclass
class StructuredEvent:
    """A single structured observability event."""

    name: str
    ts_ms: int
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"event": self.name, "ts_ms": self.ts_ms, **self.fields}


class EventLog:
    """Thread-safe bounded ring buffer of structured events.

    Wraps :func:`get_logger` so each recorded event is also emitted to the
    structured logger. Acts as the structured-logging hook required by the
    Definition of Done (final_use.md §3.3).
    """

    def __init__(self, name: str = "evals", maxlen: int = 2048) -> None:
        self._events: deque[StructuredEvent] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._logger = get_logger(name)

    def emit(self, name: str, **fields: Any) -> StructuredEvent:
        evt = StructuredEvent(name=name, ts_ms=int(time.time() * 1000), fields=fields)
        with self._lock:
            self._events.append(evt)
        self._logger.info(name, **fields)
        return evt

    def events(self, name: str | None = None) -> list[StructuredEvent]:
        with self._lock:
            items = list(self._events)
        if name is None:
            return items
        return [e for e in items if e.name == name]

    def last(self, name: str | None = None) -> StructuredEvent | None:
        evts = self.events(name)
        return evts[-1] if evts else None

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# ---------------------------------------------------------------------------
# Prometheus-style text exposition (no server required)
# ---------------------------------------------------------------------------
def _sanitize_metric_name(name: str) -> str:
    """Prometheus metric names must match [a-zA-Z_:][a-zA-Z0-9_:]*."""
    safe = "".join(c if (c.isalnum() or c in "_:") else "_" for c in name)
    if safe and safe[0].isdigit():
        safe = "_" + safe
    return f"soulyatri_eval_{safe}"


def _emit_metric_lines(
    base: str, help_text: str, samples: list[tuple[str, float]]
) -> list[str]:
    lines = [f"# HELP {base} {help_text}", f"# TYPE {base} gauge"]
    for suffix, value in samples:
        metric = f"{base}_{suffix}" if suffix else base
        # Re-emit HELP/TYPE per suffixed series for valid exposition.
        if suffix:
            lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric} {value!r}")
    return lines


def render_prometheus(collector: MetricsCollector) -> str:
    """Render a Prometheus text-exposition string from a collector snapshot.

    Latency/score metrics are exposed as ``_p50``/``_p95``/``_p99``/``_count``
    series; rate/gauge metrics as a single mean value. This is a pure function:
    it neither starts a server nor performs IO.
    """
    out: list[str] = []
    snapshot = collector.snapshot()
    for name in sorted(snapshot):
        dist = snapshot[name]
        spec = METRIC_REGISTRY.get(name)
        help_text = spec.description if spec else name
        base = _sanitize_metric_name(name)
        kind = spec.kind.value if spec else "score"
        if kind in ("rate", "gauge"):
            out.extend(_emit_metric_lines(base, help_text, [("", dist.mean)]))
        else:
            out.extend(
                _emit_metric_lines(
                    base,
                    help_text,
                    [
                        ("p50", dist.p50),
                        ("p95", dist.p95),
                        ("p99", dist.p99),
                        ("count", float(dist.count)),
                    ],
                )
            )
    return "\n".join(out) + ("\n" if out else "")


def render_structured_lines(collector: MetricsCollector) -> list[dict[str, Any]]:
    """Render the snapshot as a list of structured (JSON-ready) dicts."""
    return [dist.to_dict() for _, dist in sorted(collector.snapshot().items())]


def log_snapshot(collector: MetricsCollector, event_log: EventLog | None = None) -> EventLog:
    """Emit one structured event per metric distribution; return the EventLog."""
    log = event_log or EventLog()
    for name, dist in sorted(collector.snapshot().items()):
        _emit_distribution(log, name, dist)
    return log


def _emit_distribution(log: EventLog, name: str, dist: Distribution) -> None:
    log.emit(
        "metric_snapshot",
        metric=name,
        count=dist.count,
        p50=dist.p50,
        p95=dist.p95,
        p99=dist.p99,
        mean=dist.mean,
    )
