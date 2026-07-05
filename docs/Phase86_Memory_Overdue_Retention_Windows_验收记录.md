# Phase 86 Memory Overdue Retention Windows 验收记录

## Scope

Phase 86 focused on improving overdue aftercare timing by mapping current
overdue retention guidance to deterministic retention windows.

The phase added one additive overdue-retention-window read surface on top of
the existing overdue retention-guidance evidence so operators can see when an
overdue scope should be revisited while it remains active.

## Completed Tasks

### P86-MEM-01 - Memory Overdue Retention Windows

Implemented behavior:

- Added one combined memory overdue-retention-window read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-retention-guidance helper instead of adding a
  new scheduler, queue, or projection family.
- Exposed additive per-scope fields including
  `overdue_retention_window`, `overdue_retention_window_priority`,
  `overdue_retention_window_due_at`,
  `overdue_retention_window_target_memory_id`, and
  `overdue_retention_window_reasons`.
- Added aggregate `overdue_retention_window_counts` plus a cross-scope
  `highest_priority_overdue_retention_window_*` rollup for fast operator
  inspection.
- Kept window selection deterministic by mapping current overdue retention
  guidance to stable windows such as `review_within_12h`,
  `review_within_1d`, `review_within_3d`, and `review_within_7d`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_windows.py tests/cli/test_cli_memory_overdue_retention_windows.py tests/test_memory_overdue_retention_windows_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_windows.py tests/cli/test_cli_memory_overdue_retention_windows.py tests/test_memory_overdue_retention_windows_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention windows for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention windows stay explicitly scoped and local-first.

## Validation Notes

- The retention windows are intentionally derived from current overdue
  retention-guidance evidence, not from external schedulers or clock-driven
  background jobs.
- The additive `overdue_retention_window_due_at` field gives a concrete next
  review timestamp without claiming a storage TTL or auto-close behavior.

## Known Deferrals

- Overdue retention windows still do not emit archival TTL promises.
- The phase does not yet model window breach classifications after the next
  retention review is missed.

## Next Phase

Phase 87 should focus on deterministic overdue retention breaches:

- add one additive breach-classification layer on top of current overdue retention windows
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
