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
| R4 start coordinates at start seam | GREEN | schema + materialization |
| R5 dispatch fail-closed + coordinates | GREEN | reconstruction guard |
| R5 supporting schema | GREEN | payload contract |
| R7 failed candidate not public final | GREEN | final selection |
| R8 usage links to attempt identity | GREEN | dispatch enrichment |
| R2 evidence-correction retryable (x2) | RED (Phase 2) | bounded coverage correction + retry classification land in Phase 2 |
| R6 terminal coverage verdict | RED (Phase 2) | coverage verifier is Phase 2 |
| R3 resume-after-terminal | RED (superseded) | retry now runs in-execution; crash recovery is pinned by P1-4/P1-8; a recovery-equivalence test replaces this premise in Phase 4 |
| R4 outcome separate from Task terminal | RED (premise superseded) | the accepted Gate 1 contract is in-run retry exhaustion; the outcome-record assertions are pinned by P1-1/P1-4 and the event contract |

## 5. Test evidence (all freshly run)
- Phase 1 red suite: `8 passed` after implementation (red-before: `7 failed`)
- Gate 0 red suite: `6 passed, 5 failed` (classification above)
- focused baseline (harness loop/stopping, worker core execution,
  completion-evidence trust, public-conversation multiturn, final identity,
  terminal lease): `37 passed`
- full pytest: `2212 passed, 13 failed, 9 skipped`
  (accepted base `6afbafa`: `2199 passed, 8 failed, 9 skipped`)
  - +13 passed: 8 Phase 1 + 6 Gate 0 red -> green (R1/R4-start/R5/R5-schema/
    R7/R8) minus 1 net (bootstrap/CLI/API payload asserts moved)
  - +5 failed: exactly the classified Gate 0 reds above (R2 x2, R3, R4, R6);
    zero production regressions
  - inherited exact-base failures unchanged: 2 agent_integrations,
    5 session_pull_request (credential fixtures expire 2026-07-23, clock
    sensitive), 1 repository file-size gate (10 pre-existing violations)
- `make check` components vs base:
  - eval release gate: `10/10` (PASS)
  - ruff full: 11 errors, identical to base (zero new)
  - mypy packages apps: 13 errors, identical to base (zero new;
    line numbers shifted only)
  - file-size gate: 10 violations, same list as base; all Phase 1 files
    under limits (`attempt_coordinator.py` 427, `attempt_execution.py` ~165,
    `attempt_events.py` ~180, `execution.py` ~450)
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
- evidence reuse: Attempt 2's context reads the full durable stream, so
  accepted typed evidence from Attempt 1 is inherited; failed attempt prose
  never becomes canonical (public final selection)
- security: dispatch events carry only private coordinates/digest fields
  (stable_task_id, attempt_id, turn/step, goal/plan revision) and never
  prompt/arguments/output/grant content; public projection unchanged except
  the stricter final selection; `SESSION_FAILED` public item keeps its
  existing default until Phase 2 supplies explicit retryable verdicts
- full content-digest reconstruction equality (messages/system/tool/model
  digests vs a durable reconstruction projection) is deliberately deferred:
  Phase 1 records the coordinates at dispatch and fails closed on
  coordinate/causal reconstruction; the reconstruction projection lands with
  Phase 2's coverage work

## 7. Contract deltas for the FinOS peer (no conflict expected)
- `TASK_PREPARED` adds `max_corrections_per_attempt`, `execution_profile_id`,
  `retryable_stop_reasons` (frozen at creation; v1 caps 2 attempts / 1
  correction)
- new durable event `attempt_outcome_recorded` (attempt_id, attempt_sequence,
  outcome, ended_at, terminal_reason, retry_scheduled, next_attempt_sequence)
- `harness_attempt_started` payload schema registered with stable coordinates
- `model_request_started`/`model_response_received` carry private attempt
  coordinates; attempt identity is deterministic per Stable Task
  (`attempt-{sequence}`)
- canonical public final is now bound to the accepted attempt only; failed
  attempt candidates are attempt-private
- FinOS R3's Task usage = sum(attempt usage) aggregation now has durable
  per-attempt inputs on the Zebra side (attempt_id linkage)

## 8. Remaining gaps (Gate 1 -> Phase 2)
- bounded evidence correction and its retryable classification
  (`completion_evidence_missing_after_correction`) - R2 stays red
- resource/evidence coverage verifier and terminal coverage verdict - R6
  stays red
- exhausted missing-evidence explanation
- full W5-DSH-01 content-digest equality projection
- W5-DSH-03 replay-equivalence matrix as deterministic tests (Phase 4);
  R3's resume-after-terminal premise is superseded by in-run coordination
