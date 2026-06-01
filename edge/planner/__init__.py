"""edge/planner/ — Response planning, speculation, perceived-latency control (final_use.md §4 / Phase 8).

Owner: edge/runtime agent. Reduces time-to-first-audio without corrupting correctness:

* ``short_turn.py``  — classify trivial/short/emotional/uncertain turns → ``RouteDecision``.
* ``speculation.py`` — start safe acknowledgements/short drafts early; cancel on conflict.
* ``handoff.py``     — when filler ends, when real output takes over; suppress duplicates.

Speculation must be safe to cancel, recoverable, and subordinate to the final response
(final_use.md Phase-8 agent prompt: "make the system feel fast without lying").
"""
