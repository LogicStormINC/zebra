# Phase 64 Cross-Scope Memory Queue Summary 验收记录

## Scope

Phase 64 focused on operator visibility before queue detail inspection.

The phase added additive summary surfaces for repo-session, user, and tenant
memory queues so operators can see pending counts and the latest candidate
timestamp without loading full queue entries.

## Completed Tasks

### P64-MEM-01 - Cross-Scope Memory Queue Summary

Implemented behavior:

- Added shared queue summary reads for repo-session, user, and tenant scopes.
- Exposed additive API and CLI summary surfaces alongside the existing queue
  detail reads.
- Kept scope boundaries explicit so every summary read is still anchored to one
  session, one user, or one tenant.
- Limited the payload to pending count, queue status, and latest candidate
  metadata so it stays lightweight and non-overlapping with queue detail.

Validation:

- `uv run pytest tests/api/test_memory_scope_queue_summary.py tests/cli/test_cli_memory_scope_queue_summary.py tests/test_memory_scope_queue_summary_contract_matrix.py tests/api/test_memory_scope_queue.py tests/cli/test_cli_memory_scope_queue.py tests/test_memory_scope_queue_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api apps/cli/src/zebra_agent_cli tests/api/test_memory_scope_queue_summary.py tests/cli/test_cli_memory_scope_queue_summary.py tests/test_memory_scope_queue_summary_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Operators can now read pending memory counts by scope before opening full
  queue detail.
- API and CLI summary outputs remain additive and backward compatible with the
  current queue and bulk review paths.
- Current explicit scope boundaries remain preserved in summary reads.

## Validation Notes

- Queue detail regression coverage stayed in the validation set to ensure the
  new summary reads did not change the existing queue contract.
- `make check` passed after the summary closeout and next-phase planning docs
  were synchronized.

## Known Deferrals

- Summary reads are still one-scope-at-a-time; there is no combined
  multi-scope dashboard yet.
- Summary reads report counts and latest candidate metadata, but not grouped
  counts by memory type or review age.

## Next Phase

Phase 65 should focus on cross-scope operator overview:

- add one combined memory operations dashboard or summary read that can report
  repo-session, user, and tenant queue health together
- preserve current per-scope detail, summary, and bulk review contracts as
  additive building blocks
- keep summary logic deterministic and local-first
