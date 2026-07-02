# Phase 58 Shared Artifact Control Outcome Field Projection 验收记录

## Scope

Phase 58 extracted a shared helper for artifact control failure outcome field
projection, then adopted it in API and CLI artifact control failure flows.

The phase stayed narrow. It preserved the current control failure field
vocabulary and removed only repeated adapter-local `status` / `reason`
assembly.

## Completed Tasks

### P58-SEC-01 - Shared Artifact Control Outcome Fields Helper

Implemented behavior:

- Added `serialize_artifact_control_outcome_fields()` to
  `packages/agent-security/src/agent_security/artifact_access_projection.py`.
- Exported the shared helper through `agent_security`.
- Added focused regression coverage in
  `tests/agent_security/test_artifact_access_projection.py`.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py`

### P58-API-01 - API Shared Artifact Control Outcome Fields Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/artifact_access.py` to use the shared
  artifact control outcome fields helper for prune denied and unavailable
  responses.
- Preserved the current API prune failure vocabulary and operator-facing
  payload semantics.

### P58-CLI-01 - CLI Shared Artifact Control Outcome Fields Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_access.py` to use the shared
  artifact control outcome fields helper for prune denied and unavailable
  results.
- Preserved the current CLI prune failure vocabulary and operator-facing
  payload semantics.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py`
- `make check`

## Acceptance Summary

- One shared helper now projects artifact control failure outcome fields
  deterministically.
- API and CLI control failure flows both reuse the same outcome field
  projection path.
- Existing control failure field vocabulary remains backward compatible.

## Validation Notes

- Security, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared artifact control outcome fields helper
  adoption landed.
- The phase changed control failure field reuse only, not artifact operator
  vocabulary.

## Known Deferrals

- API and CLI control success paths still assemble the same `status` together
  with shared access fields separately.
- Access classification, serialization, denied-reason shaping, read-failure
  outcome projection, control failure outcome projection, and prune success
  access field projection are now shared, but control success outcome
  projection is still path-local.

## Next Phase

Phase 59 should focus on shared artifact control success outcome projection:

- extract one shared helper for control success `status` plus access fields
- adopt the shared helper in API artifact control success flows
- adopt the shared helper in CLI artifact control success flows
