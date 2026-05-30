"""edge/turn_detection/ — Turn-end prediction and streaming speech markers (final_use.md §4, Phase 4A).

Owner: edge/runtime agent. Produces speech start/end markers and turn-end candidates
without waiting for full-utterance transcripts.

* ``features.py`` — per-frame streaming feature bundle (VAD + speaker + emotion + markers).
* ``detector.py`` — streaming turn-end / endpointing detector (VAD-driven, hangover-based)
  that emits speech-start / speech-end / turn-end-candidate / turn-end-confirmed markers
  for the :class:`edge.session.turn_state.TurnStateMachine`. Lazy Silero + energy fallback.
"""
