"""
infra.scaling — per-session budgeting & admission control (final_use.md §16A).

Pure-Python, deterministic, CPU-only. No cluster, GPU, or live services required.

Public API:
    * :class:`SessionScheduler` — bounded concurrent sessions, a max-depth queue with
      backpressure/rejection, and sticky session->worker routing.
    * :class:`AdmissionResult` / :class:`AdmissionStatus` / :class:`BackpressurePolicy`
      — the auditable admission outcomes.
    * :class:`GpuEnvelope` / :class:`GpuClass` / :class:`SessionProfile` — the GPU
      resource-envelope model (max sessions per GPU class/VRAM).
"""

from infra.scaling.envelopes import (
    COMMON_GPU_CLASSES,
    MOSHI_SESSION_PROFILE,
    GpuClass,
    GpuEnvelope,
    SessionProfile,
)
from infra.scaling.scheduler import (
    AdmissionResult,
    AdmissionStatus,
    BackpressurePolicy,
    SessionScheduler,
    WorkerState,
)

__all__ = [
    "SessionScheduler",
    "AdmissionResult",
    "AdmissionStatus",
    "BackpressurePolicy",
    "WorkerState",
    "GpuClass",
    "GpuEnvelope",
    "SessionProfile",
    "COMMON_GPU_CLASSES",
    "MOSHI_SESSION_PROFILE",
]
