# Implementation Plan: Speech-Native Voice Roadmap

## Overview

This plan implements the deliverable defined in the design: a **planning/roadmap artifact** plus the **pure decision-logic tooling** that operates on the roadmap's planning objects, and the **property-based and structural tests** that verify them.

Implementation language is **Python**, matching the design's dataclass models and the existing `server/` codebase. Property-based tests use **Hypothesis** (`@settings(max_examples=100)` minimum), tagged with the comment format `# Feature: speech-native-voice-roadmap, Property {n}: {text}`. Structural/example tests use plain `pytest`.

All tooling lives in a self-contained `roadmap/` package at the workspace root, with tests under `roadmap/tests/` and the authored planning artifact at `roadmap/ROADMAP.md`. No task here executes a GPU model-training run — the harness is fully mocked (out of scope per Requirements 4.6, 12.4, 12.5).

File map the tasks build toward:

- `roadmap/models/phases.py` — Track, Phase, GateCriterion, Gate
- `roadmap/models/selection.py` — CriterionResult, GateResult, CandidateScores, SelectionOutcome, SELECTION_WEIGHTS, SELECTION_MINIMUMS
- `roadmap/models/runtime.py` — HarnessRun, EmotionFeatures, ConsentRecord, CloningDecision, LicenseEntry, ComplianceWarning, NormalizationResult
- `roadmap/roadmap_model.py` — Roadmap aggregate + phase-structure invariants
- `roadmap/licensing.py` — LicensingRegister
- `roadmap/gate_evaluator.py` — GateEvaluator
- `roadmap/selection_scorer.py` — SelectionScorer
- `roadmap/evaluation_harness.py` — EvaluationHarness (mocked)
- `roadmap/hinglish.py` — HinglishDataEngine (transliteration + code-switch scoring)
- `roadmap/emotion_persona.py` — EmotionPersonaController
- `roadmap/duplex_manager.py` — DuplexManager
- `roadmap/safety_guard.py` — SafetyGuard
- `roadmap/budget_planner.py` — BudgetComputePlanner
- `roadmap/ROADMAP.md` — the narrative planning artifact

## Tasks

- [ ] 1. Set up the roadmap tooling package and testing framework
  - [ ] 1.1 Create the `roadmap/` package skeleton and test configuration
    - Create `roadmap/__init__.py`, `roadmap/models/__init__.py`, and `roadmap/tests/__init__.py`
    - Add `pytest` + `hypothesis` to `server/requirements.txt` (or a `roadmap/requirements.txt`) and add a `pytest.ini`/`pyproject.toml` section pointing test discovery at `roadmap/tests`
    - Register a Hypothesis settings profile that sets `max_examples=100` as the project default and a `ROADMAP.md` path constant for tests to resolve
    - _Requirements: 12.7_
  - [ ]* 1.2 Add a configuration smoke test
    - Assert the Hypothesis default profile runs at least 100 examples and that the harness module is import-only (never invokes a GPU/training run)
    - _Requirements: 4.6_

- [ ] 2. Implement phase, track, and gate data models
  - [ ] 2.1 Implement `Track`, `Phase`, `GateCriterion`, and `Gate` dataclasses in `roadmap/models/phases.py`
    - `Phase` carries `ordinal`, `id`, `track`, `title`, `is_speech_native`, `guide_sections` (>=1), `compute_min_gpu_class`, `compute_min_vram_gb`
    - `GateCriterion` carries `metric_name`, `threshold`, `operator` in {`<=`,`<`,`>=`,`>`,`==`}; `Gate` carries `id`, `kind`, entry/exit criteria, single `owner_role`, `fallback_action`
    - _Requirements: 1.1, 1.4, 9.1_
  - [ ]* 2.2 Write unit tests for phase/gate construction and field validation
    - Cover operator set, required guide-section presence, and compute-footprint fields
    - _Requirements: 1.1, 1.4_

- [ ] 3. Implement gate-result and model-selection data models
  - [ ] 3.1 Implement `CriterionResult`, `GateResult`, `CandidateScores`, `SelectionOutcome` plus `SELECTION_WEIGHTS` and `SELECTION_MINIMUMS` in `roadmap/models/selection.py`
    - Encode the six weighted criteria (weights summing to 100) and the per-criterion minimum thresholds exactly as the design table specifies
    - `SelectionOutcome` exposes `selected` (model_id or `RETAIN_PHASE_1`), `aggregates`, and `passing`
    - _Requirements: 1.4, 2.3, 2.4, 2.9_
  - [ ]* 3.2 Write unit tests asserting weights sum to 100 and every criterion has a minimum
    - _Requirements: 2.3_

- [ ] 4. Implement harness, emotion, safety, licensing, and normalization data models
  - [ ] 4.1 Implement remaining dataclasses in `roadmap/models/runtime.py`
    - `HarnessRun`, `EmotionFeatures` (with V/A/D clamped to [-1.0, 1.0] on construction), `ConsentRecord` (+ a `is_valid` helper requiring all three fields non-empty), `CloningDecision`, `LicenseEntry`, `ComplianceWarning`, `NormalizationResult`
    - _Requirements: 4.3, 6.1, 10.1, 11.2_
  - [ ]* 4.2 Write unit tests for V/A/D clamping and the consent-record validity helper
    - _Requirements: 6.1, 10.1_

