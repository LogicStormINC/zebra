# Phase 42 Shared Artifact Control Audit Metadata Helper 验收记录

## Scope

Phase 42 extracted a shared artifact control audit-metadata helper into
`agent-security` and adopted that helper in API prune audit paths.

The phase centralized deterministic prune audit metadata assembly for denied,
success, and unavailable control results while preserving the current operator-
facing prune audit semantics.

The phase did not yet converge read-side and control-side artifact audit helper
boundaries.

## Completed Tasks

### P42-OBS-01 - Shared Artifact Control Audit Metadata Helper

Implemented behavior:

- Added `packages/agent-security/src/agent_security/artifact_control_audit.py`.
- Centralized `build_artifact_control_audit_metadata()` for prune denied,
  prune success, and prune unavailable audit payload assembly.
- API prune audit paths now reuse the shared helper boundary instead of
  building result metadata inline in the adapter.
- Added focused security-layer regression coverage for deterministic control
  audit metadata projection.

Validation:

- `uv run ruff check apps/api/src/zebra_agent_api/session_artifact_control.py packages/agent-security/src/agent_security tests/agent_security tests/api/test_session_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/agent_security/test_artifact_control_audit.py tests/api/test_session_artifacts.py`
- `make check`

## Acceptance Summary

- Shared artifact control audit metadata now has one reusable construction
  boundary in `agent-security`.
- API prune audit paths now consume the same shared control audit helper for
  denied, success, and unavailable results.
- Regression coverage protects the new control audit boundary directly and
  through API prune behavior.

## Validation Notes

- Targeted `ruff`, `mypy`, security, and API regression suites passed.
- `make check` passed after the helper adoption and closeout updates.
- CLI still has no delivery-audit sink, so this phase scoped the shared helper
  boundary and test coverage without introducing a new CLI audit persistence
  surface.

## Known Deferrals

- Read-side and control-side audit metadata still use separate shared helpers.
- Cross-surface audit metadata convergence across read and control paths is not
  yet complete.

## Next Phase

Phase 43 should focus on shared artifact audit metadata convergence:

- unify overlapping read-side and control-side artifact audit helper semantics
- adopt the converged helper vocabulary across API artifact adapters
- expand regression coverage for stable audit metadata boundaries
