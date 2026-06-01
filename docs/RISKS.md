# RISKS

> Risk register seeded at Phase 0. Severity = Impact × Likelihood.
> Owners are role names from the `final_use.md` Section 4 ownership map.

| ID | Risk | Impact | Likelihood | Severity | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-001 | No GPU / no model weights in current env blocks running Moshi/Mimi end-to-end. | High | High | **High** | Build interfaces + CPU fallbacks now (D-008); gate heavy paths behind capability checks; pin a GPU bring-up plan in `MODEL_LOCKS.md`. | speech/runtime |
| R-002 | Moshi integration proves unstable or too heavy for target latency. | High | Med | **High** | Keep CSM as fallback speech generator behind the same `SpeechRuntime` interface; keep classic baseline (Phase 13). | speech/runtime |
| R-003 | First-audible latency misses the sub-300 ms ambition under real load. | High | Med | **High** | Staged latency gates; filler latency masking; edge VAD; warm model pools; streaming everything. | edge/runtime + infra |
| R-004 | Hinglish / code-switch quality is weak (transliteration, segmentation). | High | Med | **High** | Build consented Hinglish data moat; code-switch-aware eval; fine-tune aux STT first. | training + evals |
| R-005 | Filler subsystem misfires and answers non-trivial turns or feels robotic. | Med | Med | **Med** | Keep filler bounded, deterministic, disableable; confidence thresholds; route complex turns to full stack. | client + edge |
| R-006 | Non-consensual voice cloning / impersonation misuse. | High | Low | **High** | Consent-first voice policy, protected-voice list, admin review, watermarking + detection, audit logs. | safety |
| R-007 | Barge-in / interruption recovery is unreliable (false positives or stuck states). | Med | Med | **Med** | Explicit turn-state machine with guards/timeouts (already in `server/pipeline/turn_state.py`); barge-in hysteresis; recovery tests. | edge/runtime |
| R-008 | Memory hot path adds latency or returns stale/irrelevant context. | Med | Med | **Med** | Tiered memory (Redis/Postgres/Qdrant); bounded retrieval; summarization + stale pruning; every retrieval must justify itself. | memory |
| R-009 | Codec roundtrip (Mimi) introduces artifacts or chunk-boundary instability. | Med | Med | **Med** | Roundtrip intelligibility tests; chunk policy; benchmark jitter; SNAC/DAC as documented backup behind same interface. | speech/runtime |
| R-010 | Concurrency / scaling causes session starvation or queue collapse. | High | Med | **Med** | Per-session budgeting, backpressure, sticky sessions, batching, p50/p95/p99 load tests. | infra |
| R-011 | Architecture drift: agents reintroduce a text-first design as the core. | High | Med | **High** | Freeze in `DECISIONS.md`; PR review checklist in `AGENT_PROTOCOL.md`; shared contracts in `shared/contracts.py`. | docs + all |
| R-012 | Dependency / supply-chain risk from pinned model + package versions. | Med | Low | **Low** | Pin exact versions and commit hashes in `MODEL_LOCKS.md`; verify licenses; avoid typosquat packages. | infra + safety |
| R-013 | Breaking the existing `server/`/`client/` baseline during scaffolding. | Med | Low | **Med** | Add domain folders alongside; never modify server/ behavior in Phase 0/1; CI runs existing + new. | infra |
| R-014 | Safety moderation / crisis (self-harm) flow missing or unauditable. | High | Low | **High** | First-class moderation gate; crisis escalation; fail-closed; auditable decisions. | safety |
