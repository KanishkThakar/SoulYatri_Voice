"""speech/persona/ — Emotion latent schema + persona controller (final_use.md §4, Phase 9).

Owner: speech/runtime agent. Continuous emotion conditioning (EmotionState) and
identity-preserving persona control (PersonaState) from shared/contracts.py. Uses
continuous latents, not brittle one-word tags.

Public API (Phase 9A/9B/9C):
  * 9A emotion_schema: clamp_emotion, make_emotion, blend, nudge, to/from dict/json,
    attach_to_turn_context, emotion_from_turn_context.
  * 9B controller: PersonaController, FiLMParams, film_conditioning, StyleEmbeddingProvider,
    HashStyleEmbeddingProvider.
  * 9C relationship: RelationshipStore, RelationshipProfile, RelationshipBackend,
    InMemoryRelationshipBackend.

Everything imports cleanly on a CPU-only machine with no model weights (DECISIONS.md D-008):
heavy speaker/emotion models stay behind interfaces with deterministic fallbacks.
"""

from .controller import (
    DEFAULT_PERSONA_ID,
    FILM_FEATURE_DIM,
    FiLMParams,
    HashStyleEmbeddingProvider,
    PersonaController,
    StyleEmbeddingProvider,
    film_conditioning,
)
from .emotion_schema import (
    BIPOLAR_FIELDS,
    EMOTION_FIELDS,
    UNIPOLAR_FIELDS,
    attach_to_turn_context,
    blend,
    clamp_emotion,
    clamp_unit,
    emotion_from_turn_context,
    from_dict,
    from_json,
    make_emotion,
    nudge,
    to_dict,
    to_json,
)
from .relationship import (
    InMemoryRelationshipBackend,
    RelationshipBackend,
    RelationshipProfile,
    RelationshipStore,
)

__all__ = [
    # emotion_schema (9A)
    "BIPOLAR_FIELDS",
    "UNIPOLAR_FIELDS",
    "EMOTION_FIELDS",
    "clamp_emotion",
    "clamp_unit",
    "make_emotion",
    "blend",
    "nudge",
    "to_dict",
    "from_dict",
    "to_json",
    "from_json",
    "attach_to_turn_context",
    "emotion_from_turn_context",
    # controller (9B)
    "DEFAULT_PERSONA_ID",
    "FILM_FEATURE_DIM",
    "FiLMParams",
    "film_conditioning",
    "StyleEmbeddingProvider",
    "HashStyleEmbeddingProvider",
    "PersonaController",
    # relationship (9C)
    "RelationshipProfile",
    "RelationshipBackend",
    "InMemoryRelationshipBackend",
    "RelationshipStore",
]
