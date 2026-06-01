"""Filesystem path constants for the roadmap tooling and its tests.

Centralizing these paths means tests resolve the narrative artifact and the
strategy-PDF directory the same way regardless of the working directory pytest
is invoked from.
"""

from __future__ import annotations

from pathlib import Path

# This file lives at <workspace>/roadmap/paths.py
PACKAGE_ROOT: Path = Path(__file__).resolve().parent
WORKSPACE_ROOT: Path = PACKAGE_ROOT.parent

# The narrative planning artifact authored later in the plan (Task 23).
ROADMAP_MD_PATH: Path = PACKAGE_ROOT / "ROADMAP.md"

# Strategy PDFs that the roadmap supersedes / cites (Requirement 12.6).
DOCS_DIR: Path = WORKSPACE_ROOT / "docs"

# Versioned data files for the roadmap tooling.
DATA_DIR: Path = PACKAGE_ROOT / "data"

# The externalized Romanized -> Devanagari Hinglish transliteration table
# loaded by HinglishDataEngine on construction (Task 34.1).
HINGLISH_MAP_PATH: Path = DATA_DIR / "hinglish_map.json"

__all__ = [
    "PACKAGE_ROOT",
    "WORKSPACE_ROOT",
    "ROADMAP_MD_PATH",
    "DOCS_DIR",
    "DATA_DIR",
    "HINGLISH_MAP_PATH",
]
