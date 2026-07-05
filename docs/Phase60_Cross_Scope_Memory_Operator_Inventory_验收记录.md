# Phase 60 Cross-Scope Memory Operator Inventory 验收记录

## Scope

Phase 60 expanded local operator memory readback beyond repo scope.

The phase introduced user-scoped and tenant-scoped memory inventory surfaces
over the local API and CLI while preserving the existing repo-memory lifecycle
and provenance fields.

## Completed Tasks

### P60-MEM-01 - User And Tenant Memory Operator Inventory

Implemented behavior:

- Added shared scoped memory inventory reads for repo, user, and tenant scopes.
- Reused the existing lifecycle and provenance serialization path so
  `last_review` and `source` remain consistent across all memory scopes.
- Added local API routes for `/users/{id}/memory` and `/tenants/{id}/memory`.
- Added local CLI reads through `zebra-agent memory-user <user_id>` and
  `zebra-agent memory-tenant <tenant_id>`.

Validation:

- `uv run pytest tests/api/test_memory_scope_inventory.py tests/cli/test_cli_memory_scope_inventory.py tests/test_memory_scope_inventory_contract_matrix.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli packages/agent-core/src/agent_core/application tests/api/test_memory_scope_inventory.py tests/cli/test_cli_memory_scope_inventory.py tests/test_memory_scope_inventory_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect repo-scoped, user-scoped, and tenant-scoped memory
  inventories locally.
- Shared lifecycle and provenance fields stay aligned across all supported
  memory scopes.
- Existing repo-memory inventory contracts remain backward compatible.

## Validation Notes

- Cross-scope inventory coverage passed for API, CLI, and the shared contract
  matrix.
- `make check` passed after the phase closeout and next-phase planning updates
  landed.

## Known Deferrals

- Cross-scope inventory now exists, but review controls are still session-bound
  and repo-memory-centric.
- There is still no bulk triage or scope-filtered review workflow for operators.

## Next Phase

Phase 61 should extend operator control over cross-scope memory:

- add user-scoped and tenant-scoped memory review surfaces
- keep review lifecycle and provenance outputs aligned with current repo-memory
  contracts
- decide whether bulk triage belongs before or after cross-scope review parity
