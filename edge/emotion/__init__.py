"""edge/emotion/ — Streaming emotion feature extraction (final_use.md §4, Phase 4A).

Owner: edge/runtime agent. Emits the EmotionState contract (shared/contracts.py),
consistent with server/pipeline/emotion.py. wav2vec2-class SER models are loaded
lazily and behind capability checks (CPU/no-weights safe).
"""
