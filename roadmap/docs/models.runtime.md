# `roadmap.models.runtime`

Public API of the `roadmap.models.runtime` component. Generated from live signatures and docstrings.

## class `HarnessRun`

```python
HarnessRun(model_id: 'str', revision: 'str', metric_scores: 'dict[str, float]', license_compat: "Literal['compatible', 'restricted', 'prohibited']", hardware: 'dict', excluded: 'bool' = False, exclusion_category: 'Optional[str]' = None, exclusion_reason: 'Optional[str]' = None) -> None
```

A single (mocked) evaluation record for one candidate model.

Every candidate is scored against an identical metric key set and scale so
runs are directly comparable. ``metric_scores`` carries at least
``latency_ms_p50``, ``codeswitch_quality`` and ``expressiveness``.

When a candidate cannot be evaluated (missing weights, license, or
hardware), ``excluded`` is set and ``exclusion_category`` /
``exclusion_reason`` explain why, while the harness continues with the
remaining candidates (Requirement 4.5).


## class `EmotionFeatures`

```python
EmotionFeatures(label: 'Optional[str]', confidence: 'float', valence: 'float', arousal: 'float', dominance: 'float', extraction_ok: 'bool') -> None
```

Speech-emotion features used to pick a persona conditioning mode.

Valence, arousal and dominance are clamped into ``[-1.0, 1.0]`` on
construction so the controller can never receive out-of-range values, even
if an upstream extractor reports an unbounded score (Requirement 6.1).

``label`` may be ``None`` and ``extraction_ok`` ``False`` when emotion
extraction failed or was unavailable; the controller falls back to a
neutral persona in that case while the turn still continues.


## class `ConsentRecord`

```python
ConsentRecord(speaker_id: 'str', permitted_use_scope: 'str', timestamp: 'float') -> None
```

A speaker-consent record gating cloning / voice-style transfer.

Consent is considered valid only when all three fields are present and
non-empty (Requirement 10.1). ``timestamp`` is stored as a float epoch
value; ``0.0`` / missing is treated as not present.

### Methods

#### `is_valid`

```python
is_valid(self) -> 'bool'
```

Return ``True`` iff all three consent fields are present and non-empty.

Strings must be non-empty after stripping surrounding whitespace, and
``timestamp`` must be a present, non-empty positive value. A missing
timestamp is represented as ``0.0`` (or ``None``) and is therefore
invalid.


## class `CloningDecision`

```python
CloningDecision(allowed: 'bool', reason: 'str', reference_retained: 'bool') -> None
```

The result of evaluating a cloning / voice-style-transfer request.

When the request is refused (``allowed=False``), ``reference_retained`` must
be ``False`` so no reference audio is kept without valid consent
(Requirement 10.3).


## class `LicenseEntry`

```python
LicenseEntry(component_name: 'str', license_id: 'Optional[str]', constraints: 'list[str]', intended_use_permitted: 'bool', recorded_before_use: 'bool', redistribution_restricted: 'bool' = False, restriction_type: 'Optional[str]' = None) -> None
```

A licensing record for an adopted component, captured before use.

``license_id`` is a recognized OSS identifier, or ``None`` when recording
failed (in which case adoption is allowed but an unresolved
:class:`ComplianceWarning` is retained). ``redistribution_restricted`` and
``restriction_type`` flag datasets that restrict redistribution or require
consent (Requirement 11.2, 11.6).


## class `ComplianceWarning`

```python
ComplianceWarning(component_name: 'str', resolved: 'bool') -> None
```

An outstanding licensing/compliance warning tied to a component.


## class `NormalizationResult`

```python
NormalizationResult(normalized_text: 'str', unmapped_tokens: 'list[str]' = <factory>) -> None
```

The result of Hinglish transliteration normalization.

Tokens with no mapping entry are retained unchanged inside
``normalized_text`` and also reported in ``unmapped_tokens`` so they can be
flagged for review (Requirement 5.8).
