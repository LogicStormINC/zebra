# Phase 75 Memory Overdue Type Rollups 验收记录

## Scope

Phase 75 focused on improving overdue triage by summarizing overdue candidate
memory by type for currently overdue scopes.

The phase added one additive overdue-type read surface on top of the existing
pressure, aging, velocity, governance, overview, summary, queue, action-hint,
escalation, follow-up-window, overdue-flag, and overdue-age surfaces so
operators can see which memory type dominates an overdue scope.

## Completed Tasks

### P75-MEM-01 - Memory Overdue Type Rollups

Implemented behavior:

- Added one combined memory overdue-type read path anchored to a session and
  enriched by optional user and tenant scope ids.
- Reused the existing overdue helper plus current queue inventory instead of
  introducing a new projection, scheduler, or scoring model.
- Exposed additive per-scope fields including `overdue_memory_count`,
  `overdue_memory_type_counts`, `highest_overdue_memory_type`,
  `highest_overdue_memory_type_count`, `overdue_target_memory_type`, and
  `overdue_type_rollup_reasons`.
- Added aggregate `overdue_memory_type_counts` plus a cross-scope
  `highest_priority_overdue_*` type rollup for fast operator inspection.
- Kept type selection deterministic by counting currently overdue candidate
  memory inside each overdue scope and breaking ties lexicographically.

Validation:

- `uv run pytest tests/api/test_memory_overdue_type_rollups.py tests/cli/test_cli_memory_overdue_type_rollups.py tests/test_memory_overdue_type_rollups_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_type_rollups.py tests/cli/test_cli_memory_overdue_type_rollups.py tests/test_memory_overdue_type_rollups_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue memory-type rollups for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue memory-type rollups stay explicitly scoped and local-first.

## Validation Notes

- The rollup only activates for scopes that are already overdue, so the new
  fields do not redefine overdue semantics.
- Highest-priority overdue type is derived from the existing overdue target and
  current candidate queue rather than from a new weighting algorithm.

## Known Deferrals

- Overdue-type rollups do not yet summarize by visibility class.
- The phase does not yet add historical trend analysis across repeated overdue
  windows.

## Next Phase

Phase 76 should focus on deterministic overdue visibility rollups:

- add one additive visibility summary layer on top of current overdue scope
  evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
