# Phase 67 Memory Backlog Aging Signals 验收记录

## Scope

Phase 67 focused on deterministic backlog aging signals for pending memory.

The phase added one additive aging read surface on top of the existing queue
summary, operations overview, and governance surfaces so operators can see
which pending memories are oldest and how backlog is distributed across simple
age buckets without opening full queue detail.

## Completed Tasks

### P67-MEM-01 - Memory Backlog Aging Signals

Implemented behavior:

- Added one combined backlog-aging read path anchored to a session and enriched
  by optional user and tenant scope ids.
- Reused the existing scoped memory read helpers instead of introducing a
  second durable backlog model.
- Exposed additive signals including `reference_at`, `pending_age_buckets`,
  `oldest_pending_memory_id`, `oldest_pending_captured_at`,
  `oldest_pending_age_seconds`, and `oldest_pending_age_days` per scope.
- Added aggregate age-bucket totals and oldest-pending rollup across all
  requested scopes.
- Added optional `as_of` request input so operators and tests can pin backlog
  aging to one explicit reference time.

Validation:

- `uv run pytest tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect backlog aging signals for repo, user, and tenant
  scopes without opening full queue detail.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Existing scope boundaries remain explicit in the exposed aging signals.

## Validation Notes

- Aging reads stayed additive beside the current governance and overview
  surfaces, so those earlier regression suites remained in the phase
  validation set.
- The default `reference_at` falls back to the latest session event timestamp
  when `as_of` is not provided, while callers can still pin one explicit
  reference time for stable operator inspection or tests.

## Known Deferrals

- Current age buckets are coarse and deterministic; there is no SLA-specific
  configuration or per-memory priority scoring yet.
- Aging signals do not yet surface review throughput, ownership assignment, or
  recommendation hints for which backlog item to process next.

## Next Phase

Phase 68 should focus on review velocity and recent throughput signals:

- add deterministic review-activity window summaries on top of the current
  overview, governance, and aging surfaces
- keep current contracts additive and local-first
- preserve explicit scope boundaries without introducing background jobs
