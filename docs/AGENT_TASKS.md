# AGENT_TASKS.md

> This is the active executable task registry for Zebra Agent.
> Status, owner, branch, and evidence must be maintained by humans.
> Current execution range: Phase 5 in progress; context-compiler MVP is landing on top of the completed durable control-plane baseline from `实施任务拆解与阶段验收.md`.

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

### P4-STO-02 - Event Idempotency Protection

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-STO-01`
- Branch: `codex/p4-sto-02-event-idempotency`
- Owned paths: `packages/agent-storage/`, `tests/`

#### Goal

Add deterministic idempotency protection to the SQLite event store so retried tool-side event submissions do not create duplicate durable records.

#### Deliverables

- session-level idempotency key uniqueness in SQLite
- idempotent append behavior for retried writes
- tests covering duplicate idempotency-key retry behavior

#### Acceptance

- [x] A repeated event submission with the same session-scoped idempotency key does not create a second row.
- [x] `append()` returns the existing durable event for an idempotent retry.
- [x] Existing sequence-conflict protection remains intact.

### P4-WKR-01 - Worker Recovery Entry

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-STO-02`
- Branch: `codex/p4-wkr-01-recovery-entry`
- Owned paths: `apps/worker/`, `tests/`

#### Goal

Add the first worker-side recovery entry that can rebuild a durable session from stored events and persist the rebuilt projection for later inspection.

#### Deliverables

- worker recovery service
- durable session replay from event store
- projection persistence after recovery
- tests for recoverable, terminal, and missing-session paths

#### Acceptance

- [x] Worker can rebuild a session from stored events.
- [x] Recovered session projection is written back to the projection store.
- [x] Missing-session recovery fails deterministically.
- [x] Tests cover at least one interrupted-running session and one terminal session.

### P4-SCH-01 - SQLite Worker Leases

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-WKR-01`
- Branch: `codex/p4-sch-01-sqlite-worker-leases`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `tests/`

#### Goal

Add the minimum durable lease mechanism so workers can claim, heartbeat, and release session ownership without relying on in-memory coordination.

#### Deliverables

- core lease model and port
- SQLite lease store implementation
- tests for acquire, heartbeat, expiry takeover, and release

#### Acceptance

- [x] One worker can acquire a lease for a session.
- [x] A second worker cannot steal an unexpired lease.
- [x] An expired lease can be reacquired deterministically.
- [x] Heartbeat and release behavior are covered by tests.

### P4-WKR-02 - Worker Claim And Resume Flow

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-SCH-01`
- Branch: `codex/p4-wkr-02-claim-resume`
- Owned paths: `apps/worker/`, `tests/`

#### Goal

Combine session recovery and durable leases into a minimal claim/resume flow so a worker can safely take ownership of a resumable session and continue from the latest checkpoint.

#### Deliverables

- worker claim service
- claim heartbeat and release helpers
- tests for concurrent claim blocking and expired-lease takeover

#### Acceptance

- [x] Worker can claim a running session and receive both recovery state and lease state.
- [x] Concurrent claim attempts are blocked while the lease is active.
- [x] Another worker can take over after lease expiry.
- [x] Tests cover heartbeat and release behavior in the claim flow.

### P4-GOV-01 - Core Event Schema Drafts

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-WKR-02`
- Branch: `codex/p4-gov-01-event-schema-drafts`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Define the first machine-checkable payload schema drafts for the most critical durable events so worker, storage, and future API layers share the same event contract baseline.

#### Deliverables

- versioned event contract module
- payload schema generation for core durable events
- payload validation helpers and contract tests

#### Acceptance

- [x] `SessionCreated`, `UserMessageReceived`, and `ToolExecutionCompleted` have machine-checkable payload schemas.
- [x] Unknown fields are rejected for covered event payloads.
- [x] Tests cover schema generation and validation failure behavior.

### P4-GOV-02 - Event Schema Enforcement

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-GOV-01`
- Branch: `codex/p4-gov-02-event-schema-enforcement`
- Owned paths: `packages/agent-core/`, `tests/`

#### Goal

Move covered event payload schemas from passive documentation/testing into the actual event creation path so invalid durable payloads are rejected before they hit storage.

#### Deliverables

- schema validation hook inside `SessionEvent.create`
- tests for covered-event rejection and uncovered-event passthrough

#### Acceptance

- [x] Covered events validate payloads during event creation.
- [x] Invalid payloads fail before persistence.
- [x] Uncovered events still pass through unchanged until their schema is defined.

### P4-STO-03 - Incremental Event Replay

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-GOV-02`
- Branch: `codex/p4-sto-03-incremental-replay`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `apps/worker/`, `tests/`

#### Goal

Let recovery paths resume from the latest stored projection by replaying only events after the last known sequence, instead of rebuilding every session from scratch.

#### Deliverables

- event store `read_since` contract
- SQLite incremental event read implementation
- recovery path that applies only delta events on top of a stored projection
- tests for checkpointed replay

#### Acceptance

- [x] Event store can read only events after a given sequence.
- [x] Recovery can resume from a stored projection and apply only newer events.
- [x] Tests cover both event-store delta reads and projection-based resume.

### P4-WKR-03 - Explicit Resume Entry

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-STO-03`
- Branch: `codex/p4-wkr-03-explicit-resume`
- Owned paths: `apps/worker/`, `tests/`

