"""
evals/text_metrics.py — shared, dependency-light text scoring primitives.
=========================================================================
Token-level edit distance and Word-Error-Rate used by both the Hinglish
code-switch evaluator (``evals/hinglish``) and the audio intelligibility
evaluator (``evals/audio``).

Everything here is pure-Python stdlib (no numpy / torch / jiwer) so it imports
and runs on a bare CPU-only machine with deterministic results.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "normalize_text",
    "tokenize",
    "levenshtein",
    "word_error_rate",
    "character_error_rate",
]

# Devanagari Unicode block: U+0900–U+097F.
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lower-case, NFC-normalize, and collapse whitespace.

    Punctuation is stripped to word tokens by :func:`tokenize`; this step only
    canonicalizes unicode and case so scoring is stable across input variants.
    """
    text = unicodedata.normalize("NFC", text)
    return text.casefold().strip()


def tokenize(text: str) -> list[str]:
    """Split text into lower-cased word tokens (unicode-aware, punctuation-free)."""
    return _WORD_RE.findall(normalize_text(text))


def levenshtein(ref: list[str], hyp: list[str]) -> int:
    """Token-level Levenshtein (edit) distance between two token sequences.

    Classic O(n*m) dynamic-programming with two rolling rows so memory stays O(m).
    Returns the minimum number of substitutions + insertions + deletions.
    """
    n, m = len(ref), len(hyp)
    if n == 0:
        return m
    if m == 0:
        return n

    prev = list(range(m + 1))
    cur = [0] * (m + 1)
    for i in range(1, n + 1):
        cur[0] = i
        ri = ref[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            cur[j] = min(
                prev[j] + 1,  # deletion
                cur[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution / match
            )
        prev, cur = cur, prev
    return prev[m]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word Error Rate = edit_distance(ref, hyp) / len(ref_tokens).

    WER of an empty reference is defined as 0.0 when the hypothesis is also empty,
    otherwise 1.0 (everything inserted is an error). WER is *not* clamped to 1.0:
    massive over-generation can exceed 1.0, which is the conventional definition.
    """
    ref_tokens = tokenize(reference)
    hyp_tokens = tokenize(hypothesis)
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    return levenshtein(ref_tokens, hyp_tokens) / len(ref_tokens)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Character Error Rate — useful for transliteration robustness on short tokens."""
    ref = list(normalize_text(reference).replace(" ", ""))
    hyp = list(normalize_text(hypothesis).replace(" ", ""))
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def is_devanagari(token: str) -> bool:
    """True if the token contains any Devanagari (Hindi script) character."""
    return bool(_DEVANAGARI.search(token))
