# Phase 70 Memory Pressure Action Hints 验收记录

## Scope

Phase 70 focused on turning existing memory backlog pressure signals into one
deterministic operator next-action layer.

The phase added one additive action-hint read surface on top of the existing
pressure, aging, velocity, governance, overview, summary, and queue surfaces so
operators can quickly see what to do next for each supported scope.

## Completed Tasks

### P70-MEM-01 - Memory Pressure Action Hints

Implemented behavior:

- Added one combined memory pressure action-hint read path anchored to a
  session and enriched by optional user and tenant scope ids.
- Reused the existing backlog-pressure helper instead of introducing another
  durable projection or background scorer.
- Exposed additive per-scope fields including `action_hint`,
  `action_priority`, `action_target_memory_id`, and `action_reasons`.
- Added aggregate `action_hint_counts` plus a cross-scope
  `highest_priority_action_*` rollup for fast operator inspection.
- Kept action selection deterministic with simple local rules for clear,
  elevated, high-pressure, and healthy backlog states.

Validation:

- `uv run pytest tests/api/test_memory_pressure_action_hints.py tests/cli/test_cli_memory_pressure_action_hints.py tests/test_memory_pressure_action_hints_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_pressure_action_hints.py tests/cli/test_cli_memory_pressure_action_hints.py tests/test_memory_pressure_action_hints_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic action hints for repo, user, and
  tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Existing scope boundaries remain explicit in the exposed action hints.

## Validation Notes

- Action hints stayed as a pure read-time derivation over the current pressure
  helper, which kept the implementation local-first and deterministic.
- The highest-priority rollup is intentionally simple: `high` beats `medium`,
  `medium` beats `low`, and `none` remains informational only.

## Known Deferrals

- Action hints are coarse and deterministic; there is no configurable scoring
  policy, SLA thresholding, or tenant-specific weighting yet.
- The phase recommends what to do next, but it does not yet emit escalation
  guidance for scopes that remain under sustained high pressure.

## Next Phase

Phase 71 should focus on deterministic pressure escalation recommendations:

- add one additive escalation layer for scopes that stay stalled or repeatedly
  re-enter high pressure
- keep escalation logic local-first and derived from existing pressure-action
  evidence
- preserve explicit scope boundaries without adding background services
