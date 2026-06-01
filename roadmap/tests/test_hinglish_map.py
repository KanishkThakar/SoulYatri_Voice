"""Unit tests for the Hinglish mapping loader and the coverage report.

These plain ``pytest`` tests pin down two pieces of the Hinglish_Data_Engine
data moat:

- **The mapping loader** (Task 34.1) — :func:`roadmap.hinglish._load_default_mapping`
  and the import-time :data:`roadmap.hinglish.DEFAULT_ROMANIZED_TO_DEVANAGARI`
  constant, sourced from the versioned ``roadmap/data/hinglish_map.json`` file at
  :data:`roadmap.paths.HINGLISH_MAP_PATH`. The loader must faithfully reproduce
  the file's ``"mapping"`` object, the default engine must use exactly that
  table, normalization must be deterministic across calls and instances, shared
  Devanagari forms must collapse to one value, a custom mapping must override the
  default, and unmapped tokens must be retained-and-flagged (Requirements 5.5,
  5.8).

- **The coverage report** (Task 34.2) — :func:`render_coverage_report` must emit a
  non-empty Markdown report that names the mapping size, lists the unmapped
  tokens for review, reports per-item mapped/unmapped counts, and handles an
  empty corpus gracefully (Requirement 5.8).

Validates: Requirements 5.5, 5.8.
"""

from __future__ import annotations

import json

import pytest

from roadmap.hinglish import (
    DEFAULT_ROMANIZED_TO_DEVANAGARI,
    HinglishDataEngine,
    _load_default_mapping,
)
from roadmap.paths import HINGLISH_MAP_PATH
from roadmap.reports.hinglish_coverage import render_coverage_report


@pytest.fixture(scope="module")
def file_mapping() -> dict[str, str]:
    """The ``"mapping"`` object read directly from the versioned JSON file."""
    with open(HINGLISH_MAP_PATH, encoding="utf-8") as handle:
        document = json.load(handle)
    return document["mapping"]


# --------------------------------------------------------------------------- #
# Loader (Requirements 5.5, 5.8)
# --------------------------------------------------------------------------- #


def test_mapping_file_exists_and_parses_with_non_empty_mapping(
    file_mapping: dict[str, str],
) -> None:
    """The versioned JSON file exists, parses, and has a non-empty mapping.

    Validates: Requirements 5.5, 5.8.
    """
    assert HINGLISH_MAP_PATH.exists()
    assert isinstance(file_mapping, dict)
    assert file_mapping  # non-empty


def test_load_default_mapping_equals_file_mapping(
    file_mapping: dict[str, str],
) -> None:
    """``_load_default_mapping()`` reproduces the file's ``"mapping"`` object.

    Validates: Requirements 5.5.
    """
    loaded = _load_default_mapping()
    assert isinstance(loaded, dict)
    assert loaded == file_mapping


def test_default_constant_equals_loaded_mapping(
    file_mapping: dict[str, str],
) -> None:
    """The import-time constant equals the freshly loaded mapping.

    Validates: Requirements 5.5.
    """
    assert DEFAULT_ROMANIZED_TO_DEVANAGARI == _load_default_mapping()
    assert DEFAULT_ROMANIZED_TO_DEVANAGARI == file_mapping


def test_default_engine_mapping_size_matches_loaded_mapping(
    file_mapping: dict[str, str],
) -> None:
    """A default engine's ``mapping_size`` equals the loaded mapping length.

    Validates: Requirements 5.5.
    """
    engine = HinglishDataEngine()
    assert engine.mapping_size == len(file_mapping)
    assert engine.mapping_size == len(DEFAULT_ROMANIZED_TO_DEVANAGARI)


def test_normalization_is_deterministic_across_calls_and_instances() -> None:
    """The same input normalizes identically across calls and fresh instances.

    Requirement 5.5: normalization is a pure, deterministic mapping lookup, so
    repeated calls on one engine and a freshly constructed engine all agree, and
    the known tokens resolve to their Devanagari values from the file.

    Validates: Requirements 5.5.
    """
    text = "main theek hoon"

    engine = HinglishDataEngine()
    first = engine.normalize(text)
    second = engine.normalize(text)

    fresh = HinglishDataEngine()
    third = fresh.normalize(text)

    assert first == second == third
    assert first.normalized_text == second.normalized_text == third.normalized_text
    assert first.unmapped_tokens == []

    # The known tokens map to their Devanagari values straight from the file.
    expected = " ".join(
        DEFAULT_ROMANIZED_TO_DEVANAGARI[token]
        for token in ("main", "theek", "hoon")
    )
    assert first.normalized_text == expected


