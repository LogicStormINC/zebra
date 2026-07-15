# AGENT_TASKS.md

> This is the active executable task registry for Zebra Agent.
> Status, owner, branch, and evidence must be maintained by humans.
> Current execution range: Phase 101 closeout is complete; scoped queue-sweep filtered preview evidence is recorded, and the next memory workflow priority is not yet defined.

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

- Status: `Done`
- Owner: `Codex`
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
- Branch: `codex/p8-mod-02-cli-model-smoke`
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

### P8-MOD-02 - CLI Model Gateway Smoke

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-MOD-01`
- Branch: `codex/p8-mod-01-openai-compatible-gateway`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`, `pyproject.toml`

#### Goal

Add a minimal CLI smoke entry that exercises the real model gateway with the current provider settings before folding that path into session execution flows.

#### Deliverables

- CLI command for one-shot model completion
- dependency wiring from CLI to `agent-integrations`
- deterministic JSON output for assistant response and model metadata
- tests covering provider invocation, missing API key failure, and tool-call summary output

#### Acceptance

- [x] CLI can send one prompt through the configured model gateway.
- [x] Output includes assistant response plus provider/model/usage metadata when available.
- [x] Missing API key fails deterministically.
- [x] Existing `run`/`inspect`/`resume`/`approve` behavior remains unchanged.

### P8-CLI-05 - CLI Durable Run Execution

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-MOD-02`
- Branch: `codex/p8-cli-05-run-execute`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extend the local CLI with one explicit durable execution path that creates a session, runs one harness attempt through the configured model gateway, and persists the resulting event stream and projection without changing the existing default `run` bootstrap behavior.

#### Deliverables

- `run --execute` path for one durable harness attempt
- local CLI wiring for model gateway, policy engine, runtime-backed builtin tools, and SQLite persistence
- deterministic CLI JSON output for final status, assistant message, and compact tool trace
- tests covering no-tool completion and one real builtin tool execution path

#### Acceptance

- [x] Default `zebra-agent run` behavior remains session creation only.
- [x] `zebra-agent run --execute` persists the full harness event stream to the local event store.
- [x] The durable execution path can complete with either assistant-only output or one builtin tool execution.
- [x] Final CLI output exposes terminal status and a compact trace without requiring direct database inspection.

### P8-API-06 - API Session Create And Execute

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLI-05`
- Branch: `codex/p8-api-06-session-create-execute`
- Owned paths: `apps/api/`, `apps/cli/`, `packages/agent-runtime/`, `tests/api/`, `tests/cli/`, `tests/agent_runtime/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose the first writable local API session entry by reusing the same durable execution wiring as the CLI while keeping both app entry points as thin composition layers.

#### Deliverables

- shared local harness runner in `agent-runtime`
- API `POST /sessions` path for local session creation with optional immediate execution
- deterministic API response for final session state and compact trace when execution is requested
- tests covering create-only and execute-on-create behavior through app, route adapter, and HTTP layers

#### Acceptance

- [x] CLI durable execution wiring is reused through a shared runtime-side helper instead of app-to-app imports.
- [x] `POST /sessions` can create a durable local session without immediate execution.
- [x] `POST /sessions` with execution enabled persists the full harness event stream and returns terminal status data.
- [x] Existing API read and stream routes remain unchanged.

### P8-QUE-01 - Queued Session Bootstrap Events

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-API-06`
- Branch: `codex/p8-que-01-session-bootstrap-events`
- Owned paths: `apps/api/`, `apps/cli/`, `packages/agent-core/`, `tests/api/`, `tests/cli/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Persist enough durable bootstrap state for create-only sessions so later worker-owned execution can reconstruct the queued task input instead of receiving a session with only `SESSION_CREATED`.

#### Deliverables

- shared core-side session bootstrap service or helper
- durable `SESSION_CREATED` + `USER_MESSAGE_RECEIVED` + `TASK_PREPARED` event emission for queued sessions
- CLI and API create-only flows updated to use the shared bootstrap path
- tests covering event stream contents and ready-to-run session status

#### Acceptance

- [x] Create-only CLI and API session flows persist user input and task-prepared metadata, not just the title.
- [x] Queued sessions land in `ready` state instead of remaining `created`.
- [x] Bootstrap event construction is shared instead of duplicated between app entry points.
- [x] Existing explicit execute flows remain unchanged.

### P8-WKR-04 - Worker Execute Ready Session

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-QUE-01`
- Branch: `codex/p8-wkr-04-execute-ready-session`
- Owned paths: `apps/worker/`, `packages/agent-runtime/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Let the local worker recover a queued `ready` session, execute one harness attempt through the shared local runtime/model wiring, and persist the resulting event stream plus model/tool indexes.

#### Deliverables

- worker-side queued task recovery from durable bootstrap events
- worker execution service for one resumed ready session
- lease release plus projection/model-call/tool-run persistence after execution
- tests covering assistant-only and tool-using worker execution paths

#### Acceptance

- [x] Worker can reconstruct task input from queued bootstrap events.
- [x] Worker can execute one ready session and persist terminal events.
- [x] Model call and tool run indexes update from worker-emitted events.
- [x] Lease state is released after terminal worker execution.

### P8-CLI-06 - CLI Resume Execute Trigger

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-WKR-04`
- Branch: `codex/p8-cli-06-resume-execute`
- Owned paths: `apps/cli/`, `apps/worker/`, `tests/cli/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose the new worker-side ready-session execution capability through an explicit CLI operator entry while preserving the current read-only default behavior of `resume`.

#### Deliverables

- `zebra-agent resume --execute` path
- CLI wiring into the worker execution service with configurable worker identity
- deterministic JSON output for terminal status, assistant message, and tool trace after execution
- tests covering read-only resume, execute resume, and lease/index persistence through the CLI path

#### Acceptance

- [x] Default `zebra-agent resume <id>` remains read-only.
- [x] `zebra-agent resume <id> --execute` runs the queued session through worker execution and persists terminal events.
- [x] CLI output exposes final execution status and compact trace data.
- [x] Existing worker execution tests remain green.

### P8-API-07 - API Resume Execute Trigger

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-WKR-04`
- Branch: `codex/p8-api-07-resume-execute`
- Owned paths: `apps/api/`, `apps/worker/`, `tests/api/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose the worker-backed ready-session execution path through an explicit HTTP resume trigger while preserving the existing `POST /sessions` create semantics.

#### Deliverables

- `POST /sessions/{session_id}/resume` route
- API wiring into the worker execution service with configurable worker identity
- deterministic JSON output for terminal status, assistant message, and tool trace after execution
- tests covering success, auth behavior, invalid payloads, and missing or terminal session handling

#### Acceptance

- [x] Existing `POST /sessions` behavior remains unchanged.
- [x] `POST /sessions/{session_id}/resume` executes a queued ready session through the worker path and persists terminal events.
- [x] API response exposes final execution status, worker id, and compact trace data.
- [x] Auth and invalid-request handling remain deterministic.

### P8-WKR-05 - Worker Ready Session Loop

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-WKR-04`
- Branch: `codex/p8-wkr-05-worker-loop`
- Owned paths: `apps/worker/`, `packages/agent-core/`, `packages/agent-storage/`, `tests/worker/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a minimal long-running worker loop that can discover ready sessions from durable storage and execute them without a manual CLI or HTTP resume trigger.

#### Deliverables

- projection-store support for listing ready sessions deterministically
- worker-side polling loop with configurable batch size and worker identity
- single-cycle and multi-cycle tests covering execution, empty polls, and already-leased sessions
- operator-facing documentation for invoking the worker loop locally

#### Acceptance

- [x] Worker can poll durable storage and return zero work cleanly when no ready sessions exist.
- [x] Worker can claim and execute at least one ready session discovered through the poll loop.
- [x] Active leases prevent a second worker loop from double-executing the same ready session.
- [x] The worker app exposes a stable local operator entry for running the loop.

### P8-INT-01 - Phase 8 Mainline Alignment

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-API-07`, `P8-WKR-05`
- Branch: `codex/p8-int-01-phase8-mainline`
- Owned paths: `apps/api/`, `apps/cli/`, `apps/worker/`, `packages/agent-core/`, `packages/agent-storage/`, `tests/api/`, `tests/cli/`, `tests/worker/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Align the completed Phase 8 resume-trigger and worker-loop slices onto one verified mainline branch so the local productization baseline includes all documented operator entry points together.

#### Deliverables

- one branch containing `P8-CLI-06`, `P8-API-07`, and `P8-WKR-05`
- resolved documentation and runbook updates for the combined Phase 8 operator surface
- regression validation across CLI, API, worker, and storage slices after integration

#### Acceptance

- [x] The branch contains CLI resume execute, API resume execute, and worker ready-session loop together.
- [x] `PROGRESS.md`, `README.md`, and `docs/operator_runbook.md` describe the combined Phase 8 surface without contradiction.
- [x] Integration validation passes for the combined slices.

### P8-CLOSE-01 - Phase 8 Closeout Record

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOCS`
- Depends on: `P8-INT-01`
- Branch: `codex/p8-close-01-phase-closeout`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 8 by recording productization evidence, explicit deferrals, and the next implementation lanes before Phase 9 session-control work begins.

#### Deliverables

- Phase 8 acceptance record under `docs/`
- task registry update for the closeout slice plus next-phase starter tasks
- project progress update moving the repository to Phase 9 ready state

#### Acceptance

- [x] Acceptance record maps Phase 8 criteria to implemented code paths.
- [x] Validation commands and results are recorded.
- [x] Deferred session-control, approval, and commit or PR surface work is explicit.
- [x] `PROGRESS.md` identifies Phase 9 starter tasks as the next active implementation lanes.

## Phase 9 Task Board

### P9-API-01 - Session Messages Entry

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLOSE-01`
- Branch: `codex/p9-api-01-session-messages`
- Owned paths: `apps/api/`, `packages/agent-core/`, `tests/api/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose `POST /sessions/{id}/messages` so an existing durable session can accept another user message instead of requiring a brand-new session for every interaction.

#### Deliverables

- API route and payload validation for appending one user message to a session
- durable event emission and projection update for the appended message
- tests covering happy-path append, missing session, invalid payload, and terminal-session rejection

#### Acceptance

- [x] Existing sessions can accept a new user message through the API.
- [x] The appended message persists as a durable event and updates session metadata deterministically.
- [x] Terminal sessions reject new messages cleanly.
- [x] Existing read, create, stream, and resume routes remain unchanged.

### P9-API-02 - Cancel And Suspend Entry

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P9-API-01`
- Branch: `codex/p9-api-02-session-control`
- Owned paths: `apps/api/`, `packages/agent-core/`, `tests/api/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose `POST /sessions/{id}/cancel` and `POST /sessions/{id}/suspend` so operators can move live or queued sessions through the documented control-plane transitions.

#### Deliverables

- cancel and suspend API routes with deterministic response models
- durable control events and projection transitions
- tests covering valid transitions, invalid state transitions, auth behavior, and missing sessions

#### Acceptance

- [x] Cancel and suspend routes persist control events and update session state correctly.
- [x] Invalid transitions return deterministic errors without mutating durable state.
- [x] Existing create, message, stream, and resume behavior remains unchanged.
- [x] Operator runbook documents both control actions.

### P9-API-03 - Approval HTTP Entry

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P9-API-02`
- Branch: `codex/p9-api-03-approval-http`
- Owned paths: `apps/api/`, `packages/agent-core/`, `tests/api/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose `POST /approvals/{id}/approve` and `POST /approvals/{id}/reject` by reusing the existing approval service entry instead of keeping approval resolution CLI-only.

#### Deliverables

- approval and rejection API routes
- request validation and deterministic error mapping
- tests covering grant, reject, invalid state, and auth cases

#### Acceptance

- [x] Approval decisions can be recorded over HTTP with the same durable event semantics as the core service entry.
- [x] Invalid approval state is rejected deterministically.
- [x] Existing CLI approval behavior remains unchanged.
- [x] Runbook documents the approval HTTP path.

### P9-WKR-01 - Worker Continuous Loop Behavior

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P8-CLOSE-01`
- Branch: `codex/p9-wkr-01-worker-daemon`
- Owned paths: `apps/worker/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Harden the current worker loop from a single-operator poll helper into a more stable continuous worker process with explicit idle behavior, cycle reporting, and daemon-friendly defaults.

#### Deliverables

- improved worker loop defaults for continuous operation
- deterministic stop and idle semantics for local daemon-style execution
- tests covering multi-cycle idle polling and non-interactive operator execution
- runbook guidance for long-running local worker usage

#### Acceptance

- [x] Worker loop can run for multiple cycles with deterministic idle behavior.
- [x] Loop reporting stays machine-readable for operator automation.
- [x] Existing single-cycle worker loop behavior remains supported.
- [x] Documentation explains short-run and long-run worker invocation modes.

### P9-CLOSE-01 - Phase 9 Closeout And Phase 10 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOCS`
- Depends on: `P9-API-03`, `P9-WKR-01`
- Branch: `codex/p9-closeout-phase10-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 9 by recording session-control and worker-hardening evidence, then schedule the next code-delivery surface tasks before implementation resumes.

#### Deliverables

- Phase 9 acceptance record under `docs/`
- task registry update for Phase 10 starter tasks
- project progress update moving the repository to Phase 10 ready state

#### Acceptance

- [x] Acceptance record maps Phase 9 criteria to implemented code paths.
- [x] Validation commands and results are recorded.
- [x] Deferred diff, artifacts, commit, and pull-request work is explicit.
- [x] `PROGRESS.md` identifies Phase 10 starter tasks as the next active implementation lanes.

## Phase 10 Task Board

### P10-API-01 - Session Diff Read API

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P9-CLOSE-01`
- Branch: `codex/p10-api-01-session-diff`
- Owned paths: `apps/api/`, `packages/agent-runtime/`, `tests/api/`, `tests/agent_runtime/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a read-only `GET /sessions/{id}/diff` API that lets operators inspect the current workspace delta for a durable session before any commit or PR action exists.

#### Deliverables

- session diff application entry or runtime adapter
- API route and deterministic not-found or unavailable responses
- tests covering clean workspace, changed workspace, missing session, and auth behavior
- runbook guidance for operator review

#### Acceptance

- [x] Operators can request a machine-readable diff for a known session.
- [x] Missing or non-diffable sessions fail deterministically.
- [x] The route is read-only and does not mutate session state.
- [x] Runbook documents the diff review path.

### P10-API-02 - Session Artifacts Read API

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P10-API-01`
- Branch: `codex/p10-api-02-session-artifacts`
- Owned paths: `apps/api/`, `packages/agent-storage/`, `tests/api/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose `GET /sessions/{id}/artifacts` so operator surfaces can list durable model, tool, and runtime outputs without scraping event payloads directly.

#### Deliverables

- artifact projection or query contract
- API route for per-session artifact listing
- tests covering empty artifact lists, persisted artifacts, missing session, and auth behavior
- runbook guidance for artifact lookup

#### Acceptance

- [x] Operators can list artifacts for a known session.
- [x] Empty artifact lists are represented explicitly.
- [x] Artifact response fields are stable and machine-readable.
- [x] Runbook documents the artifact lookup path.

### P10-API-03 - Session Commit API

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P10-API-01`
- Branch: `codex/p10-api-03-session-commit`
- Owned paths: `apps/api/`, `packages/agent-runtime/`, `packages/agent-security/`, `tests/api/`, `tests/agent_runtime/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a controlled `POST /sessions/{id}/commit` entry that can turn reviewed workspace changes into a local Git commit under explicit policy constraints.

#### Deliverables

- commit request validation and policy checks
- runtime-backed local Git commit implementation
- deterministic conflict responses for dirty, missing, terminal, or policy-blocked cases
- tests covering success, no-diff, invalid message, and policy rejection

#### Acceptance

- [x] A reviewed session can create one local commit through the API.
- [x] Commit message and author inputs are validated.
- [x] Policy-blocked commit attempts fail closed.
- [x] Existing read-only diff behavior remains unchanged.

### P10-API-04 - Session Pull Request API

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P10-API-03`
- Branch: `codex/p10-api-04-session-pr`
- Owned paths: `apps/api/`, `packages/agent-integrations/`, `packages/agent-security/`, `tests/api/`, `tests/agent_integrations/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a controlled `POST /sessions/{id}/pull-request` planning and execution path for future GitHub-backed delivery while keeping networked side effects explicit and approval-gated.

#### Deliverables

- PR request validation and policy checks
- integration boundary for GitHub or SCM provider execution
- deterministic dry-run or unavailable response for local-only environments
- tests covering policy gating, missing commit, and dry-run behavior

#### Acceptance

- [x] PR creation is represented as an explicit controlled action.
- [x] Networked PR execution is approval or policy gated.
- [x] Local-only environments return deterministic unavailable or dry-run responses.
- [x] Runbook documents the PR delivery path and limitations.

### P10-CLOSE-01 - Phase 10 Closeout And Phase 11 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOCS`
- Depends on: `P10-API-04`
- Branch: `codex/p10-closeout-phase11-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 10 by recording delivery-surface evidence, known local-only limitations, and the next delivery-hardening tasks.

#### Deliverables

- Phase 10 acceptance record under `docs/`
- task registry update for Phase 11 starter tasks
- project progress update moving the repository to Phase 11 ready state

#### Acceptance

- [x] Acceptance record maps Phase 10 criteria to implemented code paths.
- [x] Validation commands and results are recorded.
- [x] Deferred idempotency, delivery audit, and real SCM provider work is explicit.
- [x] `PROGRESS.md` identifies Phase 11 starter tasks as the next active implementation lanes.

## Phase 11 Task Board

### P11-API-01 - Side Effect Idempotency Keys

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P10-CLOSE-01`
- Branch: `codex/p11-api-01-idempotency`
- Owned paths: `apps/api/`, `packages/agent-storage/`, `tests/api/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add shared `Idempotency-Key` handling for side-effect API actions so commit, pull-request, approvals, and control actions can be retried safely by operators.

#### Deliverables

- idempotency request parsing and response replay contract
- storage adapter for side-effect response records
- API integration for at least commit and pull-request actions
- tests covering first request, replay, conflicting replay, and missing key behavior

#### Acceptance

- [x] Repeated side-effect requests with the same key return the original response.
- [x] Conflicting payloads for the same key fail deterministically.
- [x] Missing idempotency keys remain explicit in API behavior.
- [x] Runbook documents idempotent retry usage.

### P11-OBS-01 - Delivery Audit Events

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P11-API-01`
- Branch: `codex/p11-obs-01-delivery-audit`
- Owned paths: `apps/api/`, `packages/agent-core/`, `packages/agent-storage/`, `packages/agent-observability/`, `tests/api/`, `tests/agent_core/`, `tests/agent_storage/`, `tests/agent_observability/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Record commit and pull-request delivery attempts as durable audit events so delivery decisions can be replayed and reviewed after the API response is gone.

#### Deliverables

- delivery event types or audit records
- storage projection for delivery attempts
- wiring from commit and pull-request APIs
- tests covering success, policy-blocked, and unavailable delivery attempts

#### Acceptance

- [x] Commit attempts are recorded with session, policy, and result metadata.
- [x] Pull-request attempts are recorded with dry-run or unavailable status.
- [x] Delivery audit records can be queried deterministically.
- [x] Existing trace/eval checks remain green.

### P11-INT-01 - GitHub Pull Request Provider Skeleton

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P11-API-01`, `P11-OBS-01`
- Branch: `codex/p11-int-01-github-pr-provider`
- Owned paths: `packages/agent-integrations/`, `apps/config/`, `tests/agent_integrations/`, `tests/config/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a GitHub pull-request provider skeleton behind explicit configuration while preserving local-only dry-run as the default safe behavior.

#### Deliverables

- GitHub provider config model
- provider interface for PR creation
- dry-run and unavailable fallbacks
- tests covering missing token, dry-run, and request serialization

#### Acceptance

- [x] Local-only remains the default provider.
- [x] Missing GitHub token fails before any network call.
- [x] GitHub request payload is tested without requiring live GitHub access.
- [x] Runbook documents provider configuration and limitations.

### P11-CLOSE-01 - Phase 11 Closeout And Phase 12 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TL`
- Depends on: `P11-API-01`, `P11-OBS-01`, `P11-INT-01`
- Branch: `codex/p11-closeout-phase12-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 11 with an explicit delivery-hardening acceptance record and define the next safe Phase 12 implementation lanes.

#### Deliverables

- Phase 11 acceptance record
- task registry update for Phase 12 starter tasks
- project progress update moving the repository to Phase 12 ready state
- README and runbook alignment where current status changed

#### Acceptance

- [x] Phase 11 acceptance record maps completed tasks to implemented behavior.
- [x] Validation commands and results are recorded.
- [x] Remote SCM execution remains explicitly deferred.
- [x] `PROGRESS.md` identifies Phase 12 starter tasks as the next active implementation lanes.

## Phase 12 Task Board

### P12-CONFIG-01 - SCM Provider Settings

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P11-CLOSE-01`
- Branch: `codex/p12-config-01-scm-provider-settings`
- Owned paths: `apps/config/`, `tests/config/`, `configs/default.env`, `.env.example`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add explicit SCM provider settings so remote pull-request execution cannot be enabled accidentally.

#### Deliverables

- SCM settings dataclass
- environment/default loading for provider, GitHub owner/repo, token env, and dry-run default
- tests covering local-only default, GitHub opt-in, and missing token env behavior
- runbook update documenting safe configuration

#### Acceptance

- [x] Local-only is the default SCM provider.
- [x] GitHub provider requires explicit configuration.
- [x] Token values are read only through an environment variable name and are not serialized.
- [x] Tests cover default and GitHub opt-in config paths.

### P12-INT-01 - Pull Request Gateway Selection

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P12-CONFIG-01`
- Branch: `codex/p12-int-01-pr-gateway-selection`
- Owned paths: `packages/agent-integrations/`, `apps/api/`, `apps/config/`, `tests/agent_integrations/`, `tests/api/`, `tests/config/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire pull-request gateway selection behind SCM settings while preserving local-only as the default API behavior.

#### Deliverables

- gateway factory
- API composition wiring for selected provider
- tests proving local-only default and GitHub dry-run selection
- policy and audit behavior preserved

#### Acceptance

- [x] Existing local-only API tests continue to pass without SCM config.
- [x] GitHub dry-run can be selected only through explicit settings.
- [x] Non-dry-run GitHub execution still fails closed until the execution task lands.
- [x] Delivery audit records provider/status metadata for selected gateway paths.

### P12-API-01 - Delivery Audit Read API

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P11-CLOSE-01`
- Branch: `codex/p12-api-01-delivery-audit-read`
- Owned paths: `apps/api/`, `packages/agent-storage/`, `tests/api/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose delivery audit records through a read-only session API so operators can inspect delivery decisions after responses are gone.

#### Deliverables

- `GET /sessions/{id}/delivery-audit` route
- deterministic response schema
- tests covering not found, empty audit, and recorded delivery attempts
- runbook update

#### Acceptance

- [x] Operators can list delivery attempts for one session.
- [x] Empty delivery audit returns an explicit empty list.
- [x] Response includes action, status, policy profile, idempotency key, metadata, and timestamp.
- [x] Read API does not trigger any side effect.

### P12-CLOSE-01 - Phase 12 Closeout And Phase 13 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TL`
- Depends on: `P12-CONFIG-01`, `P12-INT-01`, `P12-API-01`
- Branch: `codex/p12-closeout-phase13-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 12 with an explicit acceptance record and define the next phase without violating file-size or remote-side-effect boundaries.

#### Deliverables

- Phase 12 acceptance record
- task registry update for Phase 13 starter tasks
- project progress update moving the repository to Phase 13 ready state
- README alignment with the latest closeout record

#### Acceptance

- [x] Phase 12 acceptance record maps completed tasks to implemented behavior.
- [x] Validation commands and results are recorded.
- [x] `app.py` file-size risk is explicit before further API work.
- [x] Remote SCM execution remains deferred behind future safety tasks.

## Phase 13 Task Board

### P13-API-01 - API Composition Split

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P12-CLOSE-01`
- Branch: `codex/p13-api-01-composition-split`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Split `ZebraAgentApi` composition before adding more API behavior, keeping every source file under repository limits.

#### Deliverables

- session read APIs moved behind focused composition modules where appropriate
- `apps/api/src/zebra_agent_api/app.py` reduced away from the 500-line hard limit
- route behavior unchanged
- targeted API regression tests

#### Acceptance

- [x] `app.py` is safely below the 500-line hard limit.
- [x] Existing route and HTTP API tests continue to pass.
- [x] No endpoint behavior changes.
- [x] Future API work has a clear extension point.

### P13-INT-01 - Guarded GitHub Pull Request Execution

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P13-API-01`, `P13-SEC-01`
- Branch: `codex/p13-int-01-guarded-github-pr-execution`
- Owned paths: `packages/agent-integrations/`, `apps/api/`, `apps/config/`, `tests/agent_integrations/`, `tests/api/`, `tests/config/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first guarded GitHub PR execution path while preserving local-only default behavior and fail-closed semantics.

#### Deliverables

- explicit opt-in execution gate
- token lookup by configured environment variable name
- request serialization and execution boundary tests without live GitHub dependency
- delivery audit coverage for attempted execution

#### Acceptance

- [x] Local-only remains the default with no remote side effect.
- [x] GitHub execution requires explicit provider and dry-run disablement.
- [x] Missing token fails before any network call.
- [x] Tests do not require live GitHub access.

### P13-SEC-01 - SCM Credential Boundary Draft

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P12-CLOSE-01`
- Branch: `codex/p13-sec-01-scm-credential-boundary`
- Owned paths: `packages/agent-security/`, `apps/config/`, `tests/agent_security/`, `tests/config/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define the minimal credential boundary required before live SCM execution becomes acceptable.

#### Deliverables

- credential capability model draft
- redaction and non-serialization rules for SCM tokens
- tests covering token name/value separation and safe serialization
- runbook update

#### Acceptance

- [x] Token values are never stored in project settings snapshots.
- [x] Serialized configs include token env names only.
- [x] Redaction behavior is deterministic.
- [x] Live SCM execution remains blocked until this boundary is adopted.

### P13-CLOSE-01 - Phase 13 Closeout And Phase 14 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TL`
- Depends on: `P13-API-01`, `P13-SEC-01`, `P13-INT-01`
- Branch: `codex/p13-closeout-phase14-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 13 with an explicit acceptance record and define post-execution hardening work before expanding remote SCM behavior.

#### Deliverables

- Phase 13 acceptance record
- task registry update for Phase 14 starter tasks
- project progress update moving the repository to Phase 14 ready state
- README alignment with the latest closeout record

#### Acceptance

- [x] Phase 13 acceptance record maps completed tasks to implemented behavior.
- [x] Validation commands and results are recorded.
- [x] Live GitHub execution remains guarded and opt-in.
- [x] Phase 14 starter tasks focus on hardening rather than broader side effects.

## Phase 14 Task Board

### P14-OBS-01 - SCM Execution Audit Hardening

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P13-CLOSE-01`
- Branch: `codex/p14-obs-01-scm-execution-audit-hardening`
- Owned paths: `apps/api/`, `packages/agent-storage/`, `tests/api/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Harden delivery audit metadata for guarded SCM execution so operators can distinguish dry-run, created, blocked, and transport-failed attempts.

#### Deliverables

- normalized SCM execution result metadata
- audit coverage for created and transport-failed GitHub attempts
- read API coverage for new metadata
- runbook update

#### Acceptance

- [x] Created GitHub PR attempts record provider, status, URL, commit SHA, and dry-run flag.
- [x] Transport failures record a deterministic unavailable status and reason.
- [x] Read API returns normalized metadata without token values.
- [x] Existing local-only audit behavior remains unchanged.

### P14-SEC-01 - SCM Token Redaction Regression Gate

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P14-OBS-01`
- Branch: `codex/p14-sec-01-scm-token-redaction-regression-gate`
- Owned paths: `packages/agent-security/`, `packages/agent-integrations/`, `apps/api/`, `tests/agent_security/`, `tests/agent_integrations/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add regression coverage proving SCM token values cannot leak through plans, API responses, delivery audit, or serialized settings.

#### Deliverables

- shared token-leak assertion helper or focused tests
- integration tests for PR plan and execution responses
- API tests for delivery audit redaction
- runbook update

#### Acceptance

- [x] Token values do not appear in PR plans.
- [x] Token values do not appear in API responses.
- [x] Token values do not appear in delivery audit records.
- [x] Token values do not appear in settings snapshots.

### P14-DOC-01 - Remote SCM Operator Safety Runbook

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P14-OBS-01`, `P14-SEC-01`
- Branch: `codex/p14-doc-01-remote-scm-operator-safety-runbook`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Document the exact safe operator path for enabling guarded GitHub PR execution.

#### Deliverables

- dry-run first checklist
- required environment variables
- policy requirements
- rollback and audit inspection steps

#### Acceptance

- [x] Runbook starts with local-only and dry-run defaults.
- [x] Live execution instructions require explicit opt-in.
- [x] Audit inspection is part of the operator flow.
- [x] Token handling rules are visible before execution steps.

### P14-CLOSE-01 - Phase 14 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P14-DOC-01`
- Branch: `codex/p14-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 14 with an acceptance record and define the next implementation phase.

#### Deliverables

- Phase 14 acceptance record
- task registry update for the next phase
- project progress update

#### Acceptance

- [x] Phase 14 completed tasks are mapped to behavior and validation evidence.
- [x] Next phase starter tasks are ready and path-scoped.
- [x] README and PROGRESS point to the current implementation state.

## Phase 15 Task Board

### P15-SEC-01 - Credential Capability Domain Model

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P14-CLOSE-01`
- Branch: `codex/p15-sec-01-credential-capability-model`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define the local credential capability model needed before adding concrete credential broker backends.

#### Deliverables

- short-lived credential capability value object
- scope and audience fields for SCM credentials
- deterministic redaction serialization
- regression tests proving raw values stay outside serializable snapshots

#### Acceptance

- [x] Capability model validates provider, scope, audience, and expiry.
- [x] Redacted serialization never emits raw token values.
- [x] Tests cover valid, invalid, and expired capability cases.
- [x] No concrete secret backend is introduced.

### P15-SEC-02 - Credential Broker Port

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P15-SEC-01`
- Branch: `codex/p15-sec-02-credential-broker-port`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define a credential broker Port that can issue scoped runtime capabilities without coupling core logic to environment variables or secret backends.

#### Deliverables

- broker Protocol or interface
- in-memory fake broker for tests
- explicit unavailable and denied error types
- docs describing local-only MVP limits

#### Acceptance

- [x] Broker Port can request an SCM credential by provider and audience.
- [x] Fake broker returns redacted capabilities in tests.
- [x] Error paths distinguish missing, denied, and unavailable credentials.
- [x] No token value is stored in durable session state.

### P15-INT-01 - SCM Broker Lookup Adapter

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P15-SEC-02`
- Branch: `codex/p15-int-01-scm-broker-lookup-adapter`
- Owned paths: `packages/agent-integrations/`, `packages/agent-security/`, `tests/agent_integrations/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Route SCM token lookup through the broker boundary while preserving local-only and dry-run defaults.

#### Deliverables

- broker-backed SCM credential lookup path
- integration tests for dry-run, missing credential, and fake credential execution
- documentation of the env-token fallback boundary if retained

#### Acceptance

- [x] Local-only behavior remains unchanged.
- [x] GitHub dry-run does not require a credential.
- [x] GitHub non-dry-run can use a broker-issued test capability.
- [x] Missing broker credential fails before network execution.

### P15-CLOSE-01 - Phase 15 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P15-INT-01`
- Branch: `codex/p15-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 15 with an acceptance record and define the next implementation phase.

#### Deliverables

- Phase 15 acceptance record
- task registry update for the next phase
- project progress update

#### Acceptance

- [x] Phase 15 completed tasks are mapped to behavior and validation evidence.
- [x] Credential broker deferrals and env fallback boundaries are explicit.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 16 Task Board

### P16-SEC-01 - Local Environment Credential Broker

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P15-CLOSE-01`
- Branch: `codex/p16-sec-01-local-env-credential-broker`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Implement a local environment-backed credential broker so runtime composition can request scoped capabilities through the broker Port without reading environment variables inside SCM adapters.

