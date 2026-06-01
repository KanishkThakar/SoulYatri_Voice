"""edge/session/ — Explicit turn-state machine and session routing (final_use.md §4, Phase 4B).

Owner: edge/runtime agent. Implements the TurnState/TurnEvent contracts as an explicit
state machine with guards and timeouts (no hidden if-else sprawl). Aligned with
server/pipeline/turn_state.py.
"""