- [ ] 5. Implement the Roadmap aggregate and phase-structure invariant
  - [ ] 5.1 Implement `Roadmap` in `roadmap/roadmap_model.py`
    - Hold ordered phases, track labels, gates, conflict register, and the explicit scope statements; enforce unique/contiguous ordinals starting at 1, unique ids, first phase is `P1-baseline`, final phase `is_speech_native`, every phase has >=1 guide section and a compute footprint
    - _Requirements: 1.1, 1.6, 9.1_
  - [ ]* 5.2 Write property test for the phase-structure invariant
    - **Property 1: Phase-structure invariant**
    - **Validates: Requirements 1.1, 1.6, 9.1**

- [ ] 6. Implement the Licensing Register
  - [ ] 6.1 Implement `LicensingRegister` in `roadmap/licensing.py`
    - Record `{component_name, license_id, constraints}` before use (recognized OSS ids only); on recording failure allow adoption but raise/retain an unresolved `ComplianceWarning`; record excluded candidates with reason (licensing or non-licensing); flag datasets restricting redistribution/requiring consent with the specific restriction type; expose a `redistribution_allowed(component)` check used by the Hinglish engine
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.6, 11.8_
  - [ ]* 6.2 Write property test for the licensing register and redistribution exclusion
    - **Property 15: Licensing register and redistribution exclusion**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.6, 11.8**

- [ ] 7. Implement the Gate Evaluator
  - [ ] 7.1 Implement `GateEvaluator` in `roadmap/gate_evaluator.py`
    - Resolve each criterion to exactly one pass/fail per its operator; missing measured value resolves to fail (fail-closed); `overall_passed` is true iff every criterion passes AND the `LicensingRegister` has no unresolved warning and no prohibiting license; when not passed set `blocked=true` and emit one `remediation` entry per failing criterion; a decision gate additionally returns its single owner role and a fallback action (allowing "remain on LEAN_Track")
    - _Requirements: 1.4, 1.5, 8.4, 8.5, 11.5, 11.7_
  - [ ]* 7.2 Write property test for gate evaluation, blocking, remediation, and licensing block
    - **Property 2: Gate evaluation, blocking, remediation, and licensing block**
    - **Validates: Requirements 1.4, 1.5, 8.4, 8.5, 11.5, 11.7**
  - [ ]* 7.3 Write unit tests for boundary cases
    - One failing criterion produces exactly one remediation entry; a missing metric forces overall fail; an unresolved warning blocks an otherwise-passing gate
    - _Requirements: 8.4, 8.5, 11.7_

- [ ] 8. Implement the Selection Scorer
  - [ ] 8.1 Implement `SelectionScorer` in `roadmap/selection_scorer.py`
    - Score every candidate against every criterion; compute `passes_all_minimums`; return `RETAIN_PHASE_1` when no candidate passes all minimums, otherwise the argmax weighted aggregate among passing candidates; document the Phase_1 concurrent-fallback policy in the docstring (retain Phase 1 alongside the selected core until the LEAN launch gate passes)
    - _Requirements: 2.4, 2.7, 2.9_
  - [ ]* 8.2 Write property test for Speech-Native Core selection
    - **Property 3: Speech-Native Core selection**
    - **Validates: Requirements 2.4, 2.7, 2.9**
  - [ ]* 8.3 Write unit test for the selection tie-break behavior
    - _Requirements: 2.9_

- [ ] 9. Checkpoint — core data models, registries, gate, and selection logic
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Implement the Evaluation Harness (comparability and record completeness)
  - [ ] 10.1 Implement the mocked `EvaluationHarness` in `roadmap/evaluation_harness.py`
    - Produce `HarnessRun` records using an identical metric key set and scale for every candidate; each record contains model id, revision, first-response latency (ms, p50), code-switch quality, expressiveness, categorical license-compat, and hardware `{gpu_class, vram_gb}`; inputs are mocked/small-sample bounded by a documented max item count and require no GPU/training run
    - _Requirements: 4.1, 4.2, 4.3, 4.6_
  - [ ]* 10.2 Write property test for harness comparability and record completeness
    - **Property 4: Evaluation harness comparability and record completeness**
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [ ] 11. Add exclusion handling to the Evaluation Harness
  - [ ] 11.1 Extend `EvaluationHarness` with per-candidate exclusion recording in `roadmap/evaluation_harness.py`
    - Catch missing-weights / license / hardware conditions per candidate, record `exclusion_category` + `exclusion_reason`, and continue evaluating remaining candidates without aborting
    - _Requirements: 4.5, 11.4_
  - [ ]* 11.2 Write property test for exclusion recording without abort
    - **Property 5: Exclusion recording without abort**
    - **Validates: Requirements 4.5, 11.4**

- [ ] 12. Add reproducibility support to the Evaluation Harness
  - [ ] 12.1 Extend `EvaluationHarness` with reproducible re-runs in `roadmap/evaluation_harness.py`
    - Re-running >=3 times on the same mocked inputs and hardware yields per-metric scores within the documented tolerance (latency ±10%, quality ±2 points, expressiveness ±2 points)
    - _Requirements: 4.4_
  - [ ]* 12.2 Write property test for harness reproducibility within tolerance
    - **Property 6: Harness reproducibility within tolerance**
    - **Validates: Requirements 4.4**

- [ ] 13. Implement Hinglish transliteration normalization
  - [ ] 13.1 Implement `HinglishDataEngine.normalize(text)` in `roadmap/hinglish.py`
    - Deterministic Romanized↔Devanagari mapping (same input always yields same output) used for both input normalization and output rendering; tokens with no mapping entry are retained unchanged in `normalized_text` and reported in `unmapped_tokens`
    - _Requirements: 5.5, 5.8_
  - [ ]* 13.2 Write property test for transliteration determinism and unmapped-token handling
    - **Property 8: Transliteration determinism and unmapped-token handling**
    - **Validates: Requirements 5.5, 5.8**