#### Goal

Expose a single worker-facing resume entry that combines claim and recovery semantics and refuses to resume terminal sessions.

#### Deliverables

- worker resume service
- terminal-session guard
- tests for resumable vs terminal sessions

#### Acceptance

- [x] Worker can resume a running session through one entrypoint.
- [x] Terminal sessions are rejected deterministically.
- [x] Rejected terminal resumes do not leave dangling leases.

### P4-STO-04 - Tool Run Index

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-WKR-03`
- Branch: `codex/p4-sto-04-tool-run-index`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `apps/worker/`, `tests/`

#### Goal

Expose a durable tool-run index so control-plane queries do not need to scan raw event payloads for every tool execution detail.

#### Deliverables

- core tool-run record model and store port
- SQLite tool-run store
- worker-side event-to-index mapping for tool execution events

#### Acceptance

- [x] Tool run records can be upserted and queried by session.
- [x] Tool execution events can be projected into tool-run records.
- [x] Tests cover storage upsert and worker-side indexing behavior.

### P4-STO-05 - Model Call Index

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CORE`
- Depends on: `P4-STO-04`
- Branch: `codex/p4-sto-05-model-call-index`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a durable model-call index so control-plane queries can inspect provider, model, usage, latency, cache, and cost data without rescanning raw session events.

#### Deliverables

- core model-call record model and store port
- model completion metadata carried through the harness response event
- SQLite model-call store
- worker-side event-to-index mapping for model response events

#### Acceptance

- [x] Model call records can be upserted and queried by session.
- [x] `MODEL_RESPONSE_RECEIVED` events carry enough metadata to index provider, model, usage, latency, cache, and cost fields.
- [x] Tests cover storage upsert, harness event emission, and worker-side indexing behavior.

## Phase 5 Task Board

### P5-CTX-01 - Context Compiler Bootstrap

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P4-STO-05`
- Branch: `codex/p5-ctx-01-context-bootstrap`
- Owned paths: `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Replace the `agent-context` placeholder with the first deterministic context compiler slice that can scan a workspace, emit typed context items with provenance, and trim the result to a token budget.

#### Deliverables

- typed context item, provenance, request, and budget models
- deterministic workspace scan and repo-map bootstrap
- basic ranking for key files and task-related files
- token-budget trimming behavior with tests

#### Acceptance

- [x] Given a task input and workspace root, the compiler returns a stable ordered list of context items.
- [x] Every context item exposes provenance information.
- [x] The compiler enforces a token budget and reports truncation.
- [x] Tests cover ranking/provenance behavior and budget trimming.

### P5-CTX-02 - Related Files Recall And Ranking Split

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-01`
- Branch: `codex/p5-ctx-02-related-files`
- Owned paths: `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Split the bootstrap compiler into smaller ranking and scanning modules, and add the first deterministic related-files recall path so context assembly can surface local dependency neighbors instead of only directly matched files.

#### Deliverables

- dedicated scanner and ranker modules
- local python import-based related-files recall
- explicit related-file context item kind
- tests covering related-file inclusion

#### Acceptance

- [x] Context ranking logic is split out of `compiler.py`.
- [x] The compiler can emit related-file items for directly matched Python files.
- [x] Related-file items preserve provenance and participate in token-budget trimming.
- [x] Tests cover at least one local import-driven related-file recall path.

### P5-CTX-03 - Conversation And Tool Output Compaction

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-02`
- Branch: `codex/p5-ctx-03-context-compaction`
- Owned paths: `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first typed compaction layer for session summaries and tool-output summaries so the context package can preserve the required operator state under a smaller token budget.

#### Deliverables

- conversation compaction request and output types
- tool-output compaction request and output types
- deterministic truncation behavior under token limits
- tests for required summary sections and truncation

#### Acceptance

- [x] Conversation compaction preserves the required session summary sections.
- [x] Tool-output compaction produces a compact, typed summary item.
- [x] Both compaction paths respect a token budget.
- [x] Tests cover section preservation, output summarization, and truncation behavior.

### P5-CTX-04 - Prompt Layout And Cache Key Rules

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-03`
- Branch: `codex/p5-ctx-04-prompt-layout-cache-key`
- Owned paths: `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define the first deterministic prompt layout and cache-key rules so compiled context can be partitioned into stable, semi-stable, and dynamic sections and hashed consistently against the model/policy/tool envelope.

#### Deliverables

- prompt section and layout types
- stable / semi-stable / dynamic classification rules
- deterministic prompt cache key builder
- tests for section routing and cache-key stability or invalidation

#### Acceptance

- [x] Prompt layout groups context into stable, semi-stable, and dynamic sections.
- [x] Cache-key generation is deterministic for identical inputs.
- [x] Cache-key generation changes when tool-manifest inputs change.
- [x] Tests cover section routing and cache-key stability behavior.

