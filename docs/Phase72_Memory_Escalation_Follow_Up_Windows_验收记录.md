# Phase 72 Memory Escalation Follow-Up Windows 验收记录

## Scope

Phase 72 focused on turning existing escalation recommendations into one
deterministic follow-up timing layer.

The phase added one additive follow-up-window read surface on top of the
existing pressure, aging, velocity, governance, overview, summary, queue,
action-hint, and escalation surfaces so operators can quickly see when each
scope must be checked again.

## Completed Tasks

### P72-MEM-01 - Memory Escalation Follow-Up Windows

Implemented behavior:

- Added one combined memory follow-up-window read path anchored to a session
  and enriched by optional user and tenant scope ids.
- Reused the existing escalation helper instead of introducing another durable
  projection or background scheduler.
- Exposed additive per-scope fields including `follow_up_window`,
  `follow_up_priority`, `follow_up_due_at`, `follow_up_target_memory_id`, and
  `follow_up_reasons`.
- Added aggregate `follow_up_window_counts` plus a cross-scope
  `highest_priority_follow_up_*` rollup for fast operator inspection.
- Kept follow-up timing deterministic with simple local rules for immediate,
  same-day, next-24h, and next-7d windows.

Validation:

- `uv run pytest tests/api/test_memory_follow_up_windows.py tests/cli/test_cli_memory_follow_up_windows.py tests/test_memory_follow_up_windows_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_follow_up_windows.py tests/cli/test_cli_memory_follow_up_windows.py tests/test_memory_follow_up_windows_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic follow-up windows for repo, user,
  and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Follow-up windows stay explicitly scoped and local-first.

## Validation Notes

- Follow-up windows stayed as a pure read-time derivation over the current
  escalation helper, which kept the implementation local-first and
  deterministic.
- The highest-priority rollup reuses the same `none/low/medium/high` ordering
  already used by action hints and escalations.

## Known Deferrals

- Follow-up timing is coarse and deterministic; there is no configurable SLA
  engine, business-calendar logic, or tenant-specific timing policy yet.
- The phase recommends when to re-check a scope, but it does not yet expose
  whether a follow-up is already overdue at read time.

## Next Phase

Phase 73 should focus on deterministic overdue follow-up flags:

- add one additive overdue layer on top of current follow-up-window evidence
- keep the logic local-first and derived from current follow-up timing
- preserve explicit scope boundaries without adding background services
