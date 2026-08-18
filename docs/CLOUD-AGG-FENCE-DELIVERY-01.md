# CLOUD-AGG-FENCE-DELIVERY-01

## Delivery Transaction Boundary Conformance Evidence

- Status: `Done` / audit result `PASS`
- Date: `2026-08-04`
- Base: `zebra-cloud-trench@29d8fd1b`
- Branch: `codex/cloud-agg-fence-delivery-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-delivery-01/zebra-agent`
- Owner: `codex`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`

## Purpose

Delivery receipt/audit is an API command transaction boundary, not a Worker
Lease aggregate. This card verifies that distinction and makes the existing
PostgreSQL evidence runner reproducible in a clean workspace environment.

## Boundary

Writable paths are limited to:

- `tests/compose/delivery_transaction/`
- this audit and the registered governance records

Delivery Core contracts, PostgreSQL adapter/migration and focused tests are
read-only audit targets. No API/Worker wiring, external action execution,
SQLite behavior, Runtime/profile selection, application Compose, Redis, Mem0,
Provider HTTP, migration redesign or parent-gate change is included.

## Acceptance matrix

| ID | Boundary | Required evidence |
| --- | --- | --- |
| DL-01 | Command identity | `(deployment_namespace, action, idempotency_key)` is unique and request hash conflicts fail closed |
| DL-02 | Claim fence | one concurrent owner is selected; `claim_token` fences state transitions and commit |
| DL-03 | Atomicity | receipt, audit and committed transaction state commit or roll back together |
| DL-04 | Replay | committed requests replay the canonical receipt; UNKNOWN/FAILED do not auto-replay |
| DL-05 | Scope | foreign namespace is rejected before mutation |
| DL-06 | Boundary | no Worker LeaseFence is synthesized; external effects remain outside this storage transaction |
| DL-07 | Reproducibility | PostgreSQL `17.5-alpine3.21` runner emits PASS and removes container, volume and network |

## Current finding

`PostgresDeliveryTransactionStore` uses command claim identity and a durable
`claim_token`; `commit` locks the transaction row and writes the idempotency
receipt, delivery audit and terminal state in one connection transaction.
`UNKNOWN`/`FAILED` states remain terminal for replay purposes. This is distinct
from Worker-owned aggregate fencing and must not unlock `CLOUD-AGG-FENCE-01`.

## Evidence and closeout

- The audit confirms Delivery uses `(deployment_namespace, action,
  idempotency_key)` plus `claim_token` as command authority. Receipt, audit and
  terminal transaction state commit atomically; UNKNOWN/FAILED states do not
  auto-replay. No Worker LeaseFence is synthesized and external effects remain
  outside this storage transaction.
- The corrected runner installs the `agent-storage` package, uses PostgreSQL
  `17.5-alpine3.21`, passes `12/12` with
  `ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=PASS`, and removes its
  container, volume and network. Shell syntax, Compose config and
  `git diff --check` pass.
- No Delivery adapter, migration, API/Worker wiring or external action changed.
  This card is closed as `Done`; the parent `CLOUD-AGG-FENCE-01` remains
  `Locked`.

## Closeout rule

Move this card to `Done` only after the corrected runner passes from the merged
target branch, cleanup is observed, and the audit records exact counts and
static/script checks. The parent aggregate gate remains `Locked`.
