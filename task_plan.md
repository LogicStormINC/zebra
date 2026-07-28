# Task Plan

## CTX-MEM-01 - Issue #197 Context Continuity And Governed Recall

1. `completed` - Verify issue `#197`, compare Codex, Claude Code, Pi Agent and
   Hermes, register one path-bounded task, and establish an isolated worktree.
2. `completed` - Land the v1.1 design baseline and executable implementation
   plan before changing runtime behavior.
3. `completed` - Add exact-tail compaction and one stricter original-history retry,
   then classify persistent context overflow as recoverable suspension.
4. `completed` - Add evidence-gated, conflict-safe candidate promotion and append
   its review events through the existing memory governance flow.
5. `completed` - Add SQLite FTS-backed relevant recall with stable-rule lane,
   deduplication, repo isolation and a token budget.
6. `completed` - Run focused, full, static and Eval gates; update durable evidence,
   commit, push and open the focused PR.

### CTX-MEM-01 Errors Encountered

- The first baseline command used nonexistent paths
  `tests/agent_core/test_context_window.py` and
  `tests/worker/test_execution_errors.py`; no tests ran. The actual context test
  is `tests/agent_core/test_context_window_gate.py`, and worker coverage is in
  lifecycle/finalization suites. The corrected baseline passed `33` tests.

## MEM-MEM0-ADP-01 - Mem0 Gateway Adapter

1. `completed` - Review the proven Mem0 REST contract, Core Gateway values and
   existing integration HTTP patterns.
2. `completed` - Claim a dedicated stacked branch with exact integration,
   test and governance paths.
3. `completed` - Implement disabled-safe configuration, opaque namespace mapping,
   strict REST decoding and bounded circuit-breaker behavior.
4. `completed` - Implement publish/search/delete over the Core Port with
   `infer=false`, provider-ref lookup and degraded error normalization.
5. `completed` - Add focused contract/fault tests, run repository validation and
   record the stacked handoff.

### Decisions

- Use the installed `httpx` dependency directly; the Mem0 SDK adds no needed
  contract and would leak provider behavior upward.
- Provider-ref persistence remains `MEM-GW-DEL-01`. This Adapter consumes a
  narrow lookup Port for delete and never creates a hidden in-memory fact source.
- Disabled and failed Mem0 paths return typed Gateway outcomes and never alter
  authoritative `MemoryStorePort` state.

## MEM-MEM0-SPIKE-01 - Mem0 OSS Contract And Operations Probe

1. `completed` - Inspect the pinned running Mem0 OpenAPI/source without reading
   secrets or issuing memory writes.
2. `completed` - Combine the reviewed Store, Gateway and Compose prerequisites
   in an isolated stacked worktree and claim the Spike paths.
3. `completed` - Add a deterministic OpenAI-compatible embedding stub and isolated
   Compose test overlay with no external credential.
4. `completed` - Exercise authenticated `infer=false` add/search/update/history/
   delete, namespace filters, duplicate delivery, restart and failure behavior.
5. `completed` - Record exact observed contracts, run focused/repository gates and
   preserve the separate real-provider credential gate.

### Decisions

- The deterministic provider validates Mem0 OSS/server/pgvector semantics only;
  it does not satisfy real-provider compatibility.
- The Spike remains isolated from the long-running dependency volumes and never
  changes Zebra's governed `MemoryStorePort` authority.

## MEM-GW-CON-01 - Provider-neutral Agent Memory Gateway Contract

1. `completed` - Audit the governed `MemoryStorePort`, authoritative Store
   composition, Mem0 direction and task dependency boundary.
2. `completed` - Claim an isolated stacked worktree on `CLOUD-STO-AUTH-01` with
   provider-neutral Core/test ownership only.
3. `completed` - Implement validated publish/search/delete values and Protocol.
4. `completed` - Prove confirmed-only publication, opaque authority, revalidatable
   hits, partial/degraded behavior and provider-independent schemas.
5. `completed` - Run focused and repository validation, record evidence and handoff.

### Decisions

- `MemoryStorePort` remains authoritative for governed lifecycle and content.
- Gateway hits intentionally omit memory text and Zebra confidence; callers must
  resolve `MemoryId` through the Store before prompt admission.
- Mem0 is the first planned adapter, but no provider or transport type enters Core.

## CLOUD-STO-AUTH-01 - Complete Authoritative Store Composition

1. `completed` - Audit every API/Worker durable collaborator that can advance a
   Session, gate an effect, or govern memory, including constructor call sites.
2. `completed` - Claim the exact Core/Storage/API/Worker/test/governance paths on
   an isolated branch stacked directly on `CLOUD-STO-SEAM-01`.
3. `completed` - Extend the flat `ControlPlaneStores` with typed Ports and keep
   the local SQLite builder as the only API/Worker constructor root.
