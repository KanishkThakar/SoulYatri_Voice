"""memory/summarizer/ — Retrieval summarizer (final_use.md §4, Phase 12B).

Owner: memory agent. Turn compression, memory summarization, relevance scoring, and
stale-memory pruning so retrieved context stays relevant and compact.
"""

from memory.summarizer.pipeline import (
    RetrievedContext,
    SummarizerPipeline,
    compress_turn,
    score_relevance,
    summarize_memories,
)

__all__ = [
    "SummarizerPipeline",
    "RetrievedContext",
    "compress_turn",
    "summarize_memories",
    "score_relevance",
]
