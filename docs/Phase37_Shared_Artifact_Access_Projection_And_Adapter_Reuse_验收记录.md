# Phase 37 Shared Artifact Access Projection And Adapter Reuse 验收记录

## Scope

Phase 37 extracted shared artifact access projection into `agent-security` and
adopted that helper in both API and CLI adapters.

The phase centralized access explainability payload assembly and policy-rank
evaluation while preserving existing operator-facing API and CLI access
contracts, including deny, unavailable, and prune access semantics.

The phase did not yet centralize delivery-audit result metadata assembly or the
construction of access-denied and artifact-unavailable response bodies.

## Completed Tasks

### P37-SEC-01 - Shared Artifact Access Projection Serializer

Implemented behavior:

- Added `packages/agent-security/src/agent_security/artifact_access_projection.py`.
- Centralized:
  - `ArtifactAccessProjection`
  - `build_artifact_access_projection()`
  - `serialize_artifact_access_projection()`
  - `policy_rank()`
- Added focused security-layer regression coverage for operator-safe,
  sensitive, and policy-rank behavior.

Validation:

- `poetry run pytest tests/agent_security/test_artifact_access_policy.py tests/agent_security/test_artifact_access_projection.py tests/agent_security/test_policy_profiles.py`
- `make check`

### P37-API-01 - API Shared Access Projection Adoption

Implemented behavior:

- API artifact access adapters now reuse the shared security access projection
  helper.
- API prune control paths now follow the new shared string-based `access_class`
  semantics without changing the current operator-facing contract.
- Existing access payloads, audit metadata, and prune semantics remain
  backward compatible.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py tests/api/test_session_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py`
- `make check`

### P37-CLI-01 - CLI Shared Access Projection Adoption

Implemented behavior:

- CLI artifact access adapters now reuse the shared security access projection
  helper.
- CLI deny, unavailable, and prune access payloads remain backward compatible.
- CLI-specific local operator context fields remain adapter-local.

Validation:

- `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
- `make check`

## Acceptance Summary

- Access explainability payload construction now has one shared serializer
  boundary in `agent-security`.
- API and CLI now consume the same shared access projection path for common
  access fields.
- Regression coverage now protects the access projection boundary directly at
  the security layer and through API and CLI surfaces.

## Validation Notes

- Targeted security, API, CLI, and cross-surface matrix suites passed.
- `make check` passed after both adapter adoption slices.
- CLI-only local operator context fields and adapter-specific response-body
  assembly remain intentionally outside the shared access serializer boundary.

## Known Deferrals

- Delivery-audit result metadata assembly is still duplicated between API read
  and prune paths.
- Access-denied and artifact-unavailable response body construction remains
  adapter-local.
- Shared audit or denial-response shaping remains future work.

## Next Phase

Phase 38 should focus on shared artifact audit metadata and denial-response
reuse:

- extract shared artifact access audit-metadata helpers
- centralize access-denied and artifact-unavailable response shaping where
  possible
- harden regression coverage around shared audit and denial-response behavior
