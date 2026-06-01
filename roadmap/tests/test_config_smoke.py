"""Configuration smoke tests for the roadmap test harness.

These are *structural/example* tests (plain ``pytest``) that guard two
project-wide invariants the rest of the suite relies on:

1. The Hypothesis default profile registered in ``conftest.py`` runs at least
   ``100`` examples, so every numbered correctness property gets the minimum
   example budget mandated by the design.

2. The roadmap package is **import-only** with respect to model execution: no
   module imports a GPU/training framework or invokes a GPU/model-training
   run. This encodes the design boundary that the Evaluation_Harness is fully
   mocked and out of scope for real training (Requirement 4.6).

The harness module (``roadmap/evaluation_harness.py``) is authored later in the
plan (Task 10.1). These tests therefore tolerate its absence today while still
asserting the design-level guarantee against every module that *does* exist,
so the same checks remain meaningful once the harness lands.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util

import pytest
from hypothesis import settings

from roadmap.paths import PACKAGE_ROOT
from roadmap.tests.conftest import HYPOTHESIS_PROFILE

# Minimum example count mandated by the design for every numbered property.
MIN_HYPOTHESIS_EXAMPLES = 100

# Top-level modules whose mere import implies GPU / model-training machinery.
# The roadmap tooling is pure-Python decision logic, so none of these belong in
# the package (Requirement 4.6: no GPU model-training run).
FORBIDDEN_IMPORTS = frozenset(
    {
        "torch",
        "tensorflow",
        "jax",
        "flax",
        "keras",
        "deepspeed",
        "accelerate",
        "vllm",
        "bitsandbytes",
    }
)

# Called attribute/function names that indicate an actual GPU placement or a
# training/inference run against real weights. Matched against *calls* (via AST)
# only, so prose in docstrings/comments never triggers a false positive.
FORBIDDEN_CALLS = frozenset(
    {
        "cuda",
        "train",
        "fit",
        "backward",
        "from_pretrained",
    }
)


def _roadmap_source_files() -> list:
    """Every ``.py`` source file in the roadmap package (excluding caches)."""
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imported_root_modules(tree: ast.AST) -> set:
    """Top-level module names imported anywhere in an AST."""
    roots: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Ignore relative imports (node.level > 0); they stay in-package.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _called_names(tree: ast.AST) -> set:
    """Names of functions/attributes that are *called* anywhere in an AST."""
    called: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            called.add(func.attr)
        elif isinstance(func, ast.Name):
            called.add(func.id)
    return called


# ---------------------------------------------------------------------------
# Hypothesis profile
# ---------------------------------------------------------------------------
def test_hypothesis_default_profile_runs_at_least_100_examples() -> None:
    """The loaded default profile must allow >= 100 examples per property.

    ``conftest.py`` registers and loads the ``roadmap`` profile, so the active
    default settings should reflect ``max_examples >= 100``.
    """
    assert HYPOTHESIS_PROFILE == "roadmap"
    assert settings().max_examples >= MIN_HYPOTHESIS_EXAMPLES, (
        "Hypothesis default profile must run at least "
        f"{MIN_HYPOTHESIS_EXAMPLES} examples; got {settings().max_examples}."
    )


# ---------------------------------------------------------------------------
# Import-only / no GPU-or-training guarantee (Requirement 4.6)
# ---------------------------------------------------------------------------
def test_roadmap_package_imports_no_gpu_or_training_frameworks() -> None:
    """No roadmap module may import a GPU/model-training framework."""
    offenders: dict = {}
    for path in _roadmap_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _imported_root_modules(tree) & FORBIDDEN_IMPORTS
        if bad:
            offenders[path.relative_to(PACKAGE_ROOT).as_posix()] = sorted(bad)
    assert not offenders, (
        "roadmap modules must not import GPU/training frameworks "
        f"(Requirement 4.6); offenders: {offenders}"
    )


def test_roadmap_package_invokes_no_gpu_or_training_run() -> None:
    """No roadmap module may call a GPU-placement or training/inference run."""
    offenders: dict = {}
    for path in _roadmap_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _called_names(tree) & FORBIDDEN_CALLS
        if bad:
            offenders[path.relative_to(PACKAGE_ROOT).as_posix()] = sorted(bad)
    assert not offenders, (
        "roadmap modules must not invoke a GPU/model-training run "
        f"(Requirement 4.6); offenders: {offenders}"
    )


def test_evaluation_harness_module_is_import_only_when_present() -> None:
    """The harness module, once it exists, must import without a GPU/training run.

    The harness is authored later (Task 10.1). Until then this is skipped so the
    suite stays green; afterwards it asserts the module imports cleanly (the
    no-GPU/no-training guarantee for its source is enforced by the AST checks
    above, which scan every package module including the harness).
    """
    harness_path = PACKAGE_ROOT / "evaluation_harness.py"
    if not harness_path.exists():
        pytest.skip(
            "roadmap/evaluation_harness.py not authored yet (Task 10.1); "
            "import-only guarantee is enforced for it once it exists."
        )

    # Importing must succeed and must not raise — i.e. it is import-only and
    # does not kick off a GPU/training run as a side effect.
    module = importlib.import_module("roadmap.evaluation_harness")
    assert module is not None
