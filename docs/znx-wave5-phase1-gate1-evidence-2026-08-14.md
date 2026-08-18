# Wave 5 Phase 1 Gate 1 Evidence (Zebra backend lane)
> Gate 1 of Wave 5 - Complex Analysis Outer Attempt & Evidence Coverage v1.
> Date: 2026-08-14. Branch: `codex/znx-hosted-outer-attempts-v1`.
> Rebased base: `6afbafa306ebbdd67956023d0924d66ea1545f99` (accepted Zebra
> production SHA; NOT the closure docs SHA `687ac7d`). Gate 0 commits
> `1d19abb..ff129ce` rebased onto it; range-diff shows commits 2-5 identical
> and commit 1 differing only by the WORKLOG conflict resolution that
> preserves both Wave 4.5 production and Wave 5 Gate 0 records.
> No push/PR/merge/deploy; no subagent; stop at Gate 1, no Phase 2.

## 1. Synchronization evidence
- backup ref `refs/backup/wave5/zebra-gate0-ff129ce` = `ff129ce` (pre-rebase
  Gate 0 HEAD, recoverable)
- ancestry verified: `1d19abb` -> `6afbafa` -> `687ac7d`; remote
  `fork/codex/znx-wave45-task-ui-foundation-v1` = `687ac7d` (untouched)
- Gate 0 re-verified on the synchronized base BEFORE production:
  `11 failed` (red suite as designed), `37 passed` (focused baseline)

## 2. Phase 1 red-first
- `tests/worker/execution/test_wave5_phase1_outer_attempts.py` (8 tests)
  added first and demonstrated `7 failed` on the synchronized base before any
  production edit (P1-8 was added with the implementation and passes with it)
- red semantics proven: no Attempt 2 in-run (P1-1), no durable
  start/outcome coordinates (P1-1/P1-6), no crash-after-outcome recovery
  (P1-4), no reconstruction fail-closed (P1-5), no usage linkage (P1-6),
  no policy caps (P1-7)

## 3. Phase 1 implementation (production)
Changed paths (production):
- `packages/agent-core/src/agent_core/domain/attempt_policy.py` (new):
  generic `TaskAttemptPolicy` frozen at Task creation - `max_attempts`
  (1..2 v1 cap), `max_corrections_per_attempt` (0..1 v1 cap),
  `execution_profile_id`, `retryable_stop_reasons` (default
  `("model_execution_failed",)`). Continuation/client cannot expand it;
  recovery rebuilds it from the frozen `TASK_PREPARED` payload and fails
  closed on drift or over-cap.
- `packages/agent-core/src/agent_core/domain/events.py`: new durable event
  `ATTEMPT_OUTCOME_RECORDED`.
- `packages/agent-core/src/agent_core/contracts/model_events.py`:
  `HARNESS_ATTEMPT_STARTED` payload schema (attempt_id, attempt_sequence,
  started_at, causal_attempt_id, legacy markers); `ATTEMPT_OUTCOME_RECORDED`
  payload schema (attempt_id, attempt_sequence, outcome, ended_at,
  terminal_reason, retry_scheduled, next_attempt_sequence);
  `MODEL_REQUEST_STARTED` gains the W5-DSH-01 private coordinates
  (stable_task_id, attempt_id, turn_id, step_id, goal_revision,
  plan_revision, resource_manifest_digest, messages_digest,
  system_prompt_digest, tool_schema_digest, model_config_digest);
  `MODEL_RESPONSE_RECEIVED` gains attempt_id + stable_task_id. All new
  fields are optional so pre-Phase-1 events stay replayable.
- `packages/agent-core/src/agent_core/contracts/task_prepared.py` +
  `application/session_bootstrap.py`: `max_corrections_per_attempt`,
  `execution_profile_id`, `retryable_stop_reasons` frozen into
  `TASK_PREPARED`; caps validated at the creation boundary.
- `packages/agent-core/src/agent_core/harness/models.py`:
  `HarnessAttempt` gains deterministic `attempt_id` (`attempt-{number}`,
  stable per Stable Task) and `causal_attempt_id`.
- `packages/agent-core/src/agent_core/application/public_conversation.py`:
  canonical final selection restricted - finals from failed/cancelled
  segments stay attempt-private, and on completed segments only the accepted
  attempt's final is canonical (legacy events without attempt coordinates
  keep their previous behavior).
