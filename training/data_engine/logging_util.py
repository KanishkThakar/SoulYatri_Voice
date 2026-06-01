"""training/data_engine/logging_util.py — structured logging hooks for the data engine.

Definition of Done (final_use.md §3.3) requires *structured logging hooks*. The rest of
the repo standardizes on ``structlog`` (see ``server/utils/logging_config.py``), but the
training subsystem must import cleanly on a CPU-only machine that may not have the optional
``dev``/server dependencies installed. So this helper uses ``structlog`` when it is
available and transparently falls back to stdlib ``logging`` with a compact JSON-ish
renderer otherwise.

No GPU / torch / transformers imports here — this module is import-safe on CPU.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Protocol

__all__ = ["get_logger", "StructLogger"]


class StructLogger(Protocol):
    """Minimal structured-logger surface used across the training subsystem."""

    def info(self, event: str, **kw: Any) -> Any: ...
    def warning(self, event: str, **kw: Any) -> Any: ...
    def error(self, event: str, **kw: Any) -> Any: ...
    def debug(self, event: str, **kw: Any) -> Any: ...


class _StdlibStructLogger:
    """Tiny structlog-compatible shim over stdlib logging.

    Emits ``event`` plus key/value context as a single JSON object so logs stay
    machine-parseable even without structlog installed.
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)
        if not self._log.handlers and not logging.getLogger().handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._log.addHandler(handler)
            self._log.setLevel(logging.INFO)

    def _emit(self, level: int, event: str, **kw: Any) -> None:
        payload = {"event": event, **kw}
        try:
            rendered = json.dumps(payload, default=str, sort_keys=True)
        except (TypeError, ValueError):
            rendered = str(payload)
        self._log.log(level, rendered)

    def info(self, event: str, **kw: Any) -> None:
        self._emit(logging.INFO, event, **kw)

    def warning(self, event: str, **kw: Any) -> None:
        self._emit(logging.WARNING, event, **kw)

    def error(self, event: str, **kw: Any) -> None:
        self._emit(logging.ERROR, event, **kw)

    def debug(self, event: str, **kw: Any) -> None:
        self._emit(logging.DEBUG, event, **kw)


def get_logger(name: str) -> StructLogger:
    """Return a structured logger bound to ``name``.

    Prefers ``structlog`` (repo standard) and falls back to a stdlib-backed shim so the
    training scripts remain import- and run-safe on minimal CPU environments.
    """
    try:
        import structlog  # noqa: PLC0415  (optional dependency, imported lazily)

        return structlog.get_logger(name)
    except Exception:  # pragma: no cover - exercised only when structlog is absent
        return _StdlibStructLogger(name)
