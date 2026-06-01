"""
memory/postgres/profile_store.py — Profile / relational store (Phase 12A).

Durable user/session profile state and preferences. Unlike the hot cache this tier is meant
to survive across sessions, so writes *upsert* by ``(session_id, kind, key)`` rather than
appending — the latest preference/profile value wins.

Connection model (ENVIRONMENT requirement): **lazy-connect with dict fallback.**
  * On first use, try to connect to Postgres via ``psycopg`` (v3) using ``$DATABASE_URL``.
  * If the driver is missing, the server is down, or any op raises, transparently fall back
    to an in-process dict store. Tests pass with NO Postgres running.
  * A short connect timeout keeps the hot path from blocking on a dead server.

Read is bounded by ``top_k`` and scored by lexical relevance + recency, consistent with the
other tiers, so the retrieval contract is uniform across the subsystem.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from memory._logging import get_logger
from memory._text import recency_weight, relevance_score
from memory.contracts import (
    DEFAULT_RETRIEVAL_POLICY,
    MemoryKind,
    MemoryReadQuery,
    MemoryRecord,
    RetrievalPolicy,
    ScoredMemory,
    now_ms,
)

__all__ = ["ProfileStore", "PostgresProfileStore"]

log = get_logger("memory.postgres.profile_store")

_CONNECT_TIMEOUT = 1  # seconds


def _profile_key(record: MemoryRecord) -> str:
    """Stable upsert key: an explicit ``content['key']`` if present, else the kind."""
    key = record.content.get("key")
    if isinstance(key, str) and key:
        return key
    return record.kind.value


class ProfileStore:
    """Postgres-backed profile store with a transparent in-memory dict fallback.

    Parameters
    ----------
    dsn:
        Postgres connection string. Defaults to ``$DATABASE_URL``.
    force_memory:
        If True, never attempt Postgres (tests / offline mode).
    """

    name = "postgres_profile_store"

    def __init__(self, dsn: str | None = None, *, force_memory: bool = False) -> None:
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        self._force_memory = bool(force_memory) or not self._dsn

        self._lock = threading.RLock()
        # Fallback: session_id -> { upsert_key -> MemoryRecord }
        self._mem: dict[str, dict[str, MemoryRecord]] = {}

        self._conn: Any | None = None
        self._connected: bool | None = None

    # ------------------------------------------------------------------
    # connection (lazy)
    # ------------------------------------------------------------------
    def _ensure_conn(self) -> Any | None:
        if self._force_memory:
            return None
        if self._connected is not None:
            return self._conn if self._connected else None

        with self._lock:
            if self._connected is not None:
                return self._conn if self._connected else None
            try:
                import psycopg  # lazy import — optional dependency (psycopg v3)

                conn = psycopg.connect(self._dsn, connect_timeout=_CONNECT_TIMEOUT)
                self._init_schema(conn)
                self._conn = conn
                self._connected = True
                log.info("profile_store_connected", backend="postgres")
            except Exception as exc:
                self._conn = None
                self._connected = False
                log.warning(
                    "profile_store_fallback_memory",
                    backend="memory",
                    reason=type(exc).__name__,
                )
        return self._conn if self._connected else None

    @staticmethod
    def _init_schema(conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_profile (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL,
                    kind        TEXT NOT NULL,
                    upsert_key  TEXT NOT NULL,
                    content     JSONB NOT NULL,
                    text        TEXT NOT NULL DEFAULT '',
                    ts_ms       BIGINT NOT NULL,
                    UNIQUE (session_id, kind, upsert_key)
                )
                """
            )
        conn.commit()

    @property
    def backend(self) -> str:
        return "postgres" if self._ensure_conn() is not None else "memory"

    def healthcheck(self) -> bool:
        conn = self._ensure_conn()
        if conn is None:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception:
            with self._lock:
                self._connected = False
                self._conn = None
            return False

    # ------------------------------------------------------------------
    # write (upsert)
    # ------------------------------------------------------------------
    def write(self, record: MemoryRecord) -> None:
        conn = self._ensure_conn()
        if conn is not None:
            try:
                self._write_pg(conn, record)
                log.debug(
                    "profile_store_write", backend="postgres",
                    session_id=record.session_id, kind=record.kind.value,
                )
                return
            except Exception as exc:
                log.warning("profile_store_write_degraded", reason=type(exc).__name__)
                with self._lock:
                    self._connected = False
                    self._conn = None
        self._write_memory(record)
        log.debug(
            "profile_store_write", backend="memory",
            session_id=record.session_id, kind=record.kind.value,
        )

    def _write_pg(self, conn: Any, record: MemoryRecord) -> None:
        key = _profile_key(record)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memory_profile
                    (id, session_id, kind, upsert_key, content, text, ts_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, kind, upsert_key) DO UPDATE SET
                    content = EXCLUDED.content,
                    text    = EXCLUDED.text,
                    ts_ms   = EXCLUDED.ts_ms,
                    id      = EXCLUDED.id
                """,
                (
                    record.id,
                    record.session_id,
                    record.kind.value,
                    key,
                    json.dumps(record.content),
                    record.text,
                    record.ts_ms,
                ),
            )
        conn.commit()

    def _write_memory(self, record: MemoryRecord) -> None:
        key = _profile_key(record)
        with self._lock:
            bucket = self._mem.setdefault(record.session_id, {})
            bucket[f"{record.kind.value}:{key}"] = record

    # ------------------------------------------------------------------
    # read (bounded)
    # ------------------------------------------------------------------
    def read(
        self, query: MemoryReadQuery, *, policy: RetrievalPolicy | None = None
    ) -> list[ScoredMemory]:
        policy = policy or DEFAULT_RETRIEVAL_POLICY
        top_k = policy.effective_top_k(query.top_k)
        records = self._load(query.session_id, query.kinds)

        now = now_ms()
        scored: list[ScoredMemory] = []
        for rec in records:
            lexical = relevance_score(query.query, rec.text) if query.query else 1.0
            recency = recency_weight(rec.ts_ms, now, policy.recency_half_life_ms)
            score = lexical if query.query else recency
            # Blend a little recency so newer profile rows edge out stale ones on ties.
            score = min(1.0, 0.85 * score + 0.15 * recency)
            if score < policy.min_score:
                continue
            scored.append(ScoredMemory(record=rec, score=score))

        scored.sort(key=lambda s: s.score, reverse=True)
        result = scored[:top_k]
        log.debug(
            "profile_store_read", backend=self.backend, session_id=query.session_id,
            candidates=len(records), returned=len(result), top_k=top_k,
        )
        return result

    def _load(self, session_id: str, kinds: list[MemoryKind]) -> list[MemoryRecord]:
        conn = self._ensure_conn()
        if conn is not None:
            try:
                return self._load_pg(conn, session_id, kinds)
            except Exception as exc:
                log.warning("profile_store_read_degraded", reason=type(exc).__name__)
                with self._lock:
                    self._connected = False
                    self._conn = None
        return self._load_memory(session_id, kinds)

    def _load_pg(
        self, conn: Any, session_id: str, kinds: list[MemoryKind]
    ) -> list[MemoryRecord]:
        sql = (
            "SELECT id, session_id, kind, content, text, ts_ms "
            "FROM memory_profile WHERE session_id = %s"
        )
        params: list[Any] = [session_id]
        if kinds:
            sql += " AND kind = ANY(%s)"
            params.append([k.value for k in kinds])
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        records: list[MemoryRecord] = []
        for rid, sid, kind, content, text, ts_ms in rows:
            parsed = content if isinstance(content, dict) else json.loads(content)
            records.append(
                MemoryRecord(
                    id=rid, session_id=sid, kind=MemoryKind(kind),
                    content=parsed, text=text or "", ts_ms=int(ts_ms),
                )
            )
        return records

    def _load_memory(
        self, session_id: str, kinds: list[MemoryKind]
    ) -> list[MemoryRecord]:
        kind_set = set(kinds)
        with self._lock:
            bucket = self._mem.get(session_id, {})
            return [
                rec for rec in bucket.values()
                if not kind_set or rec.kind in kind_set
            ]

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------
    def clear(self, session_id: str | None = None) -> None:
        conn = self._ensure_conn()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    if session_id is None:
                        cur.execute("DELETE FROM memory_profile")
                    else:
                        cur.execute(
                            "DELETE FROM memory_profile WHERE session_id = %s", (session_id,)
                        )
                conn.commit()
            except Exception as exc:
                log.warning("profile_store_clear_degraded", reason=type(exc).__name__)
        with self._lock:
            if session_id is None:
                self._mem.clear()
            else:
                self._mem.pop(session_id, None)


PostgresProfileStore = ProfileStore
