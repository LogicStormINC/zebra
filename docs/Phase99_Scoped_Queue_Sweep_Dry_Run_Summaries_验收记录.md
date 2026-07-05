# Phase 99 Scoped Queue Sweep Dry-Run Summaries 验收记录

## Scope

Phase 99 focused on operator decision support after scoped queue-sweep preview
controls were already available.

The phase added one dry-run summary layer on top of the current queue-sweep
preview payloads so operators can inspect not only the exact target set, but
also the projected post-review shape before confirm or expire execution.

## Completed Tasks

### P99-MEM-01 - Scoped Queue Sweep Dry-Run Summaries

Implemented behavior:

- Added projected dry-run summary metadata to local API queue-sweep preview
  surfaces for repo-session, user, and tenant memory.
- Added matching projected dry-run summary metadata to local CLI queue-sweep
  preview commands for the same supported scopes.
- Reused the current preview target set instead of introducing a second preview
  or execution planning path.
- Kept preview side-effect free by returning projected counts and projected
  status summaries without mutating memory review state.
- Added explicit projected fields for projected applied count, projected memory
  status, per-type projected counts, and projected per-record outcome rows.

Validation:

- `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/cli/src/zebra_agent_cli/memory_review_write.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now see projected queue-sweep outcome summaries before
  execution.
- Dry-run summary payloads stay additive and side-effect free.
- Projected summary fields stay parity-aligned across API and CLI preview
  surfaces.

## Validation Notes

- Dry-run summaries intentionally reuse the preview target set so target
  membership and projected outcome shape stay aligned.
- Projected status is deterministic because queue-sweep preview only models
  candidate memories and the next step is a confirm or expire review action.

## Known Deferrals

- Dry-run summaries currently expose projected status and per-type counts, but
  there is still no filtered preview, capped preview page, or richer “why this
  record is in the target set” explanation layer.
- Repo-session preview and dry-run summary still depend on the current
  repo-scoped query ceiling instead of a dedicated session-filtered storage
  query.

## Next Phase

The next memory workflow priority is not yet defined.

- the queue-sweep dry-run summary slice is complete
- future work can branch toward filtered preview, richer target explanations, or
  a new memory lifecycle lane
