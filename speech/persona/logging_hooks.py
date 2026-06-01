"""
speech/persona/logging_hooks.py — Structured logging hooks for the persona layer.
=================================================================================
Definition-of-done (final_use.md §3.3) requires *structured logging hooks*. The rest of
the codebase uses ``structlog`` (see ``server/utils/logging_config.py``), but the
CPU-only / no-weights foundation must import cleanly even when optional deps are missing
(DECISIONS.md D-008). So this module exposes a single ``get_logger(name)`` that:

* returns a real ``structlog`` bound logger when ``structlog`` is installed, and
* otherwise falls back to a tiny stdlib-``logging`` adapter that accepts the same
  ``logger.info("event_name", key=value, ...)`` keyword-style call shape.

Either way, callers write ``log.info("emotion_clamped", field="valence", value=1.0)`` and
nothing crashes regardless of which backend is active.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["get_logger"]


class _StdlibStructAdapter:
    """Adapt a stdlib :class:`logging.Logger` to the structlog keyword-event call style.

    structlog loggers are called as ``log.info("event", key=value)``. The stdlib logger
    expects ``log.info(msg, *args)`` and would treat keyword args as reserved options, so
    we fold the structured fields into a deterministic ``key=value`` suffix instead.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _emit(self, level: int, event: str, **fields: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        if fields:
            rendered = " ".join(f"{k}={v!r}" for k, v in sorted(fields.items()))
            self._logger.log(level, "%s %s", event, rendered)
        else:
            self._logger.log(level, "%s", event)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, **fields)

    # Bind context-style call; stdlib has no contextvars merge so we just return self.
    def bind(self, **_fields: Any) -> _StdlibStructAdapter:
        return self


def get_logger(name: str) -> Any:
    """Return a structured logger, preferring ``structlog`` when available.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A ``structlog`` bound logger, or a stdlib-backed adapter exposing the same
        ``level(event, **fields)`` call shape.
    """
    try:  # pragma: no cover - exercised implicitly by whichever backend is installed
        import structlog

        return structlog.get_logger(name)
    except Exception:  # pragma: no cover - structlog optional on CPU-only foundation
        return _StdlibStructAdapter(logging.getLogger(name))
