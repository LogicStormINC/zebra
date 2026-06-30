# Phase 36 Shared Artifact Projection Serialization And Adapter Reuse 验收记录

## Scope

Phase 36 extracted shared artifact projection serialization into
`agent-storage` and adopted that serializer in both API and CLI adapters.

The phase centralized payload lookup, lifecycle projection, retrieval-state
projection, and base artifact envelope assembly while preserving existing
operator-facing API and CLI contracts.

The phase did not yet centralize artifact access-context projection or
access-response assembly, which still remains adapter-local.

## Completed Tasks

### P36-STO-01 - Shared Artifact Projection Serializer

Implemented behavior:

- Added `packages/agent-storage/src/agent_storage/artifact_projection.py`.
- Centralized:
  - `payload_for_artifact_uri()`
  - `serialize_artifact_lifecycle()`
  - `serialize_artifact_retrieval()`
  - `serialize_session_artifact_projection()`
- Added focused storage-level regression coverage for payload lookup, lifecycle
  expiry, pruned retrieval, and base artifact envelope projection.

Validation:

- `poetry run pytest tests/agent_storage/test_artifact_projection.py tests/agent_storage/test_artifact_payloads.py tests/agent_storage/test_artifacts.py`
- `make check`

### P36-API-01 - API Adapter Shared Projection Adoption

Implemented behavior:

- API artifact list, detail, and content reads now reuse the shared storage
  artifact projection serializer.
- Removed API-local retrieval and lifecycle assembly duplication from
  `session_read.py`.
- Preserved existing access gating and delivery-audit semantics.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py tests/api/test_session_artifact_access_projection.py tests/test_artifact_access_contract_matrix.py`
- `make check`

### P36-CLI-01 - CLI Adapter Shared Projection Adoption

Implemented behavior:

- CLI artifact inspect and read now reuse the shared storage artifact
  projection serializer.
- Removed CLI-local retrieval and lifecycle assembly duplication from
  `artifact_read.py`.
- Preserved CLI-only local operator context such as `database`.

Validation:

- `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
- `make check`

## Acceptance Summary

- Artifact retrieval, lifecycle, and base envelope assembly now have one shared
  serializer boundary.
- API and CLI adapters now consume the same shared artifact projection path for
  common envelope fields.
- Regression coverage now protects the serializer boundary directly at the
  storage layer as well as through API and CLI surfaces.

## Validation Notes

- Targeted storage, API, CLI, and cross-surface matrix suites passed.
- `make check` passed after both adapter adoption slices.
- Shared envelope fields are now centralized; CLI-only local operator context
  fields remain intentionally adapter-local.

## Known Deferrals

- Artifact access-context calculation and additive access payload assembly still
  remain duplicated between API and CLI adapters.
- Delivery-audit result-metadata assembly is still adapter-local.
- Shared response shaping for access-denied or artifact-unavailable responses
  remains future work.

## Next Phase

Phase 37 should focus on shared artifact access projection and adapter reuse:

- extract shared artifact access-context and explainability projection helpers
- migrate API and CLI adapters onto the shared access projection path
- harden regression coverage around access-projection serializer stability
