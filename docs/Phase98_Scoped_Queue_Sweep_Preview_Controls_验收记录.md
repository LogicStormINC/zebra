# Phase 98 Scoped Queue Sweep Preview Controls 验收记录

## Scope

Phase 98 focused on operator safety and predictability after scoped queue-sweep
review execution was already available.

The phase added one side-effect-free preview layer on top of the current queue
sweep targeting logic so operators can inspect the exact candidate set that a
confirm or expire sweep would touch before executing it.

## Completed Tasks

### P98-MEM-01 - Scoped Queue Sweep Preview Controls

Implemented behavior:

- Added local API queue-sweep preview surfaces for repo-session, user, and
  tenant memory.
- Added matching local CLI queue-sweep preview commands for the same supported
  scopes.
- Reused the current queue query path and current repo-session
  `source_session_id` narrowing instead of introducing a second targeting rule.
- Kept preview side-effect free by returning the exact queued ids and records
  without mutating memory review state.
- Added explicit `queue_sweep_preview` and `queued_count` response fields so
  operators can distinguish preview payloads from queue-sweep execution results.

Validation:

- `uv run pytest tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/memory_review_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_parser.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_queue_sweep_preview.py tests/cli/test_cli_memory_queue_sweep_preview.py tests/test_memory_queue_sweep_preview_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now preview the exact scoped queue-sweep target set before
  review.
- Preview responses stay additive and side-effect free.
- Repo-session preview reflects the same `source_session_id` narrowing used by
  queue sweep execution.

## Validation Notes

- Preview intentionally reuses the same target selection path as queue-sweep
  execution so operators do not have to reconcile two different target rules.
- Repo-session preview still depends on the current repo-scoped candidate query
  and post-filtering by `source_session_id`; if one workspace can exceed the
  current query ceiling, the next upgrade should be a storage-side session
  filter rather than a broader in-memory workaround.

## Known Deferrals

- Preview currently returns the whole current scoped target set; there is still
  no server-side limit, selective filter, or dry-run diff view for queue-sweep
  preview.
- Queue-sweep preview and queue-sweep execution still rely on the same
  repo-scoped query ceiling instead of a dedicated session-filtered storage
  query.

## Next Phase

The next memory workflow priority is not yet defined.

- the queue-sweep preview slice is complete
- future work can branch toward filtered preview, dry-run diff summaries, or a
  new memory lifecycle lane
