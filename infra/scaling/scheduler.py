"""
infra.scaling.scheduler — per-session budgeting & admission control (Phase 16A)
================================================================================
A real, deterministic, pure-Python scheduler that implements the four 16A controls
from final_use.md:

* **worker-pool sizing** — a fixed pool of workers, each sized by a
  :class:`~infra.scaling.envelopes.GpuEnvelope` (max sessions per GPU class/VRAM);
* **bounded concurrent sessions** — global capacity = sum of per-worker envelopes;
* **queue limits + backpressure** — a FIFO admit-queue with a max depth; when both the
  live pool and the queue are full, new sessions are **rejected** (explicit
  backpressure) rather than silently dropped or unbounded-buffered;
* **sticky-session routing** — a given ``session_id`` always maps to the same worker
  for the life of the session (speaker/emotion state continuity, per INTERFACES.md §5),
  and re-admitting the same id is idempotent.

Everything is synchronous, side-effect-free (besides telemetry/logging), and
deterministic so it unit-tests without a cluster, GPU, or live services.

Acceptance (final_use.md §16A): "load tests show sessions do not starve each other."
The scheduler guarantees this by (a) never exceeding a worker's envelope, (b) spreading
admissions to the least-loaded worker, and (c) bounding the queue so latency is finite.
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field

from infra.obs import get_logger, telemetry
from infra.scaling.envelopes import GpuEnvelope

__all__ = [
    "AdmissionStatus",
    "AdmissionResult",
    "BackpressurePolicy",
    "WorkerState",
    "SessionScheduler",
]

logger = get_logger("infra.scaling.scheduler")


class AdmissionStatus(str, enum.Enum):
    """Outcome of an admission attempt."""

    admitted = "admitted"          # placed on a worker immediately
    queued = "queued"              # pool full, accepted into the bounded queue
    rejected = "rejected"          # pool + queue full -> backpressure
    already_active = "already_active"  # idempotent re-admit of a live session


class BackpressurePolicy(str, enum.Enum):
    """What to do when the live pool is saturated.

    * ``queue`` — buffer up to ``max_queue_depth`` then reject (default).
    * ``reject`` — never queue; reject immediately once the pool is full.
    """

    queue = "queue"
    reject = "reject"


@dataclass
class AdmissionResult:
    """Structured, auditable result of :meth:`SessionScheduler.admit`."""

    session_id: str
    status: AdmissionStatus
    worker_id: str | None = None
    queue_position: int | None = None
    reason: str = ""

    @property
    def accepted(self) -> bool:
        """True when the session is live or queued (i.e. not rejected)."""
        return self.status in (
            AdmissionStatus.admitted,
            AdmissionStatus.queued,
            AdmissionStatus.already_active,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "queue_position": self.queue_position,
            "reason": self.reason,
        }


@dataclass
class WorkerState:
    """Live state of a single worker in the pool."""

    worker_id: str
    envelope: GpuEnvelope
    sessions: set[str] = field(default_factory=set)

    @property
    def load(self) -> int:
        return len(self.sessions)

    @property
    def capacity(self) -> int:
        return self.envelope.max_sessions

    @property
    def has_room(self) -> bool:
        return self.load < self.capacity

    def utilization(self) -> float:
        return (self.load / self.capacity) if self.capacity else 1.0


class SessionScheduler:
    """Bounded, sticky, backpressure-aware session admission controller.

    Thread-safe (a single lock guards all mutation) so it can be shared across the
    gateway's request handlers. All decisions emit a telemetry event named
    ``infra_admission`` for observability.
    """

    def __init__(
        self,
        workers: list[GpuEnvelope] | dict[str, GpuEnvelope],
        *,
        max_queue_depth: int = 0,
        backpressure: BackpressurePolicy = BackpressurePolicy.queue,
    ) -> None:
        if not workers:
            raise ValueError("SessionScheduler requires at least one worker envelope")
        if max_queue_depth < 0:
            raise ValueError("max_queue_depth must be >= 0")

        self._lock = threading.RLock()
        self._backpressure = backpressure
        self._max_queue_depth = max_queue_depth

        # Build the worker pool. Accept either a list (auto-named) or an id->envelope map.
        self._workers: dict[str, WorkerState] = {}
        if isinstance(workers, dict):
            items = list(workers.items())
        else:
            items = [(f"worker-{i}", env) for i, env in enumerate(workers)]
        for wid, env in items:
            self._workers[wid] = WorkerState(worker_id=wid, envelope=env)

        # Sticky routing table + bounded FIFO queue of waiting session ids.
        self._sticky: dict[str, str] = {}        # session_id -> worker_id (live only)
        self._queue: list[str] = []               # FIFO of queued session ids
        self._queued_set: set[str] = set()        # membership for O(1) idempotency

    # ------------------------------------------------------------------
    # Capacity introspection
    # ------------------------------------------------------------------
    @property
    def pool_capacity(self) -> int:
        """Total live-session capacity across all workers."""
        return sum(w.capacity for w in self._workers.values())

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(w.load for w in self._workers.values())

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def max_queue_depth(self) -> int:
        return self._max_queue_depth

    @property
    def worker_ids(self) -> list[str]:
        return list(self._workers.keys())

    def is_saturated(self) -> bool:
        """True when the live pool has no room on any worker."""
        with self._lock:
            return not any(w.has_room for w in self._workers.values())

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------
    def admit(self, session_id: str) -> AdmissionResult:
        """Attempt to admit ``session_id``.

        Resolution order (explicit + auditable):
          1. already live  -> ``already_active`` (idempotent, returns sticky worker).
          2. already queued -> ``queued`` (idempotent, returns its position).
          3. a worker has room -> place on the least-loaded worker (``admitted``).
          4. pool full, policy=queue, queue has room -> enqueue (``queued``).
          5. otherwise -> ``rejected`` (backpressure).
        """
        if not session_id:
            raise ValueError("session_id must be a non-empty string")

        with self._lock:
            result = self._admit_locked(session_id)

        telemetry.record(
            "infra_admission",
            session_id=session_id,
            status=result.status.value,
            worker_id=result.worker_id,
            active=self.active_count,
            queued=self.queue_depth,
        )
        logger.info(
            "session_admission",
            session_id=session_id,
            status=result.status.value,
            worker_id=result.worker_id,
            reason=result.reason,
        )
        return result

    def _admit_locked(self, session_id: str) -> AdmissionResult:
        # 1. Idempotent re-admit of a live session -> same worker.
        if session_id in self._sticky:
            wid = self._sticky[session_id]
            return AdmissionResult(
                session_id=session_id,
                status=AdmissionStatus.already_active,
                worker_id=wid,
                reason="session already active (sticky)",
            )

        # 2. Idempotent re-admit of a queued session -> same position.
        if session_id in self._queued_set:
            return AdmissionResult(
                session_id=session_id,
                status=AdmissionStatus.queued,
                queue_position=self._queue.index(session_id),
                reason="session already queued",
            )

        # 3. Place on the least-loaded worker that has room.
        worker = self._pick_worker_locked()
        if worker is not None:
            worker.sessions.add(session_id)
            self._sticky[session_id] = worker.worker_id
            return AdmissionResult(
                session_id=session_id,
                status=AdmissionStatus.admitted,
                worker_id=worker.worker_id,
                reason="placed on least-loaded worker",
            )

        # 4. Pool saturated -> queue if policy allows and there is room.
        if (
            self._backpressure is BackpressurePolicy.queue
            and len(self._queue) < self._max_queue_depth
        ):
            self._queue.append(session_id)
            self._queued_set.add(session_id)
            return AdmissionResult(
                session_id=session_id,
                status=AdmissionStatus.queued,
                queue_position=len(self._queue) - 1,
                reason="pool saturated; enqueued (backpressure)",
            )

        # 5. Reject — explicit backpressure signal to the caller.
        reason = (
            "pool saturated; queueing disabled"
            if self._backpressure is BackpressurePolicy.reject
            else "pool and queue saturated"
        )
        return AdmissionResult(
            session_id=session_id,
            status=AdmissionStatus.rejected,
            reason=reason,
        )

    def _pick_worker_locked(self) -> WorkerState | None:
        """Least-loaded eligible worker; deterministic tie-break by worker_id."""
        candidates = [w for w in self._workers.values() if w.has_room]
        if not candidates:
            return None
        return min(candidates, key=lambda w: (w.load, w.worker_id))

    # ------------------------------------------------------------------
    # Release + queue promotion
    # ------------------------------------------------------------------
    def release(self, session_id: str) -> str | None:
        """End a session, free its slot, and promote the next queued session.

        Returns the ``session_id`` promoted from the queue onto the freed worker, or
        ``None`` if nothing was waiting. The promoted session keeps FIFO fairness.
        """
        with self._lock:
            wid = self._sticky.pop(session_id, None)
            if wid is None:
                # Maybe it was only queued — drop it from the queue if so.
                if session_id in self._queued_set:
                    self._queue.remove(session_id)
                    self._queued_set.discard(session_id)
                    telemetry.record("infra_release", session_id=session_id, was="queued")
                    return None
                telemetry.record("infra_release", session_id=session_id, was="unknown")
                return None

            worker = self._workers[wid]
            worker.sessions.discard(session_id)

            promoted = self._promote_locked(worker)

        telemetry.record(
            "infra_release",
            session_id=session_id,
            worker_id=wid,
            promoted=promoted,
            active=self.active_count,
            queued=self.queue_depth,
        )
        logger.info("session_release", session_id=session_id, worker_id=wid, promoted=promoted)
        return promoted

    def _promote_locked(self, worker: WorkerState) -> str | None:
        """Move the head of the queue onto ``worker`` if it has room."""
        if not self._queue or not worker.has_room:
            return None
        next_id = self._queue.pop(0)
        self._queued_set.discard(next_id)
        worker.sessions.add(next_id)
        self._sticky[next_id] = worker.worker_id
        return next_id

    # ------------------------------------------------------------------
    # Routing introspection
    # ------------------------------------------------------------------
    def worker_for(self, session_id: str) -> str | None:
        """Return the sticky worker id for a live session, else ``None``."""
        with self._lock:
            return self._sticky.get(session_id)

    def is_active(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sticky

    def is_queued(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._queued_set

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, object]:
        """A JSON-friendly view of the whole scheduler for dashboards/tests."""
        with self._lock:
            return {
                "pool_capacity": self.pool_capacity,
                "active_count": self.active_count,
                "queue_depth": len(self._queue),
                "max_queue_depth": self._max_queue_depth,
                "backpressure": self._backpressure.value,
                "saturated": not any(w.has_room for w in self._workers.values()),
                "workers": {
                    wid: {
                        "load": w.load,
                        "capacity": w.capacity,
                        "utilization": round(w.utilization(), 4),
                        "sessions": sorted(w.sessions),
                    }
                    for wid, w in self._workers.items()
                },
                "queue": list(self._queue),
            }
