# Wave 5 Existing-State Audit and Gate 0 Red Matrix (Zebra)
> Gate 0 deliverable of Wave 5 - Complex Analysis Outer Attempt & Evidence
> Coverage v1. Docs-first; no production code changed in this commit.
> Date: 2026-08-14. Branch: `codex/znx-hosted-outer-attempts-v1`.
> Exact base: `1d19abbb57c4df5c9e8636db9c004638d7220ee8`
> (Zebra Wave 4.5 Gate A acceptance record). Remote-ref verified:
> `fork/codex/znx-wave45-task-ui-foundation-v1` = `1d19abb`.
> Peer: FinOS Gate 0 task `019ffe56-8b1e-74e2-9289-9ee8a3544aff`, exact base
> `305223e7bf7bbc9ffc646ea488e89c7da8585c49`. No PR, merge, push, deploy.

## 1. Scope
Prove the current Hosted Worker execution chain's real gaps for generic
outer attempts, evidence coverage, recovery and usage settlement, and register
the Wave 5 task card plus the DSH-inspired backend contracts. Red/contract
tests ship in the next commit and are expected to FAIL at this exact base.
Nothing here changes production behavior.

## 2. Frozen baseline facts
- Zebra exact base `1d19abb` is the Wave 4.5 Gate A acceptance record; remote
  ref `fork/codex/znx-wave45-task-ui-foundation-v1` points at it exactly.
- Required Wave 5 branch: `codex/znx-hosted-outer-attempts-v1`.
- Compatible FinOS exact base: `305223e`.
- Frozen shared package: `@zebra-agent/task-ui@0.1.0` SHA-256
  `33b01e6910c7852fd1c0a4a7f77f9acc0f39a0b2d90d7b76d1de7e49826f5741`.
- Wave 4.5 Gate A remains PASS and is not reopened. Wave 4.5 Phase 4 owns
  `UI/packages/task-ui/**`, `UI/desktop/**` and its tests; this lane must not
  touch them.

## 3. Chain audit (exact base, file:line evidence)

### 3.1 Hosted Worker execution - GAP: single attempt only
- `apps/worker/src/zebra_agent_worker/execution.py:399` builds
  `HarnessAttempt(number=1, started_at=started_at)` - attempt identity is an
  in-memory integer, never read from durable state.
- `execution.py:449-451` persists `HARNESS_ATTEMPT_STARTED` with hard-coded
  `{"attempt_number": 1}` and only when no continuation is pending.
- `execution.py:262` and `execution.py:493` hard-code `attempt_number=1` into
  runtime setup and `HarnessModelStep`.
- `attempt_lifecycle.py:execute_attempt` runs the orchestrator exactly once;
  there is no outer attempt coordinator in the Hosted Worker path.
- `packages/agent-core/src/agent_core/harness/loop.py:112` has a
  `for attempt_number in range(1, task.max_attempts + 1)` loop primitive, but
  the Hosted Worker never uses `HarnessLoop`; both agent-runtime callers pass
  `max_attempts=1` (`packages/agent-runtime/src/agent_runtime/harness.py:182`,
  `research.py:64`). The primitive is effectively dead for hosted execution.

### 3.2 Evidence correction and retry classification - GAP: no Attempt 2
- Bounded in-attempt correction exists: `completion_blocking.py` appends one
  missing-evidence observation and requests a next completion; after one
  observation the attempt fails with `completion_evidence_missing`
  (`packages/agent-core/src/agent_core/harness/completion_evidence.py:150-166`,
  `completion_blocking.py:167-174`).
- `packages/agent-core/src/agent_core/harness/stopping.py:72-74` excludes
  `completion_evidence_missing` from retry, so even the loop primitive never
  starts Attempt 2 after a failed evidence correction. Wave 5 requires
  `completion_evidence_missing_after_correction` to be a retryable code under
  the frozen profile (max_attempts=2, max_corrections_per_attempt=1).
- `apps/worker/src/zebra_agent_worker/execution_errors.py:16-59` classifies
  provider errors: retryable provider failures suspend (recoverable), generic
  exceptions fail with `stop_reason=model_execution_failed`. No durable
  retry-scheduled record exists for any classification.

