# Dashboards & alerts (final_use.md §15A / Phase 16 monitoring)

> **Owner:** infra/SRE agent. Config-first and grounded in the metrics the server
> actually exposes from `/metrics` ([`server/utils/metrics.py`](../../server/utils/metrics.py)).
> Helper: [`infra/monitoring/prometheus.py`](prometheus.py). Scrape config:
> [`prometheus.yml`](prometheus.yml). Alert rules: [`alerts.rules.yml`](alerts.rules.yml).
> Nothing here requires a running Prometheus.

## 1. Metrics catalogue (server `/metrics`)

All series use the `soulyatri_` prefix. `infra.monitoring.SERVER_METRIC_NAMES` keeps a
machine-checkable copy (a test asserts they stay in sync with the server).

### Latency histograms (per-stage — "every delay has a measurable origin")

| Metric | Stage |
|---|---|
| `soulyatri_vad_latency_seconds` | VAD frame processing |
| `soulyatri_stt_latency_seconds` | STT transcription (aux path) |
| `soulyatri_llm_ttft_seconds` | text-brain time-to-first-token |
| `soulyatri_llm_total_latency_seconds` | text-brain total generation |
| `soulyatri_tts_latency_seconds` | TTS synthesis (fallback path) |
| `soulyatri_pipeline_e2e_latency_seconds` | speech-end → first audible (TTFA/TTFB) |
| `soulyatri_emotion_latency_seconds` | emotion feature extraction |

### Counters

| Metric | Meaning |
|---|---|
| `soulyatri_vad_speech_segments_total` | speech segments detected |
| `soulyatri_stt_transcriptions_total{language}` | transcriptions completed |
| `soulyatri_llm_requests_total` | text-brain requests |
| `soulyatri_tts_requests_total{language}` | TTS requests |
| `soulyatri_errors_total{component,error_type}` | errors by component |
| `soulyatri_filler_played_total{category}` | filler phrases played |
| `soulyatri_filler_hit_rate_total{action}` | filler-only vs pipeline turns |
| `soulyatri_barge_in_total` | barge-in events |
| `soulyatri_turn_state_transitions_total{from_state,to_state}` | state transitions |

### Gauges

| Metric | Meaning |
|---|---|
| `soulyatri_active_sessions` | live voice sessions |
| `soulyatri_active_streams` | live audio streams |

## 2. Dashboards

**Overview** — top-line health:
* p50/p95/p99 of `soulyatri_pipeline_e2e_latency_seconds` (the headline latency).
* error rate: `rate(soulyatri_errors_total[5m])`.
* `soulyatri_active_sessions` vs configured pool capacity (saturation).

**Latency breakdown** — per-stage p95 of each `*_latency_seconds` / `*_ttft_seconds`
histogram stacked, so a regression points at the offending stage.

**Conversational quality** — `filler_hit_rate`, filler false-positive proxy,
`barge_in_total`, and the `turn_state_transitions` heatmap.

**Capacity** — `active_sessions`, `active_streams`, and (from
`SessionScheduler.snapshot()` exported as app metrics) queue depth + per-worker
utilization.

## 3. Alerts

Encoded in [`alerts.rules.yml`](alerts.rules.yml); thresholds intentionally equal the
canary rollback budget in [`../deploy/release_policy.yaml`](../deploy/release_policy.yaml)
so alerting and rollout agree:

| Alert | Expr (summary) | Severity |
|---|---|---|
| `HighE2ELatencyP95` | e2e p95 > 0.45s | page |
| `HighErrorRate` | error rate > 1% | page |
| `HighLLMTTFTP95` | LLM TTFT p95 > 1s | warn |
| `SessionPoolSaturated` | sessions sustained high 10m | warn |

## 4. Why thresholds mirror the rollback policy

A single source of truth for "unhealthy" prevents the classic failure where alerts say
"fine" while a canary silently degrades (or vice-versa). The rollback evaluator
([`../deploy/rollback.py`](../deploy/rollback.py)) consumes the same numbers, so an
automated rollback and a human page are triggered by the same conditions.
