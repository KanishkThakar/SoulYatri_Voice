"""
memory/ — Memory & retrieval subsystem.

Owner: memory agent (final_use.md §4).

Purpose: durable context without poisoning the hot path. Tiered memory — Redis hot cache,
Postgres profile/relational store, Qdrant semantic vector store — plus summarization and
relevance scoring. Implements MemoryWrite / MemoryReadQuery / MemoryReadResult from
shared/contracts.py. Every retrieval must justify itself and stay bounded.
"""

from memory.contracts import (
    DEFAULT_RETRIEVAL_POLICY,
    DEFAULT_WRITE_POLICY,
    MemoryBackend,
    MemoryKind,
    MemoryReadQuery,
    MemoryReadResult,
    MemoryRecord,
    MemoryTier,
    MemoryWrite,
    RetrievalPolicy,
    ScoredMemory,
    WritePolicy,
)
from memory.store import MemoryStore

__all__ = [
    "MemoryStore",
    "MemoryRecord",
    "ScoredMemory",
    "MemoryTier",
    "WritePolicy",
    "RetrievalPolicy",
    "MemoryBackend",
    "DEFAULT_WRITE_POLICY",
    "DEFAULT_RETRIEVAL_POLICY",
    # canonical contracts (from shared)
    "MemoryKind",
    "MemoryWrite",
    "MemoryReadQuery",
    "MemoryReadResult",
]
