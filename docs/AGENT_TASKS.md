# AGENT_TASKS.md

> This is the active executable task registry for Zebra Agent.
> Status, owner, branch, and evidence must be maintained by humans.
> Current execution range: Phase 2 completed; Phase 3 prepared from `实施任务拆解与阶段验收.md`.

## Global Rules

- Read `AGENTS.md`, `实施任务拆解与阶段验收.md`, `02_Codex-like工程Agent平台_多人协作任务分配与RACI_v1.0.md`, and `PROGRESS.md` before claiming a task.
- One task allows one primary goal, one human owner, one branch, one worktree, and one main PR.
- Paths outside `Owned paths` are out of scope unless the task definition is explicitly updated first.
- If a task needs real credentials, broad policy changes, or cross-boundary refactors, stop and escalate.
- Finish by running the task-specific validation plus `make check` when applicable.

## Status Legend

`Locked` / `Ready` / `In Progress` / `Review` / `Blocked` / `Done`

## Phase 2 Task Board

### P2-RT-01 - LocalRuntime Process Execution

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `RUNTIME`
- Depends on: `Phase 1 completed`
- Branch: `codex/p2-rt-01-local-runtime`
- Owned paths: `packages/agent-runtime/`, `packages/agent-core/src/agent_core/ports/runtime.py`, `tests/`

#### Goal

Implement a real `LocalRuntime` that can execute a constrained command process through the existing `RuntimePort`.

#### Deliverables

- process execution API
- timeout handling
- exit code capture
- stdout and stderr capture contract
- tests for successful execution and timeout or failure behavior

#### Acceptance

- [x] Runtime can execute a simple command and return structured results.
- [x] Timeout behavior is deterministic and tested.
- [x] No `agent-core` module imports infrastructure SDKs because of this task.
- [x] Validation commands and results are recorded in the PR or work log.

### P2-RT-02 - Workspace And Worktree Abstractions

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `RUNTIME`
- Depends on: `P2-RT-01`
- Branch: `codex/p2-rt-02-workspace-abstraction`
- Owned paths: `packages/agent-runtime/`, `tests/`

#### Goal

Add local workspace abstractions that prepare later file, patch, and git tools without yet implementing the full sandbox flow.

#### Deliverables

- workspace model
- repository path handling
- worktree abstraction or placeholder interface
- tests for path normalization and workspace lifecycle

#### Acceptance

- [x] Runtime-side workspace handling is typed and testable.
- [x] Path normalization and invalid path behavior are covered by tests.
- [x] The implementation stays within runtime boundaries.

### P2-TOOL-01 - Tool Contracts And Execution Results

- Status: `Review`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `Phase 1 completed`
- Branch: `codex/p2-tool-01-tool-results`
- Owned paths: `packages/agent-tools/`, `packages/agent-core/src/agent_core/py.typed`, `tests/`

#### Goal

Create the first concrete execution-layer tool contracts and result structures behind the existing core tool gateway boundary.

#### Deliverables

- runtime-facing tool result model
- tool registry or execution scaffolding
- validation of tool identity and arguments shape
- tests for invalid or unknown tool calls

#### Acceptance

- [x] Tool execution paths reject invalid inputs before runtime execution.
- [x] Result model is structured enough for later command and file tools.
- [x] Tests cover success path and invalid input path.

### P2-TOOL-02 - Builtin File Read Path

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P2-TOOL-01`, `P2-RT-02`
- Branch: `codex/p2-tool-02-file-read`
- Owned paths: `packages/agent-tools/`, `packages/agent-runtime/`, `tests/`

#### Goal

Implement the first builtin file read path using runtime-side workspace constraints.

#### Deliverables

- read-file builtin tool
- path validation
- oversized output behavior
- tests for normal reads and path rejection

#### Acceptance

- [x] Reads outside the allowed workspace are rejected.
- [x] Normal read behavior is deterministic and tested.
- [x] Output behavior for large files is defined.

### P2-TOOL-03 - Builtin Command Execution Path

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P2-TOOL-01`, `P2-RT-01`
- Branch: `codex/p2-tool-03-command-run`
- Owned paths: `packages/agent-tools/`, `packages/agent-runtime/`, `tests/`

#### Goal

Implement the first builtin command tool using typed executable plus argv, not free-form shell strings.

#### Deliverables

- command tool contract
- runtime invocation mapping
- timeout propagation
- tests for success, non-zero exit, and timeout

#### Acceptance

- [x] Command execution does not rely on unrestricted shell parsing.
- [x] Exit code and captured output are returned in structured form.
- [x] Timeout handling is tested end to end.