### 3.3 Recovery / continuation - GAP: no durable outer-attempt coordinates
- `recover_task` (`apps/worker/src/zebra_agent_worker/task_recovery.py:112`)
  reads `max_attempts` from `TASK_PREPARED` but no attempt state; recovery
  always rebuilds `HarnessAttempt(number=1)`.
- `apps/worker/src/zebra_agent_worker/resume.py:26-29` refuses any terminal
  session (`SessionResumeError("cannot resume terminal session")`), so a
  retryable-failed attempt cannot be resumed as Attempt 2 at all.
- `packages/agent-core/src/agent_core/harness/models.py:198-203`
  `HarnessAttempt` carries only `number` + `started_at`; no stable
  `attempt_id`, `attempt_sequence`, `terminal_reason` or causal reference.
- `packages/agent-core/src/agent_core/contracts/events.py:366-404` registers
  no payload schema for `HARNESS_ATTEMPT_STARTED`; the event payload is
  unvalidated free-form (only `attempt_number` is written).
- PASS: Segment identity is durable and internal - `execution_segments`
  (`packages/agent-storage/src/agent_storage/agent_tasks.py:21-35`) with
  `segment_index`, `predecessor_id`, `visibility=internal`, `rollover_reason`;
  `SegmentVisibility.INTERNAL` only (`domain/agent_tasks.py:14-17`). Segment
  rollover cannot be mistaken for an Attempt because no Attempt record exists.

### 3.4 Task terminal and coverage verdict - GAP: no coverage verdict
- `apps/worker/src/zebra_agent_worker/execution_finalization.py:63` writes
  `SESSION_COMPLETED` payload `{"attempt_number": 1, "summary", "metadata"}`;
  `execution_finalization.py:91` writes `SESSION_FAILED` the same way. No
  coverage verdict, missing-requirement list or verifier identity.
- `packages/agent-core/src/agent_core/domain/agent_tasks.py:25-38` `AgentTask`
  has no attempt or coverage fields; task projection
  (`apps/api/src/zebra_agent_api/task_api.py:80-120`) exposes goal/plan/final
  identity only.
- PASS: an in-attempt evidence evaluator exists and is durable-only:
  `completion_evidence.py` accepts typed evidence / tool tags / validator
  outcomes / capability results from trusted `TOOL_EXECUTION_COMPLETED` and
  `TESTS_COMPLETED` events, and fingerprints them. It is not a resource
  manifest verifier (no manifest exists yet), and it never reaches the task
  terminal payload.

### 3.5 Canonical final identity / public conversation - GAP: failed candidate can become canonical final
- `packages/agent-core/src/agent_core/application/public_conversation.py:235-236`
  selects every `MODEL_RESPONSE_RECEIVED` with `response_stage == "final"`
  as a public final regardless of the segment's terminal outcome, so a failed
  attempt's candidate final is projected as `final_response`.
- `apps/api/src/zebra_agent_api/task_final_identity.py:20-31` returns the last
  `final_response` identity without checking task terminal state, so artifact
  binding can point at a failed attempt's candidate.
- The `SESSION_FAILED` branch in `public_conversation.py` adds a `failure`
  item but does not suppress the candidate final. Wave 5 requires
  attempt-private candidates never enter the public conversation or bind a
  business operation.

### 3.6 Usage and settlement - GAP: attempt usage not aggregatable
- Per-call usage is durable: `ModelResponseReceivedPayload` records
  `input_tokens/output_tokens/total_tokens` and `MODEL_REQUEST_STARTED`
  carries `model_call_id`/`attempt_number`
  (`packages/agent-core/src/agent_core/contracts/model_events.py:6-33`).
- `packages/agent-core/src/agent_core/harness/loop.py:48-50` accumulates
  `model_calls_used`/`tool_calls_used` in memory only, and only in the
  unused loop path. The Hosted Worker persists no per-attempt usage and no
  Task-level settlement aggregate; `AgentTask` has no usage field.
- `packages/agent-core/src/agent_core/harness/models.py:25-41` has no
  usage/settlement contract; FinOS Credit reserve/settle remains external
  (FinOS lane) and needs a deterministic per-attempt usage sum to settle once.

