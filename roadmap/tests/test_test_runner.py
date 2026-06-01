"""Meta-tests for the roadmap test-runner and pre-commit configuration.

These are plain ``pytest`` *structural/meta* tests (no Hypothesis) that guard
the developer-tooling artifacts authored in Task 44:

* ``scripts/run_roadmap_tests.ps1`` (Task 44.1) — a Windows PowerShell runner
  that executes the roadmap suite in a single (non-watch) run and propagates
  pytest's exit code to its callers / CI.
* ``roadmap/.pre-commit-config.yaml`` (Task 44.2) — a roadmap-scoped pre-commit
  config wiring ruff / ruff-format / mypy and a local ``roadmap-pytest`` hook.

The intent (Requirement 4.6) is to keep the roadmap tooling self-contained and
CPU-only: the runner and the pre-commit hooks must point at ``roadmap/tests``
and the Hypothesis ``roadmap`` profile, and must never trigger a GPU / model-
training run.

Assertions are deliberately *robust* — substring checks against the raw text
and parsed-structure checks against the YAML — rather than brittle exact-line
matches, so cosmetic edits to the artifacts do not break the meta-test.
"""

from __future__ import annotations

import yaml

from roadmap.paths import PACKAGE_ROOT, WORKSPACE_ROOT

# Resolve both artifacts via roadmap.paths so the test is CWD-independent.
RUNNER_SCRIPT_PATH = WORKSPACE_ROOT / "scripts" / "run_roadmap_tests.ps1"
PRECOMMIT_CONFIG_PATH = PACKAGE_ROOT / ".pre-commit-config.yaml"


# ---------------------------------------------------------------------------
# Runner script (Task 44.1)
# ---------------------------------------------------------------------------
def test_runner_script_exists() -> None:
    """The local PowerShell test-runner must exist at scripts/."""
    assert RUNNER_SCRIPT_PATH.is_file(), (
        f"Expected runner script at {RUNNER_SCRIPT_PATH}; it was not found. "
        "Task 44.1 should author scripts/run_roadmap_tests.ps1."
    )


def test_runner_script_targets_roadmap_tests_with_hypothesis_profile() -> None:
    """The runner must invoke pytest over the roadmap suite with the profile."""
    text = RUNNER_SCRIPT_PATH.read_text(encoding="utf-8")

    # Runs pytest against the roadmap test target.
    assert "python -m pytest roadmap" in text, (
        "Runner must invoke 'python -m pytest roadmap' over the roadmap suite."
    )
    # Uses the registered Hypothesis 'roadmap' profile (>=100 examples).
    assert "--hypothesis-profile roadmap" in text, (
        "Runner must select the Hypothesis 'roadmap' profile via "
        "'--hypothesis-profile roadmap'."
    )


def test_runner_script_propagates_pytest_exit_code() -> None:
    """The runner must capture and propagate pytest's exit code."""
    text = RUNNER_SCRIPT_PATH.read_text(encoding="utf-8")

    # Captures pytest's exit status...
    assert "$LASTEXITCODE" in text, (
        "Runner must read '$LASTEXITCODE' to capture pytest's exit status."
    )
    # ...and re-exits with it so CI / callers can detect failure.
    assert "exit" in text, (
        "Runner must 'exit' with the captured code to propagate failure."
    )


# ---------------------------------------------------------------------------
# Pre-commit config (Task 44.2)
# ---------------------------------------------------------------------------
def test_precommit_config_exists() -> None:
    """The roadmap-scoped pre-commit config must exist in the package root."""
    assert PRECOMMIT_CONFIG_PATH.is_file(), (
        f"Expected pre-commit config at {PRECOMMIT_CONFIG_PATH}; not found. "
        "Task 44.2 should author roadmap/.pre-commit-config.yaml."
    )


def test_precommit_config_is_valid_yaml_with_repos_list() -> None:
    """The config must parse as YAML and expose a top-level 'repos' list."""
    parsed = yaml.safe_load(PRECOMMIT_CONFIG_PATH.read_text(encoding="utf-8"))

    assert isinstance(parsed, dict), (
        "Pre-commit config must parse to a YAML mapping at the top level."
    )
    assert "repos" in parsed, "Pre-commit config must declare a 'repos' key."
    assert isinstance(parsed["repos"], list) and parsed["repos"], (
        "'repos' must be a non-empty list of hook repositories."
    )


def test_precommit_config_runs_roadmap_pytest_with_profile() -> None:
    """The config must wire the roadmap pytest hook and Hypothesis profile."""
    text = PRECOMMIT_CONFIG_PATH.read_text(encoding="utf-8")

    # Scoped to the roadmap package and exercising its test suite.
    assert "roadmap" in text, "Pre-commit config must reference 'roadmap'."
    assert "pytest" in text, "Pre-commit config must wire a 'pytest' hook."

    # The local hook id and the test target / Hypothesis profile it runs.
    assert "roadmap-pytest" in text, (
        "Pre-commit config must define the 'roadmap-pytest' local hook id."
    )
    assert "python -m pytest roadmap/tests" in text, (
        "The roadmap-pytest hook must run 'python -m pytest roadmap/tests'."
    )
    assert "--hypothesis-profile roadmap" in text, (
        "The roadmap-pytest hook must select the Hypothesis 'roadmap' profile."
    )