### P2-TOOL-04 - Builtin Patch Apply Path

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P2-TOOL-02`, `P2-TOOL-03`
- Branch: `codex/p2-tool-04-patch-apply`
- Owned paths: `packages/agent-tools/`, `packages/agent-runtime/`, `tests/`

#### Goal

Implement the first builtin patch path that can apply a constrained diff inside the current workspace.

#### Deliverables

- patch tool contract
- workspace-bounded patch path validation
- runtime invocation mapping for patch application
- tests for success and invalid path rejection

#### Acceptance

- [x] Patch application stays within the current workspace.
- [x] Patch failure returns a structured tool result.
- [x] Tests cover a successful apply path and a rejected path.

### P2-TOOL-05 - Builtin Validation Commands

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P2-TOOL-03`, `P2-TOOL-04`
- Branch: `codex/p2-tool-05-validation-commands`
- Owned paths: `packages/agent-tools/`, `packages/agent-runtime/`, `tests/`

#### Goal

Implement the first validation-oriented builtin tools so the local loop can run tests or checks after edits.

#### Deliverables

- test or check tool contract
- command preset mapping for deterministic validation
- timeout and non-zero handling
- tests for successful validation and failure reporting

#### Acceptance

- [x] Validation execution uses typed commands, not free shell text.
- [x] Test or check results are returned in structured form.
- [x] Failure and timeout behavior are tested.

### P2-GIT-01 - Readonly Git Inspection Tools

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `RUNTIME`
- Depends on: `P2-TOOL-03`, `P2-RT-02`
- Branch: `codex/p2-git-01-readonly-inspection`
- Owned paths: `packages/agent-tools/`, `packages/agent-runtime/`, `tests/`

#### Goal

Add the first readonly git inspection path needed for local agent verification and review loops.

#### Deliverables

- readonly git status or diff tool contract
- workspace-root git invocation mapping
- tests for clean and dirty repository inspection

#### Acceptance

- [x] Git inspection stays readonly.
- [x] Output is returned in structured form.
- [x] Tests cover at least one successful inspection path.

### P2-IT-01 - Local Toolchain Integration Flow

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P2-TOOL-02`, `P2-TOOL-04`, `P2-TOOL-05`
- Branch: `codex/p2-it-01-local-toolchain-flow`
- Owned paths: `tests/`, `packages/agent-tools/`, `packages/agent-runtime/`

#### Goal

Prove the minimum local Phase 2 edit loop with read, patch, validate, and structured results.

#### Deliverables

- integration-style test or smoke flow
- deterministic fixture workspace
- documentation of the validated local loop

#### Acceptance

- [x] The repository proves a local `read -> patch -> validate -> return result` flow.
- [x] Integration coverage uses the real runtime and builtin tools.
- [x] Validation evidence is recorded in the work log or PR.

## Notes

- Historical Phase 0 task plans from older docs are no longer the active task registry.
- New tasks should be added using `TASK_CARD_TEMPLATE.md` and must align with the active execution set.

## Phase 3 Task Board

### P3-HAR-01 - Harness Loop Skeleton

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `Phase 2 completed`
- Branch: `codex/p3-har-01-loop-skeleton`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Implement the smallest harness loop skeleton that can accept a task, hold state, and coordinate one tool-capable attempt.

#### Deliverables

- loop entrypoint
- task or attempt state model
- stopping condition skeleton
- deterministic tests for one minimal run

#### Acceptance

- [x] The repo has a typed harness loop entrypoint.
- [x] One minimal loop path is covered by deterministic tests.
- [x] The implementation does not hardcode infrastructure concerns into domain models.

### P3-MOD-01 - Mock Model Gateway

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-01`
- Branch: `codex/p3-mod-01-mock-model-gateway`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Provide the first mock model gateway path so the harness can be exercised without a real provider.

#### Deliverables

- deterministic mock model response contract
- fixture or scripted response path
- tests for harness-model interaction

#### Acceptance

- [x] The harness can consume a deterministic mock model output.
- [x] Tests cover at least one tool call planning path.
- [x] No real network model dependency is introduced.

### P3-HAR-02 - Single Attempt Tool Orchestration

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-01`, `P3-MOD-01`
- Branch: `codex/p3-har-02-single-attempt-orchestration`
- Owned paths: `packages/agent-core/`, `packages/agent-tools/`, `tests/`

#### Goal

Wire the harness, tool gateway, runtime, and policy boundary into one single-attempt execution path.

#### Deliverables

- one request-to-tool-run orchestration path
- structured tool result handling
- tests for one successful and one failed attempt

#### Acceptance

- [x] One model-driven tool execution path runs end to end.
- [x] Tool results are fed back into harness state deterministically.
- [x] Tests cover one success case and one failure case.

### P3-HAR-03 - Structured Run Output And Retry Skeleton

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-02`
- Branch: `codex/p3-har-03-run-output-retry`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Add the first structured run output contract and a minimal retry skeleton so the harness can report one failed attempt and decide whether another attempt is allowed.

#### Deliverables

- run result model
- retry eligibility or stopping helper
- tests for stop vs retry decisions

#### Acceptance

- [x] Harness run output is structured and typed.
- [x] Retry or stop decisions are deterministic.
- [x] Tests cover both retryable and terminal outcomes.

