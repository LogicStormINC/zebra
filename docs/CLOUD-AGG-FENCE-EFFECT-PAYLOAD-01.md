# CLOUD-AGG-FENCE-EFFECT-PAYLOAD-01

## Effect-to-Artifact Transaction Conformance Evidence

- Status: `Done` / audit result `PASS`
- Date: `2026-08-04`
- Base: `zebra-cloud-trench@d44965c9`
- Branch: `codex/cloud-agg-fence-effect-payload-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-effect-payload-01/zebra-agent`
- Owner: `codex`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`

## Purpose

Effect payload linkage is the boundary where a durable external-effect intent
references an Artifact payload. The existing implementation reserves and
verifies payload evidence outside provider transactions, then commits the
intent Event, Artifact finalization and Effect outbox mutation atomically in
PostgreSQL. This card audits that boundary and adds a reproducible runner.

## Boundary

Writable paths are limited to:

- `tests/compose/effect_payload/`
- this audit and the registered governance records

Effect/Artifact Core contracts, adapters and focused tests are read-only audit
targets. No adapter redesign, migration, object provider, SQLite behavior,
Runtime/API/Worker profile selection, application Compose, Redis, Mem0,
Provider HTTP, Delivery or parent-gate change is included.

## Acceptance matrix

| ID | Boundary | Required evidence |
| --- | --- | --- |
| EF-01 | Authority | schedule and terminal transitions validate namespace, Session and current LeaseFence/stream CAS |
| EF-02 | Atomicity | intent Event, Artifact finalization and outbox mutation commit or roll back together |
| EF-03 | Identity | same request replays canonically; different identity or payload reference fails closed |
| EF-04 | Recovery | lost response and mid-flight takeover preserve staged/reconcilable evidence without Effect replay |
| EF-05 | Terminal state | success and uncertain terminal transitions bind the canonical terminal Event and claim |
| EF-06 | Zero-write | stale fence, invalid binding and injected failure leave no partial Effect/Artifact state |
| EF-07 | Reproducibility | PostgreSQL `17.5-alpine3.21` runner emits PASS and removes container, volume and network |

## Current finding

`EffectPayloadDispatchMixin` delegates to transaction helpers that call the
shared Artifact Worker boundary before any payload-aware mutation. Schedule
uses one transaction for the intent Event, finalized Artifact and outbox row;
terminal success/uncertain paths use one transaction for the terminal Event,
Artifact mutation and outbox state. Unknown provider/database outcomes leave
staged evidence for management reconciliation and do not auto-replay external
effects.

## Evidence and closeout

- The audit confirms payload-aware schedule validates Worker namespace, Session,
  LeaseFence and stream CAS before mutation, then atomically commits intent
  Event, Artifact finalization and Effect outbox state. Terminal success and
  uncertain transitions use the same transaction boundary; staged evidence is
  retained for management recovery after takeover or unknown outcomes.
- The repository-owned runner uses PostgreSQL `17.5-alpine3.21`, installs the
  `agent-storage` package for reproducible psycopg collection, passes `7/7`
  with `ZEBRA_EFFECT_PAYLOAD_POSTGRES_TEST_RESULT=PASS`, and removes its
  container, volume and network. The matrix covers stale fence, atomic commit,
  lost-response replay, conflicting identity, terminal paths and takeover.
- Shell syntax, Compose config and `git diff --check` pass. No adapter,
  migration, object provider or local behavior changed. This card is closed as
  `Done`; the parent `CLOUD-AGG-FENCE-01` remains `Locked`.

## Closeout rule

Move this card to `Done` only after the focused matrix passes from the merged
target branch, cleanup is observed, and the audit records exact counts and
static/script checks. The parent aggregate gate remains `Locked`.