- [ ] 14. Implement Hinglish code-switch quality scoring
  - [ ] 14.1 Implement `HinglishDataEngine.score(input, output)` and the benchmark pass rule in `roadmap/hinglish.py`
    - A response is "within tolerance" iff |response H/E ratio − input H/E ratio| <= 15 percentage points; a build passes the Hinglish benchmark iff the evaluation-set score is >= 80%; document the lightweight-adaptation (LoRA/adapters) hook applied when the adopted core scores below 80% before any custom-model work
    - _Requirements: 5.4, 5.6, 5.7_
  - [ ]* 14.2 Write property test for code-switch quality scoring and pass threshold
    - **Property 7: Code-switch quality scoring and pass threshold**
    - **Validates: Requirements 5.4, 5.6**

- [ ] 15. Implement the Emotion/Persona Controller
  - [ ] 15.1 Implement `EmotionPersonaController.select_conditioning(features)` in `roadmap/emotion_persona.py`
    - Always expose clamped V/A/D in [-1.0, 1.0]; return `NEUTRAL` (0,0,0 + neutral tag) when extraction failed/unavailable; return `EMPATHETIC` when the dominant label is a distress label (sad/angry/fear) with confidence >= 0.50; otherwise return `STANDARD` from the V/A/D vector and dominant label; the turn always continues
    - _Requirements: 6.1, 6.3, 6.5, 6.7_
  - [ ]* 15.2 Write property test for emotion/persona conditioning selection
    - **Property 9: Emotion/persona conditioning selection**
    - **Validates: Requirements 6.1, 6.3, 6.5, 6.7**
  - [ ]* 15.3 Write unit test for the distress confidence boundary
    - A distress label at exactly confidence 0.50 selects `EMPATHETIC`
    - _Requirements: 6.5_

- [ ] 16. Checkpoint — evaluation harness and Hinglish/emotion logic
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. Implement Duplex Manager barge-in timing
  - [ ] 17.1 Implement barge-in decision logic in `roadmap/duplex_manager.py`
    - With a simulated clock: when >=150 ms of voiced user speech is detected while producing audio, schedule output suppression within 200 ms of detection and transition the turn state to `LISTENING` within 100 ms of detection, from any active/intermediate/processing state
    - _Requirements: 7.4, 7.5_
  - [ ]* 17.2 Write property test for barge-in suppression and listening transition
    - **Property 10: Barge-in suppression and listening transition**
    - **Validates: Requirements 7.4, 7.5**
  - [ ]* 17.3 Write unit test for barge-in from an intermediate state
    - A barge-in from a `THINKING`/processing state reaches `LISTENING` within budget
    - _Requirements: 7.5_

- [ ] 18. Implement Duplex Manager latency-only fallback
  - [ ] 18.1 Implement latency-only fallback discrimination in `roadmap/duplex_manager.py`
    - Complete the turn via the Phase_1_Pipeline (or TTS_Fallback when Phase 1 is unavailable) iff the core fails to emit its first audible token within the 300 ms budget; non-latency core failure types alone do not trigger this fallback
    - _Requirements: 3.5_
  - [ ]* 18.2 Write property test for latency-only fallback discrimination
    - **Property 11: Latency-only fallback discrimination**
    - **Validates: Requirements 3.5**

- [ ] 19. Implement Safety Guard watermarking
  - [ ] 19.1 Implement watermark application in `roadmap/safety_guard.py`
    - Every synthesized output on every path (including fallback paths) carries a watermark reported as detected by a mocked watermark detector; an output whose watermark cannot be verified is flagged non-compliant rather than emitted
    - _Requirements: 10.2_
  - [ ]* 19.2 Write property test for watermark on every output path
    - **Property 12: Watermark on every output path**
    - **Validates: Requirements 10.2**

- [ ] 20. Implement Safety Guard consent gating
  - [ ] 20.1 Implement consent gating and the consent log in `roadmap/safety_guard.py`
    - Allow cloning/voice-style transfer iff a valid `ConsentRecord` (speaker_id, permitted_use_scope, timestamp all present) exists; otherwise refuse, indicate the refusal, and set `reference_retained=False`; maintain a product-facing consent log where every entry carries the three fields and is retained while the voice stays in use
    - _Requirements: 10.1, 10.3, 10.6_
  - [ ]* 20.2 Write property test for consent gating and consent-log completeness
    - **Property 13: Consent gating and consent-log completeness**
    - **Validates: Requirements 10.1, 10.3, 10.6**

- [ ] 21. Implement Safety Guard crisis handling
  - [ ] 21.1 Implement crisis handling in `roadmap/safety_guard.py`
    - When the crisis-classifier score is at or above its decision threshold, surface crisis-support guidance AND flag the turn for human review; below threshold do neither
    - _Requirements: 10.4, 10.5_
  - [ ]* 21.2 Write property test for crisis handling
    - **Property 14: Crisis handling**
    - **Validates: Requirements 10.4, 10.5**

