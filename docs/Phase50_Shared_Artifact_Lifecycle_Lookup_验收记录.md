# Phase 50 Shared Artifact Lifecycle Lookup 验收记录

## Scope

Phase 50 extracted a shared helper for artifact lifecycle lookup by URI, then
adopted it in API artifact read surfaces and CLI artifact commands.

The phase stayed narrow. It preserved the current lifecycle payload semantics
and removed only repeated payload-to-lifecycle lookup logic.

## Completed Tasks

### P50-STO-01 - Shared Artifact Lifecycle Lookup Helper

Implemented behavior:

- Added `lifecycle_for_artifact_uri()` to
  `packages/agent-storage/src/agent_storage/artifact_projection.py`.
- Exported the shared helper through `agent_storage`.
- Added focused regression coverage in
  `tests/agent_storage/test_artifact_projection.py`.

Validation:

- `uv run pytest tests/agent_storage/test_artifact_projection.py`
- `uv run ruff check packages/agent-storage/src/agent_storage/artifact_projection.py packages/agent-storage/src/agent_storage/__init__.py tests/agent_storage/test_artifact_projection.py`
- `uv run mypy packages apps tests/agent_storage/test_artifact_projection.py`

### P50-API-01 - API Shared Artifact Lifecycle Lookup Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/session_read.py` to use the shared
  lifecycle lookup helper.
- Preserved the current API artifact lifecycle payload semantics.

### P50-CLI-01 - CLI Shared Artifact Lifecycle Lookup Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_read.py` to use the shared
  lifecycle lookup helper.
- Preserved the current CLI artifact lifecycle payload semantics.

Validation:

- `uv run pytest tests/agent_storage/test_artifact_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-storage/src/agent_storage/artifact_projection.py packages/agent-storage/src/agent_storage/__init__.py apps/api/src/zebra_agent_api/session_read.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/agent_storage/test_artifact_projection.py`
- `uv run mypy packages apps tests/agent_storage/test_artifact_projection.py`
- `make check`

## Acceptance Summary

- One shared helper now builds artifact lifecycle payloads deterministically.
- API and CLI artifact flows both reuse the same lifecycle lookup path.
- Existing lifecycle payload semantics remain backward compatible.

## Validation Notes

- Storage, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared lifecycle helper adoption landed.
- The phase changed lifecycle lookup reuse only, not artifact operator
  vocabulary.

## Known Deferrals

- Artifact payload lookup is still duplicated between API artifact access,
  artifact control, and CLI artifact flows.
- Lifecycle lookup is now shared, but payload lookup remains path-local.

## Next Phase

Phase 51 should focus on shared artifact payload lookup:

- extract one shared helper for artifact payload lookup by URI
- adopt the shared helper in API artifact access and control surfaces
- adopt the shared helper in CLI artifact flows
