# Cloud runtime fault isolation and scoped recovery

Task CLOUD-RELIABILITY-20261028. Integration target: `cloud-agent`.

## Incident and ownership

Read-only ERP evidence on 2026-10-28 showed three `LockNotAvailable` and one
`ExecutionAuthorityResolutionError` recorded as `model_execution_failed`, plus
one distinct Provider failure. These counts include acceptance activity, not a
production failure-rate denominator. At 10:50:15 UTC the PostgreSQL error named
`route_task_projection_work()` updating `task_projection_work_routes`.

The ERP task independently owns its native105 custom Worker and deployment in
`ni/outputs/zebra-erpnext`. This change touches only shared Cloud source and
isolated acceptance. It does not redeploy ERP, alter its scripts/schema, replay
old Runs, change authority, or invoke model/search providers.

## Minimal repair

1. PostgreSQL projection repair first reads the scoped scalar route. A ready,
   correctly selected, clean route already covering both the Task high-water
   mark and requested route position returns without UPSERT or row locking.
   Missing/dirty/unready routes and ordinary/coverage selection still follow
   existing repair and privacy checks. Concurrent new appends still update the
   native queue; this read does not ACK or advance any checkpoint.
2. After one atomic repair header completes, read its resulting route using the
   reserved parent I/O budget. An expired 100ms work slice must not roll back a
   successfully routed header merely because its final metadata read crosses
   the slice. Partial headers still roll back; no canonical write is replayed.
3. The shared Worker exception boundary distinguishes storage contention,
   storage unavailability, execution authority unavailability, nonretryable
   Provider failure and other execution failure. Infrastructure/authority cases
   suspend with `retryable=false`; unknown errors remain failed. These codes
   describe cause, not proof that an external operation did not execute.
   Existing lease-loss, cancellation, uncertain commit confirmation, provider
   continuation and fresh authorization checks remain authoritative.
4. Existing AG-UI suspension projection maps the new infrastructure reasons to
   suspended state and a Run interrupt. It carries `retryable=false`; it never
   reports success or automatically resumes. Existing Turn-completion guards
   suppress trailing segment suspension after a completed Turn, and a new Turn
   establishes a new boundary. Unknown and historical reason mappings remain.

No new schema, service, dependency, global retry policy or business-specific
runtime branch is introduced. Both business adapters should consume these
shared Worker/projector semantics, not reconstruct terminal state from message
end events or the presence of a previous answer.

## Cross-business deployment contract

Use a fixed, compatible Native API/Worker/SDK source release and migration
ledger. Host adapters supply current identity/authority, typed tools and UI;
they should reuse the native projection consumer and Run-scoped recovery.
An adapter that replaces the Worker loop is a separate runtime requiring its
own exact-image acceptance; importing some shared modules is not equivalence.

In particular, ERP's pinned v105 image is not automatically upgraded by merging
this source. Current mainline migration history must be reconciled explicitly
before a future coordinated upgrade; do not apply newest migrations blindly or
replace the active ERP repair image from this task. Existing BFF contracts,
public message/surface GET recovery and namespace/Run binding remain unchanged.

Observation recovery is GET-only. It may replay persisted presentation frames,
not model calls, tools, original commands or approvals. Keep prior committed
answers and distinguish current suspended execution from older completed Turns.
Do not turn `partial` or unknown commits into completion. A browser must retain
its current authorized Run binding when reconstructing state.

## No-model acceptance

- New real PostgreSQL tests failed on the old healthy-route UPSERT, including
  an actual canonical trigger append at a 50ms lock timeout while a maintenance
  connection deliberately remains open. They pass after the read-only fast path.
- Classification tests failed on the old generic model-failure fallthrough.
  Real Worker execution with an offline injected failure persists one suspended
  result, releases its lease and leaves no ready session for automatic replay.
- 120 completed Turns followed by a storage/auth suspension retain all completed
  outcomes under full and cursor recovery. Reused projection state rejects a
  foreign Run. Trailing suspension cannot reverse an already completed Turn.
- Existing native long-session gate now includes these checks and actual
  projector suspension -> v2 encoder -> real loopback HTTP -> public SDK.
  It restores the exact large-answer digest, tool pairing and interrupt without
  historical client effects, model calls or command POSTs. It rejects skips.
- Two existing repair tests were updated to the existing 100ms bounded page
  contract: eventual bounded repair, not one-call completion or a 2s minimum.

Validation results and exact commands are recorded in WORKLOG.md and
`.artifacts/cloud-reliability-20261028/`. Focused native and recovery gates do not
substitute for production business acceptance or a full-repository test run.

## Availability guarantees and remaining limits

This slice establishes healthy derived maintenance isolation, explicit failure
states and safe presentation recovery. Genuine dirty-route repair and source
writes still share transactional resources; all lock contention is not claimed
eliminated. A real collision now pauses safely rather than claiming a model
failure or blindly rerunning effects. Total database loss can prevent even the
suspension event being stored; unknown outcomes still require reconciliation.

Production HA requires separate deployment evidence: drain admission before
changing active authority/Worker dependencies, validate exact images as their
runtime UID, ensure pinned sandbox resources exist, and exercise replica/DB/
Redis failover against the real topology. This task neither configures database
HA nor proves zero downtime, seamless in-flight model continuation or an SLO.
Original production histories remain untouched.