- [ ] 22. Implement the Budget & Compute Planner
  - [ ] 22.1 Implement `BudgetComputePlanner` in `roadmap/budget_planner.py`
    - State per-phase footprint (min GPU class + min VRAM GB); state LEAN and AMBITIOUS budget ranges as `{lower, upper, currency}` with lower <= upper; assert LEAN is executable by <=5 people without large-scale GPU training; `select_scope(phase, available_compute)` returns a reduced-scope alternative (footprint not exceeding confirmed-available compute) when availability is below the phase minimum, zero, or invalid/missing; require an explicit AMBITIOUS justification (budget range + per-phase footprint) before AMBITIOUS is entered at G1
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  - [ ]* 22.2 Write unit/property test for `select_scope` on insufficient, zero, and invalid/missing compute
    - Returned footprint never exceeds the confirmed-available compute
    - _Requirements: 9.5_

- [ ] 23. Author the narrative roadmap planning artifact (`roadmap/ROADMAP.md`)
  - [ ] 23.1 Author the phase/track/gate structure and traceability sections
    - Ordered phase table (ordinal, id, track, title, guide-section mappings) with first phase `P1-baseline` and a final speech-native phase; LEAN labeled "primary" and AMBITIOUS labeled "optional" positioned after Decision_Gate `G1`; `G1` with entry criteria, exit criteria, single owner role (ML Lead), and the fallback action "remain on LEAN_Track"; the conflict register with topic + superseding decision + rationale per row
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 1.7_
  - [ ] 23.2 Author the model-adoption, evolution, moat, emotion, duplex/latency, and benchmark sections
    - Adopt-existing-core-first vs deferred-custom designation; Candidate_Model enumeration; `kyutai/mimi` primary codec + `neuphonic/neucodec`/`HKUSTAudio/xcodec2` alternatives; `sesame/csm-1b` + TTS_Fallback as reference-only; weighted selection table (sums to 100, per-criterion minimums); concurrent-run migration stage with per-session runtime fallback switch and Phase_1-as-additional-fallback-until-launch-gate; reuse of Silero VAD / `turn_state.py` / `filler.py`; retained auxiliary STT; WebSocket/LiveKit continuity or v2 id; Hinglish moat statement + Indic_Stack resources; FiLM conditioning + retained SER + ECAPA models; latency targets (300 ms practical / 200 ms stretch / 80 ms perceived) + mitigations; benchmark families and LEAN/AMBITIOUS launch gates with competitive targets
    - _Requirements: 2.1, 2.2, 2.5, 2.6, 2.8, 3.1, 3.2, 3.3, 3.4, 3.6, 5.1, 5.2, 5.3, 6.2, 6.4, 6.6, 7.1, 7.2, 7.3, 7.6, 7.7, 8.1, 8.2, 8.3, 8.6_
  - [ ] 23.3 Author the budget/compute, safety-scope, and scope/relationship sections
    - LEAN/AMBITIOUS budget ranges (single currency, lower <= upper), <=5-person LEAN claim, AMBITIOUS justification requirement; safety/consent/watermark declared in LEAN demo scope; licensing reviewed at every launch gate; authoritative-plan-supersedes-PDFs statement citing each `docs/` PDF by exact file name; reference to `.kiro/specs/ai-training-docs/` without restating its doc-gen requirements; explicit exclusions of from-scratch pretraining and GPU-training execution; planning-artifact-only declaration
    - _Requirements: 9.2, 9.3, 9.4, 10.7, 11.5, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

- [ ] 24. Write structural/example tests for the narrative roadmap content
  - [ ]* 24.1 Write structural tests for track/gate structure and scope statements in `roadmap/tests/test_structural_structure.py`
    - LEAN "primary" / AMBITIOUS "optional" after the decision gate; >=1 Decision_Gate between tracks; conflict-register rows complete; authoritative/supersedes statement; `ai-training-docs` reference without doc-gen restatement; pretraining + GPU-training exclusions; planning-artifact-only declaration
    - _Requirements: 1.2, 1.3, 1.7, 12.1, 12.2, 12.3, 12.4, 12.5, 12.7_
  - [ ]* 24.2 Write structural tests for enumerations and designations in `roadmap/tests/test_structural_enumerations.py`
    - Candidate_Model list, codec primary/alternatives, `csm-1b`/TTS_Fallback reference-only, Indic_Stack resources, benchmark families, competitive targets, and the selection-weight table summing to 100 with a per-criterion minimum
    - _Requirements: 2.2, 2.3, 2.5, 2.6, 5.3, 8.1, 8.6_
  - [ ]* 24.3 Write structural tests for migration/reuse statements, targets, and policies in `roadmap/tests/test_structural_targets.py`
    - Concurrent-run stage + per-session switch, reuse of Silero VAD / `turn_state.py` / `filler.py`, retained auxiliary STT, WebSocket/LiveKit continuity, Duplex_Manager evolution; latency targets + mitigations; lightweight-adaptation-before-custom; FiLM + SER + ECAPA; budget ranges + <=5-person + AMBITIOUS justification; safety-in-LEAN scope
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 5.1, 5.2, 5.7, 6.2, 6.4, 6.6, 7.1, 7.2, 7.3, 7.6, 7.7, 9.2, 9.3, 9.4, 10.7_
  - [ ]* 24.4 Write the PDF-citation existence test in `roadmap/tests/test_pdf_citations.py`
    - Assert every `docs/` file name referenced in `ROADMAP.md` exists in the actual `docs/` directory listing
    - _Requirements: 12.6_

