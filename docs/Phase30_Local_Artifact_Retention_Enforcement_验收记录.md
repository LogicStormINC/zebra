# Phase 30 Local Artifact Retention Enforcement 验收记录

## Scope

Phase 30 turned artifact retention from passive metadata into an enforceable
local lifecycle slice with deterministic policy defaults, storage-side expiry
sweep behavior, and operator-visible lifecycle readback.

The phase introduced retention profile contracts, policy-profile-to-retention
resolution, idempotent prune behavior, expiry sweep support, and API lifecycle
projection for payload-backed artifacts.

The phase did not yet add manual prune operator controls, artifact ACL
classification, or remote object storage. It stayed within the current
local-first artifact boundary.

## Completed Tasks

### P30-POL-01 - Artifact Retention Policy Profiles

Implemented behavior:

- Added `ArtifactRetentionProfile` and `ArtifactRetentionPolicy` domain models.
- Added deterministic retention defaults mapped from local policy profiles:
  - `local-bootstrap` and `read_only` -> `extended`
  - `workspace_write` -> `standard`
  - `full_access` and unknown profiles -> `short_lived`
- Added reusable `retained_until` calculation helpers for later storage and API
  slices.

Validation:

- `poetry run pytest tests/agent_core/test_artifact_retention.py tests/agent_security/test_artifact_retention_policy.py tests/agent_security/test_policy_profiles.py`
- `make check`

### P30-STO-01 - Artifact Retention Sweep And Prune Enforcement

Implemented behavior:

- Made `SQLiteArtifactPayloadStore.prune_payload()` idempotent for already-pruned
  payloads.
- Added `sweep_expired_payloads(as_of=...)` to prune active payloads whose
  `retained_until` is in the past.
- Preserved explicit lifecycle state so swept payloads remain distinguishable
  from generic missing-file cases.

Validation:

- `poetry run pytest tests/agent_storage/test_artifact_payloads.py`
- `make check`

### P30-API-01 - Artifact Lifecycle Operator Readback

Implemented behavior:

- Added additive `lifecycle` metadata to artifact list and detail responses for
  payload-backed local artifacts.
- Lifecycle readback now exposes:
  - `status`
  - `retained_until`
  - `pruned_at`
  - `expired`
- Artifact content reads now distinguish pruned payloads from generic missing
  payloads with explicit `artifact_payload_pruned` conflict semantics.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py`
- `make check`

## Acceptance Summary

- Local artifact retention defaults are now explicit and derived
  deterministically from the active policy profile.
- Storage now has an enforceable expiry path through idempotent prune and
  repeatable sweep behavior.
- Operators can inspect lifecycle state for payload-backed artifacts without
  direct database access.
- The repository now has a coherent local retention-enforcement baseline
  without widening into remote storage or multi-tenant ACL enforcement.

## Validation Notes

- Targeted Phase 30 regression suites passed for core, security, storage, and
  API surfaces.
- `make check` passed after the retention policy slice, after the storage sweep
  slice, and again for the closeout line.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Operators still do not have an explicit manual prune control through API or
  CLI.
- Artifact ACL classification and local access-control hooks are not yet
  modeled.
- Remote object storage, signed retrieval, and multi-tenant artifact isolation
  remain deferred.

## Next Phase

Phase 31 should focus on artifact operator controls and access foundations:

- define local artifact access classification and ACL-ready metadata contracts
- add explicit manual prune controls for operators
- expose lifecycle control flows through CLI parity
