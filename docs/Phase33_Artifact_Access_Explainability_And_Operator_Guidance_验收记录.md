# Phase 33 Artifact Access Explainability And Operator Guidance 验收记录

## Scope

Phase 33 projected artifact access decisions into operator-facing surfaces and
documented how local operators should interpret denied versus unavailable
artifact responses.

The phase introduced additive access metadata in API read responses, aligned CLI
inspect and read outputs with the same explainability fields, and added focused
operator guidance for policy escalation versus unavailable payload cases.

The phase did not yet consolidate shared access projection logic outside the
current API or CLI adapters, nor did it introduce richer policy explainability
beyond the current access class and required policy fields.

## Completed Tasks

### P33-API-01 - Artifact Access Projection Readback

Implemented behavior:

- Added additive `access` metadata to artifact read responses.
- Access projection now exposes:
  - `class`
  - `required_policy_profile`
  - `session_policy_profile`
  - `allowed`
- Denied and unavailable artifact reads now include the same access
  explainability block.

Validation:

- `poetry run pytest tests/api/test_session_artifact_access_projection.py tests/api/test_session_artifacts.py`
- `make check`

### P33-CLI-01 - Artifact Access Explainability Parity

Implemented behavior:

- Added additive `access` metadata to CLI artifact inspect and read output.
- CLI denied read results now carry the same machine-readable access
  explainability fields as API responses.
- Existing allowed artifact flows remain backward compatible apart from additive
  metadata.

Validation:

- `poetry run pytest tests/cli/test_cli_artifact_access_explainability.py tests/cli/test_cli_artifacts.py`
- `make check`

### P33-DOC-01 - Artifact Access Operator Guidance

Implemented behavior:

- Added `docs/artifact_access_operator_guidance.md`.
- Documented the difference between:
  - `artifact_access_denied`
  - `artifact_unavailable`
- Added local escalation guidance for when `full_access` is justified versus
  when payload regeneration or upstream metadata inspection is the right
  operator action.

Validation:

- `make check`

## Acceptance Summary

- Artifact access decisions are now explainable directly in operator-facing API
  and CLI surfaces.
- Denied versus unavailable artifact paths now have a documented remediation
  model for local operators.
- The repository now has a usable explainability baseline for artifact access
  without widening into broader policy UX work.

## Validation Notes

- Targeted Phase 33 regression suites passed for API and CLI explainability
  paths.
- `make check` passed after the explainability slices and again for the closeout
  line.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Access projection logic is still duplicated between API and CLI adapters.
- Policy explainability is still limited to access class and required policy; it
  does not yet include richer remediation or escalation hints in payloads.
- Remote object storage, signed retrieval, and multi-tenant artifact isolation
  remain deferred.

## Next Phase

Phase 34 should focus on artifact access decision consolidation and broader
surface reuse:

- centralize access decision and projection helpers for API and CLI reuse
- extend access projection consistency across remaining artifact-adjacent
  surfaces
- harden regression coverage around shared explainability contracts