4. `completed` - Replace legacy path lookups with injected stores and add A/B
   regressions that prove the unused database is not even created.
5. `completed` - Run focused, full and quality validation, record inherited
   baseline failures, close the card to Review, and commit the local slice.

### Decisions

- Keep one flat composition value. Backend hierarchies, backend enums and a
  PostgreSQL selection switch would add no value before a second adapter exists.
- Context lifecycle and handoff remain aggregate transaction boundaries; future
  adapters implement those Ports atomically instead of exposing their tables to
  API or Worker composition.
- `database_path` remains a local-profile configuration input, not a durable
  authority locator after a `ControlPlaneStores` bundle has been injected.
- Zebra's governed `MemoryStorePort` remains authoritative. Any Mem0 or other
  semantic-memory integration is a separate, derived, degraded-safe Gateway.
- The branch is local and unpushed. Merge order remains
  `EMB-PLAN-01 -> CLOUD-STO-SEAM-01 -> CLOUD-STO-AUTH-01`.
## CLOUD-COMPOSE-INFRA-01 - Docker Compose Dependency Baseline

1. `completed` - Audit repository container assets, architecture sequencing and
   Mem0 OSS self-hosting and release behavior.
2. `completed` - Register and claim the dependency-only task on an isolated
   branch stacked behind `CLOUD-STO-SEAM-01`.
3. `completed` - Create the base dependency Compose, optional Mem0 overlay,
   pinned non-root boot-smoke image, safe environment template and runbook.
4. `completed` - Validate rendered contracts and start base plus optional Mem0
   services through real migrations, health and authentication checks.
5. `completed` - Update architecture/progress evidence, obtain independent review,
   run repository checks
   and commit the task without pushing or merging stacked dependencies.

### Decisions

- Dependency containers and Zebra application containers have separate task,
  file and Compose lifecycles.
- `redis-live`, Zebra PostgreSQL, Mem0 PostgreSQL and Mem0 history never share a
  persistence role; Mem0 remains derived and rebuildable.
- `AgentMemoryGateway` is provider-neutral. Mem0 receives only confirmed memory
  with `infer=false`; every retrieval is revalidated against `MemoryStorePort`.
- The pinned Mem0 image and Compose overlay prove boot only. Real write/search,
  idempotency, deletion and namespace behavior remain a separate credentialed Spike.

## CLOUD-STO-SEAM-01 - Control-Plane Storage Composition Seam

1. `completed` - Audit API/Worker SQLite construction, existing Store Ports,
   Agent Memory semantics and the revised dependency order.
2. `completed` - Register and claim the path-bounded task on an isolated stacked
   worktree while preserving the hard `EMB-PLAN-01` merge order.
3. `completed` - Add one flat control-plane Store bundle and local SQLite builder.
4. `completed` - Inject the bundle through API/SSE and Worker flows, prove
   same-path injection and reject partial split backends before any write.
5. `completed` - Run focused, full and quality validation; record remaining Port
   gaps and the next PostgreSQL/memory task without adding a cloud dependency.

### Decisions

- The user reprioritized Zebra durable storage and memory foundations ahead of
  further Trench work on 2026-07-23.
- PostgreSQL remains durable truth, S3-compatible storage owns payload bytes,
  Redis live state is erasable, and semantic memory remains a separate,
  degraded-safe `AgentMemoryGateway` rather than a `MemoryStorePort` replacement.
- This task composes only the five existing control-plane Ports. Legacy durable
  stores without adequate Ports are recorded in `CLOUD-STO-AUTH-01`; the partial
  bundle fails closed if its database differs from those legacy stores.
- Because PR `#194` is still open, this local branch is stacked and cannot merge
  before `EMB-PLAN-01`; it will not push or merge as part of this local task.

## EMB-AGUI-SPIKE-01 - Official Python AG-UI Compatibility Spike

1. `in_progress` - Commit the reviewed Embedded architecture baseline without
   the user's unrelated `AGENTS.md` timestamp change, then create the isolated
   stacked worktree and task branch.
2. `pending` - Pin and inspect the official Python AG-UI protocol SDK and encoder.
3. `pending` - Add canonical stream, SSE round-trip, interrupt/resume, and
   unknown-event compatibility fixtures under the task-owned test path.
4. `pending` - Run focused, full, and quality validation; distinguish any
   unrelated baseline failures from task regressions.
5. `pending` - Record the version matrix, observed boundaries, follow-up contract
   decisions, and final branch handoff.

### Decisions

- This is a test-only Spike. No production package, API route, Worker composition,
  Zebra Domain Event, or Trench/CopilotKit code is in scope.
- Maintainer direction explicitly activates the Spike before the architecture
  branch merges. The implementation branch is stacked on `zebra-cloud-trench`
  and must not merge first.
- The generic worktree skill required by `executing-plans` is not installed;
  use Git's native worktree commands with the same isolation guarantees.

