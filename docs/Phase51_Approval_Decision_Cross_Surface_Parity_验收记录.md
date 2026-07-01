# Phase 51 Approval Decision Cross-Surface Parity 验收记录

## Scope

Phase 51 completed the operator parity loop for approval decision writes.

The phase aligned the local CLI approval decision payload with the API result
contract, then locked the shared API and CLI contract boundary with a
dedicated cross-surface regression matrix.

## Completed Tasks

### P51-TEST-01 - Approval Decision Cross-Surface Contract Matrix

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/approval_decision_write.py`.
- Moved CLI approval decision payload shaping out of `cli.py` and aligned it
  with API approval decision responses.
- Added `tests/test_approval_decision_contract_matrix.py`.
- Locked API and CLI parity for approval grant, reject, invalid-state, and
  missing-session paths.
- Normalized CLI-only local context such as `database` out of the shared
  parity assertion while preserving stable approval decision result fields and
  proxy-aware `approval_context`.

Validation:

- `make sync`
- `uv run pytest tests/test_approval_decision_contract_matrix.py tests/api/test_approval_api_app.py tests/api/test_http_approvals.py tests/cli/test_cli_commands.py`
- `uv run ruff check --fix apps/cli/src/zebra_agent_cli/cli.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/approval_decision_write.py apps/cli/src/zebra_agent_cli/cli.py tests/test_approval_decision_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local CLI approval decisions now return the same operator-facing result
  contract as the API, with CLI-local `database` context kept explicit.
- API and CLI approval decision output now has an explicit,
  regression-tested shared parity boundary.
- Grant, reject, invalid-state, and missing-session approval decision paths
  remain backward compatible across both operator write surfaces.

## Validation Notes

- Targeted CLI, API, and cross-surface approval decision regression suites
  passed.
- `ruff`, `mypy`, and `make check` passed after the CLI approval decision
  alignment and matrix updates.
- The parity matrix intentionally treats CLI-local `database` context as a
  CLI-only field rather than a cross-surface contract element.

## Known Deferrals

- Session message append is still API-only for operators; there is no local
  CLI append surface yet.
- Message append result parity is therefore not yet locked by a dedicated
  API-vs-CLI contract matrix.

## Next Phase

Phase 52 should focus on session message append CLI and operator parity:

- add a local CLI append surface for posting one more user message into a
  durable session
- define stable API and CLI parity rules for appended, invalid-request,
  not-found, and terminal-session append paths
- extend operator guidance so session continuation no longer depends on the
  HTTP API
