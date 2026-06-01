# ASSUMPTIONS

> Working assumptions seeded at Phase 0. Each assumption that proves false should be
> promoted to an item in `docs/RISKS.md` or `docs/OPEN_QUESTIONS.md` and the affected
> decision in `docs/DECISIONS.md` revisited.

| ID | Assumption | Basis | If false → |
|---|---|---|---|
| A-001 | Moshi + Mimi can be run as the speech-native core under our open-source-only constraint. | Canonical guide §3.2, §4. | Fall back to CSM path (R-002); revisit D-002. |
| A-002 | The dev/CI environment is **CPU-only** with **no GPU** and **no Moshi/Mimi weights**. | Current machine reality (D-008). | Enable GPU/weights path; relax import-time fallbacks. |
| A-003 | All foundation code can import and pass tests on CPU without model weights. | Design intent (D-008). | Re-scope CI to a GPU runner; gate heavy tests. |
| A-004 | pydantic v2 is available and is the contract serialization layer. | `server/requirements.txt` pins `pydantic>=2.9`; env has 2.13.4. | Switch shared contracts to stdlib dataclasses only. |
| A-005 | The existing `server/` gateway + pipeline remain the baseline/fallback and are not to be broken. | Task ground truth; D-003. | Re-plan integration; treat server/ as legacy. |
| A-006 | Latency targets are **staged ambitions**, not day-one guarantees. | Canonical guide §8.1. | Re-baseline `docs/LATENCY_TARGETS.md`. |
| A-007 | Hinglish quality is primarily a **data** problem (collection, transliteration, code-switch eval), not an architecture problem. | Canonical guide §9.4, addendum C. | Revisit model-adapter fine-tuning earlier. |
| A-008 | Target transport is WebRTC + Opus via LiveKit; the current WebSocket PCM path is an acceptable bring-up substitute. | Guide §3.1; `server/main.py` WS endpoint; `docker-compose.yml` LiveKit. | Standardize transport before scaling. |
| A-009 | Redis (hot), Postgres (profile/relational), Qdrant (vector) are the memory tiers. | Guide §7.2, §11.5. Redis already in `docker-compose.yml`. | Re-select memory infra. |
| A-010 | Emotion is represented as continuous latents (V/A/D + warmth/uncertainty/pace/intensity), consistent with `server/pipeline/emotion.py`. | Guide §5.5, §9A; existing `EmotionResult`. | Re-derive emotion schema. |
| A-011 | Consent-first voice policy + watermarking (AudioSeal-class) are required before any voice-reference feature ships. | Guide §2.4, Phase 11. | Block voice features entirely. |
| A-012 | Python 3.10+ is the language baseline for all backend/domain packages. | Repo style; env Python 3.11.9. | Adjust `pyproject.toml` target. |
| A-013 | Exact model checkpoints are **not** decided on day one and are tracked as `pending-human-pin`. | Guide §5. | Pin checkpoints and update `MODEL_LOCKS.md`. |
