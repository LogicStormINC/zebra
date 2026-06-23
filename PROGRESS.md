# Progress

## Current Phase

- Active phase: `Phase 15 - Credential Broker Foundation`
- Repository status: `phase 15 ready`
- Current focus:
  - define credential capabilities before introducing concrete secret backends
  - keep local-only PR planning as the default behavior
  - keep live SCM execution behind explicit provider, dry-run, credential, and policy gates

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
- `P6-POL-05 - Approval Request Model`
- `P6-POL-06 - Approval Event Wiring`
- `P6-POL-07 - Approval Decision Projection`
- `P6-POL-08 - Approval Service Entry`
- `P6-POL-09 - Phase 6 Closeout Record`
- `P7-OBS-01 - Observability Models Bootstrap`
- `P7-OBS-02 - Local Trace JSONL Store`
- `P7-OBS-03 - Local Replay Runner`
- `P7-EVAL-01 - Eval Case And Grader Bootstrap`
- `P7-EVAL-02 - Local Eval Runner`
- `P7-EVAL-03 - Baseline Eval Case Expansion`
- `P7-EVAL-04 - Local Release Gate Baseline`
- `P7-EVAL-05 - Eval Release Check Integration`
- `P7-EVAL-06 - Phase 7 Closeout Record`
- `P8-CLI-01 - CLI Command Skeleton`
- `P8-CLI-02 - CLI Run Local Session Creation`
- `P8-CLI-03 - CLI Inspect And Resume Session Read`
- `P8-CLI-04 - CLI Approve Local Decision`
- `P8-API-01 - API Health And Session Foundation`
- `P8-API-02 - API Route Adapter`
- `P8-CONFIG-01 - Local Settings Loader`
- `P8-CONFIG-02 - Entry Point Settings Wiring`
- `P8-API-03 - FastAPI Serving Foundation`
- `P8-API-04 - Session Stream Foundation`
- `P8-DOC-01 - Operator Runbook`
- `P8-API-05 - Local API Auth Foundation`
- `P8-MOD-01 - OpenAI-Compatible Model Gateway Adapter`
- `P8-MOD-02 - CLI Model Gateway Smoke`
- `P8-CLI-05 - CLI Durable Run Execution`
- `P8-API-06 - API Session Create And Execute`
- `P8-QUE-01 - Queued Session Bootstrap Events`
- `P8-WKR-04 - Worker Execute Ready Session`
- `P8-CLI-06 - CLI Resume Execute Trigger`
- `P8-API-07 - API Resume Execute Trigger`
- `P8-WKR-05 - Worker Ready Session Loop`
- `P8-INT-01 - Phase 8 Mainline Alignment`
- `P8-CLOSE-01 - Phase 8 Closeout Record`
- `P9-API-01 - Session Messages Entry`
- `P9-API-02 - Cancel And Suspend Entry`
- `P9-API-03 - Approval HTTP Entry`
- `P9-WKR-01 - Worker Continuous Loop Behavior`
- `P9-CLOSE-01 - Phase 9 Closeout And Phase 10 Planning`
- `P10-API-01 - Session Diff Read API`
- `P10-API-02 - Session Artifacts Read API`
- `P10-API-03 - Session Commit API`
- `P10-API-04 - Session Pull Request API`
- `P10-CLOSE-01 - Phase 10 Closeout And Phase 11 Planning`
- `P11-API-01 - Side Effect Idempotency Keys`
- `P11-OBS-01 - Delivery Audit Events`
- `P11-INT-01 - GitHub Pull Request Provider Skeleton`
- `P11-CLOSE-01 - Phase 11 Closeout And Phase 12 Planning`
- `P12-CONFIG-01 - SCM Provider Settings`
- `P12-INT-01 - Pull Request Gateway Selection`
- `P12-API-01 - Delivery Audit Read API`
- `P12-CLOSE-01 - Phase 12 Closeout And Phase 13 Planning`
- `P13-API-01 - API Composition Split`
- `P13-SEC-01 - SCM Credential Boundary Draft`
- `P13-INT-01 - Guarded GitHub Pull Request Execution`
- `P13-CLOSE-01 - Phase 13 Closeout And Phase 14 Planning`
- `P14-OBS-01 - SCM Execution Audit Hardening`
- `P14-SEC-01 - SCM Token Redaction Regression Gate`
- `P14-DOC-01 - Remote SCM Operator Safety Runbook`
- `P14-CLOSE-01 - Phase 14 Closeout And Next Planning`

## Current Focus

- Phase 11 is now closed with idempotency, delivery audit, and GitHub PR provider skeleton complete
- remote SCM execution is still not wired to the API and remains an explicit future task
- Phase 12 is now closed with SCM settings, gateway selection, and delivery audit read API complete
- `apps/api/src/zebra_agent_api/app.py` has been reduced from 489 to 384 lines by moving read-only session APIs into `session_read.py`
- SCM credential boundary now separates token environment names from token values and provides deterministic redaction
- guarded GitHub PR execution now requires explicit GitHub provider, dry-run disablement, token availability, and full-access policy
- SCM execution audit metadata now normalizes provider, status, URL, commit SHA, dry-run flag, and unavailable reasons without token values
- SCM token redaction regression coverage now checks PR plans, API responses, delivery audit records, and settings snapshots
- remote SCM operator safety runbook now documents dry-run first, explicit opt-in, token rules, audit inspection, and rollback steps
- Phase 14 is closed with `docs/Phase14_SCM_Execution_Hardening_验收记录.md`
- Phase 15 starts credential broker foundation work before adding concrete secret backends

## Next Unlocks

- `P15-SEC-01 - Credential Capability Domain Model` is ready
- `P15-SEC-02 - Credential Broker Port` unlocks after capability model
- `P15-INT-01 - SCM Broker Lookup Adapter` unlocks after broker Port

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
