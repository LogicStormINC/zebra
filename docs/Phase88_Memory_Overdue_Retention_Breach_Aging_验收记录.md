# Phase 88 Memory Overdue Retention Breach Aging 验收记录

## Scope

Phase 88 focused on improving overdue aftercare escalation depth by mapping
current overdue retention breaches to deterministic breach aging buckets.

The phase added one additive overdue-retention-breach-aging read surface on
top of the existing overdue retention-breach evidence so operators can see how
long an active breach has remained unresolved.

## Completed Tasks

### P88-MEM-01 - Memory Overdue Retention Breach Aging

Implemented behavior:

- Added one combined memory overdue-retention-breach-aging read path anchored
  to a session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-retention-breach helper instead of adding a new
  scheduler, queue, or projection family.
- Exposed additive per-scope fields including
  `overdue_retention_breach_age_bucket`,
  `overdue_retention_breach_age_seconds`,
  `overdue_retention_breach_age_days`, and
  `overdue_retention_breach_age_reasons`.
- Added aggregate `overdue_retention_breach_age_bucket_counts` plus a
  cross-scope `highest_priority_overdue_retention_breach_age_*` rollup for
  fast operator inspection.
- Kept breach aging selection deterministic by mapping current breach due
  timestamps to stable aging buckets such as `lt_1d_breached`,
  `gte_1d_lt_3d_breached`, `gte_3d_lt_7d_breached`, and `gte_7d_breached`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_breach_aging.py tests/cli/test_cli_memory_overdue_retention_breach_aging.py tests/test_memory_overdue_retention_breach_aging_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_aging.py tests/cli/test_cli_memory_overdue_retention_breach_aging.py tests/test_memory_overdue_retention_breach_aging_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention breach aging for
  repo, user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention breach aging stays explicitly scoped and local-first.

## Validation Notes

- The breach aging buckets are intentionally derived from current overdue
  retention-breach evidence, not from external schedulers or background jobs.
- The additive age bucket and age day fields make breach severity sortable
  without introducing automatic remediation semantics.

## Known Deferrals

- Overdue retention breach aging still does not emit escalation actions.
- The phase does not yet model aging-based owner or lane recommendations.

## Next Phase

Phase 89 should focus on deterministic overdue retention breach actions:

- add one additive breach-action layer on top of current overdue retention breach aging
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
