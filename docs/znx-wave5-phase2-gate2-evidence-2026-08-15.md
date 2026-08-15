# Wave 5 Phase 2 Gate 2 Evidence (Zebra backend lane)
> Gate 2 of Wave 5 - Complex Analysis Outer Attempt & Evidence Coverage v1.
> Date: 2026-08-15. Branch: `codex/znx-hosted-outer-attempts-v1`.
> Starting HEAD: `4797af80119f4f93f34240243ae4e9f1a7f7c6eb` (Gate 1 closure,
> owner-accepted). Accepted production merge-base:
> `6afbafa306ebbdd67956023d0924d66ea1545f99`. Gate 1 runtime correction:
> `b0a07e112c7d4e501061d1f5081d605c6275f055` (in ancestry).
> No push/PR/merge/deploy; no subagent; stop at Gate 2 for owner acceptance.

## 1. Phase 2 scope (as authorized)
- Generic Zebra coverage verifier reuse and one bounded evidence correction
  per Attempt, driven by the frozen `max_corrections_per_attempt` policy.
- Exact retry classification after the bounded correction is exhausted.
- Safe terminal coverage verdict and explicit missing-evidence explanation.
- No FinOS production implementation; no second verifier/retry loop/registry/
  workflow engine; no UI/next/stable/FinOS changes; no automatic
  Core/Journal/Knowledge writes.

## 2. Red-first evidence (starting HEAD `4797af8`)
New/updated Phase 2 tests were run BEFORE any production edit:
- `tests/worker/execution/test_wave5_phase2_coverage_correction.py` (new,
  P2-1..P2-10 matrix) + updated R2 x2 / R6 in
  `tests/worker/execution/test_wave5_gate0_red_contracts.py`
- result at starting HEAD: `10 failed / 15 passed` in those two files.
  The 10 reds prove the real gaps: no harness correction budget
  (`HarnessTask(max_corrections_per_attempt=...)` rejected), no exact
  `completion_evidence_missing_after_correction` code, no frozen-policy
  catalog entry for it, no safe coverage counts in the completion-evidence
  status metadata, no terminal `coverage_verdict`, and no Attempt 2 +
  safe terminal for a hosted coverage-missing task.
- guards that already held at HEAD (registered, not invented):
  authoritative-financial vs confirmed-Investor-Knowledge independence,
  trusted-typed-results-only evaluation, matching-producer correction
  selection with required tool choice.

## 3. Phase 2 implementation (shared-root, no second engine)
- `agent_core/domain/attempt_policy.py`: the exact code
  `completion_evidence_missing_after_correction` joins the default frozen
  retryable codes and the v1 retryable code catalog;
  `completion_evidence_missing` stays absolutely non-retriable.
- `agent_core/harness/models.py`: `HarnessTask.max_corrections_per_attempt`
  (0..1, v1 cap) so the harness never hard-codes "one observation".
- `agent_core/harness/completion_blocking.py`: correction-aware blocked
  reason (`completion_evidence_missing_after_correction` after a correction
  was attempted, `completion_evidence_missing` otherwise; plan gating
  unchanged).
- `agent_core/harness/completion_evidence.py`: the existing evaluator now
  reports safe counts (`required/satisfied/missing_count`, no IDs);
  `complete_without_tools`, `prepare_terminal_synthesis_evidence` and
  `terminal_synthesis_completion_evidence` use the task's frozen correction
  budget and emit the exact after-correction code on exhaustion.
- `agent_core/harness/coverage_verdict.py` (new, split for the file-size
  limit): `CompletionEvidenceStatus` + safe count metadata +
  `safe_coverage_verdict` (status/required_count/satisfied_count/
  missing_count/message only - no requirement IDs, evidence refs, digests
  or diagnostics).
- `agent_core/harness/required_tool_request.py` + `sequential_loop.py`: a
  correction that was dispatched but called the wrong tool is classified
  as after-correction; a correction that could not dispatch (budget closed)
  keeps the legacy code.
- `agent_core/harness/loop.py` + `apps/worker/.../execution_finalization.py`:
  terminal `SESSION_COMPLETED`/`SESSION_FAILED` payloads carry the safe
  `coverage_verdict`; `SESSION_FAILED` carries an explicit `retryable=false`
  (no misleading default in the public projection).
