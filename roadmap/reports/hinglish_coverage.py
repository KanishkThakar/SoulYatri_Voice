"""Render an unmapped-token coverage report for the Hinglish engine.

This module turns a :class:`~roadmap.hinglish.HinglishDataEngine` and a corpus
of text strings into a human-readable Markdown coverage report. It is the
presentation counterpart to the engine's transliteration logic and adds **no**
decision-making of its own: it normalizes each corpus item with
``engine.normalize(...)`` and reports what the engine already classifies as
unmapped (Requirement 5.8).

What the report contains (Requirement 5.8)
------------------------------------------
- The engine's mapping size (``engine.mapping_size``), so a reviewer knows how
  large the transliteration table currently is.
- A per-corpus-item table: each item's index, a short snippet, its total word
  tokens, the **mapped** count (tokens the engine recognized) and the
  **unmapped** count (tokens flagged for review).
- An aggregate summary across the whole corpus: total / mapped / unmapped token
  counts and the overall coverage percentage.
- The **aggregated, deduplicated list of unmapped tokens** with their
  occurrence counts, so reviewers can prioritise extending the mapping
  (Requirement 5.8).

Tokenization
------------
"Total tokens" for an item is ``len(text.split())`` — whitespace-delimited word
tokens. This is the same token granularity the engine uses internally (it
tokenizes on whitespace runs), so the **mapped** count is defined as::

    mapped = total_tokens - len(unmapped_tokens)

i.e. every classifiable word token that the engine did *not* flag as unmapped.
Because the engine flags one entry per unmapped occurrence, ``unmapped`` never
exceeds ``total`` and ``mapped`` is always ``>= 0``.

This module performs no file I/O and no GPU/training work; it is a pure string
renderer operating on the engine's normalization output. An empty corpus is
handled gracefully (the report renders with zeroed aggregates and a note that
no corpus items were supplied).

Requirements: 5.8.
"""

from __future__ import annotations

from collections import Counter

from ..hinglish import HinglishDataEngine

__all__ = [
    "render_coverage_report",
]

#: Maximum number of characters of a corpus item shown in the per-item table's
#: snippet column, so long inputs do not blow out the table width.
_SNIPPET_MAX_LEN = 40


def render_coverage_report(
    engine: HinglishDataEngine, corpus: list[str]
) -> str:
    """Render a Markdown unmapped-token coverage report for ``corpus``.

    Normalizes every item in ``corpus`` with ``engine.normalize(...)`` and
    reports the engine's mapping size, per-item mapped/unmapped token counts, an
    aggregate summary, and the deduplicated list of unmapped tokens flagged for
    review (Requirement 5.8). The renderer is pure: it reports exactly what the
    engine classifies and makes no mapping decisions of its own.

    Args:
        engine: The :class:`HinglishDataEngine` whose loaded mapping is being
            measured against the corpus.
        corpus: A list of text strings to analyze. May be empty.

    Returns:
        A Markdown string. The report always contains the header, the mapping
        size, the per-item section, and the aggregate summary; the
        unmapped-token review section appears with its entries when any
        unmapped tokens were found and otherwise notes full coverage.
    """
    lines: list[str] = ["# Hinglish Transliteration Coverage Report", ""]
    lines.append(f"- Mapping size: {engine.mapping_size} entries")
    lines.append(f"- Corpus items: {len(corpus)}")
    lines.append("")

    # Per-item analysis. Accumulate aggregate totals and the deduplicated
    # unmapped-token occurrence counts in a single pass over the corpus.
    total_tokens = 0
    total_unmapped = 0
    unmapped_counter: Counter[str] = Counter()

    lines.extend(_render_per_item_header())
    for index, text in enumerate(corpus):
        item_total = len(text.split())
        result = engine.normalize(text)
        item_unmapped = len(result.unmapped_tokens)
        item_mapped = item_total - item_unmapped

        total_tokens += item_total
        total_unmapped += item_unmapped
        unmapped_counter.update(result.unmapped_tokens)

        lines.append(
            f"| {index} "
            f"| {_format_snippet(text)} "
            f"| {item_total} "
            f"| {item_mapped} "
            f"| {item_unmapped} |"
        )

    if not corpus:
        lines.append("| _(empty corpus)_ | — | 0 | 0 | 0 |")

    total_mapped = total_tokens - total_unmapped
    lines.append("")
    lines.extend(
        _render_aggregate_summary(total_tokens, total_mapped, total_unmapped)
    )
    lines.append("")
    lines.extend(_render_unmapped_review(unmapped_counter))

    return "\n".join(lines) + "\n"


# -- Section renderers -------------------------------------------------------


def _render_per_item_header() -> list[str]:
    """Render the per-item table header."""
    return [
        "## Per-item coverage",
        "",
        "| Item | Snippet | Total tokens | Mapped | Unmapped |",
        "| --- | --- | --- | --- | --- |",
    ]


def _render_aggregate_summary(
    total_tokens: int, total_mapped: int, total_unmapped: int
) -> list[str]:
    """Render the corpus-wide aggregate token counts and coverage percentage."""
    coverage = (
        100.0 * total_mapped / total_tokens if total_tokens else 0.0
    )
    return [
        "## Aggregate summary",
        "",
        f"- Total tokens: {total_tokens}",
        f"- Mapped tokens: {total_mapped}",
        f"- Unmapped tokens: {total_unmapped}",
        f"- Coverage: {coverage:.1f}%",
    ]


def _render_unmapped_review(unmapped_counter: Counter[str]) -> list[str]:
    """Render the deduplicated unmapped-token list flagged for review (5.8).

    Tokens are ordered by descending occurrence count, then alphabetically, so
    the most impactful gaps in the mapping surface first.
    """
    lines = ["## Unmapped tokens flagged for review", ""]
    if not unmapped_counter:
        lines.append("_No unmapped tokens: the corpus is fully covered._")
        return lines

    lines.append(
        f"{len(unmapped_counter)} distinct token(s) had no mapping entry. "
        "Extend the transliteration mapping to cover them:"
    )
    lines.append("")
    lines.append("| Token | Occurrences |")
    lines.append("| --- | --- |")
    for token, count in sorted(
        unmapped_counter.items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"| {_escape_cell(token)} | {count} |")
    return lines


# -- Value formatting --------------------------------------------------------


def _format_snippet(text: str) -> str:
    """Render a short, table-safe snippet of a corpus item.

    Collapses internal whitespace to single spaces, truncates to
    :data:`_SNIPPET_MAX_LEN` characters with an ellipsis, escapes Markdown
    table-breaking characters, and represents an empty/whitespace-only item as
    a readable marker.
    """
    collapsed = " ".join(text.split())
    if not collapsed:
        return "_(empty)_"
    if len(collapsed) > _SNIPPET_MAX_LEN:
        collapsed = collapsed[: _SNIPPET_MAX_LEN - 1] + "\u2026"
    return _escape_cell(collapsed)


def _escape_cell(value: str) -> str:
    """Escape characters that would break a Markdown table cell."""
    return value.replace("\\", "\\\\").replace("|", "\\|")
