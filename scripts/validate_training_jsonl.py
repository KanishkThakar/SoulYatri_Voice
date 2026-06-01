#!/usr/bin/env python
"""
scripts/validate_training_jsonl.py — SoulYatri training corpus validator (Phase 17C)
====================================================================================
Parses ``docs/training/qa_dataset.jsonl`` line-by-line and asserts that every line is a
valid standalone JSON object conforming to the documented schema (docs/training/schema.md):

    {"instruction": str, "response": str, "source": [str, ...], "tags": [str, ...]}

Rules enforced per line:
  1. The line parses as JSON and is a JSON object (dict).
  2. All required keys are present: instruction, response, source, tags.
  3. ``instruction`` and ``response`` are non-empty strings.
  4. ``source`` and ``tags`` are non-empty lists of strings.

Exit code 0 means every line passed; non-zero means at least one line failed (the failing
line number and reason are printed). Blank lines are ignored.

Usage:
    python scripts/validate_training_jsonl.py
    python scripts/validate_training_jsonl.py path/to/other.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_STRING_KEYS = ("instruction", "response")
REQUIRED_LIST_KEYS = ("source", "tags")
REQUIRED_KEYS = REQUIRED_STRING_KEYS + REQUIRED_LIST_KEYS

# Default target relative to the repo root (this file lives in <root>/scripts/).
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "docs" / "training" / "qa_dataset.jsonl"


def validate_line(line: str, lineno: int) -> list[str]:
    """Validate a single JSONL line. Returns a list of error strings (empty == valid)."""
    errors: list[str] = []
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        return [f"line {lineno}: invalid JSON ({exc})"]

    if not isinstance(obj, dict):
        return [f"line {lineno}: top-level value must be a JSON object, got {type(obj).__name__}"]

    for key in REQUIRED_KEYS:
        if key not in obj:
            errors.append(f"line {lineno}: missing required key '{key}'")

    for key in REQUIRED_STRING_KEYS:
        if key in obj:
            value = obj[key]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"line {lineno}: '{key}' must be a non-empty string")

    for key in REQUIRED_LIST_KEYS:
        if key in obj:
            value = obj[key]
            if not isinstance(value, list) or not value:
                errors.append(f"line {lineno}: '{key}' must be a non-empty array")
            elif not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"line {lineno}: every entry in '{key}' must be a non-empty string")

    return errors


def validate_file(path: Path) -> tuple[int, list[str]]:
    """Validate every non-blank line of ``path``. Returns (valid_count, errors)."""
    if not path.exists():
        return 0, [f"file not found: {path}"]

    valid = 0
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue  # ignore blank lines
            line_errors = validate_line(line, lineno)
            if line_errors:
                errors.extend(line_errors)
            else:
                valid += 1
    return valid, errors


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    target = Path(argv[0]).resolve() if argv else DEFAULT_PATH

    valid, errors = validate_file(target)

    print(f"Validating: {target}")
    if errors:
        print(f"FAILED: {len(errors)} error(s), {valid} valid line(s).")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"OK: {valid} line(s) validated, all conform to the schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
