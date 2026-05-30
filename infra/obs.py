"""
infra observability — structured logging hooks (dependency-light)
==================================================================
Shared, dependency-light structured-logging helper for the ``infra/`` domain
(scaling, deploy, monitoring).

Why this lives here
-------------------
``infra/`` code (the session scheduler, region router, rollback evaluator) runs on a
CPU-only machine with no guaranteed extras and **must import and unit-test without a
cluster, GPU, or live services**. The server uses ``structlog``
(``server/utils/logging_config.py``), but ``structlog`` is optional in this environment.

This mirrors the proven ``aux/text_brain/obs.py`` shim: it offers the same
``logger.info("event", key=value)`` ergonomics and degrades cleanly to the stdlib
:mod:`logging` module when ``structlog`` is unavailable. It also exposes a tiny
thread-safe :class:`TelemetryRecorder` so admission decisions, routing choices, and
rollback verdicts are observable in tests and during local bring-up without wiring a
running Prometheus (production export is configured under ``infra/monitoring/``).

Hard rule: no heavy imports here (no torch / transformers / moshi / mimi / numpy /
prometheus runtime).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "get_logger",
    "TelemetryEvent",
    "TelemetryRecorder",
    "telemetry",
]


# ---------------------------------------------------------------------------
# Structured logging that works with or without structlog
# ---------------------------------------------------------------------------
class _StdlibStructLogger:
    """A minimal structlog-style adapter over the stdlib :mod:`logging`.

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


def get_logger(name: str) -> Any:
    """Return a structured logger.

    Prefers ``structlog`` (for parity with ``server/utils/logging_config.py``) and
    falls back to a stdlib adapter with the same call signature when ``structlog``
    is not installed.
    """
    try:
        import structlog  # noqa: PLC0415 (intentional lazy/optional import)

        return structlog.get_logger(name)
    except Exception:  # pragma: no cover - exercised only without structlog
        return _StdlibStructLogger(name)


# ---------------------------------------------------------------------------
# Lightweight telemetry recorder (observable hooks for tests + ops)
# ---------------------------------------------------------------------------
@dataclass
class TelemetryEvent:
    """A single structured telemetry event."""

    name: str
    ts_ms: int
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ts_ms": self.ts_ms, **self.fields}


class TelemetryRecorder:
    """A thread-safe, bounded, in-memory ring buffer of telemetry events.

    This is deliberately tiny: it makes admission/routing/rollback behaviour
    observable in tests and during local bring-up. Production metrics export
    (Prometheus) is configured under ``infra/monitoring/``.
    """

    def __init__(self, maxlen: int = 1024) -> None:
        self._events: deque[TelemetryEvent] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, name: str, **fields: Any) -> TelemetryEvent:
        evt = TelemetryEvent(name=name, ts_ms=int(time.time() * 1000), fields=fields)
        with self._lock:
            self._events.append(evt)
        return evt

    def events(self, name: str | None = None) -> list[TelemetryEvent]:
        with self._lock:
            items = list(self._events)
        if name is None:
            return items
        return [e for e in items if e.name == name]

    def count(self, name: str | None = None) -> int:
        return len(self.events(name))

    def last(self, name: str | None = None) -> TelemetryEvent | None:
        evts = self.events(name)
        return evts[-1] if evts else None

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# Module-level default recorder shared across the infra domain.
telemetry = TelemetryRecorder()
