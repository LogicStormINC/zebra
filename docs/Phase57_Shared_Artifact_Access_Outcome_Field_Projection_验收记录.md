# Phase 57 Shared Artifact Access Outcome Field Projection 验收记录

## Scope

Phase 57 extracted a shared helper for artifact access read-failure outcome
field projection, then adopted it in API and CLI artifact read-failure flows.

The phase stayed narrow. It preserved the current read-failure field
vocabulary and removed only repeated adapter-local `status` / `reason` /
`access` assembly.

## Completed Tasks

### P57-SEC-01 - Shared Artifact Access Outcome Fields Helper

Implemented behavior:

- Added `serialize_artifact_access_outcome_fields()` to
  `packages/agent-security/src/agent_security/artifact_access_projection.py`.
- Exported the shared helper through `agent_security`.
- Added focused regression coverage in
  `tests/agent_security/test_artifact_access_projection.py`.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py`

### P57-API-01 - API Shared Artifact Access Outcome Fields Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/artifact_access.py` to use the shared
  artifact access outcome fields helper for read-failure responses.
- Preserved the current API read-failure vocabulary and operator-facing payload
  semantics.

### P57-CLI-01 - CLI Shared Artifact Access Outcome Fields Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_access.py` to use the shared
  artifact access outcome fields helper for read-failure results.
- Preserved the current CLI read-failure vocabulary and operator-facing payload
  semantics.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py`
- `make check`

## Acceptance Summary

- One shared helper now projects artifact access read-failure outcome fields
  deterministically.
- API and CLI read-failure flows both reuse the same outcome field projection
  path.
- Existing read-failure field vocabulary remains backward compatible.

## Validation Notes

- Security, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared artifact access outcome fields helper
  adoption landed.
- The phase changed read-failure field reuse only, not artifact operator
  vocabulary.

## Known Deferrals

- API and CLI control denied and unavailable paths still assemble the same base
  `status` / `reason` fields separately.
- Access classification, serialization, denied-reason shaping, prune success
  access field projection, and read-failure outcome projection are now shared,
  but control-failure base outcome projection is still path-local.

## Next Phase

Phase 58 should focus on shared artifact control outcome field projection:

- extract one shared helper for control `status` / `reason` outcome fields
- adopt the shared helper in API artifact control failure flows
- adopt the shared helper in CLI artifact control failure flows