#### Deliverables

- local environment broker implementation
- provider/audience/scope mapping for GitHub pull-request creation
- tests for success, missing env var, denied scope, and redaction
- docs update for local-only backend limits

#### Acceptance

- [x] Broker issues `CredentialCapability` from configured environment variable names.
- [x] Missing environment values raise `CredentialMissingError`.
- [x] Unsupported provider or scope raises `CredentialDeniedError`.
- [x] Raw token values do not appear in redacted snapshots or repr.

### P16-APP-01 - API Credential Broker Composition

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P16-SEC-01`
- Branch: `codex/p16-app-01-api-credential-broker-composition`
- Owned paths: `apps/api/`, `packages/agent-integrations/`, `packages/agent-security/`, `tests/api/`, `tests/agent_integrations/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire API pull-request gateway construction through the credential broker boundary while preserving local-only and GitHub dry-run behavior.

#### Deliverables

- API composition creates or receives a broker instance
- broker-backed GitHub non-dry-run API test with fake transport
- missing broker credential API failure test
- docs update for API operator behavior

#### Acceptance

- [x] Local-only API behavior remains unchanged.
- [x] GitHub dry-run API behavior does not require credentials.
- [x] GitHub non-dry-run API path can use a broker-issued capability in tests.
- [x] Missing broker credential fails before network execution and records audit metadata.

### P16-CLOSE-01 - Phase 16 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P16-APP-01`
- Branch: `codex/p16-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 16 with local credential backend and API composition evidence.

#### Deliverables

- Phase 16 acceptance record
- next phase task board
- updated progress and README state

#### Acceptance

- [x] Local broker and API composition validation evidence is recorded.
- [x] Env fallback boundary is updated or retired explicitly.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 17 Task Board

### P17-APP-01 - API Default Environment Broker Factory

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P16-CLOSE-01`
- Branch: `codex/p17-app-01-api-default-environment-broker-factory`
- Owned paths: `apps/api/`, `packages/agent-security/`, `tests/api/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Make API composition construct a default environment-backed credential broker from SCM settings when explicit broker injection is not supplied.

#### Deliverables

- broker factory helper for GitHub SCM settings
- default `create_app` composition path using the helper
- tests proving default API broker behavior with env mapping or injected env
- docs update for default broker composition

#### Acceptance

- [x] Local-only API behavior remains unchanged.
- [x] GitHub dry-run does not require a broker credential.
- [x] GitHub non-dry-run can use the default environment broker in tests.
- [x] Missing default broker env value records delivery audit metadata.

### P17-INT-01 - SCM Env Fallback Boundary

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P17-APP-01`
- Branch: `codex/p17-int-01-scm-env-fallback-boundary`
- Owned paths: `packages/agent-integrations/`, `packages/agent-security/`, `tests/agent_integrations/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Narrow or explicitly deprecate direct environment-token fallback in SCM gateway construction now that API composition can use a broker.

#### Deliverables

- explicit fallback policy in code or docs
- regression tests for broker-first behavior
- compatibility tests for any retained fallback

#### Acceptance

- [x] Broker-backed path is preferred in integration tests.
- [x] Any retained env fallback is explicit and documented.
- [x] Removing or narrowing fallback does not break local-only or dry-run behavior.

### P17-DOC-01 - Broker-Backed SCM Operator Docs

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P17-APP-01`, `P17-INT-01`
- Branch: `codex/p17-doc-01-broker-backed-scm-operator-docs`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Update operator documentation for broker-backed SCM execution and the env fallback boundary.

#### Deliverables

- broker-backed configuration examples
- audit inspection checklist
- fallback/deprecation notes

#### Acceptance

- [x] Runbook describes broker-backed GitHub PR execution.
- [x] Token handling rules remain visible before execution steps.
- [x] Audit inspection remains part of the operator flow.

### P17-CLOSE-01 - Phase 17 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P17-DOC-01`
- Branch: `codex/p17-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 17 with credential backend hardening evidence and define the next implementation phase.

#### Deliverables

- Phase 17 acceptance record
- next phase task board
- project progress update

#### Acceptance

- [x] Phase 17 completed tasks are mapped to behavior and validation evidence.
- [x] Broker-backed operator flow and fallback boundary are recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 18 Task Board

### P18-OBS-01 - SCM Credential Source Audit Metadata

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P17-CLOSE-01`
- Branch: `codex/p18-obs-01-scm-credential-source-audit`
- Owned paths: `apps/api/`, `packages/agent-integrations/`, `packages/agent-security/`, `tests/api/`, `tests/agent_integrations/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add non-secret credential source metadata to SCM delivery audit so operators can distinguish broker-backed, explicit fallback, and missing credential paths.

#### Deliverables

- redacted credential source metadata model or helper
- pull-request audit metadata update
- tests proving token values are absent
- docs update for audit interpretation

#### Acceptance

- [x] Broker-backed PR attempts record a non-secret credential source.
- [x] Explicit fallback attempts record a non-secret credential source.
- [x] Missing credential attempts distinguish broker missing from transport failure.
- [x] No raw token value appears in API response or delivery audit metadata.

### P18-OBS-02 - Credential Failure Audit Classification

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P18-OBS-01`
- Branch: `codex/p18-obs-02-credential-failure-audit-classification`
- Owned paths: `apps/api/`, `packages/agent-integrations/`, `packages/agent-security/`, `tests/api/`, `tests/agent_integrations/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Classify credential missing, denied, unavailable, and transport failures in operator-facing delivery audit without exposing secrets.

#### Deliverables

- deterministic failure classification values
- API and integration tests for each credential failure family
- runbook update for remediation guidance

#### Acceptance

- [x] Missing credential audit is distinguishable from denied credential audit.
- [x] Broker unavailable audit is distinguishable from GitHub transport failure audit.
- [x] Remediation guidance is documented.

### P18-CLOSE-01 - Phase 18 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P18-OBS-02`
- Branch: `codex/p18-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 18 with SCM delivery audit and credential observability evidence.

#### Deliverables

- Phase 18 acceptance record
- next phase task board
- updated progress and README state

#### Acceptance

- [x] Credential source and failure classification evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 19 Task Board

### P19-SEC-01 - Secret Store Port And Redaction Contract

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P18-CLOSE-01`
- Branch: `codex/p19-sec-01-secret-store-port`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define the secret-store Port and redacted snapshot contract needed before non-environment credential backends are added.

#### Deliverables

- secret-store Protocol or interface
- redacted secret metadata model
- deterministic tests for missing and unavailable secret lookups
- focused architecture note or doc update

#### Acceptance

- [x] Secret retrieval contract keeps raw secret values out of repr and durable metadata.
- [x] Security package exposes deterministic missing and unavailable secret-store semantics.
- [x] Future broker backends can depend on the Port without reading raw storage directly from API or integrations.

### P19-SEC-02 - Local Secret Store Backend

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P19-SEC-01`
- Branch: `codex/p19-sec-02-local-secret-store-backend`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Implement a local secret-store backend aligned with the architecture's local secure storage direction.

#### Deliverables

- local secret-store backend
- broker-facing retrieval helper
- tests covering missing, unavailable, and redacted read paths

#### Acceptance

- [x] Local secret storage can serve credential material without exposing raw values in repr or snapshots.
- [x] Missing and unavailable secret-store failures remain distinguishable.
- [x] Broker-facing callers can retrieve secret material through the backend without bypassing the Port.

### P19-INT-01 - GitHub App Credential Adapter Skeleton

- Status: `Done`
- Owner: `Codex`
- Suggested role: `INT`
- Depends on: `P19-SEC-02`
- Branch: `codex/p19-int-01-github-app-credential-adapter`
- Owned paths: `packages/agent-integrations/`, `packages/agent-security/`, `tests/agent_integrations/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first provider-backed non-environment credential adapter using the secret-store and broker boundaries.

#### Deliverables

- GitHub App credential adapter skeleton
- broker lookup path using stored secret material
- redaction and failure-class regression tests

#### Acceptance

- [x] Integration path can request GitHub App-backed credentials without writing raw secrets into durable audit state.
- [x] Provider-backed missing, denied, unavailable, and transport failures remain classifiable.
- [x] Operator-facing docs identify the GitHub App adapter as a guarded future execution path.

### P19-CLOSE-01 - Phase 19 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P19-INT-01`
- Branch: `codex/p19-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 19 with secret-store and provider-backed credential foundation evidence.

#### Deliverables

- Phase 19 acceptance record
- next phase task board
- updated progress and README state

#### Acceptance

- [x] Secret-store and GitHub App credential skeleton evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 20 Task Board

### P20-SEC-01 - Network Profile Contract

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P19-CLOSE-01`
- Branch: `codex/p20-sec-01-network-profile-contract`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define deterministic network-profile contracts aligned with the architecture's egress-control model.

#### Deliverables

- network profile model and validation rules
- deterministic tests for allowed profile values and defaults
- focused architecture note or doc update

#### Acceptance

- [x] Security package defines `none`, `setup-only`, `domain-allowlist`, `mcp-proxy-only`, `git-proxy-only`, and `full-trusted-local`.
- [x] Invalid or ambiguous network profiles are rejected deterministically.
- [x] Current local defaults remain fail-closed.

### P20-INT-01 - SCM Transport Egress Guard

- Status: `Done`
- Owner: `Codex`
- Suggested role: `INT`
- Depends on: `P20-SEC-01`
- Branch: `codex/p20-int-01-scm-transport-egress-guard`
- Owned paths: `packages/agent-integrations/`, `packages/agent-security/`, `tests/agent_integrations/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Guard SCM transport execution with explicit network-profile checks before remote side effects occur.

#### Deliverables

- SCM transport egress gate
- audit metadata or reason updates for blocked egress
- regression tests for blocked and allowed paths

#### Acceptance

- [x] Remote SCM execution is blocked when the network profile disallows the transport.
- [x] Local-only and dry-run behavior remain unchanged.
- [x] Operator-facing failures clearly distinguish egress policy blocks from credential or transport failures.

### P20-DOC-01 - Egress Control Operator Docs

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P20-SEC-01`, `P20-INT-01`
- Branch: `codex/p20-doc-01-egress-control-operator-docs`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Document the operator model for guarded network profiles and SCM egress constraints.

#### Deliverables

- runbook updates for egress profiles
- remediation guidance for egress policy blocks
- examples that preserve fail-closed defaults

#### Acceptance

- [x] Operator docs explain when remote SCM execution is blocked by network profile.
- [x] Examples preserve `network none` as the default local posture.
- [x] Remediation guidance distinguishes egress policy from credential policy.

### P20-CLOSE-01 - Phase 20 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P20-DOC-01`
- Branch: `codex/p20-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 20 with egress-control evidence and define the next implementation phase.

#### Deliverables

- Phase 20 acceptance record
- next phase task board
- updated progress and README state

#### Acceptance

- [x] Network profile and SCM egress guard evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 21 Task Board

### P21-INT-01 - SCM Proxy Transport Contract

- Status: `Done`
- Owner: `Codex`
- Suggested role: `INT`
- Depends on: `P20-CLOSE-01`
- Branch: `codex/p21-int-01-scm-proxy-transport-contract`
- Owned paths: `packages/agent-integrations/`, `tests/agent_integrations/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define the proxy-facing transport contract required to move SCM side effects off direct local HTTP paths.

#### Deliverables

- proxy transport Port for SCM requests
- serializable request and response model for proxy execution
- targeted tests for deterministic proxy contract behavior

#### Acceptance

- [x] SCM integrations expose a proxy transport contract separate from the current direct GitHub HTTP path.
- [x] Proxy transport request and response payloads are deterministic and serializable.
- [x] Existing direct transport behavior remains unchanged until the proxy adapter task lands.

### P21-INT-02 - GitHub Proxy Pull Request Adapter

- Status: `Done`
- Owner: `Codex`
- Suggested role: `INT`
- Depends on: `P21-INT-01`
- Branch: `codex/p21-int-02-github-proxy-pr-adapter`
- Owned paths: `packages/agent-integrations/`, `tests/agent_integrations/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a GitHub PR adapter that executes through the proxy transport contract instead of direct local HTTP transport.

#### Deliverables

- GitHub proxy-backed PR adapter
- execution-path selection between direct and proxy-backed transport
- regression tests for created and blocked proxy-backed flows

#### Acceptance

- [x] GitHub PR execution can route through the proxy transport when configured.
- [x] Audit metadata still distinguishes egress policy, credential, and transport failures.
- [x] Direct transport behavior remains explicitly guarded and backwards compatible.

### P21-TOOL-01 - MCP Proxy Egress Starter Contract

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TOOL`
- Depends on: `P20-CLOSE-01`
- Branch: `codex/p21-tool-01-mcp-proxy-egress-starter-contract`
- Owned paths: `packages/agent-tools/`, `packages/agent-security/`, `tests/agent_tools/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define the first explicit MCP proxy egress contract so `mcp-proxy-only` can evolve from a blocked profile into a concrete execution path.

#### Deliverables

- proxy-oriented MCP egress contract
- deterministic policy-facing metadata for MCP proxy routing
- targeted tests for blocked versus proxy-routable MCP calls

#### Acceptance

- [x] Tooling surfaces a concrete MCP proxy contract rather than a placeholder profile label.
- [x] Policy-facing metadata distinguishes direct-local tool calls from future proxy-routed MCP calls.
- [x] The current fail-closed default remains unchanged.

### P21-DOC-01 - Proxy Egress Operator Docs

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P21-INT-02`, `P21-TOOL-01`
- Branch: `codex/p21-doc-01-proxy-egress-operator-docs`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Document the operator model for proxy-backed SCM and MCP egress paths.

#### Deliverables

- runbook updates for proxy-backed egress
- remediation matrix for proxy, credential, and upstream failures
- safe rollback guidance

#### Acceptance

- [x] Operator docs explain when to use direct trusted-local execution versus proxy-backed egress.
- [x] Runbook examples preserve fail-closed defaults and narrow explicit enablement.
- [x] Remediation guidance distinguishes proxy availability from upstream SCM or MCP failures.

### P21-CLOSE-01 - Phase 21 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P21-DOC-01`
- Branch: `codex/p21-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 21 with proxy-egress evidence and define the next implementation phase.

#### Deliverables

- Phase 21 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Proxy-backed egress evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 22 Task Board

### P22-TOOL-01 - MCP Proxy Gateway Execution Path

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TOOL`
- Depends on: `P21-CLOSE-01`
- Branch: `codex/p22-tool-01-mcp-proxy-gateway-execution`
- Owned paths: `packages/agent-tools/`, `tests/agent_tools/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Turn the MCP proxy starter contract into a concrete execution path behind the tool gateway.

#### Deliverables

- MCP proxy executor or gateway adapter
- tool-gateway wiring for proxy-routed MCP calls
- targeted tests for successful and blocked MCP proxy execution

#### Acceptance

- [x] `mcp.<server>.<tool>` calls can execute through the MCP proxy path when policy allows them.
- [x] Local builtin tool execution remains unchanged.
- [x] Failed MCP proxy execution is surfaced deterministically through tool results or gateway errors.

### P22-OBS-01 - Proxy Audit Metadata Normalization

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P22-TOOL-01`
- Branch: `codex/p22-obs-01-proxy-audit-metadata-normalization`
- Owned paths: `packages/agent-integrations/`, `packages/agent-tools/`, `tests/agent_integrations/`, `tests/agent_tools/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Normalize audit-facing metadata across SCM proxy and MCP proxy execution paths.

#### Deliverables

- shared proxy audit metadata shape
- deterministic failure classes for proxy availability versus upstream failures
- regression coverage across SCM and MCP proxy flows

#### Acceptance

- [x] Proxy-backed SCM and MCP execution expose a stable audit metadata shape.
- [x] Proxy availability failures remain distinguishable from upstream GitHub or MCP target failures.
- [x] Existing non-proxy audit behavior remains backwards compatible.

### P22-SEC-01 - Proxy Route Policy Integration

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SEC`
- Depends on: `P22-TOOL-01`
- Branch: `codex/p22-sec-01-proxy-route-policy-integration`
- Owned paths: `packages/agent-security/`, `packages/agent-tools/`, `tests/agent_security/`, `tests/agent_tools/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Integrate proxy route classification deeper into policy and approval surfaces.

#### Deliverables

- richer proxy-route policy metadata
- approval-facing distinctions for local versus proxy-routed tool calls
- regression tests for policy outputs

#### Acceptance

- [x] Policy-facing outputs distinguish direct-local, proxy-routed, and blocked external tool paths.
- [x] Approval or denial messaging stays deterministic for MCP proxy scenarios.
- [x] Current fail-closed defaults remain unchanged.

### P22-DOC-01 - Proxy Gateway Operator Docs

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P22-OBS-01`, `P22-SEC-01`
- Branch: `codex/p22-doc-01-proxy-gateway-operator-docs`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Document the operator model for concrete proxy gateway execution paths.

#### Deliverables

- runbook updates for MCP proxy execution
- audit interpretation guide for proxy-backed SCM and MCP paths
- rollback guidance for proxy gateway incidents

#### Acceptance

- [x] Operator docs explain how proxy-backed MCP execution differs from the starter-contract phase.
- [x] Audit interpretation covers both SCM and MCP proxy flows.
- [x] Runbook examples preserve fail-closed defaults and narrow enablement.

### P22-CLOSE-01 - Phase 22 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P22-DOC-01`
- Branch: `codex/p22-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 22 with proxy gateway evidence and define the next implementation phase.

#### Deliverables

- Phase 22 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Proxy gateway execution evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 23 Task Board

### P23-HAR-01 - Proxy Approval Event Projection

- Status: `Done`
- Owner: `Codex`
- Suggested role: `HAR`
- Depends on: `P22-CLOSE-01`
- Branch: `codex/p23-har-01-proxy-approval-event-projection`
- Owned paths: `packages/agent-core/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Project proxy-aware policy and approval metadata into durable harness event payloads.

#### Deliverables

- policy decision payload extensions for proxy route metadata
- approval-requested event payload extensions for proxy scope metadata
- regression tests for proxy-aware approval event emission

#### Acceptance

- [x] Harness events persist proxy route, target, and network-profile data when policy evaluates an MCP tool.
- [x] Existing non-proxy policy and approval event payloads remain backwards compatible.
- [x] Approval-requested events remain deterministic for both blocked and proxy-routed MCP paths.

### P23-API-01 - Proxy Approval Readback Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P23-HAR-01`
- Branch: `codex/p23-api-01-proxy-approval-readback-surface`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose proxy-aware approval context through operator-facing API read and approval surfaces.

#### Deliverables

- API response fields for proxy approval context
- readback coverage for session and approval operator flows
- regression tests for proxy-aware approval serialization

#### Acceptance

- [x] Operator-facing API surfaces expose proxy route and target context for approval-related flows.
- [x] Existing local-only approval responses remain backwards compatible.
- [x] Proxy-aware approval readback does not expose secrets or raw credential material.

### P23-OBS-01 - Proxy Approval Trace Normalization

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P23-HAR-01`
- Branch: `codex/p23-obs-01-proxy-approval-trace-normalization`
- Owned paths: `packages/agent-core/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Keep proxy-aware approval evidence consistent across policy events, traces, and run summaries.

#### Deliverables

- normalized proxy approval metadata in trace-facing outputs
- regression tests for proxy approval trace shape
- documentation of trace interpretation deltas

#### Acceptance

- [x] Trace-facing outputs reuse the same proxy route vocabulary as policy and tool execution metadata.
- [x] Proxy approval metadata remains deterministic across blocked, approval, and executed paths.
- [x] Non-proxy trace outputs remain backwards compatible.

### P23-CLOSE-01 - Phase 23 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P23-API-01`, `P23-OBS-01`
- Branch: `codex/p23-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 23 with proxy-aware approval readback evidence and define the next implementation phase.

#### Deliverables

- Phase 23 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Proxy-aware approval readback evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 24 Task Board

### P24-STO-01 - Durable Approval Context Projection

- Status: `Done`
- Owner: `Codex`
- Suggested role: `STO`
- Depends on: `P23-CLOSE-01`
- Branch: `codex/p24-sto-01-durable-approval-context-projection`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `tests/agent_core/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Persist proxy-aware approval context into durable projection state so operator reads do not depend on replaying the full event stream.

#### Deliverables

- approval-context projection model updates
- storage-layer rebuild coverage for proxy-aware approval context
- regression tests for projection persistence and recovery

#### Acceptance

- [x] Session or approval projection state persists proxy-aware approval context after `approval_requested`.
- [x] Projection rebuild stays deterministic across approval grant and reject paths.
- [x] Existing local-only projection behavior remains backwards compatible.

### P24-API-01 - Approval Queue And Detail Read API

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P24-STO-01`
- Branch: `codex/p24-api-01-approval-queue-and-detail-read-api`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose projection-backed approval queue and approval detail reads for operators.

#### Deliverables

- approval queue read endpoint or route
- approval detail read endpoint or route
- proxy-aware approval context serialization for queue and detail reads

#### Acceptance

- [x] Operators can list waiting approvals without replaying raw event streams.
- [x] Approval detail reads expose proxy-aware context using the existing safe field set.
- [x] Queue and detail responses remain free of secrets and raw credential material.

### P24-OBS-01 - Approval Projection Consistency Checks

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P24-STO-01`
- Branch: `codex/p24-obs-01-approval-projection-consistency-checks`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `tests/agent_core/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Ensure projection-backed approval context stays consistent with event and trace metadata.

#### Deliverables

- consistency assertions between replayed events and projection output
- regression coverage for proxy-aware approval context drift
- operator guidance for interpreting projection-versus-event discrepancies

#### Acceptance

- [x] Projection-backed approval context matches the event payload vocabulary for route, target, network profile, and scope.
- [x] Regression tests cover grant, reject, and repeated approval-read scenarios.
- [x] Non-proxy approval paths remain backwards compatible.

### P24-CLOSE-01 - Phase 24 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P24-API-01`, `P24-OBS-01`
- Branch: `codex/p24-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 24 with durable approval projection evidence and define the next implementation phase.

#### Deliverables

- Phase 24 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Durable approval projection evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 25 Task Board

### P25-STO-01 - Durable Workspace Projection Store

- Status: `Done`
- Owner: `Codex`
- Suggested role: `STO`
- Depends on: `P24-CLOSE-01`
- Branch: `codex/p25-sto-01-durable-workspace-projection-store`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `tests/agent_storage/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Persist workspace and sandbox lifecycle facts into durable projection state so later snapshot and resume flows do not rely on process-local memory.

#### Deliverables

- workspace projection model
- SQLite workspace projection store
- replay coverage for workspace lifecycle updates
- documentation of stored workspace fields and compatibility expectations

#### Acceptance

- [x] Durable workspace state can be rebuilt from session events deterministically.
- [x] SQLite persistence can store and reload workspace projection rows without losing lifecycle fields.
- [x] Existing session projection behavior remains backwards compatible.

### P25-RT-01 - Runtime Snapshot And Resume Contracts

- Status: `Done`
- Owner: `Codex`
- Suggested role: `RUNTIME`
- Depends on: `P25-STO-01`
- Branch: `codex/p25-rt-01-runtime-snapshot-and-resume-contracts`
- Owned paths: `packages/agent-core/`, `packages/agent-runtime/`, `tests/agent_runtime/`, `tests/agent_core/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extend the current runtime boundary beyond `execute(...)` so snapshot, restore, fork, suspend, and resume semantics exist as typed contracts before worker wiring begins.

#### Deliverables

- runtime lifecycle domain types
- runtime Port extensions for snapshot and resume operations
- local adapter placeholder or deterministic local implementation
- tests covering contract behavior and fail-closed unsupported cases

#### Acceptance

- [x] Core runtime contracts model snapshot, restore, fork, suspend, and resume explicitly.
- [x] Local runtime behavior is deterministic for the supported subset and explicit for unsupported operations.
- [x] Existing command execution paths remain compatible.

### P25-WKR-01 - Worker Snapshot Lifecycle Wiring

- Status: `Done`
- Owner: `Codex`
- Suggested role: `WKR`
- Depends on: `P25-RT-01`
- Branch: `codex/p25-wkr-01-worker-snapshot-lifecycle-wiring`
- Owned paths: `apps/worker/`, `packages/agent-runtime/`, `packages/agent-storage/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire worker-side suspend and resume control paths to durable workspace state so a session can release runtime resources and later restore execution context.

#### Deliverables

- worker lifecycle wiring for snapshot-backed suspend or resume
- durable workspace row updates during worker lifecycle transitions
- regression coverage for snapshot-backed resume orchestration
- operator notes for current local lifecycle limitations

#### Acceptance

- [x] Worker lifecycle can persist suspend or resume transitions against durable workspace state.
- [x] Resume paths read workspace projection state instead of relying on process-local memory.
- [x] Failures leave deterministic lifecycle state for a later retry or operator action.

### P25-CLOSE-01 - Phase 25 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P25-STO-01`, `P25-RT-01`, `P25-WKR-01`
- Branch: `codex/p25-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 25 with durable workspace and snapshot evidence and define the next implementation phase.

#### Deliverables

- Phase 25 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Durable workspace and snapshot evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 26 Task Board

### P26-RT-01 - Local Snapshot Backend

- Status: `Done`
- Owner: `Codex`
- Suggested role: `RUNTIME`
- Depends on: `P25-CLOSE-01`
- Branch: `codex/p26-rt-01-local-snapshot-backend`
- Owned paths: `packages/agent-core/`, `packages/agent-runtime/`, `tests/agent_runtime/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Turn the current fail-closed local snapshot contract into a real local snapshot backend with deterministic retention and compatibility semantics.

#### Deliverables

- local runtime snapshot implementation
- snapshot metadata or retention model
- restore and fork behavior for the supported local subset
- regression coverage for snapshot lifecycle compatibility

#### Acceptance

- [x] Local runtime can create a snapshot and restore a usable runtime handle from it.
- [x] Local snapshot behavior is deterministic and documented for the supported subset.
- [x] Unsupported paths remain explicit rather than silently degraded.

### P26-APP-01 - Suspend And Resume Control Wiring

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P26-RT-01`
- Branch: `codex/p26-app-01-suspend-resume-control-wiring`
- Owned paths: `apps/api/`, `apps/cli/`, `apps/worker/`, `packages/agent-core/`, `packages/agent-storage/`, `tests/agent_core/`, `tests/api/`, `tests/cli/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire session suspend and resume control paths to runtime lifecycle operations and durable workspace state so local operators can pause and continue work through a consistent control plane.

#### Deliverables

- suspend or resume lifecycle wiring across CLI, API, and worker entry points
- durable workspace state updates for control-plane lifecycle transitions
- regression coverage for suspend then resume operator flows
- failure handling for unsupported or invalid lifecycle transitions

#### Acceptance

- [x] Session suspend and resume paths update durable workspace lifecycle state consistently.
- [x] CLI and API operator flows can trigger the supported local suspend or resume path.
- [x] Invalid lifecycle transitions fail deterministically without corrupting workspace state.

### P26-DOC-01 - Snapshot Operator Runbook

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P26-APP-01`
- Branch: `codex/p26-doc-01-snapshot-operator-runbook`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Document the supported local snapshot, suspend, and resume operator model once the control paths exist.

#### Deliverables

- operator runbook updates for local snapshot lifecycle
- failure interpretation and rollback notes
- README and progress updates for the new operator surface

#### Acceptance

- [x] Operator docs describe the supported local snapshot and suspend workflow concretely.
- [x] Failure and unsupported-path behavior are documented.
- [x] README points to the current operator guidance without contradiction.

### P26-CLOSE-01 - Phase 26 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P26-RT-01`, `P26-APP-01`, `P26-DOC-01`
- Branch: `codex/p26-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 26 with local snapshot operator evidence and define the next implementation phase.

#### Deliverables

- Phase 26 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Local snapshot operator evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 27 Task Board

### P27-API-01 - Workspace Lifecycle Readback Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P26-CLOSE-01`
- Branch: `codex/p27-api-01-workspace-lifecycle-readback`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose projection-backed workspace lifecycle and snapshot metadata through safe operator read surfaces so suspended or restored state can be inspected without replaying raw events.

#### Deliverables

- session readback fields or dedicated workspace-lifecycle read surface
- snapshot-safe serialization for operator inspection
- regression coverage for ready, suspended, restored, and terminal workspace reads

#### Acceptance

- [x] Operators can read durable workspace lifecycle state without scanning raw event streams.
- [x] Snapshot metadata is exposed safely without leaking irrelevant runtime internals.
- [x] Existing session read paths remain backward compatible.

### P27-CLI-01 - Workspace Lifecycle Inspect Output

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P27-API-01`
- Branch: `codex/p27-cli-01-workspace-lifecycle-inspect`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extend CLI inspect-style operator output so local users can read workspace lifecycle and snapshot state directly from the durable control plane.

#### Deliverables

- CLI inspect or resume-read output updates for workspace lifecycle state
- snapshot metadata presentation for suspended sessions
- regression coverage for inspect output across lifecycle states

#### Acceptance

- [x] CLI surfaces expose workspace lifecycle state for local operators.
- [x] Suspended snapshot metadata is readable without replaying raw events.
- [x] Existing machine-readable CLI output stays stable for older fields.

### P27-RT-01 - Snapshot Housekeeping And Compatibility Checks

- Status: `Done`
- Owner: `Codex`
- Suggested role: `RUNTIME`
- Depends on: `P27-API-01`
- Branch: `codex/p27-rt-01-snapshot-housekeeping-compat`
- Owned paths: `apps/worker/`, `packages/agent-runtime/`, `packages/agent-storage/`, `tests/agent_runtime/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Make retained local snapshot payloads easier to validate and clean by adding explicit compatibility checks and deterministic housekeeping behavior outside a single runtime call path.

#### Deliverables

- snapshot compatibility validation or manifest checks
- deterministic housekeeping or cleanup entry for retained snapshots
- regression coverage for expired, missing, incompatible, and cleaned payloads

#### Acceptance

- [x] Operators can distinguish valid, missing, and incompatible retained snapshots deterministically.
- [x] Snapshot cleanup behavior is explicit rather than incidental.
- [x] Restore paths fail closed when compatibility checks reject a snapshot.

