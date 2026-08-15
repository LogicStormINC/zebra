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
5. `completed` - Root correction closes request-envelope equality, frozen
   policy/budget rollover, epoch/Turn identity, continuation and crash/Step
   recovery gaps; split tests below size limits and freeze the FinOS peer
   fixture.
6. `completed` - Gate 1 evidence: 30/30 Gate 1, Gate 0 8 green / 3 Phase 2
   red, focused 38/38, full `2237/11/9` vs base `2199/8/9`, eval 10/10,
   ruff/mypy identical to base; ready for owner acceptance; stop before
   Phase 2.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Phase 2 / Gate 2 (Zebra backend lane)

1. `completed` - Owner accepted Gate 1 and authorized Phase 2; verified
   branch/HEAD `4797af8`/clean status/merge-base `6afbafa` and re-confirmed
   the three intentional Phase 2 reds at the starting HEAD.
2. `completed` - Red-first: add the Phase 2 coverage/correction matrix
   (independence, trusted-typed-only, frozen correction budget 0/1, exact
   after-correction code, matching advertised producer + required choice,
   frozen-policy retryability, Attempt 2 evidence carryover, safe terminal
   verdict, public projection boundary) and update R2 x2 / R6 to the exact
   code contract; `10 failed / 15 passed` at the starting HEAD.
3. `completed` - Drive the existing completion-evidence correction path from
   the frozen `max_corrections_per_attempt`; emit
   `completion_evidence_missing_after_correction` on exhaustion and make it
   the only retryable coverage code; keep `completion_evidence_missing`
   non-retriable.
4. `completed` - Add safe coverage counts/verdict to the existing
   completion-evidence status metadata and the terminal payloads; persist
   counts in the outcome record for crash recovery; expose only the safe
   verdict publicly.
5. `completed` - Root-correct the W5-DSH-01 guard for in-attempt correction
   dispatches (plain responses not mirrored; runtime observations excluded
   from the stable envelope); adapt the four existing tests that asserted
   the old correction contract; keep all files under repository limits.
6. `completed` - Gate 2 evidence: Phase 2 + reds `25/25`, Phase 1/Gate 1
   `30/30`, focused `140/140`, full `2254/8/9` (only the inherited 8
   exact-base failures), eval `10/10`, ruff 11 / mypy 13 identical to base,
   file-size gate same 10 inherited violations; freeze the Gate 2 peer
   fixture and notify the FinOS peer task.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 2 correction (root audit)

1. `completed` - Root independent audit reproduced three P1 blockers at the
   Gate 2 HEAD `3206c77`: unsanitized public coverage verdict, W5-DSH-01
   ignoring runtime system guidance, and prompt-only corrections without an
   authorized producer; plus the evidence-doc count inaccuracy.
2. `completed` - Red-first: rewrite P2-9 (no producer must fail closed),
   add P2-9b (genuine producer exhaustion), P2-9c (tampered guidance fails
   closed, content + metadata), the core no-producer test, and 14
   parametrized verdict-sanitization cases (SESSION_COMPLETED +
   SESSION_FAILED); `18 failed / 14 passed` at `3206c77`.
3. `completed` - P1-1: `sanitize_public_coverage_verdict` rebuilds the exact
   five-field safe object from validated counts (status, non-negative ints,
   bools rejected, required = satisfied + missing, status consistent) with a
   fixed message; malformed verdicts fail closed; public projection never
   forwards the source dict.
4. `completed` - P1-2: full envelope equality - rebuilt runtime guidance
   (evidence observations, plan nudges, validator instructions) from durable
   state via the same helpers; system digest covers content + metadata;
   continuation envelope derives from the durable recovered conversation;
   tampered guidance fails closed before the gateway.
5. `completed` - P1-3: `schedule_evidence_correction` gate - no matching
   advertised trusted producer means no correction dispatch
   (`completion_evidence_missing`, no Attempt 2); budget increments only
   with a producer; plan behavior unchanged; adapted the four tests that
   relied on prompt-only corrections.
6. `completed` - Corrected evidence (fresh runs): Phase 2 + Gate 0 `25/25`,
   Gate 1 `30/30`, focused `177/177`, full `2273 passed / 8 failed /
   9 skipped` (same inherited 8), eval `10/10`, ruff 11 / mypy 13 identical
   to base, file-size gate same 10 inherited violations; updated the shared
   Gate 2 fixture and sent the corrected contract note to the FinOS peer;
   ready for root/owner re-acceptance; stop before Phase 3.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 2 re-audit fix (continuation replay)

