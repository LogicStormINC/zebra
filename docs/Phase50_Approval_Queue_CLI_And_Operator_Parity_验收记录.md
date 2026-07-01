# Phase 50 Approval Queue CLI And Operator Parity 验收记录

## Scope

Phase 50 completed the operator parity loop for approval queue and approval
detail reads.

The phase first added local CLI read surfaces for waiting approvals, then
locked the shared API and CLI contract boundary with a dedicated cross-surface
regression matrix.

## Completed Tasks

### P50-CLI-01 - Approval Queue CLI Read Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/approval_read.py`.
- Added `zebra-agent approval queue` and
  `zebra-agent approval inspect <approval_id>` commands.
- Reused the existing projection-backed approval read model instead of
  introducing a second approval storage path.
- Added regression coverage for waiting-approval list, approval detail, and
  missing-approval CLI reads.

Validation:

- `make sync`
- `uv run pytest tests/cli/test_cli_approval_read.py tests/api/test_api_app.py tests/api/test_http_approvals.py tests/api/test_routes.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/approval_read.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py tests/cli/test_cli_approval_read.py`
- `uv run mypy packages apps`
- `make check`

### P50-TEST-01 - Approval Queue Cross-Surface Contract Matrix

Implemented behavior:

- Added `tests/test_approval_read_contract_matrix.py`.
- Locked API and CLI parity for waiting-approval list, empty queue, approval
  detail, and missing-approval paths.
- Normalized CLI-only local context such as `database` out of the shared
  parity assertion while preserving stable approval result fields.
- Recorded the parity boundary explicitly so future approval read changes do
  not drift across operator control paths.

Validation:

- `make sync`
- `uv run pytest tests/test_approval_read_contract_matrix.py tests/cli/test_cli_approval_read.py tests/api/test_api_app.py tests/api/test_http_approvals.py tests/api/test_routes.py`
- `uv run ruff check tests/test_approval_read_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local operators can now inspect the waiting approval queue and one approval
  detail from the CLI without depending on the HTTP API.
- API and CLI approval queue and detail output now has an explicit,
  regression-tested shared parity boundary.
- Waiting-approval list, detail, empty-queue, and missing-approval paths
  remain backward compatible across both operator read surfaces.

## Validation Notes

- Targeted CLI, API, and cross-surface approval read regression suites passed.
- `ruff`, `mypy`, and `make check` passed after the approval queue CLI and
  matrix updates.
- The parity matrix intentionally treats CLI-local `database` context as a
  CLI-only field rather than a cross-surface contract element.

## Known Deferrals

- Approval decision write parity still relies on separate CLI and HTTP API
  regression suites instead of one explicit cross-surface contract matrix.
- Operator guidance now covers approval readback, but approval decision result
  parity is still only implicitly enforced through surface-local tests.

## Next Phase

Phase 51 should focus on approval decision cross-surface parity:

- define stable API and CLI parity rules for approval grant, reject,
  invalid-state, and missing-session operator results
- normalize CLI-only local context out of the shared approval decision
  contract
- record explicit decision-surface parity evidence before expanding the next
  operator-facing lane
