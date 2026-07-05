# Phase 81 Memory Overdue Resolution Checkpoints 验收记录

## Scope

Phase 81 focused on improving overdue closure tracking by mapping current
overdue scopes to deterministic resolution checkpoints.

The phase added one additive overdue-resolution-checkpoint read surface on top
of the existing pressure, aging, velocity, governance, overview, summary,
queue, action-hint, escalation, follow-up-window, overdue-flag, overdue-age,
overdue-type, overdue-visibility, overdue-trend, overdue-intervention,
overdue-escalation-lane, and overdue-recovery-path surfaces so operators can
see the next closure checkpoint for each overdue scope.

## Completed Tasks

### P81-MEM-01 - Memory Overdue Resolution Checkpoints

Implemented behavior:

- Added one combined memory overdue-resolution-checkpoint read path anchored to
  a session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-recovery-path helper instead of introducing a new
  projection, scheduler, or workflow engine.
- Exposed additive per-scope fields including `overdue_resolution_checkpoint`,
  `overdue_resolution_priority`, `overdue_resolution_target_memory_id`, and
  `overdue_resolution_reasons`.
- Added aggregate `overdue_resolution_checkpoint_counts` plus a cross-scope
  `highest_priority_overdue_resolution_*` rollup for fast operator inspection.
- Kept checkpoint selection deterministic by mapping current overdue recovery
  paths to stable closure checkpoints such as
  `next_review_confirmation_checkpoint`, `same_day_resolution_checkpoint`,
  `operator_completion_checkpoint`, and `owner_confirmation_checkpoint`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_resolution_checkpoints.py tests/cli/test_cli_memory_overdue_resolution_checkpoints.py tests/test_memory_overdue_resolution_checkpoints_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_resolution_checkpoints.py tests/cli/test_cli_memory_overdue_resolution_checkpoints.py tests/test_memory_overdue_resolution_checkpoints_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue resolution checkpoints for
  repo, user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue resolution checkpoints stay explicitly scoped and local-first.

## Validation Notes

- The resolution checkpoint is intentionally derived from current overdue
  recovery evidence, not from external workflow state, so the feature stays
  local-first and deterministic.
- A scope can still remain on `next_review_confirmation_checkpoint` when the
  overdue breach is new; the phase recommends the smallest coherent closeout
  checkpoint from present overdue state rather than claiming completion early.

## Known Deferrals

- Overdue resolution checkpoints do not yet persist explicit resolved or
  unresolved outcomes.
- The phase does not yet model whether a checkpoint has been passed
  successfully.

## Next Phase

Phase 82 should focus on deterministic overdue resolution outcomes:

- add one additive resolution-outcome layer on top of current overdue resolution-checkpoint evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
