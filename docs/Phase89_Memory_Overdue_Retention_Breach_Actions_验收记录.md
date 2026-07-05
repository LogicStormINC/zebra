# Phase 89 Memory Overdue Retention Breach Actions 验收记录

## Scope

Phase 89 focused on improving overdue aftercare actionability by mapping
current overdue retention breach aging into deterministic breach actions.

The phase added one additive overdue-retention-breach-action read surface on
top of the existing overdue retention-breach-aging evidence so operators can
see the current recommended handling step for each affected scope.

## Completed Tasks

### P89-MEM-01 - Memory Overdue Retention Breach Actions

Implemented behavior:

- Added one combined memory overdue-retention-breach-action read path anchored
  to a session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-retention-breach-aging helper instead of adding
  new workflow state, queues, or background services.
- Exposed additive per-scope fields including
  `overdue_retention_breach_action`,
  `overdue_retention_breach_action_priority`,
  `overdue_retention_breach_action_target_memory_id`, and
  `overdue_retention_breach_action_reasons`.
- Added aggregate `overdue_retention_breach_action_counts` plus a cross-scope
  `highest_priority_overdue_retention_breach_action_*` rollup for fast
  operator inspection.
- Kept breach actions deterministic by mapping breach aging buckets to stable
  action outcomes such as `queue_immediate_retention_review`,
  `assign_retention_owner`,
  `escalate_retention_decision`, and
  `force_archive_or_override`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_breach_actions.py tests/cli/test_cli_memory_overdue_retention_breach_actions.py tests/test_memory_overdue_retention_breach_actions_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_actions.py tests/cli/test_cli_memory_overdue_retention_breach_actions.py tests/test_memory_overdue_retention_breach_actions_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention breach actions for
  repo, user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention breach actions stay explicitly scoped and local-first.

## Validation Notes

- Breach actions are intentionally derived from current overdue
  retention-breach-aging evidence, not from external schedulers or automatic
  remediation workflows.
- The additive action and action-priority fields make breach handling sortable
  without introducing automated write-side behavior.

## Known Deferrals

- Overdue retention breach actions still do not expose lane ownership.
- The phase does not yet model breach-action routing beyond the current
  deterministic action recommendation.

## Next Phase

Phase 90 should focus on deterministic overdue retention breach lanes:

- add one additive breach-lane layer on top of current overdue retention breach actions
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
