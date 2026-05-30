"""
memory/_text.py — Dependency-light text & scoring utilities.

Shared helpers used by every tier and the summarizer:

  * :func:`tokenize`          — cheap, language-agnostic word tokenizer (handles Hinglish).
  * :func:`relevance_score`   — lexical Jaccard-ish overlap in [0, 1] (no model weights).
  * :func:`recency_weight`    — exponential time decay in (0, 1].
  * :func:`cosine`            — cosine similarity for embedding vectors (numpy or pure-python).
  * :func:`hash_embedding`    — deterministic hashing-trick embedding used as the CPU-only
                                fallback for the multilingual-e5 interface (no weights needed).

Everything here is pure stdlib + optional numpy (lazy). Nothing blocks; nothing heavy loads
at import time.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

__all__ = [
    "tokenize",
    "relevance_score",
    "recency_weight",
    "cosine",
    "hash_embedding",
]

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens. Unicode-aware so Devanagari + Latin both tokenize."""
    if not text:
        return []
    return _WORD_RE.findall(text.lower())


def relevance_score(query: str, text: str) -> float:
    """Lexical relevance in [0, 1] between ``query`` and ``text``.

    Uses overlap-coefficient-style scoring: fraction of query tokens present in the text,
    lightly boosted by Jaccard so longer exact matches rank above incidental ones. This is a
    deterministic, CPU-only stand-in for semantic scoring — good enough to keep retrieval
    bounded and explainable, and replaced by true cosine in the semantic tier.
    """
    q = set(tokenize(query))
    t = set(tokenize(text))
    if not q or not t:
        return 0.0
    inter = len(q & t)
    if inter == 0:
        return 0.0
    coverage = inter / len(q)  # how much of the query is covered
    jaccard = inter / len(q | t)
    return max(0.0, min(1.0, 0.7 * coverage + 0.3 * jaccard))


def recency_weight(ts_ms: int, now_ms: int, half_life_ms: int) -> float:
    """Exponential recency decay in (0, 1].

    A record emitted ``half_life_ms`` ago scores 0.5; one emitted now scores 1.0. Future or
    clock-skewed timestamps clamp to 1.0.
    """
    if half_life_ms <= 0:
        return 1.0
    age = max(0, now_ms - ts_ms)
    return float(math.pow(0.5, age / half_life_ms))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity mapped into [0, 1] (0.5 == orthogonal).

    Prefers numpy when available; otherwise a pure-python implementation. Returns 0.0 for a
    zero vector to avoid NaNs.
    """
    try:  # pragma: no cover - only when numpy is installed
        import numpy as np

        va = np.asarray(a, dtype="float64")
        vb = np.asarray(b, dtype="float64")
        na = float(np.linalg.norm(va))
        nb = float(np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        raw = float(np.dot(va, vb) / (na * nb))
    except Exception:
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b, strict=False):
            dot += x * y
            na += x * x
            nb += y * y
        if na == 0.0 or nb == 0.0:
            return 0.0
        raw = dot / (math.sqrt(na) * math.sqrt(nb))
    # Map [-1, 1] -> [0, 1] so it composes with the other [0,1] scores.
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))


def hash_embedding(text: str, dim: int = 384) -> list[float]:
    """Deterministic hashing-trick embedding — the CPU-only fallback for multilingual-e5.

    multilingual-e5 produces 384-dim (small) embeddings; we mirror that default dimensionality
    so a later swap to the real model keeps vector shapes consistent. Tokens are hashed into
    buckets with a sign, then the vector is L2-normalized. This is *not* semantic, but it is
    stable, fast, weight-free, and good enough for tests + offline retrieval.
    """
    vec = [0.0] * dim
    for tok in tokenize(text):
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        idx = h % dim
        sign = 1.0 if (h >> 1) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]
