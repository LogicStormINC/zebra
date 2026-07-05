# Phase 79 Memory Overdue Escalation Lanes 验收记录

## Scope

Phase 79 focused on improving overdue triage by mapping current overdue scopes
to deterministic escalation lanes.

The phase added one additive overdue-escalation-lane read surface on top of the
existing pressure, aging, velocity, governance, overview, summary, queue,
action-hint, escalation, follow-up-window, overdue-flag, overdue-age,
overdue-type, overdue-visibility, overdue-trend, and overdue-intervention
surfaces so operators can see the next handling lane for each overdue scope.

## Completed Tasks

### P79-MEM-01 - Memory Overdue Escalation Lanes

Implemented behavior:

- Added one combined memory overdue-escalation-lane read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing overdue-intervention helper instead of introducing a new
  projection, scheduler, or workflow engine.
- Exposed additive per-scope fields including `overdue_escalation_lane`,
  `overdue_escalation_priority`, `overdue_escalation_target_memory_id`, and
  `overdue_escalation_reasons`.
- Added aggregate `overdue_escalation_lane_counts` plus a cross-scope
  `highest_priority_overdue_escalation_*` rollup for fast operator inspection.
- Kept lane selection deterministic by mapping current overdue-intervention
  hints to stable handling lanes such as `local_queue_lane`,
  `same_day_operator_lane`, `immediate_operator_escalation`, and
  `manager_escalation`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_escalation_lanes.py tests/cli/test_cli_memory_overdue_escalation_lanes.py tests/test_memory_overdue_escalation_lanes_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_escalation_lanes.py tests/cli/test_cli_memory_overdue_escalation_lanes.py tests/test_memory_overdue_escalation_lanes_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue escalation lanes for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue escalation lanes stay explicitly scoped and local-first.

## Validation Notes

- The escalation lane is intentionally derived from current overdue-intervention
  evidence, not from external workflow state, so the feature stays local-first
  and deterministic.
- A scope can still remain on `local_queue_lane` when the overdue breach is new;
  the phase recommends the next handling lane from present overdue state rather
  than forcing premature escalation.

## Known Deferrals

- Overdue escalation lanes do not yet persist assignment ownership or SLA
  outcomes.
- The phase does not yet model explicit recovery plans after an escalation lane
  is chosen.

## Next Phase

Phase 80 should focus on deterministic overdue recovery paths:

- add one additive recovery-path layer on top of current overdue escalation-lane
  evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
