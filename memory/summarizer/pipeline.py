"""
memory/summarizer/pipeline.py — Retrieval summarizer (Phase 12B).

Keeps retrieved context *relevant and compact* so memory never poisons the hot path. Four
responsibilities, all CPU-only and weight-free (the heavy text-brain summarizer in ``aux/`` can
be plugged in later via the ``summarize_fn`` hook):

  1. turn compression       — :func:`compress_turn` shrinks a verbose turn into a short summary.
  2. memory summarization    — :func:`summarize_memories` fuses many records into one digest.
  3. relevance scoring       — :func:`score_relevance` / :meth:`SummarizerPipeline.rerank`.
  4. stale-memory pruning    — :meth:`SummarizerPipeline.prune` drops old/low-value records.

The pipeline takes the raw merged hits from :class:`memory.store.MemoryStore` (or a tier) and
produces a bounded, deduped, reranked, token-budgeted context block.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence

from memory._logging import get_logger
from memory._text import recency_weight, relevance_score, tokenize
from memory.contracts import (
    MemoryRecord,
    RetrievalPolicy,
    ScoredMemory,
    now_ms,
)

__all__ = [
    "RetrievedContext",
    "SummarizerPipeline",
    "compress_turn",
    "summarize_memories",
    "score_relevance",
]

log = get_logger("memory.summarizer.pipeline")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")
_WHITESPACE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# turn compression
# ---------------------------------------------------------------------------
def compress_turn(text: str, *, max_chars: int = 200) -> str:
    """Compress a single verbose turn into a short, faithful summary.

    Extractive + truncating: collapses whitespace, keeps leading sentences until the budget is
    hit, and hard-truncates on a word boundary as a final guard. Deterministic and weight-free.
    """
    if not text:
        return ""
    clean = _WHITESPACE.sub(" ", text).strip()
    if len(clean) <= max_chars:
        return clean

    out: list[str] = []
    length = 0
    for sentence in _SENTENCE_SPLIT.split(clean):
        if not sentence:
            continue
        if length + len(sentence) + 1 > max_chars:
            break
        out.append(sentence)
        length += len(sentence) + 1

    if out:
        summary = " ".join(out).strip()
    else:  # first sentence already exceeds budget — truncate on a word boundary
        summary = clean[:max_chars].rsplit(" ", 1)[0].strip()
    if len(summary) < len(clean):
        summary = summary.rstrip(".!?।") + " …"
    return summary


# ---------------------------------------------------------------------------
# memory summarization
# ---------------------------------------------------------------------------
def summarize_memories(
    records: Sequence[MemoryRecord],
    *,
    max_chars: int = 600,
    summarize_fn: Callable[[str], str] | None = None,
) -> str:
    """Fuse many records into one compact digest, newest first, deduped.

    ``summarize_fn`` lets the caller plug in the ``aux/`` text-brain for abstractive summaries;
    by default this does deterministic extractive fusion so it works with no model weights.
    """
    if not records:
        return ""
    ordered = sorted(records, key=lambda r: r.ts_ms, reverse=True)

    seen: set[str] = set()
    lines: list[str] = []
    budget = max_chars
    for rec in ordered:
        piece = compress_turn(rec.text or "", max_chars=160)
        if not piece:
            continue
        norm = piece.lower()
        if norm in seen:
            continue
        seen.add(norm)
        line = f"- ({rec.kind.value}) {piece}"
        if budget - len(line) < 0:
            break
        lines.append(line)
        budget -= len(line)

    digest = "\n".join(lines)
    if summarize_fn is not None and digest:
        try:
            digest = summarize_fn(digest)
        except Exception as exc:  # never let an optional hook break retrieval
            log.warning("summarize_fn_failed", reason=type(exc).__name__)
    return digest


# ---------------------------------------------------------------------------
# relevance scoring
# ---------------------------------------------------------------------------
def score_relevance(
    query: str,
    record: MemoryRecord,
    *,
    now: int | None = None,
    half_life_ms: int = 15 * 60 * 1000,
    recency_weight_factor: float = 0.3,
) -> float:
    """Blend lexical relevance with recency into a single [0, 1] score."""
    now = now if now is not None else now_ms()
    lexical = relevance_score(query, record.text) if query else 0.0
    recency = recency_weight(record.ts_ms, now, half_life_ms)
    if not query:
        return recency
    rw = max(0.0, min(1.0, recency_weight_factor))
    return max(0.0, min(1.0, (1.0 - rw) * lexical + rw * recency))


# ---------------------------------------------------------------------------
# retrieved-context container
# ---------------------------------------------------------------------------
class RetrievedContext:
    """A bounded, reranked, summarized context block ready for the runtime."""

    __slots__ = ("records", "digest", "scores")

    def __init__(
        self,
        records: list[MemoryRecord],
        digest: str,
        scores: list[float],
    ) -> None:
        self.records = records
        self.digest = digest
        self.scores = scores

    def __len__(self) -> int:
        return len(self.records)

    def is_empty(self) -> bool:
        return not self.records

    def to_dict(self) -> dict:
        return {
            "digest": self.digest,
            "records": [r.as_item(score=s) for r, s in zip(self.records, self.scores, strict=False)],
            "count": len(self.records),
        }


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
class SummarizerPipeline:
    """Turn raw retrieved memories into relevant, compact context.

    Parameters
    ----------
    max_records:
        Hard cap on records carried into context (compactness).
    min_relevance:
        Drop records scoring below this (every item must justify itself).
    digest_max_chars:
        Budget for the fused digest.
    half_life_ms:
        Recency decay used by both rerank and pruning.
    summarize_fn:
        Optional abstractive summarizer hook (e.g. aux text-brain).
    """

    def __init__(
        self,
        *,
        max_records: int = 6,
        min_relevance: float = 0.05,
        digest_max_chars: int = 600,
        half_life_ms: int = 15 * 60 * 1000,
        summarize_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.max_records = max_records
        self.min_relevance = min_relevance
        self.digest_max_chars = digest_max_chars
        self.half_life_ms = half_life_ms
        self.summarize_fn = summarize_fn

    # -- relevance reranking -------------------------------------------
    def rerank(
        self, query: str, records: Iterable[MemoryRecord], *, now: int | None = None
    ) -> list[ScoredMemory]:
        """Score, threshold, dedupe and sort records by blended relevance."""
        now = now if now is not None else now_ms()
        seen: set[str] = set()
        scored: list[ScoredMemory] = []
        for rec in records:
            key = (rec.text or "").strip().lower()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            score = score_relevance(
                query, rec, now=now, half_life_ms=self.half_life_ms
            )
            if score < self.min_relevance:
                continue
            scored.append(ScoredMemory(record=rec, score=score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    # -- context build -------------------------------------------------
    def build_context(
        self, query: str, records: Iterable[MemoryRecord], *, now: int | None = None
    ) -> RetrievedContext:
        """Produce a bounded, reranked, summarized :class:`RetrievedContext`."""
        ranked = self.rerank(query, records, now=now)[: self.max_records]
        chosen = [sm.record for sm in ranked]
        scores = [sm.score for sm in ranked]
        digest = summarize_memories(
            chosen, max_chars=self.digest_max_chars, summarize_fn=self.summarize_fn
        )
        log.debug(
            "summarizer_build_context", returned=len(chosen),
            digest_chars=len(digest), query_tokens=len(tokenize(query)),
        )
        return RetrievedContext(records=chosen, digest=digest, scores=scores)

    # -- stale-memory pruning ------------------------------------------
    def prune(
        self,
        records: Sequence[MemoryRecord],
        *,
        now: int | None = None,
        max_age_ms: int | None = None,
        max_keep: int | None = None,
        recency_floor: float = 0.01,
    ) -> tuple[list[MemoryRecord], list[MemoryRecord]]:
        """Split records into ``(keep, drop)``.

        A record is pruned when it is older than ``max_age_ms`` OR its recency weight falls
        below ``recency_floor``. After age-based pruning the survivors are capped at
        ``max_keep`` (freshest kept), bounding stored memory.
        """
        now = now if now is not None else now_ms()
        keep: list[MemoryRecord] = []
        drop: list[MemoryRecord] = []
        for rec in records:
            age = now - rec.ts_ms
            rw = recency_weight(rec.ts_ms, now, self.half_life_ms)
            too_old = max_age_ms is not None and age > max_age_ms
            too_faded = rw < recency_floor
            if too_old or too_faded:
                drop.append(rec)
            else:
                keep.append(rec)

        keep.sort(key=lambda r: r.ts_ms, reverse=True)
        if max_keep is not None and len(keep) > max_keep:
            drop.extend(keep[max_keep:])
            keep = keep[:max_keep]

        log.debug(
            "summarizer_prune", kept=len(keep), dropped=len(drop),
            max_age_ms=max_age_ms, max_keep=max_keep,
        )
        return keep, drop

    # -- convenience: rerank straight from store hits ------------------
    def summarize_scored(
        self, query: str, scored: Iterable[ScoredMemory], *, now: int | None = None
    ) -> RetrievedContext:
        """Build context from already-scored store hits (re-applies thresholds + budget)."""
        return self.build_context(query, (sm.record for sm in scored), now=now)


def _retrieval_policy_half_life(policy: RetrievalPolicy) -> int:
    """Helper so callers can align the pipeline half-life with a RetrievalPolicy."""
    return policy.recency_half_life_ms
