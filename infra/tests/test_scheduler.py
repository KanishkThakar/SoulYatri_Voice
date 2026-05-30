"""
Tests for infra.scaling.scheduler (Phase 16A).

Covers the §16A acceptance shape "sessions do not starve each other":
  * admission onto bounded workers + least-loaded placement,
  * sticky session->worker routing (idempotent re-admit),
  * queueing with a max depth + explicit backpressure rejection when saturated,
  * release frees a slot and promotes the FIFO head from the queue,
  * reject-policy backpressure (no queue).
"""

from __future__ import annotations

from infra.scaling import (
    AdmissionStatus,
    BackpressurePolicy,
    GpuClass,
    GpuEnvelope,
    SessionProfile,
    SessionScheduler,
)


def _env(max_sessions: int) -> GpuEnvelope:
    """A GpuEnvelope whose VRAM math yields exactly ``max_sessions`` slots."""
    gpu = GpuClass(name="test", total_vram_mb=1000 * max_sessions, reserved_vram_mb=0)
    profile = SessionProfile(name="unit", vram_mb_per_session=1000)
    return GpuEnvelope(gpu=gpu, profile=profile)


def test_admits_until_capacity_then_backpressure() -> None:
    sched = SessionScheduler([_env(2)], max_queue_depth=1)
    assert sched.pool_capacity == 2

    a = sched.admit("s1")
    b = sched.admit("s2")
    assert a.status is AdmissionStatus.admitted
    assert b.status is AdmissionStatus.admitted
    assert sched.active_count == 2
    assert sched.is_saturated()

    # Pool full -> goes to the queue (depth 1).
    c = sched.admit("s3")
    assert c.status is AdmissionStatus.queued
    assert c.queue_position == 0
    assert sched.queue_depth == 1

    # Pool + queue full -> rejected (explicit backpressure).
    d = sched.admit("s4")
    assert d.status is AdmissionStatus.rejected
    assert d.accepted is False
    assert "saturated" in d.reason


def test_sticky_routing_is_idempotent() -> None:
    sched = SessionScheduler([_env(1), _env(1)], max_queue_depth=0)
    first = sched.admit("sess-A")
    assert first.status is AdmissionStatus.admitted
    worker = first.worker_id
    assert worker is not None

    # Re-admitting the same id returns the SAME worker and does not consume capacity.
    again = sched.admit("sess-A")
    assert again.status is AdmissionStatus.already_active
    assert again.worker_id == worker
    assert sched.active_count == 1
    assert sched.worker_for("sess-A") == worker


def test_least_loaded_placement_spreads_sessions() -> None:
    sched = SessionScheduler([_env(2), _env(2)], max_queue_depth=0)
    placements = {sid: sched.admit(sid).worker_id for sid in ("s1", "s2", "s3", "s4")}
    # 4 sessions across 2 workers of capacity 2 -> 2 each (no starvation).
    snap = sched.snapshot()
    loads = sorted(w["load"] for w in snap["workers"].values())
    assert loads == [2, 2]
    assert len(set(placements.values())) == 2


def test_release_promotes_queued_session() -> None:
    sched = SessionScheduler([_env(1)], max_queue_depth=2)
    sched.admit("live")
    q1 = sched.admit("wait-1")
    q2 = sched.admit("wait-2")
    assert q1.status is AdmissionStatus.queued
    assert q2.status is AdmissionStatus.queued
    assert sched.queue_depth == 2

    promoted = sched.release("live")
    assert promoted == "wait-1"  # FIFO order
    assert sched.is_active("wait-1")
    assert sched.worker_for("wait-1") is not None
    assert sched.queue_depth == 1
    assert sched.is_queued("wait-2")


def test_release_unknown_session_is_safe() -> None:
    sched = SessionScheduler([_env(1)])
    assert sched.release("never-existed") is None


def test_release_queued_only_session_drops_from_queue() -> None:
    sched = SessionScheduler([_env(1)], max_queue_depth=2)
    sched.admit("live")
    sched.admit("queued-1")
    assert sched.is_queued("queued-1")
    # Releasing a session that is only queued removes it from the queue.
    assert sched.release("queued-1") is None
    assert not sched.is_queued("queued-1")
    assert sched.queue_depth == 0


def test_reject_policy_never_queues() -> None:
    sched = SessionScheduler(
        [_env(1)], max_queue_depth=5, backpressure=BackpressurePolicy.reject
    )
    sched.admit("s1")
    r = sched.admit("s2")
    assert r.status is AdmissionStatus.rejected
    assert sched.queue_depth == 0
    assert "queueing disabled" in r.reason


def test_named_worker_map_is_respected() -> None:
    sched = SessionScheduler({"gpu-a": _env(1), "gpu-b": _env(1)})
    assert sorted(sched.worker_ids) == ["gpu-a", "gpu-b"]
    res = sched.admit("s1")
    assert res.worker_id in ("gpu-a", "gpu-b")


def test_empty_workers_rejected() -> None:
    try:
        SessionScheduler([])
    except ValueError as e:
        assert "at least one worker" in str(e)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError for empty worker pool")


def test_snapshot_shape() -> None:
    sched = SessionScheduler([_env(2)], max_queue_depth=1)
    sched.admit("s1")
    snap = sched.snapshot()
    assert snap["pool_capacity"] == 2
    assert snap["active_count"] == 1
    assert snap["backpressure"] == "queue"
    assert "workers" in snap and "queue" in snap


def test_admit_blank_session_id_rejected() -> None:
    sched = SessionScheduler([_env(1)])
    try:
        sched.admit("")
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError for empty session_id")
