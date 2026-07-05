# Phase 83 Memory Overdue Closure Decisions 验收记录

## Scope

Phase 83 focused on improving overdue final decision handling by mapping current
overdue scopes to deterministic closure decisions.

The phase added one additive overdue-closure-decision read surface on top of
the existing pressure, aging, velocity, governance, overview, summary, queue,
action-hint, escalation, follow-up-window, overdue-flag, overdue-age,
overdue-type, overdue-visibility, overdue-trend, overdue-intervention,
overdue-escalation-lane, overdue-recovery-path, overdue-resolution-checkpoint,
and overdue-resolution-outcome surfaces so operators can see the current close
versus continue decision for each overdue scope.

## Completed Tasks

### P83-MEM-01 - Memory Overdue Closure Decisions

Implemented behavior:

- Added one combined memory overdue-closure-decision read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-resolution-outcome helper instead of introducing
  a new projection, scheduler, or workflow engine.
- Exposed additive per-scope fields including `overdue_closure_decision`,
  `overdue_closure_priority`, `overdue_closure_target_memory_id`, and
  `overdue_closure_reasons`.
- Added aggregate `overdue_closure_decision_counts` plus a cross-scope
  `highest_priority_overdue_closure_*` rollup for fast operator inspection.
- Kept decision selection deterministic by mapping current overdue resolution
  outcomes to stable closure decisions such as
  `hold_for_next_review_confirmation`,
  `defer_closure_until_same_day_follow_through`,
  `keep_open_for_operator_completion`, and
  `keep_open_for_owner_confirmation`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_closure_decisions.py tests/cli/test_cli_memory_overdue_closure_decisions.py tests/test_memory_overdue_closure_decisions_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_closure_decisions.py tests/cli/test_cli_memory_overdue_closure_decisions.py tests/test_memory_overdue_closure_decisions_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue closure decisions for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue closure decisions stay explicitly scoped and local-first.

## Validation Notes

- The closure decision is intentionally derived from current overdue
  resolution-outcome evidence, not from external workflow state, so the feature
  stays local-first and deterministic.
- A scope can still remain on `hold_for_next_review_confirmation` when the
  overdue breach is new; the phase reports the current closure decision instead
  of inferring completion that has not happened.

## Known Deferrals

- Overdue closure decisions do not yet feed a separate archival or retention
  policy lane.
- The phase does not yet emit explicit post-closure follow-up planning.

## Next Phase

Phase 84 should focus on deterministic overdue archive recommendations:

- add one additive archive-recommendation layer on top of current overdue closure-decision evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
