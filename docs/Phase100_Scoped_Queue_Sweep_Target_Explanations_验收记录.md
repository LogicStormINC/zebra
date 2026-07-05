# Phase 100 Scoped Queue Sweep Target Explanations 验收记录

## Scope

Phase 100 focused on operator explainability after scoped queue-sweep preview
and dry-run summary controls were already available.

The phase added one target explanation layer on top of the current queue-sweep
preview payloads so operators can inspect why each record is in the current
preview target set before confirm or expire execution.

## Completed Tasks

### P100-MEM-01 - Scoped Queue Sweep Target Explanations

Implemented behavior:

- Added target explanation metadata to local API queue-sweep preview surfaces
  for repo-session, user, and tenant memory.
- Added matching target explanation metadata to local CLI queue-sweep preview
  commands for the same supported scopes.
- Reused the current preview target set instead of introducing a separate
  explanation-only targeting path.
- Kept preview side-effect free by returning per-record target reasons and
  aggregate explanation counts without mutating memory review state.
- Added explicit explanation fields for target scope kind, target scope id,
  aggregate target reason counts, and per-record target explanation rows.

Validation:

- `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/cli/src/zebra_agent_cli/memory_review_write.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now inspect why each record is in the scoped queue-sweep
  preview target set.
- Target explanation payloads stay additive and side-effect free.
- Explanation fields stay parity-aligned across API and CLI preview surfaces.

## Validation Notes

- Explanation metadata intentionally reuses the current preview target set so
  target membership and target reason reporting stay aligned.
- The current explanation model is deterministic because scoped preview targets
  are derived from one explicit visibility plus scope match rule per surface.

## Known Deferrals

- Target explanations currently expose stable inclusion reasons, but there is
  still no filtered preview, capped preview page, or richer source-event level
  explanation layer.
- Repo-session preview, dry-run summary, and target explanation still depend on
  the current repo-scoped query ceiling instead of a dedicated session-filtered
  storage query.

## Next Phase

The next memory workflow priority is not yet defined.

- the queue-sweep target explanation slice is complete
- future work can branch toward filtered preview, richer source-event
  explanations, or a new memory lifecycle lane
