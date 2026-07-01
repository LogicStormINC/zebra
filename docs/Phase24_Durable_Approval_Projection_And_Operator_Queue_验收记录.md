# Phase 24 Durable Approval Projection And Operator Queue 验收记录

## Scope

Phase 24 moved proxy-aware approval operator reads off replay-only paths and
into durable projection-backed surfaces.

The phase did not broaden execution permissions. Instead, it made approval
queue and detail reads durable, projection-backed, and easier to audit while
preserving the existing fail-closed policy posture.

## Completed Tasks

### P24-STO-01 - Durable Approval Context Projection

Implemented behavior:

- Added durable `approval_context` state to session projections.
- Updated session projection rebuild so `approval_requested` persists:
  - `tool_name`
  - `reason`
  - `policy_profile`
  - `route`
  - `target`
  - `network_profile`
  - `scope`
- Preserved the same approval context after grant and reject events.
- Extended SQLite projection storage with durable approval-context persistence
  while remaining compatible with existing rows.

Validation:

- `poetry run pytest tests/agent_core/test_session_projection.py tests/agent_storage/test_sqlite_projection_store.py`
- `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_core tests/agent_storage`
- `uv run mypy packages/agent-core/src/agent_core/domain/sessions.py packages/agent-core/src/agent_core/application/session_projection.py packages/agent-storage/src/agent_storage/projections.py tests/agent_core/test_session_projection.py tests/agent_storage/test_sqlite_projection_store.py`

### P24-API-01 - Approval Queue And Detail Read API

Implemented behavior:

- Added projection-backed `GET /approvals`.
- Added projection-backed `GET /approvals/{id}`.
- Updated session and approval decision readback to reuse durable
  `approval_context`.
- Limited operator-facing approval reads to the existing safe field set without
  exposing secrets or raw credential material.

Validation:

- `poetry run pytest tests/api/test_api_app.py tests/api/test_routes.py tests/api/test_http_approvals.py tests/api/test_approval_api_app.py tests/api/test_http_app.py`
- `uv run ruff check apps/api/src/zebra_agent_api tests/api`
- `make check`

### P24-OBS-01 - Approval Projection Consistency Checks

Implemented behavior:

- Added a stable `ApprovalContext.to_mapping()` helper so replay, projection,
  and repeated-read checks compare the same safe vocabulary.
- Added regression coverage proving that:
  - event replay rebuilds the expected proxy-aware approval context
  - SQLite projection persistence preserves the same context
  - repeated reads do not drift across durable approval rows
- Added operator guidance for diagnosing projection drift before treating any
  discrepancy as a policy bypass.

Validation:

- `poetry run pytest tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py tests/agent_core/test_session_projection.py tests/agent_core/test_harness_trace_projection.py`
- `uv run ruff check packages/agent-core/src/agent_core packages/agent-storage/src/agent_storage tests/agent_core tests/agent_storage`
- `uv run mypy packages/agent-core/src/agent_core/domain/sessions.py packages/agent-core/src/agent_core/application/session_projection.py packages/agent-storage/src/agent_storage/projections.py tests/agent_storage/test_sqlite_event_store.py tests/agent_storage/test_sqlite_projection_store.py`
- `make check`

## Acceptance Summary

- Proxy-aware approval context is now durable in SQLite-backed projection state
  rather than only reconstructed from raw event replay.
- Operators can read waiting approvals and approval detail views from
  projection-backed APIs.
- Approval event payloads, durable projections, queue/detail reads, and trace
  metadata now share the same proxy-aware vocabulary for `route`, `target`,
  `network_profile`, and `scope`.
- Existing local-only approval paths remain backwards compatible.

## Validation Notes

- Targeted Phase 24 regression suites passed for storage, API, replay, and
  trace surfaces.
- `make check` passed on the closeout line.
- Full `make test` was not rerun in the closeout slice because the touched
  areas were already covered by targeted regression suites plus the repository
  release gate.

## Known Deferrals

- Runtime and workspace state are still process-local and path-based rather
  than tracked through a dedicated durable workspace projection.
- The runtime boundary still exposes only `execute(...)`; it does not yet model
  snapshot, restore, fork, suspend, or resume semantics from the architecture
  baseline.
- Session suspension exists at the control-plane level, but there is no durable
  sandbox or workspace resume path that can release and later restore runtime
  state.

## Next Phase

Phase 25 should establish durable workspace and snapshot foundations:

- introduce a durable workspace projection and SQLite workspace store
- extend runtime contracts with snapshot, restore, fork, suspend, and resume
  semantics
- add local runtime and worker-side lifecycle wiring for snapshot-backed resume

