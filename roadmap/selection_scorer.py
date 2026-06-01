"""Weighted selection of the Speech-Native Core from Candidate_Models.

This module implements the :class:`SelectionScorer` decision-logic component
described in the design's *Selection Scorer* section. It is a pure function of
its inputs (no hidden state, no I/O) and is therefore verifiable by the
property-based test for **Property 3: Speech-Native Core selection**
(tasks 8.2/8.3).

Selection logic (Requirements 2.4, 2.7, 2.9)
--------------------------------------------
1. **Score every candidate against every criterion.** Each candidate is scored
   against all six weighted criteria in :data:`SELECTION_CRITERIA`. A criterion
   score that is absent from a candidate's ``scores`` map is treated as ``0.0``
   (fail-closed), so a candidate can never pass a minimum it did not report.
2. **``passes_all_minimums``.** A candidate passes all minimums *iff*, for every
   criterion ``c``, its score is ``>= SELECTION_MINIMUMS[c]`` (Requirement 2.9
   per-criterion minimum gate).
3. **No qualifying candidate -> retain Phase 1.** When *no* candidate passes
   every per-criterion minimum, the selection is :data:`RETAIN_PHASE_1`: the
   roadmap retains the Phase_1_Pipeline as the production path until a qualifying
   model is available (Requirement 2.7).
4. **Otherwise select the argmax.** When at least one candidate passes every
   minimum, the selected core is the *passing* candidate with the highest
   weighted aggregate score (Requirement 2.9). Non-passing candidates are never
   selected even if their aggregate is higher.

Weighted-aggregate formula
---------------------------
For each candidate the weighted aggregate is the weight-normalized average of
its per-criterion scores::

    aggregate = sum(score[c] * SELECTION_WEIGHTS[c] for c in criteria)
                / sum(SELECTION_WEIGHTS.values())

Because :data:`SELECTION_WEIGHTS` sum to exactly 100, this is equivalent to
``sum(score[c] * SELECTION_WEIGHTS[c]) / 100`` and keeps the aggregate on the
same ``0..100`` scale as the inputs. The aggregate is computed for **every**
candidate (passing or not) and exposed in ``SelectionOutcome.aggregates`` for
transparency and reporting; selection itself is restricted to passing
candidates.

Tie-break rule
--------------
When two or more *passing* candidates share the single highest weighted
aggregate, the winner is the one that appears **first in the input order**
(stable first-wins). This is fully deterministic for a given input ordering and
is the behavior exercised by the task 8.3 tie-break unit test. The chosen
formula above intentionally keeps aggregates exact (no rounding) so that ties
only occur on genuinely equal scores rather than rounding artifacts.

Phase_1 concurrent-fallback policy
----------------------------------
Selecting a Speech-Native Core does **not** retire the Phase_1_Pipeline. Per
Requirement 2.8, when a qualifying core is selected the roadmap retains the
Phase_1_Pipeline as an *additional* fallback path that runs **concurrently
alongside** the selected core until that core has passed the LEAN_Track
Launch_Gate. Only the launch gate clears Phase 1 from the active fallback path.
This scorer reports the selection decision; the concurrent-fallback retention it
implies is enforced downstream by the runtime router and the gate evaluator.
When the outcome is :data:`RETAIN_PHASE_1`, Phase 1 remains the sole production
path (no core was adopted).
"""

from __future__ import annotations

from .models.selection import (
    RETAIN_PHASE_1,
    SELECTION_CRITERIA,
    SELECTION_MINIMUMS,
    SELECTION_WEIGHTS,
    CandidateScores,
    SelectionOutcome,
)

__all__ = ["SelectionScorer"]


