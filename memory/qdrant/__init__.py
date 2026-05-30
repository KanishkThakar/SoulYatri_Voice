"""memory/qdrant/ — Semantic vector memory (final_use.md §4, Phase 12A).

Owner: memory agent. Qdrant vector store using multilingual-e5 embeddings for semantic
retrieval. Collection schema + chunking policy pending (OPEN_QUESTIONS Q-011).
"""

from memory.qdrant.semantic_memory import (
    EMBED_DIM,
    Embedder,
    MultilingualE5Embedder,
    QdrantSemanticMemory,
    SemanticMemory,
)

__all__ = [
    "SemanticMemory",
    "QdrantSemanticMemory",
    "Embedder",
    "MultilingualE5Embedder",
    "EMBED_DIM",
]