- `apps/worker/.../execution.py`: the frozen
  `max_corrections_per_attempt` policy value is plumbed into the harness
  task (max=0 => no correction; max=1 => exactly one).
- `apps/worker/.../attempt_events.py` + `attempt_recovery.py`: durable
  `ATTEMPT_OUTCOME_RECORDED.result_metadata` now carries the safe coverage
  counts so crash-recovery between outcome and terminal re-commits the same
  verdict (Phase 4 owns the full W5-DSH-03 matrix; only the necessary
  durability seam is extended here).
- `agent_core/application/public_conversation.py`: the public projection
  exposes only the safe verdict (failure + completed items); private
  requirement IDs/evidence refs/digests/diagnostics never enter it.
- root correction (W5-DSH-01 interplay): the in-attempt evidence-correction
  dispatch was failing the Phase 1 reconstruction guard before any model
  call. Root fixes: `mirror_attempt_messages` mirrors only responses that
  were part of a tool exchange (plain candidate responses are emitted but
  never re-sent, so they must not appear in the durable rebuild), and the
  stable system envelope excludes harness-generated runtime observations
  (missing-evidence, convergence, plan-contract, validator-correction) which
  are deterministic guidance derived from durable evidence/plan state. The
  guard still fails closed on conversation/tool-grant/model-config/media/
  stable-prompt drift.

## 4. Test evidence (all freshly run on the final HEAD)
- Phase 2 + Gate 0 red suite (updated R2 x2 + R6): `25 passed`
- Phase 1 + Gate 1 suites (8+22+fixture/reconstruction/recovery/edges):
  `30 passed` (unchanged behavior)
- focused worker/evidence/loop/stopping/public/final-identity/terminal
  suites: `140 passed` (corrected HEAD: `177 passed`)
- full pytest: `2254 passed / 8 failed / 9 skipped` (pre-correction HEAD
  `3206c77`; corrected final HEAD after the root-audit corrections:
  `2273 passed / 8 failed / 9 skipped`)
  - Gate 1 baseline was `2237 / 11 / 9`: +17 passed (the three Phase 2
    reds closed + the new Phase 2/fixture tests), and the three Phase 2
    reds are no longer in the failure set
  - inherited exact-base failures unchanged (8): 2 agent_integrations,
    5 clock-sensitive session_pull_request (credential fixtures expire
    2026-07-23), 1 repository file-size gate (10 pre-existing violations)
  - zero new production regressions
- release eval: `10/10` (PASS)
- ruff: 11 errors, identical to base (zero new)
- mypy packages+apps: 13 errors, identical to base (zero new; line numbers
  shifted only in `completion_evidence.py`)
- file-size gate: same 10 inherited violations; all Phase 2 files under
  limits (`completion_evidence.py` 494, `coverage_verdict.py` 77, largest
  new test file 629/700)
- `git diff --check` clean; worktree clean

## 4a. Gate 2 correction (root independent audit, 2026-08-15)

The root audit found three P1 blockers plus an evidence-count accuracy issue;
all were corrected on the same lane/worktree (starting HEAD `3206c77`):

- P1-1 public coverage verdict sanitization: `public_conversation.py` now
  rebuilds the verdict through `sanitize_public_coverage_verdict` - an exact
  five-field object from validated counts (status in
  complete/partial/missing, non-negative ints, bools rejected,
  required == satisfied + missing, status consistent with counts) and a
  fixed safe message; the source dict/message is never trusted or forwarded,
  malformed verdicts fail closed (omitted). Red-first: 14 parametrized
  sanitize cases (SESSION_COMPLETED + SESSION_FAILED x 7 poison shapes)
  failed at `3206c77` (raw dict forwarded verbatim) and pass after the fix.
