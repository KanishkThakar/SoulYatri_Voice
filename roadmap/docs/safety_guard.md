# `roadmap.safety_guard`

Public API of the `roadmap.safety_guard` component. Generated from live signatures and docstrings.

## class `SafetyGuard`

```python
SafetyGuard(watermark_detector: 'Optional[WatermarkDetector]' = None) -> 'None'
```

LEAN-scope safety subsystem.

This class implements the **watermarking** responsibility (Requirement
10.2), the **consent gating + consent log** responsibility (Requirements
10.1, 10.3, 10.6), and the **crisis handling** responsibility (Requirements
10.4, 10.5). Each responsibility is an independent method group; crisis
handling was added purely additively and shares no mutable state with the
other groups.

Args:
    watermark_detector: The detector used to verify an applied watermark.
        Defaults to a fresh :class:`WatermarkDetector`. Injectable so the
        guard can be exercised against a detector that reports failure (the
        "watermark cannot be verified" path).

### Methods

#### `watermark_detector` _(property)_

The detector this guard uses to verify applied watermarks.

#### `apply_watermark`

```python
apply_watermark(self, output: 'SynthesizedOutput') -> 'SynthesizedOutput'
```

Apply a watermark to ``output`` regardless of which path produced it.

Watermarking is unconditional: it is applied on *every* output path,
including the Phase 1 and TTS fallback paths (Requirement 10.2). The
watermark token is derived deterministically from the output's content
and path, so re-applying is idempotent. The same ``output`` instance is
returned with its ``watermark`` field populated.

#### `guard_output`

```python
guard_output(self, content: 'str', path: 'str') -> 'EmissionResult'
```

Watermark a synthesized output and gate its emission on verification.

On every path (core or fallback) the output is watermarked, then the
watermark detector is asked to verify it. If the watermark is reported
as detected the output is compliant and emittable; if it cannot be
verified the output is flagged non-compliant and withheld rather than
emitted (Requirement 10.2).

Args:
    content: Opaque stand-in for the synthesized audio payload.
    path: The output path that produced the output (e.g. one of
        :data:`OUTPUT_PATHS`).

Returns:
    An :class:`EmissionResult` describing the watermarked output, the
    compliance decision, and whether the output is emitted.

#### `evaluate_output`

```python
evaluate_output(self, output: 'SynthesizedOutput') -> 'EmissionResult'
```

Watermark an existing output (if needed) and gate its emission.

Equivalent to :meth:`guard_output` but for a pre-built
:class:`SynthesizedOutput`; the watermark is (re)applied so the
every-path guarantee holds even for outputs handed in already-formed.

#### `evaluate_cloning_request`

```python
evaluate_cloning_request(self, consent: 'Optional[ConsentRecord]', *, product_facing: 'bool' = True) -> 'CloningDecision'
```

Decide a cloning / voice-style-transfer request against consent.

The request is allowed **if and only if** a *valid*
:class:`~roadmap.models.runtime.ConsentRecord` is supplied — i.e.
``speaker_id``, ``permitted_use_scope`` and ``timestamp`` are all
present and non-empty, as reported by
:meth:`ConsentRecord.is_valid` (Requirement 10.1).

- **Valid consent →** returns ``CloningDecision(allowed=True, ...,
  reference_retained=True)``. When ``product_facing`` is ``True`` the
  consent is also recorded into the product-facing consent log so the
  three fields are retained while the voice is in use (Requirement
  10.6).
- **Missing/invalid consent →** the request is refused: returns
  ``CloningDecision(allowed=False, ...)`` with a reason that indicates
  the refusal, and ``reference_retained=False`` so no voice reference is
  kept without valid consent (Requirement 10.3). Nothing is added to the
  consent log.

Args:
    consent: The consent record for the speaker, or ``None`` when no
        consent was recorded.
    product_facing: Whether this voice is being used in a product-facing
        capacity. Only product-facing, validly consented voices are
        added to the retained consent log (Requirement 10.6).

Returns:
    The :class:`~roadmap.models.runtime.CloningDecision` for the request.

