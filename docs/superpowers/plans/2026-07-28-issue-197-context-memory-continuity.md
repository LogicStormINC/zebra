# Issue #197 Context Continuity And Governed Memory Implementation Plan

> **For agentic workers:** REQUIRED: Use `executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the valid parts of issue #197 with exact-tail compaction, recoverable overflow, evidence-gated memory promotion and token-bounded relevant recall.

**Architecture:** Extend the existing projection/Capsule and memory-review paths. Same-Task state remains Event/Capsule backed; only confirmed derived memory crosses Task boundaries; SQLite FTS is a local ranking aid, not a new authority.

**Tech Stack:** Python 3.12, Pydantic, SQLite/FTS5, pytest, existing Zebra package Ports.

---

## Chunk 1: Same-Task continuity

### Task 1: Exact recent turns and scalable Capsule summary

**Files:**
- Modify: `packages/agent-context/src/agent_context/conversation.py`
- Test: `tests/agent_context/test_conversation_history.py`

- [x] Add a failing regression with four user turns and interleaved complete tool groups.
- [x] Prove current compaction does not preserve the last three user turns verbatim.
- [x] Replace the latest-tool-only cut with a tail cut anchored at the third-last real user turn and adjusted to a complete tool group boundary.
- [x] Render the existing `ContextCapsule` fields into the middle summary and derive its budget from `max_tokens`.
- [x] Run `uv run pytest tests/agent_context/test_conversation_history.py -q`; expect all pass.

### Task 2: One strict retry and recoverable overflow

**Files:**
- Create: `packages/agent-core/src/agent_core/harness/context_recovery.py`
- Modify: `packages/agent-core/src/agent_core/harness/model_step.py`
- Modify: `apps/worker/src/zebra_agent_worker/execution_errors.py`
- Test: `tests/agent_core/test_context_window_gate.py`
- Test: `tests/worker/test_worker_context_lifecycle.py`

- [x] Add a compactor spy proving the second compaction uses original messages and a smaller budget.
- [x] Add a regression proving two failed projections never call the provider.
- [x] Recalculate the required message budget from the first plan's overage and retry once.
- [x] Classify `ContextWindowExceededError` as `SUSPENDED` and attach plan diagnostics.
- [x] Run the two focused test files; expect all pass.

## Chunk 2: Governed cross-Task memory

### Task 3: Evidence-gated automatic promotion

**Files:**
- Create: `packages/agent-core/src/agent_core/application/memory_candidate_promotions.py`
- Modify: `packages/agent-core/src/agent_core/application/memory_reviews.py`
- Modify: `packages/agent-core/src/agent_core/application/__init__.py`
- Modify: `apps/worker/src/zebra_agent_worker/execution_finalization.py`
- Modify: `apps/worker/src/zebra_agent_worker/execution.py`
- Create: `tests/agent_core/test_memory_candidate_promotions.py`
- Modify: `tests/agent_core/test_memory_reviews.py`
- Modify: `tests/worker/test_execution_finalization.py`

- [x] Add tests for explicit preference, successful procedure, complete `AGENTS.md`, conflict, unsupported type and forged source.
- [x] Extend review command with an optional actor defaulting to USER.
- [x] Implement a promotion service that reconstructs eligibility from source events and refuses different confirmed records in the same scope/type.
- [x] Upsert review results and append automatic review events after candidate events during completion finalization.
- [x] Run focused core and worker tests; expect all pass.

### Task 4: FTS recall and token budget

**Files:**
- Modify: `packages/agent-core/src/agent_core/domain/memories.py`
- Modify: `packages/agent-storage/src/agent_storage/memories.py`
- Create: `packages/agent-storage/src/agent_storage/memory_search.py`
- Modify: `packages/agent-storage/src/agent_storage/memory_lookup.py`
- Modify: `apps/worker/src/zebra_agent_worker/execution.py`
- Modify: `tests/agent_storage/test_sqlite_memories.py`

- [x] Add failing tests for query relevance, repo isolation, migration backfill, update synchronization, expiry/deduplication and token cap.
- [x] Add optional `text_query` to `MemoryQuery` and an FTS5-backed list path with deterministic fallback.
- [x] Keep FTS rows synchronized inside `SQLiteMemoryStore.upsert()`.
- [x] Merge a small stable-rule lane with relevant results and enforce `max_tokens` plus legacy count limit.
- [x] Pass current `task.user_input` from Worker and run storage/worker regressions.

## Chunk 3: Durable handoff and validation

### Task 5: Documentation and complete gates

**Files:**
- Modify: `README.md`
- Modify: `PROGRESS.md`
- Modify: `docs/AGENT_TASKS.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `WORKLOG.md`

- [x] Update the task card and design status with exact focused results.
- [x] Run `make test`.
- [x] Run `make check`.
- [x] Inspect `git diff --check`, file lengths and branch status.
- [x] Commit only owned paths, push the branch and open one PR against `main`.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Baseline referenced two nonexistent test paths | 1 | Located actual tests with `rg --files`; corrected baseline passed 33 tests |
