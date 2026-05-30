"""
infra.scaling.envelopes — GPU resource envelopes (Phase 16A)
============================================================
A pure-Python, deterministic model of *how many concurrent sessions a worker may
host* given the GPU class it runs on and the per-session VRAM cost.

final_use.md §16A requires explicit **GPU resource envelopes** so sessions "do not
starve each other". This module encodes that as plain data:

* :class:`GpuClass` — a named GPU SKU with total VRAM and an optional hard cap on
  concurrent sessions (operator policy, independent of memory math).
* :class:`SessionProfile` — the per-session resource cost (VRAM + a coarse compute
  weight) for a given workload (e.g. the Moshi speech-native runtime).
* :class:`GpuEnvelope` — combines the two and computes ``max_sessions`` as the
  *minimum* of the VRAM-derived capacity and the operator hard cap.

No torch / CUDA / nvml imports — this is a budgeting model, not a probe. It is the
input the :class:`~infra.scaling.scheduler.SessionScheduler` uses to size each worker.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "GpuClass",
    "SessionProfile",
    "GpuEnvelope",
    "COMMON_GPU_CLASSES",
    "MOSHI_SESSION_PROFILE",
]


@dataclass(frozen=True)
class GpuClass:
    """A named GPU SKU and its capacity-relevant attributes.

    Attributes:
        name: Human-readable SKU id (e.g. ``"L4"``, ``"A10G"``, ``"cpu"``).
        total_vram_mb: Total device memory in MiB. ``0`` means "no GPU" (CPU-only).
        reserved_vram_mb: Memory held back for the framework/driver/activations and
            not available to sessions.
        max_concurrent_sessions: Optional operator hard cap on sessions regardless of
            the VRAM math (``None`` = no extra cap). Useful to protect compute, PCIe,
            or thermals even when memory would allow more.
    """

    name: str
    total_vram_mb: int
    reserved_vram_mb: int = 0
    max_concurrent_sessions: int | None = None

    def __post_init__(self) -> None:
        if self.total_vram_mb < 0:
            raise ValueError("total_vram_mb must be >= 0")
        if self.reserved_vram_mb < 0:
            raise ValueError("reserved_vram_mb must be >= 0")
        if self.reserved_vram_mb > self.total_vram_mb:
            raise ValueError("reserved_vram_mb cannot exceed total_vram_mb")
        if self.max_concurrent_sessions is not None and self.max_concurrent_sessions < 0:
            raise ValueError("max_concurrent_sessions must be >= 0 when set")

    @property
    def available_vram_mb(self) -> int:
        """VRAM available to sessions after the framework reservation."""
        return self.total_vram_mb - self.reserved_vram_mb


@dataclass(frozen=True)
class SessionProfile:
    """The per-session resource cost of a workload on a GPU.

    Attributes:
        name: Workload id (e.g. ``"moshi-fp16"``).
        vram_mb_per_session: Steady-state VRAM cost of one live session in MiB.
        compute_weight: Coarse relative compute cost (1.0 = one "unit"). Used by the
            scheduler to reason about saturation beyond raw memory if desired.
    """

    name: str
    vram_mb_per_session: int
    compute_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.vram_mb_per_session <= 0:
            raise ValueError("vram_mb_per_session must be > 0")
        if self.compute_weight <= 0:
            raise ValueError("compute_weight must be > 0")


@dataclass(frozen=True)
class GpuEnvelope:
    """Capacity of a single worker = (GPU class) × (session profile).

    ``max_sessions`` is the binding constraint: the smaller of how many sessions fit
    in available VRAM and the operator's hard cap.
    """

    gpu: GpuClass
    profile: SessionProfile

    @property
    def vram_capacity(self) -> int:
        """Max sessions permitted by available VRAM alone."""
        return self.gpu.available_vram_mb // self.profile.vram_mb_per_session

    @property
    def max_sessions(self) -> int:
        """Binding per-worker concurrency = min(VRAM capacity, operator hard cap)."""
        cap = self.vram_capacity
        if self.gpu.max_concurrent_sessions is not None:
            cap = min(cap, self.gpu.max_concurrent_sessions)
        return max(cap, 0)

    def fits(self, current_sessions: int) -> bool:
        """Whether one more session can be admitted at ``current_sessions`` load."""
        return current_sessions < self.max_sessions

    def headroom(self, current_sessions: int) -> int:
        """Remaining admissible sessions at the given current load (never negative)."""
        return max(self.max_sessions - current_sessions, 0)

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly snapshot for logging/telemetry."""
        return {
            "gpu_class": self.gpu.name,
            "total_vram_mb": self.gpu.total_vram_mb,
            "reserved_vram_mb": self.gpu.reserved_vram_mb,
            "available_vram_mb": self.gpu.available_vram_mb,
            "profile": self.profile.name,
            "vram_mb_per_session": self.profile.vram_mb_per_session,
            "vram_capacity": self.vram_capacity,
            "max_sessions": self.max_sessions,
        }


# ---------------------------------------------------------------------------
# Reference catalogue (documentation defaults — not pinned hardware decisions)
# ---------------------------------------------------------------------------
# Coarse, well-known GPU memory sizes. Operators override these for their fleet.
COMMON_GPU_CLASSES: dict[str, GpuClass] = {
    "cpu": GpuClass(name="cpu", total_vram_mb=0, max_concurrent_sessions=2),
    "T4": GpuClass(name="T4", total_vram_mb=16_000, reserved_vram_mb=2_000),
    "L4": GpuClass(name="L4", total_vram_mb=24_000, reserved_vram_mb=2_000),
    "A10G": GpuClass(name="A10G", total_vram_mb=24_000, reserved_vram_mb=2_000),
    "A100-40": GpuClass(name="A100-40", total_vram_mb=40_000, reserved_vram_mb=3_000),
    "A100-80": GpuClass(name="A100-80", total_vram_mb=80_000, reserved_vram_mb=4_000),
}

# A coarse default profile for the Moshi speech-native runtime (fp16-class).
# This is a planning placeholder; pin real numbers from a load test (see infra/README.md).
MOSHI_SESSION_PROFILE = SessionProfile(
    name="moshi-fp16",
    vram_mb_per_session=3_500,
    compute_weight=1.0,
)