### P5-CTX-05 - Trust Marking And Prompt-Injection Baseline

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-04`
- Branch: `codex/p5-ctx-05-trust-marking`
- Owned paths: `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first trust-level and prompt-injection baseline markers to context items so downstream layout and policy code can distinguish trusted project guidance from untrusted code and suspicious content.

#### Deliverables

- trust-level model on context items
- baseline trust assignment for repo map, project guidance, dynamic summaries, and code files
- suspicious-pattern metadata for prompt-injection-like content
- tests covering trusted vs untrusted item marking

#### Acceptance

- [x] Context items expose a trust-level field.
- [x] Stable project-guidance files are marked above untrusted code files.
- [x] Suspicious prompt-injection-like content is marked in item metadata.
- [x] Tests cover baseline trust assignment and suspicious-content marking.

### P5-CTX-06 - Harness Context Input Wiring

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-05`
- Branch: `codex/p5-ctx-06-harness-context-input`
- Owned paths: `packages/agent-core/`, `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire compiled context into the harness model request path without breaking package boundaries by defining a core-side context-compiler port and a local context adapter in `agent-context`.

#### Deliverables

- `ContextCompilerPort` in `agent-core`
- harness task fields for workspace root and context budget
- `HarnessModelStep` system-message injection path
- local `agent-context` adapter that renders compiled context into a prompt

#### Acceptance

- [x] `agent-core` consumes context compilation only through an abstract port.
- [x] Harness model requests can include a compiled context system message.
- [x] `agent-context` provides a local adapter that renders a prompt from compiled context.
- [x] Tests cover system-message injection and adapter rendering.

### P5-CTX-07 - Runtime Evidence Context Injection

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-06`
- Branch: `codex/p5-ctx-07-runtime-evidence-context`
- Owned paths: `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Let the context compiler accept compacted runtime evidence so conversation summaries and tool-output summaries can re-enter the compiled context set and flow into the dynamic prompt section under the same token budget rules.

#### Deliverables

- runtime-evidence items on `ContextCompileRequest`
- validation that only compacted dynamic items can be injected this way
- tests covering compiled-context inclusion and dynamic-section routing

#### Acceptance

- [x] `compile_context` can accept compacted conversation and tool-output items.
- [x] Runtime evidence participates in normal token-budget trimming.
- [x] Prompt layout routes runtime evidence into the dynamic section.
- [x] Tests cover runtime-evidence inclusion and prompt-layout routing.

### P5-CTX-08 - Attempt Evidence Feedback Loop

- Status: `Done`
- Owner: `UNASSIGNED`
- Suggested role: `CTX`
- Depends on: `P5-CTX-07`
- Branch: `codex/p5-ctx-08-attempt-evidence-feedback`
- Owned paths: `packages/agent-core/`, `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Feed prior attempt evidence into later attempts by accumulating runtime evidence inside the harness loop and passing it through the abstract context-compiler port on retry attempts.

#### Deliverables

- core runtime-evidence input model
- harness-loop accumulation of prior attempt summaries and tool-output evidence
- local context adapter support for abstract runtime-evidence inputs
- tests covering retry-time evidence propagation

#### Acceptance

- [x] Retry attempts receive prior attempt runtime evidence through the harness task shape.
- [x] The context-compiler port can accept abstract runtime-evidence inputs.
- [x] The local context adapter renders runtime-evidence inputs into dynamic context items.
- [x] Tests cover retry-time evidence propagation and adapter rendering.

### P5-CTX-09 - Structured Planner And Verifier Evidence

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P5-CTX-08`
- Branch: `codex/p5-ctx-09-structured-evidence`
- Owned paths: `packages/agent-core/`, `packages/agent-context/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Promote planner, verifier, and tool-status outputs from opaque conversation-summary details into structured runtime evidence so retry attempts can distinguish planning signals from verification failures and tool-output artifacts.

#### Deliverables

- runtime-evidence metadata on the core context-compiler input contract
- harness extraction of planner, verifier, tool-status, and tool-output evidence as distinct evidence kinds
- local context adapter mapping that folds planner summaries and verifier outcomes into conversation compaction fields
- tests covering structured evidence propagation and rendered retry context

#### Acceptance

- [x] Prior-attempt planner summaries are carried as `planner_summary` runtime evidence.
- [x] Prior-attempt verifier results are carried as `verifier_summary` runtime evidence with pass/fail metadata.
- [x] Tool status and tool output remain separate runtime evidence kinds.
- [x] The local context adapter renders planner summaries and verifier failures into retry context.

### P5-CTX-10 - Context-Aware Retry Plan Hint

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P5-CTX-09`
- Branch: `codex/p5-ctx-10-context-aware-retry-plan`
- Owned paths: `packages/agent-core/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a deterministic core retry-planning projection that turns structured runtime evidence into planner-facing guidance without introducing infrastructure dependencies or coupling `agent-core` to `agent-context`.

#### Deliverables

- retry-plan hint model and builder in `agent-core`
- default planner behavior that uses retry hints when prior runtime evidence exists
- tests covering evidence grouping and default planner retry metadata

#### Acceptance

- [x] Planner summaries become retry focus signals.
- [x] Failed verifier summaries and failed tool statuses become retry blockers.
- [x] Passed verifier summaries become accepted constraints.
- [x] Default planner metadata exposes retry focus, blockers, accepted constraints, and prior tool outputs.

### P5-CTX-11 - Context Compiler Acceptance Hardening

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P5-CTX-10`
- Branch: `codex/p5-ctx-11-context-acceptance-hardening`
- Owned paths: `packages/agent-context/`, `tests/agent_context/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Harden context compiler input acceptance so invalid workspaces and spoofed runtime evidence are rejected before scanning or prompt assembly.

#### Deliverables

- workspace root existence and directory validation on `ContextCompileRequest`
- runtime-evidence kind and provenance source allowlist
- tests covering invalid workspace roots and rejected file-sourced runtime evidence

#### Acceptance

- [x] Missing workspace roots are rejected.
- [x] File paths are rejected as workspace roots.
- [x] Runtime evidence is limited to conversation/tool-output summary kinds.
- [x] Runtime evidence must come from session projection or tool trace provenance.

### P5-CTX-12 - Phase 5 Closeout Record

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOCS`
- Depends on: `P5-CTX-11`
- Branch: `codex/p5-ctx-12-phase5-closeout`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 5 by recording the context-compiler acceptance evidence, known deferrals, and the next phase boundary before Phase 6 policy work begins.