### 3.7 Goal / Plan continuity - PASS (bounded)
- Goal is stable: `HarnessTask.stable_goal` (`harness/models.py:193-195`)
  falls back to `user_input`; `AgentTask.goal` is derived from the root
  `TASK_PREPARED` (`agent_tasks.py:358+`), and the worker rehydrates it
  (`execution.py:367-370`).
- Plan is durable per Task: `PLAN_UPDATED` events are projected into
  `SessionPlan` (`agent_tasks.py:399-412`), and continuation restores the
  plan (`execution.py` `task_record.task_plan`).
- GAP for W5-DSH-01/02: `SessionPlan` (`domain/plans.py:34-70`) has
  `updated_at` but no `revision` counter, so a request-reconstruction check
  cannot reference a stable `plan_revision`.

### 3.8 Lease release and terminal publication - PASS (partial)
- `append_completed_and_release_lease`
  (`packages/agent-storage/src/agent_storage/sqlite.py:34-60`) atomically
  inserts `SESSION_COMPLETED`, updates session/workspace projections and
  deletes the worker lease in one transaction. This must be preserved as the
  terminal transaction for Attempt 2 and recovery.
- `SESSION_FAILED`/`SESSION_SUSPENDED` release the lease via
  `release_claim` after finalization (non-atomic), which is the existing
  contract and is not changed by Gate 0.

### 3.9 Profile binding - GAP
- No generic execution profile exists in Zebra: `AgentTask`, `TASK_PREPARED`
  and the worker carry `policy_profile`/`tool_profile`/`network_profile` but
  no versioned `execution_profile` (e.g. `finos-complex-analysis-v1`,
  `max_attempts_cap`, `max_corrections_per_attempt_cap`). FinOS preflight
  therefore has nothing to negotiate against. Task creation already freezes
  `max_attempts` into `TASK_PREPARED`
  (`application/session_bootstrap.py:38,147`; `task_recovery.py:112`) - the
  freeze seam exists; the profile contract does not.

## 4. DSH backend contracts (must land in task card and red matrix)

### W5-DSH-01 - Private Request Reconstruction Invariant
Before every model dispatch the actual request must equal the durable
reconstruction; mismatch fails closed. Required coordinates:
`stable_task_id`, `attempt_id`, `turn_id`, `step_id`, `goal_revision`,
`plan_revision`, `resource_manifest_digest`, `messages_digest`,
`system_prompt_digest`, `tool_schema_digest`, `model_config_digest`.
Full prompt/schema/grant/private resource never enters the public projection.
Current state: `MODEL_REQUEST_STARTED` schema
(`contracts/model_events.py:6-33`) has none of these fields and is
`extra="forbid"`.

### W5-DSH-02 - Durable Execution Coordinates
`Stable Task -> Attempt -> Turn -> Step`; Segment is an internal context
carrier, not an Attempt or visible Turn. Stable identity/sequence/time/
terminal reason/causal reference; crash/resume must not duplicate, skip or
cross evidence/final. Do not port a second DSH Turn/Step system; reuse the
event/session/segment seams. Current state: no payload schema for
`HARNESS_ATTEMPT_STARTED`, `HarnessAttempt` is in-memory, `SessionPlan` has
no revision.

### W5-DSH-03 - Replay/Recovery Equivalence
Deterministic crash tests are registered at these points: after
`attempt_started`; after model call; after tool result; after coverage
report; after retry scheduled; before/after Attempt 2 creation; before/after
canonical final; before/after Task terminal; before/after Credit settlement.
Continuous execution, durable replay and recovery must yield identical
attempt identities/count, coverage/evidence, canonical final, terminal,
Goal/Plan revisions, usage and settlement. Current state: retryable-failed
sessions cannot even be resumed (`resume.py:26-29`), so none of these
equivalences is testable yet.

