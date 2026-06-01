"""Pytest + Hypothesis configuration for the roadmap test suite.

Registers a Hypothesis settings profile named ``roadmap`` that sets
``max_examples=100`` as the project default and loads it so every
property-based test in this package runs at least 100 examples unless a test
explicitly overrides it with its own ``@settings`` decorator.

The ``ROADMAP.md`` path is also exposed as a fixture so structural tests can
resolve the narrative artifact regardless of the pytest working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from roadmap.paths import ROADMAP_MD_PATH

#: Name of the project-default Hypothesis profile.
HYPOTHESIS_PROFILE = "roadmap"

# Register and load a project-default profile. ``max_examples=100`` is the
# minimum example count mandated by the design for every numbered property.
settings.register_profile(
    HYPOTHESIS_PROFILE,
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(HYPOTHESIS_PROFILE)


@pytest.fixture(scope="session")
def roadmap_md_path() -> Path:
    """Resolved path to the narrative ``ROADMAP.md`` planning artifact."""
    return ROADMAP_MD_PATH