### P27-CLOSE-01 - Phase 27 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P27-API-01`, `P27-CLI-01`, `P27-RT-01`
- Branch: `codex/p27-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 27 with workspace lifecycle readback and snapshot housekeeping evidence, then define the next implementation phase.

#### Deliverables

- Phase 27 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Workspace lifecycle readback and snapshot housekeeping evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 28 Task Board

### P28-STO-01 - Durable Artifact Payload Store

- Status: `Done`
- Owner: `Codex`
- Suggested role: `STORAGE`
- Depends on: `P27-CLOSE-01`
- Branch: `codex/p28-sto-01-durable-artifact-payload-store`
- Owned paths: `packages/agent-storage/`, `packages/agent-core/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a durable local artifact payload store so session artifacts no longer depend
only on model-call or tool-run index rows for operator retrieval.

#### Deliverables

- local artifact payload storage contract and SQLite-backed metadata model
- artifact retention-safe local file layout or handle abstraction
- regression coverage for store, lookup, and missing-payload behavior

#### Acceptance

- [x] Artifact payload metadata is durable and independently queryable.
- [x] Missing local artifact payloads fail closed with explicit status.
- [x] Existing artifact index readers remain backward compatible.

### P28-WKR-01 - Worker Artifact Capture Wiring

- Status: `Done`
- Owner: `Codex`
- Suggested role: `RUNTIME`
- Depends on: `P28-STO-01`
- Branch: `codex/p28-wkr-01-worker-artifact-capture-wiring`
- Owned paths: `apps/worker/`, `packages/agent-runtime/`, `packages/agent-storage/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Persist concrete artifact payload references during worker execution so durable
artifact reads can rely on more than ephemeral inline previews.

#### Deliverables

- worker-side artifact capture for supported model-call or tool-run outputs
- durable payload metadata writes during execution indexing
- regression coverage for successful capture and missing-payload fallback

#### Acceptance

- [x] Worker execution writes durable artifact payload references for supported outputs.
- [x] Existing session execution and indexing flows remain backward compatible.
- [x] Missing or skipped payload capture paths stay explicit in stored metadata.

### P28-API-01 - Artifact Detail And Retrieval Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P28-STO-01`
- Branch: `codex/p28-api-01-artifact-detail-and-retrieval`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose operator-safe artifact detail and retrieval read surfaces over the new
durable local artifact payload model.

#### Deliverables

- artifact detail or retrieval API path
- explicit not-found and payload-missing response semantics
- regression coverage for indexed-only, stored, and missing artifact reads

#### Acceptance

- [x] Operators can distinguish indexed-only versus payload-backed artifacts.
- [x] Artifact retrieval remains local-safe and machine-readable.
- [x] Existing artifact list responses remain backward compatible.

### P28-CLOSE-01 - Phase 28 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P28-STO-01`, `P28-WKR-01`, `P28-API-01`
- Branch: `codex/p28-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 28 with durable artifact storage evidence and define the next
implementation phase.

#### Deliverables

- Phase 28 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Durable artifact storage evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 29 Task Board

### P29-STO-01 - Artifact Metadata Governance

- Status: `Done`
- Owner: `Codex`
- Suggested role: `STORAGE`
- Depends on: `P28-CLOSE-01`
- Branch: `codex/p29-sto-01-artifact-metadata-governance`
- Owned paths: `packages/agent-storage/`, `packages/agent-core/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Harden local artifact metadata so retention, local availability, and safe
readback rules are explicit instead of implied by file presence alone.

#### Deliverables

- retention-aware or lifecycle-aware artifact metadata fields
- safe readback metadata for local payload availability
- regression coverage for retained, missing, and pruned artifact metadata paths

#### Acceptance

- [x] Artifact metadata exposes lifecycle state explicitly.
- [x] Missing and pruned artifact payloads remain distinguishable.
- [x] Existing artifact retrieval remains backward compatible.

### P29-CLI-01 - Artifact Inspect And Read Commands

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P28-CLOSE-01`
- Branch: `codex/p29-cli-01-artifact-inspect-and-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose artifact detail and content retrieval through CLI surfaces so local
operators do not need the HTTP API for artifact inspection.

#### Deliverables

- CLI artifact detail command
- CLI artifact content read path with machine-readable output
- regression coverage for indexed-only, payload-backed, and missing artifact reads

#### Acceptance

- [x] Operators can inspect artifact retrieval state from the CLI.
- [x] CLI content retrieval stays machine-readable and local-safe.
- [x] Existing CLI output contracts remain backward compatible.

### P29-OBS-01 - Artifact Audit And Preview Redaction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P28-CLOSE-01`
- Branch: `codex/p29-obs-01-artifact-audit-and-redaction`
- Owned paths: `packages/agent-storage/`, `apps/api/`, `tests/api/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Make artifact reads safer to operate by adding audit correlation and explicit
preview-redaction handling for retrieval surfaces.

#### Deliverables

- artifact read audit metadata or correlation fields
- preview-redaction or safe truncation rules
- regression coverage for sensitive preview and readback handling

#### Acceptance

- [x] Artifact reads are auditable by session and artifact identifier.
- [x] Preview redaction or truncation behavior is explicit and tested.
- [x] Existing artifact list and detail responses stay stable for non-sensitive cases.

### P29-CLOSE-01 - Phase 29 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P29-STO-01`, `P29-CLI-01`, `P29-OBS-01`
- Branch: `codex/p29-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 29 with artifact governance and operator parity evidence, then
define the next implementation phase.

#### Deliverables

- Phase 29 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact governance and operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 30 Task Board

### P30-POL-01 - Artifact Retention Policy Profiles

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SECURITY`
- Depends on: `P29-CLOSE-01`
- Branch: `codex/p30-pol-01-artifact-retention-profiles`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `tests/agent_core/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define deterministic local artifact retention policy contracts so later storage
cleanup and operator readback can rely on explicit policy-derived defaults.

#### Deliverables

- artifact retention profile models or policy inputs
- policy-to-retention resolution rules for local profiles
- regression coverage for stable defaulting and validation

#### Acceptance

- [x] Artifact retention defaults are explicit and deterministic.
- [x] Policy-driven retention resolution is test-covered.
- [x] Existing local-only policy flows remain backward compatible.

### P30-STO-01 - Artifact Retention Sweep And Prune Enforcement

- Status: `Done`
- Owner: `Codex`
- Suggested role: `STORAGE`
- Depends on: `P30-POL-01`
- Branch: `codex/p30-sto-01-artifact-retention-sweep`
- Owned paths: `packages/agent-storage/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Enforce artifact expiry locally by turning retention metadata into deterministic
prune behavior instead of passive recorded timestamps.

#### Deliverables

- retention sweep or prune selection path
- explicit prune reason or expiry metadata updates
- regression coverage for active, expired, and already-pruned payloads

#### Acceptance

- [x] Expired local artifact payloads can be swept deterministically.
- [x] Repeated prune attempts remain idempotent and explicit.
- [x] Non-expired payloads remain unchanged during sweep execution.

### P30-API-01 - Artifact Lifecycle Operator Readback

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P30-POL-01`, `P30-STO-01`
- Branch: `codex/p30-api-01-artifact-lifecycle-readback`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose retention and prune state through operator read surfaces so lifecycle
enforcement is inspectable without direct database access.

#### Deliverables

- lifecycle-aware artifact detail or list response fields
- operator-safe expired or pruned readback semantics
- regression coverage for active, expired, and pruned artifact inspection

#### Acceptance

- [x] Operators can inspect retention and prune metadata through the API.
- [x] Lifecycle readback remains backward compatible for active artifacts.
- [x] Expired and pruned states stay explicit and machine-readable.

### P30-CLOSE-01 - Phase 30 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P30-POL-01`, `P30-STO-01`, `P30-API-01`
- Branch: `codex/p30-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 30 with retention-enforcement evidence and define the next
implementation phase.

#### Deliverables

- Phase 30 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact retention enforcement evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 31 Task Board

### P31-SEC-01 - Artifact Access Classification Foundations

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SECURITY`
- Depends on: `P30-CLOSE-01`
- Branch: `codex/p31-sec-01-artifact-access-classification`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `tests/agent_core/`, `tests/agent_security/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Define local artifact access classes and ACL-ready metadata contracts so future
operator controls can enforce more than file-presence checks.

#### Deliverables

- artifact access class or ACL-ready domain models
- local policy-facing classification rules
- regression coverage for deterministic defaulting and validation

#### Acceptance

- [x] Artifact access classes are explicit and deterministic.
- [x] Local policy-facing classification rules are test-covered.
- [x] Existing local artifact read paths remain backward compatible.

### P31-API-01 - Artifact Manual Lifecycle Controls

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P31-SEC-01`
- Branch: `codex/p31-api-01-artifact-manual-lifecycle-controls`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add explicit operator-triggered lifecycle controls so retained local artifacts
can be pruned intentionally instead of only by retention sweep.

#### Deliverables

- manual artifact prune API path
- lifecycle-action audit metadata
- regression coverage for allowed, repeated, and unavailable prune requests

#### Acceptance

- [x] Operators can trigger explicit prune actions through the API.
- [x] Repeated prune requests remain idempotent and explicit.
- [x] Lifecycle-action responses stay machine-readable and local-safe.

### P31-CLI-01 - Artifact Lifecycle CLI Controls

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P31-API-01`
- Branch: `codex/p31-cli-01-artifact-lifecycle-controls`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose artifact lifecycle controls through CLI parity so local operators do not
need to call the HTTP API directly for manual prune flows.

#### Deliverables

- CLI artifact prune command
- machine-readable lifecycle control output
- regression coverage for successful and idempotent prune execution

#### Acceptance

- [x] Operators can trigger artifact prune from the CLI.
- [x] CLI lifecycle output stays aligned with API semantics.
- [x] Existing artifact inspection commands remain backward compatible.

### P31-CLOSE-01 - Phase 31 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P31-SEC-01`, `P31-API-01`, `P31-CLI-01`
- Branch: `codex/p31-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 31 with operator-control and access-foundation evidence, then
define the next implementation phase.

#### Deliverables

- Phase 31 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact operator-control evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 32 Task Board

### P32-API-01 - Artifact Access Read Enforcement

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P31-CLOSE-01`
- Branch: `codex/p32-api-01-artifact-access-read-enforcement`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Enforce artifact access classes on detail and content read surfaces so local
operator reads are gated by more than payload presence.

#### Deliverables

- access-class-aware artifact detail and content gating
- explicit deny semantics for policy-insufficient read attempts
- regression coverage for allowed, denied, and unavailable read paths

#### Acceptance

- [x] Artifact detail and content reads enforce access classes deterministically.
- [x] Access-denied responses stay machine-readable and local-safe.
- [x] Existing allowed read paths remain backward compatible.

### P32-CLI-01 - Artifact Access CLI Enforcement

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P32-API-01`
- Branch: `codex/p32-cli-01-artifact-access-cli-enforcement`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Align CLI artifact inspect, read, and prune behavior with the same access
enforcement semantics used by the API.

#### Deliverables

- CLI access-denied semantics for artifact reads and controls
- machine-readable CLI output aligned with API responses
- regression coverage for allowed, denied, and unavailable artifact actions

#### Acceptance

- [x] CLI artifact controls stay aligned with API access rules.
- [x] CLI access-denied responses are explicit and machine-readable.
- [x] Existing allowed artifact paths remain backward compatible.

### P32-OBS-01 - Artifact Access Audit Expansion

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P32-API-01`
- Branch: `codex/p32-obs-01-artifact-access-audit-expansion`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand audit metadata for artifact access decisions so allowed, denied, and
lifecycle actions are consistently inspectable.

#### Deliverables

- delivery-audit metadata for artifact access class and deny reason
- regression coverage for read and prune audit paths
- explicit audit vocabulary for access-denied artifact actions

#### Acceptance

- [x] Artifact access decisions are auditable by class and result.
- [x] Denied and unavailable artifact actions stay distinguishable in audit output.
- [x] Existing audit paths remain backward compatible for allowed flows.

### P32-CLOSE-01 - Phase 32 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P32-API-01`, `P32-CLI-01`, `P32-OBS-01`
- Branch: `codex/p32-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 32 with artifact access-enforcement evidence and define the next
implementation phase.

#### Deliverables

- Phase 32 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact access-enforcement evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 33 Task Board

### P33-API-01 - Artifact Access Projection Readback

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P32-CLOSE-01`
- Branch: `codex/p33-api-01-artifact-access-projection`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Project artifact access class and effective policy requirements directly into
operator read surfaces so denied and allowed paths are easier to interpret.

#### Deliverables

- additive access metadata in artifact read responses
- stable projection for access class and required policy
- regression coverage for operator-safe and sensitive artifact readback

#### Acceptance

- [x] Artifact read responses expose additive access metadata.
- [x] Access projection stays backward compatible for existing clients.
- [x] Sensitive and operator-safe artifacts remain distinguishable in readback.

### P33-CLI-01 - Artifact Access Explainability Parity

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P33-API-01`
- Branch: `codex/p33-cli-01-artifact-access-explainability`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Align CLI inspect and read output with the same access explainability metadata
used by the API.

#### Deliverables

- CLI access metadata for inspect or read paths
- explicit machine-readable explainability output
- regression coverage for allowed and denied artifact access flows

#### Acceptance

- [x] CLI artifact inspect or read output stays aligned with API access metadata.
- [x] Denied artifact access remains explicit and machine-readable in CLI output.
- [x] Existing allowed artifact output remains backward compatible.

### P33-DOC-01 - Artifact Access Operator Guidance

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P33-API-01`, `P33-CLI-01`
- Branch: `codex/p33-doc-01-artifact-access-operator-guidance`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Document operator remediation and policy expectations for denied artifact access
paths.

#### Deliverables

- operator guidance for denied artifact reads
- remediation notes for policy escalation versus unavailable payloads
- updated repository status and guidance pointers

#### Acceptance

- [x] Operator guidance explains denied versus unavailable artifact paths.
- [x] Remediation steps are explicit for local policy escalation.
- [x] Repository guidance stays aligned with implemented access behavior.

### P33-CLOSE-01 - Phase 33 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P33-API-01`, `P33-CLI-01`, `P33-DOC-01`
- Branch: `codex/p33-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 33 with artifact access explainability evidence and define the next
implementation phase.

#### Deliverables

- Phase 33 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact access explainability evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 34 Task Board

### P34-API-01 - Artifact Access Projection Consolidation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P33-CLOSE-01`
- Branch: `codex/p34-api-01-artifact-access-consolidation`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Consolidate artifact access projection helpers so API read paths stop duplicating
explainability wiring and remain easier to extend safely.

#### Deliverables

- shared artifact access projection helper usage across API read surfaces
- reduced duplication in artifact response assembly
- regression coverage for unchanged artifact access payload contracts

#### Acceptance

- [x] API artifact access projection wiring is centralized and deterministic.
- [x] Existing artifact access response payloads remain backward compatible.
- [x] Regression coverage protects the shared access projection contract.

### P34-CLI-01 - Artifact Access CLI Shared Projection Reuse

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P34-API-01`
- Branch: `codex/p34-cli-01-artifact-access-cli-shared-projection`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Reduce CLI-specific access explainability duplication by reusing the same
projection vocabulary and helper patterns as the API.

#### Deliverables

- CLI access projection reuse or normalization
- regression coverage for unchanged CLI artifact contracts
- explicit alignment notes for API versus CLI access payloads

#### Acceptance

- [x] CLI artifact access projection stays aligned with API semantics.
- [x] Shared explainability vocabulary is deterministic across local surfaces.
- [x] Existing CLI artifact payloads remain backward compatible.

### P34-TEST-01 - Artifact Access Contract Regression Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P34-API-01`, `P34-CLI-01`
- Branch: `codex/p34-test-01-artifact-access-contract-matrix`
- Owned paths: `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Harden the artifact access explainability contract with a dedicated regression
matrix that covers API, CLI, allowed, denied, and unavailable paths together.

#### Deliverables

- shared regression matrix for artifact access projection
- explicit coverage for additive metadata stability
- documentation notes for contract expectations

#### Acceptance

- [x] Artifact access projection regressions are covered across API and CLI.
- [x] Allowed, denied, and unavailable paths remain distinguishable in tests.
- [x] Additive explainability metadata stays stable across future refactors.

### P34-CLOSE-01 - Phase 34 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P34-API-01`, `P34-CLI-01`, `P34-TEST-01`
- Branch: `codex/p34-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 34 with artifact access consolidation evidence and define the next
implementation phase.

#### Deliverables

- Phase 34 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact access consolidation evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 35 Task Board

### P35-API-01 - Artifact Success Envelope Normalization

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P34-CLOSE-01`
- Branch: `codex/p35-api-01-artifact-success-envelope-normalization`
- Owned paths: `apps/api/`, `tests/api/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Normalize successful API artifact response envelopes so contract consumers do
not have to special-case missing success metadata compared with CLI output.

#### Deliverables

- explicit success-status normalization for artifact content or detail responses
- regression coverage for additive, backward-compatible API success envelopes
- documentation notes for normalized operator-facing success payloads

#### Acceptance

- [x] Successful API artifact responses expose a deterministic envelope.
- [x] The normalization remains additive and backward compatible.
- [x] Regression coverage protects the normalized API success contract.

### P35-CLI-01 - Artifact Envelope Consistency Parity

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P35-API-01`
- Branch: `codex/p35-cli-01-artifact-envelope-consistency-parity`
- Owned paths: `apps/cli/`, `tests/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Keep CLI artifact success and failure envelopes explicitly aligned with the
normalized API contract where local operator semantics should match.

#### Deliverables

- CLI envelope normalization or explicit parity assertions
- regression coverage for unchanged machine-readable CLI semantics
- documented alignment boundaries between API and CLI artifact outputs

#### Acceptance

- [x] CLI artifact envelopes stay aligned with normalized API semantics.
- [x] Existing machine-readable CLI contracts remain backward compatible.
- [x] Alignment boundaries are explicit in tests or docs.

### P35-TEST-01 - Artifact Envelope Contract Matrix Expansion

- Status: `Done`
- Owner: `Codex`
- Suggested role: `QA`
- Depends on: `P35-API-01`, `P35-CLI-01`
- Branch: `codex/p35-test-01-artifact-envelope-contract-matrix`
- Owned paths: `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand the Phase 34 access matrix into a broader artifact envelope matrix that
locks success-shape parity in addition to access explainability payloads.

#### Deliverables

- cross-surface success-envelope regression matrix
- assertions for additive status or metadata normalization
- documentation notes for envelope compatibility expectations

#### Acceptance

- [x] Artifact envelope regressions are covered across API and CLI.
- [x] Success-shape parity is explicit and test-protected.
- [x] Additive normalization remains backward compatible.

### P35-CLOSE-01 - Phase 35 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P35-API-01`, `P35-CLI-01`, `P35-TEST-01`
- Branch: `codex/p35-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 35 with artifact envelope normalization evidence and define the
next implementation phase.

#### Deliverables

- Phase 35 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact envelope normalization evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 36 Task Board

### P36-STO-01 - Shared Artifact Projection Serializer

- Status: `Done`
- Owner: `Codex`
- Suggested role: `STORAGE`
- Depends on: `P35-CLOSE-01`
- Branch: `codex/p36-sto-01-shared-artifact-projection-serializer`
- Owned paths: `packages/agent-storage/`, `tests/agent_storage/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extract a reusable artifact projection serializer so API and CLI adapters stop
duplicating retrieval, lifecycle, and shared envelope assembly rules.

#### Deliverables

- shared artifact projection or serializer helper
- deterministic projection for retrieval and lifecycle fields
- regression coverage for serializer output stability

#### Acceptance

- [x] Shared artifact projection logic is reusable and deterministic.
- [x] Retrieval and lifecycle semantics are preserved.
- [x] Regression coverage protects the serializer boundary.

### P36-API-01 - API Adapter Shared Projection Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P36-STO-01`
- Branch: `codex/p36-api-01-artifact-projection-adoption`
- Owned paths: `apps/api/`, `tests/api/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt the shared artifact projection serializer in API read adapters without
changing the current operator-facing contract.

#### Deliverables

- API adapter wiring to the shared projection helper
- regression coverage for unchanged API artifact envelopes
- documentation notes for adapter-level contract preservation

#### Acceptance

- [x] API artifact read adapters use the shared projection path.
- [x] Existing API artifact envelopes remain backward compatible.
- [x] Adapter-level regression coverage stays green.

### P36-CLI-01 - CLI Adapter Shared Projection Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P36-STO-01`
- Branch: `codex/p36-cli-01-artifact-projection-adoption`
- Owned paths: `apps/cli/`, `tests/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt the shared artifact projection serializer in CLI read adapters while
preserving CLI-only local operator context fields.

#### Deliverables

- CLI adapter wiring to the shared projection helper
- regression coverage for unchanged CLI machine-readable envelopes
- explicit handling of CLI-only local context fields outside shared parity

#### Acceptance

- [x] CLI artifact read adapters use the shared projection path.
- [x] CLI-only local context fields remain explicit and backward compatible.
- [x] Regression coverage protects shared versus CLI-only boundaries.

### P36-CLOSE-01 - Phase 36 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P36-STO-01`, `P36-API-01`, `P36-CLI-01`
- Branch: `codex/p36-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 36 with shared artifact projection evidence and define the next
implementation phase.

#### Deliverables

- Phase 36 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared artifact projection evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 37 Task Board

### P37-SEC-01 - Shared Artifact Access Projection Serializer

- Status: `Done`
- Owner: `Codex`
- Suggested role: `SECURITY`
- Depends on: `P36-CLOSE-01`
- Branch: `codex/p37-sec-01-shared-artifact-access-projection`
- Owned paths: `packages/agent-security/`, `tests/agent_security/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extract a reusable artifact access projection helper so API and CLI adapters
stop duplicating access-class explainability and policy-facing access checks.

#### Deliverables

- shared artifact access projection helper
- deterministic explainability payload for access class and policy requirements
- regression coverage for access projection stability

#### Acceptance

- [x] Shared artifact access projection logic is reusable and deterministic.
- [x] Access explainability payload semantics are preserved.
- [x] Regression coverage protects the access projection boundary.

### P37-API-01 - API Shared Access Projection Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P37-SEC-01`
- Branch: `codex/p37-api-01-artifact-access-projection-adoption`
- Owned paths: `apps/api/`, `tests/api/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt the shared artifact access projection helper in API adapters without
changing the current operator-facing access contract.

#### Deliverables

- API access projection wiring to the shared helper
- regression coverage for unchanged access payloads and audit behavior
- documentation notes for adapter-level access contract preservation

#### Acceptance

- [x] API access projection uses the shared helper path.
- [x] Existing API access payloads remain backward compatible.
- [x] Adapter-level regression coverage stays green.

### P37-CLI-01 - CLI Shared Access Projection Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P37-SEC-01`
- Branch: `codex/p37-cli-01-artifact-access-projection-adoption`
- Owned paths: `apps/cli/`, `tests/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt the shared artifact access projection helper in CLI adapters while
preserving CLI-only local operator context fields.

#### Deliverables

- CLI access projection wiring to the shared helper
- regression coverage for unchanged CLI machine-readable access envelopes
- explicit handling of CLI-only local context outside shared access payloads

#### Acceptance

- [x] CLI access projection uses the shared helper path.
- [x] CLI-only local context fields remain explicit and backward compatible.
- [x] Regression coverage protects shared versus CLI-only access boundaries.

### P37-CLOSE-01 - Phase 37 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P37-SEC-01`, `P37-API-01`, `P37-CLI-01`
- Branch: `codex/p37-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 37 with shared artifact access projection evidence and define the
next implementation phase.

#### Deliverables

- Phase 37 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared artifact access projection evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 38 Task Board

### P38-OBS-01 - Shared Artifact Access Audit Metadata Helper

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P37-CLOSE-01`
- Branch: `codex/p38-obs-01-artifact-access-audit-helper`
- Owned paths: `apps/api/`, `packages/agent-security/`, `tests/api/`, `tests/agent_security/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extract a reusable artifact access audit-metadata helper so API read and prune
paths stop duplicating access result metadata assembly.

#### Deliverables

- shared artifact access audit metadata helper
- deterministic metadata projection for allow, deny, and unavailable cases
- regression coverage for audit metadata stability

#### Acceptance

- [x] Shared access audit metadata logic is reusable and deterministic.
- [x] Existing audit metadata semantics remain backward compatible.
- [x] Regression coverage protects the audit metadata boundary.

### P38-API-01 - API Shared Denial Response Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P38-OBS-01`
- Branch: `codex/p38-api-01-artifact-denial-response-adoption`
- Owned paths: `apps/api/`, `tests/api/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt shared denial and unavailable artifact response shaping in API adapters
without changing the current operator-facing access contract.

#### Deliverables

- API adoption of shared denial or unavailable response helper paths
- regression coverage for unchanged API access payloads and deny semantics
- documentation notes for adapter-level denial contract preservation

#### Acceptance

- [x] API denial and unavailable response shaping uses the shared helper path.
- [x] Existing API access payloads remain backward compatible.
- [x] Adapter-level regression coverage stays green.

### P38-CLOSE-01 - Phase 38 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P38-OBS-01`, `P38-API-01`
- Branch: `codex/p38-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 38 with shared artifact audit-metadata evidence and define the
next implementation phase.

#### Deliverables

- Phase 38 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared artifact audit-metadata evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 39 Task Board

### P39-CLI-01 - CLI Shared Denial Response Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P38-CLOSE-01`
- Branch: `codex/p39-cli-01-artifact-denial-response-adoption`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt shared denial and unavailable artifact response helper paths in the CLI
adapter while preserving CLI-local operator context fields and prune behavior.

#### Deliverables

- CLI adoption of shared denial or unavailable response helper paths
- preservation of CLI-local `database` context and current prune contracts
- regression coverage for unchanged CLI deny and unavailable payloads

#### Acceptance

- [x] CLI denial and unavailable response shaping uses the shared helper path.
- [x] Existing CLI response payloads remain backward compatible.
- [x] CLI-local operator context fields stay explicit.

### P39-TEST-01 - Artifact Failure Contract Matrix Expansion

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P39-CLI-01`
- Branch: `codex/p39-test-01-artifact-failure-contract-matrix`
- Owned paths: `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand cross-surface contract coverage so shared artifact failure-envelope
reuse across API and CLI stays stable after CLI adoption.

#### Deliverables

- expanded artifact failure contract matrix
- explicit parity coverage for deny and unavailable responses
- documentation notes for cross-surface failure-envelope expectations

#### Acceptance

- [x] Cross-surface failure-envelope parity is covered explicitly.
- [x] Shared helper adoption stays backward compatible across API and CLI.
- [x] Regression coverage stays green after matrix expansion.

### P39-CLOSE-01 - Phase 39 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P39-CLI-01`, `P39-TEST-01`
- Branch: `codex/p39-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 39 with CLI denial-response reuse evidence and define the next
implementation phase.

#### Deliverables

- Phase 39 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] CLI denial-response reuse evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 40 Task Board

### P40-API-01 - API Shared Artifact Control Response Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P39-CLOSE-01`
- Branch: `codex/p40-api-01-artifact-control-response-adoption`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt shared prune denied and unavailable response helper paths in API control
adapters without changing the current operator-facing prune contract.

#### Deliverables

- API adoption of shared prune deny or unavailable response helper paths
- preservation of current API prune payloads and semantics
- regression coverage for unchanged API prune contracts

#### Acceptance

- [x] API prune denied and unavailable response shaping uses the shared helper path.
- [x] Existing API prune payloads remain backward compatible.
- [x] API prune regression coverage stays green.

### P40-CLI-01 - CLI Shared Artifact Control Response Adoption

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P40-API-01`
- Branch: `codex/p40-cli-01-artifact-control-response-adoption`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt shared prune denied and unavailable response helper paths in CLI control
adapters while preserving CLI-local `database` context and current prune
contracts.

#### Deliverables

- CLI adoption of shared prune deny or unavailable response helper paths
- preservation of CLI-local context and current prune semantics
- regression coverage for unchanged CLI prune payloads

#### Acceptance

- [x] CLI prune denied and unavailable response shaping uses the shared helper path.
- [x] Existing CLI prune payloads remain backward compatible.
- [x] CLI-local context fields stay explicit.

### P40-TEST-01 - Artifact Prune Contract Matrix Expansion

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P40-API-01`, `P40-CLI-01`
- Branch: `codex/p40-test-01-artifact-prune-contract-matrix`
- Owned paths: `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand cross-surface control contract coverage so shared prune-response reuse
across API and CLI stays stable after adapter adoption.

#### Deliverables

- expanded artifact prune contract matrix
- explicit parity coverage for prune denied and unavailable responses
- documentation notes for cross-surface prune-control expectations

#### Acceptance

- [x] Cross-surface prune contract parity is covered explicitly.
- [x] Shared prune helper adoption stays backward compatible across API and CLI.
- [x] Regression coverage stays green after matrix expansion.

### P40-CLOSE-01 - Phase 40 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P40-API-01`, `P40-CLI-01`, `P40-TEST-01`
- Branch: `codex/p40-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 40 with shared prune-control response evidence and define the next
implementation phase.

#### Deliverables

- Phase 40 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared prune-control response evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 41 Task Board

### P41-API-01 - API Shared Artifact Control Success Projection

- Status: `Done`
- Owner: `Codex`
- Suggested role: `API`
- Depends on: `P40-CLOSE-01`
- Branch: `codex/p41-api-01-artifact-control-success-projection`
- Owned paths: `apps/api/`, `tests/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt a shared prune success projection path in API control adapters without
changing the current operator-facing success contract.

#### Deliverables

- API adoption of shared prune success response projection helper paths
- preservation of current API prune success payloads and lifecycle semantics
- regression coverage for unchanged API prune success contracts

#### Acceptance

- [x] API prune success response shaping uses the shared helper path.
- [x] Existing API prune success payloads remain backward compatible.
- [x] API prune success regression coverage stays green.

### P41-CLI-01 - CLI Shared Artifact Control Success Projection

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CLI`
- Depends on: `P41-API-01`
- Branch: `codex/p41-cli-01-artifact-control-success-projection`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Adopt a shared prune success projection path in CLI control adapters while
preserving CLI-local operator context fields.

#### Deliverables

- CLI adoption of shared prune success response projection helper paths
- preservation of CLI-local `database` context and current success semantics
- regression coverage for unchanged CLI prune success contracts

#### Acceptance

- [x] CLI prune success response shaping uses the shared helper path.
- [x] Existing CLI prune success payloads remain backward compatible.
- [x] CLI-local context fields stay explicit.

### P41-TEST-01 - Artifact Prune Success Contract Matrix Expansion

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `TEST`
- Depends on: `P41-API-01`, `P41-CLI-01`
- Branch: `codex/p41-test-01-artifact-prune-success-contract-matrix`
- Owned paths: `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand cross-surface control contract coverage so shared prune success
projection reuse across API and CLI stays stable after adapter adoption.

#### Deliverables

- expanded artifact prune success contract matrix
- explicit parity coverage for `pruned` and `already_pruned` responses
- documentation notes for cross-surface prune success expectations

#### Acceptance

- [x] Cross-surface prune success parity is covered explicitly.
- [x] Shared prune success helper adoption stays backward compatible across API and CLI.
- [x] Regression coverage stays green after matrix expansion.

