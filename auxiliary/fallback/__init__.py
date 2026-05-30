"""aux/fallback/ — Classic baseline failover orchestration (final_use.md §4, Phase 13C).

Owner: auxiliary reasoning agent. Decides when to route to the classic STT→LLM→TTS
baseline (the existing server/ pipeline) and emits the FallbackDecision contract
(shared/contracts.py). The baseline may ship temporarily but is never the long-term
product architecture.
"""
