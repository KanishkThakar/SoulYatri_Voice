"""
speech/ — Speech-native runtime subsystem.

Owner: speech/runtime agent (final_use.md §4).

Purpose: the core of the frozen architecture — Mimi codec bridge, Moshi speech-native
runtime, fast acoustic decoder, codec decode, and emotion/persona conditioning. Consumes
codec tokens + context state (NOT text) as its primary interface. Implements the
CodecChunk / CodecBridge / SpeechRuntime contracts from shared/contracts.py and
docs/INTERFACES.md §5. Heavy models (Mimi/Moshi) load lazily and are GPU-optional.
"""
