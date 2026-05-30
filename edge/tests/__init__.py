"""edge/tests/ — Tests for the edge runtime (Phases 4 & 8).

Owner: edge/runtime agent. Covers the streaming feature extractor, the explicit
turn-state machine (valid/invalid transitions + timeouts), barge-in detection (timing +
false-positive bounds), short-turn classification, and speculation/handoff (no duplicate
output). All tests run on CPU with no model weights via the deterministic fallbacks.
"""
