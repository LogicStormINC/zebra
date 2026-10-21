# Host Connector Management Implementation Plan

> For agentic workers: use subagent-driven implementation with disjoint storage/HTTP paths and independent spec/quality reviews.

**Goal:** native approved connector publication and current binding CAS with preserved frozen history.

**Architecture:** reuse B1 Host approval and bounded transport; immutable native profiles, atomic binding/receipt/audit and shared writer guards; Go consumes only published public contract in a later task.

**Tech stack:** existing Python3.12/Pydantic/Psycopg/FastAPI, PostgreSQL, no new dependencies.

## Chunk 1: Persistence

- [x] Read task/spec. Add tests/agent_storage/test_host_connector_management.py red imports; run `uv run pytest -q tests/agent_storage/test_host_connector_management.py`, expect import failure initially.
- [x] Implement postgres/host_connector_management_migration.py v109 and catalog tail; extract actual HostManagementStore.authorized transaction with unchanged B1 semantics. Add host_connector_management.py with atomic read/apply/receipt/audit and typed snapshots.
- [x] Refactor host_connectors.py shared connection helpers, full immutability+legacy freeze guard/lock, actual legacy bind expected-revision SQL; test every writer/caller and preserved history.
- [x] Run same focused file with OWN new postgres:17-alpine, no existing DSN; expect all cases/zero skip including separate-process CAS, duplicate op, lock expiry, rotation, conflict rollback/freeze association/old-row preservation.

## Chunk 2: Adapter and developer contract

- [x] Add tests/api/test_host_connector_management.py strict/config/actual PG tests first. `uv run pytest -q tests/api/test_host_connector_management.py` initially fails missing module.
- [x] Extract shared bounded management_transport.py from B1; implement explicit DTO host_connector_config.py and endpoint host_connector_management.py; extend optional B1 config/actions and existing composition. No settings/http.py changes.
- [x] Real HTTP approved-vs-current GET, active/no-repoint disable, explicit reactivation, independent B1/B2 actions, invalid/deep/slow/huge JSON, unknown real COMMIT then exact replay, late-thread capacity; rerun `uv run pytest -q tests/api/test_host_connector_management.py tests/api/test_host_registry_management.py tests/api/test_runtime_management.py tests/agent_storage/test_host_connector_management.py` expecting all pass/zero skip.
- [x] Publish native OpenAPI/operator guide and source boundaries, review spec implementation then quality/security; resolve findings and rerun affected checks.

## Chunk 3: Final verification/delivery

- [x] Freeze source, run `make check` and `make test` with owned /tmp logs, exit0 required; keep skipped native environment gates distinct, preserve original dirty checkout.
- [x] Update PROGRESS/WORKLOG/task registry and evidence, link/size/diff/source hashes; prepare scoped native feature delivery, no merge/deploy/production migration. The delivery receipt confirms subsequent commit/push and remote SHA.
- [x] Prepare platform contract inventory/readiness/acceptance documentation, accurately separating Go workflow pending. After native commit/push, record the actual source/OpenAPI hash, rerun document checks, then commit/push the platform branch; the platform evidence and delivery receipt record completion without a self-referential native commit SHA.
