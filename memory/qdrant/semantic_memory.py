"""
memory/qdrant/semantic_memory.py — Semantic vector memory (Phase 12A).

The semantic tier stores embeddings of records and retrieves by vector similarity, giving the
assistant long-term semantic recall ("what did the user say about their exam stress last
week?"). It uses multilingual-e5 for embeddings — but on a CPU-only machine with no model
weights it must still work, so embedding is behind a lazy interface with a deterministic
hashing-trick fallback (:func:`memory._text.hash_embedding`).

Connection model (ENVIRONMENT requirement): **lazy-connect with numpy/in-memory fallback.**
  * On first use, try to connect to Qdrant via ``qdrant-client``.
  * If the client is missing, the server is down, or any op raises, transparently fall back
    to an in-process vector index that computes cosine similarity (numpy if present, else a
    pure-python loop). Tests pass with NO Qdrant running.
  * Retrieval is bounded by ``top_k`` and a score floor — every hit must justify itself.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Protocol, runtime_checkable

from memory._logging import get_logger
from memory._text import cosine, hash_embedding
from memory.contracts import (
    DEFAULT_RETRIEVAL_POLICY,
    MemoryKind,
    MemoryReadQuery,
    MemoryRecord,
    RetrievalPolicy,
    ScoredMemory,
)

__all__ = [
    "Embedder",
    "MultilingualE5Embedder",
    "SemanticMemory",
    "QdrantSemanticMemory",
    "EMBED_DIM",
]

log = get_logger("memory.qdrant.semantic_memory")

# multilingual-e5-small produces 384-dim embeddings; keep the fallback shape identical so a
# later swap to real weights does not change the vector contract / Qdrant collection schema.
EMBED_DIM = 384
_COLLECTION = "soulyatri_semantic"
_CONNECT_TIMEOUT = 1.0


@runtime_checkable
class Embedder(Protocol):
    """Pluggable embedding interface. Real impl = multilingual-e5; fallback = hashing trick."""

    dim: int

    def embed(self, text: str) -> list[float]: ...


class MultilingualE5Embedder:
    """Lazy multilingual-e5 embedder with a weight-free fallback.

    Attempts to load ``intfloat/multilingual-e5-small`` via ``sentence-transformers`` on first
    use. If unavailable (no weights / no GPU / offline), it falls back to a deterministic
    hashing-trick embedding so retrieval still functions and tests pass. multilingual-e5
    expects ``query:`` / ``passage:`` prefixes; we apply them for parity with the real model.
    """

    dim = EMBED_DIM

    def __init__(self, model_id: str = "intfloat/multilingual-e5-small") -> None:
        self._model_id = model_id
        self._model: Any | None = None
        self._tried = False
        self._lock = threading.Lock()

    def _ensure_model(self) -> Any | None:
        if self._tried:
            return self._model
        with self._lock:
            if self._tried:
                return self._model
            self._tried = True
            try:  # pragma: no cover - only when sentence-transformers + weights present
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_id, device="cpu")
                log.info("e5_loaded", model=self._model_id)
            except Exception as exc:
                self._model = None
                log.warning("e5_fallback_hashing", reason=type(exc).__name__)
        return self._model

    def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        prefix = "query: " if is_query else "passage: "
        model = self._ensure_model()
        if model is not None:  # pragma: no cover - needs weights
            try:
                vec = model.encode(prefix + text, normalize_embeddings=True)
                return [float(x) for x in list(vec)]
            except Exception as exc:
                log.warning("e5_encode_degraded", reason=type(exc).__name__)
        return hash_embedding(text, self.dim)


class SemanticMemory:
    """Qdrant-backed vector memory with a numpy/in-memory cosine fallback.

    Parameters
    ----------
    url:
        Qdrant URL. Defaults to ``$QDRANT_URL`` or ``http://localhost:6333``.
    embedder:
        An :class:`Embedder`. Defaults to :class:`MultilingualE5Embedder`.
    force_memory:
        If True, never attempt Qdrant (tests / offline mode).
    """

    name = "qdrant_semantic_memory"

    def __init__(
        self,
        url: str | None = None,
        *,
        embedder: Embedder | None = None,
        force_memory: bool = False,
    ) -> None:
        self._url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        self._embedder = embedder or MultilingualE5Embedder()
        self._force_memory = bool(force_memory)

        self._lock = threading.RLock()
        # Fallback index: session_id -> list[(record, vector)]
        self._mem: dict[str, list[tuple[MemoryRecord, list[float]]]] = {}

        self._client: Any | None = None
        self._connected: bool | None = None

    # ------------------------------------------------------------------
    # embedding helper
    # ------------------------------------------------------------------
    def _embed(self, text: str, *, is_query: bool = False) -> list[float]:
        emb = self._embedder
        # MultilingualE5Embedder supports the is_query kwarg; generic Embedders may not.
        try:
            return emb.embed(text, is_query=is_query)  # type: ignore[call-arg]
        except TypeError:
            return emb.embed(text)

    # ------------------------------------------------------------------
    # connection (lazy)
    # ------------------------------------------------------------------
    def _ensure_client(self) -> Any | None:
        if self._force_memory:
            return None
        if self._connected is not None:
            return self._client if self._connected else None

        with self._lock:
            if self._connected is not None:
                return self._client if self._connected else None
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams

                client = QdrantClient(url=self._url, timeout=_CONNECT_TIMEOUT)
                existing = {c.name for c in client.get_collections().collections}
                if _COLLECTION not in existing:
                    client.create_collection(
                        collection_name=_COLLECTION,
                        vectors_config=VectorParams(
                            size=self._embedder.dim, distance=Distance.COSINE
                        ),
                    )
                self._client = client
                self._connected = True
                log.info("semantic_memory_connected", backend="qdrant", url=self._url)
            except Exception as exc:
                self._client = None
                self._connected = False
                log.warning(
                    "semantic_memory_fallback_memory",
                    backend="memory",
                    reason=type(exc).__name__,
                )
        return self._client if self._connected else None

    @property
    def backend(self) -> str:
        return "qdrant" if self._ensure_client() is not None else "memory"

    def healthcheck(self) -> bool:
        client = self._ensure_client()
        if client is None:
            return False
        try:
            client.get_collections()
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
        vector = self._embed(record.text or "")
        client = self._ensure_client()
        if client is not None:
            try:
                self._write_qdrant(client, record, vector)
                log.debug(
                    "semantic_memory_write", backend="qdrant",
                    session_id=record.session_id, kind=record.kind.value,
                )
                return
            except Exception as exc:
                log.warning("semantic_memory_write_degraded", reason=type(exc).__name__)
                with self._lock:
                    self._connected = False
                    self._client = None
        self._write_memory(record, vector)
        log.debug(
            "semantic_memory_write", backend="memory",
            session_id=record.session_id, kind=record.kind.value,
        )

    def _write_qdrant(self, client: Any, record: MemoryRecord, vector: list[float]) -> None:
        from qdrant_client.models import PointStruct

        client.upsert(
            collection_name=_COLLECTION,
            points=[
                PointStruct(
                    id=record.id,
                    vector=vector,
                    payload={
                        "session_id": record.session_id,
                        "kind": record.kind.value,
                        "content": record.content,
                        "text": record.text,
                        "ts_ms": record.ts_ms,
                    },
                )
            ],
        )

    def _write_memory(self, record: MemoryRecord, vector: list[float]) -> None:
        with self._lock:
            self._mem.setdefault(record.session_id, []).append((record, vector))

    # ------------------------------------------------------------------
    # read (bounded, vector similarity)
    # ------------------------------------------------------------------
    def read(
        self, query: MemoryReadQuery, *, policy: RetrievalPolicy | None = None
    ) -> list[ScoredMemory]:
        policy = policy or DEFAULT_RETRIEVAL_POLICY
        top_k = policy.effective_top_k(query.top_k)
        qvec = self._embed(query.query or "", is_query=True)

        client = self._ensure_client()
        if client is not None:
            try:
                scored = self._read_qdrant(client, query, qvec, top_k, policy)
                log.debug(
                    "semantic_memory_read", backend="qdrant",
                    session_id=query.session_id, returned=len(scored), top_k=top_k,
                )
                return scored
            except Exception as exc:
                log.warning("semantic_memory_read_degraded", reason=type(exc).__name__)
                with self._lock:
                    self._connected = False
                    self._client = None

        scored = self._read_memory(query, qvec, top_k, policy)
        log.debug(
            "semantic_memory_read", backend="memory",
            session_id=query.session_id, returned=len(scored), top_k=top_k,
        )
        return scored

    def _read_qdrant(
        self,
        client: Any,
        query: MemoryReadQuery,
        qvec: list[float],
        top_k: int,
        policy: RetrievalPolicy,
    ) -> list[ScoredMemory]:
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        must: list[Any] = [
            FieldCondition(key="session_id", match=MatchValue(value=query.session_id))
        ]
        if query.kinds:
            must.append(
                FieldCondition(
                    key="kind", match=MatchAny(any=[k.value for k in query.kinds])
                )
            )
        hits = client.search(
            collection_name=_COLLECTION,
            query_vector=qvec,
            query_filter=Filter(must=must),
            limit=top_k,
            score_threshold=policy.min_score or None,
        )
        out: list[ScoredMemory] = []
        for hit in hits:
            payload = hit.payload or {}
            rec = MemoryRecord(
                id=str(hit.id),
                session_id=payload.get("session_id", query.session_id),
                kind=MemoryKind(payload.get("kind", MemoryKind.turn_summary.value)),
                content=payload.get("content", {}),
                text=payload.get("text", ""),
                ts_ms=int(payload.get("ts_ms", 0)),
            )
            out.append(ScoredMemory(record=rec, score=max(0.0, min(1.0, float(hit.score)))))
        return out

    def _read_memory(
        self,
        query: MemoryReadQuery,
        qvec: list[float],
        top_k: int,
        policy: RetrievalPolicy,
    ) -> list[ScoredMemory]:
        kind_set = set(query.kinds)
        with self._lock:
            entries = list(self._mem.get(query.session_id, []))
        scored: list[ScoredMemory] = []
        for rec, vec in entries:
            if kind_set and rec.kind not in kind_set:
                continue
            sim = cosine(qvec, vec)
            if sim < policy.min_score:
                continue
            scored.append(ScoredMemory(record=rec, score=sim))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------
    def clear(self, session_id: str | None = None) -> None:
        client = self._ensure_client()
        if client is not None:
            try:
                from qdrant_client.models import (
                    FieldCondition,
                    Filter,
                    FilterSelector,
                    MatchValue,
                )

                if session_id is None:
                    client.delete_collection(_COLLECTION)
                else:
                    client.delete(
                        collection_name=_COLLECTION,
                        points_selector=FilterSelector(
                            filter=Filter(
                                must=[
                                    FieldCondition(
                                        key="session_id",
                                        match=MatchValue(value=session_id),
                                    )
                                ]
                            )
                        ),
                    )
            except Exception as exc:
                log.warning("semantic_memory_clear_degraded", reason=type(exc).__name__)
        with self._lock:
            if session_id is None:
                self._mem.clear()
            else:
                self._mem.pop(session_id, None)


QdrantSemanticMemory = SemanticMemory
