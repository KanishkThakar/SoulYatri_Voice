"""
memory/redis/hot_cache.py — L2 hot session cache (Phase 12A).

The hot cache is the fastest, most-bounded memory tier. It holds the most recent records for
a session so the voice runtime can recall immediate context with sub-millisecond latency. It
is *not* durable — entries expire by TTL and the per-session ring is capped.

Connection model (ENVIRONMENT requirement): **lazy-connect with in-memory fallback.**
  * On first use, try to connect to Redis (``redis`` package + reachable server).
  * If the package is missing, the server is down, or any op raises, transparently fall back
    to a bounded in-process ``deque`` store. Tests therefore pass with NO external services.
  * The hot path never blocks on a dead backend: a short socket timeout is used and any
    failure flips the instance to the in-memory store for the rest of its life.

Retrieval is bounded: it returns at most ``top_k`` (clamped by :class:`RetrievalPolicy`) and
scores by recency + lexical overlap so the freshest relevant turn wins.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import Any

from memory._logging import get_logger
from memory._text import recency_weight, relevance_score
from memory.contracts import (
    DEFAULT_RETRIEVAL_POLICY,
    MemoryReadQuery,
    MemoryRecord,
    RetrievalPolicy,
    ScoredMemory,
    now_ms,
)

__all__ = ["HotCache", "RedisHotCache"]

log = get_logger("memory.redis.hot_cache")

_DEFAULT_TTL_SECONDS = 60 * 60  # 1 hour
_DEFAULT_MAX_PER_SESSION = 50
_REDIS_KEY_PREFIX = "soulyatri:hot"


class HotCache:
    """Redis-backed hot cache with a transparent in-memory fallback.

    Parameters
    ----------
    url:
        Redis URL. Defaults to ``$REDIS_URL`` or ``redis://localhost:6379/0``.
    ttl_seconds:
        Per-record TTL. Applies to both Redis (native EXPIRE) and the in-memory store
        (lazy expiry on read/write).
    max_per_session:
        Hard cap on records retained per session (bounded memory).
    connect_timeout:
        Socket timeout in seconds; keeps the hot path from blocking on a dead server.
    force_memory:
        If True, never attempt Redis (used by tests / offline mode).
    """

    name = "redis_hot_cache"

    def __init__(
        self,
        url: str | None = None,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_per_session: int = _DEFAULT_MAX_PER_SESSION,
        connect_timeout: float = 0.25,
        force_memory: bool = False,
    ) -> None:
        self._url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._ttl = int(ttl_seconds)
        self._max = int(max_per_session)
        self._connect_timeout = float(connect_timeout)
        self._force_memory = bool(force_memory)

        self._lock = threading.RLock()
        # In-memory fallback: session_id -> deque[(expiry_ms, MemoryRecord)]
        self._mem: dict[str, deque[tuple[int, MemoryRecord]]] = {}

        self._client: Any | None = None
        self._connected: bool | None = None  # None = not yet attempted

    # ------------------------------------------------------------------
    # connection (lazy)
    # ------------------------------------------------------------------
    def _ensure_client(self) -> Any | None:
        """Lazily create a Redis client. Returns the client or ``None`` (use fallback)."""
        if self._force_memory:
            return None
        if self._connected is not None:
            return self._client if self._connected else None

        with self._lock:
            if self._connected is not None:
                return self._client if self._connected else None
            try:
                import redis  # lazy import — optional dependency

                client = redis.Redis.from_url(
                    self._url,
                    socket_connect_timeout=self._connect_timeout,
                    socket_timeout=self._connect_timeout,
                    decode_responses=True,
                )
                client.ping()
                self._client = client
                self._connected = True
                log.info("hot_cache_connected", backend="redis", url=self._url)
            except Exception as exc:  # missing package OR server down OR timeout
                self._client = None
                self._connected = False
                log.warning(
                    "hot_cache_fallback_memory",
                    backend="memory",
                    reason=type(exc).__name__,
                )
        return self._client if self._connected else None

    @property
    def backend(self) -> str:
        """Resolve the active backend name (``redis`` or ``memory``) — connects lazily."""
        return "redis" if self._ensure_client() is not None else "memory"

    def healthcheck(self) -> bool:
        """True if Redis is reachable; False means the in-memory fallback is active."""
        client = self._ensure_client()
        if client is None:
            return False
        try:
            client.ping()
            return True
        except Exception:
            with self._lock:
                self._connected = False
                self._client = None
            return False

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------
    def write(self, record: MemoryRecord) -> None:
        """Persist a record into the hot cache (Redis list or in-memory ring)."""
        client = self._ensure_client()
        if client is not None:
            try:
                self._write_redis(client, record)
                log.debug(
                    "hot_cache_write", backend="redis", session_id=record.session_id,
                    kind=record.kind.value,
                )
                return
            except Exception as exc:  # degrade to memory without breaking the caller
                log.warning("hot_cache_write_degraded", reason=type(exc).__name__)
                with self._lock:
                    self._connected = False
                    self._client = None
        self._write_memory(record)
        log.debug(
            "hot_cache_write", backend="memory", session_id=record.session_id,
            kind=record.kind.value,
        )

    def _write_redis(self, client: Any, record: MemoryRecord) -> None:
        key = f"{_REDIS_KEY_PREFIX}:{record.session_id}"
        payload = json.dumps(record.model_dump())
        pipe = client.pipeline()
        pipe.lpush(key, payload)
        pipe.ltrim(key, 0, self._max - 1)
        pipe.expire(key, self._ttl)
        pipe.execute()

    def _write_memory(self, record: MemoryRecord) -> None:
        expiry = now_ms() + self._ttl * 1000
        with self._lock:
            ring = self._mem.get(record.session_id)
            if ring is None:
                ring = deque(maxlen=self._max)
                self._mem[record.session_id] = ring
            ring.appendleft((expiry, record))

    # ------------------------------------------------------------------
    # read (bounded)
    # ------------------------------------------------------------------
    def read(
        self, query: MemoryReadQuery, *, policy: RetrievalPolicy | None = None
    ) -> list[ScoredMemory]:
        """Return at most ``top_k`` (clamped) records, freshest-relevant first."""
        policy = policy or DEFAULT_RETRIEVAL_POLICY
        top_k = policy.effective_top_k(query.top_k)
        records = self._load(query.session_id)

        kinds = set(query.kinds)
        now = now_ms()
        scored: list[ScoredMemory] = []
        for rec in records:
            if kinds and rec.kind not in kinds:
                continue
            lexical = relevance_score(query.query, rec.text) if query.query else 1.0
            recency = recency_weight(rec.ts_ms, now, policy.recency_half_life_ms)
            # Hot cache prioritizes recency; blend lexical relevance in when a query exists.
            score = recency if not query.query else (0.6 * lexical + 0.4 * recency)
            if score < policy.min_score:
                continue
            scored.append(ScoredMemory(record=rec, score=min(1.0, score)))

        scored.sort(key=lambda s: s.score, reverse=True)
        result = scored[:top_k]
        log.debug(
            "hot_cache_read", backend=self.backend, session_id=query.session_id,
            candidates=len(records), returned=len(result), top_k=top_k,
        )
        return result

    def _load(self, session_id: str) -> list[MemoryRecord]:
        client = self._ensure_client()
        if client is not None:
            try:
                key = f"{_REDIS_KEY_PREFIX}:{session_id}"
                raw = client.lrange(key, 0, self._max - 1)
                return [MemoryRecord.model_validate(json.loads(r)) for r in raw]
            except Exception as exc:
                log.warning("hot_cache_read_degraded", reason=type(exc).__name__)
                with self._lock:
                    self._connected = False
                    self._client = None
        return self._load_memory(session_id)

    def _load_memory(self, session_id: str) -> list[MemoryRecord]:
        now = now_ms()
        with self._lock:
            ring = self._mem.get(session_id)
            if not ring:
                return []
            live = [(exp, rec) for (exp, rec) in ring if exp > now]
            # Lazily drop expired entries.
            if len(live) != len(ring):
                self._mem[session_id] = deque(live, maxlen=self._max)
            return [rec for (_exp, rec) in live]

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------
    def clear(self, session_id: str | None = None) -> None:
        """Clear one session (or everything) from whichever backend is active."""
        client = self._ensure_client()
        if client is not None:
            try:
                if session_id is None:
                    for key in client.scan_iter(f"{_REDIS_KEY_PREFIX}:*"):
                        client.delete(key)
                else:
                    client.delete(f"{_REDIS_KEY_PREFIX}:{session_id}")
            except Exception as exc:
                log.warning("hot_cache_clear_degraded", reason=type(exc).__name__)
        with self._lock:
            if session_id is None:
                self._mem.clear()
            else:
                self._mem.pop(session_id, None)


# Backwards/clarity alias — the class is the Redis tier with fallback baked in.
RedisHotCache = HotCache
