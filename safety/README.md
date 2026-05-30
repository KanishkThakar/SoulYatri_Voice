# safety/ — Safety, Consent, Anti-Cloning, and Watermarking (Phase 11)

> **Safety is a first-class gate, not a post-process.** Every synthesized-audio output
> path is watermarked, every voice action is consent-first, and every risky turn is
> moderated. The subsystem **fails closed** — on any uncertainty it denies, refuses, or
> escalates (DECISIONS.md D-007). It imports and runs on **CPU with no model weights**
> (D-008): real classifiers / AudioSeal models are lazy-loaded behind interfaces, with
> deterministic fallbacks so the gate always works on a fresh checkout.

Implements `final_use.md` Phase 11 (11A moderation, 11B voice policy, 11C watermarking)
and the `VoiceRequest` / `VoiceAction` / `ModerationDecision` contracts from
[`shared/contracts.py`](../shared/contracts.py) (see [`docs/INTERFACES.md`](../docs/INTERFACES.md) §7).

---

## Module map

| File | Phase | Responsibility |
|---|---|---|
| `safety/contracts.py` | — | Safety-internal types + structured logging/audit hooks (`AuditLog`, `AuditEvent`), HMAC `sign`/`verify_signature`, and re-exports of the shared safety contracts. |
| `safety/moderation/gate.py` | 11A | Text-path **and** speech-path moderation, crisis/self-harm escalation, abuse logging. Returns `ModerationDecision`. |
| `safety/voice_policy/policy.py` | 11B | Consent-first voice policy: consent verification, protected-voice list, admin review, spoofing checks, no-retention on refusal, consent log. |
| `safety/watermark/audioseal.py` | 11C | Insert + verify a synthesized-audio watermark on **every** output path (AudioSeal interface + deterministic fallback), detector-outcome logging, ops tooling. |
| `safety/tests/` | — | pytest coverage for all three modules. |

---

## 11A — Moderation gate (`ModerationGate`)

- **Two paths, one standard.** `moderate_text(text)` and `moderate_speech(transcript)`
  run the *same* classifier so spoken turns (transcribed by the aux STT path, Phase 7A)
  and typed turns get identical treatment. Both return a `ModerationDecision`.
- **Crisis / self-harm flow.** When the crisis score is `>= crisis_threshold` the gate
  returns `allowed=False, escalate=True, category="self_harm"` **and** surfaces
  `crisis_guidance` (a support message) via `evaluate(...)` → `ModerationOutcome`. Crisis
  takes precedence over every other category.
- **Block path.** Other categories (`abuse`, `hate`, `harassment`, `sexual`, `violence`,
  `illicit`) above `block_threshold` → `allowed=False` (no escalation). The offending
  category + score are written to the **abuse log**.
- **Fail closed.** Any classifier exception → `allowed=False, escalate=True,
  category="error"`.
- **Lazy classifier.** Set `safety.moderation.gate.load_classifier` to inject a real model
  (e.g. an aux text-brain classifier). Until then a deterministic regex/keyword lexicon is
  used. Nothing heavy imports at module top-level.
- **Auditable.** Every decision appends an `AuditEvent` to `gate.audit` (in-memory + a
  JSON log line). Filter with `gate.audit.filter(action=..., outcome=...)`.

## 11B — Voice policy (`VoicePolicy` + `ConsentStore`)

Enforces the frozen rule: **no arbitrary public voice cloning**.

- **Consent-first.** A `VoiceRequest` for a non-default voice is **REFUSED** unless a valid
  `ConsentRecord` exists with (a) matching `voice_ref_id`, (b) the requested action in its
  permitted-use `scopes`, (c) an active (non-expired, non-revoked) timestamp, and (d) an
  intact HMAC `token`. Refusal is indicated by `decision.refused == True`.
- **No retention on refusal.** Every refusal path purges the voice reference
  (`retained=False`, `store.is_retained(ref) == False`) — a denied request leaves no trace.
- **Protected-voice list.** Requests against a registered/protected voice never auto-approve;
  they escalate to **admin review** (`escalate_admin_review=True`).
