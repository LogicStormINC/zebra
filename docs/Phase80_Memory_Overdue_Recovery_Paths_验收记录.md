# Phase 80 Memory Overdue Recovery Paths 验收记录

## Scope

Phase 80 focused on improving overdue recovery planning by mapping current
overdue scopes to deterministic recovery paths.

The phase added one additive overdue-recovery-path read surface on top of the
existing pressure, aging, velocity, governance, overview, summary, queue,
action-hint, escalation, follow-up-window, overdue-flag, overdue-age,
overdue-type, overdue-visibility, overdue-trend, overdue-intervention, and
overdue-escalation-lane surfaces so operators can see the next recovery plan
for each overdue scope.

## Completed Tasks

### P80-MEM-01 - Memory Overdue Recovery Paths

Implemented behavior:

- Added one combined memory overdue-recovery-path read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-escalation-lane helper instead of introducing a
  new projection, scheduler, or workflow engine.
- Exposed additive per-scope fields including `overdue_recovery_path`,
  `overdue_recovery_priority`, `overdue_recovery_target_memory_id`, and
  `overdue_recovery_reasons`.
- Added aggregate `overdue_recovery_path_counts` plus a cross-scope
  `highest_priority_overdue_recovery_*` rollup for fast operator inspection.
- Kept recovery-path selection deterministic by mapping current overdue
  escalation lanes to stable recovery paths such as
  `next_local_review_recovery`, `same_day_recovery_burst`,
  `immediate_operator_recovery`, and `owner_assignment_recovery_plan`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_recovery_paths.py tests/cli/test_cli_memory_overdue_recovery_paths.py tests/test_memory_overdue_recovery_paths_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_recovery_paths.py tests/cli/test_cli_memory_overdue_recovery_paths.py tests/test_memory_overdue_recovery_paths_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue recovery paths for repo, user,
  and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue recovery paths stay explicitly scoped and local-first.

## Validation Notes

- The recovery path is intentionally derived from current overdue-escalation
  evidence, not from external workflow state, so the feature stays local-first
  and deterministic.
- A scope can still remain on `next_local_review_recovery` when the overdue
  breach is new; the phase recommends the smallest coherent recovery action from
  present overdue state rather than forcing premature closure semantics.

## Known Deferrals

- Overdue recovery paths do not yet persist explicit completion checkpoints or
  operator acknowledgements.
- The phase does not yet model whether a chosen recovery path has actually been
  completed.

## Next Phase

Phase 81 should focus on deterministic overdue resolution checkpoints:

- add one additive resolution-checkpoint layer on top of current overdue recovery-path evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
