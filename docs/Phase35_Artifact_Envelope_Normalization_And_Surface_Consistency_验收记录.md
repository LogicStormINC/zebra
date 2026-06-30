# Phase 35 Artifact Envelope Normalization And Surface Consistency 验收记录

## Scope

Phase 35 normalized artifact response envelopes beyond the Phase 34 access
projection contract.

The phase made successful API artifact responses explicit, aligned CLI inspect
success envelopes with API detail semantics for shared fields, and expanded the
cross-surface regression matrix so success and unavailable payload shapes are
now protected in addition to access explainability fields.

The phase did not yet eliminate the remaining implementation duplication across
API and CLI adapters, and it intentionally kept CLI-only local operator context
fields such as `database` outside the strict parity contract.

## Completed Tasks

### P35-API-01 - Artifact Success Envelope Normalization

Implemented behavior:

- Added explicit `status: "ok"` to successful API artifact detail responses.
- Added explicit `status: "ok"` to successful API artifact content responses.
- Removed the need for tests to treat API success as an implicit 200-only
  contract.

Validation:

- `poetry run pytest tests/api/test_session_artifact_access_projection.py tests/api/test_session_artifacts.py tests/test_artifact_access_contract_matrix.py`
- `make check`

### P35-CLI-01 - Artifact Envelope Consistency Parity

Implemented behavior:

- CLI `artifact inspect` now includes `preview_state` and `lifecycle` in
  successful payload-backed and indexed-only responses.
- CLI artifact retrieval now distinguishes `payload_pruned` from generic
  `payload_missing` for unavailable content reads.
- CLI kept `database` as an explicit local operator field while aligning the
  shared artifact envelope fields with API semantics.

Validation:

- `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_artifact_access_explainability.py`
- `make check`

### P35-TEST-01 - Artifact Envelope Contract Matrix Expansion

Implemented behavior:

- Expanded `tests/test_artifact_access_contract_matrix.py`.
- The matrix now compares:
  - operator-safe detail envelopes
  - denied content envelopes
  - missing-payload unavailable envelopes
  - pruned-payload unavailable envelopes
  - full-access allowed content envelopes
- Shared cross-surface fields are now locked directly instead of only comparing
  access payload fragments.

Validation:

- `poetry run pytest tests/test_artifact_access_contract_matrix.py tests/api/test_session_artifacts.py tests/cli/test_cli_artifacts.py`
- `make check`

## Acceptance Summary

- Shared API and CLI artifact envelopes are now more deterministic for local
  operators.
- Success, denied, missing, and pruned artifact read paths now have stronger
  cross-surface regression protection.
- Remaining differences are now explicit boundary choices rather than accidental
  omissions.

## Validation Notes

- Targeted API, CLI, and matrix suites passed after the Phase 35 changes.
- `make check` passed after the envelope normalization and matrix expansion
  slices.
- CLI-specific local context fields remain outside the strict parity matrix by
  design.

## Known Deferrals

- API and CLI artifact serialization logic is still duplicated across adapters.
- Shared artifact envelope assembly has not yet been extracted into a reusable
  projection helper.
- Broader artifact read and prune projection consolidation remains future work.

## Next Phase

Phase 36 should focus on shared artifact projection serialization and adapter
reuse:

- extract shared artifact retrieval and lifecycle projection helpers
- migrate API and CLI adapters onto the shared projection path
- harden regression coverage around the shared serializer boundary
