# CLOUD-REC-DRILL-01 — rollback, outbox reconciliation and worker race

Status: In Progress  
Owner: Codex  
Branch: `codex/cloud-rec-drill-01`  
Owned paths: `tests/compose/recovery_drill/`, `docs/CLOUD-REC-DRILL-01.md`

## Scope

This child is a local-only PostgreSQL 17.5 drill over the existing fenced Effect
outbox and Lease contracts. It proves that an invalid Event-version schedule
rolls back, two consumers cannot claim one pending dispatch twice, an epoch
replacement fences a crashed worker, and concurrent reconciliation has one
evidence-bearing winner. The uncertain dispatch is resolved explicitly as
`failed_no_effect`; it is never automatically replayed.

The report records observed claim-race/recovery milliseconds and durable Event
counts as a code-path measurement only. It is not a production RPO/RTO or DR
claim and does not call a provider or enable runtime Worker wiring.

## Validation

Run from the repository root:

```bash
tests/compose/recovery_drill/run-recovery-drill.sh
```

Acceptance evidence is the JSON report, `RECOVERY_DRILL_VERIFY=PASS`, and the
final sentinel `ZEBRA_PG_RECOVERY_DRILL_TEST_RESULT=PASS`. The runner removes
its PostgreSQL volume, network and temporary report on exit.
