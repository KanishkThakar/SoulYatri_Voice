"""Structural test for **Requirement 12.6** — PDF-citation existence.

Requirement 12.6 (Scope boundaries / relationship to existing artifacts):

    WHERE the Roadmap references a strategy PDF, THE Roadmap SHALL cite that
    document by its exact file name as it appears in the ``docs/`` directory.

The check below enforces the *existence* half of that requirement: every
``docs/`` PDF file name cited in the narrative ``ROADMAP.md`` artifact must
correspond to a real file present in the actual ``docs/`` directory listing.
A citation that names a PDF which does not exist in ``docs/`` is a genuine
traceability defect and fails this test with a message naming the offender(s).

This is a plain ``pytest`` structural test (no Hypothesis): it reads the two
filesystem artifacts via the shared path constants in ``roadmap/paths.py`` so
it resolves them identically regardless of the pytest working directory.

Validates: Requirements 12.6.
"""

from __future__ import annotations

import re

from roadmap.paths import DOCS_DIR, ROADMAP_MD_PATH

#: Matches a backtick-delimited file name ending in ``.pdf`` as authored in the
#: roadmap, e.g. ``\u0060SOULYATRI_MASTER_BIBLE.pdf\u0060``. Using the backtick
#: delimiters lets us capture PDF names that contain spaces (such as
#: ``Building a single clean-room voice model ... ElevenLabs.pdf``) without
#: prematurely splitting on whitespace. The match is case-insensitive on the
#: ``.pdf`` extension only.
_CITED_PDF_PATTERN = re.compile(r"`([^`]+?\.pdf)`", re.IGNORECASE)


def _actual_docs_pdf_names() -> set[str]:
    """Return the set of ``*.pdf`` file names present in the real ``docs/`` dir.

    This is the source of truth: the file names that actually exist on disk.
    """
    return {
        entry.name
        for entry in DOCS_DIR.iterdir()
        if entry.is_file() and entry.suffix.lower() == ".pdf"
    }


def _cited_pdf_names(roadmap_text: str) -> set[str]:
    """Extract every backtick-cited ``*.pdf`` file name from the roadmap text."""
    return {match.group(1).strip() for match in _CITED_PDF_PATTERN.finditer(roadmap_text)}


def test_docs_dir_and_roadmap_exist() -> None:
    """The two artifacts under test must be present before any citation check.

    Validates: Requirements 12.6.
    """
    assert ROADMAP_MD_PATH.is_file(), f"ROADMAP.md not found at {ROADMAP_MD_PATH}"
    assert DOCS_DIR.is_dir(), f"docs/ directory not found at {DOCS_DIR}"


def test_roadmap_cites_at_least_one_pdf() -> None:
    """The roadmap actually cites strategy PDFs (the rule is not vacuous).

    Requirement 12.6 is a WHERE-conditioned rule; this guards against the test
    passing trivially because no PDF citations were detected at all.

    Validates: Requirements 12.6.
    """
    roadmap_text = ROADMAP_MD_PATH.read_text(encoding="utf-8")
    cited = _cited_pdf_names(roadmap_text)
    assert cited, (
        "Expected ROADMAP.md to cite at least one `*.pdf` strategy document "
        "by exact file name, but none were found."
    )


def test_every_cited_pdf_exists_in_docs_dir() -> None:
    """Core 12.6 assertion: every cited ``docs/`` PDF exists on disk.

    For each PDF file name cited in ROADMAP.md, assert a file of that exact
    name exists in the actual ``docs/`` directory listing. Any cited-but-missing
    name is reported as a real traceability defect.

    Validates: Requirements 12.6.
    """
    roadmap_text = ROADMAP_MD_PATH.read_text(encoding="utf-8")
    cited = _cited_pdf_names(roadmap_text)
    actual = _actual_docs_pdf_names()

    missing = sorted(cited - actual)
    assert not missing, (
        "ROADMAP.md cites the following PDF file name(s) that do NOT exist in "
        f"the docs/ directory ({DOCS_DIR}): {missing}. "
        f"Actual docs/ PDFs present: {sorted(actual)}."
    )
