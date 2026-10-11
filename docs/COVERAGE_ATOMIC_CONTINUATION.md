# Atomic continuation: execution receipt and independent recovery

Status: design selected by Luke Ding, 2026-10-10; implementation IN PROGRESS.
Owner/task: Luke Ding / Codex, COV-EXEC-01, codex/cov-exec-01 worktree.
This document is not deployment approval or an SLO acceptance report.

## Decision and boundaries

Normal cooperative yield must not be classified as a process failure. Replace
its repeated full reconstruction with a versioned, atomic native handoff rooted
in validated processing facts. Keep complete recovery for missing/legacy or
uncertain executions; final certification remains an independent physical proof.

Only final_certification admission is eligible. This explicitly permits discovering
unrelated old object damage during final certification, never publishing an
incomplete formal answer. Eager mode keeps its existing guarantee and path.
Neither a projection count, an arbitrary configured callback nor a self-reported
digest is sufficient authority to skip recovery.

## Implemented storage slice

Migration84 adds coverage_execution_receipts, independent of coverage_runs,
coverage_units and coverage_batches. Each row refers to its exact native accepted
Event, carries a scoped predecessor FK and digest, and rejects ordinary UPDATE,
DELETE and TRUNCATE. Schema-administrator DDL remains outside this guarantee;
this is not a cryptographic defense against a compromised database administrator.

Migration85 retains referenced native accepted Events without adding Event fields
or rewriting witness JSON. Before receipt insertion, an exact scoped native
acceptance receives a no-op row-version write in the same transaction. This
serializes concurrent writers, including stale repeatable-read transactions;
receipt-linked sources then reject UPDATE and DELETE, and TRUNCATE refuses while
receipts exist. The write and receipt roll back together. Existing receipt sources
receive the same row-version barrier during migration, before guards install.
Sealing is retention only: it never repairs, backfills or qualifies old proofs.
Schema-admin trigger bypass remains outside this guarantee. Upgrade verification
must retain valid old MODEL witnesses while still refusing tampered sources.

An initially attempted Event seal column was rejected in review: it would change
to_jsonb(Event), invalidating independent pre-migration MODEL witnesses even with
minting off. The final migration deliberately keeps that representation unchanged.

The commit transaction runs existing result derivation, exact membership and
uniqueness, budget, current native Task/binding/STOP/fence and retention/deadline
checks first. After appending the accepted Event and projections, it atomically
stores a receipt and repeats current write/deadline gates before committing.
Failure rolls back the receipt, accepted Event and projections together.
Retries return the original accepted receipt without minting or adding counts.

Receipt body pins deployment, full frozen run binding, exact accepted Event,
predecessor, expected-unit identity/count, accepted count, verified MODEL state,
original deadline, current command/accepted Event/generation/execution floor and
producing lease. Successors retain the original policy and cannot extend a
predecessor's earlier validity deadline. Counts increment only by current unique results;
the first row requires no earlier native accepted batch. An existing native
prefix without a receipt is never backfilled from projections.

One native SHA256 fingerprint binds complete MODEL Events, independent witness
rows, call/reservation/usage rows and ledger, not just ledger counters. Input is
scoped to deployment/session/namespace/run; SQL guards combined source volume
before aggregating the fingerprint. Capacity overflow skips minting and retains
full recovery; it is not a new business acceptance limit. Integrity and SQL
errors still fail the transaction.

Only native active command handoffs can mint; legacy/non-command executions and
eager admission do not. The store's trusted composition must explicitly opt in;
the default is off and current Worker composition does not enable it. Thus this
scaffold adds no receipt/fingerprint SQL to the unchanged production path.
Generic configured derivers can produce storage witnesses
under the existing acceptance contract, but these are NOT qualified fast-path
roots: no normal-handoff consumer uses them yet. No frontend behavior changes.

## Native reader and preparation intent (2026-10-11)

`coverage_execution_receipt_read.py` reads latest actual native acceptance and
its receipt/predecessor, not the latest projection or caller-supplied digest.
Three successful native reads cover source/chain, scoped MODEL fingerprint and
fresh clock. Combined source/receipt/predecessor JSON is bounded before transfer.
The native predecessor Event is compared exactly; migration85 name/checksum,
binding, original command/fence/generation/floor, chain delta, expected identity,
settled budget and non-extending original deadlines must agree. Fresh deadline
validation follows the potentially expensive native fingerprint scan.

Missing legacy witness returns no facts; malformed, changed or expired witness
refuses. Database errors propagate. No historical object bodies are fetched.
The fingerprint remains bounded O(history) SQL: this is not yet an incremental
MODEL root or an end-to-end performance acceptance. The restricted SELECT-only
preparation adapter supports this reader and revalidates its exact native reads.

