# CLOUD-AGG-FENCE-MODEL-TOOL-01

## Model/Tool Projection Revision Fencing

- Status: `In Progress`
- Date: `2026-08-04`
- Base: `zebra-cloud-trench@d622c720`
- Branch: `codex/cloud-agg-fence-model-tool-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-model-tool-01/zebra-agent`
- Owner: `codex`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`

## Purpose

`model_call_projections` and `tool_run_projections` are Event-derived indexes,
not a second execution authority. The existing PostgreSQL adapter already
checks the canonical Event, namespace/session identity and current LeaseFence.
This card closes the remaining Worker authority gap: the write transaction must
also bind the Event sequence to `WorkerMutationAuthority.expected_stream_revision`
and the current committed stream before it updates either projection.

## Boundary

Writable paths are limited to:

- `packages/agent-storage/src/agent_storage/postgres/model_tool_projections.py`
- `tests/agent_storage/test_postgres_model_tool_projections.py`
- `tests/compose/model_tool/`
- this document and the registered governance records

`replay_session()` remains a management-only Event replay path and does not
consume Worker authority. No migration, SQLite behavior, API/Worker profile
selection, Runtime, application Compose, Redis, Mem0, Provider HTTP, Artifact,
CopilotKit/Trench or parent-gate change is included.

## Acceptance matrix

| ID | Boundary | Required evidence |
| --- | --- | --- |
| MT-01 | Authority identity | namespace and Session match the adapter and canonical Event |
| MT-02 | Lease fence | current epoch, token, owner and expiry are checked before writes |
| MT-03 | Stream revision | Event sequence equals `expected_stream_revision + 1`; the committed stream is locked and equals the Event sequence |
| MT-04 | Replay | same canonical Event is idempotent; management replay can repair projections without Worker authority |
| MT-05 | Conflict | forged Event identity or same key/different content fails closed |
| MT-06 | Zero-write | wrong revision, namespace/session, stale fence, stream drift and injected rollback leave projection rows unchanged |
| MT-07 | Scope | PostgreSQL `17.5-alpine3.21` runner records counts, PASS sentinel and removes all resources |

## Current finding

Before this card, `index_worker_event()` validated namespace/session and the
current LeaseFence but did not use `expected_stream_revision`. A caller with a
valid current Lease could therefore submit an Event-derived projection request
with an unrelated stream revision. The existing Event identity checks limited
the damage, but the Worker authority contract was not complete at this
persistence boundary.

## Closeout rule

The card may move to `Done` only after the focused tests and repository-owned
PostgreSQL runner pass from the merged cloud mainline, with deterministic
cleanup and no change to `CLOUD-AGG-FENCE-01`, Runtime selection or application
Compose.
