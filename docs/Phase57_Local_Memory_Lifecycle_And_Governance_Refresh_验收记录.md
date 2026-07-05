# Phase 57 Local Memory Lifecycle And Governance Refresh 验收记录

## Scope

Phase 57 completed the first local memory foundation for Zebra Agent.

The phase started with a typed local SQLite memory store, then added
deterministic candidate extraction, review controls, confirmed-memory prompt
injection, doc-derived repo memory, and narrow lifecycle handling for duplicate,
superseded, expired, and stale governance-derived records.

## Completed Tasks

### P57-MEM-01 To P57-MEM-05 - Local Memory Store, Extraction, And Review Controls

Implemented behavior:

- Added typed memory records, statuses, scopes, and a core memory store Port.
- Wired worker-side candidate persistence for deterministic `procedure`
  extraction from successful tool runs.
- Added local API and CLI read plus review controls for session-scoped memory
  candidates.

Validation:

- `make check`

### P57-MEM-06 To P57-MEM-08 - Confirmed Memory Prompt Injection And Review Semantics

Implemented behavior:

- Injected confirmed repo memory into stable local harness prompt assembly.
- Preserved `memory_type`, ranking order, and duplicate collapse during prompt
  rendering.
- Added deterministic confirm-review supersession for single-active memory
  types.

Validation:

- `make check`

### P57-MEM-09 To P57-MEM-11 - Narrow Deterministic Expansion Beyond Tool Procedures

Implemented behavior:

- Added `project_rule` extraction from successful reads of root `AGENTS.md`.
- Added `architecture_fact` extraction from explicit package-boundary rules in
  the same governance document.
- Added explicit `preference` extraction from user messages prefixed with
  `Preference:`.

Validation:

- `make check`

### P57-MEM-12 To P57-MEM-15 - Memory Lifecycle Tightening

Implemented behavior:

- Filtered expired confirmed memories out of prompt-time lookup.
- Made review conflict handling type-aware so confirmed preferences can coexist
  while singleton repo memories still supersede.
- Expired duplicate confirm candidates instead of creating redundant confirmed
  records.
- Auto-expired stale confirmed doc-derived `project_rule` and
  `architecture_fact` memories after a full successful reread of root
  `AGENTS.md` no longer matched the current governance source of truth.

Validation:

- `uv run pytest tests/agent_core/test_memory_candidates.py tests/worker/test_execution.py -k 'memory_candidate or agents_refresh or stale or architecture_fact or project_rule or preference'`
- `uv run mypy packages apps`
- `make check`

## Acceptance Summary

- Zebra Agent now has a local-first typed memory store with deterministic
  extraction, review, retrieval, and prompt injection.
- Repo-scoped governance memory can now be derived from successful root
  `AGENTS.md` reads without model summarization.
- Duplicate, superseded, expired, and stale doc-derived memory states now have
  durable review semantics instead of accumulating silent drift.

## Validation Notes

- Targeted memory extraction and worker regression suites passed during the
  stale-governance invalidation slice.
- `make check` passed after the phase closeout and Phase 58 starter work landed.

## Known Deferrals

- Stale invalidation is still intentionally narrow and currently anchored to
  deterministic governance-derived repo memory.
- Session memory readback still needed richer lifecycle visibility before the
  next broader invalidation step.

## Next Phase

Phase 58 should continue the memory lane with lifecycle readback and broader
stale-memory invalidation planning:

- expose durable memory review lifecycle metadata across local operator read
  surfaces
- widen stale invalidation beyond the current governance-refresh-only path
- keep API and CLI parity explicit while the memory inventory surface evolves