## Boundary follow-up: CLOUD-RELIABILITY-BOUNDARIES-20261028

Review reproduced a composition regression: classifying a post-answer storage
fault as suspended bypassed the completed-answer guard (which accepted only
failed/completed). It stranded a proven complete answer before Turn close.
The guard now accepts only the two typed storage suspension reasons after a
canonical complete AnswerCommitted for the same Attempt, with no later Turn,
control/wait or terminal boundary. Unknown/partial/blocked answers, authority
failure and uncertain provider/commit outcomes are not upgraded. The fenced
Recorder still checks current lease/cancel state; no model or input rebuild is
needed. Existing already-paused production Runs are not rewritten by this task.

A late client receipt is a durable observation, not permission to clear a newer
pause. Shared pending-effect selection and continuation reconstruction now check
pause, Turn, approval/clarification, new-message and accepted control boundaries
between schedule and receipt. Ordinary own waiting/resumed events still work;
existing consumed/uncertain-start dedup remains. The PostgreSQL maintenance
repair also rechecks pause/Turn boundaries after selecting a waiting candidate.
The receipt itself is retained and its duplicate remains idempotent.

Dirty projection repair no longer locks the route while reading source headers.
The existing atomic routing SQL acquires the route via its first UPSERT and uses
the current contiguous frontier; each completed header commits before subsequent
metadata/source reads. The page retains its 100ms work/byte/item budgets and
reserved commit budget. A timed-out header rolls back; previously committed
headers survive and are resumed later. Native triggers, namespace, privacy
classification, closure bounds and exact ACK/CAS remain unchanged. There is no
schema change and no source-event/model/tool replay.

Real isolated PostgreSQL regression: pause maintenance at first/second source
read; a native event append with unchanged 50ms lock timeout must succeed and
previous progress must already be visible to an independent connection. Old code
fails with LockNotAvailable in route_task_projection_work. Also race two repair
connections on the same header and require one contiguous advance, plus verify
cold completion preserves each anchor's closure. This removes batch-held locks,
not all possible database contention: one atomic header/COMMIT can still stall,
and database outage/failover requires separate operational acceptance.

Acceptance: final native PostgreSQL/Redis235 + real HTTP/public SDK33, zero
skips/failures; make check passed. Broad no-model suite11267 passed/3092 conditional
skips; final SQL changes are separately exercised by the final native gate.
Commands and integration boundaries are recorded in WORKLOG.md.
No runtime service, Search/MCP process, provider setting, high/v2 setting,
production database, original Run or business adapter was changed.

The combined native gate exposed a cleanup-budget handoff defect: a near-expired
header statement_timeout could cancel the next set_config call before it restored
the parent budget. Successful routing now restores the parent SQL timeout inside
the same bounded DO, before returning; the existing native I/O deadline still
caps COMMIT. Commit preparation also belongs to the same header failure boundary;
confirmed cancellation rolls back only that transaction (no page savepoint is
needed), preserving previous commits. Closed/unknown transport outcomes still
propagate without write replay. A real PostgreSQL test inspects the timeout at the
roundtrip boundary and injects a real server cancellation before the second commit, and existing slow-header tests prove the 100ms work limit and
partial-header rollback are retained. Canonical writer lock_timeout stays 50ms.


## Continuation epochs: CLOUD-CONTINUATION-EPOCHS-20261028

The next audit reproduced a second stale-recovery window: approval, clarification
and child wakeup selection used attempt/tool-start markers to establish consumption.
If a receipt arrived but execution had not started before a newer pause or closed
Turn, the old request/receipt remained recoverable. Across 120 historical Turns,
old and current continuation types could conflict or select the old conversation.
The production entry is recover_active_continuations in the shared Worker, not a
Trench/ERP adapter. This is a deterministic risk reproduction, not attribution of
an uninspected production Run to this cause.

The existing continuation_boundaries module now limits all three selectors to the
current control/Turn epoch. Completed/failed/cancelled Turns or Sessions, a new user
message, explicit stop/cancel/suspend, rejected approval and external-effect wait
retire preceding continuation candidates even without an attempt-start marker.
An ordinary own SESSION_RESUMED does not cut the epoch; waiting_children is kept
only for child recovery. Persisted source events and delivered tool results remain
intact. Existing current approval fingerprint, exact child results, uncertain
execution, counters, verification metadata, authority/lease/cancel guards remain.
There is no automatic retry, forced delegation, model or business configuration change.

Offline old-code reproduction: 85 failures/5 passes after correcting the test
constructor; new shared selector passes all 90 cases, including both receipt/control
orderings and a 120-Turn cross-kind matrix. Focused continuation/previous boundary
regressions:159 passed. Native PostgreSQL/Redis plus real HTTP/public SDK gate:
325 and33 passed respectively, zero skips. make check passed. Additional database
recovery acceptance and local integration are recorded in WORKLOG.md.

Initial stability means the known shared failure boundaries have deterministic
regressions and native acceptance: post-answer close, receipt/control isolation,
bounded projection concurrency, large-history recovery, typed interruptions and
Run-scoped SDK reconstruction. It does not mean production upgraded, database HA,
zero Provider failures, unlimited conversation size or zero downtime. The previous
full baseline was11267 passed/3092 conditional skips; this small follow-up uses
focused/native coverage rather than repeating unrelated full-suite checks.
