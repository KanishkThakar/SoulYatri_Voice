# SOULYATRI — Expanded Execution Playbook

This document continues the prior speech-native implementation guide and expands it into an agent-executable runbook. The goal is to make each phase small enough to assign to Claude-style workers or coding agents without ambiguity.

---

# Phase 0A — Architecture freeze and decision log

## Objective
Lock the system shape before implementation starts.

## Inputs
- the finalized speech-native architecture
- GPU budget
- target regions
- target platforms
- language targets
- latency target

## Tasks
1. Write `docs/DECISIONS.md`.
2. Write `docs/ASSUMPTIONS.md`.
3. Write `docs/RISKS.md`.
4. Write `docs/OPEN_QUESTIONS.md`.
5. Freeze the stack for V1.
6. Freeze the “do not build yet” list.

## Do not start
- training
- model fine-tuning
- client UI polish
- scaling work
- safety edge cases beyond basic moderation

## Deliverable
A short architecture contract the whole repo follows.

## Exit criteria
Any agent can answer:
- what is the primary model?
- what is the fallback?
- what is the filler system?
- what is the data path?
- what is the first release scope?

---

# Phase 0B — Repo scaffold and code ownership

## Objective
Create a repo that agents can safely modify without stepping on each other.

## Recommended tree
```text
soulyatri/
  client/
  edge/
  speech/
  aux/
  memory/
  safety/
  infra/
  evals/
  training/
  docs/
  scripts/
  tests/
  runs/
```

## Tasks
1. Add formatters and linters.
2. Add pre-commit hooks.
3. Add CI.
4. Add environment templates.
5. Add secrets handling.
6. Add Dockerfiles.
7. Add service contracts.
8. Add test harnesses.

## Agent boundaries
- client agent edits only `client/`
- edge agent edits only `edge/`
- speech agent edits only `speech/`
- infra agent edits only `infra/`
- eval agent edits only `evals/`
- safety agent edits only `safety/`

## Deliverable
A repo where every folder has an owner and every file has a purpose.

## Exit criteria
- repository builds
- CI runs
- conventions are documented
- no module is “miscellaneous”

---

# Phase 1A — Audio transport foundation

## Objective
Create a stable realtime audio loop before adding intelligence.

## Input contracts
- microphone PCM frames from client
- WebRTC session metadata
- session id
- speaker id if available

## Tasks
1. Capture mic audio.
2. Apply echo cancellation.
3. Apply noise suppression.
4. Stream Opus packets.
5. Receive PCM playback.
6. Add reconnect handling.
7. Add network jitter smoothing.
8. Add roundtrip metrics.

## Files
- `client/audio/*`
- `edge/webrtc_gateway/*`
- `infra/livekit/*`

## Agent instructions
- keep frame size small
- do not batch audio too aggressively
- keep transport debugging visible in logs

## Deliverable
A stable audio call path with no model dependency.

## Exit criteria
- audio flows both directions
- reconnects work
- there are no unexplained dropouts

---

# Phase 1B — Local client speech router

## Objective
Create the tiny client-side intelligence layer.

## Why this matters
It is the first latency win. It can turn dead air into a controlled wait state.

## Components
- Silero VAD
- sherpa-onnx
- phrase bank
- retrieval index
- confidence thresholds

## Tasks
1. Build the phrase schema.
2. Build the phrase cache.
3. Build the nearest-neighbor retriever.
4. Build the local intent classifier.
5. Add logic for “play filler now”.
6. Add logic for “route to full stack”.
7. Add logic for “silent wait”.
8. Add fallback rules for low confidence.

## Phrase schema
Each phrase should carry:
- text
- transcript
- audio file path
- language
- tone
- intent
- emotion
- duration
- min confidence
- max confidence
- priority
- safety tag

## Example routing policy
- greeting detected → cached acknowledgment
- simple confirmation detected → cached short phrase
- ambiguous turn → full pipeline
- emotional distress → safe empathetic filler
- long user speech → no filler unless the turn ends

## Deliverable
A fast, deterministic router that can select a cached response.

## Exit criteria
- router selects the right class of filler
- false positives are low
- local path is clearly faster than full inference

---

# Phase 2A — Edge speech feature extraction

## Objective
Extract speech features as early as possible.

## Tasks
1. Integrate VAD.
2. Extract speaker embeddings.
3. Extract emotion vectors.
4. Detect turn boundaries.
5. Detect barge-in.
6. Normalize audio timing.
7. Produce per-turn metadata.

## Outputs
```json
{
  "session_id": "...",
  "turn_id": "...",
  "speech_started": true,
  "speech_ended": false,
  "emotion": {"valence": 0.61, "arousal": 0.32},
  "speaker_embedding_id": "spk_...",
  "barge_in": false
}
```

