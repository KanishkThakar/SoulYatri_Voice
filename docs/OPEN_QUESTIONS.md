# OPEN QUESTIONS

> Per the canonical instruction: when something is unclear, **write the ambiguity here
> instead of improvising a new architecture**. Each item needs a human decision before
> the dependent work is considered final. Resolved items move to `docs/DECISIONS.md`.

| ID | Question | Why it matters | Blocks | Status |
|---|---|---|---|---|
| Q-001 | Which exact Moshi checkpoint / repo commit do we pin? | Speech-native core identity, reproducibility. | Phase 5/6 | `pending-human-pin` |
| Q-002 | Which exact Mimi version + sample-rate assumptions? | Codec token contract, chunk policy, latency. | Phase 5 | `pending-human-pin` |
| Q-003 | Where will GPU inference run (cloud region, GPU class) and when do weights land? | Determines when speech-native path can be exercised end-to-end. | Phase 5/6/16 | open |
| Q-004 | Qwen3 vs Llama 3.3 for the auxiliary text brain, and which size/quantization? | Tool/memory/moderation latency and cost. | Phase 7/12 | open |
| Q-005 | faster-whisper vs IndicConformer (or both) for auxiliary STT, and language config? | Hinglish/Hindi transcript quality for logs/memory. | Phase 7 | open |
| Q-006 | Exact emotion (SER) model + label space to standardize on. | Emotion latent schema agreement and eval. | Phase 9 | open (default in `server/pipeline/emotion.py`) |
| Q-007 | Watermarking choice (AudioSeal vs alternative) + insertion/detection policy. | Safety gate, anti-misuse. | Phase 11 | `pending-human-pin` |
| Q-008 | Numeric latency budgets per stage (capture, tokenize, TTFT, decode, network). | Converts staged ambitions into enforceable gates. | Phase 8/15 | open (see `LATENCY_TARGETS.md`) |
| Q-009 | Session-state ownership boundary between gateway (`server/`), `edge/`, and `speech/`. | Avoids duplicated/conflicting turn state. | Phase 4/6 | open |
| Q-010 | Transport: migrate WS PCM path to LiveKit WebRTC fully, and when? | Production transport stability and jitter handling. | Phase 2 | open |
| Q-011 | Postgres + Qdrant schemas and embedding (multilingual-e5) chunking policy. | Memory correctness and retrieval relevance. | Phase 12 | open |
| Q-012 | Consent token format + protected-voice list storage and review workflow. | Voice policy enforcement. | Phase 11 | open |
| Q-013 | Persona ID catalog and speaker-style embedding fusion method. | Persona continuity / brand voice. | Phase 9 | open |
| Q-014 | CI policy for GPU-dependent tests (skip vs dedicated runner). | Keeps CPU CI green while testing heavy paths. | Phase 1/15 | open (default: skip on CPU) |
| Q-015 | Do we keep both `Soulyatri_Final_*` markdowns and `final_use.md`, or designate one master? | Source-of-truth clarity. | governance | open (default: `final_use.md` is the consolidated master) |
