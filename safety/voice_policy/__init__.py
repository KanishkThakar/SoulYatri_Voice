"""safety/voice_policy/ — Consent-first voice policy layer (final_use.md §4, Phase 11B).

Owner: safety agent. Enforces consent verification, protected-voice list, admin review
workflow, and spoofing checks. Non-consensual cloning requests are blocked. Consumes the
VoiceRequest contract (shared/contracts.py).
"""

from .policy import ConsentRecord, ConsentStore, VoicePolicy

__all__ = [
    "VoicePolicy",
    "ConsentStore",
    "ConsentRecord",
]