#### Deliverables

- Phase 5 acceptance record under `docs/`
- task registry update for the closeout slice
- project progress update moving the repository to Phase 6 ready state

#### Acceptance

- [x] Acceptance record maps Phase 5 criteria to implemented code paths.
- [x] Validation commands and results are recorded.
- [x] Known deferrals are explicit.
- [x] `PROGRESS.md` identifies Phase 6 as the next active implementation phase.

## Phase 6 Task Board

### P6-POL-01 - Local Policy Profiles

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P5-CTX-12`
- Branch: `codex/p6-pol-01-policy-profiles`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `tests/smoke/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Replace the security package bootstrap placeholder with deterministic local policy profiles for read-only, workspace-write, and full-access tool-call decisions.

#### Deliverables

- `PolicyProfile` values for `read_only`, `workspace_write`, and `full_access`
- `LocalPolicyEngine` implementing the core `PolicyEnginePort` shape
- profile rules for readonly tools, workspace write tools, command approval, full-access known tools, and unknown-tool denial
- tests covering profile decisions and bootstrap compatibility

#### Acceptance

- [x] `read_only` allows readonly tools and denies write/command tools.
- [x] `workspace_write` allows patch/test tools and requires approval for generic command execution.
- [x] `full_access` allows known local tools.
- [x] unknown tools are denied for all profiles.
- [x] existing bootstrap smoke import remains compatible.

### P6-POL-02 - Command Risk Rules

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P6-POL-01`
- Branch: `codex/p6-pol-02-command-risk-rules`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `tests/smoke/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add parameter-aware command risk rules so `command.run` is not allowed solely by tool name when its arguments indicate shell execution or shell-injection risk.

#### Deliverables

- command argument inspection in `LocalPolicyEngine`
- approval decisions for shell interpreters, shell metacharacters, and malformed command arguments
- tests covering safe command allow and high-risk command approval

#### Acceptance

- [x] `full_access` allows typed safe command arrays.
- [x] shell interpreter commands require approval.
- [x] commands containing shell metacharacters require approval.
- [x] malformed command arguments require approval.

### P6-POL-03 - Path Risk Rules

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P6-POL-02`
- Branch: `codex/p6-pol-03-path-risk-rules`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `tests/smoke/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add policy-level path traversal checks so obvious workspace escape attempts are rejected before tool-specific runtime validation.

#### Deliverables

- path argument inspection for `files.read`, `git.status`, and `command.run`
- patch header path inspection for `patch.apply`
- tests covering relative traversal, absolute path usage, and patch traversal

#### Acceptance

- [x] `files.read` rejects `..` traversal paths.
- [x] `command.run` rejects absolute `cwd` paths before profile allow/approval logic.
- [x] `patch.apply` rejects patch headers that escape the workspace.
- [x] existing profile and smoke tests remain compatible with safe path arguments.

### P6-POL-04 - Sensitive Output Rules

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P6-POL-03`
- Branch: `codex/p6-pol-04-sensitive-output-rules`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `tests/smoke/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add policy-level approval rules for obvious sensitive data exfiltration risk before command execution reaches the runtime.

#### Deliverables

- sensitive path marker detection in `command.run`
- network-capable data-transfer command detection
- tests covering `.env`, private key, and upload-style command references

#### Acceptance

- [x] commands referencing `.env` paths require approval.
- [x] commands referencing private key paths require approval.
- [x] network-capable data-transfer commands require approval.
- [x] existing profile and path traversal tests remain compatible.

### P6-POL-05 - Approval Request Model

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P6-POL-04`
- Branch: `codex/p6-pol-05-approval-request-model`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `tests/smoke/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a typed approval request projection so policy decisions that require approval can expose risk, reason, and scope without changing the core policy decision schema.

#### Deliverables

- `ApprovalRisk` and `ApprovalRequest` models
- `build_approval_request` projection helper
- approval scope extraction for command tool calls
- tests covering non-approval, medium-risk command approval, and high-risk sensitive transfer approval