1. `completed` - Root re-audit rejected the closure: a real guarded
   clarification continuation (max_attempts=2) failed before the resumed
   provider call with attempt_reconstruction_invalid; rebuild() duplicated
   the prior response on top of the recovered continuation conversation.
2. `completed` - Red-first at `eeebae8`: new guarded clarification test
   (WAITING_INPUT -> resume -> exactly one resumed request -> completed),
   upgraded clarification + evidence-correction test (max_attempts=2,
   genuine producer, resumed completion + one typed correction, after-
   correction terminal), upgraded approved-batch continuation test;
   all 3 red before the fix.
3. `completed` - Minimum shared-root fix at the durable reconstruction seam:
   continuation replays only the durable tail after the last snapshot
   boundary; provider-call-id mapping seeded from the full stream;
   continuation envelope includes rebuilt runtime guidance; terminal-
   synthesis final-answer instruction derived from the durable provisional-
   final response; no guard bypass, no second engine.
4. `completed` - Corrected evidence (fresh runs): continuation tests 3/3,
   worker suites 104/104, agent_core/api/storage 468/468, full `2274 passed
   / 8 failed / 9 skipped` (same inherited 8), eval `10/10`, ruff 11 / mypy
   13 identical to base, file-size gate same 10 inherited violations;
   fixture unchanged (internal replay fix only); final SHA sent to the FinOS
   peer; ready for root/owner re-acceptance; stop before Phase 3.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 2 re-audit fix 2 (plan-nudge regression)

1. `completed` - Root re-audit found the continuation fix misclassified the
   required-plan nudge path as terminal synthesis under the real DSH guard
   (plan_required=True, max_attempts=2): the Task failed before the nudge-
   driven request 2 (attempt_reconstruction_invalid, requests=1, 12/12).
2. `completed` - Red-first at `05e68c4`: upgraded the plan-nudge
   clarification test to max_attempts=2 (proposal before Plan, nudge-driven
   request 2 -> agent.clarify, WAITING_INPUT, resumed required-plan result,
   exactly one attempt); red before the fix.
3. `completed` - Minimum shared-root fix at the terminal-synthesis
   reconstruction decision: exact durable discriminator (plain response with
   tool_call_count=0, no following tool events, no durable Plan while
   plan_required); private optional proposed_tool_names on
   MODEL_RESPONSE_RECEIVED for byte-exact nudge rebuilds; continuation
   guidance seeded from the recovered conversation; envelope rebuild derives
   full systems + conversation through the same durable replay; no guard
   bypass, no second engine.
4. `completed` - Corrected evidence (fresh runs): continuation tests 8/8,
   worker suites 104/104, agent_core/api/storage 468/468, full `2274 passed
   / 8 failed / 9 skipped` (same inherited 8), eval `10/10`, ruff 11 / mypy
   13 identical to base, file-size gate same 10 inherited violations;
   fixture unchanged (optional private event field only); final SHA sent to
   the FinOS peer; ready for root/owner re-acceptance; stop before Phase 3.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 2 re-audit fix 3 (guarded terminal synthesis)

1. `completed` - Root re-audit found two normal terminal-synthesis flows
   broken under the real DSH guard (max_attempts=2): guarded validator
   correction (FinOS v3 validator passed=false) and guarded no-progress
   convergence (repeated identical reads) both failed with
   attempt_reconstruction_invalid before the tool-disabled terminal
   dispatch.
2. `completed` - Red-first at `1ce6a8b`: two real Hosted Worker tests
   (FinOS v3 validator contract with a fake transport; repeated stable
   files.read) - both red before the fix (requests=1/4, reconstruction
   mismatch), green after.
3. `completed` - One shared-root durable terminal-synthesis reconstruction
   fix: reachable batch scan (validator signal, state changes, observation
   fingerprints), no-progress counter replayed with the harness's own
   progress rule (`observation_fingerprint` + threshold), and the three real
   triggers (plain provisional final, validator rejection, convergence
   threshold) driving the exact validator/no-progress/final-answer
   instruction rebuild via the same helpers; no guard bypass, no public
   exposure, no new state machine.
