# Phase 43 Shared Artifact Audit Metadata Convergence 验收记录

## Scope

Phase 43 converged the overlapping read-side and control-side artifact audit
helper semantics onto one shared lower-level builder inside `agent-security`.

The phase preserved the existing read-side and control-side wrapper functions,
so API adapter contracts and current audit vocabulary stayed backward
compatible while the underlying audit metadata construction logic stopped
duplicating core projection rules.

The phase did not yet add a dedicated contract matrix for artifact delivery
audit payloads themselves.

## Completed Tasks

### P43-OBS-01 - Shared Artifact Audit Metadata Convergence

Implemented behavior:

- Added `packages/agent-security/src/agent_security/artifact_audit_metadata.py`.
- Centralized `artifact_id`, access projection fields, `result_status`,
  optional retrieval state, and configurable reason-key handling in one shared
  lower-level builder.
- `build_artifact_access_audit_metadata()` and
  `build_artifact_control_audit_metadata()` now both delegate to the same
  underlying builder.
- Added focused security-layer regression coverage for shared reason-field
  variants while preserving existing API prune audit behavior.

Validation:

- `uv run ruff check packages/agent-security/src/agent_security tests/agent_security apps/api/src/zebra_agent_api/session_artifact_control.py tests/api/test_session_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/agent_security/test_artifact_access_audit.py tests/agent_security/test_artifact_control_audit.py tests/api/test_session_artifacts.py`
- `make check`

## Acceptance Summary

- Shared artifact audit metadata now has one converged lower-level builder
  boundary in `agent-security`.
- Read-side and control-side helpers preserve their current outward semantics
  while sharing the same underlying projection rules.
- Regression coverage now protects both wrapper behavior and the shared builder
  semantics.

## Validation Notes

- Targeted `ruff`, `mypy`, security, and API regression suites passed.
- `make check` passed after the convergence helper and closeout updates.
- No adapter contract changes were introduced in this phase.

## Known Deferrals

- Artifact delivery-audit payloads do not yet have a dedicated contract matrix.
- CLI still has no delivery-audit persistence surface, so convergence remains
  scoped to shared helper semantics and API-backed validation.

## Next Phase

Phase 44 should focus on artifact audit metadata contract coverage:

- add explicit regression coverage for artifact delivery-audit payload shapes
- lock stable read-side and control-side audit metadata semantics in tests
- document the audit metadata boundary for future adapter work