#### Acceptance

- [x] allow/deny decisions do not produce approval requests.
- [x] approval requests include tool name, policy profile, reason, risk, and scope.
- [x] sensitive transfer approvals are marked high risk.
- [x] command approvals include executable and cwd scope when available.

### P6-POL-06 - Approval Event Wiring

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P6-POL-05`
- Branch: `codex/p6-pol-06-approval-event-wiring`
- Owned paths: `packages/agent-core/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire `REQUIRE_APPROVAL` policy decisions into explicit harness events so approval-needed tool calls are distinguishable from hard policy denial.

#### Deliverables

- `APPROVAL_REQUESTED` event emission in the single-attempt orchestrator
- attempt summary and metadata that preserve `require_approval`
- session transition support for the current local-MVP terminal approval path
- tests covering approval event emission and no tool execution

#### Acceptance

- [x] `REQUIRE_APPROVAL` emits `APPROVAL_REQUESTED`.
- [x] approval-required tool calls do not execute the tool gateway.
- [x] attempt metadata records `policy_decision=require_approval`.
- [x] session projection can handle the current approval-request-to-failed terminal path.

### P6-POL-07 - Approval Decision Projection

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P6-POL-06`
- Branch: `codex/p6-pol-07-approval-decision-projection`
- Owned paths: `packages/agent-core/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define deterministic session projection semantics for approval grant and rejection events before adding a service endpoint for approval decisions.

#### Deliverables

- `APPROVAL_REJECTED` projection to terminal failed state
- tests covering approval-request-to-granted and approval-request-to-rejected event streams
- progress and task registry updates for approval decision projection

#### Acceptance

- [x] `APPROVAL_GRANTED` moves a waiting approval session back to running.
- [x] `APPROVAL_REJECTED` moves a waiting approval session to failed.
- [x] approval decision event streams preserve current sequence.
- [x] existing event contract and session tests remain compatible.

### P6-POL-08 - Approval Service Entry

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P6-POL-07`
- Branch: `codex/p6-pol-08-approval-service-entry`
- Owned paths: `packages/agent-core/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a local application service entry for approval decisions so API or worker layers can reuse one deterministic event-building path.

#### Deliverables

- `ApprovalDecisionAction`
- `ApprovalDecisionCommand`
- `ApprovalDecisionService`
- tests covering grant, reject, non-waiting session rejection, and sequence validation

#### Acceptance

- [x] grant commands build `APPROVAL_GRANTED` events.
- [x] reject commands build `APPROVAL_REJECTED` events.
- [x] approval decisions require a `WAITING_APPROVAL` session.
- [x] approval decision event sequence must follow the current session sequence.

