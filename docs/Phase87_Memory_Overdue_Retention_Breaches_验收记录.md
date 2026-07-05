# Phase 87 Memory Overdue Retention Breaches 验收记录

## Scope

Phase 87 focused on improving overdue aftercare escalation by mapping current
overdue retention windows to deterministic retention breach classifications.

The phase added one additive overdue-retention-breach read surface on top of
the existing overdue retention-window evidence so operators can see whether a
revisit window has been missed and how severe the breach is.

## Completed Tasks

### P87-MEM-01 - Memory Overdue Retention Breaches

Implemented behavior:

- Added one combined memory overdue-retention-breach read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-retention-window helper instead of adding a new
  scheduler, queue, or projection family.
- Exposed additive per-scope fields including
  `overdue_retention_breach`, `overdue_retention_breach_priority`,
  `overdue_retention_breach_due_at`,
  `overdue_retention_breach_target_memory_id`, and
  `overdue_retention_breach_reasons`.
- Added aggregate `overdue_retention_breach_counts` plus a cross-scope
  `highest_priority_overdue_retention_breach_*` rollup for fast operator
  inspection.
- Kept breach selection deterministic by mapping current overdue retention
  windows to stable breach states such as `within_retention_window`,
  `same_day_window_breached`, `next_day_window_breached`,
  `short_window_breached`, `weekly_window_breached`, and
  `extended_window_breached`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_breaches.py tests/cli/test_cli_memory_overdue_retention_breaches.py tests/test_memory_overdue_retention_breaches_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breaches.py tests/cli/test_cli_memory_overdue_retention_breaches.py tests/test_memory_overdue_retention_breaches_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention breaches for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention breaches stay explicitly scoped and local-first.

## Validation Notes

- The breach classifications are intentionally derived from current overdue
  retention-window evidence, not from external schedulers or background jobs.
- The additive `overdue_retention_breach_due_at` field preserves the breached
  review timestamp so operators can judge lateness without introducing
  auto-remediation behavior.

## Known Deferrals

- Overdue retention breaches still do not emit auto-escalation actions.
- The phase does not yet model breach aging tiers after the first missed window.

## Next Phase

Phase 88 should focus on deterministic overdue retention breach aging:

- add one additive breach-aging layer on top of current overdue retention breaches
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
