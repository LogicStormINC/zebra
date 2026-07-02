# Phase 45 CLI Delivery Audit Read Parity 验收记录

## Scope

Phase 45 added a local CLI surface for reading durable session delivery-audit
records and then locked API and CLI operator payload parity behind an explicit
contract matrix.

The phase stayed deliberately narrow. It reused the existing SQLite-backed
delivery-audit store and preserved the current read vocabulary instead of
expanding the audit payload shape.

## Completed Tasks

### P45-CLI-01 - CLI Delivery Audit Read Surface

Implemented behavior:

- Added `apps/cli/src/zebra_agent_cli/delivery_audit.py`.
- Added a new `delivery-audit` CLI command in
  `apps/cli/src/zebra_agent_cli/cli.py`.
- Reused the existing SQLite projection and delivery-audit stores for local
  operator reads.
- Added focused CLI regression coverage for not found, empty, and recorded
  delivery-audit output in `tests/cli/test_cli_delivery_audit.py`.

Validation:

- `uv run pytest tests/cli/test_cli_delivery_audit.py tests/api/test_session_delivery_audit.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/delivery_audit.py tests/cli/test_cli_delivery_audit.py tests/api/test_session_delivery_audit.py`
- `uv run mypy packages apps tests/cli/test_cli_delivery_audit.py tests/api/test_session_delivery_audit.py`

### P45-TEST-01 - Delivery Audit API And CLI Contract Matrix

Implemented behavior:

- Added `tests/test_delivery_audit_contract_matrix.py`.
- Locked API and CLI parity for delivery-audit `not_found`, empty, and
  recorded-record scenarios.
- Preserved narrow normalization by comparing the shared operator payload and
  excluding only the CLI-local `database` field from parity projection.

Validation:

- `uv run pytest tests/cli/test_cli_delivery_audit.py tests/api/test_session_delivery_audit.py tests/test_delivery_audit_contract_matrix.py`
- `uv run ruff check apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/delivery_audit.py tests/cli/test_cli_delivery_audit.py tests/api/test_session_delivery_audit.py tests/test_delivery_audit_contract_matrix.py`
- `uv run mypy packages apps tests/cli/test_cli_delivery_audit.py tests/api/test_session_delivery_audit.py tests/test_delivery_audit_contract_matrix.py`
- `make check`

## Acceptance Summary

- CLI can now read session delivery-audit records from the local database.
- Empty audit state and not-found behavior are explicit and deterministic.
- API and CLI delivery-audit payload parity is now covered by a dedicated
  contract matrix.

## Validation Notes

- Focused CLI, API, and parity regression suites passed.
- `make check` passed after the CLI read surface and contract matrix landed.
- The phase did not change the delivery-audit payload vocabulary.

## Known Deferrals

- API and CLI still each serialize delivery-audit records independently.
- The shared vocabulary is now contract-locked, but the projection code path is
  still duplicated across operator surfaces.

## Next Phase

Phase 46 should focus on shared delivery-audit projection reuse:

- extract one shared delivery-audit projection serializer
- adopt the shared serializer in the API read surface
- adopt the shared serializer in the CLI read surface