### P6-POL-09 - Phase 6 Closeout Record

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOCS`
- Depends on: `P6-POL-08`
- Branch: `codex/p6-pol-09-phase6-closeout`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 6 by recording policy and approval hardening evidence, known deferrals, and the next phase boundary before eval and observability work begins.

#### Deliverables

- Phase 6 acceptance record under `docs/`
- task registry update for the closeout slice
- project progress update moving the repository to Phase 7 ready state

#### Acceptance

- [x] Acceptance record maps Phase 6 criteria to implemented code paths.
- [x] Validation commands and results are recorded.
- [x] Deferred MCP, egress, credential, and API-adapter work is explicit.
- [x] `PROGRESS.md` identifies Phase 7 as the next active implementation phase.

## Phase 7 Task Board

### P7-OBS-01 - Observability Models Bootstrap

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P6-POL-09`
- Branch: `codex/p7-obs-01-observability-models`
- Owned paths: `packages/agent-observability/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `pyproject.toml`, `uv.lock`

#### Goal

Bootstrap the observability package with deterministic local trace, audit, and cost summary models before adding storage, replay, or eval runners.

#### Deliverables

- `agent-observability` workspace package
- trace record model for session event streams
- audit record and cost summary models
- tests covering event counts, tool result counts, model cost aggregation, empty streams, mixed sessions, and negative costs

#### Acceptance

- [x] Session event streams can produce a typed trace record.
- [x] Trace records include event count, tool result count, audit records, and cost summary.
- [x] Trace building rejects empty and mixed-session streams.
- [x] Cost summary rejects negative values.

### P7-OBS-02 - Local Trace JSONL Store

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P7-OBS-01`
- Branch: `codex/p7-obs-02-local-trace-store`
- Owned paths: `packages/agent-observability/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a local JSONL trace store so trace records can be persisted and read back before implementing replay runners or remote observability backends.

#### Deliverables

- `JsonlTraceStore`
- JSON serialization for trace, cost, and audit records
- tests covering append/list, missing store files, and invalid directory paths

#### Acceptance

- [x] Trace records can be appended to a JSONL file.
- [x] Stored trace records can be read back in insertion order.
- [x] Missing store files return an empty list.
- [x] Directory paths are rejected.

### P7-OBS-03 - Local Replay Runner

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P7-OBS-02`
- Branch: `codex/p7-obs-03-local-replay-runner`
- Owned paths: `packages/agent-observability/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a deterministic local replay runner that can read persisted trace records and summarize historical task execution without introducing remote observability or eval services.

#### Deliverables

- `LocalReplayRunner`
- `ReplayResult`
- store replay path for JSONL trace history
- tests covering single trace replay, store replay order, empty stores, and invalid zero-event traces

#### Acceptance

- [x] A persisted historical trace can be replayed into a typed result.
- [x] Replay results preserve session id, event count, tool result count, audit step count, model calls, tokens, and cost.
- [x] Store replay returns results in trace insertion order.
- [x] Empty stores return no replay results.
- [x] Zero-event traces are rejected.

### P7-EVAL-01 - Eval Case And Grader Bootstrap

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P7-OBS-03`
- Branch: `codex/p7-eval-01-case-grader-bootstrap`
- Owned paths: `packages/agent-observability/`, `tests/agent_observability/`, `evals/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Create the first local eval case directory and deterministic grader so Phase 7 has a minimal regression dataset before adding eval runners or release gates.

#### Deliverables

- `EvalCase`
- `EvalGrade`
- `LocalEvalGrader`
- `load_eval_cases`
- initial local JSON eval cases under `evals/cases/`
- tests covering grading pass/fail, case loading, and invalid case definitions

#### Acceptance

- [x] Eval cases can be loaded from the repository case directory.
- [x] The grader produces typed pass/fail results from replay summaries.
- [x] The initial dataset includes bugfix, security, and recovery cases.
- [x] Invalid case inputs are rejected.

### P7-EVAL-02 - Local Eval Runner

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P7-EVAL-01`
- Branch: `codex/p7-eval-02-local-runner`
- Owned paths: `packages/agent-observability/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a deterministic local eval runner that combines loaded eval cases, replay summaries, and grader output before adding CLI integration or release gates.

#### Deliverables

- `EvalRunResult`
- `LocalEvalRunner`
- tests covering ordered grading, aggregate pass metrics, missing replay failures, and empty case rejection

#### Acceptance

- [x] Eval cases can be graded against replay results in deterministic order.
- [x] Eval run results expose total count, pass count, all-pass status, and average score.
- [x] Missing replay results are explicit failures.
- [x] Empty eval runs are rejected.

### P7-EVAL-03 - Baseline Eval Case Expansion

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P7-EVAL-02`
- Branch: `codex/p7-eval-03-baseline-cases`
- Owned paths: `evals/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand the local MVP eval dataset so Phase 7 covers the documented bugfix, refactor, recovery, security, and analysis baseline lanes before release gate wiring.

#### Deliverables

- additional JSON eval cases under `evals/cases/`
- baseline coverage test for case count and category coverage

#### Acceptance

- [x] The local eval dataset includes at least eight cases.
- [x] The dataset includes bugfix, refactor, recovery, security, and analysis categories.
- [x] The added cases cover TypeScript type errors, cross-file refactor, unrelated diff control, dependency lock constraints, and analysis-only diagnosis.

### P7-EVAL-04 - Local Release Gate Baseline

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P7-EVAL-03`
- Branch: `codex/p7-eval-04-release-gate`
- Owned paths: `packages/agent-observability/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a local release gate decision layer that can evaluate eval run results before CLI integration or release automation.

#### Deliverables

- `ReleaseGatePolicy`
- `ReleaseGateResult`
- `LocalReleaseGate`
- tests covering pass, threshold failures, empty eval results, and invalid thresholds

#### Acceptance

- [x] Release gate evaluates eval pass rate and average score.
- [x] Passing eval runs produce a passing gate result.
- [x] Failed thresholds produce explicit reasons.
- [x] Empty eval results fail closed.
- [x] Invalid gate thresholds are rejected.

### P7-EVAL-05 - Eval Release Check Integration

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P7-EVAL-04`
- Branch: `codex/p7-eval-05-check-integration`
- Owned paths: `scripts/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `Makefile`

#### Goal

Wire the local eval release gate into the repository validation path so Phase 7 has a concrete pre-release check command.

#### Deliverables

- `scripts/eval_release_check.py`
- `make eval`
- `make check` eval release gate step
- tests covering the baseline release check output

#### Acceptance

- [x] `make eval` runs the local eval release check.
- [x] `make check` includes the eval release check.
- [x] The baseline dataset passes the local release gate.
- [x] The check prints pass rate, average score, and case count.

### P7-EVAL-06 - Phase 7 Closeout Record

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P7-EVAL-05`
- Branch: `codex/p7-eval-06-phase7-closeout`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 7 by recording eval and observability evidence, known deferrals, and the next phase boundary before CLI/API productization begins.

#### Deliverables

- Phase 7 closeout progress update
- validation evidence for trace, replay, eval, and release gate paths
- Phase 8 ready state in project status

#### Acceptance

- [x] `PROGRESS.md` identifies Phase 8 as the next active implementation phase.
- [x] `README.md` reflects Phase 7 closeout and Phase 8 readiness.
- [x] `WORKLOG.md` records Phase 7 closeout validation evidence.

## Phase 8 Task Board

