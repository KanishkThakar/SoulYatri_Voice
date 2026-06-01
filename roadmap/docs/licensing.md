# `roadmap.licensing`

Public API of the `roadmap.licensing` component. Generated from live signatures and docstrings.

## class `LicensingRegister`

```python
LicensingRegister() -> 'None'
```

In-memory register of adopted components, exclusions, and warnings.

All recording happens *before* a component is used in any build, so every
:class:`LicenseEntry` produced here has ``recorded_before_use=True``. A
record whose ``license_id`` could not be resolved to a recognized OSS
identifier is still stored (adoption proceeds) but with ``license_id=None``
and an accompanying unresolved :class:`ComplianceWarning` (Requirement
11.3).

### Methods

#### `record_component`

```python
record_component(self, component_name: 'str', license_id: 'Optional[str]', constraints: 'Optional[list[str]]' = None, *, intended_use_permitted: 'bool' = True, redistribution_restricted: 'bool' = False, restriction_type: 'Optional[str]' = None) -> 'LicenseEntry'
```

Record a component's license before it is used in any build.

Stores ``{component_name, license_id, constraints}`` plus the
intended-use and redistribution flags. ``license_id`` is accepted only
when it is a recognized OSS identifier (see
:data:`RECOGNIZED_OSS_LICENSES`); any other value — including ``None``
or an unrecognised string — is treated as a *failed* license recording:
the entry is still stored with ``license_id=None`` (adoption proceeds)
and an unresolved :class:`ComplianceWarning` is raised and retained for
the component until a recognized identifier is recorded (Requirements
11.1, 11.2, 11.3).

Re-recording the same component with a recognized identifier resolves
any outstanding warning for that component.

Args:
    component_name: The adopted model/dataset/tool name. Must be a
        non-empty string.
    license_id: The OSS license identifier, or ``None`` if unknown.
    constraints: Commercial-use / attribution constraints; defaults to
        an empty list.
    intended_use_permitted: Whether the license permits the intended
        use. ``False`` marks a *prohibiting* license (Requirement 11.7).
    redistribution_restricted: Whether the component's terms restrict
        redistribution or require subject consent (Requirement 11.6).
    restriction_type: The specific restriction type when
        ``redistribution_restricted`` is ``True``.

Returns:
    The stored :class:`LicenseEntry`.

Raises:
    ValueError: If ``component_name`` is empty or blank.

#### `flag_dataset`

```python
flag_dataset(self, component_name: 'str', restriction_type: 'str') -> 'LicenseEntry'
```

Flag a dataset as restricting redistribution / requiring consent.

Records the specific ``restriction_type`` on the dataset's
:class:`LicenseEntry` (Requirement 11.6). While the flag is set,
:meth:`redistribution_allowed` returns ``False`` for the dataset
(Requirement 11.8) until :meth:`satisfy_restriction` clears it.

If the dataset has not been recorded yet, a minimal entry is created
with an unresolved compliance warning for its missing license info, so
the flag is never silently lost.

Args:
    component_name: The dataset name.
    restriction_type: The specific restriction, e.g.
        ``"no-redistribution"`` or ``"subject-consent-required"``. Must
        be a non-empty string.

Returns:
    The updated (or newly created) :class:`LicenseEntry`.

Raises:
    ValueError: If ``restriction_type`` is empty or blank.

#### `satisfy_restriction`

```python
satisfy_restriction(self, component_name: 'str') -> 'None'
```

Mark a dataset's redistribution/consent restriction as satisfied.

Clears the redistribution flag so :meth:`redistribution_allowed` returns
``True`` again (Requirement 11.8). The recorded ``restriction_type`` is
preserved on the entry for audit. No-op if the component is unknown.

#### `record_exclusion`

```python
record_exclusion(self, component_name: 'str', reason: 'str', *, licensing_related: 'bool') -> 'ExclusionRecord'
```

Record an excluded Candidate_Model and its exclusion reason.

Captures the exclusion and whether it was for a *licensing* reason (a
license prohibiting the intended use) or a *non-licensing* reason such
as performance or compatibility (Requirement 11.4).

Args:
    component_name: The excluded Candidate_Model identifier. Must be a
        non-empty string.
    reason: The human-readable exclusion reason. Must be non-empty.
    licensing_related: ``True`` if excluded for a licensing reason,
        ``False`` for a non-licensing reason.

Returns:
    The stored :class:`ExclusionRecord`.

Raises:
    ValueError: If ``component_name`` or ``reason`` is empty or blank.

#### `resolve_warning`

```python
resolve_warning(self, component_name: 'str') -> 'None'
```

Resolve any outstanding compliance warning for a component.

Marks the component's warning ``resolved=True`` in place. No-op when no
warning exists for the component. Note that a warning is only truly
cleared once the missing license info is recorded via
:meth:`record_component`; this method exists for explicit resolution
bookkeeping.

#### `redistribution_allowed`

```python
redistribution_allowed(self, component_name: 'str') -> 'bool'
```

Return whether content from ``component_name`` may be redistributed.

Used by the Hinglish Data Engine: returns ``False`` while the component
is flagged as restricting redistribution or requiring subject consent,
and ``True`` once the restriction is satisfied or when the component was
never flagged (Requirement 11.8). An unknown component is treated as
having no recorded restriction and is therefore allowed.

#### `unresolved_warnings`

```python
unresolved_warnings(self) -> 'list[ComplianceWarning]'
```

Return the list of currently unresolved compliance warnings (11.3).

#### `has_unresolved_warnings`

```python
has_unresolved_warnings(self) -> 'bool'
```

Return ``True`` if any compliance warning is unresolved (11.7).

#### `has_prohibiting_license`

```python
has_prohibiting_license(self) -> 'bool'
```

Return ``True`` if any adopted component prohibits its intended use.

Used by the ``GateEvaluator`` at every Launch_Gate review: a recorded
entry with ``intended_use_permitted=False`` is a prohibiting license
and blocks the release (Requirements 11.5, 11.7).

#### `get_entry`

```python
get_entry(self, component_name: 'str') -> 'Optional[LicenseEntry]'
```

Return the recorded :class:`LicenseEntry` for a component, if any.

#### `entries`

```python
entries(self) -> 'list[LicenseEntry]'
```

Return all recorded license entries.

#### `exclusions`

```python
exclusions(self) -> 'list[ExclusionRecord]'
```

Return all recorded Candidate_Model exclusions (11.4).


## class `ExclusionRecord`

```python
ExclusionRecord(component_name: 'str', reason: 'str', category: 'ExclusionCategory') -> None
```

A record of an excluded Candidate_Model and why it was excluded.

Attributes:
    component_name: The excluded Candidate_Model identifier.
    reason: The human-readable exclusion reason.
    category: ``"licensing"`` when the exclusion is because of a license
        prohibiting the intended use, otherwise ``"non-licensing"`` (for
        performance/compatibility/hardware reasons).
