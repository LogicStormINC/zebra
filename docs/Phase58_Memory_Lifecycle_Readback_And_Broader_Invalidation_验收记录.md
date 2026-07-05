# Phase 58 Memory Lifecycle Readback And Broader Invalidation 验收记录

## Scope

Phase 58 completed the first memory lifecycle visibility pass and broadened
deterministic stale confirmed-memory invalidation beyond the original
governance-only rule.

The phase first projected the latest durable review metadata into session memory
inventory reads, then generalized stale invalidation around eligible refresh
targets so singleton repo memories can expire from deterministic re-extraction
without being tied only to one helper path.

## Completed Tasks

### P58-MEM-01 - Session Memory Lifecycle Readback

Implemented behavior:

- Added a shared memory inventory serializer for API and CLI session-memory
  reads.
- Projected the latest durable `memory_review_recorded` payload into
  `last_review` for each inventory row.
- Exposed system-driven auto-expire reasons and operators on session memory
  readback without changing the storage schema.

Validation:

- `uv run pytest tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
- `uv run ruff check apps/api/src/zebra_agent_api/session_read.py apps/cli/src/zebra_agent_cli/session_memory_read.py packages/agent-core/src/agent_core/application/memory_inventory.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
- `make check`

### P58-MEM-02 - Broader Stale Confirmed Memory Invalidation

Implemented behavior:

- Replaced the hard-coded stale-doc invalidation path with refresh-target-driven
  invalidation rules.
- Kept invalidation limited to deterministic singleton repo memory categories:
  `project_rule`, `architecture_fact`, and `procedure`.
- Added a second eligible refresh family for procedure extraction from
  successful non-sensitive `command.run` and `tests.run` events, while leaving
  non-singleton `preference` memories untouched.
- Preserved durable `memory_review_recorded` events so downstream lifecycle
  readback still sees explicit operator, reason, and status.

Validation:

- `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'stale or procedure_refresh or agents_refresh or preference or architecture_fact or project_rule'`
- `uv run ruff check packages/agent-core/src/agent_core/application tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Session memory inventory rows now explain the latest review lifecycle through
  `last_review`.
- Stale confirmed singleton repo memories now expire through source-family-aware
  deterministic refresh rules instead of a one-off governance helper check.
- Durable invalidation events remain stable for API, CLI, and worker lifecycle
  readback.

## Validation Notes

- API, CLI, core, and worker memory regression suites passed after the broader
  invalidation landed.
- `make check` passed after the phase closeout documentation and starter-task
  updates landed.

## Known Deferrals

- Memory records still do not persist first-class source provenance fields such
  as source family or locator; lifecycle reasoning is reconstructed from events.
- Session memory inventory exposes the latest review metadata, but not yet a
  compact source provenance summary for operator triage.

## Next Phase

Phase 59 should focus on memory provenance and operator-facing read clarity:

- expose deterministic source provenance for memory candidates and reviewed
  records without weakening current contracts
- keep API and CLI memory inventory parity while adding provenance readback
- decide whether the next lane should stay repo-scoped or expand toward
  user-scoped and tenant-scoped memory review surfaces
