"""
memory/_logging.py — Structured logging hooks for the memory subsystem.

Definition-of-done (final_use.md §3.3) requires *structured logging hooks*. The repo's
preferred logger is ``structlog`` (see ``server/utils/logging_config.py``), but the memory
subsystem must import cleanly on a bare CPU-only machine where ``structlog`` may not be
installed. So this helper binds to ``structlog`` if it is importable and otherwise degrades
to a thin stdlib-``logging`` shim that mimics structlog's key=value call style::

    log = get_logger("memory.redis.hot_cache")
    log.info("hot_cache_write", session_id="s1", kind="preference", backend="memory")

Either way callers get a ``.debug/.info/.warning/.error`` API that accepts a message plus
arbitrary keyword fields. No heavy dependencies are imported at module load.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["get_logger"]


class _StdlibStructShim:
    """Minimal structlog-style adapter over stdlib ``logging``.

    Renders ``log.info("event", a=1, b=2)`` as ``event a=1 b=2`` so structured fields stay
    greppable even without structlog installed.
    """

    __slots__ = ("_logger",)

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    @staticmethod
    def _render(event: str, fields: dict[str, Any]) -> str:
        if not fields:
            return event
        rendered = " ".join(f"{k}={v!r}" for k, v in fields.items())
        return f"{event} {rendered}"

    def debug(self, event: str, **fields: Any) -> None:
        self._logger.debug(self._render(event, fields))

    def info(self, event: str, **fields: Any) -> None:
        self._logger.info(self._render(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._logger.warning(self._render(event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self._logger.error(self._render(event, fields))

    # Common alias used across the codebase.
    warn = warning


def get_logger(name: str) -> Any:
    """Return a structured logger bound to ``name``.

    Prefers ``structlog`` (matching ``server/utils/logging_config.py``); falls back to a
    stdlib shim with the same key=value call style when structlog is unavailable.
    """
    try:  # pragma: no cover - exercised only when structlog is installed
        import structlog

        return structlog.get_logger(name)
    except Exception:
        return _StdlibStructShim(name)