- P1-2 full request-envelope equality: the blanket runtime-guidance
  exclusion was removed from the W5-DSH-01 envelope. The exact runtime
  guidance actually sent to the provider (missing-evidence observations,
  required-plan nudges, validator-correction instructions) is now
  independently rebuilt from durable evidence/plan state via the same
  helpers (`runtime_guidance.py`) and included in the expected digest;
  `system_prompt_digest` covers content AND metadata; continuation
  dispatches derive the expected envelope from the durable recovered
  conversation. Red-first: tampered guidance (content and metadata) passed
  the guard at `3206c77`; both tamper cases now fail closed with zero
  gateway calls (`attempt_reconstruction_invalid`), while the legitimate
  typed correction still dispatches (P2-9b, 4 model calls).
- P1-3 typed-tool-only correction: `schedule_evidence_correction` (shared
  by `complete_without_tools` and `prepare_terminal_synthesis_evidence`)
  never dispatches a prompt-only correction - with required typed evidence
  and no matching currently-advertised trusted producer the attempt fails
  closed after one initial model call with `completion_evidence_missing`
  (no Attempt 2); the correction budget increments and
  `tool_choice=required` applies only when a matching producer exists.
  Open-plan corrections stay separate. Red-first: the rewritten P2-9
  (no producer) and the new core no-producer test failed at `3206c77`
  (prompt-only correction dispatched); they pass after the fix. The
  exhaustion/Attempt-2 worker scenario (P2-9b) now uses a genuine trusted
  advertised producer (FinOS journal grant + provider) and one typed
  correction per Attempt yields `completion_evidence_missing_after_correction`
  and Attempt 2.
- corrected evidence (fresh runs on the corrected tree): Phase 2 + Gate 0
  `25/25`; Gate 1 `30/30`; focused `177/177`; full `2273 passed / 8 failed /
  9 skipped` (only the same 8 exact-base inherited failures: 2
  agent_integrations, 5 clock-sensitive session_pull_request, 1 file-size
  gate); eval `10/10`; ruff 11 / mypy 13 identical to base; file-size gate
  same 10 inherited violations; `git diff --check` clean
- adapted tests to the typed-tool-only contract: `test_agent_definition_-
  completion_contract` (producer + policy-aware scripted gateway; validator-
  only and budget-closed corrections now use the legacy code),
  `test_clarification_continuation` (clarify on the initial dispatch;
  bounded correction after the continuation with a genuine producer)
- shared Gate 2 fixture updated
  (`coverage_classification.correction_requires_matching_advertised_producer`,
  `no_producer_behavior`, `public_boundary.coverage_verdict_sanitized`,
  `malformed_verdict_policy`) and schema-validated; corrected contract note
  sent to the FinOS peer before the docs commit

## 4b. Gate 2 re-audit rejection (continuation replay, 2026-08-15)

The root re-audit rejected the closure with one new P1 blocker: a real
guarded clarification continuation (max_attempts=2, W5-DSH-01 enabled)
always failed before the resumed provider call with
`attempt_reconstruction_invalid` / "actual conversation content differs from
the durable reconstruction". Root cause: `rebuild()` started from the
recovered continuation conversation (which already materializes every event
up to the snapshot boundary) and then mirrored ALL same-attempt durable
events again, duplicating the prior `MODEL_RESPONSE_RECEIVED` (actual
`system, system, system, user, assistant, tool` vs rebuilt
`..., assistant`). Existing tests missed it because the clarification seed
left `max_attempts` at its default 1 (guard off).

Red-first (starting HEAD `eeebae8`):
- new `test_guarded_clarification_resumes_same_attempt_without_reconstruction_
  mismatch`: normal clarification lifecycle with max_attempts=2 - first run
  WAITING_INPUT, user response resumes the same Attempt, exactly one resumed
  provider request, Task completes, no reconstruction mismatch, no extra
  Attempt -> RED at `eeebae8` (0 resumed requests, attempt_reconstruction_invalid)
- upgraded `test_completion_evidence_correction_remains_bounded_across_
  clarification` to max_attempts=2 with a genuine advertised trusted
  producer: resumed completion + one typed correction dispatch; the
  retryable after-correction code schedules Attempt 2 (its own completion +
  one typed correction) before the terminal -> RED at `eeebae8` (0 resumed
  requests)
- upgraded `test_approved_batch_continues_tail_without_replaying_completed_
  call` to max_attempts=2 (same shared seam, smallest relevant approved path)
  -> RED at `eeebae8`

