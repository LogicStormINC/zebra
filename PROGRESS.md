# Progress

## Current Phase

- Active phase: `Phase 6 - Policy And Approvals Hardening`
- Repository status: `phase 6 ready`
- Current focus:
  - harden sensitive-output policy after path traversal rules
  - keep security boundaries local-first and explicit before expanding remote/cloud services

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
- `P3-HAR-05 - Assistant Message And Tool Trace Projection`
- `P3-HAR-06 - Attempt Event Timestamp Refinement`
- `P3-HAR-07 - Planner And Verifier Hooks`
- `P3-HAR-08 - Session Event Builder Cleanup`
- `P3-HAR-09 - Tool Call Selection Strategy`
- `P3-HAR-10 - Explicit Harness Budgets`
- `P4-STO-01 - SQLite Event Store And Session Projection`
- `P4-STO-02 - Event Idempotency Protection`
- `P4-WKR-01 - Worker Recovery Entry`
- `P4-SCH-01 - SQLite Worker Leases`
- `P4-WKR-02 - Worker Claim And Resume Flow`
- `P4-GOV-01 - Core Event Schema Drafts`
- `P4-GOV-02 - Event Schema Enforcement`
- `P4-STO-03 - Incremental Event Replay`
- `P4-WKR-03 - Explicit Resume Entry`
- `P4-STO-04 - Tool Run Index`
- `P4-STO-05 - Model Call Index`
- `P5-CTX-01 - Context Compiler Bootstrap`
- `P5-CTX-02 - Related Files Recall And Ranking Split`
- `P5-CTX-03 - Conversation And Tool Output Compaction`
- `P5-CTX-04 - Prompt Layout And Cache Key Rules`
- `P5-CTX-05 - Trust Marking And Prompt-Injection Baseline`
- `P5-CTX-06 - Harness Context Input Wiring`
- `P5-CTX-07 - Runtime Evidence Context Injection`
- `P5-CTX-08 - Attempt Evidence Feedback Loop`
- `P5-CTX-09 - Structured Planner And Verifier Evidence`
- `P5-CTX-10 - Context-Aware Retry Plan Hint`
- `P5-CTX-11 - Context Compiler Acceptance Hardening`
- `P5-CTX-12 - Phase 5 Closeout Record`
- `P6-POL-01 - Local Policy Profiles`
- `P6-POL-02 - Command Risk Rules`
- `P6-POL-03 - Path Risk Rules`
- `P6-POL-04 - Sensitive Output Rules`

## Current Focus

- Phase 6 policy hardening has command, path traversal, and sensitive-output prechecks
- register the next direct slice around approval request modeling

## Next Unlocks

- `P6-POL-04` is complete
- the next step is to register the next ready Phase 6 policy and approvals task card

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
