# Phase 25 Durable Workspace And Snapshot Foundations 验收记录

## Scope

Phase 25 established the first durable workspace and snapshot-oriented
foundations needed before real sandbox suspension and restoration can exist.

The phase did not introduce a working local snapshot backend yet. Instead, it
made workspace lifecycle state durable, extended runtime contracts so snapshot
operations are explicit, and wired worker recovery paths to durable workspace
state rather than raw bootstrap payloads.

## Completed Tasks

### P25-STO-01 - Durable Workspace Projection Store

Implemented behavior:

- Added durable `WorkspaceProjection` and `WorkspaceStatus` models.
- Added `rebuild_workspace(...)` so workspace lifecycle facts can be rebuilt from
  the existing event stream.
- Added `SQLiteWorkspaceProjectionStore` for:
  - `workspace_root`
  - `policy_profile`
  - lifecycle `status`
  - `current_sequence`
  - `prepared_at`
  - `updated_at`
  - `last_attempt_number`
- Preserved existing session projection behavior without introducing
  snapshot-specific runtime fields too early.

Validation:

- `poetry run pytest tests/agent_core/test_workspace_projection.py tests/agent_storage/test_sqlite_workspace_store.py tests/agent_storage/test_sqlite_projection_store.py tests/agent_core/test_session_projection.py`
- `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_core tests/agent_storage`
- `uv run mypy packages/agent-core/src/agent_core/domain/workspaces.py packages/agent-core/src/agent_core/application/workspace_projection.py packages/agent-core/src/agent_core/ports/workspace_projection_store.py packages/agent-storage/src/agent_storage/workspaces.py tests/agent_core/test_workspace_projection.py tests/agent_storage/test_sqlite_workspace_store.py`
- `make check`

### P25-RT-01 - Runtime Snapshot And Resume Contracts

Implemented behavior:

- Extended `RuntimePort` so lifecycle methods are explicit:
  - `provision`
  - `snapshot`
  - `restore`
  - `fork`
  - `suspend`
  - `resume`
- Added `RuntimeHandle`, `RuntimeSnapshot`, and `RuntimeCapabilityError`.
- Kept `execute(...)` compatible for all existing runtime and tool call sites.
- Extended `LocalRuntime` with deterministic local handle lifecycle for
  `provision`, `suspend`, and `resume`.
- Kept `snapshot`, `restore`, and `fork` fail-closed in the local adapter rather
  than pretending there is a working snapshot backend already.

Validation:

- `poetry run pytest tests/agent_runtime/test_local_runtime.py tests/agent_tools/test_command_run_tool.py tests/agent_tools/test_patch_apply_tool.py tests/agent_tools/test_tests_run_tool.py tests/agent_tools/test_git_status_tool.py`
- `uv run ruff check packages/agent-core/src/agent_core/ports/runtime.py packages/agent-runtime/src/agent_runtime tests/agent_runtime tests/agent_tools`
- `uv run mypy packages/agent-core/src/agent_core/ports/runtime.py packages/agent-runtime/src/agent_runtime/adapters/local.py packages/agent-runtime/src/agent_runtime/__init__.py tests/agent_runtime/test_local_runtime.py`
- `make check`

### P25-WKR-01 - Worker Snapshot Lifecycle Wiring

Implemented behavior:

- Extended `SessionRecoveryService` so worker recovery now carries both:
  - durable session state
  - durable workspace state
- Worker recovery now prefers durable workspace projection rows and replays
  delta events into workspace lifecycle state when needed.
- `SessionExecutionService` now restores `workspace_root` and `policy_profile`
  from recovered workspace projection state instead of trusting raw bootstrap
  payloads as the only source of truth.
- Worker event append paths now keep session projection and workspace projection
  rows aligned during:
  - attempt start
  - policy and tool events
  - terminal completion or failure
- Kept `SessionRecoveryService` backward compatible when no workspace store is
  injected so this slice did not have to widen into unrelated CLI or API paths.

Validation:

- `poetry run pytest tests/worker/test_claims.py tests/worker/test_resume.py tests/worker/test_recovery.py tests/worker/test_execution.py tests/worker/test_loop.py`
- `uv run ruff check apps/worker/src/zebra_agent_worker packages/agent-storage/src/agent_storage tests/worker`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Workspace lifecycle state is now durable and replayable rather than living
  only in bootstrap payloads and process-local recovery logic.
- Runtime contracts now describe snapshot and suspend lifecycle operations
  explicitly.
- Worker recovery and execution now reuse durable workspace projection state and
  keep workspace lifecycle rows aligned with emitted worker events.
- Existing local execution paths remain compatible while unsupported snapshot
  behavior stays fail-closed.

## Validation Notes

- Targeted Phase 25 regression suites passed for storage, runtime, and worker
  lifecycle paths.
- `make check` passed on the closeout line.
- Full `make test` was not rerun in the closeout slice because the touched
  areas were already covered by targeted regression suites plus the repository
  release gate.

## Known Deferrals

- `LocalRuntime` still does not implement real snapshot, restore, or fork
  behavior.
- Session suspend control paths are not yet wired to runtime lifecycle methods
  or durable workspace state transitions.
- CLI and API operator surfaces still expose resume-style execution without a
  snapshot-backed local suspend or restore workflow.

## Next Phase

Phase 26 should turn the new contracts into an actual local snapshot and
operator-control slice:

- implement a local snapshot backend and retention model for `LocalRuntime`
- wire session suspend and resume control paths to runtime lifecycle operations
  and workspace projection updates
- expose and document operator-facing local snapshot or suspend behavior through
  CLI and API surfaces

