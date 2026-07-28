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
6. `in_progress` - Run focused, full, static and Eval gates; update durable evidence,
   commit, push and open the focused PR.

### CTX-MEM-01 Errors Encountered

- The first baseline command used nonexistent paths
  `tests/agent_core/test_context_window.py` and
  `tests/worker/test_execution_errors.py`; no tests ran. The actual context test
  is `tests/agent_core/test_context_window_gate.py`, and worker coverage is in
  lifecycle/finalization suites. The corrected baseline passed `33` tests.

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
