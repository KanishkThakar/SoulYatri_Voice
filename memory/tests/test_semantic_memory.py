"""
Tests for memory/qdrant/semantic_memory.py (Phase 12A).

Covers the numpy/in-memory cosine fallback (NO Qdrant, NO model weights), the multilingual-e5
embedding interface fallback, bounded top_k, semantic-ish ranking, and score thresholding.
"""

from __future__ import annotations

import sys

from memory._text import cosine, hash_embedding
from memory.contracts import (
    MemoryKind,
    MemoryReadQuery,
    MemoryRecord,
    RetrievalPolicy,
)
from memory.qdrant.semantic_memory import (
    EMBED_DIM,
    MultilingualE5Embedder,
    QdrantSemanticMemory,
    SemanticMemory,
)


def _rec(session: str, kind: MemoryKind, text: str, ts_ms: int) -> MemoryRecord:
    return MemoryRecord(session_id=session, kind=kind, content={"t": text}, text=text, ts_ms=ts_ms)


def test_alias_same_class() -> None:
    assert QdrantSemanticMemory is SemanticMemory


def test_no_heavy_imports() -> None:
    for heavy in ("torch", "transformers", "qdrant_client", "sentence_transformers"):
        assert heavy not in sys.modules


def test_embedder_fallback_dim_and_determinism() -> None:
    emb = MultilingualE5Embedder()
    v1 = emb.embed("hello world", is_query=False)
    v2 = emb.embed("hello world", is_query=False)
    assert len(v1) == EMBED_DIM
    assert v1 == v2  # deterministic hashing-trick fallback


def test_hash_embedding_is_normalized() -> None:
    v = hash_embedding("the quick brown fox")
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6 or norm == 0.0


def test_write_read_fallback() -> None:
    mem = SemanticMemory(force_memory=True)
    mem.write(_rec("s1", MemoryKind.turn_summary, "I love playing cricket on weekends", 1000))
    res = mem.read(MemoryReadQuery(session_id="s1", query="cricket weekend", top_k=5))
    assert mem.backend == "memory"
    assert len(res) >= 1


def test_semantic_ranking_prefers_overlap() -> None:
    mem = SemanticMemory(force_memory=True)
    mem.write(_rec("s1", MemoryKind.turn_summary, "user feels anxious about board exams", 1000))
    mem.write(_rec("s1", MemoryKind.turn_summary, "user likes mango ice cream", 1001))
    # The hashing-trick embedding is token-exact: a query sharing the "anxious"/"exams"
    # tokens lands closer to the exam record than the dessert record.
    res = mem.read(MemoryReadQuery(session_id="s1", query="anxious about exams", top_k=2))
    assert len(res) == 2
    assert "exams" in res[0].record.text


def test_bounded_top_k() -> None:
    mem = SemanticMemory(force_memory=True)
    for i in range(12):
        mem.write(_rec("s1", MemoryKind.turn_summary, f"topic number {i}", 1000 + i))
    res = mem.read(MemoryReadQuery(session_id="s1", query="topic", top_k=3))
    assert len(res) == 3


def test_top_k_clamped_by_policy() -> None:
    mem = SemanticMemory(force_memory=True)
    for i in range(12):
        mem.write(_rec("s1", MemoryKind.turn_summary, f"topic {i}", 1000 + i))
    policy = RetrievalPolicy(max_top_k=2)
    res = mem.read(MemoryReadQuery(session_id="s1", query="topic", top_k=50), policy=policy)
    assert len(res) == 2


def test_min_score_threshold_filters() -> None:
    mem = SemanticMemory(force_memory=True)
    mem.write(_rec("s1", MemoryKind.turn_summary, "alpha beta gamma", 1000))
    # An impossibly high score floor should filter everything out.
    policy = RetrievalPolicy(min_score=0.999)
    res = mem.read(
        MemoryReadQuery(session_id="s1", query="completely unrelated zzz", top_k=5),
        policy=policy,
    )
    assert res == []


def test_kind_filter() -> None:
    mem = SemanticMemory(force_memory=True)
    mem.write(_rec("s1", MemoryKind.turn_summary, "exam stress", 1000))
    mem.write(_rec("s1", MemoryKind.preference, "likes tea", 1001))
    res = mem.read(
        MemoryReadQuery(
            session_id="s1", query="tea", kinds=[MemoryKind.preference], top_k=5
        )
    )
    assert all(r.record.kind is MemoryKind.preference for r in res)


def test_scores_in_unit_interval() -> None:
    mem = SemanticMemory(force_memory=True)
    mem.write(_rec("s1", MemoryKind.turn_summary, "hello there friend", 1000))
    res = mem.read(MemoryReadQuery(session_id="s1", query="hello friend", top_k=5))
    for sm in res:
        assert 0.0 <= sm.score <= 1.0


def test_cosine_identity() -> None:
    v = hash_embedding("same vector")
    assert cosine(v, v) > 0.99
