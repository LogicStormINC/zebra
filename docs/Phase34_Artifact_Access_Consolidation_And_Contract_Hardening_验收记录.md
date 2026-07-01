# Phase 34 Artifact Access Consolidation And Contract Hardening 验收记录

## Scope

Phase 34 consolidated the additive artifact access projection contract after
Phase 33 introduced explainability metadata.

The phase reduced duplication in API and CLI access projection assembly,
aligned CLI unavailable responses with the same additive access vocabulary used
by the API, and added a cross-surface regression matrix that compares allowed,
denied, and unavailable artifact access paths directly.

The phase did not yet normalize all response-shape differences between API and
CLI success payloads, nor did it widen explainability beyond the current access
class, required policy, session policy, and allowed fields.

## Completed Tasks

### P34-API-01 - Artifact Access Projection Consolidation

Implemented behavior:

- Centralized API access-denied and artifact-unavailable response assembly.
- Centralized access-related delivery-audit metadata assembly for artifact read
  surfaces.
- Preserved the Phase 33 additive `access` response contract.

Validation:

- `poetry run pytest tests/api/test_session_artifact_access_projection.py tests/api/test_session_artifacts.py`
- `make check`

### P34-CLI-01 - Artifact Access CLI Shared Projection Reuse

Implemented behavior:

- Reused shared helper patterns in CLI artifact read flows for access-denied and
  artifact-unavailable responses.
- Added additive `access` metadata to CLI unavailable artifact read responses.
- Kept existing CLI success and denied payloads backward compatible apart from
  the additive explainability metadata.

Validation:

- `poetry run pytest tests/cli/test_cli_artifact_access_explainability.py tests/cli/test_cli_artifacts.py`
- `make check`

### P34-TEST-01 - Artifact Access Contract Regression Matrix

Implemented behavior:

- Added `tests/test_artifact_access_contract_matrix.py`.
- Locked API and CLI parity for:
  - operator-safe detail or inspect access projection
  - sensitive content deny projection
  - unavailable content projection
  - full-access allowed content projection
- The regression matrix now compares normalized access contract outputs across
  both surfaces instead of testing each surface in isolation only.

Validation:

- `poetry run pytest tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifact_access_projection.py tests/cli/test_cli_artifact_access_explainability.py tests/cli/test_cli_artifacts.py`
- `make check`

## Acceptance Summary

- Artifact access projection logic is now more centralized and easier to extend.
- CLI and API explainability vocabulary is now stable across allowed, denied,
  and unavailable artifact read paths.
- Cross-surface regression coverage now protects the access contract from silent
  drift during future refactors.

## Validation Notes

- Targeted API, CLI, and matrix regression suites passed.
- `make check` passed after the CLI reuse and matrix additions.
- The matrix intentionally tolerates the existing API success-response omission
  of explicit `status="ok"` while still enforcing the access payload contract.

## Known Deferrals

- API successful artifact content responses still omit explicit `status`, while
  CLI success responses include it.
- API and CLI still duplicate some non-access response envelope assembly beyond
  the consolidated access payload contract.
- Richer operator remediation hints remain deferred beyond the current access
  explainability fields.

## Next Phase

Phase 35 should focus on artifact response envelope normalization and broader
surface consistency:

- normalize successful artifact response envelopes across API and CLI
- reduce remaining artifact read response-shape drift outside the `access`
  payload
- extend regression coverage to explicitly lock normalized success envelopes
