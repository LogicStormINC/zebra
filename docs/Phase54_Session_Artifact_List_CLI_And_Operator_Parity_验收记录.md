# Phase 54 Session Artifact List CLI And Operator Parity 验收记录

## Scope

Phase 54 completed the operator parity loop for session artifact list output.

The phase first added a local CLI artifact list surface for session-level
operator inventory, then locked the shared API and CLI artifact list boundary
with a dedicated cross-surface regression matrix for non-empty, empty, and
missing-session results.

## Completed Tasks

### P54-CLI-01 - Session Artifact List CLI Surface

Implemented behavior:

- Added `zebra-agent artifact list <session_id>`.
- Reused the existing CLI artifact projection and access serialization path
  instead of introducing a parallel artifact list formatter.
- Kept local artifact list output machine-readable for non-empty, empty, and
  missing-session paths.
- Preserved the existing API artifact list response shape while exposing the
  same session artifact inventory from the local CLI.

Validation:

- `make sync`
- `uv run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_commands.py`
- `make check`

### P54-TEST-01 - Session Artifact List Cross-Surface Contract Matrix

Implemented behavior:

- Added `tests/test_session_artifact_list_contract_matrix.py`.
- Locked API and CLI parity for session artifact list non-empty, empty, and
  missing-session paths.
- Explicitly normalized the CLI-local `database` field out of the shared
  contract assertion while keeping the artifact payload compared field-for-field
  otherwise.

Validation:

- `uv run pytest tests/test_session_artifact_list_contract_matrix.py tests/cli/test_cli_artifacts.py tests/api/test_session_artifacts.py tests/api/test_session_artifact_access_projection.py`
- `uv run ruff check tests/test_session_artifact_list_contract_matrix.py`
- `make check`

## Acceptance Summary

- Local operators can now list indexed session artifacts from the CLI without
  depending on the HTTP API.
- API and CLI session artifact list output now has an explicit,
  regression-tested shared parity boundary.
- Non-empty, empty, and missing-session artifact list paths remain backward
  compatible across both operator surfaces.

## Validation Notes

- Targeted CLI, API, and cross-surface artifact list regression suites passed.
- `make check` passed after the artifact list CLI and parity work landed.
- The parity matrix intentionally treats CLI-local `database` as a CLI-only
  field rather than a stable cross-surface contract element.

## Known Deferrals

- Session inspect parity is still incomplete because the API `GET /sessions/{id}`
  surface includes `approval_context`, while the local CLI `inspect` output does
  not yet have a dedicated parity alignment or contract matrix.
- Session inspect output is therefore not yet locked by a dedicated API-vs-CLI
  contract matrix.

## Next Phase

Phase 55 should focus on session inspect CLI and operator parity:

- align the local CLI inspect payload with the current API session read surface
- define stable API and CLI parity rules for session inspect output
- record explicit session inspect parity evidence before expanding the next
  operator-facing lane
