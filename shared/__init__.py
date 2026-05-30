"""
SoulYatri — Shared Contracts Package
======================================
Ownership: cross-cutting (docs + all subsystems).

This package holds the *importable* realization of the central contract document
``docs/INTERFACES.md``. It is the single source of truth for cross-subsystem data
types every domain folder (``edge/``, ``speech/``, ``aux/``, ``memory/``, ``safety/``)
depends on.

Hard rule: this package MUST import cleanly on a CPU-only machine with no model
weights. No top-level imports of torch / transformers / moshi / mimi / numpy here.
"""

from .contracts import (
    AudioFrame,
    CodecChunk,
    EmotionState,
    FallbackDecision,
    MemoryKind,
    MemoryReadQuery,
    MemoryReadResult,
    MemoryWrite,
    ModerationDecision,
    PersonaState,
    RouteDecision,
    RouteTarget,
    TurnEvent,
    TurnState,
    VoiceAction,
    VoiceRequest,
)

__all__ = [
    "AudioFrame",
    "CodecChunk",
    "TurnState",
    "TurnEvent",
    "EmotionState",
    "PersonaState",
    "RouteTarget",
    "RouteDecision",
    "FallbackDecision",
    "MemoryKind",
    "MemoryWrite",
    "MemoryReadQuery",
    "MemoryReadResult",
    "VoiceAction",
    "VoiceRequest",
    "ModerationDecision",
]
