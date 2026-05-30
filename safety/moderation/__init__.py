"""safety/moderation/ — Text-path and speech-path moderation gate (final_use.md §4, Phase 11A).

Owner: safety agent. Classifies risky speech, escalates crisis/self-harm, and logs abuse.
Decisions are auditable and fail-closed. Emits ModerationDecision (shared/contracts.py).
"""

from .gate import (
    CRISIS_GUIDANCE,
    ModerationConfig,
    ModerationGate,
    moderate_speech,
    moderate_text,
)

__all__ = [
    "CRISIS_GUIDANCE",
    "ModerationConfig",
    "ModerationGate",
    "moderate_text",
    "moderate_speech",
]