- [ ] 25. Integrate the decision-logic tooling
  - [ ] 25.1 Wire the components into a cohesive package API in `roadmap/__init__.py`
    - Export the public classes and a single `evaluate_and_select(...)` pipeline helper that runs the mocked harness over a candidate set, feeds scores into `SelectionScorer`, and evaluates the resulting launch gate via `GateEvaluator` + `LicensingRegister`
    - _Requirements: 2.4, 2.7, 2.9, 8.4_
  - [ ]* 25.2 Write the end-to-end integration test in `roadmap/tests/test_integration_harness.py`
    - One mocked pass over a small fixed candidate set asserting comparable records, a deterministic selection, exclusion continuation, and a gate result — verifying wiring, not re-testing the universal properties
    - _Requirements: 4.1, 4.5, 8.4_

- [ ] 26. Final checkpoint — ensure all property and structural tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 27. Implement serialization for the planning objects (JSON/YAML)
  - [ ] 27.1 Implement `to_dict`/`from_dict` and JSON/YAML codecs in `roadmap/serialization.py`
    - Provide `to_dict(obj)`/`from_dict(cls, data)` for every planning dataclass (`Phase`, `GateCriterion`, `Gate`, `CriterionResult`, `GateResult`, `CandidateScores`, `SelectionOutcome`, `HarnessRun`, `EmotionFeatures`, `ConsentRecord`, `CloningDecision`, `LicenseEntry`, `ComplianceWarning`, `NormalizationResult`) and the `Roadmap` aggregate
    - Add `dumps_json`/`loads_json` and `dumps_yaml`/`loads_yaml` helpers (add `pyyaml` to `roadmap/requirements.txt`); preserve `Literal`/enum values as strings and floats without precision loss
    - _Requirements: 1.1, 1.4, 12.7_
  - [ ]* 27.2 Write a property-based round-trip test in `roadmap/tests/test_serialization_roundtrip.py`
    - Hypothesis (`@settings(max_examples=100)`) asserting `from_dict(to_dict(x)) == x` and `loads_json(dumps_json(x)) == x` for generated instances of every planning dataclass
    - This is a round-trip invariant that complements the 15 design properties; do NOT tag it as a numbered `Property {n}` so the Task 39 coverage report still finds exactly Properties 1–15
    - _Requirements: 1.1, 12.7_
  - [ ]* 27.3 Write unit tests for serialization edge cases in `roadmap/tests/test_serialization_formats.py`
    - YAML↔JSON equivalence, unknown-key rejection, and `Optional`/`None` handling for `HarnessRun` exclusion fields and `LicenseEntry.license_id`
    - _Requirements: 4.3, 11.2_

- [ ] 28. Add a JSON Schema and schema-validation layer for the planning models
  - [ ] 28.1 Author JSON Schemas and a validator in `roadmap/schemas/` and `roadmap/schema.py`
    - Write one JSON Schema document per planning model under `roadmap/schemas/*.json` (phase, gate, gate_result, candidate_scores, selection_outcome, harness_run, emotion_features, consent_record, license_entry, normalization_result, roadmap)
    - Implement `validate(obj_dict, schema_name)` enforcing required fields, the `operator` enum `{<=,<,>=,>,==}`, V/A/D bounds `[-1.0, 1.0]`, and the selection-weight keys; raise a structured `SchemaValidationError` listing every violation
    - _Requirements: 1.4, 2.3, 6.1, 9.1_
  - [ ]* 28.2 Write unit tests for schema validation in `roadmap/tests/test_schema.py`
    - Valid documents pass; a missing required field, an out-of-range V/A/D, and a bad operator each fail with a descriptive error
    - _Requirements: 1.4, 6.1_
  - [ ]* 28.3 Write a property test that serialized models satisfy their schema in `roadmap/tests/test_schema_roundtrip.py`
    - Hypothesis (≥100 examples) asserting `validate(to_dict(x), schema_for(x))` passes for every generated planning object; complementary invariant, not a numbered design `Property`
    - _Requirements: 1.4, 2.3_

- [ ] 29. Load the roadmap from a structured data file and round-trip to `ROADMAP.md`
  - [ ] 29.1 Author `roadmap/data/roadmap_data.yaml` and a loader in `roadmap/roadmap_io.py`
    - Encode the seven phases (`P1-baseline`…`P7-diff-gate`), the two tracks, gate `G1`, the launch gates, the conflict register, and the scope statements as structured data; implement `load_roadmap(path) -> Roadmap` that builds and validates the `Roadmap` aggregate (reusing the Task 5 invariants and the Task 28 schema)
    - _Requirements: 1.1, 1.6, 1.7, 9.1_
  - [ ] 29.2 Implement `ROADMAP.md` round-trip in `roadmap/roadmap_io.py`
    - `render_markdown(roadmap) -> str` emits the phase/track/gate/conflict tables and `parse_markdown(md) -> Roadmap` reads them back, so the structured data file and the narrative artifact stay one source of truth; `parse_markdown(render_markdown(r))` reproduces the same `Roadmap`
    - _Requirements: 1.1, 1.6, 1.7_
  - [ ]* 29.3 Write round-trip and structural tests in `roadmap/tests/test_roadmap_io.py`
    - Assert `load_roadmap` produces a valid aggregate and that `parse_markdown(render_markdown(r))` equals the loaded roadmap
    - _Requirements: 1.1, 1.6_

- [ ] 30. Cross-check the `ROADMAP.md` narrative against the planning data objects
  - [ ] 30.1 Implement a consistency checker in `roadmap/consistency.py`
    - Compare the authored `roadmap/ROADMAP.md` (Task 23) against the structured `Roadmap` loaded by Task 29 — phase ordinals/ids/tracks, the LEAN-"primary"/AMBITIOUS-"optional" labels, gate `G1` owner and fallback, conflict-register rows, and the selection-weight table summing to 100 — and report every divergence as a structured finding
    - _Requirements: 1.1, 1.2, 1.7, 12.1_
  - [ ]* 30.2 Write tests for the consistency checker in `roadmap/tests/test_consistency.py`
    - A matching pair reports no divergence; an injected mismatch (changed label, dropped conflict row) is reported
    - _Requirements: 1.2, 1.7_

