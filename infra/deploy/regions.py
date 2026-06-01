"""
infra.deploy.regions — regional runtime layout (Phase 16B)
==========================================================
Region routing, edge placement, fallback-region behaviour, and warm model pools —
implemented as a pure-Python, deterministic model that unit-tests without any cloud.

final_use.md §16B goal: "implement region routing, edge placement near target users,
fallback region behaviour, warm model pools" so that "p95 latency stays controlled
across target geography."

Design
------
* :class:`Region` — a deployment region with its geographic ``location`` (used for a
  cheap great-circle latency estimate), an explicit ``edge_latency_ms`` floor, a
  health flag, and an ordered ``fallbacks`` list.
* :class:`WarmPool` — the count of pre-warmed model replicas in a region plus the
  in-use count, so the router can avoid cold-start regions when a warm one is viable.
* :class:`RegionRouter` — chooses the best region for a user by an effective-cost score
  that blends estimated network latency, the region's edge floor, an affinity bonus
  (sticky "home" region), and a warm-pool readiness bonus. Unhealthy or
  capacity-exhausted regions are skipped; if the preferred region is down it
  deterministically falls back along the configured chain, then to the global best.

No cloud SDKs, no network calls — latency is *estimated* from coordinates so the policy
is testable and reproducible.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field

from infra.obs import get_logger, telemetry

__all__ = [
    "GeoPoint",
    "Region",
    "WarmPool",
    "RouteOutcome",
    "RegionRoute",
    "RegionRouter",
]

logger = get_logger("infra.deploy.regions")

# Speed-of-signal-in-fibre round-trip approximation: ~0.0125 ms per km one way,
# doubled for round trip and padded for routing overhead. Coarse but monotonic in
# distance, which is all the router needs for *relative* decisions.
_MS_PER_KM_RTT = 0.025
_EARTH_RADIUS_KM = 6371.0


class RouteOutcome(str, enum.Enum):
    """Why a region was chosen."""

    affinity = "affinity"            # user's preferred/home region, healthy + warm
    nearest = "nearest"              # lowest effective cost among healthy regions
    fallback = "fallback"            # preferred region unhealthy -> configured fallback
    last_resort = "last_resort"      # all preferred chains exhausted -> global best
    none = "none"                    # no healthy region with capacity


@dataclass(frozen=True)
class GeoPoint:
    """A latitude/longitude in degrees."""

    lat: float
    lon: float

    def distance_km(self, other: GeoPoint) -> float:
        """Great-circle (haversine) distance in km — deterministic, no I/O."""
        lat1, lon1, lat2, lon2 = map(
            math.radians, (self.lat, self.lon, other.lat, other.lon)
        )
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class WarmPool:
    """Pre-warmed model replicas in a region (avoids cold-start latency).

    Attributes:
        warm: Number of replicas already loaded and ready.
        in_use: Replicas currently serving a session.
        capacity: Hard cap on concurrent replicas in the region (warm + cold-startable).
    """

    warm: int = 0
    in_use: int = 0
    capacity: int = 0

    def __post_init__(self) -> None:
        for name in ("warm", "in_use", "capacity"):
            if getattr(self, name) < 0:
                raise ValueError(f"WarmPool.{name} must be >= 0")

    @property
    def available_warm(self) -> int:
        """Warm replicas not yet in use (serve with no cold start)."""
        return max(self.warm - self.in_use, 0)

    @property
    def has_capacity(self) -> bool:
        """Whether the region can take one more session at all."""
        return self.in_use < self.capacity

    @property
    def is_warm_ready(self) -> bool:
        """Whether a warm replica can serve immediately."""
        return self.available_warm > 0 and self.has_capacity


@dataclass
class Region:
    """A deployment region and its routing-relevant attributes."""

    name: str
    location: GeoPoint
    edge_latency_ms: float = 5.0
    healthy: bool = True
    fallbacks: list[str] = field(default_factory=list)
    warm_pool: WarmPool = field(default_factory=WarmPool)

    def __post_init__(self) -> None:
        if self.edge_latency_ms < 0:
            raise ValueError("edge_latency_ms must be >= 0")

    def estimated_latency_ms(self, user: GeoPoint) -> float:
        """Edge floor + distance-derived network RTT estimate."""
        return self.edge_latency_ms + self.location.distance_km(user) * _MS_PER_KM_RTT

    def is_eligible(self) -> bool:
        """Healthy *and* has capacity to take a session."""
        return self.healthy and self.warm_pool.has_capacity


@dataclass
class RegionRoute:
    """Auditable result of a routing decision."""

    region: str | None
    outcome: RouteOutcome
    estimated_latency_ms: float | None
    warm: bool
    reason: str
    considered: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "region": self.region,
            "outcome": self.outcome.value,
            "estimated_latency_ms": self.estimated_latency_ms,
            "warm": self.warm,
            "reason": self.reason,
            "considered": list(self.considered),
        }


class RegionRouter:
    """Chooses the nearest healthy region for a user, with fallback + warm pools.

    Scoring (lower is better) for an eligible region ``r`` and user ``u``:

        cost(r) = estimated_latency_ms(r, u)
                  - affinity_bonus_ms   if r == preferred_region
                  - warm_bonus_ms       if r has a warm replica ready

    The bonuses are *latency credits*: a warm region or the user's home region wins ties
    and small gaps, which keeps p95 down by avoiding cold starts and cross-region churn.
    """

    def __init__(
        self,
        regions: list[Region] | dict[str, Region],
        *,
        affinity_bonus_ms: float = 20.0,
        warm_bonus_ms: float = 40.0,
    ) -> None:
        if not regions:
            raise ValueError("RegionRouter requires at least one region")
        if isinstance(regions, dict):
            self._regions = dict(regions)
        else:
            self._regions = {r.name: r for r in regions}
        self._affinity_bonus_ms = affinity_bonus_ms
        self._warm_bonus_ms = warm_bonus_ms

    # ------------------------------------------------------------------
    # Mutators (health + warm-pool bookkeeping) — useful in ops + tests
    # ------------------------------------------------------------------
    def set_health(self, region_name: str, healthy: bool) -> None:
        self._regions[region_name].healthy = healthy
        telemetry.record("infra_region_health", region=region_name, healthy=healthy)
        logger.info("region_health_change", region=region_name, healthy=healthy)

    def region(self, name: str) -> Region:
        return self._regions[name]

    @property
    def region_names(self) -> list[str]:
        return list(self._regions.keys())

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def route(self, user: GeoPoint, preferred_region: str | None = None) -> RegionRoute:
        """Pick the best region for ``user``.

        Order of resolution:
          1. If ``preferred_region`` is eligible -> use it (affinity).
          2. Else if it is set but ineligible -> walk its ``fallbacks`` chain.
          3. Else / chain exhausted -> global lowest-effective-cost healthy region.
          4. Nothing eligible -> ``RouteOutcome.none``.
        """
        considered: list[str] = []

        # 1. Affinity: preferred region is healthy + has capacity.
        if preferred_region is not None and preferred_region in self._regions:
            considered.append(preferred_region)
            pref = self._regions[preferred_region]
            if pref.is_eligible():
                return self._make_route(
                    pref, user, RouteOutcome.affinity, "preferred region eligible",
                    considered,
                )

            # 2. Walk the configured fallback chain in order.
            for fb_name in pref.fallbacks:
                considered.append(fb_name)
                fb = self._regions.get(fb_name)
                if fb is not None and fb.is_eligible():
                    return self._make_route(
                        fb, user, RouteOutcome.fallback,
                        f"preferred '{preferred_region}' ineligible; fell back to '{fb_name}'",
                        considered,
                    )

        # 3. Global best by effective cost among all eligible regions.
        best = self._best_eligible(user, preferred_region)
        if best is not None:
            region, _cost = best
            if region.name not in considered:
                considered.append(region.name)
            outcome = (
                RouteOutcome.last_resort
                if preferred_region is not None
                else RouteOutcome.nearest
            )
            reason = (
                "preferred chain exhausted; chose global best"
                if preferred_region is not None
                else "chose nearest healthy region by effective cost"
            )
            return self._make_route(region, user, outcome, reason, considered)

        # 4. Nothing healthy with capacity.
        telemetry.record("infra_region_route", region=None, outcome=RouteOutcome.none.value)
        logger.warning("region_route_none", preferred=preferred_region)
        return RegionRoute(
            region=None,
            outcome=RouteOutcome.none,
            estimated_latency_ms=None,
            warm=False,
            reason="no healthy region with capacity",
            considered=considered,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _effective_cost(
        self, region: Region, user: GeoPoint, preferred_region: str | None
    ) -> float:
        cost = region.estimated_latency_ms(user)
        if preferred_region is not None and region.name == preferred_region:
            cost -= self._affinity_bonus_ms
        if region.warm_pool.is_warm_ready:
            cost -= self._warm_bonus_ms
        return cost

    def _best_eligible(
        self, user: GeoPoint, preferred_region: str | None
    ) -> tuple[Region, float] | None:
        scored = [
            (r, self._effective_cost(r, user, preferred_region))
            for r in self._regions.values()
            if r.is_eligible()
        ]
        if not scored:
            return None
        # Deterministic: lowest cost, tie-break by region name.
        return min(scored, key=lambda rc: (rc[1], rc[0].name))

    def _make_route(
        self,
        region: Region,
        user: GeoPoint,
        outcome: RouteOutcome,
        reason: str,
        considered: list[str],
    ) -> RegionRoute:
        route = RegionRoute(
            region=region.name,
            outcome=outcome,
            estimated_latency_ms=round(region.estimated_latency_ms(user), 3),
            warm=region.warm_pool.is_warm_ready,
            reason=reason,
            considered=considered,
        )
        telemetry.record(
            "infra_region_route",
            region=region.name,
            outcome=outcome.value,
            est_latency_ms=route.estimated_latency_ms,
            warm=route.warm,
        )
        logger.info(
            "region_route",
            region=region.name,
            outcome=outcome.value,
            est_latency_ms=route.estimated_latency_ms,
            warm=route.warm,
        )
        return route


# ---------------------------------------------------------------------------
# Reference topology (documentation defaults — operators override for their fleet)
# ---------------------------------------------------------------------------
def default_india_first_topology() -> RegionRouter:
    """An India-first reference layout (SoulYatri targets Hindi/English/Hinglish users).

    Primary in ap-south (Mumbai), warm secondaries in Singapore and Frankfurt. Each
    region falls back along a sensible chain. Warm pools are seeded so the router
    prefers warm regions. This is a *documentation default*, not a pinned deployment.
    """
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
                fallbacks=["ap-south-1", "eu-central-1"],
                warm_pool=WarmPool(warm=1, in_use=0, capacity=6),
            ),
            Region(
                name="eu-central-1",
                location=GeoPoint(50.1109, 8.6821),  # Frankfurt
                edge_latency_ms=5.0,
                fallbacks=["ap-south-1", "ap-southeast-1"],
                warm_pool=WarmPool(warm=1, in_use=0, capacity=6),
            ),
        ]
    )
