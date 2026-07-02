# Phase 49 Shared Artifact Content Availability Semantics 验收记录

## Scope

Phase 49 extracted a shared helper for mapping artifact content retrieval
status to unavailable reasons, then adopted it in both API artifact content
reads and CLI artifact read commands.

The phase stayed narrow. It preserved the current unavailable-reason vocabulary
and removed only repeated availability semantics.

## Completed Tasks

### P49-STO-01 - Shared Artifact Content Availability Helper

Implemented behavior:

- Added `artifact_content_unavailable_reason()` to
  `packages/agent-storage/src/agent_storage/artifact_projection.py`.
- Exported the shared helper through `agent_storage`.
- Added focused storage-layer regression coverage in
  `tests/agent_storage/test_artifact_projection.py`.

Validation:

- `uv run pytest tests/agent_storage/test_artifact_projection.py`
- `uv run ruff check packages/agent-storage/src/agent_storage/artifact_projection.py packages/agent-storage/src/agent_storage/__init__.py tests/agent_storage/test_artifact_projection.py`
- `uv run mypy packages apps tests/agent_storage/test_artifact_projection.py`

### P49-API-01 - API Shared Artifact Content Availability Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/session_read.py` to use the shared
  unavailable-reason helper for artifact content reads.
- Preserved the current API unavailable response and audit metadata semantics.

### P49-CLI-01 - CLI Shared Artifact Content Availability Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_read.py` to use the shared
  unavailable-reason helper for artifact content reads.
- Removed the CLI-local unavailable-reason mapping while preserving current
  operator payload semantics.

Validation:

- `uv run pytest tests/agent_storage/test_artifact_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-storage/src/agent_storage/artifact_projection.py packages/agent-storage/src/agent_storage/__init__.py apps/api/src/zebra_agent_api/session_read.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/agent_storage/test_artifact_projection.py`
- `uv run mypy packages apps tests/agent_storage/test_artifact_projection.py`
- `make check`

## Acceptance Summary

- One shared helper now maps artifact content retrieval status to unavailable
  reasons deterministically.
- API and CLI artifact content reads both reuse the same unavailable-reason
  vocabulary.
- Existing unavailable reasons remain backward compatible.

## Validation Notes

- Storage, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared availability helper adoption landed.
- The phase changed availability reuse only, not artifact operator vocabulary.

## Known Deferrals

- Artifact lifecycle lookup is still duplicated between API artifact reads and
  CLI artifact commands.
- Content availability semantics are now shared, but lifecycle lookup remains
  path-local.

## Next Phase

Phase 50 should focus on shared artifact lifecycle lookup:

- extract one shared helper for artifact lifecycle lookup by URI
- adopt the shared helper in API artifact read surfaces
- adopt the shared helper in CLI artifact commands
