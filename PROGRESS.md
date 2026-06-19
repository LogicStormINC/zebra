# Progress

## Current Phase

- Active phase: `Phase 2 - Runtime And Tooling Spine`
- Repository status: `phase 3 in progress`
- Current focus:
  - implement the first mock model gateway path on top of the harness loop skeleton
  - keep the `Phase 2` runtime and builtin contracts stable as the base layer for harness work

## Completed

- `Phase 0 - Repo Bootstrap`
- `Phase 1 - Core Domain`
- `P2-RT-01 - LocalRuntime Process Execution`
- `P2-RT-02 - Workspace And Worktree Abstractions`
- `P2-TOOL-01 - Tool Contracts And Execution Results`
- `P2-TOOL-02 - Builtin File Read Path`
- `P2-TOOL-03 - Builtin Command Execution Path`
- `P2-TOOL-04 - Builtin Patch Apply Path`
- `P2-TOOL-05 - Builtin Validation Commands`
- `P2-IT-01 - Local Toolchain Integration Flow`
- `P2-GIT-01 - Readonly Git Inspection Tools`
- `P3-HAR-01 - Harness Loop Skeleton`
- `P3-MOD-01 - Mock Model Gateway`
- `P3-HAR-02 - Single Attempt Tool Orchestration`
- `P3-HAR-03 - Structured Run Output And Retry Skeleton`
- `P3-HAR-04 - Multi-Attempt Loop Driver`

## Current Focus

- `P3-HAR-05 - Assistant Message And Tool Trace Projection`
- keep the existing runtime and builtin contracts stable while the harness exposes richer structured traces

## Next Unlocks

- `P3-HAR-05` is now the next direct Phase 3 slice
- the next step is to expose assistant and tool traces in a more ergonomic run-facing structure

## Active Documents

Read in this order for implementation work:

1. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`
2. `docs/实施任务拆解与阶段验收.md`
3. `docs/02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`
4. `docs/AGENT_TASKS.md`
5. `AGENTS.md`
6. `README.md`

## Validation Baseline

- Default commands:
  - `make sync`
  - `make test`
  - `make check`
- Phase 2 slices should also carry targeted `pytest`, `ruff`, and `mypy` evidence in `WORKLOG.md` or the merge commit context.

## Notes

- `WORKLOG.md` is the session log. It replaces the old lowercase `progress.md` name because macOS default filesystems are case-insensitive and cannot safely hold both `PROGRESS.md` and `progress.md`.
