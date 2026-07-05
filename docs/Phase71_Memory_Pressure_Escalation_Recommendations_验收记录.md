# Phase 71 Memory Pressure Escalation Recommendations 验收记录

## Scope

Phase 71 focused on turning existing memory pressure action hints into one
deterministic escalation-recommendation layer.

The phase added one additive escalation read surface on top of the existing
pressure, aging, velocity, governance, overview, summary, queue, and
action-hint surfaces so operators can quickly see which scopes can stay local
and which ones should move into escalation handling.

## Completed Tasks

### P71-MEM-01 - Memory Pressure Escalation Recommendations

Implemented behavior:

- Added one combined memory pressure escalation read path anchored to a session
  and enriched by optional user and tenant scope ids.
- Reused the existing pressure and action-hint helpers instead of introducing
  another durable projection or background scorer.
- Exposed additive per-scope fields including
  `escalation_recommendation`, `escalation_priority`,
  `escalation_target_memory_id`, and `escalation_reasons`.
- Added aggregate `escalation_recommendation_counts` plus a cross-scope
  `highest_priority_escalation_*` rollup for fast operator inspection.
- Kept escalation selection deterministic with simple local rules for clear,
  elevated, and sustained high-pressure states.

Validation:

- `uv run pytest tests/api/test_memory_pressure_escalations.py tests/cli/test_cli_memory_pressure_escalations.py tests/test_memory_pressure_escalations_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/cli_types.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/session_memory_read.py tests/api/test_memory_pressure_escalations.py tests/cli/test_cli_memory_pressure_escalations.py tests/test_memory_pressure_escalations_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic escalation recommendations for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Escalation recommendations stay explicitly scoped and local-first.

## Validation Notes

- Escalation recommendations stayed as a pure read-time derivation over the
  current pressure and action-hint helpers, which kept the implementation
  local-first and deterministic.
- The highest-priority rollup reuses the same `none/low/medium/high` ordering
  already used by Phase 70 action hints.

## Known Deferrals

- Escalation recommendations are coarse and deterministic; there is no
  configurable routing policy, tenant-specific SLA model, or historical trend
  analysis yet.
- The phase recommends whether a scope should escalate, but it does not yet
  expose a deterministic follow-up window for when operators should re-check or
  re-open the scope.

## Next Phase

Phase 72 should focus on deterministic escalation follow-up windows:

- add one additive follow-up-window layer on top of current escalation evidence
- keep the logic local-first and derived from current pressure and escalation
  signals
- preserve explicit scope boundaries without adding background services