4. `completed` - Corrected evidence (fresh runs): guarded validator +
   convergence + continuation/plan tests 15/15, worker suites 106/106,
   agent_core/storage 466/466 (one known transient migration-concurrency
   flake, isolated rerun green), full `2276 passed / 8 failed / 9 skipped`
   (same inherited 8), eval `10/10`, ruff 11 / mypy 13 identical to base,
   file-size gate same 10 inherited violations; live validator/no-progress
   equivalence covered (Phase 4 = full crash/replay matrix only); fixture
   unchanged; final SHA sent to the FinOS peer; ready for root/owner
   re-acceptance; stop before Phase 3.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 2 re-audit fix 4 (evidence-before-terminal precedence)

1. `completed` - Root re-audit found the reconstruction violated the
   runtime's evidence-before-terminal-synthesis order: with missing
   completion evidence and a matching trusted producer it rebuilt the
   validator/no-progress/final-answer guidance alongside the missing-
   evidence observation, so the real evidence-correction dispatch never
   matched (validator + evidence and convergence + evidence combinations
   failed with attempt_reconstruction_invalid).
2. `completed` - Red-first at `26ef883`: two real Hosted Worker precedence
   tests (validator passed=false + authoritative producer; repeated stable
   reads + authoritative producer) - both red before the fix, green after.
3. `completed` - Minimum shared-root fix at the durable next-dispatch
   decision: terminal synthesis pending gated on evidence handling
   (pending = triggers AND NOT evidence_missing); validator trigger is any
   batch (the runtime flag persists until the evidence gate returns None);
   evidence observations rebuilt with the historical per-batch evidence
   state; the no-progress counter reuses the harness's own shared
   update_observation_progress transition (no parallel reducer); durable
   terminal-synthesis reconstruction moved to the focused
   terminal_synthesis.py (no new size violation); no guard bypass.
4. `completed` - Corrected evidence (fresh runs): precedence + guarded
   terminal/continuation/plan tests 17/17, worker suites 108/108,
   agent_core/storage 467/467, full `2278 passed / 8 failed / 9 skipped`
   (same inherited 8), eval `10/10`, ruff 11 / mypy 13 identical to base,
   file-size gate same 10 inherited violations; fixture unchanged; final
   SHA sent to the FinOS peer; ready for root/owner re-acceptance; stop
   before Phase 3.

## ZNX-WAVE5-OUTER-ATTEMPTS-01 - Wave 5 Gate 2 re-audit fix 5 (policy-recovery terminal synthesis)

1. `completed` - Root re-audit found the fourth runtime terminal trigger,
   policy_recovery_terminal_synthesis (set after the second recoverable
   policy DENY), missing from the durable reconstruction - a real guarded
   worker run with two recoverable DENY decisions failed closed before
   request 3 (attempt_reconstruction_invalid, gateway requests=2).
2. `completed` - Red-first at `8656cab`: two real Hosted Worker tests
   (two recoverable DENY decisions then one tool-disabled terminal
   synthesis request; and the evidence-precedence combination where the
   typed evidence correction dispatch comes first) - both red before the
   fix, green after.
3. `completed` - Minimum shared-root fix at the durable reconstruction
   seam: the policy-recovery signal is the POLICY_DECISION_MADE(deny)
   decision paired with the following non-executed TOOL_EXECUTION_FAILED
   (the exact recoverable_policy_deny_observation shape; repeated-tool
   failures are not preceded by a policy deny decision), the terminal state
   includes the two-deny trigger gated on evidence handling, and the
   per-batch evidence loop fires the typed correction for policy-recovery
   terminal entries too; no second retry/model loop/reducer/state machine;
   no external schema/fixture delta.
4. `completed` - Corrected evidence (fresh runs): policy-recovery +
   precedence + guarded terminal/continuation/plan tests 19/19, worker
   suites 110/110, agent_core/storage 467/467, full `2280 passed /
   8 failed / 9 skipped` (same inherited 8), eval `10/10`, ruff 11 / mypy
   13 identical to base, file-size gate same 10 inherited violations;
   fixture unchanged; final SHA sent to the FinOS peer; ready for
   root/owner re-acceptance; stop before Phase 3.

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
