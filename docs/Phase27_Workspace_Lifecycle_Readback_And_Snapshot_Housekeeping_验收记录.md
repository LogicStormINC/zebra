# Phase 27 Workspace Lifecycle Readback And Snapshot Housekeeping 验收记录

## Scope

Phase 27 turned the local snapshot-backed control plane from an operator-capable
write surface into an operator-readable and safer-to-maintain lifecycle slice.

The phase exposed durable workspace lifecycle and snapshot metadata through API
and CLI readback paths, then hardened retained snapshot handling with explicit
compatibility inspection and cleanup semantics.

The phase did not expand into remote sandbox orchestration, archival snapshot
stores, or browser-facing product surfaces. It stayed within the repository's
local-first runtime and control-plane boundary.

## Completed Tasks

### P27-API-01 - Workspace Lifecycle Readback Surface

Implemented behavior:

- `GET /sessions/{id}` now returns projection-backed `workspace` state when a
  durable workspace projection exists.
- Workspace readback now includes:
  - `workspace_root`
  - lifecycle `status`
  - `current_sequence`
  - `prepared_at`
  - `updated_at`
  - optional `policy_profile`
  - optional `last_attempt_number`
- Suspended workspace readback now also includes snapshot-safe metadata:
  - `runtime_name`
  - `snapshot_id`
  - `snapshot_path`
- Existing session readback remained backward compatible for callers that only
  consume the older top-level session fields.

Validation:

- `poetry run pytest tests/api/test_api_app.py tests/api/test_http_app.py tests/api/test_routes.py`
- `make check`

### P27-CLI-01 - Workspace Lifecycle Inspect Output

Implemented behavior:

- `zebra-agent inspect <session_id>` now returns the same durable `workspace`
  projection state used by the API read surface.
- `zebra-agent resume <session_id>` in read-only mode now includes the same
  workspace lifecycle readback.
- Suspended session CLI output now exposes snapshot-safe metadata without
  replaying raw event streams.
- Existing machine-readable CLI fields remained stable for prior consumers.

Validation:

- `poetry run pytest tests/cli/test_cli_commands.py`
- `make check`

### P27-RT-01 - Snapshot Housekeeping And Compatibility Checks

Implemented behavior:

- Added explicit retained snapshot inspection states:
  - `valid`
  - `missing`
  - `incompatible`
- Local runtime restore and fork paths now validate retained snapshot
  `manifest.json` and payload shape before proceeding.
- Restore paths fail closed when retained snapshot metadata or manifest contents
  no longer match the requested local snapshot.
- Successful restore now explicitly cleans the consumed retained snapshot
  payload instead of relying only on future retention pruning.
- Worker resume execution now uses the same compatibility checks before
  restoring suspended workspaces.

Validation:

- `poetry run pytest tests/agent_runtime/test_local_runtime.py`
- `poetry run pytest tests/worker/test_execution.py`
- `make check`

## Acceptance Summary

- Operators can now read durable workspace lifecycle state and suspended
  snapshot metadata through both API and CLI surfaces without replay-only
  fallback.
- Retained local snapshots now have explicit compatibility and cleanup
  semantics, so missing and incompatible payloads are distinguishable.
- Worker restore behavior remains fail-closed and local-first.
- The repository keeps snapshot lifecycle semantics aligned across runtime,
  worker, API, CLI, and operator documentation.

## Validation Notes

- Targeted Phase 27 regression suites passed for API, CLI, runtime, and worker
  surfaces.
- `make check` passed on the implementation branch after the housekeeping and
  readback updates landed.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Retained snapshot handling is still local filesystem housekeeping, not a
  versioned archival or multi-node snapshot service.
- Session artifacts are still indexed primarily from model-call and tool-run
  records; there is not yet a durable artifact payload store with operator
  download semantics.
- Remote sandbox managers, team control-plane APIs, and stronger execution
  isolation remain later-phase work.

## Next Phase

Phase 28 should focus on durable artifact payload storage and operator-safe
artifact readback:

- persist artifact payloads separately from model-call and tool-run indexes
- let worker and tool execution paths write durable artifact metadata and
  retained local payload references consistently
- expose operator readback surfaces for artifact detail and retrieval without
  widening into remote object storage yet
