# Zebra Agent Progress

## Current Effective Docs

The active execution set is:

1. `AGENTS.md`
2. `docs/实施任务拆解与阶段验收.md`
3. `docs/02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
4. `docs/AGENT_TASKS.md`
5. `README.md`

Older planning documents are reference material only unless explicitly merged into the files above.

## Current Phase

Phase 1 completed. Phase 2 is ready to start.

## Current Goal

Start the first local execution path while preserving the existing `agent-core` boundary:

- implement `LocalRuntime`
- add workspace or worktree abstractions
- implement the first builtin file and command tool paths

## Status Snapshot

Completed:

- repository bootstrap is complete
- `uv` workspace and monorepo package layout are in place
- `agent-core` base domain models are implemented
- `agent-core` base Ports are implemented
- session projection and replay semantics are implemented
- Phase 1 tests and validation pass

Ready to start:

- `packages/agent-runtime` local adapter work
- `packages/agent-tools` first builtin tool work
- Phase 2 task claiming from `docs/AGENT_TASKS.md`

Not started:

- real runtime process execution
- file, patch, test, and git tool implementations
- harness worker integration on top of runtime and tools
- control-plane persistence and recovery implementation

## Recommended Next Step

Claim one `Ready` Phase 2 task from `docs/AGENT_TASKS.md` and execute it on a dedicated `codex/<task-id>-<short-name>` branch within its owned paths only.
