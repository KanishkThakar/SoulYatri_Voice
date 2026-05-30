"""
speech/codec/_compat.py — cross-subsystem compatibility shims for the speech package.
=====================================================================================

This module is the single place where ``speech/`` reaches *outside* its own folder, so
the rest of the speech code stays clean and import-safe on a CPU-only machine with no
model weights (DECISIONS.md D-008).

It provides two things:

1. ``get_logger(name)`` — a structured logger. We prefer the project logger
   (``server.utils.logging_config.get_logger``, which is structlog-backed). That module
   pulls in ``structlog`` / ``pydantic-settings`` which may be absent in a minimal CPU
   env, so we guard the import and fall back to a tiny stdlib shim that supports the same
   ``log.info("event", key=value)`` + ``log.bind(**ctx)`` calling convention.

2. ``CodecBridge`` — the Phase-5 protocol from ``docs/INTERFACES.md`` §5.2. We try to
   import it from ``shared.contracts`` first (so if it is ever promoted into the shared
   contract we use that definition verbatim). If it is not exported there yet, we define a
   structurally-identical ``Protocol`` locally. Implementations only need to be
   *structurally* compatible, so this never conflicts with the shared contract.

Nothing here imports torch / moshi / mimi at module top level.

Owner: speech/runtime agent. Other speech subpackages (``decoder``, ``moshi_runtime``)
import these helpers from here on purpose — ``codec`` is the most foundational speech
package (decoder decodes *via* the codec bridge; the runtime emits codec chunks), so the
dependency direction is acyclic and intentional.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from shared.contracts import AudioFrame, CodecChunk

__all__ = ["get_logger", "CodecBridge", "AudioFrame", "CodecChunk"]


# ---------------------------------------------------------------------------
# Logging — prefer the project structlog logger, fall back to a stdlib shim.
# ---------------------------------------------------------------------------
class _StdlibStructShim:
    """Minimal structlog-compatible adapter over a stdlib ``logging.Logger``.

    Supports ``log.info("event", key=value)`` and ``log.bind(**ctx)`` so call sites do
    not need to know whether structlog is installed.
    """

    __slots__ = ("_logger", "_context")

    def __init__(self, logger: logging.Logger, context: dict[str, Any] | None = None) -> None:
        self._logger = logger
        self._context = dict(context or {})

    def bind(self, **kwargs: Any) -> _StdlibStructShim:
        merged = dict(self._context)
        merged.update(kwargs)
        return _StdlibStructShim(self._logger, merged)

    def _emit(self, level: int, event: str, **kwargs: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        fields = dict(self._context)
        fields.update(kwargs)
        if fields:
            rendered = " ".join(f"{k}={v!r}" for k, v in fields.items())
            self._logger.log(level, "%s | %s", event, rendered)
        else:
            self._logger.log(level, "%s", event)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit(logging.ERROR, event, **kwargs)

    def exception(self, event: str, **kwargs: Any) -> None:
        fields = dict(self._context)
        fields.update(kwargs)
        if fields:
            rendered = " ".join(f"{k}={v!r}" for k, v in fields.items())
            self._logger.exception("%s | %s", event, rendered)
        else:
            self._logger.exception("%s", event)


try:  # pragma: no cover - exercised indirectly; depends on optional deps being present
    from server.utils.logging_config import get_logger as _server_get_logger

    _HAVE_PROJECT_LOGGER = True
except Exception:  # noqa: BLE001 - any failure (missing structlog/pydantic-settings) -> shim
    _server_get_logger = None
    _HAVE_PROJECT_LOGGER = False


def get_logger(name: str) -> Any:
    """Return a structured logger, preferring the project logger when importable.

    Falls back to a stdlib-backed shim with the same ``.info(event, **fields)`` /
    ``.bind(**ctx)`` API so speech code never has to branch on logging availability.
    """
    if _HAVE_PROJECT_LOGGER and _server_get_logger is not None:
        return _server_get_logger(name)
    return _StdlibStructShim(logging.getLogger(name))


# ---------------------------------------------------------------------------
# CodecBridge protocol — import from shared.contracts if present, else define.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - shared.contracts does not export it today
    from shared.contracts import CodecBridge  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001

    @runtime_checkable
    class CodecBridge(Protocol):  # type: ignore[no-redef]
        """Mimi encode/decode roundtrip behind a stable interface (INTERFACES.md §5.2).

        SNAC/DAC may sit behind the same interface. ``encode``/``decode`` accept and
        return *iterables* so they compose with streaming token pipelines.
        """

        def encode(self, frames: Iterable[AudioFrame]) -> Iterable[CodecChunk]: ...

        def decode(self, chunks: Iterable[CodecChunk]) -> Iterable[AudioFrame]: ...
