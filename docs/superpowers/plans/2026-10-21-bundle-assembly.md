# CA-P2-01B Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** bind immutable Runtime Bundles to Definition/Task snapshots and actually assemble compatible Workers without recovery drift.

**Architecture:** explicit v2 types preserve v1 canonical contracts. Trusted file resolution freezes configuration, additive PG sidecar persists it atomically, task-local Worker assembly refuses incompatible baselines before effects.

**Tech Stack:** existing Python 3.12/Pydantic/stdlib/httpx/psycopg/pytest; no new dependency.

## Chunk 1: Core binding and durable storage

- [x] Baseline: `uv run pytest -q tests/agent_core/test_runtime_bundle*.py tests/test_agent_definition_binding_contract_matrix.py`.
- [x] Implementer writes failing tests for v2 digest/scope/serialization, unknown formats, exact grant and environment mismatch, no release lookup on recovery, legacy goldens. Add domain/runtime_assembly.py (resolved nonsecret profile/config), bundle_definition.py (Version/Snapshot together, focused204lines) and central dispatch; use explicit model revalidation plus WrapValidator/SerializeAsAny at base-typed payload fields.
- [x] Reuse draft materialization with optional validated assembly; reject absent exact Bundle grant. Route publication/binding/projections/memory/recovery plus storage/workspaces.py and postgres/workspaces.py through explicit v2 dispatch; preserve v1 paths and algorithms.
- [x] Add postgres/bundle_definition_migration.py v110 and agent_registry_bundle.py, atomically store base row plus sidecar using same connection; read sidecar only for schema/2, validate full payload against base row. Update migration catalog and expectation test. Test disposable PG persistence/conflicts/old-row preservation.
- [x] Run focused core/storage tests and independent spec then quality reviews; no commits until controller has frozen integration.

## Chunk 2: Approved resolution and actual execution

- [x] Write failing config/API/Worker/provider tests covering disabled-by-default, bounded strict catalog, digest/scope pin checks, no secret event data, actual bound provider body/instructions, supported Chat/auto/text matrix and unsupported v2 Coverage refusal before dispatch/effects and concurrent isolation.
- [x] Add config/bundle_settings.py optional catalog loader and config field; extract existing ModelSettings to model_settings.py only to respect file limit. API bundle_assembly.py resolves exact approved assets; existing versions endpoint opts into v2 with explicit runtime_bundle request, without widening management credential.
- [x] Add Worker bundle_assembly.py for task-local compatibility/baseline HMAC and model/contexts; wire after existing committed/pending-close healing and before new external effects in execution.py via focused extraction if needed for file limit. Implement integration bundle_model.py with explicit immutable bound parameters while preserving legacy provider_settings.py, preserving legacy default signatures and Coverage proof qualification without widening them (v2 Coverage is refused before dispatch). Add frozen instructions to context adapter without replacing existing governed prompt.
- [x] Reuse baseline_digest/seal_runtime_bundle for operator preparation; no additional CLI needed. Document exact invocation and private-file boundary.
- [x] Run actual Worker/provider integration including restart/recovery/new-release drift, negative compatibility, and legacy Coverage checks; fix all review findings.

## Chunk 3: Gates and delivery

- [x] Update docs/RUNTIME_BUNDLE_ASSEMBLY.md with contract/rollout/limitations, task registry, PROGRESS, WORKLOG and entry links.
- [x] Independent spec/quality review of complete integration, no unresolved findings.
- [x] Stage only owned files before tracked-source size gate. `make test` and `make check` must exit zero after final source changes. Record exact results and skips in docs/evidence/ca-p2-01b/.
- [x] Commit focused changes on codex/ca-p2-01b-bundle-assembly, push normally and compare remote SHA; confirm original dirty checkout preserved. No deployment/migration/integration.

### Exact focused checks

- Core: `uv run pytest -q tests/agent_core/test_bundle_definition.py tests/test_agent_definition_binding_contract_matrix.py tests/agent_core/test_runtime_bundle*.py` — v1 golden stable, v2 dispatch/digests and scope/grants/environment pass.
- Storage: `uv run pytest -q tests/agent_storage/test_bundle_definition_postgres.py tests/agent_storage/test_postgres_agent_registry.py tests/agent_storage/test_branch_migration_catalog.py` — owned disposable PG v109→110, atomic persistence/conflict/rollback and legacy rows preserved, no skip on new tests.
- Resolution/execution: `uv run pytest -q tests/test_bundle_assembly.py tests/worker/test_bundle_execution.py tests/api/test_bundle_materialization.py tests/agent_integrations/test_bundle_model.py` — real Worker task path observes frozen model/instructions, incompatible/unsupported modes refuse before new external effects, pending-close healing preserved, credentials absent from persisted payloads.
- Legacy compatibility: existing Worker recovery/Coverage/model tests in `make test`; final `make check` must include eval30/30 plus tracked source boundary/size/lint/types checks.

## Verification receipt

Final implementation/review and frozen-source r2 gates completed:65focused pass,
11real disposablePG tests,9legacy entry regression pass; make test10685pass/
3007skip, make check exit0/eval30/30. Structured evidence lives in
`docs/evidence/ca-p2-01b/validation.json`; source hashes include the one-line old
test substitute correction. Commit/push uses the authorized focused branch only;
no merge, deployment or production migration. Remote SHA is reported after push.
