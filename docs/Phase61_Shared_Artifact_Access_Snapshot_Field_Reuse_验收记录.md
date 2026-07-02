# Phase 61 Shared Artifact Access Snapshot Field Reuse 验收记录

## Scope

Phase 61 removed adapter-local artifact access serialization wrappers, then
adopted the shared serializer directly in API and CLI artifact flows.

The phase stayed narrow. It preserved the current artifact access snapshot
vocabulary and removed only local wrapper indirection.

## Completed Tasks

### P61-API-01 - API Shared Artifact Access Snapshot Reuse

Implemented behavior:

- Removed the API-local artifact access serialization wrapper from
  `apps/api/src/zebra_agent_api/artifact_access.py`.
- Updated API read paths in `apps/api/src/zebra_agent_api/session_read.py` to
  call `serialize_session_artifact_access_projection()` directly.
- Preserved the current API artifact operator payload semantics.

### P61-CLI-01 - CLI Shared Artifact Access Snapshot Reuse

Implemented behavior:

- Removed the CLI-local artifact access serialization wrapper from
  `apps/cli/src/zebra_agent_cli/artifact_access.py`.
- Updated CLI read and control paths in
  `apps/cli/src/zebra_agent_cli/artifact_read.py` and
  `apps/cli/src/zebra_agent_cli/artifact_access.py` to call
  `serialize_session_artifact_access_projection()` directly.
- Preserved the current CLI artifact operator payload semantics.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_read.py apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- API and CLI artifact flows now use the shared serializer directly for access
  snapshots.
- Adapter-local access serialization wrappers were removed.
- Existing artifact operator payload semantics remain backward compatible.

## Validation Notes

- API, CLI, artifact contract, and repository-wide checks passed.
- `make check` passed after direct shared serializer reuse landed.
- The phase changed adapter indirection only, not access snapshot vocabulary.

## Known Deferrals

- API and CLI still attach the same `"access": <serialized snapshot>` field in
  multiple read and control success paths.
- Access classification, serialization, denied-reason shaping, read-failure
  outcome projection, control failure outcome projection, control success
  outcome and lifecycle projection, and direct serializer reuse are now shared,
  but access snapshot attachment is still path-local.

## Next Phase

Phase 62 should focus on shared artifact access snapshot attachment:

- extract one shared helper for attaching `"access"` snapshots
- adopt the shared helper in API artifact detail and content success flows
- adopt the shared helper in CLI artifact detail, content, and control success flows
