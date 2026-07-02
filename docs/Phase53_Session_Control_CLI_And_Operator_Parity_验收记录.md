# Phase 53 Session Control CLI And Operator Parity 验收记录

## Scope

Phase 53 completed the operator parity loop for session control.

The phase first restored the missing cancel control entry and added a local
CLI cancel surface, then locked the shared API and CLI control boundary with a
dedicated cross-surface regression matrix for cancel and suspend.

## Completed Tasks

### P53-CLI-01 - Session Cancel Control Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/session_cancel_write.py`.
- Added `zebra-agent cancel <session_id>`.
- Restored the missing cancel control entry in worker and API control paths
  instead of adding a CLI-only side path.
- Added regression coverage for cancelled, invalid-state, and missing-session
  cancel behavior across worker, route, HTTP, and CLI paths.

Validation:

- `make sync`
- `uv run pytest tests/cli/test_cli_session_cancel.py tests/cli/test_cli_commands.py tests/api/test_http_session_cancel.py tests/api/test_http_app.py tests/api/test_route_session_cancel.py tests/api/test_routes.py tests/worker/test_control.py tests/worker/test_execution.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/session_cancel_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/api/src/zebra_agent_api/session_control.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/api/src/zebra_agent_api/session_payloads.py apps/worker/src/zebra_agent_worker/control.py apps/worker/src/zebra_agent_worker/__init__.py tests/cli/test_cli_session_cancel.py tests/api/test_http_session_cancel.py tests/api/test_route_session_cancel.py tests/worker/test_control.py`
- `uv run mypy packages apps`
- `make check`

### P53-TEST-01 - Session Control Cross-Surface Contract Matrix

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/session_suspend_write.py`.
- Added `tests/test_session_control_contract_matrix.py`.
- Aligned CLI suspend failure shaping with the shared API control contract.
- Locked API and CLI parity for cancel and suspend success, invalid-state,
  missing-session, and invalid-request control paths.
- Normalized CLI-only local context such as `database` out of the shared
  parity assertion, and normalized suspend `snapshot_id` because it is a
  runtime-local value rather than a stable cross-surface contract element.

Validation:

- `make sync`
- `uv run pytest tests/test_session_control_contract_matrix.py tests/cli/test_cli_session_cancel.py tests/cli/test_cli_commands.py tests/api/test_http_session_cancel.py tests/api/test_http_app.py tests/api/test_route_session_cancel.py tests/api/test_routes.py tests/worker/test_control.py tests/worker/test_execution.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/session_suspend_write.py apps/cli/src/zebra_agent_cli/cli.py tests/test_session_control_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local operators can now cancel a session from the CLI without depending on
  the HTTP API.
- API and CLI session control output now has an explicit, regression-tested
  shared parity boundary for both cancel and suspend.
- Cancelled, invalid-state, missing-session, suspended, invalid-request, and
  not-found control paths remain backward compatible across both operator
  control surfaces.

## Validation Notes

- Targeted worker, route, HTTP, CLI, and cross-surface control regression
  suites passed.
- `ruff`, `mypy`, and `make check` passed after the cancel restoration and
  control parity updates.
- The parity matrix intentionally treats CLI-local `database` as a CLI-only
  field and suspend `snapshot_id` as runtime-local metadata rather than a
  cross-surface contract field.

## Known Deferrals

- Session artifact list parity is still incomplete because the API exposes
  `/sessions/{id}/artifacts` while the local CLI still only supports
  `artifact inspect`, `artifact read`, and `artifact prune`.
- Artifact list output is therefore not yet locked by a dedicated API-vs-CLI
  contract matrix.

## Next Phase

Phase 54 should focus on session artifact list CLI and operator parity:

- add a local CLI artifact list surface for session-level artifact inventory
- define stable API and CLI parity rules for artifact list output
- record explicit artifact list parity evidence before expanding the next
  operator-facing lane
