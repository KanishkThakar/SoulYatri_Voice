# runs/

Acceptance evidence and benchmark/latency reports, per the global Definition of Done
(final_use.md §3.3) and `docs/AGENT_PROTOCOL.md` §6.

## Convention
One folder per task slice:

```
runs/<phase>-<slug>/
  acceptance.md      # what was run, command, result, pass/fail
  metrics.json       # optional machine-readable latency/quality numbers
```

Example:

```
runs/0-1-foundation/acceptance.md
```

Reports here are referenced from PRs as acceptance evidence. Regression reports from
`evals/` (Phase 15) also land here.