The shared preparation entry now accepts explicit normal-continuation intent.
Only a composed `prepare_continuation` method uses that lane; absent support
retains legacy preparation. A selected method's invalid proof refuses without
silently downgrading. Normal approval passes this intent; the actual normal
preparer, persisted protocol approval and pickup selection
are now implemented in the source-only follow-up below. Current Worker stays off.
Reader facts alone do not confer Host,
command, lease or publication authorization. Debugger tracing kept the changes
at shared preparation and native facts boundaries, not per-caller SQL patches.

## Required normal continuation transaction — NOT fully implemented yet

1. Qualify the exact native semantic verifier and receipt protocol in Worker
   capability admission. An old consumer cannot pick up marked new-protocol work.
2. After an actual cooperative yield, take existing lease/Task/run/stream locks.
   Validate current admission, STOP, rollover, fence, original command receipt,
   active generation/floor, latest native accepted Event and execution receipt.
3. Use migration85's immutable referenced native accepted-prefix boundary.
   The source constraints are implemented; qualifying the actual semantic
   verifier and validating receipt chains in normal handoff remain mandatory.
   Sealed legacy rows alone do not qualify a prefix. Do not use count checks.
4. Verify current budget source/witness state (including hidden reservations and
   unresolved usage), current external Host authority, expiry and conservative
   post-checkpoint Event classification. Unknown or changed marked proof refuses;
   it must not silently downgrade into an accepted fast path.
5. In the same transaction persist versioned continuation approval, next-generation
   pending command and outbox with exact proof/receipt/floor/approved stream.
   Preserve idempotency, no-progress denial and generation/crash/age budgets.

## Native normal preparation and pickup (source only, 2026-10-11)

NativeCoverageRecoveryCheck.prepare_continuation shares current Task/Host/STOP,
fenced Event-tail and original deadline gates with full recovery. An eligible
receipt skips historical object reconstruction and full model transcript replay.
Approval persists the exact execution receipt/Event and protocol marker in the
existing atomic next-generation/outbox transaction. Pickup reads native approval
before selecting preparation, then checks exact proof equality under existing
locks; an unsupported consumer refuses marked work rather than downgrading.

The commit verifier also pins whether exact manifest parts still lack settled
native MODEL receipts. The normal branch retains full-C call/token admission:
missing predicates or insufficient budget fall back to exact remaining-part
replay. Checks-only work need not reserve another model call. Receipt successors
cannot change verifier identity. The native Artifact facade now qualifies the
exact actual derivation function, not a caller's string, wrapper or subclass.
Successful commit verification carries that qualification into minting; a
non-null opt-in marker mismatch skips receipt queries/minting entirely. Generic
unmarked witnesses retain legacy behavior and cannot be upgraded mid-prefix.

The separate continuation configuration digest reuses actual co-located Worker
qualification and additionally requires the exact native preparer/method and
actual dispatch deriver. Its consumer/producer protocol pins are domain-separated
from v3. It is not yet wired into fleet registration or admission/pickup matching;
deployed v3 requirements deliberately remain unchanged. These are trusted
composition checks, not protection against arbitrary privileged Python code
replacing the qualification hook. Default-off/fleet rollout remains mandatory.
Production minting therefore remains OFF. Native routing tests do not establish
fleet compatibility, restart/deployment acceptance or performance SLOs.

## Native fleet qualification (2026-10-11, source only)

Migration86 appends nullable continuation_digest to the existing process capability
table, after its v82/v83 prerequisites. Exact native Worker/preparer/deriver
composition publishes a protocol-qualified configuration digest at registration
and heartbeat. Heartbeat and natural-expiry replacement cannot change that
qualification. It is a trusted process-composition claim, not protection against
arbitrary privileged Python or schema-administrator writes.

The v3 main contract remains unchanged. Unmarked tasks accept either qualified
or legacy v3 processes. Marked normal pickup reads the exact native approval for
the current pending generation in the existing requirement query and requires
the extension on the actual attested consumer process; another qualified process
cannot lend its authority. Unknown protocol/reason refuses without acquiring a
new Session lease. STOP/control commands retain their existing independent path.

Compatibility means legacy tasks under upgraded code, NOT old compiled binaries:
schema verification requires the exact migration catalog. Upgrade the fleet and
schema together in a controlled cohort; do not mix schema85 binaries with86.
Production minting remains OFF. Coordinated rollover/race/load acceptance remains
OPEN; these source changes do not constitute deployment or performance acceptance.

## Pickup transaction invariants

Select protocol before today's unconditional prepare_command_recovery call.
For eligible normal work, prepare only bounded current authority/receipt state;
never load all historical objects or invoke full checkpoint reconstruction.

Under native locks validate persisted approval equality, exact prior producing
fence and receipt, unchanged source fingerprint/authority and approved stream.
Then acquire the next lease through the existing atomic acquisition path. The
new lease must NOT be compared for equality to the producing lease. Preserve
duplicate-delivery handling, inbox links, final clock checks and approval/pickup
race detection. Legacy and genuine faults retain full native recovery.