### P3-HAR-04 - Multi-Attempt Loop Driver

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-03`
- Branch: `codex/p3-har-04-multi-attempt-loop`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Extend the harness loop from one attempt to a minimal multi-attempt driver that stops on success or when retry budget is exhausted.

#### Deliverables

- multi-attempt loop driver
- retry iteration state handling
- tests for success-after-retry and exhausted retry paths

#### Acceptance

- [x] The harness can run more than one attempt when retry is allowed.
- [x] Success stops further attempts immediately.
- [x] Tests cover at least one retry success path and one exhaustion path.

### P3-HAR-05 - Assistant Message And Tool Trace Projection

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-04`
- Branch: `codex/p3-har-05-trace-projection`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Expose a more useful structured harness trace by projecting assistant messages, tool proposals, and tool results into a compact run-facing model.

#### Deliverables

- run trace model
- projection helper from emitted events or attempt results
- tests for projected assistant and tool trace data

#### Acceptance

- [x] Harness run output exposes assistant and tool trace data in a typed form.
- [x] Projection logic is deterministic.
- [x] Tests cover both successful and failed tool paths.

### P3-HAR-06 - Attempt Event Timestamp Refinement

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-05`
- Branch: `codex/p3-har-06-attempt-timestamps`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Refine harness event timing so multi-attempt runs no longer stamp every event with the same timestamp and can model per-attempt timing more accurately.

#### Deliverables

- per-attempt timestamp strategy
- deterministic time source usage
- tests for ordered timestamps across attempts

#### Acceptance

- [x] Harness event timing is explicit and deterministic.
- [x] Multi-attempt traces show sensible per-attempt time progression.
- [x] Tests cover timestamp ordering across attempts.

### P3-HAR-07 - Planner And Verifier Hooks

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-06`
- Branch: `codex/p3-har-07-planner-verifier-hooks`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Introduce minimal planner and verifier hook contracts so the harness loop can separate “model proposes work” from “post-tool verification”.

#### Deliverables

- planner hook contract
- verifier hook contract
- tests for planner and verifier participation in one run

#### Acceptance

- [x] Harness has explicit planner and verifier hook points.
- [x] Hook participation is deterministic and typed.
- [x] Tests cover at least one planner/verifier assisted run path.

### P3-HAR-08 - Session Event Builder Cleanup

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-07`
- Branch: `codex/p3-har-08-event-builder-cleanup`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Reduce repeated event-construction code inside the harness by extracting a dedicated event builder or recorder helper.

#### Deliverables

- harness event builder helper
- loop and orchestration call-site cleanup
- tests proving no behavioral regression

#### Acceptance

- [x] Harness event creation logic is centralized.
- [x] Existing harness behavior remains unchanged.
- [x] Tests cover the refactored event builder path.

### P3-HAR-09 - Tool Call Selection Strategy

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-08`
- Branch: `codex/p3-har-09-tool-call-selection`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Make tool selection explicit by extracting the current “first tool call wins” behavior into a typed selection strategy that can evolve later.

#### Deliverables

- tool selection strategy contract
- default selector implementation
- tests for deterministic selection behavior

#### Acceptance

- [x] Tool selection is expressed through an explicit strategy.
- [x] Default behavior remains deterministic.
- [x] Tests cover at least one multi-tool completion path.

### P3-HAR-10 - Explicit Harness Budgets

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-09`
- Branch: `codex/p3-har-10-explicit-budgets`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Make the Phase 3 harness loop expose explicit model/tool call budgets and stop deterministically when those budgets are exhausted.

#### Deliverables

- typed harness task budget fields
- stopping policy support for model/tool call budgets
- tests for deterministic budget exhaustion behavior
- one mock harness smoke path covering the closed loop

#### Acceptance

- [x] Harness task shape exposes explicit model/tool call budgets.
- [x] Run results report budget usage and deterministic stop reasons.
- [x] Tests cover at least one exhausted budget path.
- [x] The repo has at least one mock harness smoke test covering the main loop.

## Phase 4 Task Board

### P4-STO-01 - SQLite Event Store And Session Projection

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P3-HAR-10`
- Branch: `codex/p4-sto-01-sqlite-event-store`
- Owned paths: `packages/agent-storage/`, `pyproject.toml`, `tests/`, `README.md`

#### Goal

Stand up the first durable storage slice by adding a local SQLite event store and a matching session projection store that can replay one session stream.

#### Deliverables

- `agent-storage` workspace package
- SQLite event append and per-session read path
- SQLite session projection save and get path
- tests for ordered replay and duplicate-sequence rejection

#### Acceptance

- [x] Session events can be appended and read back in sequence order.
- [x] Duplicate sequence writes for one session are rejected.
- [x] A stored event stream can be replayed back into a `Session` projection.
- [x] The storage package is wired into the workspace and smoke imports.