- **Spoofing checks.** A forged/tampered consent token fails HMAC verification → refused
  with `category="spoofing"`. An optional `SpoofDetector` (e.g. ECAPA-TDNN based) can be
  injected; `P(spoof) >= threshold` → refused. Detector errors fail closed.
- **100% policy compliance.** There is no "allow on uncertainty" branch: without valid
  consent the answer is always REFUSE.
- **Consent log.** `record_consent`, `revoke_consent`, and every `evaluate` decision are
  appended to the auditable log (`store.consent_log()`).

Refusal reason codes: `no_consent`, `spoofing`, `scope_mismatch`, `expired`, `revoked`,
`protected_voice`, `error`.

## 11C — Watermarking (`Watermarker`)

- **Every output path, including fallbacks.** Route all synthesized audio (speech decoder,
  Phase 10; classic STT→LLM→TTS fallback, Phase 13) through `Watermarker.protect(samples,
  sample_rate)` **before emission**. It embeds + self-verifies and returns
  `(WatermarkedAudio, WatermarkResult)`.
- **Non-compliant ⇒ not emitted.** Emit only when `result.compliant` is True. Use
  `watermarker.assert_compliant(result)` as a hard gate (raises `WatermarkComplianceError`).
- **AudioSeal interface + deterministic fallback.** `WatermarkBackend` matches the AudioSeal
  `embed`/`detect` shape. Inject a real model via
  `safety.watermark.audioseal.load_audioseal_backend`. The CPU-only
  `DeterministicFallbackBackend` applies an inaudible marker and an HMAC signature over the
  post-embed audio digest, so tampering, a missing mark, or a forged marker all fail
  verification.
- **Detector-outcome logging.** Every `verify`/`protect` appends an `AuditEvent`
  (`compliant` / `non_compliant`) to `watermarker.audit`.
- **Ops tooling.** `ops_status()` reports backend + a self-check; `python -m
  safety.watermark.audioseal` prints it as JSON (exit non-zero if the self-check fails).

---

## Structured logging hooks (Definition of Done §3.3)

`safety/contracts.py` provides `get_logger(name)` (stdlib `logging` + `NullHandler`, so the
library is quiet by default and never reconfigures global logging on import) and `AuditLog`,
which records `AuditEvent`s **and** emits one JSON line per event. A host app attaches a
handler (or routes `safety.*` loggers into the `server/` structlog pipeline) to ship the
moderation abuse log, the consent/decision log, and the watermark detector log to a sink.

We deliberately use stdlib `logging` (not `structlog`) here so the subsystem stays
dependency-light and importable on a bare CPU checkout.

---

## Configuration (`.env.example`)

| Key | Meaning |
|---|---|
| `MODERATION_ENABLED` / `MODERATION_FAIL_CLOSED` | Enable the gate / fail-closed posture. |
| `VOICE_CONSENT_REQUIRED` | Consent-first enforcement (keep `true` in production). |
| `PROTECTED_VOICE_LIST_PATH` | Source of protected/registered voice ids. |
| `WATERMARK_ENABLED` / `WATERMARK_MODEL_PATH` / `WATERMARK_DETECT_THRESHOLD` | AudioSeal backend + detector threshold. |
| `SAFETY_HMAC_SECRET` | HMAC secret for consent tokens + fallback watermark markers. **Set a real secret in production**; a deterministic dev default is used otherwise. |

---

## Integration notes for other teams

- **Speech / decoder team (Phase 10)** and **aux / fallback team (Phase 13):** call
  `Watermarker.protect(...)` on **every** synthesized output (primary, filler, and fallback
  TTS) and only emit when `result.compliant` is True (`assert_compliant` to hard-gate).
- **Anyone doing voice cloning / style transfer:** call `VoicePolicy.evaluate(VoiceRequest)`
  **before** any cloning and only proceed when `decision.allowed`. Never persist a voice
  reference for a refused/escalated request.
- **Conversation pipeline:** run `ModerationGate.moderate_text` / `moderate_speech` on the
  turn; on `escalate` surface `crisis_guidance` and flag for human review; on a non-allowed
  decision, block the turn.

## Running

```bash
python -c "import safety.moderation.gate, safety.voice_policy.policy, safety.watermark.audioseal"
python -m pytest safety/tests -q
python -m safety.watermark.audioseal   # ops self-check (JSON)
```
