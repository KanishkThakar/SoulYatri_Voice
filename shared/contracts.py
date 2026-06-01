"""
SoulYatri — Shared Cross-Subsystem Contracts
==============================================
Importable realization of ``docs/INTERFACES.md``.

These types are the contract every domain folder implements against. They are
intentionally dependency-light: pydantic v2 models + stdlib enums only, so the module
imports cleanly on a CPU-only machine with no model weights (see DECISIONS.md D-008).

Conventions (see docs/INTERFACES.md §0):
  * Timestamps are integer milliseconds (``ts_ms``) unless noted.
  * valence / arousal / dominance ∈ [-1, 1]; warmth / uncertainty / pace / intensity ∈ [0, 1].
  * Every model is JSON round-trippable via ``model_dump()`` / ``model_validate()``.

Consistency: ``TurnState`` values mirror ``server/pipeline/turn_state.py`` and the
``edge/session/turn_state.py`` contract from final_use.md. ``EmotionState`` is a superset
of the V/A/D dimensions produced by ``server/pipeline/emotion.py``.
"""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "now_ms",
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


def now_ms() -> int:
    """Current wall-clock time in integer milliseconds."""
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# 1. Audio domain
# ---------------------------------------------------------------------------
class AudioFrame(BaseModel):
    """A single chunk of PCM audio (docs/INTERFACES.md §1.1).

    In-process ``pcm`` holds float32 mono samples in [-1, 1]. On the wire this is
    typically carried as raw PCM16 bytes; this contract is the in-process view.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    seq: int = Field(ge=0, description="Monotonic frame index within the session.")
    pcm: list[float] = Field(default_factory=list, description="Float32 mono samples in [-1, 1].")
    sample_rate: int = Field(default=16000, gt=0, description="Sample rate in Hz.")
    ts_ms: int = Field(default_factory=now_ms, description="Capture/emit time in ms.")
    is_final: bool = Field(default=False, description="Last frame of the stream/turn.")


class CodecChunk(BaseModel):
    """Token-stream packet bridging audio and the speech-native runtime.

    Output of the Mimi tokenizer; input/output of Moshi (docs/INTERFACES.md §1.2,
    final_use.md §5 ``speech/codec/interfaces.py``).
    """

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    seq: int = Field(ge=0, description="Chunk sequence number for ordering/backpressure.")
    codec_tokens: list[int] = Field(default_factory=list, description="Discrete Mimi/RVQ tokens.")
    ts_ms: int = Field(default_factory=now_ms)
    is_final: bool = Field(default=False, description="Last chunk of the turn token stream.")
    sample_rate: int = Field(default=24000, gt=0, description="Rate the tokens decode back to.")


# ---------------------------------------------------------------------------
# 2. Turn state & events
# ---------------------------------------------------------------------------
class TurnState(str, Enum):
    """Canonical conversational states (docs/INTERFACES.md §2.1).

    Values align with ``server/pipeline/turn_state.py`` and the
    ``edge/session/turn_state.py`` contract in final_use.md §Phase-4.
    """

    idle = "idle"
    listening = "listening"
    buffering = "buffering"
    candidate_filler = "candidate_filler"
    forwarding = "forwarding"
    thinking = "thinking"
    speaking = "speaking"
    barge_in = "barge_in"
    repairing = "repairing"
    ended = "ended"


class TurnEvent(BaseModel):
    """Emitted on every turn-state transition (auditable). docs/INTERFACES.md §2.2."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    from_state: TurnState
    to_state: TurnState
    trigger: str = Field(description="What caused the transition.")
    ts_ms: int = Field(default_factory=now_ms)
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. Emotion & persona
# ---------------------------------------------------------------------------
class EmotionState(BaseModel):
    """Continuous affect latents (docs/INTERFACES.md §3.1, final_use.md §5.5 / §9A).

    Superset of the valence/arousal/dominance produced by ``server/pipeline/emotion.py``
    plus the persona control scalars (warmth, uncertainty, pace, intensity).
    """

    model_config = ConfigDict(extra="forbid")

    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    arousal: float = Field(default=0.0, ge=-1.0, le=1.0)
    dominance: float = Field(default=0.0, ge=-1.0, le=1.0)
    warmth: float = Field(default=0.5, ge=0.0, le=1.0)
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    pace: float = Field(default=0.5, ge=0.0, le=1.0, description="0 slow … 1 fast.")
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    label: str | None = Field(default=None, description="Optional discrete tag for logs.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PersonaState(BaseModel):
    """Identity-preserving conditioning attached to a turn (docs/INTERFACES.md §3.2)."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(default="default")
    speaker_style_ref: str | None = Field(
        default=None, description="Consent-gated speaker-style embedding/reference id."
    )
    emotion: EmotionState = Field(default_factory=EmotionState)
    language: str = Field(default="hinglish", description="en | hi | hinglish")


# ---------------------------------------------------------------------------
# 4. Routing & latency masking
# ---------------------------------------------------------------------------
class RouteTarget(str, Enum):
    """Where the router sends a turn (docs/INTERFACES.md §4.1)."""

    cached_filler = "cached_filler"
    full_stack = "full_stack"
    silent_wait = "silent_wait"


class RouteDecision(BaseModel):
    """Output of the local/edge router + filler subsystem (final_use.md §Phase-3)."""

    model_config = ConfigDict(extra="forbid")

    route: RouteTarget
    phrase_id: str | None = Field(default=None, description="Set when route == cached_filler.")
    intent: str = Field(default="unknown")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", description="Auditable justification.")
    emit_filler_then_forward: bool = Field(
        default=False,
        description="Latency sponge: play a filler AND forward the turn to the full stack.",
    )


class FallbackDecision(BaseModel):
    """Failover between speech-native core and classic baseline (final_use.md §Phase-13C)."""

    model_config = ConfigDict(extra="forbid")

    use_fallback: bool
    reason: str = ""
    expected_recovery_ms: int | None = None


# ---------------------------------------------------------------------------
# 6. Memory
# ---------------------------------------------------------------------------
class MemoryKind(str, Enum):
    """Kinds of memory writes (docs/INTERFACES.md §6.1, final_use.md §Phase-12)."""

    turn_summary = "turn_summary"
    preference = "preference"
    profile = "profile"
    tool_result = "tool_result"


class MemoryWrite(BaseModel):
    """A write into the tiered memory subsystem (Redis/Postgres/Qdrant)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    kind: MemoryKind
    content: dict = Field(default_factory=dict)
    ts_ms: int = Field(default_factory=now_ms)


class MemoryReadQuery(BaseModel):
    """A bounded memory retrieval request (docs/INTERFACES.md §6.2)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    query: str = ""
    kinds: list[MemoryKind] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=100)


class MemoryReadResult(BaseModel):
    """Result of a memory retrieval (docs/INTERFACES.md §6.2)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    items: list[dict] = Field(default_factory=list)
    latency_ms: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# 7. Safety & consent
# ---------------------------------------------------------------------------
class VoiceAction(str, Enum):
    """Consent-gated voice actions (docs/INTERFACES.md §7.1, final_use.md §Phase-11B)."""

    style_transfer = "style_transfer"
    voice_clone = "voice_clone"
    persona_render = "persona_render"


class VoiceRequest(BaseModel):
    """A consent-gated voice action request. Consent-first by default (DECISIONS.md D-007)."""

    model_config = ConfigDict(extra="forbid")

    voice_ref_id: str | None = None
    consent_token: str | None = None
    requested_action: VoiceAction


class ModerationDecision(BaseModel):
    """Output of the moderation gate (docs/INTERFACES.md §7.2, final_use.md §Phase-11A)."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    category: str | None = Field(default=None, description="Risk category if blocked.")
    escalate: bool = Field(default=False, description="Route to crisis / human review.")
    reason: str = ""
