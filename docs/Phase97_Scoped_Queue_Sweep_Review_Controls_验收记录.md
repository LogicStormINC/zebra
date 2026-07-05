# Phase 97 Scoped Queue Sweep Review Controls 验收记录

## Scope

Phase 97 focused on operator throughput after the queue, summary, and review
surfaces were already in place.

The phase added one scoped queue-sweep control layer on top of the current
single-record and explicit-id bulk review paths so operators can review the
current candidate queue directly without pre-enumerating every memory id.

## Completed Tasks

### P97-MEM-01 - Scoped Queue Sweep Review Controls

Implemented behavior:

- Added local API queue-sweep review surfaces for repo-session, user, and
  tenant memory.
- Added matching local CLI queue-sweep review commands for the same supported
  scopes.
- Reused the existing single-record and explicit-id bulk review paths instead
  of introducing a second review state machine or queue-specific lifecycle
  model.
- Kept repo queue sweep session-bound by filtering repo-visible candidates down
  to the current `source_session_id` before applying the shared review logic.
- Added explicit `queue_sweep` and `queued_count` response fields so operators
  can distinguish queue-driven review from explicit-id batch review.

Validation:

- `uv run pytest tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/session_memory_control.py apps/api/src/zebra_agent_api/app.py apps/api/src/zebra_agent_api/routes.py apps/cli/src/zebra_agent_cli/memory_review_write.py apps/cli/src/zebra_agent_cli/cli.py apps/cli/src/zebra_agent_cli/cli_parser.py apps/cli/src/zebra_agent_cli/cli_types.py tests/api/test_memory_queue_sweep_review.py tests/cli/test_cli_memory_queue_sweep_review.py tests/test_memory_queue_sweep_review_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now confirm or expire the current scoped memory queue in one
  action.
- Queue-sweep responses stay additive and preserve current memory review
  semantics.
- Queue-sweep controls remain explicitly scope-bound and local-first.

## Validation Notes

- Queue sweep stayed an additive orchestration layer on top of the existing
  review controls, so there is no second review lifecycle contract to keep in
  sync.
- Repo queue sweep intentionally filters to one `source_session_id` after the
  current repo-scoped candidate query; if repo candidate volume grows beyond
  the current query ceiling, the next step should be a storage-side session
  filter rather than a broader in-memory workaround.

## Known Deferrals

- Queue sweep currently reviews the whole current scoped queue; there is still
  no server-side preview, selective filter, or dry-run path for queue review.
- Repo queue sweep still depends on the existing repo-scoped candidate query and
  post-filtering by `source_session_id` instead of a dedicated storage query.

## Next Phase

The next memory workflow priority is not yet defined.

- the queue-sweep review slice is complete
- future work can branch toward queue filtering, preview-only triage, or a new
  memory lifecycle lane
