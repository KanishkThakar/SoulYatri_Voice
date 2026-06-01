"""Structural tests for the package README (``roadmap/README.md``).

These are *structural/example* tests (plain ``pytest``) that keep the README
authored by Task 42.1 honest as the package evolves. Rather than hard-coding the
set of report modules and CLI subcommands, they **discover** both dynamically and
assert each discovered name appears literally in the README. That way the README
documentation stays in lock-step with the code: adding a report module or a CLI
subcommand without documenting it fails the suite (Requirement 12.7 — the sole
deliverable is a planning artifact, and the README is its entry point).

Discovery sources:

- Report modules: the ``.py`` files under ``roadmap/reports/`` (excluding
  ``__init__.py``), located via the ``roadmap.reports`` package directory so the
  check is independent of the pytest working directory.
- CLI subcommands: the subparser choices registered by
  ``roadmap.cli.build_parser()`` (introspected from the ``argparse``
  ``_SubParsersAction``), so the documented command table tracks the real parser.

The README itself is resolved via ``roadmap.paths.PACKAGE_ROOT`` rather than a
hard-coded absolute path, again so the tests run from any working directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import roadmap.reports as reports_pkg
from roadmap.cli import build_parser
from roadmap.paths import PACKAGE_ROOT

#: The README authored by Task 42.1, resolved relative to the package root.
README_PATH = PACKAGE_ROOT / "README.md"

#: The reports package directory, resolved from the package's own location so
#: discovery is robust to the test CWD.
REPORTS_DIR = Path(reports_pkg.__file__).resolve().parent


def _discover_report_modules() -> list[str]:
    """Return the report module names under ``roadmap/reports/``.

    Each name is a filename without its ``.py`` suffix, excluding the
    ``__init__`` package marker and any dunder/cache files. Discovery is
    dynamic so the test tracks the report set as modules are added or removed.
    """
    names = {
        path.stem
        for path in REPORTS_DIR.glob("*.py")
        if not path.stem.startswith("__")
    }
    return sorted(names)


def _discover_cli_subcommands() -> list[str]:
    """Return the CLI subcommand strings registered by ``build_parser()``.

    The subcommands are read from the ``argparse`` subparsers action's
    ``choices`` so the documented command table is verified against the real
    parser rather than a hand-maintained list.
    """
    parser = build_parser()
    subcommands: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subcommands.update(action.choices.keys())
    return sorted(subcommands)


def _read_readme() -> str:
    """Read the README text once (UTF-8)."""
    assert README_PATH.is_file(), (
        f"README not found at {README_PATH}; Task 42.1 must author it before "
        "this structural test can verify its contents."
    )
    return README_PATH.read_text(encoding="utf-8")


def test_readme_references_every_report_module() -> None:
    """The README must mention every report module under ``roadmap/reports/``."""
    readme = _read_readme()
    discovered = _discover_report_modules()

    # Sanity: discovery must find the report package's modules.
    assert discovered, (
        f"No report modules discovered under {REPORTS_DIR}; discovery is broken."
    )

    missing = [name for name in discovered if name not in readme]
    assert not missing, (
        "README does not reference these report modules discovered under "
        f"roadmap/reports/: {missing}. Discovered modules: {discovered}."
    )


def test_readme_references_every_cli_subcommand() -> None:
    """The README must mention every subcommand registered by ``build_parser()``."""
    readme = _read_readme()
    discovered = _discover_cli_subcommands()

    # Sanity: discovery must find the CLI's subcommands.
    assert discovered, (
        "No CLI subcommands discovered from build_parser(); discovery is broken."
    )

    missing = [name for name in discovered if name not in readme]
    assert not missing, (
        "README does not reference these CLI subcommands registered by "
        f"build_parser(): {missing}. Discovered subcommands: {discovered}."
    )


def test_readme_states_harness_is_mocked_no_gpu_training() -> None:
    """The README must lock in the mocked / no-GPU-training statement (Req 4.6).

    Kept deliberately tolerant: a case-insensitive search for the "mock" claim
    plus at least one phrasing of the no-GPU/no-training guarantee.
    """
    lowered = _read_readme().lower()

    assert "mock" in lowered, (
        "README must state the harness is mocked (case-insensitive 'mock')."
    )
    assert ("no gpu" in lowered) or ("gpu training" in lowered) or (
        "gpu model-training" in lowered
    ), (
        "README must state there is no GPU / model-training run "
        "(expected one of: 'no GPU', 'GPU training', 'GPU model-training')."
    )
