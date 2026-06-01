"""
Tests for memory/summarizer/pipeline.py (Phase 12B).

Covers turn compression, memory summarization, relevance scoring + reranking, bounded/compact
context building, and stale-memory pruning.
"""

from __future__ import annotations

from memory.contracts import MemoryKind, MemoryRecord
from memory.summarizer.pipeline import (
    RetrievedContext,
    SummarizerPipeline,
    compress_turn,
    score_relevance,
    summarize_memories,
)


def _rec(text: str, ts_ms: int, kind: MemoryKind = MemoryKind.turn_summary) -> MemoryRecord:
    return MemoryRecord(session_id="s1", kind=kind, content={"t": text}, text=text, ts_ms=ts_ms)


# ---------------------------------------------------------------------------
# turn compression
# ---------------------------------------------------------------------------
def test_compress_short_text_unchanged() -> None:
    assert compress_turn("hi there") == "hi there"


def test_compress_collapses_whitespace() -> None:
    assert compress_turn("hello    world\n\n  again") == "hello world again"


def test_compress_long_text_bounded() -> None:
    long = "This is sentence one. " * 50
    out = compress_turn(long, max_chars=80)
    assert len(out) <= 84  # budget + ellipsis guard
    assert out.endswith("…")


def test_compress_single_huge_sentence_truncates_on_word() -> None:
    text = "word " * 100  # one long run, no sentence punctuation
    out = compress_turn(text.strip(), max_chars=40)
    assert len(out) <= 44
    assert "  " not in out


# ---------------------------------------------------------------------------
# relevance scoring
# ---------------------------------------------------------------------------
def test_score_relevance_ranks_overlap_higher() -> None:
    now = 10_000
    relevant = _rec("user is worried about exam results", 9_000)
    irrelevant = _rec("user likes football matches", 9_000)
    s_rel = score_relevance("exam worry", relevant, now=now)
    s_irr = score_relevance("exam worry", irrelevant, now=now)
    assert s_rel > s_irr


def test_score_relevance_empty_query_uses_recency() -> None:
    now = 10_000
    fresh = _rec("anything", now)
    s = score_relevance("", fresh, now=now)
    assert 0.0 <= s <= 1.0
    assert s > 0.9  # very recent


# ---------------------------------------------------------------------------
# memory summarization
# ---------------------------------------------------------------------------
def test_summarize_memories_dedupes_and_bounds() -> None:
    records = [
        _rec("user enjoys chai in the morning", 1000),
        _rec("user enjoys chai in the morning", 1001),  # duplicate
        _rec("user is preparing for exams", 1002),
    ]
    digest = summarize_memories(records, max_chars=400)
    assert digest.count("chai") == 1  # deduped
    assert "exams" in digest


def test_summarize_memories_empty() -> None:
    assert summarize_memories([]) == ""


def test_summarize_fn_hook_used() -> None:
    records = [_rec("something", 1000)]
    out = summarize_memories(records, summarize_fn=lambda s: "ABSTRACT")
    assert out == "ABSTRACT"


def test_summarize_fn_failure_degrades_gracefully() -> None:
    records = [_rec("something useful", 1000)]

    def boom(_s: str) -> str:
        raise RuntimeError("text-brain down")

    out = summarize_memories(records, summarize_fn=boom)
    # Falls back to the extractive digest instead of raising.
    assert "something useful" in out


# ---------------------------------------------------------------------------
# pipeline: rerank + build_context
# ---------------------------------------------------------------------------
def test_rerank_filters_below_threshold() -> None:
    pipe = SummarizerPipeline(min_relevance=0.2)
    records = [
        _rec("exam stress is high", 9_000),
        _rec("totally unrelated cricket", 9_000),
    ]
    ranked = pipe.rerank("exam stress", records, now=10_000)
    assert ranked
    assert ranked[0].record.text == "exam stress is high"


def test_build_context_is_bounded_and_compact() -> None:
    pipe = SummarizerPipeline(max_records=3, digest_max_chars=300)
    records = [_rec(f"memory item number {i} about exams", 1000 + i) for i in range(20)]
    ctx = pipe.build_context("exams", records, now=10_000)
    assert isinstance(ctx, RetrievedContext)
    assert len(ctx) <= 3  # bounded
    assert len(ctx.digest) <= 320  # compact
    assert len(ctx.scores) == len(ctx.records)


def test_build_context_empty_when_irrelevant() -> None:
    pipe = SummarizerPipeline(min_relevance=0.5)
    records = [_rec("apples oranges bananas", 1000)]
    ctx = pipe.build_context("quantum chromodynamics", records, now=2000)
    assert ctx.is_empty()


def test_context_to_dict_shape() -> None:
    pipe = SummarizerPipeline()
    ctx = pipe.build_context("exam", [_rec("exam tomorrow", 9_999)], now=10_000)
    d = ctx.to_dict()
    assert set(d.keys()) == {"digest", "records", "count"}
    if d["records"]:
        assert "score" in d["records"][0]


# ---------------------------------------------------------------------------
# stale-memory pruning
# ---------------------------------------------------------------------------
def test_prune_by_age() -> None:
    pipe = SummarizerPipeline()
    now = 1_000_000
    fresh = _rec("fresh", now - 1000)
    stale = _rec("stale", now - 10_000_000)
    keep, drop = pipe.prune([fresh, stale], now=now, max_age_ms=5_000)
    assert fresh in keep
    assert stale in drop


def test_prune_by_recency_floor() -> None:
    pipe = SummarizerPipeline(half_life_ms=1000)
    now = 10_000_000
    ancient = _rec("ancient", 0)  # recency weight ~ 0
    keep, drop = pipe.prune([ancient], now=now, recency_floor=0.01)
    assert ancient in drop
    assert keep == []


def test_prune_max_keep_caps_survivors() -> None:
    pipe = SummarizerPipeline()
    now = 100_000
    records = [_rec(f"r{i}", now - i) for i in range(10)]
    keep, drop = pipe.prune(records, now=now, max_keep=3)
    assert len(keep) == 3
    assert len(drop) == 7
    # The freshest (smallest age) should be kept.
    assert all(k.ts_ms >= d.ts_ms for k in keep for d in drop)


def test_prune_keeps_all_when_no_limits() -> None:
    pipe = SummarizerPipeline(half_life_ms=10**12)
    now = 1000
    records = [_rec(f"r{i}", now - i) for i in range(5)]
    keep, drop = pipe.prune(records, now=now)
    assert len(keep) == 5
    assert drop == []
