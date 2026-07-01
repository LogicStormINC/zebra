# Phase 49 Session Pull Request CLI And Operator Parity 验收记录

## Scope

Phase 49 completed the operator parity loop for session pull-request planning
and guarded execution.

The phase first added a local CLI write surface for session pull-request
delivery, then locked the shared API and CLI contract boundary with a
dedicated cross-surface regression matrix.

## Completed Tasks

### P49-CLI-01 - Session Pull Request CLI Delivery Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/session_pull_request_write.py`.
- Added a top-level `zebra-agent pull-request <session_id>` command.
- Reused the existing `ZebraAgentApi.open_session_pull_request` composition
  path instead of introducing a second SCM gateway assembly stack.
- Added regression coverage for dry-run, created, policy-blocked, unavailable,
  missing-session, invalid-request, and idempotent replay CLI pull-request
  flows.

Validation:

- `make sync`
- `uv run pytest tests/cli/test_cli_session_pull_request.py tests/api/test_session_pull_request.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/session_pull_request_write.py tests/cli/test_cli_session_pull_request.py`
- `uv run mypy packages apps`
- `make check`

### P49-TEST-01 - Session Pull Request Cross-Surface Contract Matrix

Implemented behavior:

- Added `tests/test_session_pull_request_contract_matrix.py`.
- Locked API and CLI parity for dry-run, created, policy-blocked,
  unavailable, and missing-session pull-request paths.
- Normalized CLI-only local context such as `database` out of the shared
  parity assertion while preserving stable pull-request result fields and
  idempotent replay behavior.
- Covered both `API -> CLI` and `CLI -> API` replay consistency through the
  combined regression suite.

Validation:

- `make sync`
- `uv run pytest tests/test_session_pull_request_contract_matrix.py tests/cli/test_cli_session_pull_request.py tests/api/test_session_pull_request.py`
- `uv run ruff check tests/test_session_pull_request_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local operators can now open one session pull request from the CLI without
  depending on the HTTP API.
- API and CLI session pull-request output now has an explicit,
  regression-tested shared parity boundary.
- Pull-request dry-run, created, policy-blocked, unavailable, missing-session,
  and idempotent replay paths remain backward compatible across both operator
  delivery surfaces.

## Validation Notes

- Targeted CLI, API, and cross-surface session pull-request regression suites
  passed.
- `ruff`, `mypy`, and `make check` passed after the session pull-request CLI
  and matrix updates.
- The parity matrix intentionally treats CLI-local `database` context as a
  CLI-only field rather than a cross-surface contract element.

## Known Deferrals

- Local operators still rely on the HTTP API to inspect approval queue and
  approval detail read surfaces.
- Operator guidance for local control-plane readback should keep expanding as
  the remaining approval-facing CLI surfaces reach parity.

## Next Phase

Phase 50 should focus on approval queue CLI and operator parity:

- add local CLI read surfaces for approval queue and approval detail
- define stable API and CLI parity rules for waiting-approval list and detail
  reads
- extend operator guidance so approval inspection no longer depends on the
  HTTP API
