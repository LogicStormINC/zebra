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
