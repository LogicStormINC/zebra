# Phase 40 Shared Artifact Control Response Reuse And Prune Contract Parity 验收记录

## Scope

Phase 40 adopted shared prune denied and unavailable response helper paths in
both API and CLI control adapters, then expanded cross-surface prune contract
coverage.

The phase centralized prune failure-envelope construction behind shared adapter
helpers while preserving the existing operator-facing prune contracts.

The phase did not yet centralize prune success response projection across API
and CLI control adapters.

## Completed Tasks

### P40-API-01 - API Shared Artifact Control Response Adoption

Implemented behavior:

- Added shared API prune-control denied and unavailable response helpers in
  `apps/api/src/zebra_agent_api/artifact_access.py`.
- `apps/api/src/zebra_agent_api/session_artifact_control.py` now reuses the
  shared helper path for prune denied and prune unavailable conflicts.
- Existing API prune contracts remain backward compatible and do not expose
  additive `access` metadata on prune failures.
- Added explicit external-reference prune unavailable regression coverage.

Validation:

- `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py tests/api/test_session_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/api/test_session_artifacts.py`
- `make check`

### P40-CLI-01 - CLI Shared Artifact Control Response Adoption

Implemented behavior:

- Added shared CLI prune-control denied and unavailable response helpers in
  `apps/cli/src/zebra_agent_cli/artifact_access.py`.
- `apps/cli/src/zebra_agent_cli/artifact_read.py` now reuses the shared helper
  path for prune denied and prune unavailable results.
- Existing CLI prune contracts remain backward compatible and preserve the
  adapter-local `database` field.
- Added explicit external-reference prune unavailable regression coverage.

Validation:

- `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py`
- `uv run mypy packages apps`
- `uv run pytest tests/cli/test_cli_artifacts.py`
- `make check`

### P40-TEST-01 - Artifact Prune Contract Matrix Expansion

Implemented behavior:

- Expanded `tests/test_artifact_access_contract_matrix.py`.
- Added explicit cross-surface parity coverage for `prune_denied` and
  `prune_unavailable_external_reference`.
- Existing read-side parity coverage remains intact.

Validation:

- `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py tests/test_artifact_access_contract_matrix.py`
- `uv run mypy packages apps`
- `uv run pytest tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py tests/test_artifact_access_contract_matrix.py`
- `make check`

## Acceptance Summary

- API and CLI prune failure envelopes now each have one shared helper path
  instead of inline repeated result assembly.
- Cross-surface parity coverage now explicitly protects prune denied and prune
  unavailable contracts.
- Operator-facing prune failure payloads remain backward compatible.

## Validation Notes

- Targeted `ruff`, `mypy`, API, CLI, and contract-matrix suites passed.
- `make check` passed after both control-helper adoption slices and closeout
  updates.
- Success-path prune response assembly remains adapter-local by design in this
  phase.

## Known Deferrals

- API prune success response projection remains adapter-local.
- CLI prune success response projection remains adapter-local.
- Cross-surface parity for prune success envelopes is not yet locked by a
  dedicated contract matrix.

## Next Phase

Phase 41 should focus on shared artifact control success projection and prune
success parity:

- centralize API prune success response projection and lifecycle assembly
- centralize CLI prune success response projection while preserving CLI-local
  context
- expand cross-surface contract coverage for prune success envelopes
