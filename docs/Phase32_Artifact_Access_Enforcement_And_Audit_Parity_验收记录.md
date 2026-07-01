# Phase 32 Artifact Access Enforcement And Audit Parity 验收记录

## Scope

Phase 32 turned artifact access classification from a passive contract into an
enforced read boundary with matching CLI behavior and expanded audit metadata.

The phase introduced API-side access gating for artifact detail and content
reads, aligned CLI enforcement for inspect/read/prune flows, and expanded audit
metadata so allowed, denied, and unavailable artifact actions are
distinguishable.

The phase did not yet project access-class reasoning directly into list
responses or add richer operator guidance around denied reads. It stayed within
the current local-first artifact boundary.

## Completed Tasks

### P32-API-01 - Artifact Access Read Enforcement

Implemented behavior:

- Added access-class-aware gating for artifact detail and content reads.
- Read paths now distinguish policy-insufficient access from generic payload
  unavailability.
- Existing allowed read paths remain backward compatible for operator-safe
  artifacts and full-access sessions.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py`
- `make check`

### P32-CLI-01 - Artifact Access CLI Enforcement

Implemented behavior:

- Aligned CLI `artifact inspect`, `artifact read`, and `artifact prune` with the
  same access enforcement semantics used by the API.
- CLI read paths now emit explicit `artifact_access_denied` responses for
  policy-insufficient sessions.
- Existing allowed artifact flows remain backward compatible.

Validation:

- `poetry run pytest tests/cli/test_cli_artifacts.py`
- `make check`

### P32-OBS-01 - Artifact Access Audit Expansion

Implemented behavior:

- Expanded artifact detail/content/prune audit metadata with:
  - `access_class`
  - `required_policy_profile`
  - `session_policy_profile`
  - `result_status`
  - `retrieval_status` or explicit unavailable reason
- Audit output now distinguishes allowed, denied, and unavailable artifact
  actions using stable metadata fields.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py`
- `make check`

## Acceptance Summary

- Artifact detail and content reads now enforce access classes deterministically.
- CLI artifact actions now stay aligned with API access enforcement semantics.
- Artifact access decisions are now consistently auditable across read and prune
  actions.
- The repository now has a coherent local access-enforcement baseline without
  widening into remote storage or multi-tenant enforcement.

## Validation Notes

- Targeted Phase 32 regression suites passed for API and CLI surfaces.
- `make check` passed after the enforcement slices and again for the closeout
  line.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Artifact access class is still not projected directly in artifact list
  responses.
- Operator-facing denied responses do not yet carry richer remediation or policy
  explainability metadata.
- Remote object storage, signed retrieval, and multi-tenant artifact isolation
  remain deferred.

## Next Phase

Phase 33 should focus on access explainability and operator-facing projection:

- project artifact access class and effective policy requirements into read
  surfaces
- align CLI inspect output with access explainability metadata
- document operator remediation for denied artifact access paths
