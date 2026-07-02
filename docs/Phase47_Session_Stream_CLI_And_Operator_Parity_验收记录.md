# Phase 47 Session Stream CLI And Operator Parity 验收记录

## Scope

Phase 47 completed the operator parity loop for persisted session event replay.

The phase first added a local CLI read surface for session stream inspection,
then locked the shared HTTP SSE replay and CLI contract boundary with a
dedicated cross-surface regression matrix.

## Completed Tasks

### P47-CLI-01 - Session Stream CLI Read Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/session_stream_read.py`.
- Added a top-level `zebra-agent stream <session_id>` command.
- Reused the existing persisted session event projection shape instead of
  introducing a new event serializer path.
- Added regression coverage for populated, bootstrap-only, and missing-session
  CLI stream reads.

Validation:

- `uv run pytest tests/cli/test_cli_session_stream.py tests/api/test_api_app.py tests/api/test_http_app.py tests/api/test_routes.py -k stream`
- `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_stream_read.py tests/cli/test_cli_session_stream.py`
- `uv run mypy packages apps`
- `make check`

### P47-TEST-01 - Session Stream Cross-Surface Contract Matrix

Implemented behavior:

- Added `tests/test_session_stream_contract_matrix.py`.
- Locked HTTP SSE replay and CLI parity for populated, bootstrap-only, and
  missing-session stream reads.
- Normalized transport-specific context such as SSE framing and CLI-local
  `database` metadata out of the shared parity assertion while preserving the
  stable contract on persisted event payload fields.
- Covered both multi-event replay and bootstrap-only replay through the
  combined regression suite.

Validation:

- `uv run pytest tests/test_session_stream_contract_matrix.py tests/cli/test_cli_session_stream.py tests/api/test_api_app.py tests/api/test_http_app.py tests/api/test_routes.py -k stream`
- `uv run ruff check tests/test_session_stream_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local operators can now inspect persisted session event streams from the CLI
- HTTP SSE replay and CLI session stream output now have an explicit,
  regression-tested shared parity boundary
- Populated replay, bootstrap-only replay, and missing-session reads remain
  backward compatible across both operator read surfaces

## Validation Notes

- Targeted CLI, HTTP API, route, and cross-surface stream regression suites passed
- `ruff`, `mypy`, and `make check` passed after the session stream CLI and
  matrix updates
- The parity matrix intentionally treats SSE framing and CLI-local `database`
  context as transport-specific rather than cross-surface contract elements

## Known Deferrals

- Local operators still rely on the HTTP API for session commit execution
- Commit and pull-request operator guidance should keep expanding as more local
  CLI delivery surfaces reach parity

## Next Phase

Phase 48 should focus on session commit CLI and operator parity:

- add a local CLI command for session commit execution
- define stable API and CLI parity rules for commit success, unavailable, and
  idempotent replay paths
- extend operator guidance so local commit execution no longer depends on the
  HTTP API