#### `request_cloning`

```python
request_cloning(self, consent: 'Optional[ConsentRecord]', *, speaker_id: 'Optional[str]' = None, product_facing: 'bool' = True) -> 'CloningDecision'
```

Request cloning / voice-style transfer for a speaker's voice.

Thin, task-facing entry point that names the operation the way a caller
thinks about it ("request to clone this voice"); it delegates to
:meth:`evaluate_cloning_request`, which holds the authoritative
consent-gating logic (Requirements 10.1, 10.3, 10.6).

The request is allowed **if and only if** a *valid*
:class:`~roadmap.models.runtime.ConsentRecord` is supplied — all three
fields (``speaker_id``, ``permitted_use_scope``, ``timestamp``) present
and non-empty. Otherwise it is refused: the returned
:class:`~roadmap.models.runtime.CloningDecision` has ``allowed=False``,
a ``reason`` that indicates the refusal, and ``reference_retained=False``
so no voice reference is kept without valid consent (Requirement 10.3).
When allowed and ``product_facing`` is true, the consent is recorded
into the retained product-facing consent log (Requirement 10.6).

Args:
    consent: The consent record for the speaker, or ``None`` when no
        consent was recorded.
    speaker_id: Optional speaker identifier for the requested voice. When
        supplied alongside a valid ``consent`` whose ``speaker_id``
        differs, the request is refused (the consent does not cover the
        requested speaker), and no reference is retained.
    product_facing: Whether this voice is being used in a product-facing
        capacity; only product-facing, validly consented voices enter the
        retained consent log.

Returns:
    The :class:`~roadmap.models.runtime.CloningDecision` for the request.

#### `record_consent`

```python
record_consent(self, consent: 'ConsentRecord') -> 'ConsentLogEntry'
```

Record a valid consent into the product-facing consent log.

Adds (or refreshes) the entry for the consenting speaker and marks the
voice as in use, so the three consent fields are retained while the
voice remains in product-facing use (Requirement 10.6). Every logged
entry is itself valid — an invalid consent record is rejected before it
can enter the log.

Args:
    consent: A valid consent record for a product-facing voice.

Returns:
    The :class:`ConsentLogEntry` now retained in the log.

Raises:
    ValueError: If ``consent`` is not valid (any field missing/empty).

#### `mark_voice_not_in_use`

```python
mark_voice_not_in_use(self, speaker_id: 'str') -> 'bool'
```

Mark a voice as no longer in product-facing use and drop its entry.

Enforces the "retained while in use" half of Requirement 10.6: once a
voice is no longer product-facing, its consent-log entry is released
from the active retained log.

Args:
    speaker_id: The speaker whose voice is no longer in use.

Returns:
    ``True`` if an entry was present and removed, ``False`` otherwise.

#### `retire_voice`

```python
retire_voice(self, speaker_id: 'str') -> 'bool'
```

Retire a product-facing voice: drop its retained consent-log entry.

Task-facing alias for :meth:`mark_voice_not_in_use`. Named the way a
caller thinks about ending a voice's product-facing life ("retire this
voice"); it performs exactly the same retention release, enforcing the
"retained *while in use*" half of Requirement 10.6 — once retired, the
voice's three consent fields are no longer held in the active log.

Args:
    speaker_id: The speaker whose voice is being retired.

Returns:
    ``True`` if an entry was present and removed, ``False`` otherwise.

#### `is_voice_in_use`

```python
is_voice_in_use(self, speaker_id: 'str') -> 'bool'
```

Return ``True`` iff a retained consent-log entry exists for the voice.

#### `get_consent_log_entry`

```python
get_consent_log_entry(self, speaker_id: 'str') -> 'Optional[ConsentLogEntry]'
```

Return the retained consent-log entry for ``speaker_id``, if any.

#### `consent_log`

```python
consent_log(self) -> 'list[ConsentLogEntry]'
```

Return the current product-facing consent log as a list.