- [ ] 31. Render a combined human-readable gate report
  - [ ] 31.1 Create the reports package and `roadmap/reports/gate_report.py`
    - Create `roadmap/reports/__init__.py`; implement `render_gate_report(gate_result, *, gate=None, registry=None) -> str` producing a human-readable launch/decision-gate report from a `GateResult`: per-criterion measured/threshold/operator/pass-fail rows, the overall pass/fail, the blocked flag, the remediation list, and (for a Decision_Gate) the single owner role and fallback action
    - _Requirements: 1.4, 1.5, 8.4, 8.5, 11.5, 11.7_
  - [ ]* 31.2 Write unit tests for the gate report in `roadmap/tests/test_gate_report.py`
    - A blocked result lists one remediation line per failing criterion; a decision-gate report shows the owner and the "remain on LEAN_Track" fallback
    - _Requirements: 8.5, 1.5_

- [ ] 32. Render a candidate-model evaluation report
  - [ ] 32.1 Implement `roadmap/reports/evaluation_report.py`
    - `render_evaluation_report(runs) -> str` emits a Markdown table from `HarnessRun` records — model id, revision, latency (ms, p50), code-switch quality, expressiveness, license-compat, and hardware `{gpu_class, vram_gb}` — with excluded candidates in a separate section showing their exclusion category and reason
    - _Requirements: 4.1, 4.2, 4.3, 4.5_
  - [ ]* 32.2 Write unit tests for the evaluation report in `roadmap/tests/test_evaluation_report.py`
    - All non-excluded rows share the identical metric columns; excluded candidates appear with category + reason
    - _Requirements: 4.1, 4.5_

- [ ] 33. Export the conflict register and licensing register
  - [ ] 33.1 Implement `roadmap/reports/registers_report.py`
    - `render_conflict_register(roadmap) -> str` emits the topic/superseding-decision/rationale table; `render_licensing_report(registry) -> (str, dict)` emits a Markdown table plus a JSON export of every `LicenseEntry` (name, license id, constraints, intended-use flag, redistribution restriction + type), the unresolved `ComplianceWarning`s, and the excluded candidates with reasons
    - _Requirements: 1.7, 11.2, 11.4, 11.6_
  - [ ]* 33.2 Write unit tests for the register exports in `roadmap/tests/test_registers_report.py`
    - An unresolved warning and a redistribution-restricted dataset both appear flagged; the JSON export round-trips through `serialization`
    - _Requirements: 11.3, 11.6_

- [ ] 34. Externalize the Hinglish transliteration mapping and report coverage
  - [ ] 34.1 Author `roadmap/data/hinglish_map.json` and load it in `roadmap/hinglish.py`
    - Move the Romanized↔Devanagari mapping into a versioned data file and have `HinglishDataEngine` load it on construction; loading preserves determinism (same input → same normalized output) and the engine still retains-and-flags tokens absent from the loaded map
    - _Requirements: 5.5, 5.8_
  - [ ] 34.2 Implement an unmapped-token coverage report in `roadmap/reports/hinglish_coverage.py`
    - `render_coverage_report(engine, corpus) -> str` reports the mapping size, per-corpus mapped/unmapped token counts, and the aggregated list of unmapped tokens flagged for review
    - _Requirements: 5.8_
  - [ ]* 34.3 Write tests for the mapping loader and coverage report in `roadmap/tests/test_hinglish_map.py`
    - The loaded map yields deterministic normalization on a fixed corpus; unmapped tokens are both retained in output and counted in the report
    - _Requirements: 5.5, 5.8_

- [ ] 35. Render a latency-budget simulation report
  - [ ] 35.1 Implement `roadmap/reports/latency_report.py`
    - `render_latency_report(decisions) -> str` summarizes `DuplexManager` timing decisions over a simulated-clock run: p50 first-response vs the 300 ms practical / 200 ms stretch / 80 ms perceived targets, barge-in suppression (≤200 ms) and listening-transition (≤100 ms) timings, the count of latency-triggered Phase_1 fallbacks, and the mitigation list when the practical target is missed
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7_
  - [ ]* 35.2 Write unit tests for the latency report in `roadmap/tests/test_latency_report.py`
    - A run that misses the practical target reports the mitigation options; suppression/transition timings are reported against their budgets
    - _Requirements: 7.4, 7.5, 7.7_

- [ ] 36. Render a consent-log and watermark-compliance audit report
  - [ ] 36.1 Implement `roadmap/reports/safety_audit.py`
    - `render_safety_audit(safety_guard, outputs) -> str` reports the product-facing consent log (speaker id, permitted-use scope, timestamp per entry), any cloning refusals with reference-not-retained confirmation, the per-output-path watermark-detection results (including fallback paths), any non-compliant unwatermarked paths, and the crisis-flag tally
    - _Requirements: 10.1, 10.2, 10.4, 10.5, 10.6_
  - [ ]* 36.2 Write unit tests for the safety audit in `roadmap/tests/test_safety_audit.py`
    - Every output path shows a watermark-detected result; a refused clone shows `reference_retained=False`; the consent log lists all three fields per entry
    - _Requirements: 10.2, 10.3, 10.6_