### P41-CLOSE-01 - Phase 41 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P41-API-01`, `P41-CLI-01`, `P41-TEST-01`
- Branch: `codex/p41-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 41 with shared prune success projection evidence and define the
next implementation phase.

#### Deliverables

- Phase 41 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared prune success projection evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 42 Task Board

### P42-OBS-01 - Shared Artifact Control Audit Metadata Helper

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P41-CLOSE-01`
- Branch: `codex/p42-obs-01-artifact-control-audit-helper`
- Owned paths: `apps/api/`, `apps/cli/`, `packages/agent-security/`, `tests/api/`, `tests/cli/`, `tests/agent_security/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extract a shared artifact control audit-metadata helper so prune success and
failure audit payload assembly stops drifting across API and CLI adapters.

#### Deliverables

- shared artifact control audit metadata helper
- deterministic metadata projection for prune success, denied, and unavailable cases
- regression coverage for audit metadata stability

#### Acceptance

- [x] Shared control audit metadata logic is reusable and deterministic.
- [x] Existing prune audit metadata semantics remain backward compatible.
- [x] Regression coverage protects the control audit metadata boundary.

### P42-CLOSE-01 - Phase 42 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P42-OBS-01`
- Branch: `codex/p42-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 42 with shared control audit-metadata evidence and define the next
implementation phase.

#### Deliverables

- Phase 42 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared control audit-metadata evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 43 Task Board

### P43-OBS-01 - Shared Artifact Audit Metadata Convergence

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OBS`
- Depends on: `P42-CLOSE-01`
- Branch: `codex/p43-obs-01-artifact-audit-convergence`
- Owned paths: `apps/api/`, `packages/agent-security/`, `tests/api/`, `tests/agent_security/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Converge overlapping read-side and control-side artifact audit helper
semantics so artifact audit metadata has a clearer single vocabulary boundary.

#### Deliverables

- converged shared artifact audit metadata helper boundary
- preservation of current API artifact audit semantics
- regression coverage for stable read and control audit metadata

#### Acceptance

- [x] Shared artifact audit metadata helper semantics are converged and deterministic.
- [x] Existing artifact audit metadata contracts remain backward compatible.
- [x] Regression coverage protects the converged audit boundary.

### P43-CLOSE-01 - Phase 43 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P43-OBS-01`
- Branch: `codex/p43-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 43 with shared artifact audit convergence evidence and define the
next implementation phase.

#### Deliverables

- Phase 43 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Shared artifact audit convergence evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 44 Task Board

### P44-TEST-01 - Artifact Audit Metadata Contract Coverage

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P43-CLOSE-01`
- Branch: `codex/p44-test-01-artifact-audit-contract-coverage`
- Owned paths: `tests/`, `apps/api/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add explicit regression coverage for artifact delivery-audit payload semantics
so read-side and control-side audit metadata boundaries stay stable.

#### Deliverables

- artifact audit metadata contract coverage
- stable normalization rules for non-deterministic audit fields when needed
- documentation notes for preserved audit metadata boundaries

#### Acceptance

- [x] Artifact audit metadata contract coverage is explicit and stable.
- [x] Existing audit metadata semantics remain backward compatible.
- [x] Regression coverage stays green after audit contract expansion.

### P44-CLOSE-01 - Phase 44 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P44-TEST-01`
- Branch: `codex/p44-closeout-next-plan-clean`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 44 with artifact audit contract evidence and define the next
implementation phase.

#### Deliverables

- Phase 44 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Artifact audit contract evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 45 Task Board

### P45-CLI-01 - Delivery Audit CLI Read Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P44-CLOSE-01`
- Branch: `codex/p45-cli-01-delivery-audit-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI read surface for session delivery-audit inspection so
operators do not need the HTTP API for routine audit lookup.

#### Deliverables

- CLI command for session delivery-audit inspection
- machine-readable local output for delivery-audit records
- regression coverage for populated, empty, and missing-session audit reads

#### Acceptance

- [x] Operators can inspect one session's delivery-audit history from the CLI.
- [x] Missing-session and empty-history semantics stay explicit and machine-readable.
- [x] Existing API delivery-audit behavior remains backward compatible.

### P45-TEST-01 - Delivery Audit Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P45-CLI-01`
- Branch: `codex/p45-test-01-delivery-audit-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI delivery-audit output so future
audit-surface changes do not drift across operators' read paths.

#### Deliverables

- cross-surface delivery-audit regression matrix
- normalization rules for non-deterministic audit fields when needed
- documented parity boundary for API and CLI audit reads

#### Acceptance

- [x] API and CLI delivery-audit output parity is explicit and regression-tested.
- [x] Stable audit fields stay locked without overfitting transient timestamps.
- [x] Artifact and SCM audit records remain backward compatible across both surfaces.

### P45-CLOSE-01 - Phase 45 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P45-TEST-01`
- Branch: `codex/p45-closeout-next-plan-clean`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 45 with delivery-audit operator parity evidence and define the
next implementation phase.

#### Deliverables

- Phase 45 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Delivery-audit operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 46 Task Board

### P46-CLI-01 - Session Diff CLI Read Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P45-CLOSE-01`
- Branch: `codex/p46-cli-01-session-diff-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI read surface for session workspace diff inspection so
operators do not need the HTTP API for routine diff lookup.

#### Deliverables

- CLI command for session diff inspection
- machine-readable local output for clean, dirty, and unavailable diff states
- regression coverage for missing-session and non-git workspace diff reads

#### Acceptance

- [x] Operators can inspect one session workspace diff from the CLI.
- [x] Clean, dirty, and unavailable diff states stay explicit and machine-readable.
- [x] Existing API diff behavior remains backward compatible.

### P46-TEST-01 - Session Diff Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P46-CLI-01`
- Branch: `codex/p46-test-01-session-diff-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session diff output so future
workspace-inspection changes do not drift across operator read paths.

#### Deliverables

- cross-surface session diff regression matrix
- normalization rules for non-deterministic diff context when needed
- documented parity boundary for API and CLI diff reads

#### Acceptance

- [x] API and CLI session diff output parity is explicit and regression-tested.
- [x] Stable diff fields stay locked without overfitting local path noise.
- [x] Clean, dirty, and unavailable diff states remain backward compatible across both surfaces.

### P46-CLOSE-01 - Phase 46 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P46-TEST-01`
- Branch: `codex/p46-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 46 with session diff operator parity evidence and define the next
implementation phase.

#### Deliverables

- Phase 46 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session diff operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 47 Task Board

### P47-CLI-01 - Session Stream CLI Read Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P46-CLOSE-01`
- Branch: `codex/p47-cli-01-session-stream-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI read surface for session event-stream inspection so
operators do not need the HTTP API for routine persisted replay lookup.

#### Deliverables

- CLI command for session stream inspection
- machine-readable local output for ordered persisted session events
- regression coverage for missing-session and bootstrap-only stream reads

#### Acceptance

- [x] Operators can inspect one session event stream from the CLI.
- [x] Ordered event replay stays explicit and machine-readable.
- [x] Existing API stream behavior remains backward compatible.

### P47-TEST-01 - Session Stream Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P47-CLI-01`
- Branch: `codex/p47-test-01-session-stream-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API event replay and CLI session stream output
so future operator replay changes do not drift across read paths.

#### Deliverables

- cross-surface session stream regression matrix
- normalization rules for SSE frame versus CLI JSON event-list context
- documented parity boundary for API and CLI stream reads

#### Acceptance

- [x] API and CLI session stream output parity is explicit and regression-tested.
- [x] Stable event fields stay locked without overfitting transport-specific framing.
- [x] Bootstrap-only and later event replay remain backward compatible across both surfaces.

### P47-CLOSE-01 - Phase 47 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P47-TEST-01`
- Branch: `codex/p47-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 47 with session stream operator parity evidence and define the next
implementation phase.

#### Deliverables

- Phase 47 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session stream operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 48 Task Board

### P48-CLI-01 - Session Commit CLI Delivery Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P47-CLOSE-01`
- Branch: `codex/p48-cli-01-session-commit-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI control surface for session commit execution so operators do
not need the HTTP API for routine local delivery completion.

#### Deliverables

- CLI command for session commit execution
- machine-readable local output for committed, unavailable, policy-blocked, and
  missing-session commit paths
- regression coverage for idempotent replay and invalid commit payload handling

#### Acceptance

- [x] Operators can create one session commit from the CLI.
- [x] Commit success and failure states stay explicit and machine-readable.
- [x] Existing API commit behavior remains backward compatible.

### P48-TEST-01 - Session Commit Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P48-CLI-01`
- Branch: `codex/p48-test-01-session-commit-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session commit output so future
local delivery changes do not drift across operator control paths.

#### Deliverables

- cross-surface session commit regression matrix
- normalization rules for CLI-local context and idempotency replay metadata
- documented parity boundary for API and CLI commit results

#### Acceptance

- [x] API and CLI session commit output parity is explicit and regression-tested.
- [x] Stable commit result fields stay locked without overfitting transport-specific context.
- [x] Success, unavailable, missing-session, and idempotent replay paths remain backward compatible across both surfaces.

### P48-CLOSE-01 - Phase 48 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P48-TEST-01`
- Branch: `codex/p48-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 48 with session commit operator parity evidence and define the next
implementation phase.

#### Deliverables

- Phase 48 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session commit operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 49 Task Board

### P49-CLI-01 - Session Pull Request CLI Delivery Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P48-CLOSE-01`
- Branch: `codex/p49-cli-01-session-pull-request-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI control surface for session pull-request planning and
guarded execution so operators do not need the HTTP API for routine local SCM
delivery completion.

#### Deliverables

- CLI command for session pull-request execution
- machine-readable local output for dry-run, created, unavailable,
  policy-blocked, and missing-session pull-request paths
- regression coverage for idempotent replay and invalid pull-request payload
  handling

#### Acceptance

- [x] Operators can open one session pull request from the CLI.
- [x] Pull-request success and failure states stay explicit and machine-readable.
- [x] Existing API pull-request behavior remains backward compatible.

### P49-TEST-01 - Session Pull Request Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P49-CLI-01`
- Branch: `codex/p49-test-01-session-pull-request-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session pull-request output so
future delivery changes do not drift across operator control paths.

#### Deliverables

- cross-surface session pull-request regression matrix
- normalization rules for CLI-local context and transport-specific request
  metadata
- documented parity boundary for API and CLI pull-request results

#### Acceptance

- [x] API and CLI session pull-request output parity is explicit and regression-tested.
- [x] Stable pull-request result fields stay locked without overfitting transport-specific context.
- [x] Dry-run, created, unavailable, missing-session, and idempotent replay paths remain backward compatible across both surfaces.

### P49-CLOSE-01 - Phase 49 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P49-TEST-01`
- Branch: `codex/p49-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 49 with session pull-request operator parity evidence and define
the next implementation phase.

#### Deliverables

- Phase 49 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session pull-request operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 50 Task Board

### P50-CLI-01 - Approval Queue CLI Read Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P49-CLOSE-01`
- Branch: `codex/p50-cli-01-approval-queue-read`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose local CLI read surfaces for approval queue and approval detail inspection
so operators do not need the HTTP API for routine approval triage.

#### Deliverables

- CLI command for approval queue inspection
- CLI command for approval detail inspection
- machine-readable local output for waiting-approval list, detail, and
  missing-approval paths
- regression coverage for queue and detail CLI reads

#### Acceptance

- [x] Operators can inspect the waiting approval queue from the CLI.
- [x] Operators can inspect one approval detail from the CLI.
- [x] Existing API approval read behavior remains backward compatible.

### P50-TEST-01 - Approval Queue Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P50-CLI-01`
- Branch: `codex/p50-test-01-approval-queue-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI approval queue or detail output so
future approval-read changes do not drift across operator control paths.

#### Deliverables

- cross-surface approval queue and detail regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI approval reads

#### Acceptance

- [x] API and CLI approval queue or detail output parity is explicit and regression-tested.
- [x] Stable approval result fields stay locked without overfitting CLI-only context.
- [x] Waiting-approval list, detail, and missing-approval paths remain backward compatible across both surfaces.

### P50-CLOSE-01 - Phase 50 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P50-TEST-01`
- Branch: `codex/p50-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 50 with approval queue operator parity evidence and define the next
implementation phase.

#### Deliverables

- Phase 50 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Approval queue operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 51 Task Board

### P51-TEST-01 - Approval Decision Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P50-CLOSE-01`
- Branch: `codex/p51-test-01-approval-decision-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI approval decision output so
future operator decision changes do not drift across control surfaces.

#### Deliverables

- cross-surface approval decision regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI approval decision results

#### Acceptance

- [x] API and CLI approval decision output parity is explicit and regression-tested.
- [x] Grant, reject, invalid-state, and missing-session paths remain backward compatible across both surfaces.
- [x] Stable approval decision result fields stay locked without overfitting CLI-only context.

### P51-CLOSE-01 - Phase 51 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P51-TEST-01`
- Branch: `codex/p51-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 51 with approval decision operator parity evidence and define the
next implementation phase.

#### Deliverables

- Phase 51 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Approval decision operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 52 Task Board

### P52-CLI-01 - Session Message Append CLI Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P51-CLOSE-01`
- Branch: `codex/p52-cli-01-session-message-append`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI append surface for durable session continuation so
operators do not need the HTTP API for routine follow-up prompts.

#### Deliverables

- CLI command for appending one user message to an existing session
- machine-readable local output for appended, invalid-request, not-found, and
  terminal-session append paths
- regression coverage for CLI append behavior

#### Acceptance

- [x] Operators can append one more user message from the CLI.
- [x] Terminal-session append failures remain deterministic from the CLI.
- [x] Existing API append behavior remains backward compatible.

### P52-TEST-01 - Session Message Append Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P52-CLI-01`
- Branch: `codex/p52-test-01-session-message-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session message append output so
future continuation changes do not drift across operator control surfaces.

#### Deliverables

- cross-surface session message append regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI append results

#### Acceptance

- [x] API and CLI append output parity is explicit and regression-tested.
- [x] Appended, invalid-request, not-found, and terminal-session append paths remain backward compatible across both surfaces.
- [x] Stable append result fields stay locked without overfitting CLI-only context.

### P52-CLOSE-01 - Phase 52 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P52-TEST-01`
- Branch: `codex/p52-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 52 with session message append operator parity evidence and define
the next implementation phase.

#### Deliverables

- Phase 52 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session message append operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 53 Task Board

### P53-CLI-01 - Session Cancel Control Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P52-CLOSE-01`
- Branch: `codex/p53-cli-01-session-cancel`
- Owned paths: `apps/cli/`, `apps/api/`, `apps/worker/`, `tests/cli/`, `tests/api/`, `tests/worker/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local session cancel control surface by restoring the missing control
entry and wiring a local CLI path so operators do not need the HTTP API for
routine cancel actions.

#### Deliverables

- restored cancel control entry with deterministic response models
- CLI command for cancelling one existing session
- machine-readable local output for cancelled, invalid-state, and not-found
  cancel paths
- regression coverage for CLI cancel behavior

#### Acceptance

- [x] Operators can cancel one session from the CLI.
- [x] Invalid-state and missing-session cancel failures remain deterministic from the CLI.
- [x] Existing API cancel behavior is restored and remains backward compatible.

### P53-TEST-01 - Session Control Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P53-CLI-01`
- Branch: `codex/p53-test-01-session-control-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session control output so future
cancel or suspend changes do not drift across operator control surfaces.

#### Deliverables

- cross-surface session control regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI cancel and suspend results

#### Acceptance

- [x] API and CLI session control output parity is explicit and regression-tested.
- [x] Cancelled, invalid-state, missing-session, suspended, invalid-request, and not-found control paths remain backward compatible across both surfaces.
- [x] Stable control result fields stay locked without overfitting CLI-only context.

### P53-CLOSE-01 - Phase 53 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P53-TEST-01`
- Branch: `codex/p53-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 53 with session control operator parity evidence and define the
next implementation phase.

#### Deliverables

- Phase 53 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session control operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 54 Task Board

### P54-CLI-01 - Session Artifact List CLI Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P53-CLOSE-01`
- Branch: `codex/p54-cli-01-session-artifact-list`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose a local CLI artifact list surface for session-level operator inventory
so artifact discovery does not depend on the HTTP API.

#### Deliverables

- CLI command for listing session artifacts
- machine-readable local output for non-empty, empty, and missing-session
  artifact list paths
- regression coverage for CLI artifact list behavior

#### Acceptance

- [x] Operators can list session artifacts from the CLI.
- [x] Empty and missing-session artifact list paths remain deterministic from the CLI.
- [x] Existing API artifact list behavior remains backward compatible.

### P54-TEST-01 - Session Artifact List Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P54-CLI-01`
- Branch: `codex/p54-test-01-session-artifact-list-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI artifact list output so future
artifact inventory changes do not drift across operator control surfaces.

#### Deliverables

- cross-surface session artifact list regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI artifact list results

#### Acceptance

- [x] API and CLI artifact list output parity is explicit and regression-tested.
- [x] Non-empty, empty, and missing-session artifact list paths remain backward compatible across both surfaces.
- [x] Stable artifact list result fields stay locked without overfitting CLI-only context.

### P54-CLOSE-01 - Phase 54 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P54-TEST-01`
- Branch: `codex/p54-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 54 with session artifact list operator parity evidence and define
the next implementation phase.

#### Deliverables

- Phase 54 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session artifact list operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 55 Task Board

### P55-CLI-01 - Session Inspect CLI Parity Alignment

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P54-CLOSE-01`
- Branch: `codex/p55-cli-01-session-inspect-parity`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Align the local CLI inspect payload with the current API session read surface
so routine session inspection does not drift across operator entry points.

#### Deliverables

- CLI inspect parity alignment for stable API session read fields
- machine-readable local output for populated and missing-session inspect paths
- regression coverage for aligned inspect payload behavior

#### Acceptance

- [x] Operators can inspect session state from the CLI with parity-aligned output.
- [x] Stable API session read fields remain visible from the CLI where they are part of the shared operator contract.
- [x] Existing API session inspect behavior remains backward compatible.

### P55-TEST-01 - Session Inspect Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P55-CLI-01`
- Branch: `codex/p55-test-01-session-inspect-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session inspect output so future
inspection changes do not drift across operator read surfaces.

#### Deliverables

- cross-surface session inspect regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI inspect results

#### Acceptance

- [x] API and CLI session inspect output parity is explicit and regression-tested.
- [x] Populated and missing-session inspect paths remain backward compatible across both surfaces.
- [x] Stable inspect result fields stay locked without overfitting CLI-only context.

### P55-CLOSE-01 - Phase 55 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P55-TEST-01`
- Branch: `codex/p55-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 55 with session inspect operator parity evidence and define the
next implementation phase.

#### Deliverables

- Phase 55 acceptance record
- next phase starter tasks
- updated progress and README state

#### Acceptance

- [x] Session inspect operator parity evidence is recorded.
- [x] Next phase starter tasks are ready and path-scoped.

## Phase 56 Task Board

### P56-CLI-01 - Session Resume Execute CLI Parity Alignment

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CLI`
- Depends on: `P55-CLOSE-01`
- Branch: `codex/p56-cli-01-session-resume-execute-parity`
- Owned paths: `apps/cli/`, `tests/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Align local CLI `resume --execute` output and failure shaping with the current
API session resume execution surface so operator control semantics do not drift
across entry points.

#### Deliverables

- CLI resume execute parity alignment for stable API resume fields
- machine-readable local output for resumed, missing-session, invalid-request,
  lease-conflict, and not-resumable paths
- regression coverage for aligned resume execute behavior

#### Acceptance

- [x] Operators can resume execution from the CLI with parity-aligned output.
- [x] Stable API resume execute fields and failure classes remain visible from the CLI where they are part of the shared operator contract.
- [x] Existing API resume execute behavior remains backward compatible.

### P56-TEST-01 - Session Resume Execute Cross-Surface Contract Matrix

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TEST`
- Depends on: `P56-CLI-01`
- Branch: `codex/p56-test-01-session-resume-execute-contract-matrix`
- Owned paths: `tests/`, `apps/cli/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Lock stable parity rules between API and CLI session resume execute output so
future resume changes do not drift across operator control surfaces.

#### Deliverables

- cross-surface session resume execute regression matrix
- normalization rules for CLI-local context when needed
- documented parity boundary for API and CLI resume execute results

#### Acceptance

- [x] API and CLI session resume execute output parity is explicit and regression-tested.
- [x] Resumed, missing-session, invalid-request, lease-conflict, and not-resumable paths remain backward compatible across both surfaces.
- [x] Stable resume execute result fields stay locked without overfitting CLI-only context.

### P56-CLOSE-01 - Phase 56 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
 - Suggested role: `DOC`
 - Depends on: `P56-TEST-01`
 - Branch: `codex/p56-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 56 with session resume execute operator parity evidence and record the
current next-implementation planning status.

#### Deliverables

- Phase 56 acceptance record
- current implementation lane and next-priority status
- updated progress and README state

#### Acceptance

- [x] Session resume execute operator parity evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 57 Task Board

### P57-MEM-01 - Local Memory Store Foundation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P56-CLOSE-01`
- Branch: `codex/p57-mem-01-memory-store-foundation`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Establish the first durable memory foundation so Zebra Agent can persist
derived repo or user knowledge without treating memory as the source of truth
for session recovery.

#### Deliverables

- typed memory domain models for scope, lifecycle, and provenance
- core memory store Port with deterministic query inputs
- local SQLite memory store adapter with roundtrip coverage

#### Acceptance

- [x] Memory records are typed and validate scope, lifecycle, and provenance fields deterministically.
- [x] `agent-core` exposes a memory store Port without introducing Redis or network dependencies.
- [x] SQLite storage can upsert and query memory records by repo or user scope with deterministic ordering.

### P57-MEM-02 - Memory Candidate Extraction From Successful Tool Runs

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P57-MEM-01`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extract deterministic procedure-memory candidates from successful session tool
execution so later adapters can persist operator-verified workflow knowledge
without making memory a prerequisite for recovery.

#### Deliverables

- `MemoryCandidateExtracted` event contract and payload schema
- extraction service for successful `command.run` and `tests.run` events
- deterministic de-duplication and regression coverage for extracted candidates

#### Acceptance

- [x] Successful `command.run` and `tests.run` events can yield `procedure` memory candidates with provenance.
- [x] Extraction emits machine-checkable `memory_candidate_extracted` event payloads without persisting secrets or raw approval-only data.
- [x] Repeated matching tool runs within one session do not create duplicate candidates.

### P57-MEM-03 - Worker Memory Candidate Persistence Wiring

- Status: `Done`
- Owner: `Codex`
- Suggested role: `RUNTIME`
- Depends on: `P57-MEM-02`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `apps/worker/`, `packages/agent-storage/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Wire deterministic memory candidate extraction into the real worker completion
path so completed sessions persist local procedure-memory candidates and expose
the emitted session events for later inspection.

#### Deliverables

- worker execution hook for completed sessions
- local repo-scope identifier derivation from the workspace root
- regression coverage for persisted memory records and emitted session events

#### Acceptance

- [x] Worker execution persists `procedure` memory candidates after successful session completion.
- [x] Completed session event streams include `memory_candidate_extracted` after `session_completed`.
- [x] Failed sessions do not emit or persist memory candidates.

### P57-MEM-04 - Session Memory Read Surface

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OPERATOR`
- Depends on: `P57-MEM-03`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose persisted session-scoped memory inventory over the existing local API and
CLI read surfaces so operators can inspect candidate or confirmed repo memories
without opening the SQLite store directly.

#### Deliverables

- `GET /sessions/{id}/memory` local API read surface
- `zebra-agent memory <session_id>` local CLI read surface
- cross-surface regression coverage for ok, missing-session, and unavailable-scope results

#### Acceptance

- [x] Session memory reads derive repo scope from the persisted session workspace root.
- [x] API and CLI expose deterministic memory envelopes without leaking deleted records by default.
- [x] Cross-surface tests cover successful readback, missing sessions, and missing workspace scope.

### P57-MEM-05 - Memory Candidate Review Controls

- Status: `Done`
- Owner: `Codex`
- Suggested role: `OPERATOR`
- Depends on: `P57-MEM-04`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first durable operator review controls for persisted memory candidates so
local sessions can promote verified candidates to `confirmed` or mark stale
candidates as `expired` without direct SQLite edits.

#### Deliverables

- core memory review service and durable review event contract
- local API controls for confirm and expire decisions
- local CLI memory review command with API-vs-CLI contract coverage

#### Acceptance

- [x] Only `candidate` memory records can be reviewed through the operator controls.
- [x] Confirm and expire decisions persist updated memory status and append a durable session review event.
- [x] API and CLI review surfaces match on success and invalid-state envelopes.

### P57-MEM-06 - Confirmed Memory Context Injection

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-05`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `packages/agent-context/`, `packages/agent-storage/`, `packages/agent-runtime/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Inject repo-scoped confirmed memory into the local context compiler so verified
rules and procedures can influence subsequent harness runs without turning
memory into a recovery dependency.

#### Deliverables

- confirmed-memory input path on the harness context-compiler contract
- local confirmed-memory lookup helper for repo scope
- runtime, API, CLI, and worker wiring that feeds confirmed memory into the system prompt

#### Acceptance

- [x] Confirmed repo memories render into the stable section of the compiled system prompt.
- [x] Local harness execution paths use the real `LocalContextCompiler` instead of bypassing it.
- [x] API and CLI execute paths prove confirmed memory can be loaded from SQLite and injected into model requests.

### P57-MEM-07 - Confirmed Memory Ranking And Typed Prompt Labels

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-06`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `packages/agent-context/`, `packages/agent-storage/`, `packages/agent-runtime/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Keep confirmed memory useful as the stable prompt section grows by preserving
memory type semantics, ranking higher-signal records ahead of lower-signal
ones, and deduplicating exact repeats before injection.

#### Deliverables

- typed confirmed-memory input on the context-compiler and harness contracts
- deterministic repo-memory ranking helper with exact duplicate collapse
- memory-type-aware stable prompt titles across local execution surfaces

#### Acceptance

- [x] Confirmed repo memory retrieval preserves `memory_type` instead of flattening records to plain text.
- [x] Repo memory injection prefers higher-priority memory types and drops exact normalized duplicates before prompt assembly.
- [x] Stable prompt rendering labels confirmed memories by type, such as `Project Rule` and `Procedure`.

### P57-MEM-08 - Confirmed Memory Supersession On Review

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-07`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Prevent repo memory review from accumulating competing confirmed records of the
same type and scope by recording a deterministic supersession outcome when a
newer memory is confirmed.

#### Deliverables

- confirm-review conflict rule for prior confirmed memories in the same scope
- durable `superseded` state transition updates during confirm review
- API and CLI parity coverage for supersession payloads and persisted state

#### Acceptance

- [x] Confirming a candidate memory supersedes prior `confirmed` memories with the same scope and `memory_type`.
- [x] Memory review events record superseded memory identifiers when a confirm decision replaces older records.
- [x] API and CLI review surfaces preserve parity for both ordinary confirm responses and supersession cases.

### P57-MEM-09 - Doc-Derived Project Rule Candidate Extraction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-08`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Broaden memory extraction beyond `procedure` without adding a new ingestion
surface by deriving a narrow `project_rule` candidate from successful reads of
the repository governance document.

#### Deliverables

- deterministic `files.read` extraction path for root `AGENTS.md`
- `project_rule` candidate derived from the `Local Commands` section
- worker coverage proving doc-derived project-rule candidates persist on completed runs

#### Acceptance

- [x] Successful reads of root `AGENTS.md` can emit a `project_rule` candidate without relying on model summarization.
- [x] The extracted rule is constrained to explicit `Local Commands` entries and skips truncated file reads.
- [x] Worker execution persists the new `project_rule` candidate type and emits `memory_candidate_extracted` with the correct type.

### P57-MEM-10 - Doc-Derived Architecture Fact Candidate Extraction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-09`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Continue broadening derived memory beyond `procedure` and `project_rule` by
capturing one narrow class of module-boundary knowledge from the repo
governance document without introducing semantic summarization.

#### Deliverables

- `files.read` extraction path that can emit multiple doc-derived candidates from root `AGENTS.md`
- deterministic `architecture_fact` candidate derived from the package dependency boundary rules
- worker coverage proving one governance read can persist both `project_rule` and `architecture_fact` candidates

#### Acceptance

- [x] Successful reads of root `AGENTS.md` can emit an `architecture_fact` candidate from explicit package dependency rules.
- [x] A single governance-document read may persist multiple candidate types when distinct deterministic sections are present.
- [x] Worker execution persists `architecture_fact` candidates and emits `memory_candidate_extracted` with the correct type.

### P57-MEM-11 - Explicit User Preference Candidate Extraction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-10`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add the first narrow `preference` extraction path by reusing durable user
message events and only accepting explicitly marked preference statements.

#### Deliverables

- deterministic `preference` candidate extraction from `USER_MESSAGE_RECEIVED` events
- explicit message marker rule requiring `Preference:` prefix
- worker coverage proving explicit user preferences persist without depending on tool execution

#### Acceptance

- [x] Completed sessions can emit `preference` candidates from explicit user messages without relying on free-form summarization.
- [x] Preference extraction is limited to explicitly marked `Preference:` messages and ignores ordinary task prompts.
- [x] Worker execution persists `preference` candidates and emits `memory_candidate_extracted` with the correct type.

### P57-MEM-12 - Confirmed Memory Freshness Filtering

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-11`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-storage/`, `tests/agent_storage/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Prevent stale confirmed memories from entering the stable prompt context once a
memory has an explicit expiration timestamp.

#### Deliverables

- `as_of`-aware confirmed repo memory lookup
- expiration filtering before ranking, deduplication, and prompt injection
- storage-level regression coverage for expired and still-fresh confirmed memories

#### Acceptance

- [x] Confirmed repo memories with `expires_at <= as_of` are excluded from confirmed-memory lookup.
- [x] Unexpired confirmed repo memories remain eligible for ranking and injection.
- [x] Existing API, CLI, runtime, and worker callers continue to use the default current-time freshness check without changing their public contracts.

### P57-MEM-13 - Type-Aware Memory Review Conflict Policy

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-12`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Make memory review conflict handling match the growing memory type set instead
of applying one supersession rule to every confirmed memory category.

#### Deliverables

- type-aware review conflict policy for confirmed-memory supersession
- retained single-active behavior for `project_rule`, `architecture_fact`, and `procedure`
- coexistence behavior for confirmed `preference` memories with API and CLI parity coverage

#### Acceptance

- [x] Confirming `project_rule`, `architecture_fact`, and `procedure` candidates still supersedes prior confirmed records in the same scope and type.
- [x] Confirming a `preference` candidate does not supersede prior confirmed preferences in the same scope.
- [x] API and CLI review responses preserve parity for both superseding and non-superseding confirm flows.

