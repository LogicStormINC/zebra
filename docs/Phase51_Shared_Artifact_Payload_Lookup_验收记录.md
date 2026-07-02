# Phase 51 Shared Artifact Payload Lookup 验收记录

## Scope

Phase 51 extracted a shared helper for artifact payload lookup by URI, then
adopted it in API artifact access or control surfaces and CLI artifact flows.

The phase stayed narrow. It preserved the current payload lookup semantics and
removed only repeated URI-to-payload resolution logic.

## Completed Tasks

### P51-STO-01 - Shared Artifact Payload Lookup Helper

Implemented behavior:

- Added `resolve_payload_for_artifact_uri()` to
  `packages/agent-storage/src/agent_storage/artifact_projection.py`.
- Exported the shared helper through `agent_storage`.
- Added focused regression coverage in
  `tests/agent_storage/test_artifact_projection.py`.

Validation:

- `uv run pytest tests/agent_storage/test_artifact_projection.py`
- `uv run ruff check packages/agent-storage/src/agent_storage/artifact_projection.py packages/agent-storage/src/agent_storage/__init__.py tests/agent_storage/test_artifact_projection.py`
- `uv run mypy packages apps tests/agent_storage/test_artifact_projection.py`

### P51-API-01 - API Shared Artifact Payload Lookup Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/artifact_access.py` to use the shared
  payload lookup helper.
- Updated `apps/api/src/zebra_agent_api/session_artifact_control.py` to use the
  same helper for prune payload resolution.
- Preserved the current API payload lookup semantics.

### P51-CLI-01 - CLI Shared Artifact Payload Lookup Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_read.py` to use the shared
  payload lookup helper.
- Preserved the current CLI payload lookup semantics.

Validation:

- `uv run pytest tests/agent_storage/test_artifact_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-storage/src/agent_storage/artifact_projection.py packages/agent-storage/src/agent_storage/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/agent_storage/test_artifact_projection.py`
- `uv run mypy packages apps tests/agent_storage/test_artifact_projection.py`
- `make check`

## Acceptance Summary

- One shared helper now resolves artifact payloads deterministically.
- API and CLI artifact flows both reuse the same payload lookup path.
- Existing payload lookup semantics remain backward compatible.

## Validation Notes

- Storage, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared payload helper adoption landed.
- The phase changed payload lookup reuse only, not artifact operator
  vocabulary.

## Known Deferrals

- Session policy profile lookup is still duplicated between API artifact access
  and CLI artifact flows.
- Payload lookup is now shared, but artifact access classification inputs are
  still partially path-local.

## Next Phase

Phase 52 should focus on shared session policy profile lookup:

- extract one shared helper for session policy profile lookup from workspace state
- adopt the shared helper in API artifact access classification
- adopt the shared helper in CLI artifact access classification