Minimum shared-root correction at the durable reconstruction seam:
- `rebuild()` for a continuation mirrors only the durable tail AFTER the last
  snapshot boundary (`CLARIFICATION_REQUESTED` / `APPROVAL_REQUESTED`), so
  the prior response is replayed exactly once; the recovered continuation
  conversation stays the base (no mutable actual-message-as-expected shortcut)
- `mirror_attempt_messages` seeds the provider-call-id mapping from the full
  durable stream (`provider_events`) so continuation tail results keep the
  harness's provider-or-internal id rule even when the proposals precede the
  snapshot boundary
- the continuation envelope also includes the rebuilt runtime guidance
  (`runtime_guidance()`) so a resumed typed correction observation is covered
- the terminal-synthesis dispatch (provisional final) conversation now
  includes the fixed final-answer instruction, derived from the durable
  provisional-final response (`response_stage == "tool_loop"` with no
  following tool events) - this was a latent guarded-path gap the approved
  continuation test exposed
- no guard bypass: full system/runtime-guidance equality, tool/media/model/
  invocation-policy equality and the tamper-before-gateway guarantee are
  preserved; the P1-1/P1-3 corrections are untouched

Corrected evidence (fresh runs on the corrected tree): the two new/upgraded
clarification tests + approved continuation `3/3` (red before, green after);
worker suites `104 passed`; agent_core/api/storage `468 passed`; full
`2274 passed / 8 failed / 9 skipped` (only the same 8 exact-base inherited
failures); eval `10/10`; ruff 11 / mypy 13 identical to base; file-size gate
same 10 inherited violations; `git diff --check` clean

## 4c. Gate 2 re-audit rejection (required-plan nudge regression, 2026-08-15)

The root re-audit rejected the closure with one deterministic P1 regression
introduced by the continuation fix: under the real Wave 5 DSH guard
(plan_required=True, max_attempts=2), a first response that proposes a
substantive tool before creating a Plan must be rejected with the existing
required-plan nudge and a second model request - but on `05e68c4` the Task
failed before request 2 (`attempt_reconstruction_invalid`, gateway
requests=1, reproduced 12/12). Root cause:
`_terminal_synthesis_pending` (added in `380a989` for guarded approved-batch
terminal synthesis) saw `response_stage="tool_loop"` with no later tool
events and misclassified the plan-nudge path as a provisional final,
appending a false "tool budget is complete" user instruction to the rebuilt
conversation. The existing plan-nudge clarification test seeded
`max_attempts=1` (guard off), so the gap was missed.

Red-first (starting HEAD `05e68c4`):
- upgraded `test_required_plan_nudge_remains_bounded_across_clarification`
  to max_attempts=2 with strengthened assertions: request 1 proposes
  files.read before the Plan, request 2 dispatches after the nudge and asks
  agent.clarify, the first execute reaches WAITING_INPUT (not
  attempt_reconstruction_invalid), the resumed provider request follows the
  existing expected required-plan result (required_plan_not_created, one
  resumed request), exactly one attempt, no files.read execution
  -> RED at `05e68c4` (failed before request 2)

Minimum shared-root fix at the terminal-synthesis reconstruction decision:
- `terminal_synthesis_pending` now requires an exact durable discriminator:
  the last response must be PLAIN (`tool_call_count == 0` in the response
  payload itself), staged `tool_loop`, with no tool events following, AND the
  plan-nudge path is excluded while `plan_required` has no durable Plan (the
  harness schedules the nudge, not terminal synthesis). The approved-batch
  provisional-final reconstruction still works (plain response, no plan
  requirement).
- the nudge content needs the proposed tool names, which are blocked before
  any TOOL_CALL_PROPOSED event; the existing durable MODEL_RESPONSE_RECEIVED
  now carries a private optional `proposed_tool_names` field (schema-
  validated, historical events stay replayable) and the runtime-guidance
  rebuild reads it, so the rebuilt nudge is byte-exact.
- `_completion_for_names` uses a non-blank placeholder assistant content
  (only the tool-call names are consumed by the nudge builder).