### P57-MEM-14 - Duplicate Confirm Review Handling

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-13`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Stop confirmed-memory review from accumulating redundant duplicates when a
candidate exactly matches an already confirmed memory in the same scope and
type.

#### Deliverables

- duplicate-match detection on confirm review using normalized memory text
- duplicate confirm outcome that expires the candidate instead of creating another confirmed record
- API and CLI parity coverage exposing the matching confirmed memory id

#### Acceptance

- [x] Confirming a candidate that exactly matches an existing confirmed memory does not create a second confirmed record.
- [x] Duplicate confirm review returns the matching confirmed memory id in both the durable event payload and API/CLI responses.
- [x] Existing supersession behavior remains intact for non-duplicate confirmed replacements.

### P57-MEM-15 - Stale Doc Memory Invalidation On Governance Refresh

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-MEM-14`
- Branch: `codex/p57-mem-02-memory-candidate-extraction`
- Owned paths: `packages/agent-core/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Invalidate confirmed doc-derived memory when a later full governance-document
read shows that the previously confirmed rule or architecture fact no longer
appears in the repo source of truth.

#### Deliverables

- post-extraction stale invalidation for confirmed doc-derived memories after full root `AGENTS.md` refresh
- durable invalidation event emission using the existing memory review event contract
- worker and core coverage proving stale confirmed doc memories expire only when the governance document is fully reread

#### Acceptance

- [x] A completed session that fully rereads root `AGENTS.md` expires confirmed `project_rule` and `architecture_fact` memories that no longer appear in the extracted doc-derived candidate set.
- [x] Sessions that do not fully reread root `AGENTS.md` leave confirmed doc-derived memories untouched.
- [x] Worker execution emits durable invalidation events for stale doc-derived confirmed memories.

### P57-CLOSE-01 - Phase 57 Closeout And Phase 58 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P57-MEM-15`
- Branch: `codex/p58-mem-01-session-memory-lifecycle-readback`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 57 with local memory acceptance evidence and define the next memory
implementation lane without leaving the task registry stale.

#### Deliverables

- Phase 57 acceptance record
- synchronized progress and README state for the closed memory-foundation phase
- Phase 58 starter tasks for lifecycle visibility and broader invalidation

#### Acceptance

- [x] Phase 57 local memory foundation and governance-refresh evidence is recorded.
- [x] `docs/AGENT_TASKS.md`, `PROGRESS.md`, and `README.md` agree on the current active lane.

## Phase 58 Task Board

### P58-MEM-01 - Session Memory Lifecycle Readback

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P57-CLOSE-01`
- Branch: `codex/p58-mem-01-session-memory-lifecycle-readback`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Make session memory inventory reads explain current memory state by projecting
the latest durable memory-review metadata into both API and CLI read surfaces.

#### Deliverables

- shared memory-inventory serializer that attaches latest review lifecycle metadata by memory id
- API and CLI session-memory read surfaces exposing `last_review`
- regression coverage for ordinary memory rows and auto-expired governance-memory rows

#### Acceptance

- [x] Session memory inventory rows now include explicit `last_review` metadata when a durable review event exists.
- [x] Auto-expired governance-memory rows expose the system operator and invalidation reason on both API and CLI read paths.
- [x] API and CLI session-memory read outputs keep parity for shared lifecycle fields.

### P58-MEM-02 - Broader Stale Confirmed Memory Invalidation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P58-MEM-01`
- Branch: `codex/p58-mem-02-broader-stale-memory-invalidation`
- Owned paths: `packages/agent-core/`, `apps/worker/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Broaden the current narrow governance-refresh invalidation rule so stale
confirmed singleton repo memories can expire from deterministic re-extraction
without hard-coding only one document source.

#### Deliverables

- source-family-aware stale invalidation rules for deterministic singleton repo memories
- worker coverage proving stale invalidation still only fires after a complete eligible source refresh
- updated lifecycle notes documenting which memory types participate in auto-expiry

#### Acceptance

- [x] Stale invalidation is no longer hard-coded only to the current root `AGENTS.md` helper path.
- [x] Invalidation still stays deterministic and limited to singleton repo memory categories.
- [x] Durable invalidation events remain stable for downstream lifecycle readback.

### P58-CLOSE-01 - Phase 58 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P58-MEM-02`
- Branch: `codex/p58-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 58 with lifecycle visibility and broader invalidation evidence, then
record the next memory or operator lane.

#### Deliverables

- Phase 58 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 58 lifecycle and invalidation evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 59 Task Board

### P59-MEM-01 - Memory Source Provenance Readback

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P58-CLOSE-01`
- Branch: `codex/p59-mem-01-memory-source-provenance-readback`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expose deterministic memory source provenance on operator read surfaces so
reviewers can see where a memory came from without replaying the full event
stream.

#### Deliverables

- shared provenance serializer for memory inventory rows
- API and CLI parity coverage for provenance-bearing memory inventory payloads
- lifecycle notes documenting how provenance interacts with reviewed and auto-expired records

#### Acceptance

- [x] Session memory inventory rows expose deterministic source provenance for reviewed and candidate records.
- [x] API and CLI memory inventory outputs keep parity for shared provenance fields.
- [x] Existing lifecycle readback fields remain backward compatible.

### P59-CLOSE-01 - Phase 59 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P59-MEM-01`
- Branch: `codex/p59-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 59 with provenance readback evidence and define the next memory
scope or operator lane.

#### Deliverables

- Phase 59 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 59 provenance evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 60 Task Board

### P60-MEM-01 - User And Tenant Memory Operator Inventory

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P59-CLOSE-01`
- Branch: `codex/p60-mem-01-user-tenant-memory-inventory`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Expand operator memory readback beyond repo scope by introducing deterministic
inventory surfaces for user-scoped and tenant-scoped memory.

#### Deliverables

- shared inventory query path for repo, user, and tenant memory scopes
- API and CLI parity coverage for user and tenant memory inventory reads
- lifecycle and provenance notes documenting cross-scope differences

#### Acceptance

- [x] Operators can read user-scoped and tenant-scoped memory inventories through local API and CLI surfaces.
- [x] Shared lifecycle and provenance fields stay consistent across repo, user, and tenant scopes.
- [x] Existing repo-memory inventory contracts remain backward compatible.

### P60-CLOSE-01 - Phase 60 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P60-MEM-01`
- Branch: `codex/p60-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 60 with cross-scope memory inventory evidence and define the next
memory operator or review lane.

#### Deliverables

- Phase 60 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 60 cross-scope memory inventory evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 61 Task Board

### P61-MEM-01 - Cross-Scope Memory Review Controls

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P60-CLOSE-01`
- Branch: `codex/p61-mem-01-cross-scope-memory-review`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Extend local operator memory review beyond repo-session candidate paths so
user-scoped and tenant-scoped memory can be reviewed through explicit local
surfaces.

#### Deliverables

- shared review path for user-scoped and tenant-scoped memory records
- API and CLI parity coverage for cross-scope confirm and expire flows
- lifecycle notes documenting how cross-scope review relates to existing
  session-derived provenance

#### Acceptance

- [x] Operators can confirm or expire eligible user-scoped and tenant-scoped memory through local API and CLI surfaces.
- [x] Cross-scope review responses preserve the current lifecycle payload contract.
- [x] Existing repo-memory review behavior remains backward compatible.

### P61-CLOSE-01 - Phase 61 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P61-MEM-01`
- Branch: `codex/p61-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 61 with cross-scope review evidence and define the next operator or
memory workflow lane.

#### Deliverables

- Phase 61 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 61 cross-scope review evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 62 Task Board

### P62-MEM-01 - Scope-Aware Memory Review Queue

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P61-CLOSE-01`
- Branch: `codex/p62-mem-01-memory-review-queue`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator review throughput by introducing scope-aware memory candidate
listing and filtering before batch workflows are considered.

#### Deliverables

- shared listing path for candidate memory across repo, user, and tenant scopes
- API and CLI parity coverage for scope-aware review queue reads
- lifecycle and provenance notes documenting how queue filtering interacts with reviewed records

#### Acceptance

- [x] Operators can list pending candidate memory by scope before choosing one record to review.
- [x] API and CLI queue outputs preserve the current shared lifecycle and provenance fields where applicable.
- [x] Existing inventory and review controls remain backward compatible.

### P62-CLOSE-01 - Phase 62 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P62-MEM-01`
- Branch: `codex/p62-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 62 with scope-aware review queue evidence and define the next
operator throughput lane.

#### Deliverables

- Phase 62 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 62 review queue evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 63 Task Board

### P63-MEM-01 - Bulk Memory Review Decisions

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P62-CLOSE-01`
- Branch: `codex/p63-mem-01-bulk-memory-review-decisions`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator throughput after queue discovery by allowing explicit
multi-record confirm or expire decisions within one scope.

#### Deliverables

- shared bulk review command path over scoped candidate memory ids
- API and CLI parity coverage for bulk confirm or expire results
- deterministic partial-failure semantics that preserve existing review event contracts

#### Acceptance

- [x] Operators can confirm or expire multiple candidate memories in one scoped action.
- [x] Bulk review responses distinguish applied, skipped, and invalid records without changing current single-review behavior.
- [x] Existing queue and single-record review controls remain backward compatible.

### P63-CLOSE-01 - Phase 63 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P63-MEM-01`
- Branch: `codex/p63-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 63 with bulk review evidence and define the next operator memory
workflow lane.

#### Deliverables

- Phase 63 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 63 bulk review evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 64 Task Board

### P64-MEM-01 - Cross-Scope Memory Queue Summary

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P63-CLOSE-01`
- Branch: `codex/p64-mem-01-cross-scope-memory-queue-summary`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator visibility by surfacing pending memory counts and queue status
across repo-session, user, and tenant scopes without changing existing review
flows.

#### Deliverables

- shared queue summary read path for pending memory counts by scope
- API and CLI parity coverage for queue summary reads
- additive summary payloads that coexist with current queue detail and bulk review surfaces

#### Acceptance

- [x] Operators can read pending memory counts by scope before opening full queue detail.
- [x] API and CLI summary outputs remain additive and backward compatible with current queue and bulk review paths.
- [x] Current explicit scope boundaries remain preserved in summary reads.

### P64-CLOSE-01 - Phase 64 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P64-MEM-01`
- Branch: `codex/p64-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 64 with queue summary evidence and define the next operator memory
workflow lane.

#### Deliverables

- Phase 64 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 64 queue summary evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 65 Task Board

### P65-MEM-01 - Cross-Scope Memory Operations Overview

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P64-CLOSE-01`
- Branch: `codex/p65-mem-01-cross-scope-memory-operations-overview`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator coordination by exposing one combined local overview of memory
queue health across repo-session, user, and tenant scopes.

#### Deliverables

- shared overview read path that aggregates current queue summary signals across scopes
- API and CLI parity coverage for cross-scope overview reads
- additive overview payloads that preserve current per-scope summary and detail contracts

#### Acceptance

- [x] Operators can inspect a combined overview of queue health across supported scopes.
- [x] API and CLI overview outputs remain additive and backward compatible with current summary, queue, and bulk review paths.
- [x] Scope-specific drill-down remains possible without changing existing per-scope endpoints or commands.

### P65-CLOSE-01 - Phase 65 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P65-MEM-01`
- Branch: `codex/p65-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 65 with operator-overview evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 65 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 65 operator-overview evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 66 Task Board

### P66-MEM-01 - Memory Review Governance Signals

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P65-CLOSE-01`
- Branch: `codex/p66-mem-01-memory-review-governance-signals`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator governance decisions by exposing lightweight review activity
and backlog breakdown signals on top of the current overview surfaces.

#### Deliverables

- shared governance-signal read path for pending backlog and recent review activity
- API and CLI parity coverage for governance-signal reads
- additive payloads that preserve current overview, summary, queue, and bulk review contracts

#### Acceptance

- [x] Operators can inspect lightweight governance signals without opening full event history.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Existing scope boundaries remain explicit in the exposed governance signals.

### P66-CLOSE-01 - Phase 66 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P66-MEM-01`
- Branch: `codex/p66-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 66 with governance-signal evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 66 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 66 governance-signal evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 67 Task Board

### P67-MEM-01 - Memory Backlog Aging Signals

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P66-CLOSE-01`
- Branch: `codex/p67-mem-01-memory-backlog-aging-signals`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator prioritization by exposing deterministic backlog aging signals
for pending memory without requiring full queue inspection.

#### Deliverables

- shared aging-signal read path for oldest pending memory and age buckets
- API and CLI parity coverage for backlog aging reads
- additive payloads that preserve current governance, overview, summary, and queue contracts

#### Acceptance

- [x] Operators can inspect backlog aging signals for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Existing scope boundaries remain explicit in the exposed aging signals.

### P67-CLOSE-01 - Phase 67 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P67-MEM-01`
- Branch: `codex/p67-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 67 with backlog-aging evidence and define the next memory workflow
lane.

#### Deliverables

- Phase 67 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 67 backlog-aging evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 68 Task Board

### P68-MEM-01 - Memory Review Velocity Signals

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P67-CLOSE-01`
- Branch: `codex/p68-mem-01-memory-review-velocity-signals`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator prioritization by exposing deterministic recent review
throughput signals on top of the current governance and aging surfaces.

#### Deliverables

- shared velocity-signal read path for recent review counts and latest review windows
- API and CLI parity coverage for review-velocity reads
- additive payloads that preserve current aging, governance, overview, summary, and queue contracts

#### Acceptance

- [x] Operators can inspect recent review throughput for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Existing scope boundaries remain explicit in the exposed velocity signals.

### P68-CLOSE-01 - Phase 68 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P68-MEM-01`
- Branch: `codex/p68-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 68 with review-velocity evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 68 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 68 review-velocity evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 69 Task Board

### P69-MEM-01 - Memory Backlog Pressure Signals

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P68-CLOSE-01`
- Branch: `codex/p69-mem-01-memory-backlog-pressure-signals`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator prioritization by exposing one deterministic backlog pressure
summary that combines current backlog size, backlog aging, and recent review
throughput.

#### Deliverables

- shared pressure-signal read path for current backlog pressure classification
- API and CLI parity coverage for pressure reads
- additive payloads that preserve current velocity, aging, governance, overview, summary, and queue contracts

#### Acceptance

- [x] Operators can inspect deterministic backlog pressure signals for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Existing scope boundaries remain explicit in the exposed pressure signals.

### P69-CLOSE-01 - Phase 69 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P69-MEM-01`
- Branch: `codex/p69-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 69 with backlog-pressure evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 69 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 69 backlog-pressure evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 70 Task Board

### P70-MEM-01 - Memory Pressure Action Hints

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P69-CLOSE-01`
- Branch: `codex/p70-mem-01-memory-pressure-action-hints`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator execution by exposing deterministic action hints on top of the
current backlog pressure, aging, and review-velocity signals.

#### Deliverables

- shared action-hint read path for recommended next operator focus
- API and CLI parity coverage for action-hint reads
- additive payloads that preserve current pressure, velocity, aging, governance, overview, summary, and queue contracts

#### Acceptance

- [x] Operators can inspect deterministic action hints for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Existing scope boundaries remain explicit in the exposed action hints.

### P70-CLOSE-01 - Phase 70 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P70-MEM-01`
- Branch: `codex/p70-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 70 with pressure-action-hint evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 70 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 70 pressure-action-hint evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 71 Task Board

### P71-MEM-01 - Memory Pressure Escalation Recommendations

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P70-CLOSE-01`
- Branch: `codex/p71-mem-01-memory-pressure-escalation-recommendations`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve sustained memory-operations triage by exposing deterministic escalation
recommendations for scopes that stay stalled or repeatedly re-enter high
pressure.

#### Deliverables

- shared escalation-recommendation read path derived from current pressure and action-hint signals
- API and CLI parity coverage for escalation reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic escalation recommendations for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Escalation recommendations stay explicitly scoped and local-first.

### P71-CLOSE-01 - Phase 71 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P71-MEM-01`
- Branch: `codex/p71-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 71 with escalation evidence and define the next memory workflow
lane.

#### Deliverables

- Phase 71 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 71 escalation evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 72 Task Board

### P72-MEM-01 - Memory Escalation Follow-Up Windows

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P71-CLOSE-01`
- Branch: `codex/p72-mem-01-memory-escalation-follow-up-windows`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve escalation execution by exposing deterministic follow-up timing
guidance for scopes that remain local versus scopes that need re-check or
re-open handling.

#### Deliverables

- shared follow-up-window read path derived from current escalation and pressure signals
- API and CLI parity coverage for follow-up-window reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic follow-up windows for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Follow-up windows stay explicitly scoped and local-first.

### P72-CLOSE-01 - Phase 72 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P72-MEM-01`
- Branch: `codex/p72-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 72 with follow-up-window evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 72 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 72 follow-up-window evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 73 Task Board

### P73-MEM-01 - Memory Follow-Up Overdue Flags

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P72-CLOSE-01`
- Branch: `codex/p73-mem-01-memory-follow-up-overdue-flags`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator timing discipline by exposing deterministic overdue status for
follow-up windows that have already lapsed at read time.

#### Deliverables

- shared overdue-flag read path derived from current follow-up-window evidence
- API and CLI parity coverage for overdue-flag reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue follow-up flags for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue flags stay explicitly scoped and local-first.

### P73-CLOSE-01 - Phase 73 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P73-MEM-01`
- Branch: `codex/p73-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 73 with overdue-flag evidence and define the next memory workflow
lane.

#### Deliverables

- Phase 73 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 73 overdue-flag evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 74 Task Board

### P74-MEM-01 - Memory Overdue Age Buckets

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P73-CLOSE-01`
- Branch: `codex/p74-mem-01-memory-overdue-age-buckets`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue triage by exposing deterministic overdue age buckets for
follow-up items that have already lapsed.

#### Deliverables

- shared overdue-age read path derived from current overdue evidence
- API and CLI parity coverage for overdue-age reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue age buckets for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue age buckets stay explicitly scoped and local-first.

### P74-CLOSE-01 - Phase 74 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P74-MEM-01`
- Branch: `codex/p74-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 74 with overdue-age evidence and define the next memory workflow
lane.

#### Deliverables

- Phase 74 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 74 overdue-age evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 75 Task Board

### P75-MEM-01 - Memory Overdue Type Rollups

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P74-CLOSE-01`
- Branch: `codex/p75-mem-01-memory-overdue-type-rollups`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue triage by exposing deterministic memory-type rollups for
currently overdue scopes.

#### Deliverables

- shared overdue-type read path derived from current overdue scope evidence
- API and CLI parity coverage for overdue-type reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue memory-type rollups for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue memory-type rollups stay explicitly scoped and local-first.

### P75-CLOSE-01 - Phase 75 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P75-MEM-01`
- Branch: `codex/p75-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 75 with overdue-type evidence and define the next memory workflow
lane.

#### Deliverables

- Phase 75 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 75 overdue-type evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 76 Task Board

### P76-MEM-01 - Memory Overdue Visibility Rollups

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P75-CLOSE-01`
- Branch: `codex/p76-mem-01-memory-overdue-visibility-rollups`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue triage by exposing deterministic overdue visibility rollups for
currently overdue scopes.

#### Deliverables

- shared overdue-visibility read path derived from current overdue scope evidence
- API and CLI parity coverage for overdue-visibility reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue visibility rollups for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue visibility rollups stay explicitly scoped and local-first.

### P76-CLOSE-01 - Phase 76 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P76-MEM-01`
- Branch: `codex/p76-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 76 with overdue-visibility evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 76 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 76 overdue-visibility evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 77 Task Board

### P77-MEM-01 - Memory Overdue Trend Signals

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P76-CLOSE-01`
- Branch: `codex/p77-mem-01-memory-overdue-trend-signals`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue triage by exposing deterministic overdue trend signals for
currently overdue scopes.

#### Deliverables

- shared overdue-trend read path derived from current overdue scope evidence
- API and CLI parity coverage for overdue-trend reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue trend signals for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue trend signals stay explicitly scoped and local-first.

### P77-CLOSE-01 - Phase 77 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P77-MEM-01`
- Branch: `codex/p77-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 77 with overdue-trend evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 77 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 77 overdue-trend evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 78 Task Board

### P78-MEM-01 - Memory Overdue Intervention Hints

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P77-CLOSE-01`
- Branch: `codex/p78-mem-01-memory-overdue-intervention-hints`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue triage by exposing deterministic overdue intervention hints for
currently overdue scopes.

#### Deliverables

- shared overdue-intervention read path derived from current overdue scope evidence
- API and CLI parity coverage for overdue-intervention reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue intervention hints for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue intervention hints stay explicitly scoped and local-first.

### P78-CLOSE-01 - Phase 78 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P78-MEM-01`
- Branch: `codex/p78-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 78 with overdue-intervention evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 78 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 78 overdue-intervention evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 79 Task Board

### P79-MEM-01 - Memory Overdue Escalation Lanes

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P78-CLOSE-01`
- Branch: `codex/p79-mem-01-memory-overdue-escalation-lanes`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue triage by exposing deterministic overdue escalation lanes for
currently overdue scopes.

#### Deliverables

- shared overdue-escalation-lane read path derived from current overdue scope evidence
- API and CLI parity coverage for overdue-escalation-lane reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue escalation lanes for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue escalation lanes stay explicitly scoped and local-first.

### P79-CLOSE-01 - Phase 79 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P79-MEM-01`
- Branch: `codex/p79-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 79 with overdue-escalation-lane evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 79 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 79 overdue-escalation-lane evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 80 Task Board

### P80-MEM-01 - Memory Overdue Recovery Paths

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P79-CLOSE-01`
- Branch: `codex/p80-mem-01-memory-overdue-recovery-paths`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue recovery planning by exposing deterministic recovery paths for
currently overdue scopes after escalation-lane selection.

#### Deliverables

- shared overdue-recovery-path read path derived from current overdue escalation-lane evidence
- API and CLI parity coverage for overdue-recovery-path reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue recovery paths for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue recovery paths stay explicitly scoped and local-first.

### P80-CLOSE-01 - Phase 80 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P80-MEM-01`
- Branch: `codex/p80-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 80 with overdue-recovery-path evidence and define the next memory
workflow lane.

#### Deliverables

- Phase 80 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 80 overdue-recovery-path evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 81 Task Board

### P81-MEM-01 - Memory Overdue Resolution Checkpoints

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P80-CLOSE-01`
- Branch: `codex/p81-mem-01-memory-overdue-resolution-checkpoints`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue recovery tracking by exposing deterministic resolution
checkpoints for currently overdue scopes after recovery-path selection.

#### Deliverables

- shared overdue-resolution-checkpoint read path derived from current overdue recovery-path evidence
- API and CLI parity coverage for overdue-resolution-checkpoint reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue resolution checkpoints for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue resolution checkpoints stay explicitly scoped and local-first.

### P81-CLOSE-01 - Phase 81 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P81-MEM-01`
- Branch: `codex/p81-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 81 with overdue-resolution-checkpoint evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 81 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 81 overdue-resolution-checkpoint evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 82 Task Board

### P82-MEM-01 - Memory Overdue Resolution Outcomes

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P81-CLOSE-01`
- Branch: `codex/p82-mem-01-memory-overdue-resolution-outcomes`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue closure tracking by exposing deterministic resolution outcomes
for currently overdue scopes after resolution-checkpoint selection.

#### Deliverables

- shared overdue-resolution-outcome read path derived from current overdue resolution-checkpoint evidence
- API and CLI parity coverage for overdue-resolution-outcome reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue resolution outcomes for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue resolution outcomes stay explicitly scoped and local-first.

### P82-CLOSE-01 - Phase 82 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P82-MEM-01`
- Branch: `codex/p82-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 82 with overdue-resolution-outcome evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 82 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 82 overdue-resolution-outcome evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 83 Task Board

### P83-MEM-01 - Memory Overdue Closure Decisions

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P82-CLOSE-01`
- Branch: `codex/p83-mem-01-memory-overdue-closure-decisions`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue final handling by exposing deterministic closure decisions for
currently overdue scopes after resolution-outcome selection.

#### Deliverables

- shared overdue-closure-decision read path derived from current overdue resolution-outcome evidence
- API and CLI parity coverage for overdue-closure-decision reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue closure decisions for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue closure decisions stay explicitly scoped and local-first.

### P83-CLOSE-01 - Phase 83 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P83-MEM-01`
- Branch: `codex/p83-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 83 with overdue-closure-decision evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 83 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 83 overdue-closure-decision evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 84 Task Board

### P84-MEM-01 - Memory Overdue Archive Recommendations

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P83-CLOSE-01`
- Branch: `codex/p84-mem-01-memory-overdue-archive-recommendations`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare handling by exposing deterministic archive
recommendations for currently overdue scopes after closure-decision selection.

#### Deliverables

- shared overdue-archive-recommendation read path derived from current overdue closure-decision evidence
- API and CLI parity coverage for overdue-archive-recommendation reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue archive recommendations for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue archive recommendations stay explicitly scoped and local-first.

### P84-CLOSE-01 - Phase 84 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P84-MEM-01`
- Branch: `codex/p84-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 84 with overdue-archive-recommendation evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 84 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 84 overdue-archive-recommendation evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 85 Task Board

### P85-MEM-01 - Memory Overdue Retention Guidance

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P84-CLOSE-01`
- Branch: `codex/p85-mem-01-memory-overdue-retention-guidance`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare by exposing deterministic retention guidance for
currently overdue scopes after archive-recommendation selection.

#### Deliverables

- shared overdue-retention-guidance read path derived from current overdue archive-recommendation evidence
- API and CLI parity coverage for overdue-retention-guidance reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention guidance for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention guidance stays explicitly scoped and local-first.

### P85-CLOSE-01 - Phase 85 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P85-MEM-01`
- Branch: `codex/p85-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 85 with overdue-retention-guidance evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 85 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 85 overdue-retention-guidance evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 86 Task Board

### P86-MEM-01 - Memory Overdue Retention Windows

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P85-CLOSE-01`
- Branch: `codex/p86-mem-01-memory-overdue-retention-windows`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare timing by exposing deterministic retention windows
for currently overdue scopes after retention-guidance selection.

#### Deliverables

- shared overdue-retention-window read path derived from current overdue retention-guidance evidence
- API and CLI parity coverage for overdue-retention-window reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention windows for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention windows stay explicitly scoped and local-first.

### P86-CLOSE-01 - Phase 86 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P86-MEM-01`
- Branch: `codex/p86-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 86 with overdue-retention-window evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 86 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 86 overdue-retention-window evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 87 Task Board

### P87-MEM-01 - Memory Overdue Retention Breaches

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P86-CLOSE-01`
- Branch: `codex/p87-mem-01-memory-overdue-retention-breaches`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare escalation by exposing deterministic retention breach
classifications for currently overdue scopes after retention-window selection.

#### Deliverables

- shared overdue-retention-breach read path derived from current overdue retention-window evidence
- API and CLI parity coverage for overdue-retention-breach reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breaches for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breaches stay explicitly scoped and local-first.

### P87-CLOSE-01 - Phase 87 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P87-MEM-01`
- Branch: `codex/p87-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 87 with overdue-retention-breach evidence and define the next
memory workflow lane.

#### Deliverables

- Phase 87 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 87 overdue-retention-breach evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 88 Task Board

### P88-MEM-01 - Memory Overdue Retention Breach Aging

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P87-CLOSE-01`
- Branch: `codex/p88-mem-01-memory-overdue-retention-breach-aging`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare escalation depth by exposing deterministic retention
breach aging for currently overdue scopes after retention-breach selection.

#### Deliverables

- shared overdue-retention-breach-aging read path derived from current overdue retention-breach evidence
- API and CLI parity coverage for overdue-retention-breach-aging reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach aging for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach aging stays explicitly scoped and local-first.

### P88-CLOSE-01 - Phase 88 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P88-MEM-01`
- Branch: `codex/p88-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 88 with overdue-retention-breach-aging evidence and define the
next memory workflow lane.

#### Deliverables

- Phase 88 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 88 overdue-retention-breach-aging evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 89 Task Board

### P89-MEM-01 - Memory Overdue Retention Breach Actions

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P88-CLOSE-01`
- Branch: `codex/p89-mem-01-memory-overdue-retention-breach-actions`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare actionability by exposing deterministic retention
breach actions for currently overdue scopes after breach-aging selection.

#### Deliverables

- shared overdue-retention-breach-action read path derived from current overdue retention-breach-aging evidence
- API and CLI parity coverage for overdue-retention-breach-action reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach actions for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach actions stay explicitly scoped and local-first.

### P89-CLOSE-01 - Phase 89 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P89-MEM-01`
- Branch: `codex/p89-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 89 with overdue-retention-breach-action evidence and define the
next memory workflow lane.

#### Deliverables

- Phase 89 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 89 overdue-retention-breach-action evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 90 Task Board

### P90-MEM-01 - Memory Overdue Retention Breach Lanes

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P89-CLOSE-01`
- Branch: `codex/p90-mem-01-memory-overdue-retention-breach-lanes`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare routing by exposing deterministic retention breach
lanes for currently overdue scopes after breach-action selection.

#### Deliverables

- shared overdue-retention-breach-lane read path derived from current overdue retention-breach-action evidence
- API and CLI parity coverage for overdue-retention-breach-lane reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach lanes for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach lanes stay explicitly scoped and local-first.

### P90-CLOSE-01 - Phase 90 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P90-MEM-01`
- Branch: `codex/p90-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 90 with overdue-retention-breach-lane evidence and define the
next memory workflow lane.

#### Deliverables

- Phase 90 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 90 overdue-retention-breach-lane evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 91 Task Board

### P91-MEM-01 - Memory Overdue Retention Breach Owner Targets

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P90-CLOSE-01`
- Branch: `codex/p91-mem-01-memory-overdue-retention-breach-owner-targets`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare routing clarity by exposing deterministic retention
breach owner targets for currently overdue scopes after breach-lane selection.

#### Deliverables

- shared overdue-retention-breach-owner-target read path derived from current overdue retention-breach-lane evidence
- API and CLI parity coverage for overdue-retention-breach-owner-target reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach owner targets for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach owner targets stay explicitly scoped and local-first.

### P91-CLOSE-01 - Phase 91 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P91-MEM-01`
- Branch: `codex/p91-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 91 with overdue-retention-breach-owner-target evidence and define
the next memory workflow lane.

#### Deliverables

- Phase 91 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 91 overdue-retention-breach-owner-target evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 92 Task Board

### P92-MEM-01 - Memory Overdue Retention Breach Follow-Through Modes

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P91-CLOSE-01`
- Branch: `codex/p92-mem-01-memory-overdue-retention-breach-follow-through-modes`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare execution clarity by exposing deterministic retention
breach follow-through modes for currently overdue scopes after owner-target
selection.

#### Deliverables

- shared overdue-retention-breach-follow-through-mode read path derived from current overdue retention-breach-owner-target evidence
- API and CLI parity coverage for overdue-retention-breach-follow-through-mode reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach follow-through modes for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach follow-through modes stay explicitly scoped and local-first.

### P92-CLOSE-01 - Phase 92 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P92-MEM-01`
- Branch: `codex/p92-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 92 with overdue-retention-breach-follow-through-mode evidence and
define the next memory workflow lane.

#### Deliverables

- Phase 92 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 92 overdue-retention-breach-follow-through-mode evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 93 Task Board

### P93-MEM-01 - Memory Overdue Retention Breach Follow-Through Outcomes

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P92-CLOSE-01`
- Branch: `codex/p93-mem-01-memory-overdue-retention-breach-follow-through-outcomes`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare completion clarity by exposing deterministic
follow-through outcomes for currently overdue scopes after follow-through mode
selection.

#### Deliverables

- shared overdue-retention-breach-follow-through-outcome read path derived from current overdue retention-breach-follow-through-mode evidence
- API and CLI parity coverage for overdue-retention-breach-follow-through-outcome reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach follow-through outcomes for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach follow-through outcomes stay explicitly scoped and local-first.

