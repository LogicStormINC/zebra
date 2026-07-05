# Phase 90 Memory Overdue Retention Breach Lanes 验收记录

## Scope

Phase 90 focused on improving overdue aftercare routing by mapping current
overdue retention breach actions into deterministic breach lanes.

The phase added one additive overdue-retention-breach-lane read surface on top
of the existing overdue retention-breach-action evidence so operators can see
which handling lane each affected scope should follow.

## Completed Tasks

### P90-MEM-01 - Memory Overdue Retention Breach Lanes

Implemented behavior:

- Added one combined memory overdue-retention-breach-lane read path anchored
  to a session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-retention-breach-action helper instead of adding
  new workflow state, queues, or background services.
- Exposed additive per-scope fields including
  `overdue_retention_breach_lane`,
  `overdue_retention_breach_lane_priority`,
  `overdue_retention_breach_lane_target_memory_id`, and
  `overdue_retention_breach_lane_reasons`.
- Added aggregate `overdue_retention_breach_lane_counts` plus a cross-scope
  `highest_priority_overdue_retention_breach_lane_*` rollup for fast operator
  inspection.
- Kept breach lanes deterministic by mapping breach actions to stable routing
  outcomes such as `operator_retention_review_lane`,
  `owner_assignment_lane`,
  `manager_retention_escalation_lane`, and
  `emergency_retention_override_lane`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_breach_lanes.py tests/cli/test_cli_memory_overdue_retention_breach_lanes.py tests/test_memory_overdue_retention_breach_lanes_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_lanes.py tests/cli/test_cli_memory_overdue_retention_breach_lanes.py tests/test_memory_overdue_retention_breach_lanes_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention breach lanes for
  repo, user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention breach lanes stay explicitly scoped and local-first.

## Validation Notes

- Breach lanes are intentionally derived from current overdue
  retention-breach-action evidence, not from external schedulers or automated
  ownership systems.
- The additive lane and lane-priority fields make breach routing sortable
  without introducing automated reassignment behavior.

## Known Deferrals

- Overdue retention breach lanes still do not expose final operator ownership.
- The phase does not yet model breach-lane outcomes beyond the current
  deterministic routing recommendation.

## Next Phase

Phase 91 should focus on deterministic overdue retention breach owner targets:

- add one additive breach-owner-target layer on top of current overdue retention breach lanes
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