class SelectionScorer:
    """Select the Speech-Native Core via weighted, minimum-gated scoring.

    The scorer is configured with the weighted criteria and per-criterion
    minimum pass thresholds (defaulting to the canonical
    :data:`SELECTION_WEIGHTS` / :data:`SELECTION_MINIMUMS` tables from the
    design). It is otherwise stateless: :meth:`select` is a pure function of the
    candidate scores passed to it.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        minimums: dict[str, float] | None = None,
    ) -> None:
        """Create a scorer.

        Args:
            weights: Optional override for the per-criterion weights. Defaults to
                the canonical :data:`SELECTION_WEIGHTS`. The criterion key set
                must match ``minimums``.
            minimums: Optional override for the per-criterion minimum pass
                thresholds. Defaults to the canonical :data:`SELECTION_MINIMUMS`.

        Raises:
            ValueError: If ``weights`` and ``minimums`` cover different criteria,
                or if any weight is non-positive.
        """
        self._weights: dict[str, float] = dict(
            weights if weights is not None else SELECTION_WEIGHTS
        )
        self._minimums: dict[str, float] = dict(
            minimums if minimums is not None else SELECTION_MINIMUMS
        )

        if set(self._weights) != set(self._minimums):
            raise ValueError(
                "weights and minimums must cover the same criteria; "
                f"got weights={sorted(self._weights)} "
                f"minimums={sorted(self._minimums)}"
            )
        if not self._weights:
            raise ValueError("at least one weighted criterion is required")
        if any(w <= 0 for w in self._weights.values()):
            raise ValueError("every criterion weight must be positive")

        # Stable, canonical criterion order: prefer the design's declared order
        # when using the default table, otherwise sort for determinism.
        if set(self._weights) == set(SELECTION_CRITERIA):
            self._criteria: tuple[str, ...] = tuple(SELECTION_CRITERIA)
        else:
            self._criteria = tuple(sorted(self._weights))

        self._weight_total: float = float(sum(self._weights.values()))

    @property
    def criteria(self) -> tuple[str, ...]:
        """The criteria, in canonical evaluation order."""
        return self._criteria

    def aggregate(self, candidate: CandidateScores) -> float:
        """Return the weight-normalized aggregate score for one candidate.

        Missing criterion scores are treated as ``0.0`` (fail-closed). See the
        module docstring for the formula.

        Args:
            candidate: The candidate whose scores are aggregated.

        Returns:
            The weighted aggregate on the ``0..100`` scale.
        """
        weighted_sum = 0.0
        for criterion in self._criteria:
            score = float(candidate.scores.get(criterion, 0.0))
            weighted_sum += score * self._weights[criterion]
        return weighted_sum / self._weight_total

    def passes_all_minimums(self, candidate: CandidateScores) -> bool:
        """Return whether a candidate meets every per-criterion minimum.

        A criterion absent from the candidate's ``scores`` is treated as ``0.0``
        and therefore fails any positive minimum (fail-closed).

        Args:
            candidate: The candidate to test.

        Returns:
            ``True`` iff ``score[c] >= minimum[c]`` for every criterion ``c``.
        """
        return all(
            float(candidate.scores.get(criterion, 0.0)) >= self._minimums[criterion]
            for criterion in self._criteria
        )

    def select(self, candidates: list[CandidateScores]) -> SelectionOutcome:
        """Select the Speech-Native Core from a list of scored candidates.

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
        """
        aggregates: dict[str, float] = {}
        passing: list[str] = []

        for candidate in candidates:
            aggregates[candidate.model_id] = self.aggregate(candidate)
            if self.passes_all_minimums(candidate):
                passing.append(candidate.model_id)

        if not passing:
            # No candidate clears every per-criterion minimum (Requirement 2.7):
            # retain the Phase_1_Pipeline as the production path until a
            # qualifying model is available.
            return SelectionOutcome(
                selected=RETAIN_PHASE_1,
                aggregates=aggregates,
                passing=passing,
            )

        # Argmax over passing candidates only (Requirement 2.9). ``passing`` is
        # in input order, so taking the first model that attains the maximum
        # aggregate implements the documented first-wins tie-break rule.
        best_aggregate = max(aggregates[model_id] for model_id in passing)
        selected = next(
            model_id
            for model_id in passing
            if aggregates[model_id] == best_aggregate
        )

        return SelectionOutcome(
            selected=selected,
            aggregates=aggregates,
            passing=passing,
        )
