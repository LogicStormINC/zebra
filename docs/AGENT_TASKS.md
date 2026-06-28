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

- Status: `Ready`
- Owner: `Unassigned`
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

- [ ] Trace-facing outputs reuse the same proxy route vocabulary as policy and tool execution metadata.
- [ ] Proxy approval metadata remains deterministic across blocked, approval, and executed paths.
- [ ] Non-proxy trace outputs remain backwards compatible.

### P23-CLOSE-01 - Phase 23 Closeout And Next Planning

- Status: `Locked`
- Owner: `Unassigned`
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

- [ ] Proxy-aware approval readback evidence is recorded.
- [ ] Next phase starter tasks are ready and path-scoped.
