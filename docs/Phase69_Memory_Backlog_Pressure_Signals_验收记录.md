# Phase 69 Memory Backlog Pressure Signals 验收记录

## Scope

Phase 69 focused on deterministic backlog pressure classification for memory
operations.

The phase added one additive pressure read surface on top of the existing
overview, governance, backlog-aging, and review-velocity surfaces so operators
can inspect one direct summary of whether each scope is clear, steady,
elevated, or high pressure.

## Completed Tasks

### P69-MEM-01 - Memory Backlog Pressure Signals

Implemented behavior:

- Added one combined backlog-pressure read path anchored to a session and
  enriched by optional user and tenant scope ids.
- Reused the existing backlog-aging and review-velocity helpers instead of
  introducing another durable pressure projection.
- Exposed additive per-scope signals including `pressure_level` and
  `pressure_reasons` beside the existing pending, aging, and recent-review
  metrics.
- Added aggregate `pressure_level_counts` plus a cross-scope
  `highest_pressure_*` rollup for fast operator inspection.
- Kept pressure classification deterministic with simple local rules based on
  stale backlog, growing backlog, and missing recent review activity.

Validation:

- `uv run pytest tests/api/test_memory_backlog_pressure_signals.py tests/cli/test_cli_memory_backlog_pressure_signals.py tests/test_memory_backlog_pressure_signals_contract_matrix.py tests/api/test_memory_review_velocity_signals.py tests/cli/test_cli_memory_review_velocity_signals.py tests/test_memory_review_velocity_signals_contract_matrix.py tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_backlog_pressure_signals.py tests/cli/test_cli_memory_backlog_pressure_signals.py tests/test_memory_backlog_pressure_signals_contract_matrix.py tests/api/test_memory_review_velocity_signals.py tests/cli/test_cli_memory_review_velocity_signals.py tests/test_memory_review_velocity_signals_contract_matrix.py tests/api/test_memory_backlog_aging_signals.py tests/cli/test_cli_memory_backlog_aging_signals.py tests/test_memory_backlog_aging_signals_contract_matrix.py tests/api/test_memory_review_governance_signals.py tests/cli/test_cli_memory_review_governance_signals.py tests/test_memory_review_governance_signals_contract_matrix.py tests/api/test_memory_operations_overview.py tests/cli/test_cli_memory_operations_overview.py tests/test_memory_operations_overview_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic backlog pressure signals for repo,
  user, and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Existing scope boundaries remain explicit in the exposed pressure signals.

## Validation Notes

- Pressure stayed an additive layer over the current aging and review-velocity
  helpers, so those earlier regression suites remained in the phase validation
  set.
- The current pressure model is intentionally simple and local-first: it uses
  current pending counts, oldest pending age, and recent review windows instead
  of a separate historical scoring pipeline.

## Known Deferrals

- Pressure levels are coarse and deterministic; there is no configurable weight
  model or tenant-specific SLA thresholding yet.
- Pressure does not yet emit explicit operator action hints such as “review
  stale backlog first” or “throughput is healthy”.

## Next Phase

Phase 70 should focus on deterministic pressure action hints:

- add one additive operator hint layer on top of current pressure, aging, and
  review-velocity signals
- keep current contracts additive and local-first
- preserve explicit scope boundaries without introducing background jobs
