# Phase 48 Session Commit CLI And Operator Parity 验收记录

## Scope

Phase 48 completed the operator parity loop for session commit execution.

The phase first added a local CLI write surface for session commit delivery,
then locked the shared API and CLI contract boundary with a dedicated
cross-surface regression matrix.

## Completed Tasks

### P48-CLI-01 - Session Commit CLI Delivery Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/session_commit_write.py`.
- Added a top-level `zebra-agent commit <session_id>` command.
- Reused the existing `SessionCommitApi` path instead of introducing a second
  commit orchestration stack.
- Added regression coverage for committed, policy-blocked, clean-workspace
  unavailable, missing-session, invalid-request, and idempotent replay CLI
  commit flows.

Validation:

- `uv run pytest tests/cli/test_cli_session_commit.py tests/api/test_session_commit.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/session_commit_write.py tests/cli/test_cli_session_commit.py`
- `uv run mypy packages apps`
- `make check`

### P48-TEST-01 - Session Commit Cross-Surface Contract Matrix

Implemented behavior:

- Added `tests/test_session_commit_contract_matrix.py`.
- Locked API and CLI parity for committed success, policy-blocked,
  clean-workspace unavailable, and missing-session commit paths.
- Normalized CLI-only local context such as `database` out of the shared parity
  assertion while preserving stable commit result fields and idempotent replay
  behavior.
- Covered both `API -> CLI` and `CLI -> API` replay consistency through the
  combined regression suite.

Validation:

- `make sync`
- `uv run pytest tests/test_session_commit_contract_matrix.py tests/cli/test_cli_session_commit.py tests/api/test_session_commit.py`
- `uv run ruff check tests/test_session_commit_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Local operators can now create one session commit from the CLI without
  depending on the HTTP API.
- API and CLI session commit output now has an explicit, regression-tested
  shared parity boundary.
- Commit success, policy-blocked, unavailable, missing-session, and idempotent
  replay paths remain backward compatible across both operator delivery
  surfaces.

## Validation Notes

- Targeted CLI, API, and cross-surface session commit regression suites passed.
- `ruff`, `mypy`, and `make check` passed after the session commit CLI and
  matrix updates.
- The parity matrix intentionally treats CLI-local `database` context as a
  CLI-only field rather than a cross-surface contract element.

## Known Deferrals

- Local operators still rely on the HTTP API for session pull-request planning
  and execution.
- Operator guidance for local delivery should keep expanding as the remaining
  SCM-facing CLI surfaces reach parity.

## Next Phase

Phase 49 should focus on session pull-request CLI and operator parity:

- add a local CLI control surface for session pull-request planning and guarded
  execution
- define stable API and CLI parity rules for dry-run, created, unavailable,
  policy-blocked, and idempotent replay paths
- extend operator guidance so local pull-request delivery no longer depends on
  the HTTP API
