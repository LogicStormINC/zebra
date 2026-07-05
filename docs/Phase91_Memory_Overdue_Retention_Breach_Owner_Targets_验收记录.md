# Phase 91 Memory Overdue Retention Breach Owner Targets 验收记录

## Scope

Phase 91 focused on improving overdue aftercare ownership clarity by mapping
current overdue retention breach lanes into deterministic owner targets.

The phase added one additive overdue-retention-breach-owner-target read surface
on top of the existing overdue retention-breach-lane evidence so operators can
see which responsible party should take the next step for each affected scope.

## Completed Tasks

### P91-MEM-01 - Memory Overdue Retention Breach Owner Targets

Implemented behavior:

- Added one combined memory overdue-retention-breach-owner-target read path
  anchored to a session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-retention-breach-lane helper instead of adding
  new ownership state, queues, or background services.
- Exposed additive per-scope fields including
  `overdue_retention_breach_owner_target`,
  `overdue_retention_breach_owner_target_priority`,
  `overdue_retention_breach_owner_target_memory_id`, and
  `overdue_retention_breach_owner_target_reasons`.
- Added aggregate `overdue_retention_breach_owner_target_counts` plus a
  cross-scope `highest_priority_overdue_retention_breach_owner_target_*`
  rollup for fast operator inspection.
- Kept owner targets deterministic by mapping breach lanes to stable ownership
  outcomes such as `memory_operator`, `scope_owner`,
  `retention_manager`, and `retention_admin`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_retention_breach_owner_targets.py tests/cli/test_cli_memory_overdue_retention_breach_owner_targets.py tests/test_memory_overdue_retention_breach_owner_targets_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_retention_breach_owner_targets.py tests/cli/test_cli_memory_overdue_retention_breach_owner_targets.py tests/test_memory_overdue_retention_breach_owner_targets_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue retention breach owner targets
  for repo, user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue retention breach owner targets stay explicitly scoped and local-first.

## Validation Notes

- Owner targets are intentionally derived from current overdue
  retention-breach-lane evidence, not from external identity systems or
  automatic assignment workflows.
- The additive owner-target and owner-target-priority fields make ownership
  routing sortable without introducing automated reassignment behavior.

## Known Deferrals

- Overdue retention breach owner targets still do not expose concrete operator
  identities.
- The phase does not yet model owner-target confirmation or reassignment
  outcomes beyond the current deterministic ownership recommendation.

## Next Phase

Phase 92 should focus on deterministic overdue retention breach follow-through
modes:

- add one additive breach-follow-through-mode layer on top of current overdue retention breach owner targets
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
