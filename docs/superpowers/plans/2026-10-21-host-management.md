# Host Registry Management Implementation Plan

> For agentic workers: use subagent-driven implementation and independent spec/quality reviews, with disjoint storage and HTTP paths.

**Goal:** Native scoped online Host registry management; connector and Go consumption remain separate.

**Architecture:** Reuse HostRegistryRecord/registry table; mounted approved template and independent service credential; shared PostgreSQL approval + CAS + receipt/audit in short bounded transactions. Python owns all storage. No new dependencies.

## Chunk 1: Native persistence

- [x] Review spec and task ownership before coding; write actual PG red checks in tests/agent_storage/test_host_management.py.
- [x] Add host_management_migration.py v108 with registry revision, approvals, receipts and audit; append migration_catalog_tail. Existing rows default1, no removal.
- [x] Add postgres/host_management.py consumed application/storage API: HostManagementTrust, ManagedHostRegistry, approval CAS/read/apply and typed failures. Canonical receipts, current authorization before replay, atomic audit, per-binding short locks/timeout.
- [x] Existing host_auth.py privileged upsert increments revision; test stale API CAS and retained Host/replay data.
- [x] Test new PG concurrent conflict/replay/current trust revoke/expiry/different bindings and two independent process race.

## Chunk 2: HTTP/operator/native contract

- [x] Add apps/api host_registry_config.py strict private template loader; host_registry_management.py bounded GET/PUT adapter; host_registry_admin.py explicit approval tool via configured native database URL.
- [x] Add optional settings/environment path and http.py composition preserving lazy disabled startup.
- [x] Test strict real HTTP positive/negative/config/current storage, slow timeout capacity and secret omission; use tests/api/test_host_registry_management.py.
- [x] Add native OpenAPI docs/contracts/host-registry-management-v1.openapi.json and docs/HOST_REGISTRY_MANAGEMENT.md operator/rolling/reconciliation guide. Independent spec/quality review, resolve findings.

## Chunk 3: Verification and source delivery

- [x] Run focused new and Host management regressions against own disposable PG; no existing DB/container/service changes.
- [x] Run native make test/check and record passed/skipped/failures; explicit source hash and link/limits checks. No fake end-user or production HA claim.
- [x] Update native PROGRESS/registry/WORKLOG/README; scoped commit/push preserving original cloud-agent dirty work; no main/cloud-agent merge/deploy/production migration.
- [x] Overdoze contract inventory/readiness/plan/index/task records pin actual native published commit + contract hash; no Go client before contract finalization, no frontend changes. Validate doc links/diff, commit/push separately.

## Exact red/green execution

1. Add tests/agent_storage/test_host_management.py imports and cases for approve/apply/read, one-winner CAS, replay after response loss, changed-payload409, stale/disabled approval, legacy writer advance, lock-wait expiry rollback, and two independent processes. Run `uv run pytest -q tests/agent_storage/test_host_management.py`; expected initial collection/import failure until host_management.py exists. Fixture creates its OWN disposable postgres:17-alpine container, then invokes existing apply_postgres_migrations; no existing DSN accepted.
2. Implement packages/agent-storage/src/agent_storage/postgres/host_management_migration.py, append migration_catalog_tail.py; implement host_management.py and amend host_auth.py upsert revision. Run same exact command; expected all cases pass, zero skip. Unknown COMMIT is represented as503 at transport and reconciled by identical receipt lookup; never blindly retry a changed operation.
3. Add tests/api/test_host_registry_management.py strict transport/real PG fixtures plus bounded late-thread slot regression. Run `uv run pytest -q tests/api/test_host_registry_management.py`; expect import failure before route/config/admin implementation. Implement three named API files/settings/composition, rerun; expect all pass.
4. Run `uv run pytest -q tests/api/test_runtime_management.py tests/api/test_host_registry_management.py tests/agent_storage/test_host_management.py`; expect current descriptor regression and all new tests pass. Run `make check` then `make test` with logs in task-owned /tmp files; exit0 required, report skipped native suites separately.
5. Run `git diff --check`, line/link/source/contract hashes checks, independent spec/quality review. Scoped native commit/push then pin native commit and OpenAPI SHA in Overdoze docs/evidence/p1-e2b/native-host-management.json; verify doc links/diff and push platform documentation branch. No merge/deploy.

Source/remote SHA and dependent Overdoze documentation publication are confirmed separately in the delivery receipt; no commit embeds its own SHA.
