"""speech/moshi_runtime/ — Moshi streaming speech-native inference service (final_use.md §4, Phase 6).

Owner: speech/runtime agent. Wraps Moshi as a predictable streaming service implementing
the SpeechRuntime protocol (stream_reply + cancel) with session continuity and an
interruption-aware repair path. Weights load lazily; never imported at module top level.

Public API:
  * MoshiRuntimeService / make_runtime  — Phase 6A SpeechRuntime implementation
  * SessionStore / SessionState         — Phase 6B continuity (conv/speaker/emotion state)
  * RepairController / RepairAction      — Phase 6C cancel/rollback/restart/continuation
"""

from .repair import RepairAction, RepairController, TurnControl
from .service import (
    EchoTransformBackend,
    MoshiBackend,
    MoshiRuntimeService,
    make_runtime,
)
from .session_runtime import SessionState, SessionStore, TurnRecord

__all__ = [
    "MoshiRuntimeService",
    "make_runtime",
    "EchoTransformBackend",
    "MoshiBackend",
    "SessionStore",
    "SessionState",
    "TurnRecord",
    "RepairController",
    "RepairAction",
    "TurnControl",
]
