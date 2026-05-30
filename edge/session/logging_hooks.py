"""
edge/session/logging_hooks.py — Structured logging hooks for the edge runtime
==============================================================================
Owner: edge/runtime agent (final_use.md §3.3 "structured logging hooks").

The server uses ``structlog`` (see ``server/utils/logging_config.py``), but the edge
subsystem must import and run on a bare CPU-only machine where ``structlog`` may not be
installed. This module provides a tiny, dependency-light structured logger that:

* uses ``structlog`` when it is available (so logs merge with the server format), and
* falls back to the stdlib ``logging`` module with ``key=value`` rendering otherwise.

The returned logger always supports ``debug/info/warning/error(event, **fields)`` so the
rest of the edge code can emit auditable, structured events without caring which backend
is active. This keeps the "structured logging hooks" definition-of-done satisfied on
CPU-only environments with no extra dependencies.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol


class StructuredLogger(Protocol):
    """Minimal structured-logging surface used across the edge subsystem."""

    def debug(self, event: str, **fields: Any) -> None: ...
    def info(self, event: str, **fields: Any) -> None: ...
    def warning(self, event: str, **fields: Any) -> None: ...
    def error(self, event: str, **fields: Any) -> None: ...


class _StdlibStructuredLogger:
    """Adapts a stdlib ``logging.Logger`` to the structlog-style kwargs API.

    Fields are rendered as ``key=value`` pairs appended to the event name, giving a
    readable, greppable, structured-ish line without pulling in any dependency.
    """

    __slots__ = ("_logger",)

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @staticmethod
    def _render(event: str, fields: dict[str, Any]) -> str:
        if not fields:
            return event
        rendered = " ".join(f"{key}={value!r}" for key, value in fields.items())
        return f"{event} {rendered}"

    def debug(self, event: str, **fields: Any) -> None:
        if self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(self._render(event, fields))

    def info(self, event: str, **fields: Any) -> None:
        if self._logger.isEnabledFor(logging.INFO):
            self._logger.info(self._render(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        if self._logger.isEnabledFor(logging.WARNING):
            self._logger.warning(self._render(event, fields))

    def error(self, event: str, **fields: Any) -> None:
        if self._logger.isEnabledFor(logging.ERROR):
            self._logger.error(self._render(event, fields))


def get_logger(name: str) -> StructuredLogger:
    """Return a structured logger bound to ``name``.

    Prefers ``structlog`` (to stay consistent with the server's JSON logs) and falls
    back to a stdlib adapter when structlog is unavailable. Never raises.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        An object exposing ``debug/info/warning/error(event, **fields)``.
    """
    try:  # pragma: no cover - exercised only when structlog is installed
        import structlog

        return structlog.get_logger(name)  # type: ignore[return-value]
    except Exception:
        return _StdlibStructuredLogger(logging.getLogger(name))
