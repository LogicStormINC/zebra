# Phase 73 Memory Follow-Up Overdue Flags 验收记录

## Scope

Phase 73 focused on turning existing follow-up windows into one deterministic
overdue-status layer.

The phase added one additive overdue read surface on top of the existing
pressure, aging, velocity, governance, overview, summary, queue, action-hint,
escalation, and follow-up-window surfaces so operators can quickly see which
scopes have already missed their current follow-up deadline.

## Completed Tasks

### P73-MEM-01 - Memory Follow-Up Overdue Flags

Implemented behavior:

- Added one combined memory overdue read path anchored to a session and
  enriched by optional user and tenant scope ids.
- Reused the existing follow-up-window helper instead of introducing another
  durable projection or scheduler.
- Exposed additive per-scope fields including `follow_up_overdue`,
  `follow_up_overdue_priority`, `follow_up_overdue_since`,
  `follow_up_overdue_target_memory_id`, and `follow_up_overdue_reasons`.
- Added aggregate `overdue_scope_count` plus a cross-scope
  `highest_priority_overdue_*` rollup for fast operator inspection.
- Kept overdue detection deterministic with one local rule based on whether the
  derived `follow_up_due_at` has already lapsed at read time.

Validation:

- `uv run pytest tests/api/test_memory_overdue_flags.py tests/cli/test_cli_memory_overdue_flags.py tests/test_memory_overdue_flags_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_overdue_flags.py tests/cli/test_cli_memory_overdue_flags.py tests/test_memory_overdue_flags_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue follow-up flags for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue flags stay explicitly scoped and local-first.

## Validation Notes

- Overdue flags stayed as a pure read-time derivation over the current
  follow-up-window helper, which kept the implementation local-first and
  deterministic.
- The highest-priority rollup reuses the same `none/low/medium/high` ordering
  already used by action hints, escalations, and follow-up windows.

## Known Deferrals

- Overdue detection is intentionally binary and local; there is no configurable
  grace period, business-calendar adjustment, or repeated-breach escalation yet.
- The phase identifies overdue scopes, but it does not yet summarize how far
  overdue a scope is in a normalized age bucket.

## Next Phase

Phase 74 should focus on deterministic overdue age buckets:

- add one additive overdue-age layer on top of current overdue evidence
- keep the logic local-first and derived from current overdue timestamps
- preserve explicit scope boundaries without adding background services
