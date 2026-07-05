# Phase 59 Memory Source Provenance Readback 验收记录

## Scope

Phase 59 completed the first operator-facing memory provenance readback slice.

The phase kept storage contracts unchanged and instead projected deterministic
source provenance onto session memory inventory rows by reconstructing source
details from the persisted session event stream.

## Completed Tasks

### P59-MEM-01 - Memory Source Provenance Readback

Implemented behavior:

- Added shared `source` provenance serialization for session memory inventory
  rows.
- Reconstructed deterministic provenance from `source_event_start` and
  `source_event_end` against persisted session events instead of changing the
  memory record schema.
- Covered tool-derived procedure memory, governance doc reads, and explicit
  user-message preference memory.
- Preserved existing `last_review` lifecycle readback and API or CLI parity.

Validation:

- `uv run pytest tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
- `uv run ruff check packages/agent-core/src/agent_core/application/memory_inventory.py tests/api/test_session_memory.py tests/cli/test_cli_session_memory.py tests/test_session_memory_read_contract_matrix.py`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Session memory inventory rows now expose deterministic source provenance for
  candidate and reviewed records.
- API and CLI session memory read surfaces keep parity for shared provenance
  fields.
- Existing lifecycle readback remains backward compatible.

## Validation Notes

- Provenance readback regression coverage passed across API, CLI, and the shared
  contract matrix.
- `make check` passed after documentation and progress-state synchronization.

## Known Deferrals

- Provenance is currently reconstructed from session events at read time rather
  than materialized onto the memory record itself.
- Operator readback still stops at repo-scoped memory inventory; user-scoped and
  tenant-scoped memory operator surfaces remain out of scope.

## Next Phase

Phase 60 should decide whether memory operator work expands outward by scope or
deeper by workflow:

- add operator-facing inventory and review surfaces for user-scoped and
  tenant-scoped memory, or
- add richer repo-memory review workflows such as bulk triage or explicit source
  family filtering
