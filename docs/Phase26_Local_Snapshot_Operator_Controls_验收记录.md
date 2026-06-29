# Phase 26 Local Snapshot Operator Controls 验收记录

## Scope

Phase 26 turned the durable workspace and runtime lifecycle contracts from
Phase 25 into a usable local operator slice.

The phase introduced a real local snapshot backend, wired suspend and resume
control paths across runtime, worker, CLI, and API surfaces, and documented the
supported operator model for the current local-first repository line.

The phase did not attempt to implement full process checkpointing, remote
sandbox orchestration, or archival snapshot governance. It stayed within the
local filesystem-backed subset described by the architecture's local runtime
baseline.

## Completed Tasks

### P26-RT-01 - Local Snapshot Backend

Implemented behavior:

- `LocalRuntime` now supports real local snapshot, restore, and fork behavior
  for workspace-backed handles.
- Added `LocalSnapshotBackend` with:
  - runtime-managed `snapshots/`
  - runtime-managed `restores/`
  - snapshot `manifest.json`
  - deterministic per-handle retention
- Extended `RuntimeSnapshot` with explicit `workspace_root` and `snapshot_path`
  metadata so restore and fork paths do not rely on hidden in-memory state.
- Kept unsupported paths explicit:
  - no snapshot without `workspace_root`
  - no restore or fork for foreign runtime snapshots
  - no restore from pruned or missing snapshot payloads

Validation:

- `poetry run pytest tests/agent_runtime/test_local_runtime.py tests/agent_tools/test_command_run_tool.py tests/agent_tools/test_patch_apply_tool.py tests/agent_tools/test_tests_run_tool.py tests/agent_tools/test_git_status_tool.py`
- `make check`

### P26-APP-01 - Suspend And Resume Control Wiring

Implemented behavior:

- Added durable `session_suspended` and `session_resumed` lifecycle events.
- Extended workspace projections with:
  - `runtime_name`
  - `snapshot_id`
  - `snapshot_path`
- Added `SessionControlService` for:
  - local snapshot-backed suspend
  - suspended workspace restore before execution
- Worker resume execution now restores suspended workspaces onto a fresh
  runtime-managed directory before the harness runs.
- CLI now exposes `suspend`.
- API now exposes `POST /sessions/{id}/suspend`.
- Existing worker-backed resume flows now support both ready and suspended
  sessions without widening into remote runtime assumptions.

Validation:

- `poetry run pytest tests/agent_core/test_session_projection.py tests/agent_core/test_workspace_projection.py tests/agent_storage/test_sqlite_workspace_store.py tests/worker/test_execution.py tests/api/test_routes.py tests/api/test_http_app.py tests/cli/test_cli_commands.py`
- `make check`

### P26-DOC-01 - Snapshot Operator Runbook

Implemented behavior:

- Updated `docs/operator_runbook.md` to Phase 26 semantics.
- Added explicit operator guidance for:
  - CLI and API suspend
  - ready and suspended resume execution
  - worker restore behavior
  - failure interpretation and rollback steps
  - local snapshot boundaries
- Updated `docs/local_snapshot_runtime.md` so it reflects the now-wired
  control-plane integration rather than the earlier pre-wiring state.
- Kept the runbook below repository markdown size limits.

Validation:

- `make check`

## Acceptance Summary

- Local snapshot behavior is now real rather than contract-only.
- Suspend and resume now have durable event, projection, and operator-surface
  semantics across CLI, API, and worker execution.
- Runtime, workspace projection, and operator documentation now describe the
  same local snapshot-backed control model.
- The repository remains local-first and fail-closed for unsupported snapshot
  paths.

## Validation Notes

- Targeted Phase 26 regression suites passed for runtime, projection, worker,
  API, and CLI surfaces.
- `make check` passed on the closeout line.
- The closeout slice itself was doc-only, so it re-used the already-green
  repository validation path instead of rerunning every targeted suite again.

## Known Deferrals

- Session readback surfaces still do not expose projection-backed workspace
  lifecycle or snapshot metadata directly to operators.
- Snapshot retention is deterministic for the local runtime path, but there is
  not yet a dedicated housekeeping or compatibility-check surface that audits
  retained snapshot payloads independently of a single runtime call path.
- The current local snapshot model is a filesystem copy, not full sandbox or
  process checkpointing.
- Remote sandbox managers, team control-plane APIs, and stronger runtime
  isolation remain later-phase work.

## Next Phase

Phase 27 should focus on making local snapshot lifecycle state easier to inspect
and safer to operate:

- expose workspace lifecycle and snapshot metadata through projection-backed
  operator read surfaces
- extend CLI inspect-style surfaces so operators can read workspace and snapshot
  state without replaying raw events
- add snapshot housekeeping and compatibility checks so retained local snapshot
  payloads are easier to verify and clean deterministically
