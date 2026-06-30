# Phase 31 Artifact Operator Controls And Access Foundations 验收记录

## Scope

Phase 31 established local artifact access foundations and operator-triggered
lifecycle controls so retained payloads can be classified and pruned
intentionally instead of only through automatic retention sweep behavior.

The phase introduced deterministic access classes, policy-facing access
classification rules, API manual prune control, and CLI parity for the same
lifecycle action semantics.

The phase did not yet enforce access classes on artifact read surfaces, nor did
it introduce remote object storage or multi-tenant ACL enforcement. It stayed
within the current local-first artifact boundary.

## Completed Tasks

### P31-SEC-01 - Artifact Access Classification Foundations

Implemented behavior:

- Added `ArtifactAccessClass` and `ArtifactAccessDescriptor` domain models.
- Added deterministic access classification rules for local artifacts:
  - `operator_safe`
  - `sensitive`
  - `restricted`
- Added policy-facing minimum-profile resolution for later operator controls and
  access enforcement.

Validation:

- `poetry run pytest tests/agent_core/test_domain_models.py tests/agent_security/test_artifact_access_policy.py tests/agent_security/test_policy_profiles.py`
- `make check`

### P31-API-01 - Artifact Manual Lifecycle Controls

Implemented behavior:

- Added `POST /sessions/{id}/artifacts/{artifact_id}/prune`.
- Manual prune now operates only on managed payload-backed local artifacts.
- Prune behavior is idempotent and distinguishes:
  - successful prune
  - already pruned
  - unavailable artifact targets
  - policy-denied sensitive targets
- Delivery audit now records manual prune attempts with access class and policy
  metadata.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py`
- `make check`

### P31-CLI-01 - Artifact Lifecycle CLI Controls

Implemented behavior:

- Added `zebra-agent artifact prune <session_id> <artifact_id>`.
- CLI prune output now mirrors API lifecycle-control semantics for:
  - `pruned`
  - `already_pruned`
  - `artifact_prune_unavailable`
  - `artifact_prune_denied`
- Existing artifact inspect and read behavior remains backward compatible.

Validation:

- `poetry run pytest tests/cli/test_cli_artifacts.py`
- `make check`

## Acceptance Summary

- The repository now has deterministic local artifact access classes suitable
  for later ACL-ready enforcement.
- Operators can explicitly prune managed artifact payloads through both API and
  CLI paths.
- Manual lifecycle control behavior is idempotent, machine-readable, and policy
  aware for sensitive artifact classes.
- Artifact operator controls now have a coherent local baseline without
  widening into remote storage or multi-tenant enforcement.

## Validation Notes

- Targeted Phase 31 regression suites passed for core, security, API, and CLI
  surfaces.
- `make check` passed after the access-foundation slice and again after the
  operator-control slices landed.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Artifact detail and content read surfaces still do not enforce access classes.
- Artifact access classification is not yet projected directly into operator
  read responses.
- Remote object storage, signed retrieval, and multi-tenant artifact isolation
  remain deferred.

## Next Phase

Phase 32 should focus on artifact access enforcement and audit parity:

- enforce access classes on artifact read surfaces
- align CLI read and inspect behavior with the same access enforcement
- expand audit metadata for access-denied and access-classified artifact actions
