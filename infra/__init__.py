"""
infra/ — Infrastructure & SRE subsystem.

Owner: infra/SRE agent (final_use.md §4, Phase 16).

Purpose: deployment topology, containerization, monitoring, and release hardening.
Houses LiveKit config, Docker/deploy assets, and observability wiring. Keeps production
boring: explicit resource budgets, queues, rollout, rollback, and regional routing.
The repo-root docker-compose.yml (LiveKit + Redis) is the current local entrypoint.
"""
