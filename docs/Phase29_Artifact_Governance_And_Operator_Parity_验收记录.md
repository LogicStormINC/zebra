# Phase 29 Artifact Governance And Operator Parity 验收记录

## Scope

Phase 29 hardened the local artifact slice so operators can inspect, read, and
audit retained artifacts with explicit lifecycle semantics instead of relying on
file-presence guesses or API-only workflows.

The phase added CLI artifact inspection, delivery-audit coverage for artifact
reads, preview redaction metadata, and lifecycle-aware payload metadata that
distinguishes retained, missing, and pruned states.

The phase did not yet introduce configurable retention profiles, automatic
expiry sweeps, or artifact ACL enforcement. It stayed within the current
local-first artifact boundary.

## Completed Tasks

### P29-STO-01 - Artifact Metadata Governance

Implemented behavior:

- Extended durable artifact payload metadata with:
  - explicit `lifecycle_status`
  - optional `retained_until`
  - optional `pruned_at`
- Added incremental SQLite schema migration support for the new metadata fields.
- Added explicit pruned-payload handling so metadata survives file cleanup and
  subsequent reads fail with a stable `pruned` classification instead of an
  ambiguous missing-file error.
- Preserved backward compatibility for existing artifact retrieval flows.

Validation:

- `poetry run pytest tests/agent_storage/test_artifact_payloads.py`
- `make check`

### P29-CLI-01 - Artifact Inspect And Read Commands

Implemented behavior:

- Added `zebra-agent artifact inspect <session_id> <artifact_id>`.
- Added `zebra-agent artifact read <session_id> <artifact_id>`.
- Aligned CLI retrieval-state output with API semantics for:
  - `indexed_only`
  - `payload_available`
  - `payload_missing`
  - `external_reference`
- Kept content retrieval machine-readable with base64 payload output.

Validation:

- `poetry run pytest tests/cli/test_cli_artifacts.py tests/cli/test_cli_commands.py`
- `make check`

### P29-OBS-01 - Artifact Audit And Preview Redaction

Implemented behavior:

- Added explicit `preview_state` metadata for artifact list and detail previews.
- Added delivery-audit records for artifact detail and content reads keyed by
  session and artifact identifier.
- Added redaction and truncation handling for sensitive previews while
  preserving existing non-sensitive preview behavior.

Validation:

- `poetry run pytest tests/agent_storage/test_artifacts.py tests/api/test_session_artifacts.py tests/api/test_session_delivery_audit.py`
- `make check`

## Acceptance Summary

- Operators can now inspect and read local artifacts through both API and CLI
  surfaces without falling back to raw storage paths.
- Artifact previews and read paths now carry explicit safety metadata through
  `preview_state` and delivery-audit records.
- Durable payload metadata now distinguishes `available`, `missing`, and
  `pruned` states while keeping existing retrieval contracts backward
  compatible.
- The repository now has a coherent local artifact governance baseline without
  widening into remote storage or multi-tenant controls.

## Validation Notes

- Targeted Phase 29 regression suites passed for storage, CLI, and API surfaces.
- `make check` passed after the lifecycle-governance slice and again for the
  closeout line.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Retention is recorded in metadata but not yet driven by configurable policy
  profiles.
- Artifact expiry does not yet have an automatic sweep or operator-triggered
  prune workflow.
- Artifact ACL modeling and multi-tenant access enforcement remain later-phase
  work.
- Remote object storage, signed retrieval, and non-local artifact delivery are
  still deferred.

## Next Phase

Phase 30 should focus on local artifact retention enforcement:

- define deterministic artifact retention profiles in policy and core contracts
- add storage-side expiry sweep and prune enforcement for retained payloads
- expose retention and prune metadata through operator read surfaces