- `apps/worker/src/zebra_agent_worker/attempt_events.py` (new): durable
  reconstruction, start materialization (no duplicate starts; legacy starts
  upgraded with stable identity), outcome recording, retry decision.
- `apps/worker/src/zebra_agent_worker/attempt_execution.py` (new):
  single-attempt execution with dispatch-event enrichment (private
  coordinates on MODEL_REQUEST_STARTED / MODEL_RESPONSE_RECEIVED).
- `apps/worker/src/zebra_agent_worker/attempt_coordinator.py` (new):
  outer attempt loop under one Stable Task - reconstruct current attempt
  from the durable stream, validate the causal chain, materialize start,
  run, record outcome, retry only frozen retryable codes, terminalize once
  after accepted/exhausted/non-retriable results, fail closed
  (`attempt_reconstruction_invalid`) before any dispatch when the
  reconstruction is inconsistent. Paused states (waiting approval/input,
  suspended) never get an outcome record, so continuation/suspension
  recovery resumes the same attempt.
- `apps/worker/src/zebra_agent_worker/execution.py`: Hosted Worker now
  drives the coordinator; dropped 130+ lines of inlined single-attempt
  machinery (563 -> ~450 lines).
- `apps/worker/src/zebra_agent_worker/execution_finalization.py`:
  terminal payloads carry the real accepted/exhausted attempt number.
- `apps/worker/src/zebra_agent_worker/task_recovery.py`: policy rebuilt from
  the frozen payload with fail-closed cap validation.

Root correction after the initial `fa10e53` Gate 1 evidence commit:
- task-wide frozen policy/budgets now survive Segment handoff and cannot be
  erased or expanded by a child `TASK_PREPARED` fact;
- active execution epochs and Turn identity derive from durable Task events,
  not the internal Segment/session id;
- every guarded provider request compares actual messages, system prompts,
  tool schemas, exact media identity, model configuration and invocation
  policy against an independently reconstructed durable envelope; provider
  tool-call id/name/arguments and tool-result linkage are preserved;
- `resource_manifest_digest` is always populated: Phase 1 records an explicit
  immutable "manifest absent" digest until the FinOS-owned manifest contract
  is bound in a later gate;
- paused states keep the same Attempt; cumulative model/tool budgets and
  correlated in-flight Step recovery remain fail closed across rollover;
- cohesive modules stay below the repository limits (`attempt_coordinator.py`
  468 lines; largest changed source file 495; largest new test file 673).

Adapted existing tests (no behavior change, contract surfaces moved):
`tests/agent_core/test_session_bootstrap.py`,
`tests/api/test_api_app.py`, `tests/cli/test_cli_session_stream.py`
(TASK_PREPARED payload now includes the frozen policy fields),
`tests/api/http_app/test_http_session_creation.py` (attempt outcome event
advances the session sequence by one),
`tests/worker/execution/test_core_execution.py` (policy-engine seam moved
from execution to attempt_execution).

## 4. Gate 0 red classification after Phase 1
| Test | After Phase 1 | Reason |
|---|---|---|
| R1 hosted worker starts Attempt 2 | GREEN | in-run coordination |
| R3 recovery resumes the durable attempt chain | GREEN | epoch-scoped recovery + correlated Step guard |
| R4 start/outcome separate from Task terminal | GREEN | start/outcome schemas + idempotent terminal recovery |
| R5 dispatch fail-closed + coordinates | GREEN | full request-envelope reconstruction guard |
| R5 supporting schema | GREEN | payload contract + frozen fixture |
| R7 failed candidate not public final | GREEN | accepted-attempt-only final selection |
| R8 usage links to attempt identity | GREEN | dispatch/outcome enrichment |
| R2 evidence-correction retryable (x2) | RED (Phase 2) | bounded coverage correction + retry classification land in Phase 2 |
| R6 terminal coverage verdict | RED (Phase 2) | coverage verifier is Phase 2 |

## 5. Test evidence (all freshly run)
- Phase 1 + Gate 1 correction/contract suites: `30 passed` (8 original
  Phase 1 + 22 correction/recovery/reconstruction/fixture checks). The
  original suite was red-first (`7 failed`); the correction window recorded
  14 failures at `fa10e53`, and root takeover additionally reproduced the
  missing invocation-policy API plus a `None` manifest digest before fixing.
