"""
infra.deploy — regional runtime layout + release hardening (final_use.md §16B/§16C).

Pure-Python, deterministic, CPU-only. No cloud SDKs, network calls, or live services.

Public API:
    * §16B: :class:`RegionRouter`, :class:`Region`, :class:`WarmPool`, :class:`GeoPoint`,
      :class:`RegionRoute`, :class:`RouteOutcome`, :func:`default_india_first_topology`.
    * §16C: :class:`RollbackEvaluator`, :class:`ReleasePolicy`, :class:`RollbackDecision`,
      :class:`RollbackAction`, :class:`RollbackThreshold`, :func:`load_release_policy`.

Config + docs that live in this package (validated by infra/tests):
    * ``release_policy.yaml`` — canary + rollback thresholds.
    * ``deployment_topology.md`` — regional layout design doc.
    * ``RUNBOOKS.md`` — staging / canary / rollback runbooks.
    * ``INCIDENT_RESPONSE.md`` — incident-response doc.
"""

from infra.deploy.regions import (
    GeoPoint,
    Region,
    RegionRoute,
    RegionRouter,
    RouteOutcome,
    WarmPool,
    default_india_first_topology,
)
from infra.deploy.rollback import (
    Comparison,
    ReleasePolicy,
    RollbackAction,
    RollbackDecision,
    RollbackEvaluator,
    RollbackThreshold,
    load_release_policy,
)

__all__ = [
    # 16B
    "RegionRouter",
    "Region",
    "WarmPool",
    "GeoPoint",
    "RegionRoute",
    "RouteOutcome",
    "default_india_first_topology",
    # 16C
    "RollbackEvaluator",
    "ReleasePolicy",
    "RollbackDecision",
    "RollbackAction",
    "RollbackThreshold",
    "Comparison",
    "load_release_policy",
]
