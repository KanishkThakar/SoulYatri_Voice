# Phase 15 — Evaluation harness, observability & regression discipline — Acceptance

**Scope:** `evals/` only. Depends on `shared/contracts.py`. CPU-only, no GPU, no
model weights, no training. Deterministic fixtures/mocks.

**Source:** final_use.md §Phase 15 (15A/15B/15C), §12 evaluation matrix,
`docs/LATENCY_TARGETS.md`. Definition of Done: final_use.md §3.3.

---

## 1. Modules delivered

| File | Phase / §12 | Purpose |
|---|---|---|
| `evals/latency/metrics.py` | 15A | Metric registry (`MetricSpec`, `METRIC_REGISTRY`, `METRICS`, `STAGE_LATENCY_METRICS`) + thread-safe `MetricsCollector` with exact p50/p95/p99 percentile aggregation. |
| `evals/observability.py` | 15A | Structured logging (`get_logger`, `EventLog`) + pure Prometheus-style text exposition (`render_prometheus`, `render_structured_lines`, `log_snapshot`). No running Prometheus. |
| `evals/replay/harness.py` | 15B | `ReplayHarness` + scenario data model (`Scenario`, `ScenarioTurn`), injected `PipelineFn` Protocol, JSON-serializable `ReplayReport`, scenario loaders. |
| `evals/replay/mock_pipeline.py` | 15B | Deterministic reference mock pipeline + `make_mock_pipeline(timing_scale, force_route)` for regression simulation. |
| `evals/replay/scenarios/*.json` | 15B | 7 fixtures: English, Hindi, Hinglish, interruptions, distress, short confirmations, noisy speech. |
| `evals/text_metrics.py` | §12 | Shared Levenshtein + WER/CER primitives (stdlib only). |
| `evals/hinglish/scorer.py` (+ `fixtures.json`) | §12 | Code-switch ratio + transliteration robustness (`1 - CER`). |
| `evals/emotion/scorer.py` (+ `fixtures.json`) | §12 | Label agreement (confusable clusters) + continuous V/A/D agreement. |
| `evals/audio/scorer.py` (+ `fixtures.json`) | §12 | Token-level WER intelligibility + UTMOS-like naturalness proxy. |
| `evals/gates.py` | 15C | `RegressionGate`, configurable `Threshold`s, pass/fail `GateReport`; defaults from `docs/LATENCY_TARGETS.md` + §12. |
| `evals/README.md` | DoD §3.3 | Design note. |
| `evals/tests/test_*.py` | DoD §3.3 | 61 pytest tests. |

> Note: `evals/latency/metrics.py`, `evals/observability.py`,
> `evals/replay/harness.py`, `evals/text_metrics.py` and the first five scenario
> fixtures were started by a prior run; this run built on them (no duplication)
> and added the §12 scorers, regression gates, mock pipeline, two scenarios,
> fixtures, the full test suite, README, and this acceptance note.

---

## 2. Acceptance-criteria mapping

### Phase 15A — Observability ("every delay has a measurable origin")
- ✅ Metric registry includes all required metrics: `time_to_first_audible_ms`,
  `first_token_ms`, `turn_end_detection_delay_ms`, `interruption_recovery_ms`,
  `filler_hit_rate`, `filler_false_positive_rate`.
- ✅ Per-stage latency breakdown (`stage_vad_ms` … `stage_decoder_ms`) so every
  delay has a measurable origin (LATENCY_TARGETS.md engineering checklist).
- ✅ In-process collector with p50/p95/p99 (exact linear-interpolation percentile,
  matches numpy default) — `test_metrics.py`.
- ✅ Prometheus-style render helper, pure function, no server — `test_observability.py`.
- ✅ Structured logging hooks (structlog-or-stdlib) + `EventLog` ring buffer.

### Phase 15B — Replay harness
- ✅ Loads fixed JSON scenarios for all seven required categories.
- ✅ Runs them through an **injected** pipeline callable (`PipelineFn` Protocol);
  reference mock + custom-callable tests prove injection works.
- ✅ Captures timings + filler routing rates into the collector.
- ✅ Scenarios are small JSON fixtures (transcripts + expected route/labels +
  synthetic timing) — no real audio/models. Reproducible reports.

### §12 evaluation matrix — dimension scorers (real deterministic scoring)
- ✅ **code-switch** — `hinglish/scorer.py`: code-switch ratio + transliteration
  robustness over fixtures.
- ✅ **emotion** — `emotion/scorer.py`: label agreement vs intended affect +
  continuous V/A/D agreement.
- ✅ **intelligibility + naturalness** — `audio/scorer.py`: token-level WER + a
  naturalness proxy.
- ✅ All exercised on known fixtures in `test_scorers.py`.

### Phase 15C — Regression gates ("PRs can fail automatically on regressions")
- ✅ Configurable thresholds for TTFA, first-token, turn-end delay, filler
  hit/false-positive, interruption recovery, WER, emotion agreement,
  code-switch, naturalness.
- ✅ Defaults from `docs/LATENCY_TARGETS.md` (sub-300 ms first-audible ambition;
  low-hundreds-ms interruption stop).
- ✅ Produces pass/fail report; **fails on regression**. Tests cover both the
  passing path and multiple failing paths — `test_gates.py`.

### Definition of Done (final_use.md §3.3)
- ✅ code · ✅ tests (`evals/tests/`, 61 tests) · ✅ design note (`evals/README.md`)
  · ✅ structured logging hooks (`observability.get_logger` / `EventLog`)
  · ✅ acceptance result recorded here under `runs/`.

---

## 3. Representative run output

```
scenarios=7 turns=15 route_acc=1.00 intent_acc=1.00
[PASS] 10/10 gates passed
```

(Replay of all 7 bundled scenarios through the reference mock pipeline, then the
default regression gate over the captured metrics + seeded quality metrics.)

---

## 4. Final verification output

Commands run from repo root `c:\Users\mpstme.student\Downloads\SoulYatri_Voice`:

```
$ python -c "import evals"
import evals OK

$ python -m pytest evals -q -p no:cacheprovider --timeout=60
.............................................................   [100%]
61 passed in 0.48s

$ python -m ruff check evals
All checks passed!
```

- **Deadlock-free:** `--timeout=60` (pytest-timeout) enforced; suite completes in
  < 1 s.
- **Lint clean:** ruff 0.15.10, `evals/` reports no errors.
- **Import clean:** `import evals` and all submodules import on a CPU-only machine
  with no model weights.

**Status: PASS.**
