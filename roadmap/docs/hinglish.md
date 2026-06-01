# `roadmap.hinglish`

Public API of the `roadmap.hinglish` component. Generated from live signatures and docstrings.

## class `HinglishDataEngine`

```python
HinglishDataEngine(mapping: 'dict[str, str] | None' = None) -> 'None'
```

Deterministic Romanized↔Devanagari normalization for Hinglish text.

The engine holds the transliteration mapping in both directions as instance
attributes so the *same* table backs input normalization (Romanized →
Devanagari) and output rendering (Devanagari → Romanized):

- ``self._roman_to_deva``: Romanized token → Devanagari token.
- ``self._deva_to_roman``: Devanagari token → canonical Romanized token
  (first Romanized spelling seen for each Devanagari form).

:meth:`normalize` canonicalizes input to Devanagari: a recognized Romanized
token is replaced by its Devanagari form, a token that is *already* a
recognized Devanagari form is passed through unchanged (it is "mapped", so it
is not flagged), and any token absent from the mapping is retained unchanged
and reported as unmapped (Requirement 5.8).

Determinism (Requirement 5.5) follows from the normalization being a pure,
order-independent dictionary lookup per token with no randomness or mutable
shared state: ``normalize(s)`` always returns the same result for the same
``s``.

### Methods

#### `mapping_size` _(property)_

Number of Romanized → Devanagari entries in the loaded mapping.

#### `normalize`

```python
normalize(self, text: 'str') -> 'NormalizationResult'
```

Normalize ``text`` to its canonical Devanagari form.

Tokenizes ``text`` on whitespace (preserving the original spacing) and,
for each token:

- replaces a recognized Romanized token with its Devanagari form
  (input-normalization direction);
- passes through a token that is already a recognized Devanagari form
  unchanged (it is part of the mapping, so it is *not* flagged);
- otherwise retains the token unchanged in ``normalized_text`` and also
  appends it to ``unmapped_tokens`` for review (Requirement 5.8).

The transformation is a pure per-token dictionary lookup, so the same
input always yields the same output (Requirement 5.5).

Args:
    text: The input string to normalize.

Returns:
    A :class:`NormalizationResult` whose ``normalized_text`` is the
    rebuilt string and whose ``unmapped_tokens`` lists, in order of
    occurrence, every token that had no mapping entry.

#### `he_ratio`

```python
he_ratio(self, text: 'str') -> 'float'
```

Return the Hindi-to-English (H/E) ratio of ``text`` as a percentage.

The ratio is ``100 * hindi / (hindi + english)`` over the classifiable
word tokens of ``text`` (see the module docstring for the definition).
Text with no classifiable Hindi/English tokens has a ratio of ``0.0``.

Args:
    text: The text whose H/E ratio is computed.

Returns:
    The H/E ratio on a ``0.0..100.0`` percentage scale.

#### `score`

```python
score(self, input: 'str', output: 'str') -> 'CodeSwitchScore'
```

Score the code-switch quality of a single (input, output) pair.

A response is **within tolerance** iff the absolute difference between
its H/E ratio and the input's H/E ratio is at most 15 percentage points
(Requirement 5.4). The returned :class:`CodeSwitchScore` carries the
input ratio, the output ratio, the absolute difference in percentage
points, the ``within_tolerance`` boolean, and a per-pair ``quality``
percentage (``100.0`` within tolerance, ``0.0`` otherwise).

Args:
    input: The code-switched user input text.
    output: The system response text.

Returns:
    The structured :class:`CodeSwitchScore` for the pair.

#### `within_tolerance`

```python
within_tolerance(self, input: 'str', output: 'str') -> 'bool'
```

Return whether a single (input, output) pair is within tolerance.

