# CLOUD-AGG-FENCE-ARTIFACT-01

## Artifact Lifecycle Fencing Conformance Evidence

- Status: `Done` / audit result `PASS`
- Date: `2026-08-04`
- Base: `zebra-cloud-trench@da21d324`
- Branch: `codex/cloud-agg-fence-artifact-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-artifact-01/zebra-agent`
- Owner: `codex`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`

## Purpose

The v9 Artifact payload metadata is a Worker-owned lifecycle authority around
staged object evidence, canonical Event binding and retention pruning. This
card audits the already implemented adapter and adds a repository-owned runner
so its PostgreSQL fencing evidence is reproducible from the cloud mainline.

## Boundary

Writable paths are limited to:

- `tests/compose/artifact_payload/`
- this audit and the registered governance records

The Artifact Core contract, v9 migration, PostgreSQL adapter and focused test
matrix are read-only audit targets. No adapter redesign, object-provider change,
SQLite behavior, Runtime/API/Worker profile selection, application Compose,
Redis, Mem0, Delivery or parent-gate change is included.

## Acceptance matrix

| ID | Boundary | Required evidence |
| --- | --- | --- |
| AR-01 | Authority identity | every Worker transition matches deployment namespace and Session |
| AR-02 | Lease fence | current epoch, token, owner and expiry are checked in the same transaction |
| AR-03 | Stream CAS | reserve and every subsequent Worker transition lock/check the Session stream revision |
| AR-04 | Lifecycle CAS | payload row revision is checked under `FOR UPDATE` before each state transition |
| AR-05 | Integrity | object receipt, canonical `artifact://` Event binding and exact version evidence are validated |
| AR-06 | Replay/rollback | idempotent replay and injected failure leave no half-state or duplicate mutation |
| AR-07 | Management | reconciliation uses separate administrative CAS and audit rows; it never synthesizes Worker authority |
| AR-08 | Reproducibility | PostgreSQL `17.5-alpine3.21` runner emits PASS and removes container, volume and network |

## Current finding

`PostgresCloudArtifactPayloadStore` routes `reserve_for_worker`,
`record_object_for_worker`, `finalize_for_worker`, `compensate_for_worker`,
`begin_prune_for_worker` and `complete_prune_for_worker` through
`assert_worker_boundary`. That helper validates namespace, Session, current
LeaseFence and the locked Session stream revision. Each transition then locks
the metadata row, checks lifecycle revision and records an idempotency mutation.
Management recovery uses `AdministrativeMutationCAS` and a separate audit ledger.

## Evidence and closeout

- The audit confirms every Worker transition routes through
  `assert_worker_boundary` for namespace, Session, current LeaseFence and the
  locked stream revision, then locks metadata and applies lifecycle revision
  CAS plus idempotency mutation. Management recovery remains an explicit
  administrative CAS/audit path.
- The repository-owned runner uses PostgreSQL `17.5-alpine3.21`, installs the
  `agent-storage` package for reproducible psycopg collection, passes `13/13`
  with `ZEBRA_ARTIFACT_PAYLOAD_POSTGRES_TEST_RESULT=PASS`, and removes its
  container, volume and network. The matrix covers stale authority,
  namespace/session isolation, concurrent reserve, canonical Event binding,
  compensation, exact-version prune, replay, rollback and management audit.
- Shell syntax, Compose config and `git diff --check` pass. No adapter,
  migration, object provider or local behavior changed. This card is closed as
  `Done`; the parent `CLOUD-AGG-FENCE-01` remains `Locked`.

## Closeout rule

Move this card to `Done` only after the focused matrix passes from the merged
target branch, the runner cleanup is observed, and the audit records the exact
counts and static/script checks. The parent aggregate gate remains `Locked`.