After crash recovery, any root used for a new fast prefix must come from an
independent verified reconstruction, not a repair of progress projections.

## Certification and performance

Final certification remains unchanged: full exact manifest membership, result
derivation, private checkpoint/original object bytes, current Host authority,
native budget, physical pre/post validation and fail-closed publication.
Receipt identity is processing evidence, not semantic accuracy or object availability.

The scaffold fingerprint is O(history) native SQL, not an incremental immutable
source root. Qualified test composition now skips recovery object reads at
approval/pickup; production remains unchanged. Shared native Event history and
exact prepared-read revalidation still require bounded scans.
Do not claim the existing nine-record workload, SQL<=1000, control p95<=5s or
normal full-recovery count=0 has improved. A retained incremental source root is
the upgrade path if the native fingerprint remains costly after routing changes.
Before activation, pin receipt retention and per-tenant storage budgets: this
prototype retains one full descriptor per accepted commit and has no purge executor.
Do not expose the opt-in as a tool-supplied flag or treat it as verifier qualification.

Release evidence must include exact duplicate/crash/STOP/revoke/rollover, old
consumer and approval-to-pickup races, hidden usage and native source mutation,
final historical object damage refusal, and unchanged ordinary local behavior.
Measure normal prepare/full-recovery calls separately from actual faults. Repeat
the frozen 9/64-record load, report business/reset/clock/timeout SQL and GETs,
and run mixed-tenant fairness/connection tests. No production restart here.

## Evidence

Duplicate pickup root repair: predecessor proof was checked before same-generation
receipt idempotency, wrongly returning reconciliation after successful retry.
Shared locked handoff now returns no lease for the native duplicate first. Pickup
preparation joins its existing approval query to native receipt generation, skipping
proof reconstruction only for an already-picked generation. Approval creation and
exceptional recovery remain full checks. STOP/approval mutation and post-native-write
crash tests assert rollback/no drift; retry completion requires real final full
verification with physical reads and exactly one certificate. Source review GO;
native suite37 pass/1 test-only import error128.85s; corrected final crash/cert
case passed12.44s, zero skips. Sibling multipart/crash/approval tamper/no-progress/
crash-budget10 passed155.32s, zero skips. No activation or latency claim.

Qualification concurrency acceptance: actual PG blocking-pid observations assert
revoke/epoch mutation waits on native qualified pin locks; afterward the old
consumer refuses. Expiry after successful pin and tentative write rolls back.
Actual normal preparation then revoke/epoch injection must run exactly once,
return protocol1 proof and refuse pickup without changes to native lease/pending/
receipt/Inbox/outbox/Event snapshots or extra historical object reads. Source
review GO. Final hardened17 plus specific84-to85 upgrade2 passed111.63s, zero
skips. This is not the full crash/STOP/source-race matrix or
schema86 fleet rollover/load acceptance. Source upgrade fixture explicitly pins
catalog<=84 before,<=85 after; unrelated cases use current catalog.

Native fleet qualification: corrected full92 passed108.63s, zero skips, actual
scratch PostgreSQL/Worker with synthetic Host/model/S3 transports. Tests include
unqualified process refusal despite another qualified process, unchanged v3
tasks, heartbeat upgrade/downgrade refusal, repeated normal pickup without new
historical object reads, current Host revocation and final certification. Scoped
source review GO; make check sizes2382/Ruff/Mypy1092/eval30 passed. Earlier91/1
stale catalog-tail assertion report is superseded. No full default-suite rerun,
production migration/restart/minting activation or workload latency acceptance.

Source-retention migration85: revised source/test review GO; native source plus
receipt19 passed146.53s, zero skips. Rollback, scoped mismatch, stale RR/concurrent
mutation, valid old MODEL witness upgrade and exact tampered witness refusal
verified. Supplemental explicit84-to85 upgrade2 passed26.18s.
Ruff/Mypy1089/size/eval30 pass; default6915 passed/1598 infrastructure
prerequisite skips125.90s. These are source-retention tests, not fast-path latency
or production acceptance. No Worker activation or receipt protocol qualification.

Source review: scoped GO for storage scaffold; not fast-path or release approval.
Native scratch Worker/PG final9 tests passed95.19s (no skips), including
actual default-off composition, atomic rollback, retry chain, immutable mutation,
legacy and capacity fallback, protocol NULL refusal, exact native-source rollback,
original policy equality and predecessor validity inheritance.
Prior acceptance regression plus receipt selection45 passed659.38s; this earlier
report predates final protocol/default hardening. Further gates are in WORKLOG.md.
Default regression6915 passed/1588 prerequisite skips117.34s before last
receipt-only policy/validity guards; those guards have the final9-case native
regression and make check. No load or p95 evidence has been generated for a fast path.
Host, model and object transports are controlled fixtures, not live services.
Qualified fixture normal continuation avoids full recovery; production minting
remains OFF and end-to-end production/load acceptance is OPEN.