- [ ] 37. Render a per-phase budget and compute summary
  - [ ] 37.1 Implement `roadmap/reports/budget_report.py`
    - `render_budget_report(planner, roadmap) -> str` tabulates each phase's minimum GPU class and VRAM (GB), the LEAN and AMBITIOUS budget ranges (`lower ≤ upper`, single currency), the ≤5-person LEAN claim, the AMBITIOUS-entry justification requirement, and any `select_scope` reduced-scope alternatives chosen for constrained compute
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  - [ ]* 37.2 Write unit tests for the budget report in `roadmap/tests/test_budget_report.py`
    - Each phase row carries a GPU class + VRAM; a constrained-compute phase shows a reduced-scope footprint that does not exceed available compute
    - _Requirements: 9.1, 9.5_

- [ ] 38. Generate the requirement-to-task-to-test traceability matrix
  - [ ] 38.1 Implement a traceability generator in `roadmap/reports/traceability.py`
    - Parse `requirements.md` for every acceptance-criterion id, parse this `tasks.md` for `_Requirements:_` references, and scan `roadmap/tests/` for the property tags and `_Requirements:_` annotations; emit a Markdown matrix mapping each criterion → covering task(s) → covering test(s) plus a list of any uncovered criteria
    - _Requirements: 1.6, 12.7_
  - [ ]* 38.2 Write tests asserting full criterion coverage in `roadmap/tests/test_traceability.py`
    - The generated matrix maps every requirements criterion to at least one task; the uncovered-criteria list is empty
    - _Requirements: 1.6, 12.7_

- [ ] 39. Generate a property-test coverage report
  - [ ] 39.1 Implement a property-coverage scanner in `roadmap/reports/property_coverage.py`
    - Scan `roadmap/tests/` for the tag comments `# Feature: speech-native-voice-roadmap, Property {n}: {text}` and report which of Properties 1–15 are implemented, each with its test location, and which (if any) are missing
    - _Requirements: 12.7_
  - [ ]* 39.2 Write a test asserting all 15 properties are present in `roadmap/tests/test_property_coverage.py`
    - Assert the scanner finds exactly Properties 1 through 15, each tagged once, with no gaps and no numbers beyond 15
    - _Requirements: 12.7_

- [ ] 40. Generate API reference and per-component documentation pages
  - [ ] 40.1 Implement a docstring/API-reference generator in `roadmap/docs_gen.py`
    - `generate_api_reference(package="roadmap") -> dict[str, str]` introspects each module's public classes/functions and their docstrings and renders one Markdown page per component; scoped to the roadmap tooling package's own API and explicitly does NOT duplicate the `.kiro/specs/ai-training-docs/` knowledge base
    - _Requirements: 12.3, 12.7_
  - [ ] 40.2 Author per-component documentation pages under `roadmap/docs/`
    - Write a page per planning component (Roadmap, GateEvaluator, SelectionScorer, EvaluationHarness, HinglishDataEngine, EmotionPersonaController, DuplexManager, SafetyGuard, LicensingRegister, BudgetComputePlanner) describing inputs→outputs and linking to the generated API reference
    - _Requirements: 12.7_
  - [ ]* 40.3 Write tests for the docs generator in `roadmap/tests/test_docs_gen.py`
    - Every public component has a generated page that contains the component's documented interface; no `ai-training-docs` content is restated
    - _Requirements: 12.3_

- [ ] 41. Add a CLI for the roadmap tooling
  - [ ] 41.1 Implement `roadmap/cli.py` and register a console entry point
    - Provide subcommands `validate` (schema + invariants), `select` (run the mocked harness → `SelectionScorer` → gate), `gate-report`, `eval-report`, `trace`, `coverage`, and `render-roadmap`; wire each to the existing modules and register a `roadmap` console-script entry point in `pyproject.toml`
    - _Requirements: 2.4, 2.7, 2.9, 8.4, 12.7_
  - [ ]* 41.2 Write CLI smoke tests in `roadmap/tests/test_cli.py`
    - Each subcommand runs on fixture data, exits zero, and never invokes a GPU/training run
    - _Requirements: 4.6, 12.7_

- [ ] 42. Author the roadmap package README
  - [ ] 42.1 Write `roadmap/README.md`
    - Document the package layout, how to load/validate the roadmap, how to run each report and the CLI, and how to run the property + structural tests (Hypothesis ≥100 examples); state that the harness is mocked and runs no GPU training
    - _Requirements: 4.6, 12.7_
  - [ ]* 42.2 Write a README link/structural test in `roadmap/tests/test_readme.py`
    - Assert the README references each report module and CLI subcommand that exists in the package
    - _Requirements: 12.7_

- [ ] 43. Add linting and type-checking for the roadmap package
  - [ ] 43.1 Configure ruff and mypy scoped to `roadmap/` in `pyproject.toml`
    - Add `[tool.ruff]` and `[tool.mypy]` sections targeting the `roadmap` package, add a `roadmap/py.typed` marker, and resolve type annotations on the public dataclasses and decision-logic functions
    - _Requirements: 12.7_
  - [ ]* 43.2 Add a lint/type configuration smoke test in `roadmap/tests/test_tooling_config.py`
    - Assert the ruff and mypy configuration targets `roadmap/` and that `py.typed` is present
    - _Requirements: 12.7_

