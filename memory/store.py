"""
memory/store.py — Tiered memory facade (Phase 12A write/read policies).

:class:`MemoryStore` is the single entry point the rest of SoulYatri uses. It wires the three
tiers together and applies the :class:`WritePolicy` (which tier(s) a write lands in) and
:class:`RetrievalPolicy` (bounded, justified reads):

    store = MemoryStore()                      # all tiers, fallbacks baked in
    store.write(MemoryWrite(...))              # fan-out by kind -> tiers
    result = store.read(MemoryReadQuery(...))  # merged, deduped, bounded by top_k

Reads merge across tiers, dedupe by record id, keep the best score per record, then truncate
to the effective ``top_k`` and attach ``latency_ms`` for observability. Every external backend
lazy-connects with an in-memory fallback, so the whole store runs with NO services up.
"""

from __future__ import annotations

import time

from memory._logging import get_logger
from memory.contracts import (
    DEFAULT_RETRIEVAL_POLICY,
    DEFAULT_WRITE_POLICY,
    MemoryBackend,
    MemoryReadQuery,
    MemoryReadResult,
    MemoryRecord,
    MemoryTier,
    MemoryWrite,
    RetrievalPolicy,
    ScoredMemory,
    WritePolicy,
)
from memory.postgres.profile_store import ProfileStore
from memory.qdrant.semantic_memory import SemanticMemory
from memory.redis.hot_cache import HotCache

__all__ = ["MemoryStore"]

log = get_logger("memory.store")


class MemoryStore:
    """Facade over the hot / profile / semantic tiers with write & retrieval policies."""

    def __init__(
        self,
        *,
        hot: MemoryBackend | None = None,
        profile: MemoryBackend | None = None,
        semantic: MemoryBackend | None = None,
        write_policy: WritePolicy | None = None,
        retrieval_policy: RetrievalPolicy | None = None,
        force_memory: bool = False,
    ) -> None:
        self.hot = hot or HotCache(force_memory=force_memory)
        self.profile = profile or ProfileStore(force_memory=force_memory)
        self.semantic = semantic or SemanticMemory(force_memory=force_memory)
        self.write_policy = write_policy or DEFAULT_WRITE_POLICY
        self.retrieval_policy = retrieval_policy or DEFAULT_RETRIEVAL_POLICY

        self._tiers: dict[MemoryTier, MemoryBackend] = {
            MemoryTier.hot: self.hot,
            MemoryTier.profile: self.profile,
            MemoryTier.semantic: self.semantic,
        }

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------
    def write(self, write: MemoryWrite, *, text: str | None = None) -> MemoryRecord:
        """Persist a write into every tier its :class:`MemoryKind` routes to."""
        record = MemoryRecord.from_write(write, text=text)
        tiers = self.write_policy.tiers_for(write.kind)
        for tier in tiers:
            backend = self._tiers.get(tier)
            if backend is None:
                continue
            try:
                backend.write(record)
            except Exception as exc:  # a tier failure must not break the others
                log.warning(
                    "store_write_tier_failed", tier=tier.value, reason=type(exc).__name__
                )
        log.debug(
            "store_write", session_id=write.session_id, kind=write.kind.value,
            tiers=[t.value for t in tiers],
        )
        return record

    # ------------------------------------------------------------------
    # read (merged + bounded)
    # ------------------------------------------------------------------
    def read(
        self,
        query: MemoryReadQuery,
        *,
        policy: RetrievalPolicy | None = None,
        tiers: list[MemoryTier] | None = None,
    ) -> MemoryReadResult:
        """Merge bounded reads across tiers; dedupe by id; cap at effective ``top_k``."""
        policy = policy or self.retrieval_policy
        started = time.perf_counter()
        search_tiers = tiers or [MemoryTier.hot, MemoryTier.profile, MemoryTier.semantic]

        best: dict[str, ScoredMemory] = {}
        for tier in search_tiers:
            backend = self._tiers.get(tier)
            if backend is None:
                continue
            try:
                hits = backend.read(query, policy=policy)
            except Exception as exc:  # degrade gracefully — skip the broken tier
                log.warning(
                    "store_read_tier_failed", tier=tier.value, reason=type(exc).__name__
                )
                continue
            for sm in hits:
                prev = best.get(sm.record.id)
                if prev is None or sm.score > prev.score:
                    best[sm.record.id] = sm

        merged = sorted(best.values(), key=lambda s: s.score, reverse=True)
        top_k = policy.effective_top_k(query.top_k)
        merged = merged[:top_k]

        latency_ms = int((time.perf_counter() - started) * 1000)
        result = MemoryReadResult(
            session_id=query.session_id,
            items=[sm.record.as_item(score=sm.score) for sm in merged],
            latency_ms=latency_ms,
        )
        log.debug(
            "store_read", session_id=query.session_id, returned=len(result.items),
            top_k=top_k, latency_ms=latency_ms,
        )
        return result

    # ------------------------------------------------------------------
    # maintenance / health
    # ------------------------------------------------------------------
    def healthcheck(self) -> dict[str, bool]:
        """Per-tier health. ``False`` means that tier is on its in-memory fallback."""
        return {
            "hot": self.hot.healthcheck(),
            "profile": self.profile.healthcheck(),
            "semantic": self.semantic.healthcheck(),
        }

    def clear(self, session_id: str | None = None) -> None:
        for backend in self._tiers.values():
            clear = getattr(backend, "clear", None)
            if callable(clear):
                clear(session_id)
