"""aux/text_brain/ — Auxiliary text reasoning (Qwen3 / Llama 3.3) (final_use.md §4, Phase 7B).

Owner: auxiliary reasoning agent. Tool plans, memory summaries, moderation summaries, and
RAG query prep with deterministic output schemas and timeouts. Served via Ollama in the
baseline (server/config.py). Never the primary conversational runtime.
"""
