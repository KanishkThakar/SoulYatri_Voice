"""Render a human-readable latency-budget report for the Duplex_Manager.

This module turns the design's *full-duplex latency targets* (Requirement 7)
into a human-readable Markdown report. Like the other renderers in this package
it is a **pure string function**: it performs no I/O, reads no files, and never
invokes a GPU / model-training run. It only states the already-defined targets
and (optionally) compares a single supplied measurement against them.

What the report contains (Requirements 7.1, 7.2, 7.3, 7.7)
----------------------------------------------------------
- **Latency targets (7.1, 7.2, 7.3).** The three p50 first-/perceived-response
  targets, each stated with its unit (``ms``) and comparison operator (``<=``):

  - practical first-response ``<= 300 ms`` p50 (Requirement 7.1),
  - stretch first-response ``<= 200 ms`` p50 (Requirement 7.2),
  - perceived ``<= 80 ms`` p50 (Requirement 7.3).

  The practical target is sourced from
  :attr:`~roadmap.duplex_manager.DuplexConfig.first_response_budget_ms` so the
  report and the Duplex_Manager's latency-fallback budget can never drift apart.
- **PASS/FAIL evaluation.** When a measured p50 is supplied, the report shows a
  ``PASS``/``FAIL`` verdict against the practical (``<= 300 ms``) and stretch
  (``<= 200 ms``) targets.
- **Mitigation options (7.7).** When the practical target is missed — or, when
  no measurement is supplied, listed unconditionally for reference — the report
  lists the mitigation options from the design: model quantization, a smaller
  Speech_Native_Core, and expanded filler coverage.

Requirements: 7.1, 7.2, 7.3, 7.7.
"""

from __future__ import annotations

from typing import Optional

from ..duplex_manager import DuplexConfig

__all__ = [
    "render_latency_report",
    "PRACTICAL_TARGET_MS",
    "STRETCH_TARGET_MS",
    "PERCEIVED_TARGET_MS",
]

#: Practical first-response latency target at p50 (Requirement 7.1). Sourced
#: from the Duplex_Manager's first-response budget so the report and the
#: latency-fallback budget cannot drift apart.
PRACTICAL_TARGET_MS: float = DuplexConfig().first_response_budget_ms

#: Stretch first-response latency target at p50 (Requirement 7.2).
STRETCH_TARGET_MS: float = 200.0

#: Perceived-latency target at p50 — end-of-user-speech to first audible output
#: of any kind, including a cached filler phrase (Requirement 7.3).
PERCEIVED_TARGET_MS: float = 80.0

#: Mitigation options to specify when the practical latency target is missed on
#: the defined target hardware profile (Requirement 7.7).
_MITIGATION_OPTIONS: tuple[str, ...] = (
    "Model quantization",
    "A smaller Speech_Native_Core",
    "Expanded filler coverage",
)


def render_latency_report(
    measured_p50_ms: Optional[float] = None,
    *,
    target_profile: str = "default",
) -> str:
    """Render a human-readable Markdown latency-budget report (Requirement 7).

    The renderer is pure: it states the already-defined latency targets and, when
    a measurement is supplied, compares it against them. It makes no
    decisions of its own beyond the stated ``<=`` target comparisons.

    Args:
        measured_p50_ms: An optional measured first-response latency at the 50th
            percentile, in milliseconds. When provided, the report adds a
            PASS/FAIL evaluation against the practical (``<= 300 ms``) and
            stretch (``<= 200 ms``) targets, and lists the mitigation options
            when the practical target is missed. When ``None`` (the default), the
            report renders just the targets and the mitigation options for
            reference.
        target_profile: A label for the target hardware profile the targets
            apply to (the latency targets are defined "on the Roadmap's defined
            target hardware profile"). Used only in the report header.

    Returns:
        A Markdown string. The report always contains the header and the
        targets table; it adds an evaluation section only when
        ``measured_p50_ms`` is supplied, and always closes with the mitigation
        options.
    """
    lines: list[str] = [
        f"# Latency Budget Report ({target_profile} hardware profile)",
        "",
    ]
    lines.extend(_render_targets())

    if measured_p50_ms is not None:
        lines.append("")
        lines.extend(_render_evaluation(measured_p50_ms))

    lines.append("")
    lines.extend(_render_mitigations(measured_p50_ms))

    return "\n".join(lines) + "\n"


# -- Section renderers -------------------------------------------------------


def _render_targets() -> list[str]:
    """Render the three p50 latency targets with unit (ms) and operator (<=).

    Covers the practical (7.1), stretch (7.2), and perceived (7.3) targets.
    """
    return [
        "## Latency Targets (p50)",
        "",
        "| Target | Operator | Threshold (ms) |",
        "| --- | --- | --- |",
        f"| Practical first-response | `<=` | {_format_number(PRACTICAL_TARGET_MS)} |",
        f"| Stretch first-response | `<=` | {_format_number(STRETCH_TARGET_MS)} |",
        f"| Perceived | `<=` | {_format_number(PERCEIVED_TARGET_MS)} |",
    ]


def _render_evaluation(measured_p50_ms: float) -> list[str]:
    """Render the PASS/FAIL evaluation against the practical and stretch targets.

    A target passes when ``measured_p50_ms <= target`` (Requirements 7.1, 7.2).
    """
    practical_passed = measured_p50_ms <= PRACTICAL_TARGET_MS
    stretch_passed = measured_p50_ms <= STRETCH_TARGET_MS
    return [
        "## Measured p50 Evaluation",
        "",
        f"- Measured p50 first-response: {_format_number(measured_p50_ms)} ms",
        "",
        "| Target | Operator | Threshold (ms) | Result |",
        "| --- | --- | --- | --- |",
        f"| Practical first-response | `<=` | {_format_number(PRACTICAL_TARGET_MS)} "
        f"| {_pass_fail(practical_passed)} |",
        f"| Stretch first-response | `<=` | {_format_number(STRETCH_TARGET_MS)} "
        f"| {_pass_fail(stretch_passed)} |",
    ]


def _render_mitigations(measured_p50_ms: Optional[float]) -> list[str]:
    """Render the mitigation options for a missed practical target (7.7).

    When a measurement is supplied and the practical target is missed, the
    section is framed as the mitigations to apply. When no measurement is
    supplied, the same options are listed for reference.
    """
    practical_missed = (
        measured_p50_ms is not None and measured_p50_ms > PRACTICAL_TARGET_MS
    )

    if measured_p50_ms is None:
        intro = (
            "If the practical target is not met on the defined target hardware "
            "profile, specify the following mitigation options:"
        )
    elif practical_missed:
        intro = (
            "The practical target was missed. Specify the following mitigation "
            "options:"
        )
    else:
        intro = (
            "The practical target was met. The following mitigation options "
            "apply if the practical target is missed on the defined target "
            "hardware profile:"
        )

    lines = ["## Mitigation Options", "", intro, ""]
    lines.extend(f"- {option}" for option in _MITIGATION_OPTIONS)
    return lines


# -- Value formatting --------------------------------------------------------


def _format_number(value: float) -> str:
    """Render a numeric value without trailing ``.0`` noise (e.g. ``300`` not ``300.0``)."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return str(value)
    return str(value)


def _pass_fail(passed: bool) -> str:
    """Render a boolean pass/fail as ``PASS`` / ``FAIL``."""
    return "PASS" if passed else "FAIL"
