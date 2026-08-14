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
  suites: `140 passed`
- full pytest: `2254 passed / 8 failed / 9 skipped`
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
  outcome-durability seam needed by Phase 2 was extended here
- real DeepSeek acceptance (Phase 5) and final SHA closure (Phase 6) remain
  future gates; no push/PR/merge/deploy from this lane
