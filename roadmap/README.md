# SoulYatri Speech-Native Voice Roadmap (`roadmap/`)

This package holds the **planning/roadmap decision-logic tooling** for SoulYatri's
speech-native, low-latency, emotional, Hinglish voice AI, plus the property-based
and structural tests that verify it. It is a self-contained Python package: pure,
testable functions that operate on the roadmap's planning objects (phases, tracks,
gates, selection criteria, budgets, licensing records) and the human-readable
reports rendered from them.

## The harness is mocked — no GPU / model training

> **The Evaluation_Harness is fully MOCKED end-to-end and runs NO GPU or
> model-training work.** Every component in this package is import-only: it pulls
> in no GPU/training framework and never invokes a GPU model-training run
> (Requirement 4.6). The harness runs on mocked / small-sample inputs bounded by a
> documented maximum item count and **does not require any GPU model-training run**.
> The sole deliverable of this spec is a **planning artifact**, not executable
> model-training code (Requirement 12.7). The import-only / no-training guarantee is
> enforced by `roadmap/tests/test_config_smoke.py`.

## Package layout

Top-level subpackages:

| Path | Contents |
| --- | --- |
| `roadmap/models/` | Planning dataclasses — `phases.py` (Track, Phase, GateCriterion, Gate), `selection.py` (CriterionResult, GateResult, CandidateScores, SelectionOutcome), `runtime.py` (HarnessRun, EmotionFeatures, ConsentRecord, …) |
| `roadmap/reports/` | Pure Markdown/string report renderers (see [Reports](#reports)) |
| `roadmap/schemas/` | One JSON Schema document per planning model (`phase.json`, `gate.json`, `roadmap.json`, …) |
| `roadmap/data/` | Structured source data — `roadmap_data.yaml` (the roadmap) and `hinglish_map.json` (the transliteration mapping) |
| `roadmap/docs/` | Generated API/component documentation |
| `roadmap/tests/` | Property-based (Hypothesis) and structural/example (pytest) tests |

Top-level modules:

| Module | Responsibility |
| --- | --- |
| `roadmap_model.py` | The `Roadmap` aggregate and its phase-structure invariants |
| `roadmap_io.py` | `load_roadmap()` loader + `render_markdown` / `parse_markdown` round-trip |
| `licensing.py` | `LicensingRegister` — recorded licenses, compliance warnings, exclusions |
| `gate_evaluator.py` | `GateEvaluator` — fail-closed pass/fail, blocking, remediation |
| `selection_scorer.py` | `SelectionScorer` — weighted Speech-Native Core selection |
| `evaluation_harness.py` | `EvaluationHarness` (mocked) + `MockCandidate` |
| `hinglish.py` | `HinglishDataEngine` — transliteration + code-switch scoring |
| `emotion_persona.py` | `EmotionPersonaController` — V/A/D conditioning selection |
| `duplex_manager.py` | `DuplexManager` — barge-in timing + latency fallback |
| `safety_guard.py` | `SafetyGuard` — watermarking, consent gating, crisis handling |
| `budget_planner.py` | `BudgetComputePlanner` — footprints, budget ranges, scope decisions |
| `serialization.py` | `to_dict`/`from_dict` + JSON/YAML codecs for every planning object |
| `schema.py` | `validate(...)` JSON Schema validation layer |
| `docs_gen.py` | API/component documentation generator |
| `cli.py` | The `roadmap` command-line interface (see [CLI](#cli)) |
| `paths.py` | Workspace/package path constants (e.g. `ROADMAP_MD_PATH`) |
| `ROADMAP.md` | The authored narrative planning artifact |

## Loading and validating the roadmap

The roadmap is materialized from the structured data file
`roadmap/data/roadmap_data.yaml`. Use `load_roadmap()` from `roadmap.roadmap_io`:

```python
from roadmap.roadmap_io import load_roadmap

roadmap = load_roadmap()  # reads roadmap/data/roadmap_data.yaml by default
print(len(roadmap.phases), "phases;", len(roadmap.gates), "gates")
```

`load_roadmap()` performs three steps and fails loudly on any problem:

1. **Read** the YAML with `yaml.safe_load` (plain scalars/containers only).
2. **Build** the `Roadmap` aggregate via `roadmap.serialization.from_dict`, which
   runs every phase-structure invariant on construction (contiguous ordinals from
   1, unique ids, first phase `P1-baseline`, final phase speech-native, per-phase
   guide sections + compute footprint).
3. **Validate** the result against the `"roadmap"` JSON Schema via
   `roadmap.schema.validate`.

From the shell, the same load-and-validate path is exposed by the `validate` CLI
subcommand:

```bash
python -m roadmap.cli validate
```

## Reports

Every renderer under `roadmap/reports/` is a **pure string function**: it reads the
already-computed planning objects and returns Markdown. None performs I/O that
touches a GPU or runs training. Each report module and its public `render_*`
function:

| Report module | Public function | What it renders |
| --- | --- | --- |
| `gate_report` | `render_gate_report` | A launch/decision-gate report from a `GateResult` (per-criterion pass/fail, overall, blocked flag, remediation, owner + fallback). |
| `evaluation_report` | `render_evaluation_report` | The candidate-model evaluation table from `HarnessRun` records, with excluded candidates in a separate section. |
| `registers_report` | `render_conflict_register`, `render_licensing_report` | The conflict register and the licensing register (Markdown + JSON export). |
| `hinglish_coverage` | `render_coverage_report` | Per-corpus mapped/unmapped token counts and the unmapped-token review list. |
| `latency_report` | `render_latency_report` | The full-duplex p50 latency targets and mitigation options. |
| `safety_audit` | `render_safety_audit` | The consent-log and watermark-compliance safety audit. |
| `budget_report` | `render_budget_report` | LEAN/AMBITIOUS budget ranges, per-phase footprints, and scope decisions. |
| `traceability` | `render_traceability_report` | The requirement → task → test traceability matrix. |
| `property_coverage` | `render_property_coverage_report` | Coverage of the 15 numbered design properties across the test suite. |

Each report is a pure function you can call directly, for example:

```python
from roadmap.reports.latency_report import render_latency_report
from roadmap.reports.traceability import render_traceability_report
from roadmap.reports.property_coverage import render_property_coverage_report

print(render_latency_report(measured_p50_ms=275.0))
print(render_traceability_report())
print(render_property_coverage_report())
```

The `gate_report`, `evaluation_report`, `traceability`, and `property_coverage`
reports are also wired behind the CLI (see below). The `registers_report`,
`hinglish_coverage`, `latency_report`, `safety_audit`, and `budget_report`
renderers are called directly from Python because they need a register, corpus,
measurement, guard, or planner instance as input.

## CLI

The package ships a small `argparse` CLI in `roadmap/cli.py`. It runs on
fixture/default data, so every subcommand works with no required arguments, and it
is **fully mocked** (it imports no GPU/training framework and invokes no training
run). Invoke it as a module:

```bash
python -m roadmap.cli <subcommand>
```

Subcommands:

| Subcommand | Action |
| --- | --- |
| `validate` | Load the roadmap (`roadmap_io.load_roadmap`) and validate it against the phase-structure invariants and the JSON Schema. |
| `select` | Run the fully-mocked evaluate → select → gate pipeline (`evaluate_and_select`) over a built-in `MockCandidate` fixture and print the selection. |
| `gate-report` | Evaluate a gate (`--gate`, default `LEAN-DEMO`) with `GateEvaluator` and render `render_gate_report`. |
| `eval-report` | Evaluate the built-in candidate fixture with the mocked harness and render `render_evaluation_report`. |
| `trace` | Render the requirement → task → test traceability matrix (`render_traceability_report`). |
| `coverage` | Render the design-property (1–15) coverage report (`render_property_coverage_report`). |
| `render-roadmap` | Render the roadmap as Markdown (`roadmap_io.render_markdown`, YAML/`to_dict` fallback). |

Examples:

```bash
python -m roadmap.cli validate
python -m roadmap.cli select
python -m roadmap.cli gate-report --gate LEAN-DEMO
python -m roadmap.cli eval-report
python -m roadmap.cli trace
python -m roadmap.cli coverage
python -m roadmap.cli render-roadmap
```

## Running the tests

The suite combines **property-based tests** (Hypothesis) with **structural/example
tests** (plain `pytest`). The Hypothesis `roadmap` profile registered in
`roadmap/tests/conftest.py` runs **at least 100 examples** (`max_examples=100`) per
property. The 15 numbered design properties are tagged with the comment marker
`# Feature: speech-native-voice-roadmap, Property {n}: {text}`.

On Windows, use the local test-runner script. It runs `pytest` over `roadmap/tests`
in a single (non-watch) run with the Hypothesis `roadmap` profile and propagates a
non-zero exit code on failure:

```powershell
.\scripts\run_roadmap_tests.ps1
.\scripts\run_roadmap_tests.ps1 -k duplex          # forward extra pytest flags
```

The equivalent direct `pytest` command (any shell, run from the workspace root):

```bash
python -m pytest roadmap/tests -q --hypothesis-profile roadmap
```

Both run the full property + structural suite against the mocked tooling; neither
triggers any GPU or model-training run.