def test_shared_devanagari_forms_collapse_to_one_value() -> None:
    """Alternate Romanized spellings share a single Devanagari value.

    The file deliberately lists ``nahi``/``nahin`` and ``accha``/``achha`` as
    alternate spellings that must collapse to the same canonical Devanagari form.

    Validates: Requirements 5.5.
    """
    mapping = DEFAULT_ROMANIZED_TO_DEVANAGARI

    assert "nahi" in mapping
    assert "nahin" in mapping
    assert mapping["nahi"] == mapping["nahin"] == "नहीं"

    assert "accha" in mapping
    assert "achha" in mapping
    assert mapping["accha"] == mapping["achha"] == "अच्छा"


def test_custom_mapping_engine_uses_custom_map_not_default() -> None:
    """An engine constructed with a custom mapping ignores the default table.

    Validates: Requirements 5.5.
    """
    engine = HinglishDataEngine(mapping={"x": "य"})

    assert engine.mapping_size == 1
    assert engine.mapping_size != len(DEFAULT_ROMANIZED_TO_DEVANAGARI)

    result = engine.normalize("x main")
    # "x" is in the custom map; "main" is NOT (it only exists in the default).
    assert result.normalized_text == "य main"
    assert result.unmapped_tokens == ["main"]


def test_unmapped_token_retained_and_flagged() -> None:
    """An unmapped token is retained unchanged and flagged for review.

    Requirement 5.8: ``normalize("main foobar hoon")`` keeps ``foobar`` verbatim
    in the output and lists it in ``unmapped_tokens`` while the known tokens are
    normalized and not flagged.

    Validates: Requirements 5.8.
    """
    engine = HinglishDataEngine()
    result = engine.normalize("main foobar hoon")

    # The unknown token is retained unchanged and is the only flagged token.
    assert "foobar" in result.normalized_text.split()
    assert result.unmapped_tokens == ["foobar"]

    # The known tokens are normalized to Devanagari and never flagged.
    assert DEFAULT_ROMANIZED_TO_DEVANAGARI["main"] in result.normalized_text.split()
    assert DEFAULT_ROMANIZED_TO_DEVANAGARI["hoon"] in result.normalized_text.split()
    assert "main" not in result.unmapped_tokens
    assert "hoon" not in result.unmapped_tokens


# --------------------------------------------------------------------------- #
# Coverage report (Requirement 5.8)
# --------------------------------------------------------------------------- #


def test_coverage_report_lists_unmapped_tokens_and_counts() -> None:
    """The report names the mapping size and lists the unmapped tokens.

    Requirement 5.8: the Markdown report is non-empty, mentions the mapping
    size, surfaces the unmapped tokens (``foobar``, ``baz``) in the review
    section, and includes per-item mapped/unmapped counts.

    Validates: Requirements 5.8.
    """
    engine = HinglishDataEngine()
    corpus = ["main theek hoon", "foobar baz main", ""]

    report = render_coverage_report(engine, corpus)

    assert isinstance(report, str)
    assert report.strip()  # non-empty

    # Mapping size is mentioned.
    assert str(engine.mapping_size) in report

    # Both unmapped tokens are surfaced for review.
    assert "foobar" in report
    assert "baz" in report
    assert "Unmapped tokens flagged for review" in report

    # Per-item mapped/unmapped columns are present.
    assert "Mapped" in report
    assert "Unmapped" in report
    assert "Per-item coverage" in report


def test_coverage_report_handles_empty_corpus_gracefully() -> None:
    """An empty corpus renders a non-empty report without crashing.

    Validates: Requirements 5.8.
    """
    engine = HinglishDataEngine()

    report = render_coverage_report(engine, [])

    assert isinstance(report, str)
    assert report.strip()  # non-empty, no crash
    assert str(engine.mapping_size) in report
    # The empty corpus is noted and the aggregate summary still renders.
    assert "Corpus items: 0" in report
    assert "Aggregate summary" in report
