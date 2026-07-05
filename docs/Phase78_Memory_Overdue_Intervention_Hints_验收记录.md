# Phase 78 Memory Overdue Intervention Hints 验收记录

## Scope

Phase 78 focused on improving overdue triage by mapping current overdue scopes
to deterministic intervention hints.

The phase added one additive overdue-intervention read surface on top of the
existing pressure, aging, velocity, governance, overview, summary, queue,
action-hint, escalation, follow-up-window, overdue-flag, overdue-age,
overdue-type, overdue-visibility, and overdue-trend surfaces so operators can
see a concrete next action for each overdue scope.

## Completed Tasks

### P78-MEM-01 - Memory Overdue Intervention Hints

Implemented behavior:

- Added one combined memory overdue-intervention read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-trend helper instead of introducing a new
  projection, scheduler, or workflow engine.
- Exposed additive per-scope fields including `overdue_intervention_hint`,
  `overdue_intervention_priority`, `overdue_intervention_target_memory_id`, and
  `overdue_intervention_reasons`.
- Added aggregate `overdue_intervention_hint_counts` plus a cross-scope
  `highest_priority_overdue_intervention_*` rollup for fast operator
  inspection.
- Kept intervention selection deterministic by mapping current overdue-trend
  signals to stable next actions such as `queue_next_review_window`,
  `same_day_review_burst`, `review_now`, and `assign_scope_owner`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_intervention_hints.py tests/cli/test_cli_memory_overdue_intervention_hints.py tests/test_memory_overdue_intervention_hints_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_intervention_hints.py tests/cli/test_cli_memory_overdue_intervention_hints.py tests/test_memory_overdue_intervention_hints_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue intervention hints for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue intervention hints stay explicitly scoped and local-first.

## Validation Notes

- The intervention hint is intentionally derived from current overdue-trend
  evidence, not from external workflow state, so the feature stays local-first
  and deterministic.
- A scope can still receive a low-priority hint if the overdue breach is new;
  the phase recommends the next action from present overdue state rather than
  from raw memory age.

## Known Deferrals

- Overdue intervention hints do not yet attach assignee routing or calendar
  integration.
- The phase does not yet escalate automatically across repeated unresolved
  intervention windows.

## Next Phase

Phase 79 should focus on deterministic overdue escalation lanes:

- add one additive escalation-lane layer on top of current overdue scope
  evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
