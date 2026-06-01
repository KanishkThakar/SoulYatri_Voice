"""
Tests for memory/store.py — the tiered facade (Phase 12A write/read policies).

Covers fan-out writes by kind, merged + deduped + bounded reads, per-tier health, and
graceful degradation when a tier raises.
"""

from __future__ import annotations

from memory.contracts import (
    DEFAULT_WRITE_POLICY,
    MemoryKind,
    MemoryReadQuery,
    MemoryRecord,
    MemoryTier,
    MemoryWrite,
    RetrievalPolicy,
    ScoredMemory,
)
from memory.store import MemoryStore


def _store() -> MemoryStore:
    return MemoryStore(force_memory=True)


def test_all_tiers_in_fallback() -> None:
    store = _store()
    health = store.healthcheck()
    assert health == {"hot": False, "profile": False, "semantic": False}


def test_write_policy_routes_preference_to_hot_and_profile() -> None:
    assert DEFAULT_WRITE_POLICY.tiers_for(MemoryKind.preference) == [
        MemoryTier.hot,
        MemoryTier.profile,
    ]
    assert DEFAULT_WRITE_POLICY.tiers_for(MemoryKind.profile) == [MemoryTier.profile]
    assert DEFAULT_WRITE_POLICY.tiers_for(MemoryKind.turn_summary) == [
        MemoryTier.hot,
        MemoryTier.semantic,
    ]


def test_write_and_read_merged() -> None:
    store = _store()
    store.write(
        MemoryWrite(session_id="s1", kind=MemoryKind.preference, content={"language": "hinglish"})
    )
    res = store.read(MemoryReadQuery(session_id="s1", query="language", top_k=10))
    assert res.session_id == "s1"
    assert len(res.items) >= 1
    assert any(item["content"].get("language") == "hinglish" for item in res.items)
    assert res.latency_ms >= 0


def test_read_dedupes_across_tiers() -> None:
    store = _store()
    # preference fans out to hot + profile -> same record id in two tiers.
    rec = store.write(
        MemoryWrite(session_id="s1", kind=MemoryKind.preference, content={"key": "lang", "v": "hi"})
    )
    res = store.read(MemoryReadQuery(session_id="s1", query="lang", top_k=10))
    ids = [item["id"] for item in res.items]
    assert ids.count(rec.id) == 1  # deduped despite being in two tiers


def test_read_bounded_top_k() -> None:
    store = _store()
    for i in range(30):
        store.write(
            MemoryWrite(
                session_id="s1", kind=MemoryKind.turn_summary, content={"t": f"turn {i}"}
            )
        )
    res = store.read(MemoryReadQuery(session_id="s1", query="turn", top_k=5))
    assert len(res.items) <= 5


def test_read_top_k_clamped_by_policy() -> None:
    store = MemoryStore(force_memory=True, retrieval_policy=RetrievalPolicy(max_top_k=3))
    for i in range(30):
        store.write(
            MemoryWrite(
                session_id="s1", kind=MemoryKind.turn_summary, content={"t": f"turn {i}"}
            )
        )
    res = store.read(MemoryReadQuery(session_id="s1", query="turn", top_k=100))
    assert len(res.items) <= 3


def test_items_carry_scores() -> None:
    store = _store()
    store.write(
        MemoryWrite(session_id="s1", kind=MemoryKind.turn_summary, content={"t": "exam stress"})
    )
    res = store.read(MemoryReadQuery(session_id="s1", query="exam", top_k=5))
    assert res.items
    assert "score" in res.items[0]


def test_tier_failure_degrades_gracefully() -> None:
    """If one tier's read raises, the store still returns results from the others."""

    class BoomBackend:
        name = "boom"

        def write(self, record: MemoryRecord) -> None:
            raise RuntimeError("write down")

        def read(self, query, *, policy=None) -> list[ScoredMemory]:
            raise RuntimeError("read down")

        def healthcheck(self) -> bool:
            return False

    store = MemoryStore(force_memory=True, semantic=BoomBackend())
    # turn_summary routes to hot + semantic; semantic explodes, hot still works.
    store.write(
        MemoryWrite(session_id="s1", kind=MemoryKind.turn_summary, content={"t": "hello world"})
    )
    res = store.read(MemoryReadQuery(session_id="s1", query="hello", top_k=5))
    assert len(res.items) >= 1  # survived the broken tier


def test_clear_all_tiers() -> None:
    store = _store()
    store.write(
        MemoryWrite(session_id="s1", kind=MemoryKind.preference, content={"language": "hi"})
    )
    store.clear("s1")
    res = store.read(MemoryReadQuery(session_id="s1", query="language", top_k=5))
    assert res.items == []
