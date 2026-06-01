"""
Tests for infra.deploy.regions (Phase 16B).

Covers: nearest-region selection by effective cost, affinity preference, warm-pool
bias, health-based fallback chain, last-resort global best, no-region case, and the
default India-first topology.
"""

from __future__ import annotations

from infra.deploy import (
    GeoPoint,
    Region,
    RegionRouter,
    RouteOutcome,
    WarmPool,
    default_india_first_topology,
)


def _three_region_router() -> RegionRouter:
    return RegionRouter(
        [
            Region(
                name="ap-south-1",
                location=GeoPoint(19.076, 72.8777),  # Mumbai
                edge_latency_ms=4.0,
                fallbacks=["ap-southeast-1", "eu-central-1"],
                warm_pool=WarmPool(warm=2, in_use=0, capacity=8),
            ),
            Region(
                name="ap-southeast-1",
                location=GeoPoint(1.3521, 103.8198),  # Singapore
                edge_latency_ms=5.0,
                fallbacks=["ap-south-1"],
                warm_pool=WarmPool(warm=1, in_use=0, capacity=6),
            ),
            Region(
                name="eu-central-1",
                location=GeoPoint(50.1109, 8.6821),  # Frankfurt
                edge_latency_ms=5.0,
                fallbacks=["ap-south-1"],
                warm_pool=WarmPool(warm=1, in_use=0, capacity=6),
            ),
        ]
    )


def test_nearest_region_chosen_without_preference() -> None:
    router = _three_region_router()
    delhi = GeoPoint(28.6139, 77.2090)  # closest to Mumbai
    route = router.route(delhi)
    assert route.region == "ap-south-1"
    assert route.outcome is RouteOutcome.nearest
    assert route.estimated_latency_ms is not None


def test_affinity_preferred_region_used_when_eligible() -> None:
    router = _three_region_router()
    # A user physically near Frankfurt but with affinity to ap-south-1.
    frankfurt_user = GeoPoint(50.0, 8.0)
    route = router.route(frankfurt_user, preferred_region="ap-south-1")
    assert route.region == "ap-south-1"
    assert route.outcome is RouteOutcome.affinity


def test_fallback_chain_when_preferred_unhealthy() -> None:
    router = _three_region_router()
    router.set_health("ap-south-1", False)
    delhi = GeoPoint(28.6139, 77.2090)
    route = router.route(delhi, preferred_region="ap-south-1")
    assert route.outcome is RouteOutcome.fallback
    assert route.region == "ap-southeast-1"  # first healthy fallback in the chain
    assert "ap-south-1" in route.considered


def test_fallback_skips_unhealthy_chain_links() -> None:
    router = _three_region_router()
    router.set_health("ap-south-1", False)
    router.set_health("ap-southeast-1", False)  # first fallback also down
    delhi = GeoPoint(28.6139, 77.2090)
    route = router.route(delhi, preferred_region="ap-south-1")
    assert route.region == "eu-central-1"  # second fallback
    assert route.outcome is RouteOutcome.fallback


def test_capacity_exhaustion_makes_region_ineligible() -> None:
    router = _three_region_router()
    # Saturate ap-south-1 capacity so it cannot take a session.
    region = router.region("ap-south-1")
    region.warm_pool.in_use = region.warm_pool.capacity
    assert not region.is_eligible()
    delhi = GeoPoint(28.6139, 77.2090)
    route = router.route(delhi, preferred_region="ap-south-1")
    # Preferred is full -> fall back.
    assert route.region != "ap-south-1"
    assert route.outcome is RouteOutcome.fallback


def test_warm_pool_bias_breaks_close_ties() -> None:
    # Two regions at the same location & edge floor; only one is warm.
    here = GeoPoint(0.0, 0.0)
    router = RegionRouter(
        [
            Region(name="cold", location=here, edge_latency_ms=5.0,
                    warm_pool=WarmPool(warm=0, in_use=0, capacity=4)),
            Region(name="warm", location=here, edge_latency_ms=5.0,
                    warm_pool=WarmPool(warm=2, in_use=0, capacity=4)),
        ],
        warm_bonus_ms=40.0,
    )
    route = router.route(here)
    assert route.region == "warm"
    assert route.warm is True


def test_no_healthy_region_returns_none() -> None:
    router = _three_region_router()
    for name in router.region_names:
        router.set_health(name, False)
    route = router.route(GeoPoint(0.0, 0.0))
    assert route.region is None
    assert route.outcome is RouteOutcome.none


def test_last_resort_when_chain_exhausted() -> None:
    # Preferred down with NO fallbacks configured -> global best (last_resort).
    router = RegionRouter(
        [
            Region(name="a", location=GeoPoint(0.0, 0.0), edge_latency_ms=5.0,
                   fallbacks=[], warm_pool=WarmPool(warm=1, in_use=0, capacity=2)),
            Region(name="b", location=GeoPoint(1.0, 1.0), edge_latency_ms=5.0,
                   warm_pool=WarmPool(warm=1, in_use=0, capacity=2)),
        ]
    )
    router.set_health("a", False)
    route = router.route(GeoPoint(0.0, 0.0), preferred_region="a")
    assert route.region == "b"
    assert route.outcome is RouteOutcome.last_resort


def test_distance_is_monotonic() -> None:
    mumbai = GeoPoint(19.076, 72.8777)
    delhi = GeoPoint(28.6139, 77.2090)
    london = GeoPoint(51.5074, -0.1278)
    assert mumbai.distance_km(delhi) < mumbai.distance_km(london)


def test_default_topology_routes_indian_user_home() -> None:
    router = default_india_first_topology()
    bengaluru = GeoPoint(12.9716, 77.5946)
    route = router.route(bengaluru)
    assert route.region == "ap-south-1"
    assert route.warm is True


def test_warm_pool_validation() -> None:
    try:
        WarmPool(warm=-1)
    except ValueError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError for negative warm count")
