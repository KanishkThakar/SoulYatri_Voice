"""
Tests for memory/contracts.py (Phase 12).

Verifies the memory-internal helpers build on shared.contracts consistently, round-trip via
pydantic, and that the default policies match the documented write/read routing.
"""

from __future__ import annotations

import importlib
import sys

import memory.contracts as MC
import shared.contracts as SC


def test_reexports_match_shared() -> None:
    """The canonical contracts are re-exported, not redefined."""
    assert MC.MemoryWrite is SC.MemoryWrite
    assert MC.MemoryReadQuery is SC.MemoryReadQuery
    assert MC.MemoryReadResult is SC.MemoryReadResult
    assert MC.MemoryKind is SC.MemoryKind


def test_no_heavy_imports() -> None:
    importlib.import_module("memory.contracts")
    for heavy in ("torch", "transformers", "qdrant_client", "redis", "psycopg"):
        assert heavy not in sys.modules


def test_record_from_write_flattens_text() -> None:
    write = MC.MemoryWrite(
        session_id="s1",
        kind=MC.MemoryKind.preference,
        content={"language": "hinglish", "tone": "warm"},
    )
    rec = MC.MemoryRecord.from_write(write)
    assert rec.session_id == "s1"
    assert "hinglish" in rec.text
    assert "warm" in rec.text
    assert rec.id  # auto id assigned


def test_record_as_item_includes_score() -> None:
    rec = MC.MemoryRecord(session_id="s1", kind=MC.MemoryKind.profile, text="x")
    item = rec.as_item(score=0.42)
    assert item["score"] == 0.42
    assert item["session_id"] == "s1"
    assert item["kind"] == "profile"


def test_record_as_item_without_score() -> None:
    rec = MC.MemoryRecord(session_id="s1", kind=MC.MemoryKind.profile, text="x")
    assert "score" not in rec.as_item()


def test_record_roundtrip() -> None:
    rec = MC.MemoryRecord(session_id="s1", kind=MC.MemoryKind.turn_summary, text="hi", ts_ms=5)
    rebuilt = MC.MemoryRecord.model_validate(rec.model_dump())
    assert rebuilt == rec


def test_default_write_policy_routes() -> None:
    p = MC.DEFAULT_WRITE_POLICY
    assert MC.MemoryTier.hot in p.tiers_for(MC.MemoryKind.turn_summary)
    assert MC.MemoryTier.semantic in p.tiers_for(MC.MemoryKind.turn_summary)
    assert p.tiers_for(MC.MemoryKind.profile) == [MC.MemoryTier.profile]


def test_retrieval_policy_effective_top_k() -> None:
    p = MC.RetrievalPolicy(max_top_k=5)
    assert p.effective_top_k(100) == 5
    assert p.effective_top_k(3) == 3
    assert p.effective_top_k(0) == 1  # floor at 1


def test_scored_memory_bounds() -> None:
    rec = MC.MemoryRecord(session_id="s1", kind=MC.MemoryKind.profile, text="x")
    sm = MC.ScoredMemory(record=rec, score=0.5)
    assert 0.0 <= sm.score <= 1.0


def test_memory_backend_protocol_runtime_checkable() -> None:
    from memory.redis.hot_cache import HotCache

    cache = HotCache(force_memory=True)
    assert isinstance(cache, MC.MemoryBackend)
