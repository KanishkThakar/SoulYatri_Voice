"""
Tests for memory/redis/hot_cache.py (Phase 12A).

Covers hot-cache write/read with the in-memory fallback (NO Redis running), bounded top_k
retrieval, recency ordering, kind filtering, TTL expiry, and graceful degradation.
"""

from __future__ import annotations

import importlib
import sys

from memory.contracts import (
    MemoryKind,
    MemoryReadQuery,
    MemoryRecord,
    MemoryWrite,
    RetrievalPolicy,
)
from memory.redis.hot_cache import HotCache, RedisHotCache


def _rec(session: str, kind: MemoryKind, text: str, ts_ms: int) -> MemoryRecord:
    return MemoryRecord(session_id=session, kind=kind, content={"t": text}, text=text, ts_ms=ts_ms)


def test_import_clean_no_redis() -> None:
    """Module imports and constructs with no Redis package/server (in-memory fallback)."""
    importlib.import_module("memory.redis.hot_cache")
    for heavy in ("torch", "transformers", "moshi", "mimi"):
        assert heavy not in sys.modules


def test_alias_is_same_class() -> None:
    assert RedisHotCache is HotCache


def test_write_then_read_fallback() -> None:
    cache = HotCache(force_memory=True)
    cache.write(_rec("s1", MemoryKind.turn_summary, "user likes chai", 1000))
    res = cache.read(MemoryReadQuery(session_id="s1", query="", top_k=5))
    assert cache.backend == "memory"
    assert len(res) == 1
    assert res[0].record.text == "user likes chai"


def test_healthcheck_false_in_fallback() -> None:
    cache = HotCache(force_memory=True)
    assert cache.healthcheck() is False
    assert cache.backend == "memory"


def test_bounded_top_k() -> None:
    cache = HotCache(force_memory=True)
    for i in range(20):
        cache.write(_rec("s1", MemoryKind.turn_summary, f"turn {i}", 1000 + i))
    res = cache.read(MemoryReadQuery(session_id="s1", query="", top_k=3))
    assert len(res) == 3  # respects requested top_k


def test_top_k_clamped_by_policy() -> None:
    cache = HotCache(force_memory=True)
    for i in range(20):
        cache.write(_rec("s1", MemoryKind.turn_summary, f"turn {i}", 1000 + i))
    policy = RetrievalPolicy(max_top_k=4)
    # Caller asks for 100 but the policy hard-caps at 4.
    res = cache.read(MemoryReadQuery(session_id="s1", query="", top_k=100), policy=policy)
    assert len(res) == 4


def test_recency_ordering() -> None:
    cache = HotCache(force_memory=True)
    cache.write(_rec("s1", MemoryKind.turn_summary, "old", 1000))
    cache.write(_rec("s1", MemoryKind.turn_summary, "new", 9_000_000_000_000))
    res = cache.read(MemoryReadQuery(session_id="s1", query="", top_k=2))
    assert res[0].record.text == "new"  # freshest first


def test_kind_filter() -> None:
    cache = HotCache(force_memory=True)
    cache.write(_rec("s1", MemoryKind.preference, "lang hinglish", 1000))
    cache.write(_rec("s1", MemoryKind.tool_result, "weather sunny", 2000))
    res = cache.read(
        MemoryReadQuery(session_id="s1", query="", kinds=[MemoryKind.preference], top_k=5)
    )
    assert len(res) == 1
    assert res[0].record.kind is MemoryKind.preference


def test_session_isolation() -> None:
    cache = HotCache(force_memory=True)
    cache.write(_rec("s1", MemoryKind.turn_summary, "a", 1000))
    cache.write(_rec("s2", MemoryKind.turn_summary, "b", 1000))
    assert len(cache.read(MemoryReadQuery(session_id="s1", top_k=5))) == 1
    assert len(cache.read(MemoryReadQuery(session_id="s2", top_k=5))) == 1


def test_max_per_session_bound() -> None:
    cache = HotCache(force_memory=True, max_per_session=5)
    for i in range(20):
        cache.write(_rec("s1", MemoryKind.turn_summary, f"t{i}", 1000 + i))
    res = cache.read(MemoryReadQuery(session_id="s1", query="", top_k=100))
    assert len(res) == 5  # ring buffer bounded


def test_ttl_expiry() -> None:
    # ttl_seconds=0 -> everything is immediately stale on read.
    cache = HotCache(force_memory=True, ttl_seconds=0)
    cache.write(_rec("s1", MemoryKind.turn_summary, "ephemeral", 1000))
    res = cache.read(MemoryReadQuery(session_id="s1", query="", top_k=5))
    assert res == []


def test_query_lexical_match() -> None:
    cache = HotCache(force_memory=True)
    cache.write(_rec("s1", MemoryKind.turn_summary, "user is stressed about exams", 5000))
    cache.write(_rec("s1", MemoryKind.turn_summary, "user enjoys cricket", 5001))
    # Query shares the "exams"/"stressed" tokens with the first record (lexical scorer is
    # token-exact, not stemmed) so it outranks the unrelated cricket record.
    res = cache.read(MemoryReadQuery(session_id="s1", query="stressed exams", top_k=1))
    assert len(res) == 1
    assert "exams" in res[0].record.text


def test_clear_session() -> None:
    cache = HotCache(force_memory=True)
    cache.write(_rec("s1", MemoryKind.turn_summary, "x", 1000))
    cache.clear("s1")
    assert cache.read(MemoryReadQuery(session_id="s1", top_k=5)) == []


def test_write_via_memory_write_record_roundtrip() -> None:
    """A record built from the canonical MemoryWrite stores and reads back."""
    cache = HotCache(force_memory=True)
    write = MemoryWrite(
        session_id="s1", kind=MemoryKind.preference, content={"language": "hinglish"}
    )
    rec = MemoryRecord.from_write(write)
    cache.write(rec)
    res = cache.read(MemoryReadQuery(session_id="s1", query="language", top_k=5))
    assert len(res) == 1
    assert res[0].record.content["language"] == "hinglish"