## 5. Red-test matrix (committed in tests/worker/execution/
test_wave5_gate0_red_contracts.py; revised 2026-08-14 per root audit;
all FAIL at exact base)
| # | Red test | Real gap it proves | Base behavior |
|---|---|---|---|
| R1 | Hosted worker starts Attempt 2 after retryable attempt-1 failure (max_attempts=2 seeded) | 3.1 single attempt | 1 `HARNESS_ATTEMPT_STARTED`, terminal `attempt_number=1` |
| R2 | Evidence-correction failure is retryable when attempts remain; loop starts Attempt 2 | 3.2 no Attempt 2 | `should_retry=False`, 1 attempt |
| R3 | Retryable-failed session resumes as Attempt 2 | 3.3 recovery blocked | `SessionResumeError` |
| R4 | Attempt coordinates at the existing lifecycle seams: start (`HARNESS_ATTEMPT_STARTED`: `attempt_id/attempt_sequence/started_at/causal_attempt_id`) and terminal (`SESSION_COMPLETED`/`SESSION_FAILED`: `attempt_id/ended_at/terminal_reason`) | 3.3 no durable coordinates (W5-DSH-02) | no schema registered (`KeyError`); owner contract does not prescribe every field on the start event |
| R5 | Behavioral fail-closed at the real dispatch seam: durable attempt coordinate (2) differs from worker reconstruction (1) and the model gateway must not be called; `MODEL_REQUEST_STARTED` schema accepting W5-DSH-01 digests/coordinates is a supporting assertion | 3.3/3.9 no reconstruction invariant (W5-DSH-01) | gateway is invoked despite the mismatch; schema fields absent, `extra="forbid"` |
| R6 | Task terminal carries coverage verdict | 3.4 no coverage verdict | terminal payload has none |
| R7 | Failed attempt candidate final is not public canonical final; `final_message_identity` is None | 3.5 wrong canonical final | candidate projected + identity returned |
| R8 | Behavioral: every usage-bearing event links to a stable attempt identity and one Stable Task's usage equals the sum of its attempt usages, computed at the existing task-event seam (no storage shape prescribed) | 3.6 no settlement aggregation | usage events carry no `attempt_id` (`KeyError`) |

W5-DSH-03 crash-point fixtures are registered in the task card and will be
implemented as deterministic replay/equivalence tests when attempts and
coverage exist (Phase Z4); R1/R3 already prove the recovery preconditions
are missing.

Revision 2026-08-14 (root Gate 0 audit): R4 split into start/terminal seams
per the owner lifecycle contract (no over-specification of the start event);
R5 gained the behavioral dispatch fail-closed red through the real worker
seam with schema coverage demoted to supporting; R8 is behavioral (usage
linkable to stable attempt identity, Task usage = sum of attempt usages) and
leaves storage shape free.

## 6. Security findings (Gate 0, exact base)
- No prompt/reasoning/raw provider output/grant/policy leaks into the public
  projection today (public conversation selects bounded `assistant_message`
  text only; `ModelResponseReceivedPayload` is `extra="forbid"`).
- New exposure risk in Wave 5: adding digests and coordinates to request
  events is safe only if they stay in the private domain; public projection
  must not add coverage internals beyond the safe summary (status/counts).
- `SESSION_FAILED` public item defaults `retryable=True`
  (`public_conversation.py:158-161`), which becomes misleading once
  non-retryable classifications exist; Wave 5 must carry an explicit
  retryable verdict from the durable classifier, not a default.

## 7. Explicit non-goals (Wave 5, unchanged)
Planner, Scheduler, DAG, second registry/engine, FinOS-specific workflow, UI
Node Engine, Cordis, compaction, chunk packing, persistence batching, any
DSH runtime dependency, PR/merge/deploy/push, modifying
`UI/packages/task-ui/**` or `UI/desktop/**`, FinOS source, next/stable.

## 8. Gate 0 exit criteria
- [x] Gate A refs remotely readable and exact (fork `1d19abb`; FinOS `305223e`)
- [x] Wave 5 merge-base exact (`1d19abb`), branch
      `codex/znx-hosted-outer-attempts-v1` created, worktree clean
- [x] docs-first task card + this audit (commit 1, docs-only)
- [ ] deterministic red tests land and FAIL at exact base (commit 2)
- [ ] focused baseline checks run; inherited exact-base failures separated
- [ ] final worktree clean; report exact branch/HEAD/merge-base/paths/tests
