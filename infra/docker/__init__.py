"""
infra.docker — containerization assets (final_use.md §16C).

This package holds Docker/compose artifacts (no importable runtime code):

    * ``Dockerfile.server`` — builds the FastAPI voice-pipeline image (CPU-safe default,
      non-root, healthchecked on ``/metrics``).
    * ``docker-compose.full.yml`` — extends the root compose patterns (LiveKit + Redis)
      with Postgres + Qdrant + the server + Prometheus, per the §2.2 model stack. The
      repo-root ``docker-compose.yml`` is intentionally left untouched.
    * ``PINNED_VERSIONS.md`` — image/runtime pin policy.

Validated by ``infra/tests/test_config_files.py`` (compose is parsed with
``yaml.safe_load`` and required services/keys are asserted).
"""
