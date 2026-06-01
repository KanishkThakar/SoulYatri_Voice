"""
edge/ — Edge Runtime subsystem.

Owner: edge/runtime agent (final_use.md §4).

Purpose: fast, low-latency conversational interpretation close to the user — turn
detection, emotion/speaker feature extraction, barge-in detection, session routing.
Must remain streaming and never block on full-utterance transcription before acting.
Implements the TurnState/TurnEvent, EmotionState, and RouteDecision contracts from
shared/contracts.py.
"""
