# Phase 77 Memory Overdue Trend Signals 验收记录

## Scope

Phase 77 focused on improving overdue triage by classifying current overdue
scopes into deterministic trend signals.

The phase added one additive overdue-trend read surface on top of the existing
pressure, aging, velocity, governance, overview, summary, queue, action-hint,
escalation, follow-up-window, overdue-flag, overdue-age, overdue-type, and
overdue-visibility surfaces so operators can distinguish newly overdue scopes
from more dangerous overdue states without introducing historical storage.

## Completed Tasks

### P77-MEM-01 - Memory Overdue Trend Signals

Implemented behavior:

- Added one combined memory overdue-trend read path anchored to a session and
  enriched by optional user and tenant scope ids.
- Reused the existing overdue-age helper instead of introducing a new
  projection, scheduler, or history table.
- Exposed additive per-scope fields including `overdue_trend_signal`,
  `overdue_trend_rank`, and `overdue_trend_reasons`.
- Added aggregate `overdue_trend_signal_counts` plus a cross-scope
  `highest_priority_overdue_trend_*` rollup for fast operator inspection.
- Kept trend selection deterministic by mapping current overdue-age buckets to
  stable local signals such as `emerging_overdue`, `persistent_overdue`,
  `escalating_overdue`, and `critical_overdue`.

Validation:

- `uv run pytest tests/api/test_memory_overdue_trend_signals.py tests/cli/test_cli_memory_overdue_trend_signals.py tests/test_memory_overdue_trend_signals_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/memory_inventory_read.py apps/api/src/zebra_agent_api/session_read.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/session_memory_read.py apps/cli/src/zebra_agent_cli/read_commands.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_overdue_trend_signals.py tests/cli/test_cli_memory_overdue_trend_signals.py tests/test_memory_overdue_trend_signals_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect deterministic overdue trend signals for repo, user,
  and tenant scopes.
- API and CLI outputs remain additive and backward compatible with current
  memory operation read paths.
- Overdue trend signals stay explicitly scoped and local-first.

## Validation Notes

- The trend signal is intentionally derived from current overdue-age evidence,
  not from historical samples, so the feature stays local-first and
  deterministic.
- A long-lived memory candidate can still classify as `emerging_overdue` if the
  follow-up breach itself is recent; the phase tracks overdue state, not raw
  memory age.

## Known Deferrals

- Overdue trend signals do not yet expose intervention guidance.
- The phase does not yet compare consecutive snapshots or detect repeated
  breaches across multiple review windows.

## Next Phase

Phase 78 should focus on deterministic overdue intervention hints:

- add one additive intervention-hint layer on top of current overdue scope
  evidence
- keep the logic local-first and derived from current overdue scope data
- preserve explicit scope boundaries without adding background services