### P93-CLOSE-01 - Phase 93 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P93-MEM-01`
- Branch: `codex/p93-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 93 with overdue-retention-breach-follow-through-outcome evidence
and define the next memory workflow lane.

#### Deliverables

- Phase 93 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 93 overdue-retention-breach-follow-through-outcome evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 94 Task Board

### P94-MEM-01 - Memory Overdue Retention Breach Follow-Through Completion States

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P93-CLOSE-01`
- Branch: `codex/p94-mem-01-memory-overdue-retention-breach-follow-through-completion-states`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare closure visibility by exposing deterministic
follow-through completion states for currently overdue scopes after
follow-through outcome selection.

#### Deliverables

- shared overdue-retention-breach-follow-through-completion-state read path derived from current overdue retention-breach-follow-through-outcome evidence
- API and CLI parity coverage for overdue-retention-breach-follow-through-completion-state reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach follow-through completion states for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach follow-through completion states stay explicitly scoped and local-first.

### P94-CLOSE-01 - Phase 94 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P94-MEM-01`
- Branch: `codex/p94-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 94 with overdue-retention-breach-follow-through-completion-state
evidence and define the next memory workflow lane.

#### Deliverables

- Phase 94 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 94 overdue-retention-breach-follow-through-completion-state evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 95 Task Board

### P95-MEM-01 - Memory Overdue Retention Breach Follow-Through Verification States

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CTX`
- Depends on: `P94-CLOSE-01`
- Branch: `codex/p95-mem-01-memory-overdue-retention-breach-follow-through-verification-states`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare signoff visibility by exposing deterministic
follow-through verification states for currently overdue scopes after
follow-through completion-state selection.

#### Deliverables

- shared overdue-retention-breach-follow-through-verification-state read path derived from current overdue retention-breach-follow-through-completion-state evidence
- API and CLI parity coverage for overdue-retention-breach-follow-through-verification-state reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach follow-through verification states for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach follow-through verification states stay explicitly scoped and local-first.

### P95-CLOSE-01 - Phase 95 Closeout And Next Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P95-MEM-01`
- Branch: `codex/p95-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 95 with overdue-retention-breach-follow-through-verification-state
evidence and define the next memory workflow lane.

#### Deliverables

- Phase 95 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 95 overdue-retention-breach-follow-through-verification-state evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 96 Task Board

### P96-MEM-01 - Memory Overdue Retention Breach Follow-Through Verification Outcomes

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P95-CLOSE-01`
- Branch: `codex/p96-mem-01-memory-overdue-retention-breach-follow-through-verification-outcomes`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve overdue aftercare verification result visibility by exposing
deterministic follow-through verification outcomes for currently overdue scopes
after follow-through verification-state selection.

#### Deliverables

- shared overdue-retention-breach-follow-through-verification-outcome read path derived from current overdue retention-breach-follow-through-verification-state evidence
- API and CLI parity coverage for overdue-retention-breach-follow-through-verification-outcome reads
- additive payloads that preserve current memory operation contracts and explicit scope boundaries

#### Acceptance

- [x] Operators can inspect deterministic overdue retention breach follow-through verification outcomes for supported scopes.
- [x] API and CLI outputs remain additive and backward compatible with current memory operation read paths.
- [x] Overdue retention breach follow-through verification outcomes stay explicitly scoped and local-first.

### P96-CLOSE-01 - Phase 96 Closeout And Next Planning

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `DOC`
- Depends on: `P96-MEM-01`
- Branch: `codex/p96-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 96 with overdue-retention-breach-follow-through-verification-outcome
evidence and record that this overdue-retention-breach follow-through sublane is
complete while the next memory workflow lane remains undefined.

#### Deliverables

- Phase 96 acceptance record
- current implementation lane and next-priority status
- synchronized progress and README state

#### Acceptance

- [x] Phase 96 overdue-retention-breach-follow-through-verification-outcome evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 97 Task Board

### P97-MEM-01 - Scoped Queue Sweep Review Controls

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P96-CLOSE-01`
- Branch: `codex/p97-mem-01-scoped-queue-sweep-review-controls`
- Owned paths: `apps/api/`, `apps/cli/`, `packages/agent-core/`, `packages/agent-storage/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Improve operator throughput by letting one scoped action review the current
candidate queue directly, without requiring callers to enumerate every memory
id ahead of time.

#### Deliverables

- scoped queue-sweep review controls for repo-session, user, and tenant memory
- API and CLI parity coverage for queue-sweep confirm or expire actions
- additive result payloads that preserve current single-record and explicit-id
  bulk-review contracts

#### Acceptance

- [x] Operators can confirm or expire the current scoped memory queue in one action.
- [x] Queue-sweep responses stay additive and keep current memory review semantics.
- [x] Queue-sweep controls remain explicitly scope-bound and local-first.

### P97-CLOSE-01 - Phase 97 Closeout And Next Planning

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `DOC`
- Depends on: `P97-MEM-01`
- Branch: `codex/p97-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 97 with scoped queue-sweep review evidence and synchronize the next
memory workflow priority.

#### Deliverables

- Phase 97 acceptance record
- synchronized progress and README state
- current implementation lane and next-priority decision

#### Acceptance

- [x] Phase 97 scoped queue-sweep review evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 98 Task Board

### P98-MEM-01 - Scoped Queue Sweep Preview Controls

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P97-CLOSE-01`
- Branch: `codex/p98-mem-01-scoped-queue-sweep-preview-controls`
- Owned paths: `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a no-side-effect preview surface for scoped queue-sweep review so operators
can inspect the exact candidate set that a queue confirm or expire action would
touch before executing it.

#### Deliverables

- scoped queue-sweep preview controls for repo-session, user, and tenant memory
- API and CLI parity coverage for queue-sweep preview payloads
- additive preview payloads that expose exact queued ids and records without
  mutating review state

#### Acceptance

- [x] Operators can preview the exact scoped queue-sweep target set before review.
- [x] Preview responses stay additive and side-effect free.
- [x] Repo-session preview reflects the same `source_session_id` narrowing used by queue sweep execution.

### P98-CLOSE-01 - Phase 98 Closeout And Next Planning

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `DOC`
- Depends on: `P98-MEM-01`
- Branch: `codex/p98-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 98 with scoped queue-sweep preview evidence and synchronize the
next memory workflow priority.

#### Deliverables

- Phase 98 acceptance record
- synchronized progress and README state
- current implementation lane and next-priority decision

#### Acceptance

- [x] Phase 98 scoped queue-sweep preview evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 99 Task Board

### P99-MEM-01 - Scoped Queue Sweep Dry-Run Summaries

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P98-CLOSE-01`
- Branch: `codex/p99-mem-01-scoped-queue-sweep-dry-run-summaries`
- Owned paths: `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add dry-run summary metadata to scoped queue-sweep preview responses so
operators can see not only the exact target set, but also the projected review
outcome shape before confirm or expire execution.

#### Deliverables

- dry-run summary metadata on scoped queue-sweep preview responses for repo-session, user, and tenant memory
- API and CLI parity coverage for projected queue-sweep summary payloads
- additive preview payloads that expose projected post-review status and counts without mutating review state

#### Acceptance

- [x] Operators can see projected queue-sweep outcome summaries before execution.
- [x] Dry-run summary payloads stay additive and side-effect free.
- [x] Projected summary fields stay parity-aligned across API and CLI preview surfaces.

### P99-CLOSE-01 - Phase 99 Closeout And Next Planning

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `DOC`
- Depends on: `P99-MEM-01`
- Branch: `codex/p99-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 99 with scoped queue-sweep dry-run summary evidence and synchronize
the next memory workflow priority.

#### Deliverables

- Phase 99 acceptance record
- synchronized progress and README state
- current implementation lane and next-priority decision

#### Acceptance

- [x] Phase 99 scoped queue-sweep dry-run summary evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 100 Task Board

### P100-MEM-01 - Scoped Queue Sweep Target Explanations

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P99-CLOSE-01`
- Branch: `codex/p100-mem-01-scoped-queue-sweep-target-explanations`
- Owned paths: `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add explanation metadata to scoped queue-sweep preview responses so operators
can see why each memory record is in the current preview target set.

#### Deliverables

- target explanation metadata on scoped queue-sweep preview responses for repo-session, user, and tenant memory
- API and CLI parity coverage for queue-sweep target explanation payloads
- additive preview payloads that expose per-record target reasons and aggregate explanation counts without mutating review state

#### Acceptance

- [x] Operators can inspect why each record is in the scoped queue-sweep preview target set.
- [x] Target explanation payloads stay additive and side-effect free.
- [x] Explanation fields stay parity-aligned across API and CLI preview surfaces.

### P100-CLOSE-01 - Phase 100 Closeout And Next Planning

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `DOC`
- Depends on: `P100-MEM-01`
- Branch: `codex/p100-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 100 with scoped queue-sweep target explanation evidence and synchronize
the next memory workflow priority.

#### Deliverables

- Phase 100 acceptance record
- synchronized progress and README state
- current implementation lane and next-priority decision

#### Acceptance

- [x] Phase 100 scoped queue-sweep target explanation evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 101 Task Board

### P101-MEM-01 - Scoped Queue Sweep Filtered Preview Controls

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `CTX`
- Depends on: `P100-CLOSE-01`
- Branch: `codex/p101-mem-01-scoped-queue-sweep-filtered-preview-controls`
- Owned paths: `apps/api/`, `apps/cli/`, `tests/`, `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Add a minimal filtered preview control for scoped queue-sweep preview so
operators can narrow the current target set before execution without changing
queue-sweep review semantics.

#### Deliverables

- scoped queue-sweep preview filtering for repo-session, user, and tenant memory
- API and CLI parity coverage for filtered preview payloads
- additive preview payloads that expose filter inputs and filtered counts without mutating review state

#### Acceptance

- [x] Operators can narrow preview targets with one supported filter before execution.
- [x] Filtered preview payloads stay additive and side-effect free.
- [x] Filter fields stay parity-aligned across API and CLI preview surfaces.

### P101-CLOSE-01 - Phase 101 Closeout And Next Planning

- Status: `Done`
- Owner: `Unassigned`
- Suggested role: `DOC`
- Depends on: `P101-MEM-01`
- Branch: `codex/p101-closeout-next-plan`
- Owned paths: `docs/`, `README.md`, `PROGRESS.md`, `WORKLOG.md`

#### Goal

Close Phase 101 with scoped queue-sweep filtered preview evidence and
synchronize the next memory workflow priority.

#### Deliverables

- Phase 101 acceptance record
- synchronized progress and README state
- current implementation lane and next-priority decision

#### Acceptance

- [x] Phase 101 scoped queue-sweep filtered preview evidence is recorded.
- [x] Current implementation lane and next-priority decision are synchronized in `docs/AGENT_TASKS.md`.

## Phase 102 Task Board

### P102-UI-01 - Desktop Workspace Product Foundation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P101-CLOSE-01`
- Branch: `codex/p102-ui-01-desktop-product-foundation`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Turn the desktop shell into a truthful local-first workspace foundation before
adding approval and delivery workflows.

#### Deliverables

- Codex-style idle and thread workspace with durable local task navigation
- health-backed runtime connection state instead of hard-coded availability
- explicit local API configuration entry using the existing operator config
- session-backed workspace metadata where available, with honest unavailable states
- focused frontend checks for new non-trivial state projection logic

#### Acceptance

- [x] Restarting the desktop UI restores indexed tasks and reloads session state from the API.
- [x] API connectivity is reflected truthfully in the header and project surface.
- [x] Operators can inspect and update the local API URL and bearer token from the workspace.
- [x] Workspace metadata is not presented as real Git state when no backend evidence exists.
- [x] `pnpm build` and focused frontend checks pass.

### P102-CLOSE-01 - Phase 102 Closeout And Phase 103 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P102-UI-01`
- Branch: `codex/p102-closeout-phase103-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 102 acceptance state and define the next desktop
product-logic boundary without reopening implementation scope.

#### Acceptance

- [x] `P102-UI-01` is recorded as merged and done.
- [x] Phase 103 has one non-overlapping ready task with explicit owned paths.

## Phase 103 Task Board

### P103-UI-01 - Live Execution And Approval Interaction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P102-CLOSE-01`
- Branch: `codex/p103-ui-01-live-execution-approvals`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Replace replay-only execution feedback and placeholder interruption with a
live operator loop, then mount the existing approval API into the active task
surface.

#### Deliverables

- incremental session event consumption without buffering the entire SSE response
- real session cancel behavior from the active composer or execution surface
- approval detail and approve or reject actions in the active task workspace
- deterministic UI state projection for running, waiting, cancelled, failed, and completed sessions

#### Acceptance

- [x] Operators see session events incrementally while a task executes.
- [x] Stop sends the real cancel request and projects the resulting terminal state.
- [x] Waiting approvals expose concrete context and approve or reject controls.
- [x] Refresh or reconnect converges to the same durable session state.
- [x] Focused frontend checks, `pnpm build`, and `make check` pass.

### P103-CLOSE-01 - Phase 103 Closeout And Phase 104 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P103-UI-01`
- Branch: `codex/p103-closeout-phase104-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 103 acceptance state and define the next desktop
product boundary without reopening live execution or approval scope.

#### Acceptance

- [x] `P103-UI-01` is recorded as merged through PR `#42` and done.
- [x] Phase 104 has one non-overlapping ready task with explicit owned paths.

## Phase 104 Task Board

### P104-UI-01 - Result Review And Safe Delivery Interaction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P103-CLOSE-01`
- Branch: `codex/p104-ui-01-result-review-delivery`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Make the existing diff, artifact, validation, commit, and pull-request APIs
operable from the active Codex task workspace without duplicating backend or
legacy workbench logic.

#### Deliverables

- one task-local review surface that makes changed files, artifacts, validation evidence, and unresolved delivery risks visible before writes
- commit creation from the active task with explicit operator input and durable delivery-audit refresh
- pull-request planning by default, followed by an explicit execution action rather than an ambiguous single-step write
- deterministic loading, success, unavailable, and failure states for delivery actions

#### Acceptance

- [x] Operators can review available change and validation evidence before committing.
- [x] Commit creation uses the existing typed API and refreshes durable session and delivery state.
- [x] Pull-request flow defaults to a side-effect-free plan and requires an explicit action to execute.
- [x] Delivery actions are disabled when the active session, evidence, or required policy is unavailable.
- [x] Focused frontend checks, `pnpm build`, and `make check` pass.

### P104-CLOSE-01 - Phase 104 Closeout And Phase 105 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P104-UI-01`
- Branch: `codex/p104-closeout-phase105-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 104 acceptance state and define the next desktop
product boundary without reopening result review or delivery scope.

#### Acceptance

- [x] `P104-UI-01` is recorded as merged through PR `#44` and done.
- [x] Phase 105 has one non-overlapping ready task with explicit owned paths.

## Phase 105 Task Board

### P105-UI-01 - Task Launch Configuration And Workspace Binding

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P104-CLOSE-01`
- Branch: `codex/p105-ui-01-task-launch-configuration`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Replace placeholder Composer controls with a truthful task-launch contract
that binds new sessions to an explicit workspace and supported policy while
representing model and attachment capabilities honestly.

#### Deliverables

- explicit workspace path configuration for new tasks using the existing create-session `workspace` field
- a compact preflight summary of workspace, policy, and configured runtime model before submission
- persisted launch defaults that do not rewrite existing session configuration
- unsupported attachment and model-selection controls removed, disabled, or clearly represented as fixed capabilities
- deterministic validation for missing workspace, unsupported policy, and restored launch defaults

#### Acceptance

- [x] New desktop tasks send the selected workspace and policy through the existing typed create-session API.
- [x] Operators can verify launch configuration before starting a task.
- [x] Existing sessions continue to display their durable workspace and policy rather than current draft defaults.
- [x] The UI does not imply that attachments or arbitrary model switching work when the backend has no such contract.
- [x] Focused frontend checks, `pnpm build`, and `make check` pass.

### P105-CLOSE-01 - Phase 105 Closeout And Phase 106 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P105-UI-01`
- Branch: `codex/p105-closeout-phase106-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 105 acceptance state and define the next durable task
discovery boundary without reopening launch configuration scope.

#### Acceptance

- [x] `P105-UI-01` is recorded as merged through PR `#46` and done.
- [x] Phase 106 has one non-overlapping ready task with explicit owned paths.

## Phase 106 Task Board

### P106-APP-01 - Durable Recent Session Discovery

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P105-CLOSE-01`
- Branch: `codex/p106-app-01-durable-session-discovery`
- Owned paths: `packages/agent-core/src/agent_core/ports/projection_store.py`, `packages/agent-storage/src/agent_storage/projections.py`, `apps/api/src/zebra_agent_api/`, `tests/api/`, `tests/agent_storage/`, `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Make durable sessions discoverable after local browser state is lost by adding
one bounded recent-session API and using it as the desktop task index without
discarding unsent local drafts.

#### Deliverables

- a projection-store query for recent sessions with deterministic newest-first ordering and a bounded limit
- an authenticated `GET /sessions` response that returns compact durable session summaries without replaying every event stream
- desktop startup reconciliation that imports durable sessions, preserves local drafts, and removes stale local bindings only when the API provides authoritative evidence
- deterministic backend and frontend checks for ordering, limit validation, deduplication, and local-draft preservation

#### Acceptance

- [x] A fresh desktop storage profile can discover recent durable sessions from the configured API.
- [x] Recent-session results are bounded, newest first, and use the same durable status, workspace, and policy projections as session detail.
- [x] Desktop reconciliation does not duplicate sessions or discard unsent local drafts.
- [x] Authentication and invalid-limit behavior match existing API conventions.
- [x] Focused backend and frontend checks, `pnpm build`, and `make check` pass.

### P106-CLOSE-01 - Phase 106 Closeout And Phase 107 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P106-APP-01`
- Branch: `codex/p106-closeout-phase107-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 106 acceptance state and define the next workspace
navigation boundary without reopening durable session discovery scope.

#### Acceptance

- [x] `P106-APP-01` is recorded as merged through PR `#48` and done.
- [x] Phase 107 has one non-overlapping ready task with explicit owned paths.

## Phase 107 Task Board

### P107-UI-01 - Workspace-Backed Project Navigation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P106-CLOSE-01`
- Branch: `codex/p107-ui-01-workspace-project-navigation`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Replace the hard-coded single project card with workspace-backed project
navigation derived from durable session evidence and the configured launch
workspace, without introducing a second project database.

#### Deliverables

- deterministic project projection from durable session workspace roots plus the configured launch workspace
- sidebar project cards with active project state and task filtering by selected workspace
- project selection that updates the new-task workspace while existing sessions continue to display their durable workspace
- an explicit unbound bucket for drafts or sessions without workspace evidence
- focused checks for project identity, deduplication, ordering, filtering, and launch-workspace selection

#### Acceptance

- [x] The project section no longer hard-codes `zebra-agent` when durable workspace evidence is available.
- [x] Selecting a project shows only its tasks and prepares new tasks for that workspace.
- [x] Existing session workspace and policy remain durable and are not rewritten by project selection.
- [x] Drafts and sessions without workspace evidence remain visible in an explicit unbound project.
- [x] Focused frontend checks, `pnpm build`, and `make check` pass.

### P107-CLOSE-01 - Phase 107 Closeout And Phase 108 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P107-UI-01`
- Branch: `codex/p107-closeout-phase108-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 107 acceptance state and define the next project
identity boundary without reopening project discovery or navigation scope.

#### Acceptance

- [x] `P107-UI-01` is recorded as merged through PR `#50` and done.
- [x] Phase 108 has one non-overlapping ready task with explicit owned paths.

## Phase 108 Task Board

### P108-UI-01 - Project-Aware Workspace Identity

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P107-CLOSE-01`
- Branch: `codex/p108-ui-01-project-aware-workspace-identity`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Replace the remaining hard-coded project identity in the desktop workspace
with the selected or durable workspace identity, without adding project
metadata that the backend does not persist.

#### Deliverables

- idle workspace title derived from the selected project, including an explicit unbound label
- active-session inspector project identity derived from that session's durable workspace rather than current launch state
- full workspace paths retained as accessible context while compact labels remain readable
- deterministic coverage for compact, root, relative, trailing-slash, and unbound project labels

#### Acceptance

- [x] Switching projects updates the idle workspace identity consistently with sidebar selection and launch configuration.
- [x] Opening an existing session displays project identity from its durable workspace even when the new-task project differs.
- [x] Unbound tasks never inherit a configured or hard-coded project name.
- [x] Full workspace paths remain available without widening the compact desktop layout.
- [x] Focused frontend checks, `pnpm build`, and `make check` pass.

### P108-CLOSE-01 - Phase 108 Closeout And Phase 109 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P108-UI-01`
- Branch: `codex/p108-closeout-phase109-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 108 acceptance state and define the next task
visibility boundary without reopening workspace identity scope.

#### Acceptance

- [x] `P108-UI-01` is recorded as merged through PR `#52` and done.
- [x] Phase 109 has one non-overlapping ready task with explicit owned paths.

## Phase 109 Task Board

### P109-UI-01 - Reversible Task Visibility

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P108-CLOSE-01`
- Branch: `codex/p109-ui-01-reversible-task-visibility`
- Owned paths: `UI/desktop/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Replace misleading destructive task controls with truthful local draft deletion
and reversible durable-session hiding, without inventing a backend delete API.

#### Deliverables

- distinct delete-draft and hide-durable-task labels and icons based on durable session binding
- persisted local hide tombstones with an explicit restore-hidden-tasks control
- immediate restoration from the latest authoritative recent-session snapshot
- deterministic reconciliation coverage for hide persistence and restoration

#### Acceptance

- [x] Local drafts are presented as deletable while durable sessions are presented as hideable.
- [x] Hiding a durable task never sends a backend delete request and survives reload.
- [x] Operators can restore hidden recent tasks without clearing browser storage or restarting the app.
- [x] Restoring tasks preserves durable title, workspace, status, and session binding.
- [x] Focused frontend checks, `pnpm build`, and `make check` pass.

### P109-CLOSE-01 - Phase 109 Closeout And Phase 110 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P109-UI-01`
- Branch: `codex/p109-closeout-phase110-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 109 acceptance state and define a bounded real-provider
execution closure task without broadening the desktop product surface.

#### Acceptance

- [x] `P109-UI-01` is recorded as merged through PR `#54` and done.
- [x] Phase 110 has one non-overlapping ready task with explicit owned paths.

## Phase 110 Task Board

### P110-INT-01 - General Agent Desktop And Provider Closure

- Status: `Done`
- Owner: `Codex`
- Suggested role: `APP`
- Depends on: `P109-CLOSE-01`
- Branch: `codex/p110-int-01-provider-backed-desktop-execution`
- Owned paths: `UI/desktop/`, `apps/api/`, `apps/config/`, `packages/agent-integrations/`, `tests/`, `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`, `docs/实施任务拆解与阶段验收.md`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Align the desktop with Zebra Agent's general executing-agent positioning, then
prove one real local task from durable creation through provider-backed execution
and final readback while keeping provider secrets untracked.

#### Deliverables

- local ignored provider configuration using the supported `deepseek-v4-flash` model
- default task UI centered on generic execution rather than code delivery
- HITL controls rendered only from a concrete active approval
- browser-observed create, execute, SSE event, final message, and durable status convergence
- truthful frontend error handling for any provider or execution failure found in the flow
- deterministic regression coverage for each code defect fixed during acceptance
- concise startup and provider-readiness guidance aligned with the verified path

#### Acceptance

- [x] No provider credential is staged, committed, logged, or returned by an API response.
- [x] Normal tasks show no fixed Diff, Commit, or Pull Request workflow.
- [x] HITL approval context and actions appear only while a concrete approval is active.
- [x] A real desktop task reaches a terminal durable state through the configured provider.
- [x] The task timeline and assistant response converge without a manual page reload.
- [x] Reloading the task preserves its title, workspace, messages, events, and terminal status.
- [x] Focused integration checks, `pnpm build`, `make test`, and `make check` pass.

### P110-CLOSE-01 - Phase 110 Closeout And Phase 111 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P110-INT-01`
- Branch: `codex/p110-closeout-phase111-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 110 acceptance state and define the provider tool-discovery
boundary without reopening desktop positioning or approval-resume scope.

#### Acceptance

- [x] `P110-INT-01` is recorded as merged through PR `#56` and done.
- [x] Phase 111 has one non-overlapping ready task with explicit owned paths.

## Phase 111 Task Board

### P111-MDL-01 - Provider Tool Discovery And Safe Execution

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P110-CLOSE-01`
- Branch: `codex/p111-mdl-01-provider-tool-discovery`
- Owned paths: `packages/agent-core/`, `packages/agent-integrations/`, `packages/agent-tools/`, `packages/agent-runtime/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Expose the active typed tool catalog to OpenAI-compatible providers and prove that
a real provider can select and execute one policy-allowed tool through the existing
harness rather than returning a textual imitation of a tool call.

#### Deliverables

- provider-neutral model request contracts for available tools
- deterministic OpenAI-compatible function-tool serialization
- runtime composition that advertises the same registered tools it can execute
- regression coverage for tool request payloads, malformed contracts, and safe execution
- real-provider acceptance evidence with no credential disclosure

#### Acceptance

- [x] The model gateway receives typed tool definitions without depending on `agent-tools`.
- [x] OpenAI-compatible requests serialize deterministic function names, descriptions, and JSON schemas.
- [x] The local API and CLI advertise only tools present in their executable registry.
- [x] A real provider proposes a registered safe tool and the harness executes it through policy and tool gateways.
- [x] Text-only model completion remains backward compatible when no tools are available or selected.
- [x] Targeted tests, `make test`, and `make check` pass.

#### Explicit Non-Goals

- resuming the exact pending tool call after an approval decision
- multi-tool or parallel tool-call execution
- adding code-delivery UI or product defaults

### P111-CLOSE-01 - Phase 111 Closeout And Phase 112 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P111-MDL-01`
- Branch: `codex/p111-closeout-phase112-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 111 acceptance state and define the bounded tool-result
synthesis task without reopening approval continuation or multi-tool execution.

#### Acceptance

- [x] `P111-MDL-01` is recorded as merged through PR `#58` and done.
- [x] Phase 112 has one non-overlapping ready task with explicit owned paths.

## Phase 112 Task Board

### P112-HAR-01 - Tool Result Synthesis And Final Response

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P111-CLOSE-01`
- Branch: `codex/p112-har-01-tool-result-synthesis`
- Owned paths: `packages/agent-core/`, `packages/agent-integrations/`, `packages/agent-runtime/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Feed one policy-allowed tool result back to the provider and persist the final
assistant answer so provider-backed tasks finish with a result-grounded response.

#### Deliverables

- provider-neutral assistant tool-call and tool-result message contracts
- OpenAI-compatible serialization with preserved provider tool-call identity
- opt-in single-tool result synthesis in the existing orchestrator
- production local runtime and worker composition with a two-call model budget
- deterministic and real-provider final-response acceptance evidence

#### Acceptance

- [x] The second provider request contains the original assistant tool call and matching tool-result message.
- [x] The final assistant answer replaces the synthetic tool-proposal text in terminal metadata and durable readback.
- [x] Both model calls are represented in events and counted against the model-call budget.
- [x] Text-only tasks remain single-call and existing non-synthesizing orchestrator composition stays backward compatible.
- [x] A real provider reads an isolated proof payload and returns a final answer grounded in that payload.
- [x] Targeted tests, `make test`, and `make check` pass.

#### Explicit Non-Goals

- approval decision continuation of a pending tool call
- additional or parallel tool calls after the first result
- frontend redesign or code-delivery workflow changes

### P112-CLOSE-01 - Phase 112 Closeout And Phase 113 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P112-HAR-01`
- Branch: `codex/p112-closeout-phase113-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 112 acceptance state and define exact approved-tool
continuation without reopening multi-tool execution.

#### Acceptance

- [x] `P112-HAR-01` is recorded as merged through PR `#60` and done.
- [x] Phase 113 has one non-overlapping ready task with explicit owned paths.

## Phase 113 Task Board

### P113-HITL-01 - Exact Approved Tool Continuation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P112-CLOSE-01`
- Branch: `codex/p113-hitl-01-exact-approved-tool-continuation`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `packages/agent-runtime/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Persist an immutable pending tool call at the approval boundary and, after a
grant, resume by executing that exact call and synthesizing its final answer
instead of asking the model to propose a replacement call.

#### Deliverables

- durable pending-call evidence with tool name, arguments, internal id,
  provider call id, and the original assistant tool-call turn
- approval decisions bound to the exact pending call rather than only a session
- recovery that distinguishes an approved unconsumed call from a normal rerun
- one guarded execution and final-response synthesis path for the recovered call
- desktop approval flow that resumes the granted session and streams convergence
- explicit interrupted-continuation handling without silently replaying an
  uncertain side effect

#### Acceptance

- [x] Approval readback identifies the exact immutable tool call and arguments being approved.
- [x] Granting approval cannot change the approved tool name, arguments, or call identity.
- [x] Resume executes the approved pending call without making a replacement initial model request.
- [x] The tool result is returned to the provider and the durable session reaches a grounded terminal state.
- [x] A repeated resume cannot execute an already consumed approved call again.
- [x] Rejection remains terminal and executes no tool.
- [x] The desktop approve action resumes execution and converges through existing durable stream and session reads.
- [x] Focused API, CLI, Worker, storage, and desktop tests plus repository gates pass.

#### Explicit Non-Goals

- multiple or parallel tool calls in one continuation
- automatic replay after an interruption with uncertain external side effects
- generic distributed workflow scheduling
- code-delivery-specific UI

### P113-CLOSE-01 - Phase 113 Closeout And Phase 114 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P113-HITL-01`
- Branch: `codex/p113-closeout-phase114-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 113 acceptance state and define one bounded sequential
tool-loop task without reopening parallel execution or distributed scheduling.

#### Acceptance

- [x] `P113-HITL-01` is recorded as merged through PR `#62` and done.
- [x] Phase 114 has one non-overlapping ready task with explicit owned paths.

## Phase 114 Task Board

### P114-HAR-01 - Bounded Sequential Tool Loop

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P113-CLOSE-01`
- Branch: `codex/p114-har-01-bounded-sequential-tool-loop`
- Owned paths: `packages/agent-core/`, `packages/agent-integrations/`, `packages/agent-runtime/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Allow one provider-backed attempt to execute a bounded sequence of tool calls,
feeding each result back to the model until it returns a final answer or a
configured budget or safety boundary stops the loop.

#### Deliverables

- provider-neutral conversation state for sequential assistant tool calls and tool results
- deterministic loop accounting for model-call and tool-call budgets
- production composition that permits another advertised tool after a successful result
- repeated-call protection and explicit terminal behavior when a budget is exhausted
- approval pause and exact continuation for a later tool step without replaying completed calls
- deterministic and real-provider acceptance evidence for a multi-step task

#### Acceptance

- [x] A provider can request a tool, observe its result, request a different tool, and then return a grounded final answer.
- [x] Every model and tool call is durably represented and counted against its configured budget.
- [x] Exhausted budgets and repeated identical calls stop deterministically without an unbounded provider loop.
- [x] A later approval-required call pauses with exact call identity and resumes without replaying completed tools.
- [x] Existing text-only, single-tool, rejection, and uncertain-side-effect protections remain compatible.
- [x] Targeted tests, `make test`, `make check`, the eval release gate, and one real-provider multi-step acceptance pass.

#### Explicit Non-Goals

