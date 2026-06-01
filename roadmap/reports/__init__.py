"""Human-readable report renderers for the speech-native voice roadmap.

This package holds the *presentation* layer of the roadmap tooling: pure
functions that turn the roadmap's planning objects and decision-logic outputs
(``GateResult``, ``HarnessRun`` records, the conflict/licensing registers, …)
into human-readable Markdown / plain-text reports.

Every renderer here is a **pure string function** — it performs no I/O, reads no
files, and never invokes a GPU/model-training run. Renderers only read the
already-computed planning objects defined in :mod:`roadmap.models` and the
decision-logic components in :mod:`roadmap`, so this package preserves the
import-only / no-training guarantee enforced across the roadmap tooling
(Requirement 4.6).

Public API
----------
- :func:`render_gate_report` — render a launch/decision-gate report from a
  :class:`~roadmap.models.selection.GateResult` (Requirements 1.4, 1.5, 8.4,
  8.5, 11.5, 11.7).
"""

from __future__ import annotations

from .gate_report import render_gate_report

__all__ = [
    "render_gate_report",
]
