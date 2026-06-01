"""Tests for the roadmap API-reference / docs generator (``roadmap.docs_gen``).

These are plain ``pytest`` example tests (Task 40.3, Requirement 12.3). They
verify that:

- :func:`generate_api_reference` produces a non-empty Markdown string that
  documents the package's known public members.
- :func:`document_object` renders a single class section with the class name
  and at least one of its public methods.
- :func:`generate_component_pages` returns one non-empty Markdown page per
  component, keyed by the friendly component name, each containing the
  component's class name (its documented interface).
- The *committed* documentation pages under ``roadmap/docs/`` exist, are
  non-empty, and contain the documented interface of their component.
- :func:`write_api_reference` writes a non-empty reference file to a caller
  supplied path (a pytest ``tmp_path``), without disturbing the committed docs.

Determinism caveat (from Task 40.2): the generator's output for a class whose
constructor carries a ``frozenset`` default argument (e.g.
``EmotionPersonaController.distress_labels``) is non-deterministic across
processes because of Python's string-hash randomization of ``frozenset`` repr
ordering. These tests therefore use "contains expected section" assertions and
deliberately never compare a freshly generated page byte-for-byte against the
committed file.

Paths are resolved via :data:`roadmap.paths.PACKAGE_ROOT` so the suite is
independent of the working directory pytest is invoked from.
"""

from __future__ import annotations

from pathlib import Path

from roadmap import GateEvaluator
from roadmap.docs_gen import (
    DEFAULT_PACKAGE,
    document_object,
    generate_api_reference,
    generate_component_pages,
    write_api_reference,
)
from roadmap.paths import PACKAGE_ROOT

#: Directory holding the committed, authored documentation pages (Task 40.2).
DOCS_DIR = PACKAGE_ROOT / "docs"

#: A few public members that must appear in the full API reference.
EXPECTED_REFERENCE_MEMBERS = (
    "GateEvaluator",
    "SelectionScorer",
    "evaluate_and_select",
    "Roadmap",
    "HinglishDataEngine",
)

#: Main components that must each get a generated per-component page, mapped to
#: the class name whose documented interface the page must contain.
EXPECTED_COMPONENT_CLASSES = {
    "gate_evaluator": "GateEvaluator",
    "selection_scorer": "SelectionScorer",
    "evaluation_harness": "EvaluationHarness",
    "safety_guard": "SafetyGuard",
}


# ---------------------------------------------------------------------------
# generate_api_reference
# ---------------------------------------------------------------------------
def test_generate_api_reference_is_non_empty_markdown() -> None:
    """The full reference is a non-empty string with a Markdown heading."""
    reference = generate_api_reference()

    assert isinstance(reference, str)
    assert reference.strip(), "API reference must not be empty."
    # Titled with the documented package name.
    assert f"`{DEFAULT_PACKAGE}` API Reference" in reference


def test_generate_api_reference_documents_known_public_members() -> None:
    """The reference mentions known public classes and functions by name."""
    reference = generate_api_reference()

    for member in EXPECTED_REFERENCE_MEMBERS:
        assert member in reference, (
            f"Expected public member {member!r} to be documented in the "
            "generated API reference."
        )


# ---------------------------------------------------------------------------
# document_object
# ---------------------------------------------------------------------------
def test_document_object_renders_class_with_method() -> None:
    """Documenting a class yields its name and at least one public method."""
    section = document_object(GateEvaluator)

    assert isinstance(section, str)
    assert "GateEvaluator" in section
    # ``evaluate`` is a public method of GateEvaluator and must be rendered.
    assert "evaluate" in section
    # The constructor signature is rendered inside a python code fence.
    assert "```python" in section


# ---------------------------------------------------------------------------
# generate_component_pages
# ---------------------------------------------------------------------------
def test_generate_component_pages_returns_pages_for_main_components() -> None:
    """Each main component gets a non-empty page containing its class name."""
    pages = generate_component_pages()

    assert isinstance(pages, dict)
    assert pages, "Expected at least one generated component page."

    for component, class_name in EXPECTED_COMPONENT_CLASSES.items():
        assert component in pages, (
            f"Expected a generated page for component {component!r}; "
            f"got keys {sorted(pages)}."
        )
        page = pages[component]
        assert page.strip(), f"Generated page for {component!r} must not be empty."
        assert class_name in page, (
            f"Generated page for {component!r} must document its interface "
            f"(expected class name {class_name!r})."
        )


# ---------------------------------------------------------------------------
# Committed documentation pages (Task 40.2 output)
# ---------------------------------------------------------------------------
def test_committed_index_and_api_reference_exist_and_non_empty() -> None:
    """The authored index and api_reference pages exist and are non-empty."""
    index_md = DOCS_DIR / "index.md"
    api_reference_md = DOCS_DIR / "api_reference.md"

    for path in (index_md, api_reference_md):
        assert path.exists(), f"Expected committed doc page at {path}."
        assert path.read_text(encoding="utf-8").strip(), (
            f"Committed doc page {path} must not be empty."
        )

    # The api_reference page documents this package's own API.
    api_text = api_reference_md.read_text(encoding="utf-8")
    assert "GateEvaluator" in api_text


def test_committed_component_pages_contain_their_interface() -> None:
    """Sampled committed per-component pages exist and document their class.

    Uses "contains expected section" checks rather than byte-for-byte equality
    against freshly generated output, because the generator's rendering of a
    frozenset constructor default is non-deterministic across processes.
    """
    samples = {
        "gate_evaluator.md": "GateEvaluator",
        "safety_guard.md": "SafetyGuard",
    }
    for filename, class_name in samples.items():
        path = DOCS_DIR / filename
        assert path.exists(), f"Expected committed component page at {path}."
        text = path.read_text(encoding="utf-8")
        assert text.strip(), f"Committed component page {path} must not be empty."
        assert class_name in text, (
            f"Committed page {filename} must document its interface "
            f"(expected class name {class_name!r})."
        )


# ---------------------------------------------------------------------------
# write_api_reference
# ---------------------------------------------------------------------------
def test_write_api_reference_writes_non_empty_file(tmp_path: Path) -> None:
    """Writing the reference creates a non-empty file containing a known member.

    The destination is a pytest ``tmp_path`` so the committed ``roadmap/docs``
    files are never overwritten.
    """
    destination = tmp_path / "generated" / "api_reference.md"
    assert not destination.exists()

    write_api_reference(destination)

    assert destination.exists(), "write_api_reference must create the file."
    content = destination.read_text(encoding="utf-8")
    assert content.strip(), "Written API reference must not be empty."
    assert "GateEvaluator" in content


def test_write_api_reference_does_not_touch_committed_docs(tmp_path: Path) -> None:
    """Writing to a tmp path leaves the committed api_reference.md unchanged."""
    committed = DOCS_DIR / "api_reference.md"
    before = committed.read_text(encoding="utf-8")

    write_api_reference(tmp_path / "api_reference.md")

    after = committed.read_text(encoding="utf-8")
    assert before == after, "write_api_reference must not modify committed docs."