### P8-CLI-01 - CLI Command Skeleton

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P7-EVAL-06`
- Branch: `codex/p8-cli-01-command-skeleton`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a deterministic CLI command skeleton for `run`, `resume`, `inspect`, and `approve` before wiring persistent storage, worker execution, or API calls.

#### Deliverables

- CLI parser and execution result model
- `run` command intent output
- `resume` command intent output
- `inspect` command intent output
- `approve` command intent output
- tests covering all Phase 8 starter CLI commands

#### Acceptance

- [x] `zebra-agent run` can parse prompt, title, and workspace intent.
- [x] `zebra-agent resume` can parse a session id.
- [x] `zebra-agent inspect` can parse a session id.
- [x] `zebra-agent approve` can parse an approval decision.
- [x] CLI command outputs are deterministic and test-covered.

### P8-CLI-02 - CLI Run Local Session Creation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLI-01`
- Branch: `codex/p8-cli-02-run-session-create`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `uv.lock`

#### Goal

Wire `zebra-agent run` to create a local durable session projection while keeping worker execution and model orchestration for later task cards.

#### Deliverables

- `run --database` option
- local `Session.create` composition in CLI
- SQLite projection persistence for newly created sessions
- tests proving `run` output can be read back from the local projection store

#### Acceptance

- [x] `zebra-agent run` creates a local session id.
- [x] Created sessions are persisted to the configured SQLite projection store.
- [x] Run output includes session id, status, prompt, title, workspace, and database path.
- [x] Worker execution remains deferred to later task cards.

### P8-CLI-03 - CLI Inspect And Resume Session Read

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLI-02`
- Branch: `codex/p8-cli-03-session-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire `zebra-agent inspect` and `zebra-agent resume` to read local durable session projections without starting worker execution yet.

#### Deliverables

- `inspect --database` option
- `resume --database` option
- projection-store lookup for session title, status, and sequence
- deterministic missing-session output
- tests covering existing and missing session reads

#### Acceptance

- [x] `zebra-agent inspect` reads an existing local session projection.
- [x] `zebra-agent resume` reads an existing local session projection.
- [x] Missing sessions return deterministic `not_found` output.
- [x] Resume does not mutate session state or start worker execution yet.

### P8-CLI-04 - CLI Approve Local Decision

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLI-03`
- Branch: `codex/p8-cli-04-approve-decision`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire `zebra-agent approve` to local approval decision events and projection updates while preserving fail-closed behavior for invalid session states.

#### Deliverables

- `approve --database` option
- `approve --operator` option
- approval decision event append via `SQLiteEventStore`
- projection update via existing session projection logic
- tests covering granted approvals and invalid session states

#### Acceptance

- [x] `zebra-agent approve --decision approve` records an approval granted event.
- [x] Approval decisions update the local session projection.
- [x] Non-waiting sessions return deterministic `invalid_state` output.
- [x] Invalid decision values are rejected by CLI parsing.

### P8-API-01 - API Health And Session Foundation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLI-04`
- Branch: `codex/p8-api-01-health-session-foundation`
- Owned paths: `apps/api/`, `tests/api/`, `tests/smoke/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `uv.lock`

#### Goal

Add the first API composition root for health checks and local session lookup before adding HTTP framework routing, streaming, or auth.

#### Deliverables

- API app object
- health handler
- session lookup handler backed by `SQLiteProjectionStore`
- tests covering health, existing session lookup, and missing session lookup

#### Acceptance

- [x] API health returns service status.
- [x] API session lookup returns existing session projection data.
- [x] Missing sessions return deterministic 404/not_found output.
- [x] API remains a thin composition layer over storage and core contracts.

### P8-API-02 - API Route Adapter

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-API-01`
- Branch: `codex/p8-api-02-route-adapter`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a concrete local route adapter for API health and session lookup before introducing an HTTP framework, streaming, or auth.

#### Deliverables

- route request model
- route adapter for `GET /health`
- route adapter for `GET /sessions/{session_id}`
- deterministic 404 output for unsupported routes
- tests covering health, session lookup, and unknown routes

#### Acceptance

- [x] `GET /health` routes to the API health handler.
- [x] `GET /sessions/{session_id}` routes to the API session lookup handler.
- [x] Unsupported routes return deterministic 404/not_found output.
- [x] Route adapter remains framework-independent.

### P8-CONFIG-01 - Local Settings Loader

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-API-02`
- Branch: `codex/p8-config-01-local-settings`
- Owned paths: `apps/config/`, `configs/`, `tests/config/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `pyproject.toml`, `uv.lock`

#### Goal

Add local configuration loading and profile/model selection defaults before wiring settings into CLI, API, worker, or model gateway runtime paths.

#### Deliverables

- `zebra-agent-config` workspace app package
- typed settings models
- default local env-style config
- environment override support
- tests covering defaults and overrides

#### Acceptance

- [x] Settings load a local profile and database URL.
- [x] Settings expose model provider, API key env name, base URL, and model name.
- [x] Environment values override repository defaults.
- [x] DeepSeek defaults use `https://api.deepseek.com` and `deepseek-v4-flash`.

