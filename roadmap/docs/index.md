# `roadmap` Tooling Documentation

The `roadmap` package is a **planning artifact plus pure decision-logic tooling** for the speech-native voice roadmap. It holds the narrative plan (`roadmap/ROADMAP.md`) and the testable functions that operate on the plan's objects — phases, tracks, gates, model-selection criteria, budgets, and licensing records.

The evaluation harness is **fully mocked**: nothing in this package places work on a GPU or runs a model-training/inference job. The package's sole deliverable is a planning artifact, not executable model-training code.

These pages document **this package's own API only**, generated from live signatures and docstrings. They do not restate the `.kiro/specs/ai-training-docs/` documentation/knowledge-base workstream.

## Full API reference

- [`roadmap` API Reference](api_reference.md) — every public member on one page.

## Planning components

Each component links to its generated, per-component API page.

- [`Roadmap`](roadmap_model.md) — ordered phases, tracks, gates, conflict register + scope statements → a validated planning aggregate (unique/contiguous ordinals, `P1-baseline` first, speech-native final phase).
- [`GateEvaluator`](gate_evaluator.md) — a `Gate`, measured metric values, and a `LicensingRegister` → a `GateResult` (per-criterion pass/fail, fail-closed on missing metrics, blocked flag + one remediation per failing criterion).
- [`SelectionScorer`](selection_scorer.md) — per-candidate `CandidateScores` → a `SelectionOutcome` (`RETAIN_PHASE_1` when no candidate passes every minimum, else the highest weighted aggregate among passing candidates).
- [`EvaluationHarness`](evaluation_harness.md) — mocked candidate models → comparable `HarnessRun` records (identical metric keys/scale, per-candidate exclusion recording, reproducible within tolerance — no GPU/training run).
- [`HinglishDataEngine`](hinglish.md) — Romanized/Devanagari text → deterministic `NormalizationResult` (unmapped tokens retained + flagged) and code-switch quality scores against the benchmark pass rule.
- [`EmotionPersonaController`](emotion_persona.md) — `EmotionFeatures` → a conditioning selection (clamped V/A/D, `NEUTRAL`/`EMPATHETIC`/`STANDARD`); the turn always continues.
- [`DuplexManager`](duplex_manager.md) — simulated-clock turn events → barge-in suppression / listening transitions and latency-only fallback decisions.
- [`SafetyGuard`](safety_guard.md) — synthesized outputs + consent/crisis inputs → watermark-compliance results, consent gating with a consent log, and crisis handling.
- [`LicensingRegister`](licensing.md) — component/dataset license records → recognized-OSS validation, unresolved `ComplianceWarning`s, redistribution checks, and recorded exclusions with reasons.
- [`BudgetComputePlanner`](budget_planner.md) — per-phase compute footprints + LEAN/AMBITIOUS budget ranges → `select_scope` reduced-scope alternatives that never exceed confirmed-available compute.

## Supporting modules

- [`roadmap.models.phases`](models.phases.md) — Dataclasses for `Track`, `Phase`, `GateCriterion`, `Gate`.
- [`roadmap.models.runtime`](models.runtime.md) — Runtime dataclasses (`HarnessRun`, `EmotionFeatures`, `ConsentRecord`, `LicenseEntry`, …).
- [`roadmap.models.selection`](models.selection.md) — Selection/gate-result dataclasses plus `SELECTION_WEIGHTS` and `SELECTION_MINIMUMS`.
- [`roadmap.roadmap`](roadmap.md) — Package façade exports and the `evaluate_and_select` pipeline helper.
