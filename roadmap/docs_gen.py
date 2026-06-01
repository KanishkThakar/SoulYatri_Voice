"""Docstring / API-reference generator for the roadmap tooling package.

This module introspects the *public* API of the :mod:`roadmap` package (its
``__all__`` exports, defaulting to ``roadmap.__all__``) and renders clean
Markdown API-reference documentation directly from the live signatures and
docstrings. It is **pure string generation** — none of the ``generate_*``
helpers touch the filesystem, so tests can assert on the produced Markdown.
A separate :func:`write_api_reference` helper performs the only file write.

Scope (Requirements 12.3, 12.7)
-------------------------------
The generated reference documents *only* this package's own decision-logic
API (classes, functions, and minimally-rendered constants). It deliberately
does **not** restate or duplicate the ``.kiro/specs/ai-training-docs/``
knowledge base, which is a separate documentation/knowledge-base workstream.

Implementation notes
--------------------
The generator uses only the Python standard library (``inspect``,
``importlib``, ``textwrap``). It performs no GPU placement and no
model-training/inference run, so it preserves the import-only / no-training
guarantee enforced by ``test_config_smoke.py`` (Requirement 4.6).

Public functions
----------------
- :func:`document_object` — render one Markdown section for a class or
  function (or a minimal section for a constant).
- :func:`generate_api_reference` — render the full Markdown API reference for
  a list of public members (defaults to ``roadmap.__all__``) as a single
  string.
- :func:`generate_component_pages` — render one Markdown page per component
  module, returned as a ``{component: markdown}`` mapping.
- :func:`write_api_reference` — write the full reference to a file (the only
  filesystem-touching helper).
"""

from __future__ import annotations

import importlib
import inspect
import textwrap
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "document_object",
    "generate_api_reference",
    "generate_component_pages",
    "write_api_reference",
    "DEFAULT_PACKAGE",
]

# The package whose public API this generator documents by default.
DEFAULT_PACKAGE = "roadmap"

# Maximum characters of a constant's ``repr`` rendered inline before truncation.
_MAX_CONSTANT_REPR = 200


# ---------------------------------------------------------------------------
# Low-level rendering helpers (pure, no I/O)
# ---------------------------------------------------------------------------
def _docstring(obj: Any) -> str:
    """Return a cleaned docstring for *obj*, or a placeholder when absent.

    Uses :func:`inspect.getdoc` so inherited docstrings are resolved and common
    leading indentation is stripped. Never raises on a missing docstring.
    """
    doc = inspect.getdoc(obj)
    if doc and doc.strip():
        return doc.strip()
    return "_No description provided._"


def _signature_str(obj: Any) -> str:
    """Best-effort ``str`` of *obj*'s call signature.

    Falls back to ``"(...)"`` for objects whose signature cannot be introspected
    (some C-level builtins), so the generator never crashes on an exotic member.
    """
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return "(...)"


def _code_fence(text: str) -> str:
    """Wrap *text* in a Python-tagged Markdown code fence."""
    return f"```python\n{text}\n```"


def _public_class_members(cls: type) -> list[tuple[str, Any, str]]:
    """Return ``(name, attribute, kind)`` triples for a class's public members.

    Iterates the class's own ``__dict__`` (definition order, which is stable in
    Python 3.7+) so inherited ``object`` members are not documented. ``kind`` is
    one of ``"method"`` or ``"property"``. Names beginning with an underscore
    are skipped, except ``__init__`` is intentionally omitted because the class
    heading already renders the constructor signature.
    """
    members: list[tuple[str, Any, str]] = []
    for name, raw in vars(cls).items():
        if name.startswith("_"):
            continue
        if isinstance(raw, property):
            members.append((name, raw, "property"))
            continue
        # ``getattr`` unwraps staticmethod/classmethod descriptors into the
        # underlying callable so ``inspect.signature`` works uniformly.
        attr = getattr(cls, name, None)
        if inspect.isroutine(attr):
            members.append((name, attr, "method"))
    return members


