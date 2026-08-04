# CLOUD-AGG-FENCE-PROVIDER-01

## Provider Continuation Lifecycle Fencing Conformance

- Status: `In Progress`
- Date: `2026-08-04`
- Base: `zebra-cloud-trench@5694032c`
- Branch: `codex/cloud-agg-fence-provider-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-provider-01/zebra-agent`
- Owner: `codex`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`

## Purpose

The v13 PostgreSQL Provider Continuation aggregate stores opaque provider
payloads and the canonical selection Event. Its selection commit already
validates the current LeaseFence and binds the Event sequence to
`WorkerMutationAuthority.expected_stream_revision`. This conformance card
closes the remaining Worker lifecycle gap: soft deletion must use the same
stream CAS before changing the payload row.

## Boundary

Writable paths are limited to:

- `packages/agent-storage/src/agent_storage/postgres/provider_continuations.py`
- `tests/agent_storage/test_postgres_provider_continuations.py`
- `tests/compose/provider_continuation/`
- this audit and the registered governance records

No migration, Provider HTTP, SQLite behavior, Runtime/API/Worker profile
selection, application Compose, Redis, Mem0, Artifact, Delivery or parent-gate
change is included.

## Acceptance matrix

| ID | Boundary | Required evidence |
| --- | --- | --- |
| PC-01 | Authority identity | namespace and Session in `WorkerMutationAuthority` match the store and continuation row |
| PC-02 | Lease fence | current epoch, token, owner and expiry are checked before every Worker mutation |
| PC-03 | Stream CAS | commit and delete lock `session_streams` and require `expected_stream_revision` |
| PC-04 | Lifecycle | soft delete clears payload, advances lifecycle revision and is idempotent |
| PC-05 | Zero-write | stale revision, namespace/session, stale fence and injected rollback leave the row unchanged |
| PC-06 | Scope | PostgreSQL `17.5-alpine3.21` runner emits a PASS sentinel and removes container, volume and network |

## Current finding

`commit_worker_selection` calls `lock_expected_stream` in its transaction, but
`delete_for_worker` only checked the LeaseFence. A still-valid Lease with an
older stream revision could therefore delete a continuation after newer Session
facts were committed. The fix must reuse the existing helper and leave v13
schema and local SQLite compatibility untouched.

## Closeout rule

Move this card to `Done` only after the focused PostgreSQL runner passes on the
merged target branch, the stale-revision and rollback cases prove zero writes,
and changed-path static checks pass. The parent aggregate gate remains
`Locked`.
