# `roadmap.evaluation_harness`

Public API of the `roadmap.evaluation_harness` component. Generated from live signatures and docstrings.

## class `EvaluationHarness`

```python
EvaluationHarness(sample_items: 'int' = 8) -> 'None'
```

Produces comparable, fully mocked :class:`HarnessRun` records.

The harness applies an identical metric key set (:data:`METRIC_KEYS`), an
identical bounded probe sample, and identical scoring scales to every
candidate, so the records it emits are directly comparable
(Requirements 4.1, 4.2). Each record carries the model identifier, the
revision, the three metric scores, the categorical license-compatibility
value, and the hardware used as ``{gpu_class, vram_gb}`` (Requirement 4.3).

The harness is fully mocked: it derives every score deterministically from
the candidate's mocked seeds and identity over an in-memory sample bounded
by :data:`MAX_ITEMS`, and never performs a GPU or model-training run
(Requirement 4.6).

Args:
    sample_items: The size of the small probe sample evaluated per
        candidate. Must be in the inclusive range ``1..MAX_ITEMS``.

### Methods

#### `evaluate`

```python
evaluate(self, candidate: 'MockCandidate') -> 'HarnessRun'
```

Evaluate a single candidate and return its comparable record.

A candidate that *cannot* be evaluated is recorded as **excluded**
instead of being scored (Requirements 4.5, 11.4). The exclusion
conditions are checked in a fixed precedence order
(:meth:`_detect_exclusion`); when one matches, the returned
:class:`HarnessRun` has ``excluded=True``, an ``exclusion_category``
from :data:`EXCLUSION_CATEGORIES`, a descriptive ``exclusion_reason``,
and the documented sentinel **empty** ``metric_scores`` (no measurement
was performed). The candidate's ``license_compat`` and ``hardware`` are
still recorded, since both are known without measurement.

Otherwise the candidate is scored on the happy path, producing a record
with the identical metric key set and scales as every other
non-excluded candidate (Requirements 4.1, 4.2, 4.3).

#### `evaluate_all`

```python
evaluate_all(self, candidates: 'Sequence[MockCandidate]') -> 'list[HarnessRun]'
```

Evaluate every candidate, returning one record per candidate.

Non-excluded records share the identical metric key set and scoring
scale, so they are directly comparable across candidates (Requirement
4.1). A candidate that cannot be evaluated is recorded as excluded and
the loop continues to the remaining candidates without aborting
(Requirements 4.5, 11.4), so the returned list always has exactly one
record per input candidate, preserving order.

#### `reproduce`

```python
reproduce(self, candidate: 'MockCandidate', runs: 'int' = 3) -> 'ReproducibilityReport'
```

Re-run a candidate ``runs`` times and check per-metric reproducibility.

Evaluates ``candidate`` ``runs`` times on the same mocked inputs and
hardware and verifies that, per metric, the scores across runs stay
within the documented tolerance (latency ±10% relative, quality and
expressiveness ±2 points absolute) — Requirement 4.4. The check is
implemented generally via :func:`within_tolerance` (each run compared to
the reference/first run), so it remains meaningful even though the
underlying derivation is fully deterministic and the runs are therefore
byte-identical and trivially within tolerance.

An **excluded** candidate carries no measured metrics: every run yields
the same empty ``metric_scores`` (exclusion is deterministic too), so
the report is returned with empty ``metrics`` and ``reproducible=True``,
with ``excluded`` / ``exclusion_category`` reflecting why no metric was
measured.

Args:
    candidate: The candidate to re-run.
    runs: How many times to evaluate the candidate. Must be
        ``>= MIN_REPRODUCIBILITY_RUNS`` (3); Requirement 4.4 mandates "at
        least three times".

Returns:
    A :class:`ReproducibilityReport` with the per-metric values across
    runs, each metric's ``within_tolerance`` flag, and an overall
    ``reproducible`` flag.

Raises:
    TypeError: If ``candidate`` is not a :class:`MockCandidate` or
        ``runs`` is not an ``int``.
    ValueError: If ``runs`` is below :data:`MIN_REPRODUCIBILITY_RUNS`.


## class `MockCandidate`

```python
MockCandidate(model_id: 'str', revision: 'str', seeds: 'dict[str, float]' = <factory>, license_compat: 'LicenseCompat' = 'compatible', hardware: 'dict' = <factory>, weights_available: 'bool' = True) -> None
```

A mocked Candidate_Model input for the evaluation harness.

A candidate is a small data carrier — never real weights. It supplies the
identity recorded on the run plus deterministic *measurement seeds* the
harness derives scores from.

