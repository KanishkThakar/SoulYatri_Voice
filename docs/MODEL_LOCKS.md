# MODEL_LOCKS — Model & Artifact Manifest

> **Purpose (final_use.md §5):** pin exact upstream repositories, model IDs, commit
> hashes, licenses, and local storage paths for every downloaded dependency.
>
> **Rule:** If an exact checkpoint is not decided yet, the placeholder row still goes in
> here with status `pending-human-pin`. No artifact is considered final until its row is
> fully filled and a human has confirmed the pin.
>
> **Environment note (D-008):** the current dev/CI environment is **CPU-only with no model
> weights**. Nothing in this manifest may be imported at module top-level in `shared/` or
> the scaffold packages. Weights are loaded lazily, behind capability checks, only where a
> runtime/service actually needs them.

## Status legend
- `pending-human-pin` — role frozen, exact checkpoint/version not yet chosen by a human.
- `pinned` — exact ID + commit/hash + license + local path recorded and confirmed.
- `present-in-baseline` — already referenced by the existing `server/` baseline config.

## Core speech-native stack

| Artifact | Intended use | Repo / Model ID | Commit / Version | License | Local path | Sample-rate / notes | Status |
|---|---|---|---|---|---|---|---|
| Mimi | Main neural speech codec (waveform ↔ codec tokens) | _TBD_ | _TBD_ | _TBD_ | `models/mimi/` | pin model card, version, sample-rate assumptions, codebook/RVQ layout | `pending-human-pin` |
| Moshi | Main speech-native runtime (speech-in/out, full-duplex) | _TBD_ | _TBD_ | _TBD_ | `models/moshi/` | pin exact checkpoint / repo commit; record context window + streaming config | `pending-human-pin` |
| CSM | Fallback / reference speech generation (RVQ audio codes) | _TBD_ | _TBD_ | _TBD_ | `models/csm/` | record where and why used (fallback, synthetic data, quality ref) | `pending-human-pin` |
| sherpa-onnx | Tiny client helper (ASR/KWS/intent routing/filler trigger) | _TBD_ | _TBD_ | _TBD_ | `client/models/sherpa/` | pin runtime package + model assets | `pending-human-pin` |

## Edge feature + fallback stack

| Artifact | Intended use | Repo / Model ID | Commit / Version | License | Local path | Notes | Status |
|---|---|---|---|---|---|---|---|
| Silero VAD | Voice activity detection (speech start/end gating) | snakers4/silero-vad | `silero-vad>=5.1` (pin commit) | MIT | `models/silero_vad/` | record threshold defaults; used in `server/pipeline/vad.py` | `present-in-baseline` |
| faster-whisper | Auxiliary STT (transcripts, logging, retrieval, moderation, fallback) | SYSTRAN/faster-whisper | `faster-whisper>=1.1.0` (pin model size) | MIT (code) | `models/whisper/` | record chosen size + language config; default `small` in `server/config.py` | `present-in-baseline` |
| IndicConformer (or equiv.) | Indic STT fallback (Hindi/Hinglish) | AI4Bharat | _TBD_ | _TBD_ | `models/indic_conformer/` | record Hindi/Hinglish evaluation plan | `pending-human-pin` |
| ECAPA-TDNN | Speaker embeddings (192-dim) | speechbrain/spkrec-ecapa-voxceleb | pin commit | Apache-2.0 | `models/speaker_encoder/` | dimensionality = 192; used in `server/pipeline/speaker.py` | `present-in-baseline` |
| wav2vec2 SER | Emotion encoder (affect extraction) | ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition | pin commit | _TBD_ | `models/emotion/` | record label space; default in `server/config.py` / `server/pipeline/emotion.py` | `present-in-baseline` |

## Auxiliary reasoning + memory stack

| Artifact | Intended use | Repo / Model ID | Commit / Version | License | Local path | Notes | Status |
|---|---|---|---|---|---|---|---|
| Qwen3 or Llama 3.3 | Auxiliary text brain (tools, memory compression, moderation summaries) | _TBD_ | _TBD_ | _TBD_ | served via Ollama | record quantization / serving plan; default `qwen3:8b` via Ollama in `server/config.py` | `pending-human-pin` |
| multilingual-e5 | Memory retrieval embeddings | intfloat/multilingual-e5-* | _TBD_ | MIT | `models/e5/` | record chunking policy + dimensionality | `pending-human-pin` |
| Redis | Hot session cache (L2) | redis | `7-alpine` (compose) | BSD-3 / RSALv2 | container | versions + key schema | `present-in-baseline` |
| Postgres | Profile / relational memory | postgres | _TBD_ | PostgreSQL License | container | versions + schema | `pending-human-pin` |
| Qdrant | Vector store (semantic memory) | qdrant/qdrant | _TBD_ | Apache-2.0 | container | versions + collection schema | `pending-human-pin` |

## Safety stack

| Artifact | Intended use | Repo / Model ID | Commit / Version | License | Local path | Notes | Status |
|---|---|---|---|---|---|---|---|
| AudioSeal (or equiv.) | Synthesized-audio watermark insertion + detection | facebookresearch/audioseal | _TBD_ | _TBD_ | `models/watermark/` | record insertion/detection policy + thresholds | `pending-human-pin` |

## Optional / emergency fallback stack

| Artifact | Intended use | Status |
|---|---|---|
| XTTS v2 / OpenVoice | Emergency text-to-speech fallback only (Phase 13B) | `pending-human-pin` |
| whisper.cpp | CPU-only transcript fallback | `pending-human-pin` |
| SNAC / DAC | Codec backup behind the Mimi interface | `pending-human-pin` |

---

## Pinning checklist (per artifact, before status → `pinned`)
- [ ] Upstream repo URL + exact commit hash or release tag
- [ ] Model ID / card link
- [ ] License recorded and confirmed compatible with open-source-only constraint
- [ ] Local storage path under `models/` (git-ignored)
- [ ] Sample-rate / dimensionality / label-space assumptions documented
- [ ] CPU vs GPU requirement noted; lazy-load confirmed (no top-level import)
- [ ] Human sign-off recorded
