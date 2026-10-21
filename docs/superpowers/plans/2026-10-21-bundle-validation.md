# CA-P2-01C Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Track steps with checkboxes.

**Goal:** publish a scoped native contract/query/validation prerequisite for Go P2 orchestration.

**Architecture:** existing native Bundle parser and approved resolver remain authority. A separate private scoped credential enables pure bounded HTTP operations without mutating native state. Old Bundle/Definition/Snapshot bytes and B baseline digests remain stable.

**Tech Stack:** current Python/Pydantic/FastAPI/httpx/stdlib only; no new dependency.

## Chunk1: Protocol, configuration and HTTP

- [x] Run `make sync`; baseline `uv run pytest -q tests/api/test_runtime_management.py tests/test_bundle_assembly.py tests/api/test_bundle_materialization.py`.
- [x] Write failing tests in tests/api/test_bundle_management.py and tests/config/test_bundle_management_config.py: unknown new route/setting; exact private approval fields/scope/actions; old B baseline digest expected c7748ed8...900fdc; malformed/rotated credentials, scope and contract mismatches, hostile JSON and asset rejection, disabled behavior.
- [x] Add config/private_configuration.py focused bounded private regular file reader; reuse from config/bundle_settings.py and new API approval loader. Add optional setting and exclude only this new API-only field from old HMAC bytes. Tests must preserve old fingerprint with None/configured path.
- [x] Add API bundle_management_contract.py static producer payload/digest; bundle_management_config.py strict scoped credential/current file parsing; bundle_management.py GET/POST auth/read/validate/re-authorize. Reuse _HEADERS/_error, native parser and RuntimeExecutionCatalog; no public request path/remote resolution. Compose lazily in host_registry_management.py without changing target/Host credential semantics.
- [x] Verify body/deadline/semaphore behavior with runnable async tests: timeout/cancel retains actual background slots; max8threads; late exceptions consumed; config rotation before response denies old credential; validation produces no mutations or model/Worker/tool calls. `uv run pytest -q tests/api/test_bundle_management.py tests/config/test_bundle_management_config.py` green, existing B regressions green.
- [x] Independent implementation spec then quality review, all concrete findings fixed before gates.

## Chunk2: Producer artifacts and independent consumer acceptance

- [x] Create docs/contracts/bundle-validation-v1/openapi.json and contract.json plus deterministic positive/negative vectors. Existing runtime-bundle-v1/ stays byte unchanged. Pin hashes in evidence.
- [x] Add tests/test_bundle_management_contract.py verifying exact producer artifact equality, OpenAPI paths/security/status/body/digest and portable vectors. Add tests/api/test_bundle_management_process.py actual loopback subprocess create_http_app with private approvals/catalog and raw HTTP; positive and wrong-scope/action/rotation/negative paths, no database or execution side effects.
- [x] Run `uv run pytest -q tests/test_bundle_management_contract.py tests/api/test_bundle_management_process.py tests/api/test_bundle_management.py tests/config/test_bundle_management_config.py tests/worker/test_bundle_execution.py tests/worker/test_bundle_title_recovery.py tests/test_bundle_assembly.py` — all pass with no skipped new acceptance. Document independent producer ownership and next Go OD-P2-01A remains separate.

## Chunk3: Documentation and delivery

- [x] Update docs/BUNDLE_MANAGEMENT.md, existing status links/README, PROGRESS/WORKLOG/task card and current task_plan. Explain receipt correlation, supported/unsupported scope, legacy baseline compatibility and file-backed HA limits.
- [x] Final independent spec/quality review, then freeze staged source. `make test` and `make check` must exit0; record counts/skips/commands/fingerprints in docs/evidence/ca-p2-01c/. Preserve old worktrees and dirty source checkout.
- [x] Prepare verified scoped commit/push codex/ca-p2-01c-bundle-validation; compare remote SHA as the final delivery action. No merge, deployment or production migration.