Attributes:
    model_id: The Candidate_Model identifier, e.g.
        ``"kyutai/moshiko-pytorch-bf16"``.
    revision: The model version/revision the mocked measurements apply to.
    seeds: Mock measurement seeds keyed by metric name (any of
        :data:`METRIC_KEYS`). A missing metric defaults to seed ``0.0``.
        Different seeds yield different (but deterministic) scores.
    license_compat: The categorical license-compatibility result recorded
        on the run (Requirement 4.2). A value of ``"prohibited"`` marks the
        candidate as excludable under the ``"license"`` category.
    hardware: The hardware descriptor ``{"gpu_class": str, "vram_gb": float}``
        recorded on the run (Requirement 4.3). When ``vram_gb`` is below
        :data:`REQUIRED_MIN_VRAM_GB` the candidate is excludable under the
        ``"hardware"`` category.
    weights_available: Whether the candidate's weights can be loaded. The
        explicit marker for the ``"missing_weights"`` exclusion condition:
        ``False`` means the model cannot be evaluated at all
        (Requirements 4.5, 11.4). Defaults to ``True``.


## class `ReproducibilityReport`

```python
ReproducibilityReport(model_id: 'str', revision: 'str', runs: 'int', metrics: 'dict[str, MetricReproducibility]', reproducible: 'bool', excluded: 'bool' = False, exclusion_category: 'str | None' = None) -> None
```

The result of re-running one candidate to check reproducibility.

Produced by :meth:`EvaluationHarness.reproduce`. It records the candidate
identity, the number of runs performed, the per-metric outcomes, and a
single ``reproducible`` flag that is true iff every measured metric stayed
within its documented tolerance across all runs (Requirement 4.4).

An **excluded** candidate has no measured metrics: ``metrics`` is empty and
``reproducible`` is ``True`` (trivially — exclusion is deterministic, so
every run agrees that no measurement was performed). ``excluded`` and
``exclusion_category`` mirror the underlying :class:`HarnessRun` so callers
can tell a trivially-reproducible exclusion apart from a measured one.

Attributes:
    model_id: The re-run candidate's model identifier.
    revision: The re-run candidate's revision.
    runs: The number of evaluations performed (``>= MIN_REPRODUCIBILITY_RUNS``).
    metrics: Per-metric reproducibility records, keyed by metric. Empty when
        the candidate was excluded.
    reproducible: ``True`` iff every metric in ``metrics`` is within
        tolerance (vacuously ``True`` when there are no measured metrics).
    excluded: Whether the candidate was excluded from measurement.
    exclusion_category: The exclusion category when ``excluded`` is true,
        else ``None``.


## class `MetricReproducibility`

```python
MetricReproducibility(metric_key: 'str', values: 'tuple[float, ...]', tolerance_kind: 'str', tolerance_amount: 'float', within_tolerance: 'bool') -> None
```

Per-metric reproducibility outcome across a candidate's re-runs.

Attributes:
    metric_key: The metric this record describes (one of
        :data:`METRIC_KEYS`).
    values: The metric's value from each run, in run order.
    tolerance_kind: The tolerance rule applied — either
        :data:`TOLERANCE_KIND_RELATIVE_PCT` or
        :data:`TOLERANCE_KIND_ABSOLUTE_POINTS`.
    tolerance_amount: The tolerance magnitude (percent for a relative rule,
        points for an absolute rule).
    within_tolerance: Whether every value is within ``tolerance_amount`` of
        the reference (first) run, per :func:`within_tolerance`.


## `within_tolerance`

```python
within_tolerance(metric_key: 'str', values: 'Sequence[float]') -> 'bool'
```

Return whether ``values`` for ``metric_key`` agree within its tolerance.

Applies the documented per-metric reproducibility rule from
:data:`METRIC_TOLERANCES` (Requirement 4.4):

* ``latency_ms_p50`` uses a **relative** tolerance of ±10%: every value must
  lie within ``LATENCY_TOLERANCE_PCT`` percent of the *reference* value (the
  first value in ``values``).
* ``codeswitch_quality`` and ``expressiveness`` use an **absolute** tolerance
  of ±2 points: every value must lie within that many points of the
  reference value, on the metric's own ``0..100`` scale.

The check compares each run against the first run rather than just the
min/max spread so the "reference run ± tolerance" semantics are explicit and
match the design's "re-running … yields … scores within a documented
per-metric tolerance" wording. The first value is the reference.

Args:
    metric_key: One of :data:`METRIC_KEYS`. An unknown key raises
        ``KeyError`` so a typo never silently passes.
    values: The metric's value from each run, in run order. An empty
        sequence is vacuously within tolerance (no runs disagree); a single
        value is trivially within tolerance.

Returns:
    ``True`` iff every value is within the metric's tolerance of the
    reference (first) value.
