# Acceptance — Phase 11 Safety (moderation, voice policy, watermarking)

**Task:** Implement `final_use.md` Phase 11 FULLY — safety as a first-class gate. 11A
moderation (text + speech, crisis escalation, abuse logging), 11B consent-first voice
policy (protected-voice list, admin review, spoofing checks, no-retention, consent log),
11C watermarking on every output path (AudioSeal interface + deterministic fallback,
detector logging, ops tooling).

**Environment:** Windows, Python 3.11.9, pydantic 2.13.4, ruff 0.15.10. CPU-only, no GPU,
no Moshi/Mimi/AudioSeal weights. Classifiers + watermark backends are lazy-loaded with
deterministic fallbacks; everything imports and tests on CPU. Fail CLOSED throughout
(DECISIONS.md D-007 / D-008).

## Files created (strict ownership — only `safety/` + `runs/phase-11-safety/`)

```text
safety/contracts.py                     # safety-internal types + AuditLog/AuditEvent + HMAC sign/verify
safety/moderation/gate.py               # 11A ModerationGate (text + speech, crisis, abuse log)
safety/voice_policy/policy.py           # 11B VoicePolicy + ConsentStore (consent-first, no-retention)
safety/watermark/audioseal.py           # 11C Watermarker (embed+verify, AudioSeal iface + fallback, ops CLI)
safety/moderation/__init__.py           # re-exports (appended)
safety/voice_policy/__init__.py         # re-exports (appended)
safety/watermark/__init__.py            # re-exports (appended)
safety/tests/__init__.py
safety/tests/test_moderation.py         # 17 tests
safety/tests/test_voice_policy.py       # 19 tests
safety/tests/test_watermark.py          # 16 tests
safety/README.md                        # design note
runs/phase-11-safety/acceptance.md      # this file
```

No files outside `safety/` and `runs/phase-11-safety/` were modified. `shared/`,
`docs/INTERFACES.md`, `pyproject.toml`, `server/`, and other domains untouched. The shared
contracts `VoiceRequest`, `VoiceAction`, `ModerationDecision` are imported (not redefined).

## Commands run

```text
# 1. Required import smoke test
python -c "import safety.moderation.gate, safety.voice_policy.policy, safety.watermark.audioseal"
→ IMPORT OK                         (exit 0)

# 2. Required test run
python -m pytest safety/tests -q
→ 52 passed in 0.30s                 (exit 0)
   - safety/tests/test_moderation.py   17 passed
   - safety/tests/test_voice_policy.py 19 passed
   - safety/tests/test_watermark.py    16 passed

# 3. Watermark ops tooling self-check
python -m safety.watermark.audioseal
→ {"backend":"deterministic_fallback","self_check_compliant":true,"self_check_score":1.0,...}  (exit 0)

# 4. Lint + format parity with CI
python -m ruff check safety   → All checks passed!      (exit 0)
python -m ruff format --check safety → 12 files already formatted  (exit 0)
```

## Phase 11 acceptance criteria

### 11A — moderation gate ("unsafe turns blocked or escalated; decisions auditable")
- Text-path AND speech-path moderation share one classifier (`moderate_text` /
  `moderate_speech`), both returning `ModerationDecision`. ✔
- Crisis/self-harm at/above threshold → `allowed=False, escalate=True` AND crisis-support
  guidance surfaced (`ModerationOutcome.crisis_guidance`); crisis takes precedence. ✔
- Other risk categories blocked; offending category+score written to the abuse log. ✔
- Every decision recorded as an auditable `AuditEvent` (JSON round-trippable). ✔
- Classifier error fails closed (deny + escalate, `category="error"`). ✔
- Real ML classifier injectable via lazy `load_classifier`; deterministic lexicon fallback
  otherwise. ✔

### 11B — voice policy ("non-consensual cloning blocked with 100% policy compliance")
- Consent-first: a `VoiceRequest` lacking valid recorded consent (speaker id + permitted-use
  scope + active timestamp + intact HMAC token) is REFUSED (`refused=True`). ✔
- On refusal the voice reference is NOT retained (`retained=False`,
  `store.is_retained(ref)==False`). ✔
- Protected-voice list routes to admin review (`escalate_admin_review=True`). ✔
- Spoofing checks: forged/tampered/mismatched consent token → `category="spoofing"`;
  optional `SpoofDetector` blocks high `P(spoof)`; detector error fails closed. ✔
- 100% compliance: 50/50 non-consensual clone attempts refused, none retained. ✔
- Consent log records grants, revokes, and every decision; entries JSON round-trippable. ✔

### 11C — watermarking ("generated audio can be checked; watermark path regression tested")
- `Watermarker.protect()` embeds + self-verifies on every path; empty audio and a simulated
  classic-fallback TTS stream both produce verifiable, compliant output. ✔
- Output whose watermark cannot be verified (tampered samples, forged marker, detector
  error) is flagged `compliant=False`; `assert_compliant` raises `WatermarkComplianceError`
  as a hard emit-gate. ✔
- AudioSeal-shaped interface with injectable real backend (`load_audioseal_backend`) +
  deterministic HMAC fallback for CPU. ✔
- Detector outcomes logged (`compliant`/`non_compliant`) to an auditable `AuditLog`. ✔
- Ops tooling: `ops_status()` + `python -m safety.watermark.audioseal`. ✔

## Definition of Done (final_use.md §3.3)
- Code ✔  Tests (52) ✔  Design note (`safety/README.md`) ✔  Structured logging hooks
  (`AuditLog` + `get_logger`, JSON log lines) ✔  Acceptance recorded (this file) ✔.

## Notes / follow-ups for other teams
- **Speech/decoder (Phase 10) + aux/fallback (Phase 13):** route ALL synthesized audio
  through `Watermarker.protect(...)` before emit; gate emission on `result.compliant`
  (use `assert_compliant`). This includes filler audio and the classic TTS fallback path.
- **Any voice cloning / style transfer:** call `VoicePolicy.evaluate(VoiceRequest)` and only
  proceed when `decision.allowed`; never persist a refused/escalated voice reference.
- **Pending human pins (OPEN_QUESTIONS):** real AudioSeal checkpoint + real moderation
  classifier are lazy-load hooks today (`load_audioseal_backend`, `load_classifier`); set
  `SAFETY_HMAC_SECRET` to a real secret in production.
