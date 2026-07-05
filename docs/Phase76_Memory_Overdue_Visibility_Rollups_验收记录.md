# Phase 76 Memory Overdue Visibility Rollups 验收记录

## Scope

Phase 76 focused on improving overdue triage by summarizing overdue candidate
memory by visibility for currently overdue scopes.

The phase added one additive overdue-visibility read surface on top of the
existing pressure, aging, velocity, governance, overview, summary, queue,
action-hint, escalation, follow-up-window, overdue-flag, overdue-age, and
overdue-type surfaces so operators can see which visibility class dominates an
overdue scope.

## Completed Tasks

### P76-MEM-01 - Memory Overdue Visibility Rollups

Implemented behavior:

- Added one combined memory overdue-visibility read path anchored to a session
  and enriched by optional user and tenant scope ids.
- Reused the existing overdue helper plus current queue inventory instead of
  introducing a new projection, scheduler, or scoring model.
- Exposed additive per-scope fields including
  `overdue_memory_visibility_counts`,
  `highest_overdue_memory_visibility`,
  `highest_overdue_memory_visibility_count`,
  `overdue_target_memory_visibility`, and
  `overdue_visibility_rollup_reasons`.
- Added aggregate `overdue_memory_visibility_counts` plus a cross-scope
  `highest_priority_overdue_*` visibility rollup for fast operator inspection.
- Kept visibility selection deterministic by counting currently overdue
  candidate memory inside each overdue scope and breaking ties
  lexicographically.

Validation:

- `uv run pytest tests/api/test_memory_overdue_visibility_rollups.py tests/cli/test_cli_memory_overdue_visibility_rollups.py tests/test_memory_overdue_visibility_rollups_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_visibility_rollups.py tests/cli/test_cli_memory_overdue_visibility_rollups.py tests/test_memory_overdue_visibility_rollups_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue visibility rollups for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue visibility rollups stay explicitly scoped and local-first.

## Validation Notes

- The rollup only activates for scopes that are already overdue, so the new
  fields do not redefine overdue semantics.
- Highest-priority overdue visibility is derived from the existing overdue
  target and current candidate queue rather than from a new weighting
  algorithm.

## Known Deferrals

- Overdue visibility rollups do not yet expose historical trend analysis across
  repeated overdue windows.
- The phase does not yet rank overdue pressure shifts over time.

## Next Phase

Phase 77 should focus on deterministic overdue trend signals:

- add one additive trend layer on top of current overdue scope evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