- continuation runtime-guidance rebuild seeds plan-nudged/observation state
  from the recovered conversation (the same markers the harness checks), so
  pre-boundary guidance is never rebuilt twice.
- the envelope rebuild now derives the full expected request (systems +
  conversation) through the same durable replay and compaction transform;
  the system digest uses exactly the rebuilt system messages.
- no guard bypass: full system/runtime-guidance equality (content AND
  metadata), tool/media/model/invocation-policy equality and the
  tamper-before-gateway guarantee are preserved; P1-1/P1-3 corrections
  untouched; shared fixture unchanged (internal event field is optional and
  private).

Corrected evidence (fresh runs on the corrected tree): guarded plan-nudge
clarification + all continuation tests `8/8`; worker suites `104 passed`;
agent_core/api/storage `468 passed`; full `2274 passed / 8 failed /
9 skipped` (only the same 8 exact-base inherited failures); eval `10/10`;
ruff 11 / mypy 13 identical to base; file-size gate same 10 inherited
violations; `git diff --check` clean

## 4d. Gate 2 re-audit rejection 3 (guarded terminal-synthesis flows, 2026-08-15)

The root re-audit rejected the closure again: two NORMAL existing
terminal-synthesis flows that the Gate 2 corrections explicitly required
preserving were broken whenever W5-DSH-01 is enabled (max_attempts=2):

- P1-A guarded validator correction: a Hosted Worker with the FinOS v3
  validator contract - model request 1 calls
  finos.trade_log_quality.validate, the provider returns a valid
  passed=false validator result, and the model has a second "Corrected
  final." response. Expected: one bounded tool-disabled validator-correction
  dispatch, 2 provider requests, COMPLETED on the same Attempt. Actual at
  `1ce6a8b`: FAILED attempt_reconstruction_invalid, requests=1. The rebuilt
  envelope missed the validator_correction SYSTEM message, the
  tool_loop_no_progress SYSTEM observation and the fixed final-answer USER
  instruction; runtime_guidance's validator detection was unreachable (the
  scan stop set contained TOOL_EXECUTION_COMPLETED/FAILED/STARTED), and
  terminal_synthesis_pending required tool_call_count==0 so it could not
  recognize validator-triggered terminal synthesis.
- P1-B guarded no-progress convergence: repeated identical files.read
  proposals for the same stable file reach the existing no-progress
  threshold, then one tool-disabled terminal-synthesis request. Expected:
  4 tool-loop requests + 1 terminal request, COMPLETED with 5 provider
  requests on the same Attempt. Actual at `1ce6a8b`: FAILED before provider
  request 5 (attempt_reconstruction_invalid, requests=4). The rebuilt
  envelope missed the tool_loop_no_progress observation (whose
  consecutive_no_progress_batches count is not durable) and the final-answer
  instruction.

Red-first (starting HEAD `1ce6a8b`): two real Hosted Worker tests
(`test_guarded_validator_correction_dispatches_terminal_synthesis` with the
FinOS v3 validator contract and a fake local transport returning passed=false;
`test_guarded_no_progress_convergence_dispatches_terminal_synthesis` with a
real stable file) - both RED at `1ce6a8b` (FAILED with the reconstruction
mismatch, requests=1/4) and green after the fix.

Minimum shared-root fix at the durable terminal-synthesis reconstruction
decision (one fix, no per-test bypasses):
- `_scan_attempt_batches` replaces the unreachable lookahead: each durable
  model response's tool batch is scanned with TOOL_CALL_PROPOSED,
  TOOL_EXECUTION_COMPLETED/FAILED (validator-rejection signal via the same
  `_validator_failed_event` helper) and PLAN_UPDATED/APPROVAL_REQUESTED
  (state-changed) processed - execution completion/failure is now actually
  inspectable.
- the no-progress counter is replayed with the harness's OWN progress rule
  (`observation_fingerprint` + the same reset/increment semantics and
  `DEFAULT_REPEAT_HARD_STOP_THRESHOLD`), so no new durable marker was
  needed: the fingerprints are derived from the durable execution events.
- `_terminal_synthesis_state` recognizes the three real triggers - plain
  provisional final (unchanged exact discriminator), validator rejection
  (last batch), and no-progress convergence (replayed count >= threshold) -
  and `terminal_synthesis_pending` uses it for the final-answer instruction.
