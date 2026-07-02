# Phase 60 Shared Artifact Control Success Lifecycle Attachment 验收记录

## Scope

Phase 60 extracted a shared helper for artifact control success lifecycle
attachment, then adopted it in API and CLI artifact control success flows.

The phase stayed narrow. It preserved the current control success lifecycle
vocabulary and removed only repeated adapter-local `lifecycle` attachment.

## Completed Tasks

### P60-SEC-01 - Shared Artifact Control Success Lifecycle Helper

Implemented behavior:

- Extended `serialize_artifact_control_success_outcome_fields()` in
  `packages/agent-security/src/agent_security/artifact_access_projection.py`
  so the shared helper now attaches `lifecycle`.
- Kept the shared helper exported through `agent_security`.
- Extended focused regression coverage in
  `tests/agent_security/test_artifact_access_projection.py`.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py`

### P60-API-01 - API Shared Artifact Control Success Lifecycle Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/artifact_access.py` to use the shared
  artifact control success helper for `lifecycle` attachment in prune success
  responses.
- Preserved the current API prune success vocabulary and operator-facing
  payload semantics.

### P60-CLI-01 - CLI Shared Artifact Control Success Lifecycle Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_access.py` to use the shared
  artifact control success helper for `lifecycle` attachment in prune success
  results.
- Preserved the current CLI prune success vocabulary and operator-facing
  payload semantics.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py`
- `make check`

## Acceptance Summary

- One shared helper now projects artifact control success lifecycle fields
  deterministically.
- API and CLI control success flows both reuse the same lifecycle attachment
  path.
- Existing control success lifecycle vocabulary remains backward compatible.

## Validation Notes

- Security, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared artifact control success lifecycle helper
  adoption landed.
- The phase changed control success lifecycle reuse only, not artifact operator
  vocabulary.

## Known Deferrals

- API and CLI still keep the same tiny local `serialize_artifact_access(...)`
  wrappers over the shared access serializer.
- Access classification, serialization, denied-reason shaping, read-failure
  outcome projection, control failure outcome projection, and control success
  outcome plus lifecycle projection are now shared, but direct adapter access
  snapshot reuse is still path-local.

## Next Phase

Phase 61 should focus on shared artifact access snapshot field reuse:

- remove API-local access serialization wrapper in favor of the shared serializer
- remove CLI-local access serialization wrapper in favor of the shared serializer
- keep artifact operator payload semantics unchanged while shrinking adapter code
