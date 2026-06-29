# Local Snapshot Runtime

## Scope

`LocalRuntime` now supports a narrow but real local snapshot backend for
workspace-backed handles.

This slice is intentionally limited to local filesystem copies. It does not yet
attempt to fake container or VM checkpoint semantics.

The current repository line now wires these runtime semantics into the local
session control plane:

- suspend creates a durable snapshot for the current workspace-backed session
- workspace projections persist `runtime_name`, `snapshot_id`, and
  `snapshot_path`
- worker resume restores onto a fresh runtime-managed working directory before
  harness execution continues

## Supported Subset

Supported operations:

- snapshot a local runtime handle that has a valid `workspace_root`
- restore a new local runtime handle from a saved snapshot
- fork additional local runtime handles from the same snapshot

Supported source workspace shape:

- existing directory on the local filesystem
- filesystem state that can be copied with standard recursive directory copy

Unsupported operations remain explicit:

- snapshot on a handle without `workspace_root`
- snapshot on a missing or non-directory workspace root
- restore or fork from a snapshot owned by a different runtime
- restore or fork from a pruned or missing snapshot payload

## Storage Layout

The local backend keeps runtime-managed state under a snapshot root:

- `snapshots/<snapshot_id>/workspace/`
- `snapshots/<snapshot_id>/manifest.json`
- `restores/<snapshot_id>-restore-XX/`
- `restores/<snapshot_id>-fork-XX/`

`manifest.json` records:

- `snapshot_id`
- `runtime_name`
- `source_handle_id`
- `created_at`
- source `workspace_root`

`RuntimeSnapshot` now also carries:

- `workspace_root`
- `snapshot_path`

This keeps restore and fork flows explicit without depending on hidden process
memory outside the runtime instance.

## Retention Model

Retention is deterministic per source handle:

- each `LocalRuntime` instance enforces a configurable snapshot retention limit
- when a new snapshot exceeds the limit, the oldest snapshot directories for
  that handle are pruned first
- restore or fork from a pruned snapshot fails with an explicit capability error

The default retention limit is `3`.

## Semantics

- snapshot copies the current workspace directory into runtime-managed snapshot
  storage
- restore creates a fresh runtime-managed working directory from the snapshot
  payload and returns a new handle
- fork behaves like restore but allocates a separate working directory so the
  restored copies do not alias each other
- restored and forked handles start in `suspended=False`

This is a filesystem snapshot, not a process checkpoint. Open subprocess state,
in-memory interpreter state, and live network connections are outside the
supported subset.

## Control-Plane Integration

The current local control plane uses these runtime semantics in three places:

- `uv run zebra-agent suspend <session_id>` creates a local snapshot and marks
  the durable session state as suspended
- `POST /sessions/{id}/suspend` exposes the same local snapshot-backed suspend
  path over the HTTP API
- worker-backed resume execution restores the suspended workspace onto a fresh
  working directory and updates the durable `workspace_root` before the harness
  runs

What still remains outside this document:

- operator guidance and rollback procedure live in `docs/operator_runbook.md`
- Phase 26 closeout evidence lives in the phase acceptance record once the
  documentation slice is closed
