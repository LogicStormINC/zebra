# Phase 39 CLI Shared Denial Response Reuse And Failure Contract Parity 验收记录

## Scope

Phase 39 adopted shared denial or unavailable response helper paths in the CLI
artifact read adapters and expanded cross-surface failure contract coverage.

The phase centralized CLI artifact read failure-envelope construction behind a
shared adapter helper while preserving CLI-local `database` context and
existing prune behavior.

The phase did not yet centralize prune denied or prune unavailable response
construction across API and CLI control adapters.

## Completed Tasks

### P39-CLI-01 - CLI Shared Denial Response Adoption

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/artifact_access.py`.
- CLI artifact inspect and read paths now reuse shared denial and unavailable
  response helper paths.
- Existing CLI `database` context and prune-deny or prune-unavailable contracts
  remain backward compatible.

Validation:

- `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
- `uv run mypy packages apps`
- `uv run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
- `make check`

### P39-TEST-01 - Artifact Failure Contract Matrix Expansion

Implemented behavior:

- Expanded `tests/test_artifact_access_contract_matrix.py`.
- Added explicit `detail_denied` parity coverage after shared CLI helper
  adoption.
- Existing content deny, unavailable, pruned, and allowed parity coverage stays
  green.

Validation:

- `uv run ruff check apps/cli/src/zebra_agent_cli/artifact_access.py apps/cli/src/zebra_agent_cli/artifact_read.py tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
- `uv run mypy packages apps`
- `uv run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py tests/test_artifact_access_contract_matrix.py`
- `make check`

## Acceptance Summary

- CLI artifact read failures now share a stable helper path instead of inline
  repeated envelope assembly.
- Cross-surface contract coverage now explicitly protects detail-denied parity
  in addition to content failure cases.
- Shared helper adoption across API and CLI remains backward compatible for
  existing operator-facing payloads.

## Validation Notes

- Targeted `ruff`, `mypy`, CLI, and contract-matrix suites passed.
- `make check` passed after the CLI helper adoption and matrix expansion.
- CLI prune failure paths intentionally remain adapter-local because they still
  differ from read failure envelopes and have not yet been centralized.

## Known Deferrals

- API prune denied and prune unavailable response shaping remains adapter-local.
- CLI prune denied and prune unavailable response shaping remains adapter-local.
- Cross-surface prune control response parity is not yet locked by a dedicated
  contract matrix.

## Next Phase

Phase 40 should focus on shared artifact control response reuse and prune
contract parity:

- centralize API prune denied and unavailable response helper paths
- centralize CLI prune denied and unavailable response helper paths
- expand cross-surface contract coverage for prune control responses