## EMB-PLAN-01 - Zebra Embedded Architecture Consolidation

1. `completed` - Audit the draft Embedded architecture, repository source-of-truth
   documents, current cloud activation state, and existing implementation seams.
2. `completed` - Consolidate the draft into one authoritative architecture that
   uses CopilotKit in Trench and removes the custom Zebra React SDK plan.
3. `completed` - Register dependency-ordered Embedded, Trench, cloud, analysis,
   writeback, memory, and GA task cards with explicit owned paths and gates.
4. `completed` - Synchronize durable project progress and worklog records without
   activating implementation tasks prematurely.
5. `completed` - Validate document consistency, file limits, and the final diff.

### Decisions

- `zebra-cloud-trench` owns this architecture and task-registry change only;
  implementation cards use one task, branch, worktree, owner, and PR each.
- Trench owns CopilotKit React v2 and its Copilot Runtime/BFF. Zebra exposes an
  AG-UI adapter and remains the durable Task, Event, Policy, approval, tool
  receipt, and Artifact authority.
- The first production business slice is read-only. Analysis, controlled
  writeback, the optional Memory Gateway, and multi-tenant GA follow explicit gates.

### Errors Encountered

- The first status-search command placed Markdown backticks inside a
  double-quoted shell pattern, so zsh attempted command substitution for
  `Ready` and `In`. No files changed. The replacement check uses literal
  patterns without backticks.
- The repository-wide file-size gate reports two pre-existing violations in
  untouched files: `CodexConversationPane.styles.ts` at 561/500 lines and
  `agent_core/contracts/events.py` at 505/500 lines. All three new documents are
  within their applicable limits; the unrelated baseline was not modified.
- The generic planning skill stop checker reported `0/0 phases` because this
  repository's existing `task_plan.md` uses numbered backticked statuses rather
  than the checker's checkbox headings. The five EMB-PLAN-01 entries above are
  explicitly `completed`; targeted document validation is the completion gate.

## CTX-SEG-02 - Follow-up Context And Budget Recovery

1. `completed` - Register and claim the path-bounded repair task on an isolated branch.
2. `completed` - Preserve a bounded prior user/assistant checkpoint across terminal follow-up rollover.
3. `completed` - Remove implicit low call ceilings and suspend recoverably when an explicit hard budget cannot fit a complete batch.
4. `completed` - Hide NoopVerifier status noise while keeping real verifier evidence visible.
5. `completed` - Update durable architecture/status records and run focused, full, Desktop, and quality gates.

## WEB-UX-01 - Trusted Local Read-Only Web Auto Execution

1. `completed` - Register and claim a path-bounded task on an independent branch.
2. `completed` - Treat durable allowlist Web authority as automatic allow and
   explicit local trusted mode as a one-time operator trust boundary.
3. `completed` - Default new Desktop tasks to trusted local Web authority and
   preserve durable profile rendering.
4. `completed` - Run focused, full repository, Desktop, and browser regressions;
   then close the task with durable evidence.
5. `completed` - Upgrade existing local Tasks at execution time, honor the
   system HTTPS proxy, remove local command/MCP approval interruptions, and rerun
   the real old-Task plus full regression chain.

## SUBAGENT-UX-01 - Model-Native Subagent Delegation

1. `completed` - Approve and independently review the model-native delegation
   design, then register a separate owned task and branch.
2. `completed` - Inject manifest-aware parent guidance and require a model-authored
   delegation reason with actionable validation recovery.
3. `completed` - Prove direct, parent-tool, complex delegation, invalid-call retry,
   child non-recursion, and failed-child fallback behavior.
4. `completed` - Update durable architecture/status records and run focused, full,
   static, Eval, and real-model simple-task validation.

## CTX-SEG-01 - Stable Task And Automatic Internal Segments

1. `completed` - Record ADR-013, supersede the explicit user handoff decision,
   and define the dependency-ordered Task/Segment implementation roadmap.
2. `completed` - Remove ordinary Desktop handoff rendering, navigation, and client
   creation actions without changing backend safety contracts.
3. `completed` - Add a deterministic regression that forbids stage handoff controls
   on the ordinary user surface.
4. `completed` - Run Desktop checks/build and repository validation, then update
   durable status, findings, and worklog evidence.
5. `completed` - Add Task/Segment domain and SQLite projection/migration contracts.
6. `completed` - Add Task API, monotonic cross-Segment stream, and active-Segment routing.
7. `completed` - Add deterministic lifecycle controller and automatic safe rollover.
8. `completed` - Bind Desktop to stable Task identity and add cross-Segment regressions.
9. `completed` - Run all gates, update closeout evidence, push, and open the PR.

### Errors Encountered

- The first full test run found `session_handoffs.py` at 526 lines after the
  atomic Task CAS integration. Task-specific storage logic and row types were
  moved to their owned modules; the file is now 497 lines and the gate passes.
