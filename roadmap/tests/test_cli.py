"""Smoke tests for the roadmap command-line interface (``roadmap/cli.py``).

These are *structural/example* tests (plain ``pytest``) that guard the CLI's
shipping guarantees from Task 41.1:

1. Every subcommand runs on built-in fixture/default data, requires no
   arguments, exits ``0``, and produces output. ``main(...)`` is driven
   in-process (stdout captured via ``capsys``) so the checks are fast and
   deterministic; the CLI already reconfigures stdout to UTF-8 defensively so
   the non-ASCII report glyphs always encode (Requirement 12.7: the sole
   deliverable is a planning artifact, exercisable from the shell).

2. The parser registers exactly the seven documented subcommands — a guard
   against silently adding/removing a command.

3. The CLI module is **import-only** with respect to model execution: its
   source imports no GPU/training framework and invokes no GPU/model-training
   run, mirroring ``test_config_smoke.py`` but scoped to ``cli.py``
   (Requirement 4.6: the harness runs mocked, with no GPU model-training run).

The forbidden import/call sets and the AST scan helpers are reused from
``test_config_smoke`` so the CLI's guard stays in lock-step with the
package-wide invariant.
"""

from __future__ import annotations

import argparse
import ast

import pytest

from roadmap import cli
from roadmap.paths import PACKAGE_ROOT
from roadmap.tests.test_config_smoke import (
    FORBIDDEN_CALLS,
    FORBIDDEN_IMPORTS,
    _called_names,
    _imported_root_modules,
)

#: Every subcommand the CLI is documented to expose (Task 41.1). Each must run
#: with no arguments on built-in fixture/default data.
EXPECTED_SUBCOMMANDS = frozenset(
    {
        "validate",
        "select",
        "gate-report",
        "eval-report",
        "trace",
        "coverage",
        "render-roadmap",
    }
)

#: Path to the CLI module under test, resolved independently of the pytest CWD.
CLI_SOURCE_PATH = PACKAGE_ROOT / "cli.py"


def _registered_subcommands(parser: argparse.ArgumentParser) -> set:
    """Return the set of subcommand names registered on ``parser``."""
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices.keys())
    return set()


# ---------------------------------------------------------------------------
# Each subcommand runs on fixture data, exits zero, and prints output
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("subcommand", sorted(EXPECTED_SUBCOMMANDS))
def test_subcommand_exits_zero_and_prints_output(
    subcommand: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main([subcommand])`` returns ``0`` and writes non-empty stdout.

    Run in-process so the smoke test is fast/deterministic and so the captured
    output can be asserted directly.
    """
    exit_code = cli.main([subcommand])
    captured = capsys.readouterr()

    assert exit_code == 0, (
        f"`roadmap {subcommand}` exited {exit_code} (expected 0); "
        f"stderr: {captured.err!r}"
    )
    assert captured.out.strip(), (
        f"`roadmap {subcommand}` produced no stdout; it should print its "
        "result/report when run on built-in fixture data."
    )


def test_validate_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    """``validate`` confirms the roadmap loads and validates (prints ``OK``)."""
    assert cli.main(["validate"]) == 0
    assert "OK" in capsys.readouterr().out


def test_select_prints_a_selection(capsys: pytest.CaptureFixture[str]) -> None:
    """``select`` prints the selection produced by the mocked pipeline."""
    assert cli.main(["select"]) == 0
    out = capsys.readouterr().out
    assert "select:" in out
    assert "selected:" in out


def test_gate_report_renders_a_gate(capsys: pytest.CaptureFixture[str]) -> None:
    """``gate-report`` renders a gate report for the default gate."""
    assert cli.main(["gate-report"]) == 0
    assert capsys.readouterr().out.strip()


# ---------------------------------------------------------------------------
# The parser registers exactly the seven documented subcommands
# ---------------------------------------------------------------------------
def test_build_parser_registers_exactly_the_expected_subcommands() -> None:
    """``build_parser()`` exposes exactly the seven documented subcommands."""
    parser = cli.build_parser()
    registered = _registered_subcommands(parser)
    assert registered == set(EXPECTED_SUBCOMMANDS), (
        "CLI must register exactly the documented subcommands; "
        f"got {sorted(registered)}, expected {sorted(EXPECTED_SUBCOMMANDS)}."
    )


def test_cli_exports_main_and_build_parser() -> None:
    """The CLI module exports its public entry points via ``__all__``."""
    assert set(cli.__all__) == {"main", "build_parser"}
    assert callable(cli.main)
    assert callable(cli.build_parser)


# ---------------------------------------------------------------------------
# The CLI never imports a GPU/training framework or invokes a GPU/training run
# ---------------------------------------------------------------------------
def _cli_ast() -> ast.AST:
    """Parse the CLI module source into an AST (independent of the test CWD)."""
    source = CLI_SOURCE_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(CLI_SOURCE_PATH))


def test_cli_imports_no_gpu_or_training_frameworks() -> None:
    """``cli.py`` must import none of the forbidden GPU/training frameworks."""
    offending = _imported_root_modules(_cli_ast()) & FORBIDDEN_IMPORTS
    assert not offending, (
        "roadmap/cli.py must not import GPU/training frameworks "
        f"(Requirement 4.6); offenders: {sorted(offending)}"
    )


def test_cli_invokes_no_gpu_or_training_run() -> None:
    """``cli.py`` must call none of the forbidden GPU/training run names."""
    offending = _called_names(_cli_ast()) & FORBIDDEN_CALLS
    assert not offending, (
        "roadmap/cli.py must not invoke a GPU/model-training run "
        f"(Requirement 4.6); offenders: {sorted(offending)}"
    )
