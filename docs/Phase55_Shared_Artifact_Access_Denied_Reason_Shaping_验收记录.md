# Phase 55 Shared Artifact Access Denied Reason Shaping 验收记录

## Scope

Phase 55 extracted a shared helper for artifact access denied-reason
construction, then adopted it in API and CLI artifact flows.

The phase stayed narrow. It preserved the current denied-reason vocabulary and
removed only repeated adapter-local string assembly.

## Completed Tasks

### P55-SEC-01 - Shared Artifact Access Denied Reason Helper

Implemented behavior:

- Added `artifact_policy_denied_reason()` to
  `packages/agent-security/src/agent_security/artifact_access_projection.py`.
- Exported the shared helper through `agent_security`.
- Added focused regression coverage in
  `tests/agent_security/test_artifact_access_projection.py`.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py`

### P55-API-01 - API Shared Artifact Access Denied Reason Adoption

Implemented behavior:

- Updated `apps/api/src/zebra_agent_api/artifact_access.py` to use the shared
  artifact access denied-reason helper.
- Preserved the current API denied-reason vocabulary and operator-facing
  payload semantics.

### P55-CLI-01 - CLI Shared Artifact Access Denied Reason Adoption

Implemented behavior:

- Updated `apps/cli/src/zebra_agent_cli/artifact_access.py` to use the shared
  artifact access denied-reason helper.
- Preserved the current CLI denied-reason vocabulary and operator-facing
  payload semantics.

Validation:

- `uv run pytest tests/agent_security/test_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `uv run ruff check packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py tests/agent_security/test_artifact_access_projection.py`
- `uv run mypy packages/agent-security/src/agent_security/artifact_access_projection.py packages/agent-security/src/agent_security/__init__.py apps/api/src/zebra_agent_api/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_access.py`
- `make check`

## Acceptance Summary

- One shared helper now builds artifact access denied reasons deterministically.
- API and CLI artifact flows both reuse the same denied-reason path.
- Existing denied-reason vocabulary remains backward compatible.

## Validation Notes

- Security, API, CLI, and artifact contract regressions passed.
- `make check` passed after the shared denied-reason helper adoption landed.
- The phase changed denied-reason reuse only, not artifact operator vocabulary.

## Known Deferrals

- API and CLI prune success paths still project `access_class` and
  `required_policy_profile` separately.
- Denied-reason shaping is now shared, but control success access field
  projection is still path-local.

## Next Phase

Phase 56 should focus on shared artifact control success access field
projection:

- extract one shared helper for control success access fields
- adopt the shared helper in API artifact control success flows
- adopt the shared helper in CLI artifact control success flows