- parallel tool-call execution from one provider response
- subagent delegation or generic workflow scheduling
- automatic replay after an interruption with uncertain external side effects
- code-delivery-specific product behavior

### P114-CLOSE-01 - Phase 114 Closeout And Phase 115 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P114-HAR-01`
- Branch: `codex/p114-closeout-phase115-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 114 acceptance state and define deterministic handling
for complete provider tool-call batches before introducing true concurrency.

#### Acceptance

- [x] `P114-HAR-01` is recorded as merged through PR `#64` and done.
- [x] Phase 115 has one non-overlapping ready task with explicit owned paths.

## Phase 115 Task Board

### P115-HAR-01 - Deterministic Multi-Call Batch Execution

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P114-CLOSE-01`
- Branch: `codex/p115-har-01-deterministic-multi-call-batches`
- Owned paths: `packages/agent-core/`, `packages/agent-runtime/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Consume every tool call in one provider response as an ordered batch so calls
are never silently discarded, while preserving per-call policy, budget,
duplicate protection, durable evidence, and exact approval continuation.

#### Deliverables

- provider-order batch processing for all selected calls in one model response
- one policy decision and durable execution trace per call
- atomic pause context that preserves the approved call and unconsumed batch tail
- approval continuation that resumes the pending call and then the remaining batch
- batch-aware model and tool budget enforcement without partial silent success
- deterministic and real-provider acceptance evidence for one multi-call response

#### Acceptance

- [x] Two allowed calls from one provider response execute once in provider order and both results reach the next model request.
- [x] A denied, repeated, or over-budget batch member stops explicitly and leaves later members unexecuted.
- [x] An approval-required batch member pauses before execution and preserves the unconsumed tail durably.
- [x] Approval resume executes the exact pending call, then continues the preserved tail without replaying earlier calls.
- [x] Existing text-only, single-call, sequential-turn, rejection, and uncertain-side-effect behavior remains compatible.
- [x] Targeted tests, `make test`, `make check`, the eval release gate, and one real-provider batch acceptance pass.

#### Explicit Non-Goals

- concurrent execution of multiple tool calls
- dependency-graph scheduling or automatic call reordering
- subagent delegation or distributed workflow scheduling
- automatic replay after uncertain external side effects

### P115-CLOSE-01 - Phase 115 Closeout And Phase 116 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P115-HAR-01`
- Branch: `codex/p115-closeout-phase116-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 115 acceptance state and define bounded concurrency for
explicitly safe tool batches without weakening policy, approval, or recovery
boundaries.

#### Acceptance

- [x] `P115-HAR-01` is recorded as merged through PR `#66` and done.
- [x] Phase 116 has one non-overlapping ready task with explicit owned paths.

## Phase 116 Task Board

### P116-HAR-01 - Bounded Safe Concurrent Tool Batches

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE`
- Depends on: `P115-CLOSE-01`
- Branch: `codex/p116-har-01-bounded-safe-concurrent-batches`
- Owned paths: `packages/agent-core/`, `packages/agent-tools/`, `packages/agent-security/`, `packages/agent-runtime/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Reduce latency for independent retrieval and inspection work by executing one
provider batch concurrently only when every member is explicitly classified as
parallel-safe, while preserving provider-order results and deterministic
fallback for every other batch.

#### Deliverables

- explicit tool capability metadata that distinguishes parallel-safe calls from unknown or side-effecting calls
- a configurable concurrency bound with no unbounded task creation
- preflight policy, duplicate, and budget checks before a safe batch starts
- concurrent execution for fully eligible batches with provider-order result and event projection
- sequential fallback for mixed, approval-required, unknown, or side-effecting batches
- deterministic cancellation and failure semantics that never imply rollback of an already-started call
- focused timing, ordering, fallback, failure, and real-provider acceptance evidence

#### Acceptance

- [x] Two independent parallel-safe calls overlap in execution and both results reach the next model request in provider order.
- [x] The configured concurrency limit is enforced for a larger eligible batch.
- [x] Mixed, unknown, write-capable, denied, and approval-required batches execute or pause through the existing sequential path.
- [x] Policy, duplicate, and budget rejection occurs before any member of a candidate concurrent batch starts.
- [x] One concurrent member failure is recorded explicitly; already-started siblings are observed to completion and no rollback or unsafe replay is claimed.
- [x] Existing text-only, sequential, HITL continuation, uncertain-side-effect, and complete-batch behavior remains compatible.
- [x] Targeted tests, `make test`, `make check`, the eval release gate, and one real-provider concurrent-batch acceptance pass.

#### Explicit Non-Goals

- dependency-graph scheduling or automatic call reordering
- concurrent write or externally side-effecting tools
- concurrent approval flows
- subagent delegation or distributed workflow scheduling
- cancellation guarantees for work that has already started

### P116-CLOSE-01 - Phase 116 Closeout And Phase 117 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P116-HAR-01`
- Branch: `codex/p116-closeout-phase117-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 116 acceptance state and define bounded conversation
compaction for longer provider-backed tool loops before introducing subagent
delegation.

#### Acceptance

- [x] `P116-HAR-01` is recorded as merged through PR `#68` and done.
- [x] Phase 117 has one non-overlapping ready task with explicit owned paths.

## Phase 117 Task Board

### P117-CTX-01 - Bounded Harness Conversation Compaction

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / CTX`
- Depends on: `P116-CLOSE-01`
- Branch: `codex/p117-ctx-01-bounded-conversation-compaction`
- Owned paths: `packages/agent-core/`, `packages/agent-context/`, `packages/agent-integrations/`, `packages/agent-runtime/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Keep longer general-agent tool loops within a deterministic dynamic-conversation
budget by compacting completed older exchanges before the next provider request,
without breaking tool-call identity, approval recovery, or the stable context
prefix.

#### Deliverables

- deterministic message-size estimation and a configurable dynamic-conversation budget
- reuse of the existing conversation and tool-output compaction capabilities behind a core Port
- compaction of completed older assistant/tool exchanges while retaining the original user goal and recent working set
- preservation of complete assistant/tool call pairs, provider call ids, and every unresolved or approval-pending call
- durable compaction evidence with before/after estimates and retained/removed counts, excluding raw sensitive output
- exact approval continuation and final-answer synthesis from compacted conversation state
- deterministic and real-provider acceptance evidence for a longer multi-step task

#### Acceptance

- [x] A conversation above the configured dynamic budget is compacted before the next provider request and its deterministic estimate falls within the supported bound.
- [x] The stable system prefix, original user goal, latest working exchange, and valid assistant/tool pairing remain present after compaction.
- [x] Pending, failed, or approval-required calls are never summarized away or detached from their provider call ids.
- [x] Conversations below the threshold remain byte-for-byte equivalent, and repeated compaction produces the same canonical messages.
- [x] Compaction events expose only counts, estimates, and provenance metadata rather than raw tool output or secrets.
- [x] Approval pause and resume continue from the compacted canonical conversation without replaying completed tools.
- [x] Existing text-only, sequential, complete-batch, safe-concurrent, failure, and HITL behavior remains compatible.
- [x] Targeted tests, `make test`, `make check`, the eval release gate, and one real-provider compacted-loop acceptance pass.

#### Explicit Non-Goals

- model-generated or semantic summaries
- embedding retrieval, vector databases, or repository indexing changes
- provider-specific tokenizer guarantees or automatic context-window expansion
- compaction of unresolved tool calls or approval evidence
- subagent delegation, nested agents, or distributed scheduling

### P117-CLOSE-01 - Phase 117 Closeout And Phase 118 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P117-CTX-01`
- Branch: `codex/p117-closeout-phase118-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 117 acceptance state and define one bounded local-first
read-only Research Subagent slice without introducing write sharing, role-specific
review agents, or distributed scheduling.

#### Acceptance

- [x] `P117-CTX-01` is recorded as merged through PR `#70` and done.
- [x] Phase 118 has one non-overlapping ready task with explicit owned paths.

## Phase 118 Task Board

### P118-SUB-01 - Bounded Read-Only Research Subagent

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / CTX / RUNTIME`
- Depends on: `P117-CLOSE-01`
- Branch: `codex/p118-sub-01-bounded-read-only-research`
- Owned paths: `packages/agent-core/`, `packages/agent-tools/`, `packages/agent-security/`, `packages/agent-runtime/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Allow the primary local agent to delegate one bounded evidence-gathering task to
a child Research Subagent that can inspect the same workspace but cannot mutate
it, expand the parent's authority, recursively delegate, or outlive its parent.

#### Deliverables

- provider-neutral child-agent identity, task, lifecycle, budget, and result contracts
- local-first `spawn`, `join`, `cancel`, and `collect` primitives behind an `agent-core` Port
- one typed research-delegation capability that returns structured findings with sources and confidence
- a strictly read-only child tool profile built from existing safe inspection tools
- explicit limits for child count, model calls, tool calls, concurrency, and recursive depth
- parent-child event evidence for start, completion, failure, and cancellation without raw sensitive output
- deterministic and real-provider acceptance evidence for a parent answer grounded in child findings

#### Acceptance

- [x] A parent run can delegate one research task, collect its structured result, and use that result in the final provider answer.
- [x] Child results include a bounded summary, concrete source references, confidence, and terminal status.
- [x] A child inherits the parent workspace and a read-only authority ceiling even when the parent has a broader policy profile.
- [x] File mutation, command execution, network access, credential access, and recursive delegation are unavailable to the child.
- [x] Child count, concurrency, model-call, tool-call, and depth limits reject excess work before it starts.
- [x] Join, cancellation, child failure, and parent cancellation converge deterministically without orphaned local work or unsafe replay claims.
- [x] Parent-child events expose identities, budgets, status, and provenance but do not copy raw sensitive findings into control metadata.
- [x] Existing text-only, tool-loop, batch, compaction, approval, and safe-concurrent behavior remains compatible.
- [x] Targeted tests, `make test`, `make check`, the eval release gate, and one real-provider parent-to-child acceptance pass.

#### Explicit Non-Goals

- write-capable child agents or shared-worktree mutation
- Reviewer, Coder, or other fixed role frameworks
- independent child worktrees or merge coordination
- durable cross-process child recovery or distributed scheduling
- A2A, remote agents, multi-tenant quotas, or automatic model routing
- Tree-sitter, LSP, vector retrieval, or repository indexing changes

### P118-CLOSE-01 - Phase 118 Closeout And Phase 119 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P118-SUB-01`
- Branch: `codex/p118-closeout-phase119-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 118 acceptance state and define one bounded parallel
read-only research fan-out slice by reusing the existing safe-batch executor,
without adding role frameworks, adaptive graphs, or distributed scheduling.

#### Acceptance

- [x] `P118-SUB-01` is recorded as merged through PR `#72` and done.
- [x] Phase 119 has one non-overlapping ready task with explicit owned paths.

## Phase 119 Task Board

### P119-SUB-01 - Bounded Parallel Research Fan-Out

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / RUNTIME`
- Depends on: `P118-CLOSE-01`
- Branch: `codex/p119-sub-01-bounded-parallel-research-fanout`
- Owned paths: `packages/agent-core/`, `packages/agent-runtime/`, `packages/agent-security/`, `apps/worker/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Allow one parent provider response to fan out a small fixed number of independent
`agent.research` calls concurrently, then return every sourced child result to the
parent in provider order under aggregate child and concurrency bounds.

#### Deliverables

- explicit parallel-safe classification for independent read-only research calls
- configurable local child and concurrency limits with a conservative production default
- reuse of safe-batch policy, duplicate, and budget preflight before any fan-out starts
- concurrent child execution with deterministic provider-order tool results and lifecycle events
- aggregate child usage, source, completion, failure, and cancellation evidence
- parent teardown propagation that cancels and joins every unfinished child
- deterministic timing, ordering, bound, failure, cancellation, and real-provider acceptance evidence

#### Acceptance

- [x] Two independent `agent.research` calls from one provider response overlap and both sourced results reach the next parent model request in provider order.
- [x] The configured child and concurrency limits are enforced for a larger research batch with no unbounded task or thread creation.
- [x] Policy, duplicate, parent tool budget, and child aggregate-bound rejection occurs before a candidate fan-out starts.
- [x] Every child retains the same workspace and read-only authority ceiling, and no child can recursively delegate.
- [x] One child failure is explicit while already-started siblings are observed to terminal state; no rollback or unsafe replay is claimed.
- [x] Parent cancellation or teardown propagates to every unfinished child and joins local work before the coordinator closes.
- [x] Child lifecycle and aggregate evidence contains identities, order, usage, sources, status, confidence, and provenance without raw findings in control metadata.
- [x] Mixed, write-capable, approval-required, single-research, sequential, compaction, and HITL behavior remains compatible.
- [x] Targeted tests, `make test`, `make check`, the eval release gate, and one real-provider parallel research acceptance pass.

#### Explicit Non-Goals

- adaptive dependency graphs, recursive fan-out, or child-created children
- write-capable children, shared-worktree mutation, or merge coordination
- Reviewer, Coder, or other fixed role frameworks
- dynamic model routing or per-child provider selection
- durable cross-process children, distributed scheduling, A2A, or remote agents
- Tree-sitter, LSP, vector retrieval, or repository indexing changes

### P119-CLOSE-01 - Phase 119 Closeout And Phase 120 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P119-SUB-01`
- Branch: `codex/p119-closeout-phase120-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 119 acceptance state and define one vertical slice that
separates product-facing tool availability from security authority, so general
agent tasks do not inherit coding-specific capabilities by default.

#### Acceptance

- [x] `P119-SUB-01` is recorded as merged through PR `#75` and done.
- [x] Phase 120 has one non-overlapping ready task with explicit owned paths.
- [x] A fixed Reviewer role is rejected because bounded `agent.research`
  objectives already cover read-only independent review without another role API.

## Phase 120 Task Board

### P120-CAP-01 - Durable General And Coding Tool Profiles

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / RUNTIME / APP`
- Depends on: `P119-CLOSE-01`
- Branch: `codex/p120-cap-01-durable-tool-profiles`
- Owned paths: `packages/agent-core/`, `packages/agent-runtime/`, `packages/agent-storage/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Separate the fixed set of tools advertised and registered for a task from its
security `policy_profile`, default new product tasks to a general-purpose tool
surface, and retain the current coding-oriented surface as an explicit option.

#### Deliverables

- one provider-neutral typed tool-profile contract with fixed `general` and `coding` values
- a `general` manifest containing `agent.research`, `command.run`, `files.read`, and `patch.apply`
- a `coding` manifest that preserves the current tools and additionally includes `git.status` and `tests.run`
- durable tool-profile persistence through session creation, events, projections, API and CLI readback, worker execution, and desktop task launch
- deterministic registry filtering before model advertisement or tool execution
- backward-compatible recovery of existing sessions that predate the field
- focused backend, desktop, browser, and real-provider acceptance evidence

#### Acceptance

- [x] A newly created task defaults to `general`; an explicit `coding` task retains the current complete executable tool manifest.
- [x] Existing sessions without durable tool-profile evidence recover as `coding`, preserving the behavior under which they were created.
- [x] The selected profile survives create, list, inspect, reload, worker claim, execution, suspend or resume, and approval continuation paths.
- [x] General tasks neither advertise nor execute `git.status` or `tests.run`; coding tasks advertise and execute them through the existing typed gateway.
- [x] Unknown profile values fail at the API, CLI, configuration, and projection trust boundaries instead of silently widening capabilities.
- [x] Tool profiles never bypass policy: every registered call still passes the same policy and approval checks, and selecting `coding` cannot increase file, network, command, or credential authority.
- [x] Research children retain their fixed read-only, non-recursive tool ceiling regardless of the parent profile.
- [x] The desktop defaults visibly and durably to general-purpose execution and offers coding tools only through an explicit launch selection.
- [x] Legacy behavior, HITL continuation, concurrent batches, compaction, and bounded Research fan-out remain compatible.
- [x] Targeted checks, full backend and desktop gates, browser persistence validation, and one real-provider manifest-selection acceptance pass.

#### Explicit Non-Goals

- treating a tool profile as a security boundary or replacing `policy_profile`
- arbitrary user-authored manifests or per-call profile mutation
- automatic profile inference from prompt text or dynamic model routing
- removing coding tools from the product or changing their existing contracts
- new network, browser, MCP, credential, or external SaaS capabilities
- fixed Reviewer or Coder subagent roles, write-capable children, or worktree merge coordination

### P120-CLOSE-01 - Phase 120 Closeout And Phase 121 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P120-CAP-01`
- Branch: `codex/p120-closeout-phase121-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 120 acceptance state and define the next security-first
vertical slice required before general-purpose tasks can safely gain external
information tools.

#### Acceptance

- [x] `P120-CAP-01` is recorded as merged through PR `#77` and done.
- [x] Phase 121 has one non-overlapping ready task with explicit owned paths.
- [x] External Web, browser, MCP, and SaaS tools remain deferred until durable
  network authority reaches Policy and worker recovery without fail-open gaps.

## Phase 121 Task Board

### P121-NET-01 - Durable Per-Task Network Authority

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / SECURITY / APP`
- Depends on: `P120-CLOSE-01`
- Branch: `codex/p121-net-01-durable-network-authority`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `packages/agent-runtime/`, `packages/agent-storage/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Make network authority an explicit, durable, fail-closed property of every task
and carry it into the production Policy engine before any new external
information capability is advertised to the model.

#### Deliverables

- one provider-neutral task network configuration using the existing typed
  `NetworkProfile` contract and normalized domain allowlist
- a default `none` profile for every new and legacy task without durable network
  evidence
- durable persistence through task creation, `task_prepared` events, workspace
  projections, SQLite migration, API and CLI readback, worker recovery, suspend
  or resume, and approval continuation
- production `LocalPolicyEngine` composition from recovered network authority in
  direct runtime, API, CLI, and worker execution paths
- explicit API, CLI, and desktop launch controls that present network authority
  separately from tool capability and filesystem or command policy
- deterministic validation for unsupported profiles, malformed allowlists,
  profile or allowlist mismatches, and legacy rows
- focused backend, desktop, and browser persistence acceptance evidence

#### Acceptance

- [x] New tasks default durably to `network_profile=none`; legacy events and
  projection rows without network evidence recover to the same fail-closed value.
- [x] The selected network profile and normalized domain allowlist survive
  create, list, inspect, reload, worker claim, execution, suspend or resume, and
  approval continuation.
- [x] Direct runtime, API, CLI, and worker composition pass the recovered network
  profile into `LocalPolicyEngine`; no execution path silently uses a wider
  process-global fallback.
- [x] `domain-allowlist` requires at least one normalized bare hostname and every
  non-domain profile rejects allowlist entries.
- [x] Unknown, blank, malformed, and mismatched values fail at API, CLI, event,
  projection, storage, and desktop trust boundaries without widening authority.
- [x] Network authority remains independent of `tool_profile` and
  `policy_profile`; changing it neither registers tools nor expands file,
  command, Git, credential, or approval authority.
- [x] Existing MCP routing remains fail closed: `none` blocks external MCP calls,
  proxy-enabled profiles still require Policy approval, and no transport is
  invoked before approval.
- [x] Fixed Research children retain `network_profile=none` regardless of a
  broader parent profile.
- [x] The desktop visibly defaults to no external network, requires an explicit
  launch choice for broader authority, and restores durable network state after
  reload.
- [x] Full backend tests, static checks, eval release gate, desktop contract
  checks, production build, and browser create or readback validation pass.

#### Explicit Non-Goals

- adding Web search, URL fetch, browser automation, MCP server discovery, or SaaS
  tools to any model-visible profile
- implementing a new egress proxy, MCP transport, credential broker backend, or
  provider-specific networking path
- treating network profile selection as implicit approval for external actions
- prompt-based network inference, per-call mutation, arbitrary CIDR or wildcard
  rules, redirect policy, DNS pinning, or production SSRF handling
- controlling the model-provider connection itself through the task tool-egress
  profile

### P121-CLOSE-01 - Phase 121 Closeout And Phase 122 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P121-NET-01`
- Branch: `codex/p121-closeout-phase122-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 121 acceptance state and define the first external
information slice without weakening the durable network, Policy, approval, or
gateway boundaries.

#### Acceptance

- [x] `P121-NET-01` is recorded as merged through PR `#79` and done.
- [x] Phase 122 has one non-overlapping ready task with explicit owned paths.
- [x] Direct arbitrary URL execution is rejected in favor of one bounded,
  read-only Web Gateway path controlled by durable network authority and Policy.

## Phase 122 Task Board

### P122-WEB-01 - Bounded Read-Only Web Gateway

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / SECURITY / TOOLS / INTEGRATIONS / APP`
- Depends on: `P121-CLOSE-01`
- Branch: `codex/p122-web-01-bounded-read-only-web-gateway`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `packages/agent-tools/`, `packages/agent-integrations/`, `packages/agent-runtime/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Give general-purpose tasks one truthful external information capability by
advertising a typed, read-only `web.fetch` tool whose execution is bounded by
durable network authority, explicit Policy approval, and a dedicated Web
Gateway transport rather than direct tool-process networking.

#### Deliverables

- one provider-neutral `web.fetch` contract for HTTPS text retrieval with a
  validated URL and no caller-supplied credentials, headers, methods, or body
- one Web Gateway request and response contract plus an injectable transport;
  production composition uses the gateway and tests may use a fake transport
- deterministic Policy routing that blocks `network_profile=none`, requires an
  exact normalized hostname match for `domain-allowlist`, and requires approval
  before any gateway transport invocation
- bounded response handling with fixed timeout, byte ceiling, accepted textual
  content types, stable metadata, and explicit unavailable or rejected results
- general and coding profile advertisement through the existing typed registry,
  with Research children retaining their no-network and no-Web ceiling
- API, CLI, worker, approval-continuation, desktop HITL, browser, and
  real-provider acceptance evidence

#### Acceptance

- [x] `web.fetch` is visible in general and coding task manifests, but not in
  fixed Research children or any unregistered arbitrary tool path.
- [x] Only `https` URLs with no userinfo and an exact allowlisted hostname reach
  the approval boundary; localhost, IP literals, explicit ports, fragments,
  malformed URLs, and non-allowlisted hosts fail closed.
- [x] No request reaches the gateway while Policy is denied or waiting for
  approval; an exact approval continuation invokes the transport once.
- [x] Gateway execution permits only one GET, sends no task or model credentials,
  does not follow redirects, and enforces timeout, content-type, and response
  byte limits before returning text to the model.
- [x] External content is labeled untrusted and produces auditable route,
  target, profile, status, content type, and byte-count evidence without
  persisting response bodies in control metadata.
- [x] API, CLI, and Worker recover the durable network profile before Policy
  evaluation; process-global configuration cannot widen a task.
- [x] The desktop shows Web access only as launch authority and approval-driven
  HITL; it does not add a default browser or coding-delivery panel.
- [x] Existing local tools, MCP proxy routing, profile isolation, sequential or
  concurrent loops, approvals, compaction, and subagent behavior remain
  compatible.
- [x] Targeted tests, full backend and static gates, eval release gate, desktop
  checks, production build, browser validation, and one real-provider tool
  selection pass succeed.

#### Explicit Non-Goals

- Web search ranking, browser automation, JavaScript rendering, cookies,
  authentication, form submission, uploads, or write-capable HTTP methods
- redirects, wildcard domains, arbitrary ports, IP or CIDR allowlists, private
  network access, caller-defined headers, or process environment credentials
- claiming production-grade DNS pinning or a complete distributed egress proxy;
  the local transport remains a bounded adapter behind the gateway contract
- MCP server discovery, external SaaS connectors, crawling, indexing, caching,
  or persistent Web memory
- granting Research children network access or inferring network authority from
  prompt text

### P122-CLOSE-01 - Phase 122 Closeout And Phase 123 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P122-WEB-01`
- Branch: `codex/p122-closeout-phase123-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 122 acceptance state and define one local information
discovery slice that reduces reliance on unrestricted command execution before
adding another external information provider.

#### Acceptance

- [x] `P122-WEB-01` is recorded as merged through PR `#81` and done.
- [x] Phase 123 has one non-overlapping ready task with explicit owned paths.
- [x] The Hermes `search_files` implementation is used as a design reference
  for bounded pagination, path safety, result limits, and truncation evidence,
  without copying its global runtime assumptions into Zebra Agent.

## Phase 123 Task Board

### P123-TOOL-01 - Bounded Workspace Search Tool

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / SECURITY / TOOLS / RUNTIME`
- Depends on: `P122-CLOSE-01`
- Branch: `codex/p123-tool-01-bounded-workspace-search`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `packages/agent-tools/`, `packages/agent-runtime/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Give general-purpose and Research agents one typed, read-only `files.search`
capability for discovering relevant workspace files or matching text without
requiring `command.run`, while preserving deterministic workspace containment,
bounded output, and provider-neutral tool behavior.

#### Deliverables

- one typed `files.search` contract with content and filename modes, an optional
  workspace-relative root, optional file glob, bounded limit, and offset
- one deterministic local implementation using the existing workspace and
  runtime boundaries rather than a second shell or path abstraction
- stable result metadata for mode, query, root, match count, offset,
  truncation, and next offset without embedding result bodies in control fields
- read-only Policy classification plus explicit parallel-safe registration
- general and coding profile exposure, with fixed Research children receiving
  the same tool under their existing read-only, no-network, non-recursive ceiling
- deterministic, full-repository, real-provider, and Research-child acceptance
  evidence

#### Acceptance

- [x] Content mode returns ordered workspace-relative path, line, column, and
  bounded text evidence; filename mode returns ordered workspace-relative paths.
- [x] Search roots cannot be absolute, blank, or escape the workspace; symlink
  traversal cannot expose data outside the workspace.
- [x] Query, mode, glob, limit, and offset are validated at the typed tool
  boundary; malformed input fails structurally without executing a command.
- [x] Results enforce fixed count, line, and byte ceilings; truncation exposes a
  deterministic `next_offset` and narrowing hint.
- [x] `files.search` is allowed by read-only, workspace-write, and full-access
  Policy profiles and remains independent of task network authority.
- [x] General and coding tasks advertise and execute `files.search`; unknown or
  filtered profiles cannot invoke it through a hidden fallback.
- [x] Research children advertise and execute `files.search` but retain only
  read-only local tools, fixed budgets, no Web access, and no recursion.
- [x] Existing tool advertisement, safe concurrency, sequential loops,
  approvals, compaction, Web Gateway, and durable worker recovery remain
  compatible.
- [x] Targeted tests, full backend and static gates, eval release gate, and one
  real `deepseek-v4-flash` search-and-read acceptance pass succeed.

#### Explicit Non-Goals

- persistent repository indexing, ripgrep daemon state, Tree-sitter, LSP,
  embeddings, vector search, semantic ranking, or cross-repository retrieval
- arbitrary regular-expression execution without bounds, binary-file search,
  archive or office-document extraction, fuzzy filename ranking, or hidden-file
  credential discovery
- directory mutation, file writes, patching, shell execution, Web Search,
  browser automation, or network access
- copying Hermes global task caches, repeated-search counters, configuration
  hot reload, or plugin registry architecture into Zebra Agent

### P123-CLOSE-01 - Phase 123 Closeout And Phase 124 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P123-TOOL-01`
- Branch: `codex/p123-closeout-phase124-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 123 acceptance state and define the first durable
clarification HITL slice so a general-purpose agent can pause for missing user
input without treating chat text or an in-process callback as durable state.

#### Acceptance

- [x] `P123-TOOL-01` is recorded as merged through PR `#83` and done.
- [x] Phase 124 has one non-overlapping ready task with explicit owned paths.
- [x] Hermes Clarify is used only as a schema and interaction reference; its
  process-global blocking queue is rejected for Zebra's recoverable worker model.

## Phase 124 Task Board

### P124-HITL-01 - Durable Clarification Request And Resume

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / TOOLS / RUNTIME / STORAGE / APP / UI`
- Depends on: `P123-CLOSE-01`
- Branch: `codex/p124-hitl-01-durable-clarification`
- Owned paths: `packages/agent-core/`, `packages/agent-tools/`, `packages/agent-runtime/`, `packages/agent-storage/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Allow the model to issue one typed `agent.clarify` request, durably pause the
session for user input, expose that concrete request to operators, and resume
the same task after one correlated user response without replaying a side effect
or relying on a live worker thread.

#### Deliverables

- provider-neutral clarification request and response contracts with one
  question, up to four unique choices, optional context, and stable identifiers
- `waiting_input` session state plus `clarification_requested` and
  `clarification_responded` events with deterministic projection and recovery
- one typed `agent.clarify` model tool that ends the current run slice without
  executing a side effect, requesting approval, or blocking a process thread
- API and CLI readback of the active clarification plus a correlated response
  path that is idempotent and resumes worker execution exactly once
- desktop rendering and response controls only while a concrete active
  clarification exists; no dormant HITL card in idle or ordinary running states
- deterministic, full-repository, desktop, browser, recovery, and real-provider
  acceptance evidence

#### Acceptance

- [x] A valid request contains a non-blank bounded question and zero to four
  unique, non-blank bounded choices; malformed calls fail structurally.
- [x] A clarification call persists one correlated request, transitions the
  session from running to waiting input, and releases the worker without a
  blocked thread or fabricated tool result.
- [x] Session projections and API/CLI reads expose only the active request's
  identifier, question, choices, context, and creation evidence.
- [x] One matching response persists user text plus response evidence, clears
  the active request, and schedules exactly one continuation from waiting input.
- [x] Duplicate, stale, mismatched, blank, or terminal-session responses fail
  closed without additional model calls or queue entries.
- [x] Continuation context contains the original assistant request and correlated
  user answer, while previously completed tools are not executed again.
- [x] Policy and tool profiles cannot turn clarification into command, file,
  network, credential, approval, or write authority.
- [x] Research children cannot recursively suspend a parent through
  `agent.clarify`; the tool remains parent-session only.
- [x] Desktop HITL controls appear only for one concrete active clarification,
  support offered and free-form responses, and disappear after resolution.
- [x] Existing approval continuation, ordinary message append, suspend/resume,
  cancellation, compaction, concurrent tools, Web Gateway, and recovery remain
  compatible.
- [x] Targeted tests, full backend/static/eval gates, desktop checks/build,
  browser validation, and one real `deepseek-v4-flash` clarification pass succeed.

#### Explicit Non-Goals

- blocking worker threads, process-global callback queues, long polling from a
  tool handler, or assuming the API and worker share one process
- using clarification as approval for dangerous tools or merging it with the
  existing approval decision contract
- multi-question forms, branching surveys, file uploads, rich markdown forms,
  arbitrary UI schemas, or more than four offered choices
- automatic timeout decisions, default-answer selection, notification delivery,
  or cross-session clarification routing
- granting Clarify to fixed Research children, inferring answers from unrelated
  messages, or resuming a terminal session

### P124-CLOSE-01 - Phase 124 Closeout And Phase 125 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC`
- Depends on: `P124-HITL-01`
- Branch: `codex/p124-closeout-phase125-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 124 acceptance state and define one durable session-plan
slice so a general-purpose agent can expose real task decomposition and progress
instead of relying on UI stages inferred from unrelated execution events.

#### Acceptance

- [x] `P124-HITL-01` is recorded as merged through PR `#85` and done.
- [x] Phase 125 has one non-overlapping ready task with explicit owned paths.
- [x] Hermes `todo` is used only as a reference for ordered steps, bounded
  statuses, and full-list readback; its in-memory store and conversation-history
  hydration are rejected in favor of Zebra session events and projections.

