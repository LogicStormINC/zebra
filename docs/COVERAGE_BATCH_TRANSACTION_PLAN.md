# Coverage batch transaction implementation

Owner: Luke Ding / Codex. Task COV-EXEC-01, branch codex/cov-exec-01.
Accepted user plan, 2026-10-11. Baseline is certified nine-record native Worker:
20403 Connection.execute calls, 287 object reads, seven wakes, 30.5219 seconds.
Controlled transports and fixture consumer lifecycle; not a production SLO.

## Required boundaries

1. Instrument client calls and server work without excluding failed attempts,
   setup inside execution, connection reset, or final certification.
2. Prepare a bounded batch under current authority; share metadata/bytes only
   inside the trusted operation. Pure CPU steps do not query authority repeatedly.
   Revalidate exact lifecycle records and current authority before committing.
3. Seal exact work membership; normal commits inspect only delta keys. Counters
   are derived atomically from Event-backed facts, never sufficient alone to
   certify completeness. Legacy and unsupported mutations retain refusal/replay.
4. Batch acceptance and governed metadata changes; do not remove model call
   reservation/settlement or crash reconciliation.
5. Certification reads external objects outside lifecycle/run locks only when
   immutable retention and final version checks preserve the existing guarantee.
   Stream exact original verification; no count-only or digest-only certificate.
6. Persist checkpoints independently of relinquishing execution. Bound fair work
   by tenant namespace, bytes, time, calls and database capacity across Workers.
7. Validate cancellation, revocation, owner replacement, duplicate delivery,
   interrupted model/upload/commit, tenant isolation and history growth.

## Acceptance

- Nine-record application database calls <=1000, complete old measurement scope.
- Normal batch query count independent of historic manifest/events; bounded pages
  and indexed exact membership, no all-key parameter upload.
- No external I/O while final publish transaction holds native lifecycle locks.
- Measure nested SQL with pg_stat_statements when available; inability to enable
  it is a separate unmet server-observation gate, not inferred from client counts.
- Multi-tenant native load reports p50/p95, locks/connection waits and rows/bytes;
  controlled model timings are distinct from real provider or Trench latency.
- Static checks, file limits and meaningful native regression checks pass.

## Delivery tracking

### Shared consumer read-phase continuation

The common CoverageArtifacts loader now uses the existing optional readonly
scope, so MODEL checkpoint/policy reads, snapshot reads and publication readback
all share the same entry/exit lifecycle preparation. A reader's result cannot
escape until exit revalidates exact metadata, absence and fresh authority.
Only native unowned execution phases coalesce. Already-owned/custom proof reads
retain the original guarded path and its locks; no unlocked-I/O claim there.
Bulk metadata explicitly matches the configured deployment before callbacks/SQL.
Injected clocks retain post-callback authority; only the exact native clock may
use one check at an admitted incremental boundary without other I/O/callbacks.
No permission TTL, skipped reset or independent final proof weakening. This is
shared consumer composition, not completion of the whole <=1000 SQL gate.

Component-verified: bounded exact acceptance batches; owner-transaction borrowing;
known-pure operation authority and pinned lifecycle reads; verified-load Port reuse;
native MODEL volume/91 and scoped lookup indexes/92; compatible fleet identity;
sealed exact ordered membership and record metadata/93; selected bounded record
reads and unique Event-backed part settlement; all-client/nested-server meters,
exclusive phase attribution and strict SQL budget assertion; optional immutable
Artifact batch publication, set-based reservation/receipt settlement, upload and
physical version verification outside transactions, atomic whole-batch finalization
and exact post-callback revalidation. MODEL checkpoint/usage still publish immediately;
buffering observations never defers charge settlement. Legacy/recovery/
final proof remains independent; incremental original corruption detection is
deferred to final certification by explicit user decision.

Prior sealed nine18.2650s/12,916 calls/server19,132/four callbacks remains the
comparison baseline. Batch publication19.5519s/11,582 calls/server17,212/four
callbacks saves1,334 application calls (~10.3%) but does not improve elapsed time.
Post-callback validation run23.0696s/13,031 calls/server19,188 has five callbacks;
do not compare it as a fixed-four-callback regression or gain. Strict <=1000
SQL gate still FAIL; all runs are retained in the evidence document.
Current race-safe source serial repeat19.6260s/11,772client/17,472server/225GET,
four callbacks and five qualified batches. Saves1,144calls vs the prior12,916,
but accepted batch count differs and latency is not improved; no p95/SLO claim.
The full plan is not complete. Remaining: full execution/history scale, scoped
bulk evidence reads/authority and batched per-object canonical Event/finalization,
final external proof outside locks with immutable retention evidence,
fleet-wide quotas/backpressure/fairness and live multi-tenant/Trench acceptance.

Exact commands, regression results and evidence boundaries:
`COVERAGE_BATCH_TRANSACTION_EVIDENCE.md`. Running services, migrations, release
activation and branch integration are separate from isolated source validation.
Existing dirty work is preserved; runtime receipts remain OFF.

### Current execution-context continuation

Native canonical materialization/finalization/audit now uses set statements;
each object retains its own Event ID, sequence, fence and mutation request hash.
Reservation, receipt and finalization query counts are constant for 1/9 objects.
The optional bounded readonly execution Port prepares <=1000 identities/32MiB,
revalidates full metadata and authority on exit, and keeps object I/O outside
database transactions. Core execution/prior observations/report pages use it.
Known-pure locked proof additionally prefetches lifecycle rows and canonical
Events in <=1000-identity pages, retains all URI/Event-ID conflicts, and cannot
escape its owning transaction. MODEL replay pages and current observations use
this path; unknown callbacks and overflow retain original guarded reads.
Migration94 indexes deployment/exact materialization URI; fleet identity names
this composition. Final proof still independently rereads original bytes.

These replace per-object SQL patterns, not the release gate. Current complete
execution measurement and outstanding authority/transaction fanout, immutable
retention, history/fleet scale and live acceptance are recorded in the evidence
document. Do not reinterpret a 2-query proof page as <=1000 whole-execution SQL.

### Exact-owner native operation composition

MODEL budget and batch acceptance/certification now expose their existing native
transaction to nested adapters through the existing work-unit mechanism. Exact
owner/deadline reentry is allowed, unrelated same-DSN sockets are not. Caught
nested failures roll back the operation; borrowers cannot escape or reset it.
Worker local authority/tail work is one database-only phase ending before Host
I/O. All current authority callbacks and full final originals remain; existing
locked external proof is not solved by transaction sharing. Fleet qualification
includes this composition and production activation remains OFF.

Final-source whole-nine23.4505s12180client18052server/248GET/5callbacks/6batches
certifies independently but FAILS the<=1000 gate. It is not comparable as a
fixed-batch speed change to the earlier4/5-batch10806/10922 results. Shared
minimum-deadline propagation also fixes older wrappers widening a shorter
SQL timeout; positive blocking-query cancellation is separately verified.
Next root must
replace repeated guarded adapter entry across a bounded execution phase with
native phase preparation/validation, retaining fresh post-I/O checks, rather
than merely borrow the same socket or relax public callback authority. Final
immutable retention, history/fleet quotas/fairness/load/live gates remain OPEN.