### P8-CONFIG-02 - Entry Point Settings Wiring

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CONFIG-01`
- Branch: `codex/p8-config-02-entrypoint-wiring`
- Owned paths: `apps/cli/`, `apps/api/`, `tests/cli/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire local settings into CLI and API composition roots so entry points use the configured database URL by default while preserving explicit operator overrides.

#### Deliverables

- CLI database default resolved through `zebra-agent-config`
- API app database default resolved through `zebra-agent-config`
- app package dependencies on `zebra-agent-config`
- tests covering settings defaults and explicit database overrides

#### Acceptance

- [x] CLI commands use settings database URL when `--database` is omitted.
- [x] CLI explicit `--database` still overrides settings.
- [x] API `create_app()` uses settings database URL when no path is provided.
- [x] API explicit database path still overrides settings.

### P8-API-03 - FastAPI Serving Foundation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CONFIG-02`
- Branch: `codex/p8-api-03-fastapi-serving`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `pyproject.toml`, `uv.lock`

#### Goal

Add the first HTTP framework serving layer on top of the existing API route adapter so local operators can access health and session lookup over ASGI without moving domain logic into FastAPI handlers.

#### Deliverables

- FastAPI dependency wiring for `zebra-agent-api`
- HTTP app factory that delegates requests through `RouteAdapter`
- tests covering health, session lookup, and deterministic not-found behavior over HTTP

#### Acceptance

- [x] HTTP `GET /health` returns the same health payload as the route adapter.
- [x] HTTP `GET /sessions/{session_id}` returns the same session payload as the route adapter.
- [x] Unsupported paths or methods return deterministic `not_found` output.
- [x] FastAPI handlers remain thin adapters over the existing API app and route adapter.

### P8-API-04 - Session Stream Foundation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-API-03`
- Branch: `codex/p8-api-04-session-stream`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first read-only session stream endpoint so operators can replay persisted session events over HTTP before real-time streaming or websocket delivery exists.

#### Deliverables

- API session event listing for one session
- route adapter support for `GET /sessions/{session_id}/stream`
- HTTP SSE response built from persisted session events
- tests covering stream replay, missing sessions, and deterministic path handling

#### Acceptance

- [x] `GET /sessions/{session_id}/stream` replays persisted session events in order.
- [x] Missing sessions return deterministic `not_found` output for the stream path.
- [x] Non-stream session routes remain unchanged.
- [x] Streaming implementation remains a thin adapter over existing API/storage logic.

### P8-DOC-01 - Operator Runbook

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P8-API-04`
- Branch: `codex/p8-doc-01-operator-runbook`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `Makefile`, `pyproject.toml`

#### Goal

Close the remaining Phase 8 operator guidance gap by documenting a runnable local workflow for CLI, HTTP API, and session stream usage.

#### Deliverables

- operator runbook for local CLI/API workflow
- explicit API serve command
- CLI run bootstrap event persistence for stream replay consistency
- README pointer to the runbook
- validation evidence that the documented commands work end to end

#### Acceptance

- [x] Operators have one durable runbook covering setup, CLI usage, API serving, and stream replay.
- [x] The runbook points to executable local commands, not placeholder prose.
- [x] A session created through CLI has a replayable bootstrap event for the stream endpoint.
- [x] README points to the runbook as the current operator entry.
- [x] The documented flow is validated in the current repository state.

### P8-API-05 - Local API Auth Foundation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-DOC-01`
- Branch: `codex/p8-mod-01-openai-compatible-gateway`
- Owned paths: `apps/api/`, `apps/config/`, `configs/`, `tests/api/`, `tests/config/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `pyproject.toml`

#### Goal

Add the first local API auth guard so non-health HTTP routes can require a configured bearer token without introducing a full multi-user auth system yet.

#### Deliverables

- settings support for local API bearer token
- HTTP auth guard for session read and stream endpoints
- tests covering disabled auth, missing token, invalid token, and valid token
- operator docs for local token usage

#### Acceptance

- [x] Health remains accessible without auth.
- [x] When no auth token is configured, current local API behavior remains unchanged.
- [x] When an auth token is configured, session read and stream endpoints require a matching bearer token.
- [x] Auth failures return deterministic HTTP `401` output.

### P8-MOD-01 - OpenAI-Compatible Model Gateway Adapter

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-API-05`
- Branch: `codex/p8-api-05-local-auth`
- Owned paths: `packages/agent-integrations/`, `tests/agent_integrations/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `pyproject.toml`

#### Goal

Add the first real model gateway adapter for OpenAI-compatible chat completions so DeepSeek-backed runtime wiring has a reusable foundation before it is attached to CLI or API execution flows.

#### Deliverables

- new `agent-integrations` workspace package
- OpenAI-compatible HTTP model gateway adapter
- settings-to-gateway factory for current DeepSeek configuration shape
- tests covering request serialization, response parsing, tool-call parsing, and missing API key handling

#### Acceptance

- [x] The adapter can convert core `SessionMessage` inputs into an OpenAI-compatible chat completion request.
- [x] The adapter can parse assistant text, usage, and optional tool calls into `ModelCompletion`.
- [x] Missing configured API keys fail deterministically before any HTTP request.
- [x] The implementation remains isolated from `agent-core` domain rules beyond the existing port contract.
