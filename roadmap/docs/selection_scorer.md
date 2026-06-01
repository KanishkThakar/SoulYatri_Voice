# `roadmap.selection_scorer`

Public API of the `roadmap.selection_scorer` component. Generated from live signatures and docstrings.

## class `SelectionScorer`

```python
SelectionScorer(weights: 'dict[str, float] | None' = None, minimums: 'dict[str, float] | None' = None) -> 'None'
```

Select the Speech-Native Core via weighted, minimum-gated scoring.

The scorer is configured with the weighted criteria and per-criterion
minimum pass thresholds (defaulting to the canonical
:data:`SELECTION_WEIGHTS` / :data:`SELECTION_MINIMUMS` tables from the
design). It is otherwise stateless: :meth:`select` is a pure function of the
candidate scores passed to it.

### Methods

#### `criteria` _(property)_

The criteria, in canonical evaluation order.

#### `aggregate`

```python
aggregate(self, candidate: 'CandidateScores') -> 'float'
```

Return the weight-normalized aggregate score for one candidate.

Missing criterion scores are treated as ``0.0`` (fail-closed). See the
module docstring for the formula.

Args:
    candidate: The candidate whose scores are aggregated.

Returns:
    The weighted aggregate on the ``0..100`` scale.

#### `passes_all_minimums`

```python
passes_all_minimums(self, candidate: 'CandidateScores') -> 'bool'
```

Return whether a candidate meets every per-criterion minimum.

A criterion absent from the candidate's ``scores`` is treated as ``0.0``
and therefore fails any positive minimum (fail-closed).

Args:
    candidate: The candidate to test.

Returns:
    ``True`` iff ``score[c] >= minimum[c]`` for every criterion ``c``.

#### `select`

```python
select(self, candidates: 'list[CandidateScores]') -> 'SelectionOutcome'
```

Select the Speech-Native Core from a list of scored candidates.

Args:
    candidates: The Candidate_Models with their per-criterion scores. The
        input order is significant: it defines the tie-break order
        (first-wins) when passing candidates share the top aggregate.

Returns:
    A :class:`SelectionOutcome` whose ``aggregates`` map covers *every*
    candidate, whose ``passing`` list names the candidates meeting every
    minimum (in input order), and whose ``selected`` is either the
    highest-aggregate passing candidate or :data:`RETAIN_PHASE_1` when no
    candidate passes every minimum.
