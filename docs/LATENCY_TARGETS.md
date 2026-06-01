# LATENCY_TARGETS — Staged Latency Gates

> Source: `final_use.md` §8.1 (latency gates) and §13 (latency engineering).
> These are **staged targets**, not day-one guarantees. Each stage must be *measurable*
> (see `evals/latency/`) before the next ambition is claimed. Numeric per-stage budgets
> are tracked as open question Q-008 until pinned by a human.

## Definitions

| Metric | Meaning |
|---|---|
| `time_to_first_audible_ms` (TTFA) | From end-of-user-turn to first audible assistant audio. |
| `first_token_time_ms` | From turn forward to first codec token from the runtime. |
| `turn_end_detection_delay_ms` | From actual end-of-speech to detected turn end. |
| `interruption_recovery_ms` | From barge-in onset to clean output stop + recoverable state. |
| `filler_hit_rate` | Fraction of trivial turns correctly served by cached filler. |
| `filler_false_positive_rate` | Fraction of non-trivial turns wrongly served by filler. |

## Staged gates

### Gate 0 — Stable baseline (before intelligence)
- A **stable bidirectional audio path** exists (capture → transport → playback) before any
  intelligence is layered on.
- Measure: reconnect survival, jitter resilience, baseline end-to-end audio latency
  (recorded, not yet optimized).
- Owner: client + edge/runtime + infra.

### Gate 1 — Filler improvement (perceived latency)
- After the local filler / phrase-bank subsystem lands, there is a **visible improvement
  in time to first audible response** for trivial turns.
- Measure: TTFA before vs after fillers; `filler_hit_rate` up, `filler_false_positive_rate`
  bounded and low.
- Owner: client + edge/runtime.

### Gate 2 — Sub-300 ms first-audible ambition (mature near-launch)
- **Sub-300 ms class** ambition for first audible response on the mature path.
- Real compute latency target band: **~150–300 ms** for useful production quality
  (`final_use.md` §13.3).
- Perceived latency target: **under ~80 ms** feel using fillers + streaming.
- Measure: TTFA p50/p95 on representative scenarios; `first_token_time_ms`.
- Owner: speech/runtime + edge + infra.

### Gate 3 — Interruption stop (low-hundreds-ms)
- Clean interruption **stop budget in the low hundreds of milliseconds**.
- On barge-in, output stops cleanly (fade or hard-cut by policy) and the turn state
  reaches a recoverable `repairing`/`listening` state within budget.
- Measure: `interruption_recovery_ms` p50/p95; bounded false-positive barge-ins.
- Owner: edge/runtime + speech/runtime.

## Where latency comes from (engineering checklist — §13.1/§13.2)
Capture buffer · VAD delay · tokenization delay · semantic model TTFT · acoustic decoder
delay · network transit · playback buffering.

Reduce via: short audio frames · stream everything · edge VAD · keep main model warm ·
cached filler masking · KV-cache reuse · careful quantization · avoid transcoding ·
dynamic batching · no full-sentence blocking.

## Regression discipline
Every runtime/model change is replayed on fixed scenarios (English, Hindi, Hinglish,
interruptions, distress, short confirmations, noisy speech). PRs may fail automatically on
threshold regressions (`evals/` — Phase 15). Reports are recorded under `runs/`.
