"""
Tests for infra.scaling.envelopes (Phase 16A — GPU resource envelopes).

Covers: VRAM-derived capacity, operator hard caps as the binding constraint,
headroom/fits helpers, validation, and the reference catalogue.
"""

from __future__ import annotations

import pytest

from infra.scaling import (
    COMMON_GPU_CLASSES,
    MOSHI_SESSION_PROFILE,
    GpuClass,
    GpuEnvelope,
    SessionProfile,
)


def test_vram_capacity_math() -> None:
    gpu = GpuClass(name="L4", total_vram_mb=24_000, reserved_vram_mb=2_000)
    profile = SessionProfile(name="moshi", vram_mb_per_session=3_500)
    env = GpuEnvelope(gpu=gpu, profile=profile)
    # (24000 - 2000) // 3500 = 6
    assert env.vram_capacity == 6
    assert env.max_sessions == 6


def test_operator_hard_cap_is_binding() -> None:
    gpu = GpuClass(
        name="A100-80", total_vram_mb=80_000, reserved_vram_mb=0, max_concurrent_sessions=10
    )
    profile = SessionProfile(name="tiny", vram_mb_per_session=1_000)  # VRAM allows 80
    env = GpuEnvelope(gpu=gpu, profile=profile)
    assert env.vram_capacity == 80
    assert env.max_sessions == 10  # hard cap wins


def test_fits_and_headroom() -> None:
    env = GpuEnvelope(
        gpu=GpuClass(name="x", total_vram_mb=4_000),
        profile=SessionProfile(name="p", vram_mb_per_session=1_000),
    )
    assert env.max_sessions == 4
    assert env.fits(0) is True
    assert env.fits(3) is True
    assert env.fits(4) is False
    assert env.headroom(1) == 3
    assert env.headroom(10) == 0  # never negative


def test_cpu_class_capacity_zero_vram() -> None:
    gpu = COMMON_GPU_CLASSES["cpu"]
    env = GpuEnvelope(gpu=gpu, profile=MOSHI_SESSION_PROFILE)
    # 0 available VRAM -> 0 by VRAM, but cpu hard cap is 2; min(0, 2) == 0.
    assert env.vram_capacity == 0
    assert env.max_sessions == 0


def test_envelope_to_dict_keys() -> None:
    env = GpuEnvelope(gpu=COMMON_GPU_CLASSES["L4"], profile=MOSHI_SESSION_PROFILE)
    d = env.to_dict()
    for key in ("gpu_class", "available_vram_mb", "vram_capacity", "max_sessions"):
        assert key in d


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_vram_mb": -1},
        {"total_vram_mb": 100, "reserved_vram_mb": 200},
        {"total_vram_mb": 100, "max_concurrent_sessions": -1},
    ],
)
def test_gpu_class_validation(kwargs: dict) -> None:
    base = {"name": "bad"}
    with pytest.raises(ValueError):
        GpuClass(**{**base, **kwargs})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"vram_mb_per_session": 0},
        {"vram_mb_per_session": 100, "compute_weight": 0},
    ],
)
def test_session_profile_validation(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        SessionProfile(name="bad", **kwargs)


def test_common_catalogue_is_consistent() -> None:
    for name, gpu in COMMON_GPU_CLASSES.items():
        assert gpu.name == name
        assert gpu.available_vram_mb >= 0
