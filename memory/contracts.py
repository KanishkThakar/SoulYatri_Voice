"""
memory/contracts.py — Memory-internal helper contracts (Phase 12).

These types build *on top of* the cross-subsystem contracts in ``shared.contracts`` and stay
strictly consistent with them. The canonical wire types — :class:`MemoryWrite`,
:class:`MemoryReadQuery`, :class:`MemoryReadResult`, :class:`MemoryKind` — are owned by
``shared/contracts.py`` (mirrored in ``docs/INTERFACES.md`` §6) and are re-exported here for
convenience. Everything else in this module is memory-subsystem-internal plumbing:

  * :class:`MemoryRecord`     — the normalized stored form of a write (tier-agnostic).
  * :class:`ScoredMemory`     — a record paired with a relevance score during retrieval.
  * :class:`WritePolicy`      — which tier(s) a given :class:`MemoryKind` lands in.
  * :class:`RetrievalPolicy`  — bounds (top_k cap, score floor, recency weighting).
  * :class:`MemoryBackend`    — the structural interface every tier implements.

CPU/no-weights rule (DECISIONS D-008): plain pydantic v2 + stdlib only. No torch /
transformers / qdrant-client / redis imports at module load — backends lazy-connect.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts import (
    MemoryKind,
    MemoryReadQuery,
    MemoryReadResult,
    MemoryWrite,
    now_ms,
)

__all__ = [
    # re-exported canonical contracts
    "MemoryKind",
    "MemoryWrite",
    "MemoryReadQuery",
    "MemoryReadResult",
    "now_ms",
    # memory-internal helpers
    "MemoryRecord",
    "ScoredMemory",
    "MemoryTier",
    "WritePolicy",
    "RetrievalPolicy",
    "DEFAULT_WRITE_POLICY",
    "DEFAULT_RETRIEVAL_POLICY",
    "MemoryBackend",
]


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
class MemoryTier(str, Enum):
    """Logical storage tiers (final_use.md Phase 12A)."""

    hot = "hot"  # Redis hot cache — recent turns, fast + bounded
    profile = "profile"  # Postgres — durable user/session profile & preferences
    semantic = "semantic"  # Qdrant — vector store for semantic recall


# ---------------------------------------------------------------------------
# Stored record
# ---------------------------------------------------------------------------
class MemoryRecord(BaseModel):
    """Normalized stored form of a :class:`MemoryWrite` (tier-agnostic).

    A :class:`MemoryWrite` carries no identity; once persisted it gets a stable ``id`` and a
    derived ``text`` projection used for relevance scoring and summarization.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    kind: MemoryKind
    content: dict = Field(default_factory=dict)
    text: str = Field(default="", description="Flattened text projection for scoring/summaries.")
    ts_ms: int = Field(default_factory=now_ms)

    @classmethod
    def from_write(cls, write: MemoryWrite, *, text: str | None = None) -> MemoryRecord:
        """Build a record from a canonical :class:`MemoryWrite`."""
        return cls(
            session_id=write.session_id,
            kind=write.kind,
            content=dict(write.content),
            text=text if text is not None else _flatten_content(write.content),
            ts_ms=write.ts_ms,
        )

    def as_item(self, score: float | None = None) -> dict:
        """Render as a ``MemoryReadResult.items`` entry (dict with optional score)."""
        item = {
            "id": self.id,
            "session_id": self.session_id,
            "kind": self.kind.value,
            "content": self.content,
            "text": self.text,
            "ts_ms": self.ts_ms,
        }
        if score is not None:
            item["score"] = round(float(score), 6)
        return item


class ScoredMemory(BaseModel):
    """A :class:`MemoryRecord` paired with its retrieval relevance score."""

    model_config = ConfigDict(extra="forbid")

    record: MemoryRecord
    score: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------
class WritePolicy(BaseModel):
    """Routes a :class:`MemoryKind` to the tiers that should persist it.

    Defaults (final_use.md Phase 12A "write/read policies"):
      * ``turn_summary`` → hot + semantic (recent recall + long-term semantic recall)
      * ``preference``   → hot + profile  (durable, also cached hot for the session)
      * ``profile``      → profile        (durable relational state)
      * ``tool_result``  → hot            (ephemeral; useful only within the session)
    """

    model_config = ConfigDict(extra="forbid")

    routes: dict[MemoryKind, list[MemoryTier]] = Field(default_factory=dict)

    def tiers_for(self, kind: MemoryKind) -> list[MemoryTier]:
        return self.routes.get(kind, [MemoryTier.hot])


class RetrievalPolicy(BaseModel):
    """Bounds every retrieval so memory never poisons the hot path.

    * ``max_top_k`` hard-caps the caller's requested ``top_k``.
    * ``min_score`` drops weakly-relevant items (every retrieval must justify itself).
    * ``recency_half_life_ms`` decays older items so fresh context wins ties.
    * ``deadline_ms`` is the soft retrieval budget; backends bail out toward fallback.
    """

    model_config = ConfigDict(extra="forbid")

    max_top_k: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_half_life_ms: int = Field(default=15 * 60 * 1000, gt=0)  # 15 min
    deadline_ms: int = Field(default=50, gt=0)

    def effective_top_k(self, requested: int) -> int:
        """Clamp the caller's ``top_k`` into ``[1, max_top_k]``."""
        return max(1, min(int(requested), self.max_top_k))


DEFAULT_WRITE_POLICY = WritePolicy(
    routes={
        MemoryKind.turn_summary: [MemoryTier.hot, MemoryTier.semantic],
        MemoryKind.preference: [MemoryTier.hot, MemoryTier.profile],
        MemoryKind.profile: [MemoryTier.profile],
        MemoryKind.tool_result: [MemoryTier.hot],
    }
)

DEFAULT_RETRIEVAL_POLICY = RetrievalPolicy()


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------
@runtime_checkable
class MemoryBackend(Protocol):
    """Structural interface every memory tier implements.

    All methods must be safe to call with *no* external service running — implementations
    lazy-connect and fall back to an in-process store. Retrieval respects ``top_k``.
    """

    name: str

    def write(self, record: MemoryRecord) -> None: ...

    def read(
        self, query: MemoryReadQuery, *, policy: RetrievalPolicy | None = None
    ) -> list[ScoredMemory]: ...

    def healthcheck(self) -> bool: ...


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _flatten_content(content: dict) -> str:
    """Best-effort flatten a content dict into a scoring/summary text projection."""
    if not content:
        return ""
    parts: list[str] = []
    for key, value in content.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}: {value}")
        elif isinstance(value, (list, tuple)):
            parts.append(f"{key}: " + ", ".join(str(v) for v in value))
        elif isinstance(value, dict):
            parts.append(f"{key}: " + _flatten_content(value))
        else:
            parts.append(f"{key}: {value}")
    return " | ".join(parts)
