# Phase 101 Scoped Queue Sweep Filtered Preview Controls 验收记录

## Scope

Phase 101 focused on operator narrowing controls after scoped queue-sweep
preview, dry-run summary, and target explanation controls were already
available.

The phase added one minimal filtered preview layer on top of the current
queue-sweep preview payloads so operators can reduce the current preview target
set before confirm or expire execution.

## Completed Tasks

### P101-MEM-01 - Scoped Queue Sweep Filtered Preview Controls

Implemented behavior:

- Added `memory_type` filtering to local API queue-sweep preview surfaces for
  repo-session, user, and tenant memory.
- Added matching `memory_type` filtering to local CLI queue-sweep preview
  commands for the same supported scopes.
- Reused the current preview target set and applied filtering only inside the
  preview layer instead of introducing a second queue selection path.
- Kept preview side-effect free by returning filter metadata and filtered counts
  without mutating memory review state.
- Added explicit filtered preview fields for the active `memory_type` filter and
  the pre-filter queued count.

Validation:

- `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/session_payloads.py apps/api/src/zebra_agent_api/session_memory_control.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_parser.py apps/cli/src/zebra_agent_cli/memory_review_write.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now narrow preview targets with one supported filter before
  execution.
- Filtered preview payloads stay additive and side-effect free.
- Filter fields stay parity-aligned across API and CLI preview surfaces.

## Validation Notes

- The first supported filter is intentionally limited to `memory_type` because
  it narrows preview targets meaningfully without introducing a second queue
  selection protocol.
- Queue-sweep review execution remains unfiltered; filtering is preview-only so
  operators still need an explicit confirm or expire sweep to apply changes.

## Known Deferrals

- Filtered preview currently supports only one filter field; there is still no
  capped preview page, combined multi-filter query, or source-event level
  explanation filter.
- Repo-session preview, dry-run summary, target explanation, and filtered
  preview still depend on the current repo-scoped query ceiling instead of a
  dedicated session-filtered storage query.

## Next Phase

The next memory workflow priority is not yet defined.

- the queue-sweep filtered preview slice is complete
- future work can branch toward richer filters, capped preview pagination, or a
  new memory lifecycle lane