- [ ] 44. Add a local test-runner and pre-commit configuration
  - [ ] 44.1 Author a local test-runner script `scripts/run_roadmap_tests.ps1`
    - Run `pytest` over `roadmap/tests` with the Hypothesis profile (≥100 examples) in single-run (non-watch) mode and surface a non-zero exit on failure; document the equivalent direct `pytest` command for non-Windows shells
    - _Requirements: 4.6, 12.7_
  - [ ] 44.2 Author a `.pre-commit-config.yaml` for the roadmap package
    - Wire ruff, mypy, and the roadmap pytest run as pre-commit hooks scoped to `roadmap/`; the hooks must not trigger any GPU/model-training run
    - _Requirements: 4.6, 12.7_
  - [ ]* 44.3 Write a meta-test validating the runner configuration in `roadmap/tests/test_test_runner.py`
    - Assert the runner script and pre-commit config reference the `roadmap/tests` path and the Hypothesis profile
    - _Requirements: 4.6_

- [ ] 45. Consolidate edge-case and regression test suites
  - [ ] 45.1 Implement shared test fixtures and a regression-cases data file in `roadmap/tests/fixtures.py` and `roadmap/tests/regression_cases.json`
    - Provide reusable Hypothesis strategies (out-of-range V/A/D, zero/one/many passing candidates, missing gate metrics, partial consent, 0–100% token ratios, zero/invalid compute) and a JSON file recording any counterexamples surfaced by earlier property runs
    - _Requirements: 12.7_
  - [ ]* 45.2 Write a consolidated edge-case suite in `roadmap/tests/test_edge_cases.py`
    - Exercise boundary inputs across the decision logic (distress confidence exactly 0.50, latency exactly 300 ms, the 15-point ratio boundary, weight sum exactly 100) using the shared fixtures
    - _Requirements: 5.4, 6.5, 7.4, 2.3_
  - [ ]* 45.3 Write a regression suite in `roadmap/tests/test_regression.py`
    - Replay every recorded counterexample from `regression_cases.json` against its decision-logic function and assert the corrected behavior holds
    - _Requirements: 12.7_

- [ ] 46. Final checkpoint — end-to-end validation and traceability completeness
  - Run the full property + structural + unit suite, the consistency cross-check, the traceability matrix, and the property-coverage report; confirm every requirements criterion maps to a task and a test and that Properties 1–15 are all implemented and tagged. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, but each of the 15 property tests maps 1:1 to a design correctness property and is the primary verification mechanism for the decision logic.
- Each property test must run a minimum of 100 Hypothesis examples and carry the tag comment `# Feature: speech-native-voice-roadmap, Property {n}: {text}`. Tasks 27–46 add only complementary round-trip/schema/structural tests and must NOT introduce new numbered design `Property {n}` tags — the design defines exactly Properties 1–15, and Task 39 asserts that count is preserved.
- The Evaluation_Harness is mocked end-to-end; no task invokes a GPU model-training run (Requirements 4.6, 12.4, 12.5). Tasks 27–46 stay within this boundary: they add packaging, serialization, schema validation, reporting, documentation, traceability, and CI/lint tooling around the existing pure decision logic and never add training execution or GPU model work.
- The narrative artifact (`roadmap/ROADMAP.md`, Task 23) is the spec's primary deliverable; the structural tests in Task 24 verify its required content, enumerations, targets, and citations, and Task 30 cross-checks that the narrative stays in sync with the structured planning data (Tasks 27–29).
- Tasks 27–29 add serialization (JSON/YAML), a JSON-schema validation layer, and structured-data loading with `ROADMAP.md` round-trip. Tasks 31–37 add human-readable reports (gate, evaluation, conflict/licensing registers, Hinglish coverage, latency-budget, safety audit, budget/compute). Tasks 38–39 add the requirement→task→test traceability matrix and the property-test coverage report. Tasks 40–44 add API/component docs, a CLI, the package README, lint/type-check (ruff/mypy), and a local test-runner + pre-commit configuration. Task 45 consolidates edge-case and regression suites.
- Checkpoints (Tasks 9, 16, 26, 46) provide incremental validation at natural breaks; Task 46 is the final end-to-end validation and traceability-completeness gate.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.1", "4.1", "23.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.2", "5.1", "6.1", "8.1", "10.1", "13.1", "15.1", "17.1", "19.1", "22.1", "23.2"] },
    { "id": 3, "tasks": ["5.2", "6.2", "7.1", "8.2", "8.3", "11.1", "14.1", "15.2", "15.3", "18.1", "20.1", "22.2", "23.3"] },
    { "id": 4, "tasks": ["7.2", "7.3", "12.1", "13.2", "14.2", "17.2", "17.3", "18.2", "21.1", "24.1", "24.2", "24.3", "24.4"] },
    { "id": 5, "tasks": ["10.2", "11.2", "12.2", "19.2", "20.2", "21.2", "25.1"] },
    { "id": 6, "tasks": ["25.2"] },
    { "id": 7, "tasks": ["27.1", "31.1", "34.1", "40.1", "44.1", "44.2", "45.1"] },
    { "id": 8, "tasks": ["27.2", "27.3", "28.1", "31.2", "32.1", "33.1", "34.2", "35.1", "36.1", "37.1", "38.1", "39.1", "40.2", "44.3", "45.2", "45.3"] },
    { "id": 9, "tasks": ["28.2", "28.3", "29.1", "32.2", "33.2", "34.3", "35.2", "36.2", "37.2", "38.2", "39.2", "40.3"] },
    { "id": 10, "tasks": ["29.2", "41.1"] },
    { "id": 11, "tasks": ["29.3", "30.1", "41.2", "42.1", "43.1"] },
    { "id": 12, "tasks": ["30.2", "42.2", "43.2"] }
  ]
}
```
