# Phase 28 Durable Artifact Storage And Retrieval 验收记录

## Scope

Phase 28 turned session artifacts from read-only indexed summaries into a
durable local artifact slice with payload persistence, worker capture, and
operator-safe retrieval.

The phase introduced a local payload store, wired worker-side capture for
supported tool outputs, and exposed artifact detail plus content retrieval over
the local API without widening into remote object storage.

The phase did not implement object-store adapters, artifact ACL enforcement, or
cross-tenant governance. It stayed within the repository's current local-first
artifact boundary.

## Completed Tasks

### P28-STO-01 - Durable Artifact Payload Store

Implemented behavior:

- Added durable artifact payload domain models and payload-store Port.
- Added `SQLiteArtifactPayloadStore` with:
  - SQLite-backed artifact payload metadata
  - local file-backed payload bytes
  - explicit missing-payload inspection
- Preserved backward compatibility for the existing session artifact list
  indexing path.

Validation:

- `poetry run pytest tests/agent_storage/test_artifact_payloads.py tests/agent_storage/test_artifacts.py tests/agent_core/test_domain_models.py`
- `make check`

### P28-WKR-01 - Worker Artifact Capture Wiring

Implemented behavior:

- Worker indexing now persists supported text tool outputs into the durable
  artifact payload store when no explicit `artifact_uri` is already present.
- Resulting `ToolRunRecord.artifact_uri` values now point at retained local
  payloads for those supported outputs.
- Existing explicit artifact references remain unchanged, so previously indexed
  external references stay backward compatible.

Validation:

- `poetry run pytest tests/worker/test_tool_run_index.py tests/worker/test_execution.py`
- `make check`

### P28-API-01 - Artifact Detail And Retrieval Surface

Implemented behavior:

- Added `GET /sessions/{id}/artifacts/{artifact_id}` for artifact detail and
  retrieval-state inspection.
- Added `GET /sessions/{id}/artifacts/{artifact_id}/content` for machine-readable
  base64 content retrieval of local payload-backed artifacts.
- Retrieval semantics now distinguish:
  - `indexed_only`
  - `payload_available`
  - `payload_missing`
  - `external_reference`
- Existing `GET /sessions/{id}/artifacts` list responses remain backward
  compatible.

Validation:

- `poetry run pytest tests/api/test_session_artifacts.py`
- `make check`

## Acceptance Summary

- Durable artifact payload metadata and payload bytes now exist independently of
  the earlier model-call and tool-run summary indexes.
- Worker execution can now produce local artifact references that survive beyond
  inline previews for supported tool outputs.
- Operators can distinguish indexed-only versus payload-backed artifact states
  through explicit API read surfaces.
- The repository keeps artifact storage, worker capture, and API retrieval
  aligned without widening into remote storage dependencies.

## Validation Notes

- Targeted Phase 28 regression suites passed for storage, worker, and API
  surfaces.
- `make check` passed after the retrieval endpoints and worker capture wiring
  landed.
- The closeout slice itself is documentation-only and reuses the already-green
  repository validation path.

## Known Deferrals

- Artifact retrieval is currently API-only; equivalent dedicated CLI artifact
  inspection commands do not yet exist.
- Artifact governance is still local-only. There is not yet retention policy
  configuration, artifact ACL modeling, or object-store offload.
- Model-call payloads are still represented mainly through indexed summaries;
  worker payload capture currently focuses on supported text tool outputs.
- Remote object storage, signed access, and multi-tenant artifact isolation
  remain later-phase work.

## Next Phase

Phase 29 should focus on artifact governance and operator parity:

- harden artifact metadata with retention, safe readback, and local lifecycle
  rules
- add CLI artifact inspection and content retrieval so operators are not API-only
- improve audit correlation and redaction around artifact reads and previews
