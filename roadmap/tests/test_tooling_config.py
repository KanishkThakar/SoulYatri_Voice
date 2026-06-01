"""Lint/type tooling configuration smoke tests for the roadmap package.

These are *structural/example* tests (plain ``pytest``) that guard the tooling
contract established in Task 43.1: the lint (ruff) and type-check (mypy) gates
must explicitly target the ``roadmap/`` planning package, and the package must
ship the PEP 561 ``py.typed`` marker so downstream type-checkers treat it as
typed. This keeps the sole deliverable — a typed planning artifact, not
executable model-training code — verifiable from configuration alone
(Requirement 12.7).

The pyproject.toml is located robustly via ``roadmap.paths.WORKSPACE_ROOT`` so
the assertions hold regardless of the working directory pytest is invoked from.

TOML parsing is resilient to this environment:
- Python 3.11+ ships ``tomllib`` in the stdlib.
- Python 3.10 (this environment) has no ``tomllib``; we fall back to ``tomli``.
- If neither parser is importable, we fall back to substring assertions over
  the raw pyproject.toml text so the test never errors on a missing parser.
"""

from __future__ import annotations

from typing import Any

from roadmap.paths import PACKAGE_ROOT, WORKSPACE_ROOT

# A TOML parser is preferred; fall back gracefully across environments.
try:  # Python 3.11+
    import tomllib as _toml  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter version
    try:  # Python 3.10 with the tomli backport
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover - no parser at all
        _toml = None  # type: ignore[assignment]

PYPROJECT_PATH = WORKSPACE_ROOT / "pyproject.toml"


def _load_pyproject() -> dict[str, Any] | None:
    """Parse pyproject.toml into a dict, or return ``None`` if no parser exists.

    When a parser is available we assert on the parsed structure; otherwise the
    caller falls back to substring assertions over the raw text.
    """
    if _toml is None:
        return None
    with PYPROJECT_PATH.open("rb") as handle:
        return _toml.load(handle)


def _raw_pyproject() -> str:
    """Raw pyproject.toml text for substring-based fallback assertions."""
    return PYPROJECT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sanity: the config file is locatable without hard-coded/CWD-relative paths.
# ---------------------------------------------------------------------------
def test_pyproject_is_locatable_via_workspace_root() -> None:
    """pyproject.toml must resolve relative to the exported WORKSPACE_ROOT."""
    assert PYPROJECT_PATH.is_file(), (
        f"pyproject.toml not found at {PYPROJECT_PATH}; it must resolve via "
        "roadmap.paths.WORKSPACE_ROOT regardless of the working directory."
    )


# ---------------------------------------------------------------------------
# Ruff lint gate targets roadmap/
# ---------------------------------------------------------------------------
def test_ruff_config_targets_roadmap() -> None:
    """The ruff configuration must explicitly reference the roadmap package.

    Tolerant to either signal, but requires at least one explicit ``roadmap``
    reference under ``[tool.ruff]``:
    - ``"roadmap"`` appears in ``[tool.ruff] src`` (first-party source root), OR
    - a ``roadmap``-scoped key exists under ``per-file-ignores``.
    """
    data = _load_pyproject()
    if data is not None:
        ruff = data.get("tool", {}).get("ruff", {})
        assert ruff, "[tool.ruff] section is missing from pyproject.toml."

        src = ruff.get("src", [])
        src_targets_roadmap = any("roadmap" in str(entry) for entry in src)

        per_file_ignores = ruff.get("lint", {}).get("per-file-ignores", {})
        ignores_target_roadmap = any(
            str(key).startswith("roadmap") for key in per_file_ignores
        )

        assert src_targets_roadmap or ignores_target_roadmap, (
            "[tool.ruff] must explicitly target roadmap/ via src "
            f"(got src={src!r}) or a roadmap-scoped per-file-ignores key "
            f"(got keys={list(per_file_ignores)!r})."
        )
    else:  # pragma: no cover - exercised only without a TOML parser
        raw = _raw_pyproject()
        assert "[tool.ruff]" in raw, "[tool.ruff] section missing from pyproject.toml."
        assert "roadmap" in raw.split("[tool.ruff]", 1)[1], (
            "[tool.ruff] configuration must reference roadmap/."
        )


# ---------------------------------------------------------------------------
# Mypy type-check gate targets roadmap/
# ---------------------------------------------------------------------------
def test_mypy_config_targets_roadmap() -> None:
    """The mypy configuration must explicitly reference the roadmap package.

    Requires at least one explicit ``roadmap`` reference under mypy config:
    - ``"roadmap"`` is in ``[tool.mypy] files``, OR
    - a ``[[tool.mypy.overrides]]`` block has a ``module`` starting ``roadmap``.
    """
    data = _load_pyproject()
    if data is not None:
        mypy = data.get("tool", {}).get("mypy", {})
        assert mypy, "[tool.mypy] section is missing from pyproject.toml."

        files = mypy.get("files", [])
        files_target_roadmap = any("roadmap" in str(entry) for entry in files)

        overrides = mypy.get("overrides", [])
        overrides_target_roadmap = any(
            str(block.get("module", "")).startswith("roadmap") for block in overrides
        )

        assert files_target_roadmap or overrides_target_roadmap, (
            "[tool.mypy] must explicitly target roadmap/ via files "
            f"(got files={files!r}) or a roadmap-scoped overrides module "
            f"(got modules={[b.get('module') for b in overrides]!r})."
        )
    else:  # pragma: no cover - exercised only without a TOML parser
        raw = _raw_pyproject()
        assert "[tool.mypy]" in raw, "[tool.mypy] section missing from pyproject.toml."
        mypy_section = raw.split("[tool.mypy]", 1)[1]
        assert "roadmap" in mypy_section, (
            "[tool.mypy] configuration must reference roadmap/."
        )


# ---------------------------------------------------------------------------
# PEP 561 typing marker is present and packaged
# ---------------------------------------------------------------------------
def test_roadmap_ships_py_typed_marker() -> None:
    """The roadmap package must contain the PEP 561 ``py.typed`` marker file."""
    py_typed = PACKAGE_ROOT / "py.typed"
    assert py_typed.is_file(), (
        f"PEP 561 marker not found at {py_typed}; the roadmap package must ship "
        "py.typed so consumers/type-checkers treat it as typed (Task 43.1)."
    )


def test_setuptools_package_data_ships_py_typed() -> None:
    """``[tool.setuptools.package-data]`` must ship py.typed for roadmap."""
    data = _load_pyproject()
    if data is not None:
        package_data = (
            data.get("tool", {}).get("setuptools", {}).get("package-data", {})
        )
        roadmap_data = package_data.get("roadmap", [])
        assert any("py.typed" in str(entry) for entry in roadmap_data), (
            "[tool.setuptools.package-data] must ship py.typed for the roadmap "
            f"package; got {roadmap_data!r}."
        )
    else:  # pragma: no cover - exercised only without a TOML parser
        raw = _raw_pyproject()
        assert "[tool.setuptools.package-data]" in raw, (
            "[tool.setuptools.package-data] section missing from pyproject.toml."
        )
        pkg_data_section = raw.split("[tool.setuptools.package-data]", 1)[1]
        assert "py.typed" in pkg_data_section, (
            "[tool.setuptools.package-data] must ship py.typed for roadmap."
        )