def _render_class(cls: type, *, level: int = 2) -> str:
    """Render a Markdown section for a class: name, signature, docstring, methods."""
    hashes = "#" * level
    sub_hashes = "#" * (level + 1)
    lines: list[str] = [f"{hashes} class `{cls.__name__}`", ""]

    constructor_sig = _signature_str(cls)
    lines.append(_code_fence(f"{cls.__name__}{constructor_sig}"))
    lines.append("")
    lines.append(_docstring(cls))
    lines.append("")

    public_members = _public_class_members(cls)
    if public_members:
        lines.append(f"{sub_hashes} Methods")
        lines.append("")
        for name, attr, kind in public_members:
            if kind == "property":
                lines.append(f"{'#' * (level + 2)} `{name}` _(property)_")
                lines.append("")
                lines.append(_docstring(attr.fget) if attr.fget else "_No description provided._")
                lines.append("")
            else:
                sig = _signature_str(attr)
                lines.append(f"{'#' * (level + 2)} `{name}`")
                lines.append("")
                lines.append(_code_fence(f"{name}{sig}"))
                lines.append("")
                lines.append(_docstring(attr))
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_function(func: Any, *, level: int = 2) -> str:
    """Render a Markdown section for a module-level function."""
    hashes = "#" * level
    name = getattr(func, "__name__", "function")
    sig = _signature_str(func)
    lines = [
        f"{hashes} `{name}`",
        "",
        _code_fence(f"{name}{sig}"),
        "",
        _docstring(func),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_constant(name: str, value: Any, *, level: int = 2) -> str:
    """Render a minimal Markdown section for a module-level constant."""
    hashes = "#" * level
    type_name = type(value).__name__
    rendered = repr(value)
    if len(rendered) > _MAX_CONSTANT_REPR:
        rendered = rendered[:_MAX_CONSTANT_REPR] + "…"
    lines = [
        f"{hashes} `{name}`",
        "",
        f"_Constant_ of type `{type_name}`.",
        "",
        _code_fence(rendered),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def document_object(obj: Any, *, name: Optional[str] = None, level: int = 2) -> str:
    """Render a Markdown section documenting a single object.

    Dispatches on the kind of *obj*:

    - **class** → name, constructor signature, docstring, and a sub-section
      documenting each public method (with signature + docstring) and property.
    - **function** → name, signature, and docstring.
    - **anything else** (module-level constant) → a minimal section showing the
      constant's type and a truncated ``repr`` of its value.

    The render never crashes on a missing docstring or an un-introspectable
    signature.

    Args:
        obj: The class, function, or constant to document.
        name: Optional display name, required only for constants (which carry no
            ``__name__``). Ignored for classes and functions.
        level: The Markdown heading level (number of ``#``) for the section's
            top heading. Defaults to ``2`` (``##``).

    Returns:
        A Markdown string for the section, terminated by a single newline.
    """
    if inspect.isclass(obj):
        return _render_class(obj, level=level)
    if inspect.isroutine(obj):
        return _render_function(obj, level=level)
    display = name or getattr(obj, "__name__", repr(obj))
    return _render_constant(display, obj, level=level)


def _resolve_members(
    package: str, members: Optional[list[str]]
) -> list[tuple[str, Any]]:
    """Import *package* and resolve member names to ``(name, object)`` pairs.

    Defaults to the package's ``__all__`` when *members* is ``None``. Names that
    cannot be resolved on the package are skipped rather than raising.
    """
    module = importlib.import_module(package)
    names = members if members is not None else list(getattr(module, "__all__", []))
    resolved: list[tuple[str, Any]] = []
    for member_name in names:
        if hasattr(module, member_name):
            resolved.append((member_name, getattr(module, member_name)))
    return resolved


def generate_api_reference(
    *, package: str = DEFAULT_PACKAGE, members: Optional[list[str]] = None
) -> str:
    """Render the full Markdown API reference for a package's public members.

    Introspects each public member (defaulting to ``<package>.__all__``) and
    renders a single Markdown document with a title, a short scope note, and one
    section per member produced by :func:`document_object`. Members are rendered
    in the order they appear in ``members`` (or ``__all__``).

    This function is pure: it performs no filesystem writes, so tests can assert
    directly on the returned string. Use :func:`write_api_reference` to persist
    the output.

    Args:
        package: The importable package name to document. Defaults to
            :data:`DEFAULT_PACKAGE` (``"roadmap"``).
        members: Optional explicit list of public member names to document. When
            ``None`` the package's ``__all__`` is used.

    Returns:
        The complete Markdown API reference as a single string.
    """
    resolved = _resolve_members(package, members)
    lines = [
        f"# `{package}` API Reference",
        "",
        (
            f"Auto-generated API reference for the public API of the "
            f"`{package}` tooling package. Generated from live signatures and "
            "docstrings; do not edit by hand."
        ),
        "",
    ]
    for name, obj in resolved:
        lines.append(document_object(obj, name=name, level=2))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _short_component_name(module_name: str, package: str) -> str:
    """Return a friendly component key for *module_name* relative to *package*.

    ``"roadmap.gate_evaluator"`` → ``"gate_evaluator"`` and
    ``"roadmap.models.phases"`` → ``"models.phases"``; a module outside the
    package keeps its full dotted name.
    """
    prefix = package + "."
    if module_name.startswith(prefix):
        return module_name[len(prefix):]
    return module_name


def generate_component_pages(
    package: str = DEFAULT_PACKAGE, *, members: Optional[list[str]] = None
) -> dict[str, str]:
    """Render one Markdown page per component module of *package*.

    Groups the package's public classes and functions (defaulting to
    ``<package>.__all__``) by their defining module (``obj.__module__``) and
    renders one Markdown page per module. Each page lists the documented members
    that belong to that component. Constants (which have no ``__module__``) are
    not assigned a page.

    The result is keyed by a friendly component name (e.g. ``"gate_evaluator"``,
    ``"models.phases"``). This is the per-component view the documentation pages
    (Task 40.2) and the docs-generator tests (Task 40.3) build on. It is pure:
    no filesystem writes occur.

    Args:
        package: The importable package name to document. Defaults to
            :data:`DEFAULT_PACKAGE` (``"roadmap"``).
        members: Optional explicit list of public member names to document. When
            ``None`` the package's ``__all__`` is used.

    Returns:
        A mapping of ``component_name -> markdown_page``.
    """
    resolved = _resolve_members(package, members)

    grouped: dict[str, list[tuple[str, Any]]] = {}
    for name, obj in resolved:
        if not (inspect.isclass(obj) or inspect.isroutine(obj)):
            # Skip module-level constants for the per-component page view.
            continue
        module_name = getattr(obj, "__module__", None)
        if not module_name:
            continue
        component = _short_component_name(module_name, package)
        grouped.setdefault(component, []).append((name, obj))

    pages: dict[str, str] = {}
    for component in sorted(grouped):
        sections = [
            f"# `{package}.{component}`",
            "",
            (
                f"Public API of the `{package}.{component}` component. "
                "Generated from live signatures and docstrings."
            ),
            "",
        ]
        for name, obj in grouped[component]:
            sections.append(document_object(obj, name=name, level=2))
            sections.append("")
        pages[component] = "\n".join(sections).rstrip() + "\n"

    return pages


def write_api_reference(
    path: str | Path,
    *,
    package: str = DEFAULT_PACKAGE,
    members: Optional[list[str]] = None,
) -> None:
    """Write the full Markdown API reference to *path*.

    This is the only helper in this module that touches the filesystem. The
    parent directory is created if it does not already exist. The reference
    content is produced by :func:`generate_api_reference`.

    Args:
        path: Destination file path for the generated Markdown.
        package: The package to document. Defaults to :data:`DEFAULT_PACKAGE`.
        members: Optional explicit list of member names; defaults to
            ``<package>.__all__``.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = generate_api_reference(package=package, members=members)
    destination.write_text(content, encoding="utf-8")
