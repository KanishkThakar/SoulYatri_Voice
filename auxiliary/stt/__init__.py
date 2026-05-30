"""aux/stt/ — Auxiliary STT utilities (final_use.md §4, Phase 7A).

Owner: auxiliary reasoning agent. faster-whisper / IndicConformer for transcripts, logs,
search, moderation review, and fallback. Runs asynchronously; must not block the main
voice loop. Mirrors server/pipeline/stt.py.
"""