## Phase 125 Task Board

### P125-PLAN-01 - Durable Session Task Plan

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / TOOLS / SECURITY / STORAGE / RUNTIME / APP / UI`
- Depends on: `P124-CLOSE-01`
- Branch: `codex/p125-plan-01-durable-session-task-plan`
- Owned paths: `packages/agent-core/`, `packages/agent-tools/`, `packages/agent-security/`, `packages/agent-runtime/`, `packages/agent-storage/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Allow the parent model to maintain one bounded, ordered task plan as durable
session state, return the complete authoritative plan after every update, and
show real progress to operators without treating inferred UI stages or chat text
as the plan source of truth.

#### Deliverables

- provider-neutral plan and step contracts with stable step identifiers,
  bounded descriptions, deterministic order, and `pending`, `in_progress`,
  `completed`, or `cancelled` status
- one durable plan-update event plus deterministic session and SQLite projection
  that survives replay, worker recovery, and active-context compaction
- one typed parent-session `agent.plan` tool for full-list read or replace/update
  operations, returning the complete current plan and status counts
- safe API and CLI plan readback from the shared projection, with no independent
  adapter-side reconstruction from raw chat or tool text
- one compact desktop plan surface that renders only an authoritative non-empty
  plan and does not expose unsupported manual editing
- deterministic, full-repository, desktop, browser, recovery, compaction, and
  real-provider acceptance evidence

#### Acceptance

- [x] A plan contains at most 12 ordered steps; every step has one unique,
  non-blank bounded identifier and description plus one supported status.
- [x] At most one step may be `in_progress`; malformed, duplicate, oversized,
  or invalid-status updates fail structurally without changing durable state.
- [x] A valid update persists one bounded event and deterministically replaces
  or updates the session projection without scanning chat history.
- [x] Read and update results return the complete authoritative plan plus stable
  total, pending, in-progress, completed, and cancelled counts.
- [x] Active pending and in-progress steps remain available after replay,
  worker recovery, clarification or approval continuation, and compaction;
  completed steps are not presented as unfinished work.
- [x] `agent.plan` is parent-session only and cannot grant command, file,
  network, credential, approval, or workspace-write authority.
- [x] Fixed Research children cannot mutate the parent plan or expose a hidden
  recursive planning channel.
- [x] API, CLI, and desktop reads agree on step identifiers, order, text,
  status, counts, and latest update evidence.
- [x] Desktop plan UI appears only for a concrete non-empty durable plan and
  remains absent for idle, legacy, and empty-plan sessions.
- [x] Existing clarification and approval continuation, ordinary messages,
  tool batches, compaction, Web Gateway, and recovery remain compatible.
- [x] Targeted tests, full backend/static/eval gates, desktop checks/build,
  browser validation, and one real `deepseek-v4-flash` plan pass succeed.

#### Validation Evidence

- `make check` passed Ruff, Mypy across 235 source files, and the 8-case eval gate.
- `make test` passed all 1,049 backend and cross-surface tests.
- All nine desktop checks, the Node 22 production build, and Tauri `cargo check`
  passed; the native check used a temporary generated icon because the repository
  does not track the configured application icon.
- Browser acceptance rendered one authoritative two-step plan with `1/2` complete,
  rendered no plan region for an empty durable plan, and remained viewport-bound.
- Real `deepseek-v4-flash` called `agent.plan`, persisted exactly one
  `plan_updated` event, returned `PLAN_FINAL_OK`, and read back the same ordered
  plan and counts from the session API.

#### Explicit Non-Goals

- project-wide kanban, cross-session dependencies, assignees, due dates,
  reminders, notifications, cron scheduling, or distributed workflow dispatch
- user-authored plan editing, plan approval gates, branching DAGs, nested steps,
  arbitrary metadata, rich markdown, attachments, or more than 12 steps
- deriving plans from UI stages, assistant prose, hidden chain of thought, or
  planner-hook summaries without an explicit durable plan event
- copying Hermes process-local stores, global todo files, history hydration,
  256-item limits, or post-compression prompt mutation into Zebra Agent

### P125-CLOSE-01 - Phase 125 Closeout And Phase 126 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC / ARCH / SECURITY`
- Depends on: `P125-PLAN-01`
- Branch: `codex/p125-closeout-phase126-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 125 acceptance state and define one bounded external
source-discovery slice so general-purpose tasks can discover candidate sources
without introducing browser automation or widening Research-child authority.

#### Acceptance

- [x] `P125-PLAN-01` is recorded as merged through PR `#87` and done.
- [x] Phase 126 has one non-overlapping ready task with explicit owned paths.
- [x] Hermes Web tools are used only as a reference for provider separation,
  bounded result normalization, and untrusted-content labeling; Zebra retains
  its durable network authority, Policy, approval, Gateway, and event boundaries.

## Phase 126 Task Board

### P126-WEB-01 - Bounded Web Search Gateway

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / SECURITY / TOOLS / INTEGRATIONS / RUNTIME / APP / UI`
- Depends on: `P125-CLOSE-01`
- Branch: `codex/p126-web-01-bounded-web-search-gateway`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `packages/agent-tools/`, `packages/agent-integrations/`, `packages/agent-runtime/`, `apps/config/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`, `.env.example`

#### Goal

Give general-purpose parent sessions one typed, read-only `web.search` capability
that discovers a small ordered set of candidate sources through an explicitly
configured SearXNG JSON Gateway while preserving task-local network authority,
approval-before-egress, bounded output, and untrusted-content handling.

#### Deliverables

- one provider-neutral search request, result, response, and transport contract
  with a non-blank query of at most 500 characters and a result limit from one
  to five
- one explicit optional SearXNG JSON adapter configured by an HTTPS endpoint;
  missing or malformed configuration remains unavailable rather than falling
  back to public instances or a different provider
- Policy and Gateway checks that require `domain-allowlist`, an exact match for
  the configured search endpoint hostname, and one concrete approval before
  any DNS lookup or HTTP request
- one bounded credential-free GET with proxies and redirects disabled, public
  DNS enforcement, fixed timeout and response-byte ceilings, and strict JSON
  content handling
- deterministic provider-order normalization to bounded title, HTTPS URL, and
  snippet fields plus safe route, target, count, truncation, and provider
  metadata without raw response bodies in control events
- general and coding profile registration plus worker recovery and desktop HITL
  support, while fixed Research children remain offline and cannot search
- deterministic, full-repository, desktop, browser, approval-continuation, and
  real-model tool-selection acceptance evidence

#### Acceptance

- [x] `web.search` is visible only in general and coding parent manifests; it is
  absent from fixed Research children and unregistered arbitrary tool paths.
- [x] Query and limit validation happens before Policy or transport; blank,
  oversized, malformed, or extra arguments fail structurally.
- [x] No configured endpoint, `network_profile=none`, a non-HTTPS/private
  endpoint, or a missing exact endpoint-host allowlist match fails closed before
  DNS, credential, proxy, or transport access.
- [x] A valid call produces one approval whose operator-safe context includes
  the normalized provider hostname, bounded query, limit, route, and expected
  read-only side effect; transport call count remains zero before approval.
- [x] Exact approval continuation performs one credential-free GET against only
  the configured endpoint, with encoded query and limit parameters, redirects
  and environment proxies disabled, and fixed timeout and byte ceilings.
- [x] Response handling accepts only bounded JSON, preserves provider order,
  returns at most five unique HTTPS results, and bounds every title, URL, snippet,
  aggregate output, and metadata field before model exposure.
- [x] Search results are labeled untrusted and cannot grant authority, trigger
  an automatic fetch, or place raw provider bodies in durable control metadata.
- [x] API, CLI, Worker recovery, Policy, Gateway, and desktop approval surfaces
  agree on durable task network authority and the configured endpoint identity.
- [x] Existing `web.fetch`, local tools, plans, clarification and approval
  continuation, compaction, tool batches, and session recovery remain compatible.
- [x] Targeted tests, full backend/static/eval gates, all desktop checks/build,
  browser validation, and one real `deepseek-v4-flash` search selection and
  synthesis pass succeed.

#### Explicit Non-Goals

- browser automation, JavaScript rendering, cookies, login, form submission,
  downloads, uploads, screenshots, or computer use
- crawling, recursive fetch, automatic opening of result URLs, semantic ranking,
  result reranking, LLM summaries, persistent indexing, caching, or Web memory
- arbitrary public SearXNG fallback, multiple search vendors, vendor API keys,
  caller-defined endpoints, headers, methods, filters, locale, or safe-search
  controls in this slice
- wildcard domains, private-network endpoints, IP literals, redirects, explicit
  ports, caller credentials, process-global authority widening, or Research-child
  networking
- tool discovery bridges, Skill Registry, MCP discovery, SaaS connectors, or a
  default desktop search page

### P126-CLOSE-01 - Phase 126 Closeout And Phase 127 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC / ARCH / SECURITY`
- Depends on: `P126-WEB-01`
- Branch: `codex/p126-closeout-phase127-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 126 acceptance state and define one bounded local Skill
disclosure slice based on the current Hermes source without importing Hermes
runtime authority or prematurely building a Skill marketplace.

#### Acceptance

- [x] `P126-WEB-01` is recorded as merged through PR `#89` and done.
- [x] Phase 127 has one non-overlapping ready task with explicit owned paths.
- [x] Hermes commit `47d853fdf` is the reviewed source reference for discovery,
  exclusions, collision handling, and progressive disclosure; Zebra retains its
  typed registry, Policy, session, event, recovery, and authority boundaries.

## Phase 127 Task Board

### P127-SKILL-01 - Bounded Local Skill Progressive Disclosure

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / SECURITY / TOOLS / RUNTIME / APP`
- Depends on: `P126-CLOSE-01`
- Branch: `codex/p127-skill-01-local-progressive-disclosure`
- Owned paths: `packages/agent-core/`, `packages/agent-security/`, `packages/agent-tools/`, `packages/agent-runtime/`, `apps/config/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `configs/default.env`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`, `.env.example`

#### Goal

Let general and coding parent sessions discover configured local reusable
workflows on demand, then read one bounded Skill document or supporting text file
without treating Skill content as executable authority or loading all Skills into
the model context.

#### Deliverables

- one explicit optional local Skill-root configuration shared by API, CLI,
  direct runtime, and Worker recovery, with no configured roots as the default
- one bounded deterministic catalog that recursively discovers `SKILL.md`, skips
  dependency, cache, VCS, virtual-environment, and nested support-package paths,
  and fails closed on ambiguous exposed names
- typed `skills.list` and `skills.read` tools using metadata-first progressive
  disclosure, strict schemas, stable ordering, count and content ceilings, and
  no implicit Skill execution
- canonical containment, symlink-escape, traversal, binary, encoding, hidden
  secret-file, and oversized-content defenses for Skill and support-file reads
- explicit untrusted-guidance labeling that cannot grant tool, filesystem,
  command, network, credential, approval, or workspace-write authority
- deterministic, full-repository, desktop/browser compatibility, Worker
  recovery, and real-provider tool-selection acceptance evidence

#### Acceptance

- [x] With no configured Skill roots, neither Skill tool is registered or
  model-visible; invalid, missing, duplicate, or non-directory roots fail closed.
- [x] Discovery returns only bounded metadata for valid `SKILL.md` documents in
  deterministic order and never injects full Skill bodies into the base prompt.
- [x] Exposed names and descriptions are bounded; duplicate names across roots
  remain unavailable rather than selecting one by scan order.
- [x] `skills.read` accepts one known Skill plus an optional relative support-file
  path, rejects absolute paths and traversal, and cannot escape the canonical
  Skill directory through symlinks.
- [x] Only the primary `SKILL.md` and bounded UTF-8 files in approved support
  directories are readable; dependency trees, hidden secret files, binaries,
  oversized content, and nested Skill packages are excluded.
- [x] Returned content is labeled untrusted procedural guidance and causes no
  command, template expansion, environment capture, tool call, or network access.
- [x] Every tool subsequently suggested by a Skill still passes the ordinary
  registry, Policy, approval, Gateway, budget, event, and recovery paths.
- [x] General and coding parent sessions share the capability when configured;
  fixed Research children remain unchanged and receive no Skill tools.
- [x] API, CLI, direct runtime, and Worker recovery construct the same catalog
  from the same explicit configuration without process-global mutation.
- [x] Existing local tools, Web tools, plans, clarification, approvals, tool
  batches, compaction, cancellation, and session recovery remain compatible.
- [x] Targeted tests, full backend/static/eval gates, desktop checks/build,
  browser validation, and one real `deepseek-v4-flash` Skill pass succeed.

#### Validation Evidence

- The catalog discovered all 72 current Hermes `SKILL.md` documents from commit
  `47d853fdf`; four bodies above 32 KiB remained metadata-visible but correctly
  failed bounded full-body reads.
- `make check` passed Ruff, Mypy across 240 source files, and the 8-case eval gate;
  `make test` passed all 1,091 backend and cross-surface tests.
- All ten desktop contract checks, the Node 22 production build, and Tauri
  `cargo check` passed without adding a Skill management or HITL surface.
- Browser acceptance remained exactly viewport-bound at `762px`, had no
  horizontal overflow or console warnings/errors, and exposed no idle HITL
  approve/reject controls for ordinary Skill availability.
- Real `deepseek-v4-flash` executed `skills.list` then `skills.read` against the
  refreshed Hermes catalog and returned exactly `SKILL_FINAL_OK` in three model
  calls and two tool calls.

#### Explicit Non-Goals

- Skill installation, editing, deletion, generation, publishing, signing,
  downloading, updating, marketplace, registry service, or remote Skill roots
- automatic Skill selection, prompt-wide Skill-body injection, automatic script
  execution, template interpolation, environment-variable expansion, or secrets
- plugin discovery, MCP transport, tool-search bridges, dynamic tool loading,
  arbitrary manifests, role-specific child Skills, or Research-child Skills
- desktop Skill management pages, manual UI execution controls, Skill approvals,
  analytics, ranking, recommendations, caching, indexing, or semantic retrieval

### P127-CLOSE-01 - Phase 127 Closeout And Phase 128 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC / ARCH / SECURITY`
- Depends on: `P127-SKILL-01`
- Branch: `codex/p127-closeout-phase128-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 127 acceptance state and define one bounded historical
session-recall slice that turns Zebra's durable local history into an explicit
read-only parent-agent capability without exposing raw control events.

#### Acceptance

- [x] `P127-SKILL-01` is recorded as merged through PR `#91` and done.
- [x] Phase 128 has one non-overlapping ready task with explicit owned paths.
- [x] Hermes `session_search_tool.py` informs browse, literal search, and bounded
  read interaction only; Zebra retains typed Ports, SQLite projection/event
  ownership, Policy, tool budgets, session isolation, and safe serialization.

## Phase 128 Task Board

### P128-HIST-01 - Bounded Durable Session Recall

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / STORAGE / TOOLS / RUNTIME / APP`
- Depends on: `P127-CLOSE-01`
- Branch: `codex/p128-hist-01-bounded-durable-session-recall`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `packages/agent-tools/`, `packages/agent-runtime/`, `packages/agent-security/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Let general and coding parent sessions explicitly browse, search, and read
bounded prior-session text from their configured local SQLite database so the
agent can recover useful task context without treating all history as prompt
context or conflating raw events with durable memory.

#### Deliverables

- provider-neutral session-history request, result, message, and Port contracts
  for browse, literal query, and paginated single-session reads
- one SQLite adapter that scans only bounded recent projections and event rows,
  excludes the active session, and deterministically projects safe user and
  assistant text without raw event payload exposure
- one typed read-only `sessions.search` tool with mutually exclusive call shapes,
  strict argument validation, stable ordering, pagination, and aggregate output
  ceilings
- shared API, CLI, direct-runtime, and Worker composition through an optional
  history Port; no configured history adapter means the tool is unavailable
- explicit untrusted-history labeling and compatibility evidence across Policy,
  tool batches, compaction, recovery, desktop, browser, and a real model

#### Acceptance

- [x] `sessions.search` is registered only when a history Port is supplied and
  appears in general and coding parent manifests but not fixed Research children.
- [x] No arguments browses bounded newest-first prior sessions; `query` performs
  bounded case-insensitive literal matching; `session_id` reads one bounded page.
- [x] Browse, query, and read shapes reject unknown fields, incompatible argument
  combinations, malformed identifiers, invalid offsets, and out-of-range limits.
- [x] Search scans at most a fixed number of recent sessions and safe message
  events, preserves deterministic relevance then recency order, and reports
  truncation rather than silently implying exhaustive recall.
- [x] Results exclude the active session and expose only bounded session identity,
  title, status, timestamps, snippets, and user/assistant messages.
- [x] Raw event payloads, tool arguments or outputs, approvals, clarifications,
  plans, memory records, credentials, environment values, and hidden reasoning
  are never returned by this tool.
- [x] Read pagination uses stable event sequence order, returns explicit offset,
  count, next offset, and truncation, and cannot cross into another session.
- [x] Historical content is labeled untrusted and cannot grant tools, filesystem,
  command, network, credential, approval, or workspace-write authority.
- [x] API, CLI, direct runtime, and Worker use the same Port contract and SQLite
  adapter; worker recovery retains the active-session exclusion.
- [x] Existing Skills, Web tools, plans, clarification, approvals, local tools,
  concurrent batches, compaction, cancellation, and recovery remain compatible.
- [x] Targeted tests, full backend/static/eval gates, desktop checks/build,
  browser validation, and one real `deepseek-v4-flash` recall pass succeed.

#### Validation Evidence

- backend: targeted storage/tool/harness/Worker checks passed, followed by the
  full test suite, Ruff, Mypy, and the 8-case eval release gate
- desktop: all ten focused checks, the Node 22 production build, and Tauri
  `cargo check` passed; the existing aggregate bundle-size warning remains
- browser: the live API/Vite workspace stayed viewport-bound at `1200x762`, all
  observed API requests completed successfully, ordinary idle state exposed no
  HITL controls, and the console was clean after naming the Sender input
- provider: `deepseek-v4-flash` searched for `ZEBRA_P128_RECALL_7F3A`, read the
  returned prior session, observed only explicitly untrusted safe history, and
  completed with `HISTORY_FINAL_OK: ZEBRA_P128_RECALL_7F3A`

#### Explicit Non-Goals

- FTS5, BM25, semantic or vector retrieval, embeddings, LLM summaries, reranking,
  fuzzy search, stemming, cached indexes, or prompt-wide history injection
- cross-profile database discovery, cross-tenant recall, remote history, shared
  team history, session lineage, subagent history, automation-source demotion,
  or current-session self-search
- raw event inspection, tool-trace replay, approval reconstruction, hidden model
  reasoning, memory mutation, session mutation, deletion, export, or import
- desktop history management pages, search UI, manual transcript editing, HITL,
  notifications, recommendations, or automatic recall without a tool call

### P128-CLOSE-01 - Phase 128 Closeout And Phase 129 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC / ARCH / SECURITY`
- Depends on: `P128-HIST-01`
- Branch: `codex/p128-closeout-phase129-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 128 acceptance state and define one bounded workspace
inventory slice that lets a general agent discover local material without a
known filename, search term, shell command, or prompt-wide repository dump.

#### Acceptance

- [x] `P128-HIST-01` is recorded as merged through PR `#93` and done.
- [x] Phase 129 has one non-overlapping ready task with explicit owned paths.
- [x] Updated Hermes commit `3f0b0e20e` is the reviewed source baseline;
  Hermes `search_files(target="files")` informs bounded file discovery only,
  while Zebra keeps a separate typed workspace-list contract, LocalWorkspace
  containment, Policy, tool budgets, and deterministic output ceilings.

## Phase 129 Task Board

### P129-TOOL-01 - Bounded Workspace Inventory Tool

- Status: `Done`
- Owner: `Codex`
- Suggested role: `TOOLS / RUNTIME / SECURITY`
- Depends on: `P128-CLOSE-01`
- Branch: `codex/p129-tool-01-bounded-workspace-inventory`
- Owned paths: `packages/agent-core/`, `packages/agent-tools/`, `packages/agent-runtime/`, `packages/agent-security/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Give general and coding parent sessions one typed read-only `files.list` tool
for deterministic, bounded directory and shallow-tree discovery inside the
active workspace, so document analysis and other non-coding tasks can locate
relevant local material before choosing a file to search or read.

#### Deliverables

- one `files.list` contract with a workspace-relative root, bounded depth,
  explicit offset and limit, and stable machine-readable metadata
- deterministic directory-first then filename ordering over normalized relative
  paths, with fixed scanned-entry and aggregate output-byte ceilings
- LocalWorkspace containment plus fail-closed handling for missing paths,
  non-directories, hidden roots, symlinks, and unsupported arguments
- default exclusion of hidden entries, symlinks, VCS data, dependency trees,
  virtual environments, caches, generated build trees, and oversized scans
- parent general/coding registration and read-only Policy compatibility without
  changing the fixed Research-child manifest or adding a desktop control surface

#### Acceptance

- [x] `files.list` is model-visible and executable in general and coding parent
  sessions, is parallel-safe, and remains absent from fixed Research children.
- [x] No path lists the workspace root; a relative directory path lists only
  contained entries; depth is explicit and bounded from `1` through `4`.
- [x] Results are stable across repeated calls, directories sort before files,
  and each entry exposes only normalized relative path, kind, and bounded size.
- [x] Offset and limit provide deterministic pagination with explicit
  `returned_count`, `next_offset`, and `truncated` metadata.
- [x] The adapter scans at most a fixed entry ceiling and caps aggregate output;
  hitting either ceiling is reported rather than implying a complete inventory.
- [x] Absolute paths, traversal, missing roots, file roots, hidden roots,
  malformed depth/offset/limit values, and unknown fields fail before listing.
- [x] Hidden entries, symlinks, VCS internals, dependency trees, virtual
  environments, caches, and generated build trees are never returned or followed.
- [x] Listing is read-only under every Policy profile and cannot grant file,
  command, network, credential, approval, or workspace-write authority.
- [x] Existing file read/search, Skills, session recall, Web tools, plans,
  clarification, approvals, batches, compaction, cancellation, and recovery work.
- [x] Targeted tests, full backend/static/eval gates, desktop checks/build,
  browser compatibility, and one real `deepseek-v4-flash` list/read pass succeed.

#### Explicit Non-Goals

- file contents, hashes, MIME detection, recursive full-repository dumps,
  persistent indexes, watchers, caches, semantic ranking, vectors, or summaries
- directory creation, rename, move, delete, upload, attachment ingestion, file
  mutation, shell fallback, Git mutation, or automatic file reads
- exposing ignored dependencies, hidden files, symlinks, external mounts, Home,
  credentials, environment values, raw filesystem metadata, or OS absolute paths
- Research-child expansion, desktop file browser, preview UI, drag-and-drop,
  browser automation, MCP, connectors, dynamic tool loading, or `tool_search`

#### Validation Evidence

- `76` focused tool, Harness, and Policy tests passed.
- All `1132` backend tests, Ruff, Mypy across `245` source files, and the
  8-case eval release gate passed.
- All ten desktop contract checks, the Node `22.17.0` production build, and
  Tauri `cargo check` passed.
- Browser acceptance at `1200x762` connected to the isolated API with only 200
  responses, no console warning/error/issue, no viewport overflow, and no idle
  HITL controls.
- A real `deepseek-v4-flash` general/read-only run called `files.list` on
  `materials`, then `files.read`, and completed with
  `LIST_FINAL_OK: ZEBRA_P129_LIST_READ_8C41`.

### P129-CLOSE-01 - Phase 129 Closeout And Phase 130 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC / CORE / OBS`
- Depends on: `P129-TOOL-01`
- Branch: `codex/p129-closeout-phase130-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 129 acceptance state and define one narrow trace
correlation slice for the same-name parallel-tool projection defect exposed by
the real provider acceptance run.

#### Acceptance

- [x] `P129-TOOL-01` is recorded as merged through PR `#95` and done.
- [x] The defect is scoped to trace evidence correlation; durable execution,
  provider conversation, and ordered event persistence remain correct.
- [x] Phase 130 has one non-overlapping task with explicit core, API, CLI,
  test, and documentation ownership.

## Phase 130 Task Board

### P130-OBS-01 - Durable Tool Trace Correlation

- Status: `Done`
- Owner: `Codex`
- Suggested role: `CORE / OBS / API / CLI`
- Depends on: `P129-CLOSE-01`
- Branch: `codex/p130-obs-01-durable-tool-trace-correlation`
- Owned paths: `packages/agent-core/`, `apps/api/`, `apps/cli/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`

#### Goal

Correlate each proposed, policy-evaluated, started, and completed or failed tool
event by the existing internal `tool_call_id`, so core, API, and CLI traces keep
the correct arguments and policy evidence for parallel same-name calls.

#### Deliverables

- additive `tool_call_id` correlation on tool proposal, policy, and terminal
  execution events, matching the identifier already present on start events
- one shared core projection strategy that tracks multiple pending calls by ID
  while retaining deterministic provider/result order
- API and CLI persisted-event serializers with equivalent correlation behavior
- legacy-event compatibility for durable sessions written before Phase 130

#### Acceptance

- [x] Every newly emitted proposal, policy, start, completion, and failure event
  for an executable tool carries the same non-blank `tool_call_id`.
- [x] Parallel calls with the same tool name retain their own arguments, policy
  context, output, and metadata in core, API, and CLI traces.
- [x] Parallel calls with different names and sequential calls preserve their
  existing trace ordering and public response shape.
- [x] Legacy event streams without correlation IDs still project deterministically
  using provider-order compatibility rather than dropping all arguments.
- [x] Unknown, duplicate, denied, approval-required, clarification, plan,
  failed-tool, and resumed-continuation behavior remains unchanged.
- [x] Correlation metadata does not expose credentials, environment values,
  hidden reasoning, or additional tool authority.
- [x] Focused core/API/CLI regression matrices, all backend/static/eval gates,
  desktop compatibility checks/build, and one real provider batch pass succeed.

#### Explicit Non-Goals

- changing tool execution order, parallel scheduling, budgets, retry behavior,
  policy decisions, approvals, cancellation, recovery, or provider messages
- adding trace IDs to public response objects, changing event types, rewriting
  historical databases, or migrating stored event payloads
- distributed tracing, spans, OpenTelemetry export, remote observability,
  analytics, dashboards, new desktop trace controls, or raw event UI

#### Validation Evidence

- `75` focused core event, concurrent-batch, shared projection, API, and CLI
  tests passed, including correlated and legacy same-name matrices.
- All `1134` backend tests, Ruff, Mypy across `245` source files, and the
  8-case eval release gate passed.
- All ten desktop contract checks, the Node `22.17.0` production build, and
  Tauri `cargo check` passed; Cargo used the existing local cache after one
  transient crates.io low-speed timeout.
- A real `deepseek-v4-flash` run emitted two same-name `files.read` calls in one
  parallel batch; proposal, policy, start, and completion IDs matched, the CLI
  trace retained `a.txt -> TRACE-A-130` and `b.txt -> TRACE-B-130`, and the final
  answer was `TRACE_FINAL_OK: TRACE-A-130|TRACE-B-130`.

### P130-CLOSE-01 - Phase 130 Closeout And Phase 131 Planning

- Status: `Done`
- Owner: `Codex`
- Suggested role: `DOC / ARCH / PRODUCT`
- Depends on: `P130-OBS-01`
- Branch: `codex/p130-closeout-phase131-plan`
- Owned paths: `docs/AGENT_TASKS.md`, `PROGRESS.md`

#### Goal

Record the merged Phase 130 acceptance state and define one bounded input slice
that lets users attach local text material directly to a general Agent task
without first copying it into the selected workspace.

#### Acceptance

- [x] `P130-OBS-01` is recorded as merged through PR `#97` and done.
- [x] Phase 131 is limited to durable UTF-8 text attachments on task creation
  and later user messages, with explicit count, per-file, and aggregate limits.
- [x] Phase 131 has one non-overlapping task with explicit core, storage, API,
  Harness, desktop, test, and documentation ownership.

## Phase 131 Task Board

### P131-INP-01 - Durable Bounded Text Attachments

- Status: `Ready`
- Owner: `Codex`
- Suggested role: `CORE / STORAGE / API / HARNESS / UI / SECURITY`
- Depends on: `P130-CLOSE-01`
- Branch: `codex/p131-inp-01-durable-bounded-text-attachments`
- Owned paths: `packages/agent-core/`, `packages/agent-storage/`, `packages/agent-context/`, `apps/api/`, `apps/cli/`, `apps/worker/`, `UI/desktop/`, `tests/`, `docs/AGENT_TASKS.md`, `PROGRESS.md`, `README.md`, `UI/README.md`

#### Goal

Let users attach bounded local UTF-8 text material when creating a task or
adding a user message, persist the material with the session, and supply it to
the parent model as explicitly untrusted task input without widening workspace,
tool, command, network, credential, approval, or Research-child authority.

#### Deliverables

- provider-neutral attachment input and durable metadata contracts with stable
  attachment identity, filename, media type, byte size, digest, and message link
- strict API parsing for bounded base64-encoded UTF-8 text attachments on task
  creation and message append, with atomic rejection before execution
- local SQLite-backed payload persistence that reuses the existing artifact
  payload lifecycle rather than creating a second binary storage subsystem
- deterministic parent-Harness context projection with explicit untrusted-input
  labels, fixed per-file and aggregate text ceilings, and recovery compatibility
- desktop Composer file selection, removable pending attachment chips, truthful
  upload/error state, and durable session readback without idle HITL controls

#### Acceptance

- [ ] New tasks and later ordinary user messages accept zero or more bounded
  UTF-8 text attachments and preserve message-to-attachment correlation.
- [ ] The API rejects unknown attachment fields, malformed base64, blank or
  unsafe names, unsupported media types, invalid UTF-8, excessive count,
  excessive per-file bytes, and excessive aggregate bytes before model execution.
- [ ] Accepted payload bytes, digest, size, media type, safe filename, session,
  and originating message are durable and survive API or Worker restart.
- [ ] Parent model context contains deterministic bounded attachment text under
  an explicit untrusted-user-material boundary and never treats it as authority.
- [ ] Recovery and later-message execution reconstruct the same attachment
  context exactly once without duplicating text into the visible chat message.
- [ ] Session readback exposes safe attachment metadata but not base64 payloads,
  absolute storage paths, credentials, environment values, or hidden reasoning.
- [ ] Desktop users can select, inspect, remove, submit, and recover attachment
  metadata; selection errors are actionable and pending files clear only on
  successful submission.
- [ ] Existing text-only create and message payloads remain backward compatible,
  and approvals, clarification, plans, compaction, tools, cancellation, history,
  artifacts, API, CLI, Worker, and desktop behavior remain compatible.
- [ ] Focused attachment matrices, all backend/static/eval gates, desktop checks
  and build, Tauri validation, browser acceptance, and one real provider pass
  over attached material succeed.

#### Explicit Non-Goals

- PDF, DOCX, spreadsheet, archive, audio, video, image, OCR, vision, MIME
  sniffing, document conversion, embeddings, semantic indexing, or summarization
- arbitrary binary uploads, remote URLs, cloud object storage, signed links,
  cross-session reuse, attachment mutation, export, sharing, or collaboration
- automatic workspace writes, hidden attachment directories, shell parsing,
  prompt-wide filesystem ingestion, Research-child attachment access, or new
  filesystem, command, network, credential, approval, or policy authority
