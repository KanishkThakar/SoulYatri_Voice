"""Shared test helpers for aux/tests.

We deliberately drive coroutines with ``asyncio.run`` (via :func:`run_async`)
instead of relying on a specific pytest-asyncio mode/config, so these tests are
robust regardless of repo-level pytest settings.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)
