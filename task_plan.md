# Task Plan

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 0 (Zebra backend lane)

1. `completed` - Verify exact base `1d19abb`, merge-base, clean worktree,
   remote ref `fork/codex/znx-wave45-task-ui-foundation-v1`, and create
   `codex/znx-hosted-outer-attempts-v1`.
2. `completed` - Audit the full caller/transaction/recovery chain and write
   the docs-first existing-state audit + Wave 5 task card (W5-DSH-01/02/03,
   R1-R8 red matrix).
3. `completed` - Commit red/contract tests that prove the six real gaps at
   the exact base (no production edits).
4. `completed` - Run the minimal focused baseline checks; separate inherited
   exact-base failures from new red failures.
5. `completed` - Leave the worktree clean and report exact
   branch/HEAD/merge-base/changed paths/tests/security/gaps; stop at Gate 0.
   Gate 0 evidence is ready for owner acceptance; acceptance is not claimed
   by this lane and Phase 1 starts only on owner acceptance.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Phase 1 / Gate 1 (Zebra backend lane)

1. `completed` - Owner accepted Gate 0; synchronize: verify ancestry and
   remote refs, create backup ref, rebase the five Gate 0 commits onto
   accepted production `6afbafa`, re-run Gate 0 red suite (11 failed) and
   focused baseline (37 passed).
2. `completed` - Red-first: add 8 Phase 1 tests and demonstrate 7 failures
   on the synchronized base.
3. `completed` - Freeze generic Task attempt policy at creation (caps 2/1,
   retryable codes, profile id) with fail-closed recovery.
4. `completed` - Activate Hosted Worker Attempt 1 -> Attempt 2 coordination
   with durable start/outcome coordinates and crash recovery; W5-DSH-01
   fail-closed guard; usage-attempt linkage; accepted-attempt-only canonical
   final.
5. `completed` - Gate 1 evidence: red-before/green-after, Gate 0 red
   classification, full `2212/13/9` vs base `2199/8/9`, eval 10/10,
   ruff/mypy identical to base, crash/security findings, peer contract
   deltas; clean tree; ready for owner acceptance; stop before Phase 2.

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
