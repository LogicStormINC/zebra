# Phase 41 Shared Artifact Control Success Projection And Prune Success Parity 验收记录

## Scope

Phase 41 adopted shared prune success projection helper paths in both API and
CLI control adapters, then expanded cross-surface prune success contract
coverage.

The phase centralized prune success-envelope construction behind shared adapter
helpers while preserving the existing operator-facing prune success contracts.

The phase did not yet centralize prune audit metadata assembly across API and
CLI control adapters.

## Completed Tasks

### P41-API-01 - API Shared Artifact Control Success Projection

Implemented behavior:

- Added a shared API prune-control success response helper in
  `apps/api/src/zebra_agent_api/artifact_access.py`.
- `apps/api/src/zebra_agent_api/session_artifact_control.py` now reuses the
  shared helper path for prune success responses.
- Existing API prune success contracts remain backward compatible.
- Added more explicit regression coverage for success response fields and
  lifecycle boundaries.

Validation:

- `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py tests/api/test_session_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/api/test_session_artifacts.py`
- `make check`

### P41-CLI-01 - CLI Shared Artifact Control Success Projection

Implemented behavior:

- Added a shared CLI prune-control success result helper in
  `apps/cli/src/zebra_agent_cli/artifact_access.py`.
- `apps/cli/src/zebra_agent_cli/artifact_read.py` now reuses the shared helper
  path for prune success results.
- Existing CLI prune success contracts remain backward compatible and preserve
  the local `database` field.
- Added more explicit regression coverage for success result fields.

Validation:

- `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/cli/test_cli_artifacts.py`
- `make check`

### P41-TEST-01 - Artifact Prune Success Contract Matrix Expansion

Implemented behavior:

- Expanded `tests/test_artifact_access_contract_matrix.py`.
- Added explicit cross-surface parity coverage for `prune_success` and
  `prune_already_pruned`.
- Normalized non-stable lifecycle timestamps so the matrix locks the stable
  contract rather than exact transient values.

Validation:

- `uv run ruff check tests/test_artifact_access_contract_matrix.py apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py tests/test_artifact_access_contract_matrix.py`
- `make check`

## Acceptance Summary

- API and CLI prune success envelopes now each have one shared helper path
  instead of inline repeated result assembly.
- Cross-surface parity coverage now explicitly protects both `pruned` and
  `already_pruned` control results.
- Operator-facing prune success payloads remain backward compatible.

## Validation Notes

- Targeted `ruff`, `mypy`, API, CLI, and contract-matrix suites passed.
- `make check` passed after both success-helper adoption slices and closeout
  updates.
- Prune control audit metadata remains adapter-local in this phase.

## Known Deferrals

- API prune audit metadata assembly remains adapter-local.
- CLI prune audit metadata assembly remains adapter-local.
- Cross-surface audit metadata parity for prune control paths is not yet locked
  by a dedicated helper boundary.

## Next Phase

Phase 42 should focus on shared artifact control audit metadata:

- extract a shared prune control audit-metadata helper
- adopt that helper across API and CLI control adapters
- add regression coverage for deterministic prune audit metadata parity
