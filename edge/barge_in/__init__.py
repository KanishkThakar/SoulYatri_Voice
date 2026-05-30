"""edge/barge_in/ — Interruption / barge-in detection (final_use.md §4, Phase 4C).

Owner: edge/runtime agent. Detects overlap while the AI is speaking and emits
cancel/repair events with bounded false positives. Mirrors server/pipeline/barge_in.py.
"""