Convenience boolean wrapper over :meth:`score`: a response is **within
tolerance** iff the absolute difference between its H/E ratio and the
input's H/E ratio is at most :data:`TOLERANCE_PCT` (15) percentage points
(Requirement 5.4). Equivalent to ``self.score(input, output)
.within_tolerance`` but returned directly as a ``bool`` for callers that
only need the pass/fail decision.

Args:
    input: The code-switched user input text.
    output: The system response text.

Returns:
    ``True`` iff ``|output H/E ratio - input H/E ratio| <= 15`` pp.

#### `benchmark_passes`

```python
benchmark_passes(eval_set_score: 'float') -> 'bool'
```

Return whether an evaluation-set score passes the Hinglish benchmark.

A build passes iff the evaluation-set score is at or above the 80%
threshold (Requirement 5.6). When this returns ``False``, the roadmap's
remediation is lightweight adaptation (LoRA/adapters) on the
Hinglish_Data_Engine output before any custom-model work (Requirement
5.7); see :data:`LORA_ADAPTATION_HOOK`.

Args:
    eval_set_score: The evaluation-set score as a percentage
        (``0.0..100.0``).

Returns:
    ``True`` iff ``eval_set_score >= 80.0``.

#### `evaluate_benchmark`

```python
evaluate_benchmark(self, pairs: 'Iterable[tuple[str, str]]') -> 'BenchmarkResult'
```

Aggregate per-pair code-switch results into a benchmark result.

Each ``(input, output)`` pair is scored with :meth:`score`; the
evaluation-set score is the percentage of pairs within tolerance, and
the build passes iff that score is ``>= 80%`` (Requirement 5.6). When
the build does not pass, ``adaptation_hook`` names the
lightweight-adaptation (LoRA/adapters) remediation applied before any
custom-model work (Requirement 5.7).

Args:
    pairs: An iterable of ``(input, output)`` text pairs.

Returns:
    A :class:`BenchmarkResult` with the per-pair scores, the
    within-tolerance count, the total, the evaluation-set percentage,
    the pass flag, and the adaptation hook (``None`` when passing).


## class `CodeSwitchScore`

```python
CodeSwitchScore(input_ratio: 'float', output_ratio: 'float', difference_pp: 'float', within_tolerance: 'bool', quality: 'float') -> None
```

The code-switch quality result for one (input, output) pair.

Ratios are H/E percentages on a ``0.0..100.0`` scale (see the module
docstring for the H/E ratio definition). ``difference_pp`` is the absolute
gap between the two ratios expressed in **percentage points**.

Attributes:
    input_ratio: The input text's H/E ratio (percentage).
    output_ratio: The response text's H/E ratio (percentage).
    difference_pp: ``abs(output_ratio - input_ratio)`` in percentage points.
    within_tolerance: ``True`` iff ``difference_pp <= 15.0`` (Requirement
        5.4).
    quality: The per-pair quality score as a percentage — ``100.0`` when
        within tolerance, ``0.0`` otherwise — on the same scale as the
        evaluation-set aggregate.


## class `BenchmarkResult`

```python
BenchmarkResult(per_pair: 'list[CodeSwitchScore]', within_tolerance_count: 'int', total: 'int', eval_set_score: 'float', passes: 'bool', adaptation_hook: 'str | None') -> None
```

The aggregate Hinglish code-switch benchmark result over a pair set.

Attributes:
    per_pair: The per-pair :class:`CodeSwitchScore` results, in input order.
    within_tolerance_count: Number of pairs that were within tolerance.
    total: Total number of pairs evaluated.
    eval_set_score: The evaluation-set score as a percentage —
        ``100 * within_tolerance_count / total`` (``0.0`` for an empty set).
    passes: ``True`` iff ``eval_set_score >= 80.0`` (Requirement 5.6).
    adaptation_hook: Human-readable designation of the next remediation step
        when the benchmark does **not** pass: lightweight LoRA/adapter
        adaptation on the Hinglish_Data_Engine output, applied *before* any
        custom-model work (Requirement 5.7). ``None`` when the build passes.