- the rebuilt runtime guidance appends the exact instruction messages via
  the same helpers the harness uses: validator_correction (once) and the
  tool_loop_no_progress observation (with the replayed count) exactly when
  the terminal-synthesis dispatch is not the plain-provisional variant;
  continuation seeding covers validator/no-progress markers already present
  in the recovered conversation.
- no guard bypass: full system/runtime-guidance equality (content AND
  metadata), conversation, tool/media/model/invocation-policy axes and the
  tamper-before-gateway guarantee are preserved; no public exposure; no new
  state machine; proposed_tool_names stays private and validated.

Corrected evidence (fresh runs on the corrected tree): guarded validator +
convergence + all continuation/plan tests `15/15`; worker suites
`106 passed`; agent_core/storage `466 passed` (one known transient
migration-concurrency flake, isolated rerun green); full `2276 passed /
8 failed / 9 skipped` (only the same 8 exact-base inherited failures);
eval `10/10`; ruff 11 / mypy 13 identical to base; file-size gate same 10
inherited violations; `git diff --check` clean.

Gate 2 now covers live pre-dispatch equivalence for validator correction and
no-progress convergence under the guard; Phase 4 remains ONLY the full
W5-DSH-03 crash/replay matrix.

## 5. Contract deltas for the FinOS peer (Gate 2)
- exact retry classification: `completion_evidence_missing_after_correction`
  is the only coverage code that may schedule Attempt 2 under the frozen
  policy; `completion_evidence_missing` (no correction performed) remains
  terminal and non-retriable
- frozen `max_corrections_per_attempt`: 0 = no correction, 1 = exactly one
  bounded correction per Attempt (existing required-tool selection with
  `tool_choice=required` and the advertised typed argument schema; no
  FinOS-specific tool name or manifest argument invented)
- terminal `coverage_verdict` is safe-only:
  `{status, required_count, satisfied_count, missing_count, message}`;
  `SESSION_FAILED` additionally carries explicit `retryable`
- `ATTEMPT_OUTCOME_RECORDED.result_metadata` carries the safe coverage
  counts (no IDs) so Attempt 2 and crash recovery can rebuild the verdict
- public projection exposes only the safe verdict; requirement IDs, evidence
  refs, digests, diagnostics and result metadata stay private
- public projection sanitizes the verdict: exact five-field safe object
  rebuilt from validated counts; malformed verdicts fail closed (omitted);
  source dict/message never forwarded
- corrections are typed-tool-only: no matching advertised trusted producer
  means no correction dispatch (`completion_evidence_missing`, no Attempt 2)
- frozen fixture:
  `tests/fixtures/wave5_gate2_contract_delta_v1.json`, schema-validated by
  `tests/worker/execution/test_wave5_gate2_peer_contract.py`

## 6. Security / public-boundary findings
- no prompt/reasoning/raw provider output/grant/policy leak into the public
  projection; the coverage verdict is counts + a fixed safe message
- no FinOS business type, finance-specific routing, model-specific branch or
  prompt keyword classifier was introduced; coverage stays generic
  requirement IDs/typed labels
- `completion_evidence_missing` cannot be frozen as retryable (absolute
  non-retriable set unchanged) - a drifted frozen list still cannot retry it
- the explicit Phase 1 "manifest absent" digest is preserved; Phase 3 binds
  the real FinOS immutable resource manifest

## 7. Remaining gaps (Gate 2 -> Phase 3/4)
- Phase 3: FinOS profile preflight, immutable resource manifest binding,
  read-only grant and Credit quote/reserve/settle (FinOS lane +
  coordination commit)
- Phase 4: full W5-DSH-03 crash/replay equivalence matrix; only the
  outcome-durability seam needed by Phase 2 was extended here. Live
  pre-dispatch equivalence for continuation, plan-nudge, approved
  terminal synthesis, validator correction and no-progress convergence is
  covered by Gate 2; the full crash/replay matrix remains Phase 4.
- real DeepSeek acceptance (Phase 5) and final SHA closure (Phase 6) remain
  future gates; no push/PR/merge/deploy from this lane
