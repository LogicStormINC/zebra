# Phase 38 Shared Artifact Audit Metadata And Denial Response Reuse 验收记录

## Scope

Phase 38 extracted a shared artifact access audit-metadata helper into
`agent-security` and adopted shared denial or unavailable response shaping in
the API artifact read adapters.

The phase centralized deterministic audit metadata assembly for allowed,
denied, and prune-success paths, and removed duplicated API read response
construction for access-denied and artifact-unavailable results while
preserving the current operator-facing contracts.

The phase did not yet adopt the same denial or unavailable response helper path
in the CLI adapter.

## Completed Tasks

### P38-OBS-01 - Shared Artifact Access Audit Metadata Helper

Implemented behavior:

- Added `packages/agent-security/src/agent_security/artifact_access_audit.py`.
- Centralized `build_artifact_access_audit_metadata()` for shared artifact
  access audit payload assembly.
- API read and prune audit paths now reuse the same shared helper boundary for
  common access metadata.
- Added focused security-layer regression coverage for deterministic allowed,
  denied, and prune-success metadata projection.

Validation:

- `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py packages/agent-security/src/agent_security tests/agent_security`
- `uv run mypy packages/agent-security/src/agent_security apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_artifact_control.py`
- `uv run pytest tests/agent_security/test_artifact_access_audit.py tests/agent_security/test_artifact_access_projection.py tests/api/test_session_artifacts.py tests/test_artifact_access_contract_matrix.py`
- `make check`

### P38-API-01 - API Shared Denial Response Adoption

Implemented behavior:

- API artifact detail and content adapters now reuse shared helper paths for
  access-denied and artifact-unavailable response construction.
- Denial-reason derivation is centralized behind one API helper boundary.
- Existing API response bodies remain backward compatible, including retained
  `access` payloads on read deny or unavailable results and unchanged prune
  deny semantics.

Validation:

- `uv run ruff check apps/api/src/zebra_agent_api/artifact_access.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/session_artifact_control.py`
- `uv run mypy packages apps`
- `uv run pytest tests/api/test_session_artifacts.py tests/test_artifact_access_contract_matrix.py tests/agent_security/test_artifact_access_audit.py`
- `make check`

## Acceptance Summary

- Shared artifact access audit metadata now has one reusable construction
  boundary in `agent-security`.
- API artifact read adapters now consume shared denial and unavailable response
  helper paths instead of rebuilding those envelopes inline.
- Regression coverage continues to protect operator-facing API and cross-surface
  access contracts.

## Validation Notes

- Focused `ruff`, `mypy`, security, API, and cross-surface regression suites
  passed.
- `make check` passed after the API response-helper adoption and closeout
  updates.
- API prune denial output intentionally remains adapter-local because its
  contract differs from read-denial responses and does not expose additive
  `access` metadata.

## Known Deferrals

- CLI artifact read adapters still assemble denial and unavailable responses
  locally.
- CLI prune unavailable and prune denied responses remain adapter-local.
- Cross-surface response-helper reuse is not fully complete until CLI adoption
  lands.

## Next Phase

Phase 39 should focus on CLI denial-response reuse and cross-surface failure
contract hardening:

- adopt shared denial and unavailable response helper paths in the CLI adapter
- preserve CLI-local `database` context and existing prune semantics
- expand cross-surface regression coverage around failure-envelope parity
