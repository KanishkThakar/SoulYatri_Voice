"""
Tests for memory/postgres/profile_store.py (Phase 12A).

Covers the dict fallback (NO Postgres running), upsert-by-key semantics, kind filtering,
bounded top_k, and graceful degradation.
"""

from __future__ import annotations

from memory.contracts import (
    MemoryKind,
    MemoryReadQuery,
    MemoryRecord,
    RetrievalPolicy,
)
from memory.postgres.profile_store import PostgresProfileStore, ProfileStore


def _rec(session: str, kind: MemoryKind, content: dict, text: str, ts_ms: int) -> MemoryRecord:
    return MemoryRecord(session_id=session, kind=kind, content=content, text=text, ts_ms=ts_ms)


def test_alias_same_class() -> None:
    assert PostgresProfileStore is ProfileStore


def test_fallback_backend_when_no_dsn() -> None:
    store = ProfileStore(force_memory=True)
    assert store.backend == "memory"
    assert store.healthcheck() is False


def test_write_and_read() -> None:
    store = ProfileStore(force_memory=True)
    store.write(_rec("s1", MemoryKind.profile, {"name": "Asha"}, "name Asha", 1000))
    res = store.read(MemoryReadQuery(session_id="s1", query="name", top_k=5))
    assert len(res) == 1
    assert res[0].record.content["name"] == "Asha"


def test_upsert_by_key_overwrites() -> None:
    store = ProfileStore(force_memory=True)
    store.write(
        _rec("s1", MemoryKind.preference, {"key": "lang", "value": "hi"}, "lang hi", 1000)
    )
    store.write(
        _rec("s1", MemoryKind.preference, {"key": "lang", "value": "hinglish"}, "lang hinglish", 2000)
    )
    res = store.read(
        MemoryReadQuery(session_id="s1", query="lang", kinds=[MemoryKind.preference], top_k=10)
    )
    # Upsert means only one row for (session, kind, key).
    assert len(res) == 1
    assert res[0].record.content["value"] == "hinglish"


def test_different_keys_coexist() -> None:
    store = ProfileStore(force_memory=True)
    store.write(_rec("s1", MemoryKind.preference, {"key": "lang", "value": "hi"}, "lang hi", 1000))
    store.write(
        _rec("s1", MemoryKind.preference, {"key": "tone", "value": "warm"}, "tone warm", 1001)
    )
    res = store.read(
        MemoryReadQuery(session_id="s1", query="", kinds=[MemoryKind.preference], top_k=10)
    )
    assert len(res) == 2


def test_kind_filter() -> None:
    store = ProfileStore(force_memory=True)
    store.write(_rec("s1", MemoryKind.profile, {"key": "name", "v": "Asha"}, "name", 1000))
    store.write(_rec("s1", MemoryKind.preference, {"key": "lang", "v": "hi"}, "lang", 1000))
    res = store.read(
        MemoryReadQuery(session_id="s1", query="", kinds=[MemoryKind.profile], top_k=10)
    )
    assert len(res) == 1
    assert res[0].record.kind is MemoryKind.profile


def test_bounded_top_k() -> None:
    store = ProfileStore(force_memory=True)
    for i in range(15):
        store.write(
            _rec("s1", MemoryKind.profile, {"key": f"k{i}"}, f"field {i}", 1000 + i)
        )
    policy = RetrievalPolicy(max_top_k=5)
    res = store.read(MemoryReadQuery(session_id="s1", query="", top_k=100), policy=policy)
    assert len(res) == 5


def test_clear() -> None:
    store = ProfileStore(force_memory=True)
    store.write(_rec("s1", MemoryKind.profile, {"key": "name"}, "name", 1000))
    store.clear("s1")
    assert store.read(MemoryReadQuery(session_id="s1", top_k=5)) == []
