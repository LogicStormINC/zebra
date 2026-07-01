# Phase 46 Session Diff CLI And Operator Parity 验收记录

## Scope

Phase 46 completed the operator parity loop for session workspace diff
inspection.

The phase first added a local CLI read surface for session diff inspection,
then locked the shared API and CLI contract boundary with a dedicated
cross-surface regression matrix.

## Completed Tasks

### P46-CLI-01 - Session Diff CLI Read Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/session_diff_read.py`.
- Added a top-level `zebra-agent diff <session_id>` command.
- Reused the existing workspace diff service and session bootstrap
  `workspace_root` instead of introducing a new runtime adapter path.
- Added regression coverage for dirty, clean, missing-session, and non-git
  workspace diff reads from the CLI.

Validation:

- `uv run pytest tests/cli/test_cli_session_diff.py tests/api/test_session_diff.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_diff_read.py tests/cli/test_cli_session_diff.py`
- `uv run mypy packages apps`
- `make check`

### P46-TEST-01 - Session Diff Cross-Surface Contract Matrix

Implemented behavior:

- Added `tests/test_session_diff_contract_matrix.py`.
- Locked API and CLI parity for dirty, clean, missing-session, and non-git
  session diff reads.
- Normalized CLI-only local context such as `database` out of the shared parity
  assertion while preserving stable contract coverage for `workspace`, `clean`,
  `git_status`, `diff`, and deterministic unavailable reasons.
- Covered both successful unified diff reads and deterministic unavailable
  states through the combined regression suite.

Validation:

- `uv run pytest tests/test_session_diff_contract_matrix.py tests/api/test_session_diff.py tests/cli/test_cli_session_diff.py`
- `uv run ruff check tests/test_session_diff_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local operators can now inspect session workspace diffs from the CLI without
  depending on the HTTP API.
- API and CLI session diff output now has an explicit, regression-tested shared
  parity boundary.
- Dirty, clean, missing-session, and non-git diff reads remain backward
  compatible across both read surfaces.

## Validation Notes

- Targeted CLI, API, and cross-surface session diff regression suites passed.
- `ruff`, `mypy`, and `make check` passed after the session diff CLI and matrix
  updates.
- The parity matrix intentionally treats CLI-local `database` context as a
  CLI-only field rather than a cross-surface contract element.

## Known Deferrals

- Local operators still rely on the HTTP API for session stream replay.
- Operator guidance for local persisted event replay should keep expanding as
  more local CLI read surfaces reach parity.

## Next Phase

Phase 47 should focus on session stream CLI and operator parity:

- add a local CLI read surface for session stream inspection
- define stable API and CLI parity rules for persisted event replay
- extend operator guidance so local event replay no longer depends on the HTTP
  API
