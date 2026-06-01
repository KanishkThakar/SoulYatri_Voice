# evals/ — Evaluation harness, observability & regression discipline (Phase 15)

> Owner: evaluation agent (final_use.md §4). Implements **Phase 15** (15A/15B/15C)
> and the **§12 evaluation matrix** dimension scorers.
>
> **Replace vibes with measured progress.** Every runtime/model change is replayed
> on fixed scenarios and gated against thresholds before merge.

## Design constraints

- **CPU-only, no weights, no GPU, no training.** Pure-Python stdlib + `pydantic`
  (via `shared/contracts.py`). No `torch` / `transformers` / `moshi` / `mimi` /
  `numpy` / `prometheus_client`. Everything imports and runs on a bare machine.
- **Deterministic.** Scenarios and scorer inputs are small JSON/data fixtures
  (transcripts + expected labels + synthetic timing), never real audio or models.
- **Injected pipeline.** The replay harness runs against an injected `PipelineFn`
  callable, so the *same* harness drives a mock here and a real edge/speech
  pipeline in CI.
- **Single source of truth.** All metrics flow through one `MetricsCollector`,
  which feeds both the Prometheus-style exposition and the regression gates.

## Module map

| Module | Phase | What it does |
|---|---|---|
| `latency/metrics.py` | 15A | Metric registry (`MetricSpec` + `METRIC_REGISTRY`) and thread-safe `MetricsCollector` with exact p50/p95/p99 aggregation. Includes per-stage latency breakdown (`stage_*_ms`). |
| `observability.py` | 15A | Structured logging (`structlog` if present, stdlib adapter otherwise), an in-memory `EventLog` hook, and a pure `render_prometheus()` text exposition (no server required). |
| `replay/harness.py` | 15B | `ReplayHarness` loads JSON scenarios and runs them through an injected `PipelineFn`, capturing timings + routing rates into the collector. Produces a JSON-serializable `ReplayReport`. |
| `replay/mock_pipeline.py` | 15B | Reference deterministic mock pipeline (no models). `make_mock_pipeline(timing_scale=…, force_route=…)` simulates regressions. |
| `replay/scenarios/*.json` | 15B | 7 fixtures: English, Hindi, Hinglish, interruptions, distress, short confirmations, noisy speech. |
| `text_metrics.py` | §12 | Shared token/char Levenshtein + WER/CER primitives. |
| `hinglish/scorer.py` | §12 | Code-switch ratio + transliteration robustness (`1 - CER`). |
| `emotion/scorer.py` | §12 | Emotion-label agreement (with confusable clusters) + continuous V/A/D agreement. |
| `audio/scorer.py` | §12 | Token-level WER intelligibility + UTMOS-like naturalness proxy. |
| `gates.py` | 15C | `RegressionGate` compares a collector snapshot against configurable `Threshold`s → pass/fail `GateReport`. Defaults from `docs/LATENCY_TARGETS.md` + §12. |
| `tests/` | DoD | pytest suite (61 tests) covering all of the above. |

## The metric registry (15A)

`METRIC_REGISTRY` covers every metric named in final_use.md §15A / §12 and
`docs/LATENCY_TARGETS.md`:

- `time_to_first_audible_ms` (TTFA), `first_token_ms`,
  `turn_end_detection_delay_ms`, `interruption_recovery_ms`
- `filler_hit_rate`, `filler_false_positive_rate`
- §12 quality: `wer`, `emotion_agreement`, `code_switch_score`, `naturalness_proxy`
- per-stage breakdown: `stage_vad_ms`, `stage_stt_ms`, `stage_llm_ms`,
  `stage_tts_ms`, `stage_codec_ms`, `stage_runtime_ms`, `stage_decoder_ms`
- stability gauge: `gpu_utilization_pct`

Each `MetricSpec` records `kind` (latency / rate / score / gauge) and
`higher_is_better`, which the regression gates use to pick floor vs ceiling
comparison automatically.

## Quick start

```python
from evals.replay.harness import ReplayHarness
from evals.replay.mock_pipeline import mock_pipeline
from evals.gates import RegressionGate
from evals.observability import render_prometheus

# 1. Replay all bundled scenarios through an injected pipeline (mock here).
harness = ReplayHarness(mock_pipeline)
report = harness.run()                 # JSON-serializable ReplayReport
print(report.route_accuracy)           # 1.0 for the reference mock

# 2. Gate the captured metrics against thresholds.
gate_report = RegressionGate().evaluate(harness.collector)
print(gate_report.summary())           # "[PASS] 10/10 gates passed"
assert gate_report.passed              # CI fails the build if this regresses

# 3. Expose Prometheus-style text (no server needed) for dashboards.
print(render_prometheus(harness.collector))
```

To plug in the **real** pipeline, implement the `PipelineFn` Protocol
(`(turn, scenario) -> PipelineOutput`) and pass it to `ReplayHarness`.

## Regression gates (15C)

`default_thresholds()` encodes the staged targets from
`docs/LATENCY_TARGETS.md`:

| Metric | Aggregate | Limit | Direction |
|---|---|---|---|
| `time_to_first_audible_ms` | p95 | 300 ms | ceiling (sub-300 ms ambition) |
| `first_token_ms` | p95 | 220 ms | ceiling (provisional, Q-008) |
| `turn_end_detection_delay_ms` | p95 | 150 ms | ceiling (provisional, Q-008) |
| `interruption_recovery_ms` | p95 | 300 ms | ceiling (low-hundreds-ms stop) |
| `filler_hit_rate` | mean | 0.80 | floor |
| `filler_false_positive_rate` | mean | 0.05 | ceiling |
| `wer` | mean | 0.30 | ceiling |
| `emotion_agreement` | mean | 0.70 | floor |
| `code_switch_score` | mean | 0.70 | floor |
| `naturalness_proxy` | mean | 0.70 | floor |

Numeric per-stage budgets remain open question **Q-008** in
`docs/LATENCY_TARGETS.md`; the limits above are explicit, overridable defaults,
not hard guarantees. A metric with no recorded samples is *skipped* (passes,
flagged) so partial runs don't false-fail.

## Structured logging hooks (DoD §3.3)

`observability.get_logger()` returns a `structlog` logger when available and a
stdlib adapter with the same `logger.info("event", key=value)` signature
otherwise (mirroring `aux/text_brain/obs.py`). `EventLog` is a bounded,
thread-safe ring buffer that also forwards to the logger; the replay harness
emits `replay_turn` / `replay_scenario` events through it.

## Running

```bash
python -c "import evals"
python -m pytest evals -q -p no:cacheprovider --timeout=60
python -m ruff check evals
```

Reports are JSON-serializable and intended to be recorded under `runs/`
(see `runs/phase-15-evals/acceptance.md`).