## Agent instructions
- keep extraction streaming
- do not require full utterances
- do not block on LLM or STT

## Exit criteria
- turn detection is reliable
- emotional features are stable enough to be useful

---

# Phase 2B — Turn management state machine

## Objective
Define how a session moves through states.

## Suggested states
- `idle`
- `listening`
- `buffering`
- `candidate_filler`
- `forwarding`
- `thinking`
- `speaking`
- `barge_in`
- `repairing`
- `ended`

## Tasks
1. define transitions
2. define guards
3. define timeouts
4. define retry behavior
5. define cancellation behavior

## Deliverable
A simple explicit state machine, not a pile of if-statements.

## Exit criteria
Every audio turn maps cleanly to a state transition.

---

# Phase 3A — Speech codec integration

## Objective
Make the audio-token bridge real.

## Tasks
1. add Mimi encode/decode
2. build token stream abstraction
3. test roundtrip reconstruction
4. benchmark token latency
5. benchmark token memory footprint
6. define chunk size

## Acceptance criteria
- codec roundtrip is intelligible
- chunking stays stable
- no hidden latency spikes

## Notes
If Mimi integration is temporarily awkward, keep SNAC or DAC as a temporary engineering fallback, but do not let that become the final architecture.

---

# Phase 3B — Semantic speech model bootstrapping

## Objective
Make Moshi the main runtime component.

## Tasks
1. load the model
2. define input token format
3. define output token format
4. define state carryover format
5. define stream interface
6. define cancellation interface
7. define repair interface

## Model responsibilities
- conversational planning
- spoken continuation
- duplex response control
- incremental generation
- interruption-aware repair

## Deliverable
A shell around the model that agents can call predictably.

## Exit criteria
- model can answer a short turn
- the interface is stable
- the stream does not deadlock

---

# Phase 4A — Auxiliary text brain

## Objective
Keep text where text is actually useful.

## Use cases
- memory compression
- RAG
- tool planning
- moderation summaries
- transcript cleanup
- dataset labeling
- offline analysis

## Tasks
1. choose primary text model
2. define prompt contract
3. define tool contract
4. define memory contract
5. define output format contract
6. define fallback behavior

## Deliverable
A text service that supports the voice runtime, not replaces it.

## Exit criteria
- tools can be called reliably
- summaries are stable
- moderation can run asynchronously

---

# Phase 4B — Response planning and speculation

## Objective
Reduce latency before speech output starts.

## Tasks
1. build speculative response planner
2. build short-turn classifier
3. build filler-vs-full-answer classifier
4. add early text drafting
5. add answer confidence scoring
6. add cancellation if speculation is wrong

## Policy
- simple turn → filler or immediate answer
- complex turn → full pipeline
- uncertain turn → brief filler + full pipeline
- emotional turn → empathetic filler + careful answer

## Deliverable
The assistant does not sit there like a potato while thinking.

## Exit criteria
- response starts earlier
- speculation errors are recoverable
- the final answer still wins

---

# Phase 5A — Emotion and persona layer

## Objective
Make the speech sound like a consistent agent.

## Tasks
1. define persona IDs
2. define style vectors
3. define emotional latents
4. define warmth / certainty / pace / intensity controls
5. map latents to generation controls
6. store state across turns

## Deliverable
A stable style controller that can vary emotion without changing identity.

## Exit criteria
- speech style changes are audible
- persona remains consistent
- user emotion influences delivery

---

# Phase 5B — Emotional memory and relationship state

## Objective
Remember the conversational relationship.

## Tasks
1. store recent emotional trajectory
2. store user preference for tone
3. store response length preference
4. store conflict / stress / calm history
5. use memory for future style shaping

## Deliverable
A memory layer that remembers how the user likes the agent to sound.

## Exit criteria
- the assistant adapts over time
- emotional continuity is preserved across turns

---

# Phase 6A — Fast acoustic decoder

## Objective
Predict fine-grained audio tokens quickly enough for realtime speech.

## Tasks
1. define decoder input contract
2. define decoder output contract
3. define chunk size
4. define cache usage
5. define batch policy
6. define quantization policy
7. define rollback policy

## Deliverable
A decoder service that is small, fast, and streaming-first.

## Exit criteria
- first chunk arrives quickly
- decoder does not become the bottleneck
- throughput is stable

---

# Phase 6B — Codec decoder and waveform playback

## Objective
Turn speech tokens into real audio.

## Tasks
1. decode codec tokens
2. reconstruct waveform
3. align chunk boundaries
4. smooth transitions
5. add crossfade logic
6. handle cutoff on interruption

## Deliverable
A clean PCM audio stream.

## Exit criteria
- playback is smooth
- transitions are not jarring
- interruptions stop the audio cleanly

---

# Phase 7A — Safety and consent gate

## Objective
Keep the system safe before any public release.

