"""
training/labeling/review.py — Phase 14C consented collection + labeling/review workflow.

Implements the human-in-the-loop gate that makes synthetic (and collected real) data
**filtered, reviewed, and measurable against human eval** before it is eligible for
training. Two pieces:

  1. ``CollectionIntake`` — accepts a candidate record only if it carries valid provenance
     + consent (real utterances must be consented; synthetic is ``not_applicable``).
  2. ``ReviewWorkflow`` — an explicit state machine over each item:

         pending → in_review → (approved | rejected | needs_changes)
         needs_changes → in_review → …

     Only ``approved`` items are exported as training-eligible. Transitions are validated
     (no hidden if-else sprawl, mirroring the edge turn-state discipline) and logged.

CPU/no-weights rule: pure stdlib + pydantic + local schema. Imports cleanly on CPU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from training.data_engine.logging_util import get_logger
from training.data_engine.schema import (
    ConsentError,
    ProvenanceError,
    RecordBase,
    SourceType,
    build_record,
)

__all__ = [
    "ReviewState",
    "ReviewAction",
    "ReviewItem",
    "ReviewTransitionError",
    "ReviewWorkflow",
    "CollectionIntake",
    "ALLOWED_TRANSITIONS",
]

log = get_logger("training.labeling.review")


# ---------------------------------------------------------------------------
# States & actions
# ---------------------------------------------------------------------------
class ReviewState(str, Enum):
    """Lifecycle states for a record under review."""

    pending = "pending"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    needs_changes = "needs_changes"


class ReviewAction(str, Enum):
    """Actions a reviewer can take to drive the state machine."""

    claim = "claim"  # pending/needs_changes -> in_review
    approve = "approve"  # in_review -> approved
    reject = "reject"  # in_review -> rejected
    request_changes = "request_changes"  # in_review -> needs_changes
    resubmit = "resubmit"  # needs_changes -> pending


# Explicit, auditable transition table: state -> {action -> next_state}.
ALLOWED_TRANSITIONS: dict[ReviewState, dict[ReviewAction, ReviewState]] = {
    ReviewState.pending: {
        ReviewAction.claim: ReviewState.in_review,
    },
    ReviewState.in_review: {
        ReviewAction.approve: ReviewState.approved,
        ReviewAction.reject: ReviewState.rejected,
        ReviewAction.request_changes: ReviewState.needs_changes,
    },
    ReviewState.needs_changes: {
        ReviewAction.resubmit: ReviewState.pending,
        ReviewAction.claim: ReviewState.in_review,
    },
    # Terminal states: no outgoing transitions.
    ReviewState.approved: {},
    ReviewState.rejected: {},
}

TERMINAL_STATES = frozenset({ReviewState.approved, ReviewState.rejected})


class ReviewTransitionError(ValueError):
    """Raised on an invalid review-workflow state transition."""


# ---------------------------------------------------------------------------
# Review item
# ---------------------------------------------------------------------------
@dataclass
class ReviewItem:
    """A single record progressing through the review workflow."""

    record: RecordBase
    state: ReviewState = ReviewState.pending
    reviewer: str | None = None
    notes: list[str] = field(default_factory=list)
    history: list[tuple[ReviewState, ReviewAction, ReviewState]] = field(default_factory=list)

    @property
    def sample_id(self) -> str:
        return self.record.sample_id

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


# ---------------------------------------------------------------------------
# Collection intake (consented real-utterance collection)
# ---------------------------------------------------------------------------
class CollectionIntake:
    """Accepts candidate records into the review queue, enforcing provenance + consent.

    Real-utterance collection requires consent; synthetic uses ``not_applicable``. This is
    the front door: records that fail the schema's provenance/consent rule are rejected
    here and never enter the workflow.
    """

    def __init__(self) -> None:
        self.accepted: list[RecordBase] = []
        self.rejected: list[dict] = []

    def submit(self, data: dict) -> RecordBase:
        """Validate and accept a single raw record dict. Raises on missing audit metadata."""
        try:
            record = build_record(data)
        except (ProvenanceError, ConsentError) as exc:
            self.rejected.append({"error": f"{type(exc).__name__}: {exc}", "data": data})
            log.warning("intake_rejected", reason=str(exc))
            raise
        # Real (non-synthetic, non-public) material must be explicitly consented to proceed.
        if (
            record.provenance.source_type == SourceType.real_consented
            and not record.is_training_eligible
        ):
            msg = f"real utterance {record.sample_id} is not consent-eligible for training"
            self.rejected.append({"error": msg, "data": data})
            log.warning("intake_rejected", reason=msg, sample_id=record.sample_id)
            raise ConsentError(msg)
        self.accepted.append(record)
        log.info(
            "intake_accepted",
            sample_id=record.sample_id,
            kind=record.kind.value,
            source_type=record.provenance.source_type.value,
        )
        return record


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------
class ReviewWorkflow:
    """In-memory review queue with an explicit, validated state machine."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}

    # -- queue management ----------------------------------------------------
    def add(self, record: RecordBase) -> ReviewItem:
        """Add a record to the queue in the ``pending`` state."""
        if record.sample_id in self._items:
            raise ValueError(f"duplicate sample_id in review queue: {record.sample_id}")
        item = ReviewItem(record=record)
        self._items[record.sample_id] = item
        log.info("review_enqueued", sample_id=record.sample_id, state=item.state.value)
        return item

    def get(self, sample_id: str) -> ReviewItem:
        return self._items[sample_id]

    def __len__(self) -> int:
        return len(self._items)

    # -- transitions ---------------------------------------------------------
    def apply(
        self,
        sample_id: str,
        action: ReviewAction,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> ReviewItem:
        """Apply an action to an item, validating the transition.

        Raises ``ReviewTransitionError`` if the action is not allowed from the current
        state (terminal states reject all actions).
        """
        item = self._items[sample_id]
        allowed = ALLOWED_TRANSITIONS.get(item.state, {})
        if action not in allowed:
            raise ReviewTransitionError(
                f"action '{action.value}' not allowed from state '{item.state.value}' "
                f"for {sample_id} (allowed: {[a.value for a in allowed]})"
            )
        from_state = item.state
        to_state = allowed[action]
        item.state = to_state
        if reviewer is not None:
            item.reviewer = reviewer
        if note:
            item.notes.append(note)
        item.history.append((from_state, action, to_state))
        log.info(
            "review_transition",
            sample_id=sample_id,
            action=action.value,
            from_state=from_state.value,
            to_state=to_state.value,
            reviewer=reviewer,
        )
        return item

    # -- queries -------------------------------------------------------------
    def items_in_state(self, state: ReviewState) -> list[ReviewItem]:
        return [it for it in self._items.values() if it.state == state]

    def approved_records(self) -> list[RecordBase]:
        """Return records that passed review AND are consent-eligible for training.

        Double gate: ``approved`` by a human reviewer and ``is_training_eligible`` by
        consent. This is the only export path to training.
        """
        out: list[RecordBase] = []
        for it in self._items.values():
            if it.state == ReviewState.approved and it.record.is_training_eligible:
                out.append(it.record)
        return out

    def summary(self) -> dict[str, int]:
        """Counts by state — used by dry-run reporting."""
        counts: dict[str, int] = {s.value: 0 for s in ReviewState}
        for it in self._items.values():
            counts[it.state.value] += 1
        return counts
