# SoulYatri — Launch & Governance Index (Phase 18)

> Entry point for the launch-governance pack (`final_use.md` §Phase 18). These documents
> turn all prior phases into a coordinated execution machine: a daily operating loop, a
> release gate, a launch-readiness map, and a final handoff packet. Everything links to
> **real** subsystems and `runs/<phase>/acceptance.md` records.

SoulYatri is an open-source, **speech-native**, low-latency, full-duplex, emotional,
Hindi + English + Hinglish conversational voice AI. Canonical loop:
`Audio → Mimi → Moshi → Mimi → Audio` (`docs/DECISIONS.md` D-002).

---

## Launch pack

| Doc | Phase | Purpose |
|---|---|---|
| [OPERATING_MANUAL.md](OPERATING_MANUAL.md) | 18A | Daily operating loop — triage, task slicing (§9 ticket), benchmark cadence, long-job approval, release cadence, multi-agent worktree/branch coordination. |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | 18B | Preflight checks (latency, safety, watermark, memory, load, docs, rollback) + the `# Release Gate`. Each gate cites the real subsystem + acceptance record. |
| [LAUNCH_READINESS.md](LAUNCH_READINESS.md) | 14 | The §14 launch-readiness checklist reproduced and mapped item-by-item to subsystem + acceptance record (or PENDING-EXTERNAL with reason). |
| [HANDOFF_PACK.md](HANDOFF_PACK.md) | 18C | Final architecture summary, benchmark snapshot template, consolidated risk register, runbook index, docs indexes, next-cycle issue backlog. |

---

## How these fit together

```text
OPERATING_MANUAL  → how a day runs (one micro-phase per agent, isolated branches)
       │
RELEASE_CHECKLIST → the go/no-go gate before any release (# Release Gate)
       │
LAUNCH_READINESS  → honest §14 status: DONE vs PENDING-EXTERNAL vs TO-MEASURE
       │
HANDOFF_PACK      → everything a new team needs to continue from artifacts alone
```

---

## Companion governance docs (Phase 0)

| Doc | Purpose |
|---|---|
| [../AGENT_PROTOCOL.md](../AGENT_PROTOCOL.md) | Branch/worktree rules, PR checklist, Definition of Done. |
| [../DECISIONS.md](../DECISIONS.md) | Frozen architecture (D-001 … D-009). |
| [../MODEL_LOCKS.md](../MODEL_LOCKS.md) | V1 model/artifact manifest + `pending-human-pin` rows. |
| [../LATENCY_TARGETS.md](../LATENCY_TARGETS.md) | Staged latency gates. |
| [../RISKS.md](../RISKS.md) | Risk register (R-001 … R-014). |
| [../OPEN_QUESTIONS.md](../OPEN_QUESTIONS.md) | Unresolved items (Q-001 … Q-015). |
| [../index.md](../index.md) | Top-level documentation index. |

---

## Acceptance

Phase 18 acceptance and the project-wide build status are recorded in
[`runs/phase-18-launch/acceptance.md`](../../runs/phase-18-launch/acceptance.md).