## Tasks
1. moderation on text path
2. moderation on speech path
3. consent checks
4. voice cloning restrictions
5. self-harm / crisis escalation
6. abuse logging
7. watermark hooks

## Deliverable
A policy gate that every turn passes through.

## Exit criteria
- unsafe requests are blocked
- safety decisions are auditable
- the system fails closed, not open

---

# Phase 7B — Voice misuse prevention

## Objective
Prevent the system from becoming a cheap impersonation machine.

## Tasks
1. consent verification
2. voice ownership policy
3. protected voice list
4. spoofing checks
5. admin review workflow

## Deliverable
A voice policy layer that treats cloning as a controlled feature.

## Exit criteria
- unauthorized cloning is blocked
- logs are sufficient for review

---

# Phase 8A — Memory and retrieval

## Objective
Give the assistant durable context without hurting latency.

## Tasks
1. Redis hot cache
2. PostgreSQL profile store
3. Qdrant semantic store
4. retrieval summarizer
5. turn compression
6. memory write policy
7. memory read policy

## Deliverable
A memory subsystem with predictable cost.

## Exit criteria
- retrieval is fast
- memory is relevant
- memory does not overwhelm the turn path

---

# Phase 8B — Tool use and fallback reasoning

## Objective
Let the assistant use external tools when needed.

## Tasks
1. define tool schema
2. define tool call timeout
3. define fallback chain
4. define retry policy
5. define safe tools only
6. define text brain escalation

## Deliverable
A controlled tool-using assistant, not a chaotic one.

## Exit criteria
- tools are callable
- failures degrade gracefully
- the voice pipeline stays intact

---

# Phase 9A — Observability and benchmarks

## Objective
Make latency and quality visible.

## Metrics
- first audible response time
- first token time
- turn end detection delay
- filler hit rate
- filler false-positive rate
- interruption recovery time
- STT error rate
- emotion agreement rate
- GPU utilization
- queue depth

## Tasks
1. add Prometheus metrics
2. add Grafana dashboards
3. add traces
4. add structured logs
5. add benchmark replay scripts
6. add regression thresholds

## Deliverable
A system where every bad latency event leaves a fingerprint.

## Exit criteria
- you can explain every delay
- dashboards make failures obvious

---

# Phase 9B — Evaluation harness

## Objective
Test the system against real scenarios, not vibes.

## Test sets
- English
- Hindi
- Hinglish
- code-switching
- emotional distress
- interruptions
- short confirmations
- long planning turns
- noisy environments

## Tasks
1. build replay runner
2. build transcript evaluator
3. build audio evaluator
4. build filler evaluator
5. build duplex evaluator
6. build regression diffing

## Deliverable
A repeatable evaluation loop.

## Exit criteria
- every model update can be measured
- regressions are caught before release

---

# Phase 10A — Scaling and concurrency

## Objective
Handle many simultaneous users without turning the GPU into a space heater with regrets.

## Tasks
1. define per-session resource budgets
2. define worker pools
3. define queue limits
4. define backpressure policy
5. define autoscaling thresholds
6. define region routing
7. define sticky session policy
8. define GPU fallback policy

## Deliverable
A scalable runtime that stays responsive under load.

## Exit criteria
- concurrency stays stable
- tail latency remains acceptable
- sessions do not starve each other

---

# Phase 10B — Deployment hardening

## Objective
Prepare production release.

## Tasks
1. Dockerize every service
2. pin model versions
3. pin codec versions
4. pin tool versions
5. create rollout strategy
6. create rollback strategy
7. create staging and canary environments
8. document operational runbooks

## Deliverable
A deployment system that can be operated by humans, not just hoped for.

## Exit criteria
- staging is reproducible
- rollback works
- version drift is controlled

---

# 24. Agent execution pattern

The cleanest way to use Claude or any coding agent is to feed it one phase at a time.

## Task spec format
```text
Goal:
Implement Phase 3A audio codec integration.

Scope:
Only touch speech/tokenizer and speech/codec-decoder.

Inputs:
- current architecture guide
- sample PCM input
- expected token format
- benchmark target

Deliverables:
- code
- tests
- short design note
- benchmark results

Acceptance:
- roundtrip audio works
- token stream is stable
- latency meets target
```

## Review rule
A task is not done until:
- code exists
- tests exist
- behavior matches the spec
- benchmark numbers are recorded

---

# 25. Recommended implementation order for agents

1. freeze architecture
2. scaffold repo
3. build transport
4. add client router
5. add edge features
6. add codec
7. integrate Moshi
8. integrate auxiliary text brain
9. add emotion/persona
10. add acoustic decoder
11. add waveform playback
12. add safety
13. add memory
14. add observability
15. add evaluation
16. add scaling
17. harden deployment

That order is not glamorous. It is correct. Glamour is how projects die.