Every returned entry carries the three consent fields (speaker id,
permitted-use scope, timestamp) and is valid; only voices currently in
product-facing use are present (Requirement 10.6). The returned list is
a fresh snapshot, so callers cannot mutate the guard's internal state.

#### `handle_crisis`

```python
handle_crisis(self, crisis_score: 'float', *, threshold: 'float' = 0.5, guidance: 'str' = "It sounds like you may be going through something really difficult. You don't have to face this alone — please consider reaching out to a trusted person or a local crisis/helpline service right now. If you are in immediate danger, contact your local emergency number.") -> 'CrisisDecision'
```

Apply the crisis decision to an (upstream) classifier score.

The crisis classifier is upstream and out of scope here; this method
owns only the *decision* applied to its real-valued ``crisis_score``.
The threshold comparison is **inclusive** at the boundary:

- ``crisis_score >= threshold`` → both required actions fire together:
  crisis-support guidance is surfaced to the user **and** the turn is
  flagged for human review (Requirements 10.4, 10.5). The returned
  :class:`CrisisDecision` has ``crisis_support_surfaced=True``,
  ``flagged_for_human_review=True`` and carries the ``guidance`` text.
- ``crisis_score < threshold`` → **neither** action fires: both booleans
  are ``False`` and ``guidance`` is ``None``.

A score exactly equal to ``threshold`` therefore triggers both actions
(the boundary is inclusive).

Args:
    crisis_score: The crisis classifier's score for the turn (a real
        number; conventionally in ``[0.0, 1.0]`` but not required to be).
    threshold: The decision threshold to compare against, inclusive at
        the boundary. Defaults to :data:`CRISIS_DECISION_THRESHOLD`.
    guidance: The crisis-support guidance text to surface when the
        decision triggers. Defaults to :data:`CRISIS_SUPPORT_GUIDANCE`.

Returns:
    A frozen :class:`CrisisDecision` recording whether each action fired,
    the ``crisis_score`` and ``threshold`` it was decided on, and the
    surfaced ``guidance`` (or ``None`` when below threshold).


## class `SynthesizedOutput`

```python
SynthesizedOutput(content: 'str', path: 'str', watermark: 'Optional[str]' = None) -> None
```

An abstract synthesized audio output payload.

The audio itself is modelled opaquely as ``content`` (any string stand-in
for the synthesized waveform/token stream). ``path`` records which output
path produced it so the watermark guarantee can be asserted per path, and
``watermark`` holds the applied watermark token (``None`` until a watermark
has been applied).

Attributes:
    content: Opaque stand-in for the synthesized audio payload.
    path: The output path that produced this output (e.g. one of
        :data:`OUTPUT_PATHS`); must be a non-empty identifier.
    watermark: The applied watermark token, or ``None`` if not yet applied.

### Methods

#### `is_watermarked` _(property)_

``True`` iff a non-empty watermark token has been applied.


## class `EmissionResult`

```python
EmissionResult(output: 'SynthesizedOutput', compliant: 'bool', emitted: 'bool', watermark_detected: 'bool', reason: 'str' = '') -> None
```

The outcome of watermarking and compliance-checking an output.

An output is emittable only when its watermark is verified as detected. When
verification fails, the output is flagged non-compliant and withheld
(``emitted=False``) rather than released (Requirement 10.2).

Attributes:
    output: The (watermarked) :class:`SynthesizedOutput`.
    compliant: ``True`` iff the watermark was verified as detected.
    emitted: ``True`` iff the output is released; equals ``compliant``.
    watermark_detected: The raw detector verdict for the output.
    reason: Human-readable explanation of the decision.


## class `WatermarkDetector`

```python
WatermarkDetector()
```

A deterministic, mocked watermark detector.

Stands in for a real audio-watermark detector. It verifies that an output
carries the expected watermark token for its content under
:data:`WATERMARK_SCHEME`. Detection succeeds only when a watermark is
present *and* matches the token that :meth:`expected_watermark` derives from
the output's content and path, so a missing or tampered watermark is
correctly reported as *not detected*.