- Gate 0 red suite: `8 passed, 3 failed` (only R2 x2 + R6 remain; Phase 2)
- focused baseline (harness loop/stopping, worker core execution,
  completion-evidence trust, public-conversation multiturn, final identity,
  terminal lease and evidence continuity): `38 passed`
- full pytest: `2237 passed, 11 failed, 9 skipped`
  (accepted base `6afbafa`: `2199 passed, 8 failed, 9 skipped`)
  - +38 passed: 8 original Phase 1 + 8 Gate 0 green + 22 correction/contract
    checks
  - +3 failed: exactly the classified Phase 2 reds (R2 x2, R6); zero
    production regressions
  - inherited exact-base failures unchanged: 2 agent_integrations,
    5 session_pull_request (credential fixtures expire 2026-07-23, clock
    sensitive), 1 repository file-size gate (10 pre-existing violations)
- `make check` components vs base:
  - eval release gate: `10/10` (PASS)
  - ruff full: 11 errors, identical to base (zero new)
  - mypy packages apps: 13 errors, identical to base (zero new;
    line numbers shifted only)
  - file-size gate: 10 violations, same inherited list as base; all Wave 5
    files under their hard limits
- `git diff --check` clean; worktree clean

## 6. Crash / recovery / idempotency / security findings
- crash after retriable outcome, before Attempt 2 (P1-4): resume starts
  Attempt 2 exactly once - no attempt-1 replay, no duplicate start, no
  sequence gap
- crash after non-retriable/exhausted outcome, before Task terminal (P1-8):
  re-execution re-commits the terminal exactly once with no dispatch
- crash mid-attempt with a continuation/suspension: the same attempt resumes
  (outcome records are only written for completed/failed attempts)
- cancel mid-attempt: external terminal state stops coordination without an
  outcome record (recorder interruption contract preserved)
- one active attempt: the coordinator is single-threaded under one lease;
  Segment stays an internal context carrier and is never an Attempt
- in-run evidence wiring includes recorder events in the next Attempt context,
  while failed attempt prose never becomes canonical. Functional coverage
  acceptance/reuse remains a Phase 2 claim and is not asserted by Gate 1.
- security: dispatch events carry only private coordinates/digest fields
  (stable_task_id, attempt_id, turn/step, goal/plan revision) and never
  prompt/arguments/output/grant content; public projection unchanged except
  the stricter final selection; `SESSION_FAILED` public item keeps its
  existing default until Phase 2 supplies explicit retryable verdicts
- request reconstruction is content-level for messages/system/tool/media,
  model configuration and invocation policy; only digests/coordinates are
  durable and none of the private request content reaches public projection

## 7. Contract deltas for the FinOS peer (no conflict expected)
- `TASK_PREPARED` adds `max_corrections_per_attempt`, `execution_profile_id`,
  `retryable_stop_reasons` (frozen at creation; v1 caps 2 attempts / 1
  correction)
- new durable event `attempt_outcome_recorded` (attempt_id, attempt_sequence,
  outcome, ended_at, terminal_reason, retry_scheduled, next_attempt_sequence)
- `harness_attempt_started` payload schema registered with stable coordinates
- `model_request_started`/`model_response_received` carry private attempt
  coordinates and reconstruction digests, including
  `invocation_policy_digest`; attempt identity is deterministic per Stable
  Task (`attempt-{sequence}`)
- canonical public final is now bound to the accepted attempt only; failed
  attempt candidates are attempt-private
- FinOS R3's Task usage = sum(attempt usage) aggregation now has durable
  per-attempt inputs on the Zebra side (attempt_id linkage)
- frozen fixture:
  `tests/fixtures/wave5_gate1_contract_delta_v1.json`, schema-validated by
  `test_wave5_gate1_peer_contract.py`; digest fields remain private

## 8. Remaining gaps (Gate 1 -> Phase 2)
- bounded evidence correction and its retryable classification
  (`completion_evidence_missing_after_correction`) - R2 stays red
- resource/evidence coverage verifier and terminal coverage verdict - R6
  stays red
- exhausted missing-evidence explanation
- binding the FinOS-owned immutable resource manifest in place of the explicit
  Phase 1 "manifest absent" digest
- W5-DSH-03 replay-equivalence matrix as deterministic tests (Phase 4); Gate
  1 closes R3's concrete resume premise but does not claim the full matrix