The detector is intentionally injectable into :class:`SafetyGuard` so the
guard can re-verify what it just embedded, and so tests can substitute a
detector that fails to model the "watermark cannot be verified" case.

### Methods

#### `expected_watermark`

```python
expected_watermark(self, content: 'str', path: 'str') -> 'str'
```

Return the canonical watermark token for ``content`` on ``path``.

The token is a deterministic function of the content and path, so the
same output always yields the same watermark and the detector can
recompute and compare it without any shared mutable state.

#### `detect`

```python
detect(self, output: 'SynthesizedOutput') -> 'bool'
```

Return ``True`` iff ``output`` carries a verifiable watermark.


## class `ConsentLogEntry`

```python
ConsentLogEntry(speaker_id: 'str', permitted_use_scope: 'str', timestamp: 'float', in_use: 'bool' = True) -> None
```

One product-facing consent-log record for a voice in use.

The consent log is the product-facing record the design's *Safety Guard*
requires for **every** voice used in a product-facing capacity. Each entry
carries exactly the three consent fields — ``speaker_id``,
``permitted_use_scope`` and ``timestamp`` — and is retained while the voice
remains in product-facing use (Requirement 10.6).

Retention semantics: an entry is kept (``in_use=True``) for as long as the
voice it describes is in product-facing use. Marking the voice as no longer
in use flips ``in_use`` to ``False``, which the :class:`SafetyGuard` uses to
drop the entry from the active retained log — so "retained while in use" is
enforced explicitly rather than by indefinite accumulation.

Every entry is itself valid: it is only ever constructed from a valid
:class:`~roadmap.models.runtime.ConsentRecord` (all three fields present and
non-empty), and :meth:`is_valid` re-checks that invariant.

Attributes:
    speaker_id: The consenting speaker's identifier (non-empty).
    permitted_use_scope: The scope the speaker consented to (non-empty).
    timestamp: The consent timestamp as a float epoch value (> 0).
    in_use: ``True`` while the voice remains in product-facing use.

### Methods

#### `from_consent`

```python
from_consent(consent: 'ConsentRecord', *, in_use: 'bool' = True) -> "'ConsentLogEntry'"
```

Build a log entry from a (valid) consent record.

Raises:
    ValueError: If ``consent`` is not valid (any of the three fields
        missing/empty), so an invalid entry can never enter the log.

#### `is_valid`

```python
is_valid(self) -> 'bool'
```

Return ``True`` iff all three consent fields are present and non-empty.


## class `CrisisDecision`

```python
CrisisDecision(crisis_support_surfaced: 'bool', flagged_for_human_review: 'bool', score: 'float', threshold: 'float', guidance: 'Optional[str]' = None) -> None
```

The outcome of applying the crisis decision to a classifier score.

Crisis handling is an all-or-nothing pair of actions tied to a single
threshold comparison (Requirements 10.4, 10.5):

- When the crisis-classifier ``score`` is **at or above** the decision
  ``threshold`` (``score >= threshold`` — the boundary is *inclusive*), both
  actions fire together: crisis-support guidance is surfaced to the user
  (``crisis_support_surfaced=True``, with the guidance in ``guidance``) and
  the turn is flagged for human review (``flagged_for_human_review=True``).
- When ``score`` is **strictly below** ``threshold`` neither action fires:
  both booleans are ``False`` and ``guidance`` is ``None``.

The two booleans therefore always move together, and :meth:`triggered`
reports that shared verdict. The instance is frozen so a recorded decision
cannot be mutated after the fact.

Attributes:
    crisis_support_surfaced: ``True`` iff crisis-support guidance was
        surfaced to the user.
    flagged_for_human_review: ``True`` iff the turn was flagged for human
        review.
    score: The crisis-classifier score the decision was made on.
    threshold: The decision threshold compared against (inclusive).
    guidance: The crisis-support guidance text surfaced, or ``None`` when
        the decision did not trigger.

### Methods

#### `triggered` _(property)_

``True`` iff crisis handling fired (both actions occurred together).
