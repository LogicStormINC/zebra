# Fresh binding read consolidation — 2026-10-11

Scope: COV-EXEC-01, Luke Ding / Codex, codex/cov-exec-01 isolated worktree.
Source-only follow-up; no runtime activation, restart, merge or push.

## Shared change

`load_session_task_binding` previously read root identity, derived all native
lineage, then read the latest binding separately. It now reads root identity
and latest scoped binding together with an indexed LATERAL lookup in the same
fresh read-only REPEATABLE READ transaction. The independent full lineage query
and child-root projection check remain unchanged. All native callers benefit.

No grant, STOP, lease or Artifact metadata cache was added. External object
reads retain their pre/post authority guards. Root-session business statements
are deterministically reduced from three to two, not including implicit BEGIN
or callback connection reset. Missing binding does not skip lineage checks;
duplicate, malformed or cross-Task identities refuse. SQL UUID conversion
errors are translated back to the existing controlled ValueError boundary.

## Evidence

- Initial storage + actual Worker binding regression: 10 passed, 25.51s,
  zero skips (`/tmp/cov-binding-consolidation.xml`).
- Hardened storage matrix: 12 passed, 11.30s, zero skips
  (`/tmp/cov-binding-hardened.xml`). Covers RR/read-only/reset semantics,
  fresh renewed binding, tenant isolation, corrupt parent proof, absent root,
  duplicate received Events, missing binding with valid/corrupt lineage,
  malformed root and substituted snapshot Task identity; exact two-query guard.
- Source reviewer: narrow GO; not rollout approval.
- Nine-record diagnostic60s, atomic receipt fixture, serial two paths:
  2 passed, 14 deselected, 96.06s, zero skips
  (`/tmp/cov-binding-native-nine.xml`). Both paths preserve 18 qualified
  receipts, zero exceptional recovery transcripts, 717 physical GETs, nine
  model HTTP calls, one independent certificate and one callback.

| Binding composition | Certified completion | Connection.execute | Native binding reads |
| --- | ---: | ---: | ---: |
| Fixed fixture callback | 35.4825s | 45,226 | 0 |
| Fresh database loader | 51.4186s | 54,181 | 2,985 |

The two rows are different compositions, **not** a before/after speedup.
The earlier frozen9 workload used a fixed binding callback: it did not exercise
this database loader and cannot establish its optimization benefit. The new
matrix labels binding composition explicitly. Its additional 8,955 executes
match 2,985 root binding reads (two business queries plus one scoped reset).
Query-count benefit is proven by the focused native regression; a native old/new
latency comparison or p95 claim has not been made.

Controlled input remains only nine records / 117 bytes, not real business load.
Connection.execute excludes cursor calls and implicit transactions. Diagnostic
60s is not the production2s work window. Transports are controlled and phase
times overlap. No semantic accuracy, live E2E or production SLO claim.

## Still open

Authority checks still fan out thousands of times. This change removes one
redundant lookup per root binding read, **not** the entire repeated authority
architecture. Artifact/authority operation boundaries, commit MODEL-history
replay, source fingerprints, mixed-tenant/fleet/fault acceptance and coordinated
rollout remain open. Production receipt minting remains off.

## Shared verified Artifact load — follow-up

The integrations `CoverageArtifacts.load` previously invoked bounded bytes and
then inspected metadata again, even when the store implemented the existing
`VerifiedArtifactPayloadReaderPort`. It now uses that Port for its fresh
pre/post-physical-read authority and metadata checks, compares the entire returned
StoredArtifactPayload with initial metadata, and independently verifies length
and SHA. Non-verified stores retain the old bounded-read + inspection branch.
No authority/metadata cache, dependency or new Port was introduced.

The native guard-order regression proves three fresh guards rather than four:
initial lookup, pre-I/O and post-I/O; only the redundant final inspection is
removed. Revocation during I/O still discards returned bytes, and substituted
full metadata, wrong length and wrong digest refuse.

- Existing integration publication/model tests: 46 passed1.26s; snapshot3
  passed1.03s. Native shared-load/facade15 passed15.60s, zero skips
  (`/tmp/cov-verified-load.xml`). Scoped reviewer source GO.
- make check: tracked sizes2382/Ruff/Mypy1092/eval30 passed; explicit
  tracked+untracked size check2562 passed. No live E2E/rollout claim.
- Same native-loader/atomic-receipt/diagnostic60s nine-record composition,
  legacy optional capability disabled only in the shared loader versus enabled:
  serial2 passed100.12s, zero skips/30 deselected
  (`/tmp/cov-verified-load-nine.xml`).

| Shared load path | Certified completion | Connection.execute | Binding reads | Public _record calls |
| --- | ---: | ---: | ---: | ---: |
| Legacy bounded + inspect | 50.1475s | 54,181 | 2,985 | 1,753 |
| Verified bounded read | 41.3743s | 49,829 | 2,713 | 1,481 |

Both preserve18 qualified receipts, zero exceptional recovery transcripts,
717 GETs, nine model HTTPs, one independent certificate and one callback. Query
reduction4,352 (8.0%) and binding-read reduction272 are measured on the same
controlled composition. One observed time pair is not repeated p95/SLO evidence;
static checks briefly ran concurrently, so do not infer an isolated latency
effect or production speedup. Overall SQL/time targets remain unmet.

Actual2s work window, native database binding and verified load: hardened1
passed68.45s, zero skips/31 deselected
(`/tmp/cov-verified-load-two-second.xml`). Certified completion63.7075s,
70,139execute/3,680binding reads/907GET/10callbacks; 18qualified receipts,
zero exceptional recovery transcripts, nine model HTTPs and independent final
certificate retained. This is not comparable to older fixed-binding2s timings.
No native old-path2s timing pair was run. The cost of repeated slice preparation
and native MODEL transcript replay remains, despite zero exceptional recovery.

## Incremental accepted-batch routing (2026-10-11)

Root cause: every record_merge called batches(), reading every historical result
Artifact even when final_certification mode already scoped original checkpoints
to current records. Event request descriptors deliberately exclude result bodies;
mutable coverage_units is not an authoritative batch-membership proof.

Accepted Events now atomically carry optional sorted unique record_ids derived
from the validated request (at most the existing 1,000-result commit bound).
The shared Event writer omits this hint if the complete descriptor would exceed
the existing 64KiB limit; the original mandatory descriptor limit still applies.
Only incremental final_certification transcripts filter by current record IDs.
Missing/non-array legacy hints retain full reads; mixed batches are read whole.
Canonical Artifact replay and same-key retries validate exact optional membership.
A hint hiding a required part cannot supply the exact accepted part sources, so
merge refuses. Hints route reads, never constitute proof or publication authority.

Final certification, eager validation, recovery and rebuild remain unfiltered.
Unrelated historical result damage may be deferred during incremental acceptance,
as explicitly authorized, but final certification physically rechecks every batch
and refuses corrupted bytes/membership. No certificate shortcut or cached authority.
No schema migration, hint backfill, object download/storage change or live restart.

Ceiling: SQL still filters a scoped native Event prefix; no new JSON/GIN index was
added without query-plan/load evidence. Full MODEL ledger/Event replay and fresh
authority fanout still exist. This change removes unrelated physical batch replay,
not all O(history) processing.

Validation: deterministic verification/persistence27 pass0.23s; oversized fallback1
pass0.23s. Initial native run13 passed, two failed solely on a stale batch_page=2
assertion (the pre-existing short-page optimization makes it1). Corrected that
expectation, then native final guards4 pass128.53s, zero skips: physical proof,
sequence/cumulative bounds, SQL-hidden required part refusal and persisted mixed
batch routing/duplicate refusal. Hardened damage/fallback/mixed5 pass91.04s,
zero skips. The mixed fixture is deliberately tampered history, not successful
mixed commit acceptance. Scoped source review GO; make check sizes2382/Ruff/
Mypy1092/eval30 GO; tracked+untracked2563 size GO. No full release/live E2E claim.
Same native nine-record full/scoped timing serial2 pass99.73s, zero skips/62
deselected (`/tmp/cov-batch-routing-nine.xml`). Same verified loader, native binding,
final_certification, qualified fixture-only receipts and diagnostic60s window;
no concurrent builds/gates. Control disables only optional batch routing.

| Batch reads | Certified completion | execute calls | binding reads | GETs |
| --- | ---: | ---: | ---: | ---: |
| Full historical batches | 46.3997s | 49,829 | 2,713 | 717 |
| Current-record batches | 45.1373s | 47,669 | 2,569 | 645 |

Both preserve18 qualified receipts/zero exceptional recovery/nine model HTTPs/
one independent certificate/one callback. SQL2160 fewer(4.3%), GET72 fewer(10.0%).
Inclusive commit time7.4244->5.0952s; one observed pair is not p95/SLO. Fresh
public Artifact _record still1481 calls in both paths, accounting for observed
22.20/23.03 inclusive seconds. Phase timings nest and are not additive.
Native2s scoped timing, successful mixed-batch commit, tenant-scale real load,
fleet/live acceptance remain unproven. Full native MODEL Event replay and current
authority fanout still dominate; no source speedup implies runtime deployment.

## Receipt-backed MODEL initialization (2026-10-11)

Root cause: each work-slice bootstrap and MODEL invocation object construction
initialize the durable budget (not each model HTTP call). Initialization replayed
the full MODEL transcript and settled historical objects even immediately after
atomic acceptance with an unchanged native tail.

The shared budget initializer now reuses the existing receipt reader only in
explicitly opted-in, native producer-qualified compositions. The reader's
optional unchanged-MODEL mode checks for a native MODEL event after the latest
acceptance in its source query. A new tail or absent legacy receipt returns to
full replay; default receipt consumers still reject fingerprint conflicts.

Eligible roots still require exact native accepted/predecessor/command source,
MODEL Event/call/ledger/witness fingerprint, current Task admission policy,
current run/stream/fence/STOP guards, original deadlines and fresh external
authority before and after proof I/O. Corrupt eligible roots refuse rather than
silently downgrading. Returning policy is not permission to invoke transport;
reservation, selected checkpoint verification and independent final physical
certification remain unchanged. No projection-count or cross-operation cache.

Ceiling: the native fingerprint remains bounded O(history) SQL. New MODEL tails
and commits still perform their required replay. Production receipt composition
remains disabled; this source change does not activate or deploy it.

Native probes run inside the existing receipt-mint transaction, avoiding nested
lock acquisition by the test itself. An earlier external probe was interrupted
after 256.99s with no completed tests because it borrowed conflicting locks;
that duration is not a runtime performance measurement. Corrected native4 passed
34.38s, zero skips: qualification, zero historical object reads, budget mutation
refusal, new-tail fallback and default-reader fingerprint refusal. Deterministic
initialization13 passed; combined focused48 passed/10 native tests skipped without
DSN. Native full-workload and final static results are recorded separately below.

Same native diagnostic60s nine serial2 passed104.30s, zero skips/126 deselected
(`/tmp/cov-receipt-budget-nine.xml`), no concurrent heavy gates. Full-budget:
48.3019s/47,669execute/2,569binding/645GET; receipt-budget:
46.4271s/47,699execute/2,571binding/645GET. Both two full initializations before
acceptance, one callback/18qualified/zero recovery/nine model HTTPs/one certificate.
No avoided replay or physical reads in this profile; extra30 execute calls are
receipt-eligibility overhead, not a query improvement. Timing difference is not
evidence of speedup. Actual multi-slice work must be measured separately.

Full receipt guard matrix plus corrected initialization probes: native14 passed
137.72s, zero skips (`/tmp/cov-receipt-budget-guards.xml`). Covers native chain and
append-only retention, rollback, eager/default compatibility, capacity fallback,
legacy prefix, predecessor/source/witness/call/budget mutation, post-scan expiry
and initializer reuse eligibility. Scoped reviewer GO; make check tracked2382/
Ruff/Mypy1092/eval30 GO, explicit tracked+untracked2565 size GO. Focused validation
is not the complete test suite or tenant/fleet/live acceptance.

Actual2s work-window same native nine serial2 passed149.83s, zero skips/126
deselected (`/tmp/cov-receipt-budget-two-second.xml`), no concurrent heavy gates:

| Budget initialization | Certified completion | execute calls | binding reads | GETs | Full replay |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full historical replay | 73.4938s | 67,979 | 3,536 | 835 | 20 |
| Qualified unchanged receipt | 67.1875s | 65,039 | 3,394 | 745 | 2 |

Both10callbacks/18qualified receipts/zero exceptional recovery/nine model HTTPs/
one independent final certificate. SQL2940 fewer(4.3%), GET90 fewer(10.8%);
18 redundant initialization replays avoided. Public Artifact _record1998->1818.
The observed6.31s difference is one pair, not p95/SLO or live tenant latency.
The workload regression now explicitly requires only two pre-acceptance full
initializations for qualified multi-slice runs. Overall65kqueries/67s is still
poor; fresh authority fanout, commit/native MODEL prefix replay and fingerprint
scan remain open. Fleet/large tenant/real semantic accuracy validation remains
unproven. No activation, runtime migration/restart, merge, commit or push.

Hardened qualified2s rerun with the new replay-count assertion:1 passed74.13s,
zero skips/127 deselected (`/tmp/cov-receipt-budget-two-second-hardened.xml`).
Certified completion68.6504s, same65,039execute/3,394binding/745GET/two full
initializations/10callbacks/18qualified/zero recovery/final cert. Final focused
orchestration47 passed0.26s and make check GO. Repeat confirms deterministic
query/read counts in this fixture, not large-load latency percentiles.

## Same-read metadata in MODEL boundaries (2026-10-11)

Root cause: CoverageArtifacts.load already obtains verified post-I/O metadata,
but discards it. CoverageModelInvocation._load then queries metadata again only
to track retention. Frozen boundaries also know the exact expected body digest
but still perform a preliminary getter before the native verified reader does
its fresh pre/post full-record reads. These nested getters fan out native Task
and permission checks and connection setup; no extra physical proof is gained.

The shared loader now exposes load_payload returning the same read's metadata
and bytes. Existing load preserves its (URI, bytes) result through that helper.
MODEL loads consume returned retention instead of another getter. Only when
exact frozen bytes provide expected_digest and the existing verified Port is
available does the helper skip the preliminary getter. Unknown objects and
legacy stores retain their existing lookup and read/inspection sequence.

Every boundary still physically reads the object and compares exact expected
bytes. Native verified reads retain fresh pre/post authority and full-record
comparison. Loader independently checks identity/session/URI/kind/MIME/lifecycle/
creation/retention/size/digest/length; MODEL rechecks original time bounds after
I/O and clamps prior retention. No metadata/body/permission cache crosses reads.
Known-digest native reads can perform bounded I/O before rejecting wrong kind,
MIME or creation metadata; nothing is accepted or sent before those checks.
Missing frozen objects raise instead of returning None internally; the required
boundary still refuses. Discovery/publication missing-object behavior unchanged.

Ceiling: required repeated physical I/O and per-read native authority remain.
This removes duplicate getters rather than replacing proof with a mutable count.
It does not change commit MODEL transcript replay, receipt opt-in/default policy,
final certification, schema or service activation.

Validation before timing: integration invocation/snapshot41 and recovery/refusal
182 passed; native loader16 passed21.38s, zero skips. Includes known/unknown
digest, verified/legacy reader, fresh pre/post authority, revocation during I/O,
returned metadata/byte mismatch and two consecutive reads without caching.
Scoped source reviewer GO. make check2382/Ruff/Mypy1092/eval30 GO and explicit
tracked+untracked2565 file-size GO. Full release/fleet/live gates not claimed.

Hardened native loader/facade26 passed27.57s, zero skips
(`/tmp/cov-model-load-metadata-hardened.xml`). Added known/unknown-digest tests
showing later metadata retention cannot renew the original shorter deadline,
including a physical read that crosses that original deadline. Final make check
and explicit size gate GO. Production composition, object storage and permission
policy remain unchanged; no restart/merge/push/activation.

Actual2s nine-record same-composition serial2 passed139.46s, zero skips/254
deselected (`/tmp/cov-model-load-metadata-two-second.xml`). Only the MODEL metadata
flow changes between controls; no concurrent heavy gates.

| MODEL metadata flow | Certified completion | execute calls | binding reads | GETs |
| --- | ---: | ---: | ---: | ---: |
| Repeated getters | 70.7937s | 65,039 | 3,394 | 745 |
| Same-read metadata + known digest | 59.9912s | 56,607 | 2,867 | 745 |

Both10callbacks/18qualified receipts/zero exceptional recovery/two initial full
replays/nine model HTTPs/one independent final certificate. Public Artifact
_record1818->1291. Removed527 getters and527 binding-loader calls;8432 fewer
execute calls(13.0%), exactly16 per eliminated getter in this controlled native
composition. Inclusive _record time31.27->20.90s, phases nest and are not additive.
Observed completion difference10.80s is one pair, not p95/SLO or real tenant
latency. Physical GETs unchanged: no evidence I/O was replaced by a cache.
Still56k+SQL/60s; commit/native MODEL history replay and necessary current
authority fanout, large tenant/fleet/live validation remain OPEN.

Same-composition60s nine serial2 passed99.28s, zero skips/254 deselected
(`/tmp/cov-model-load-metadata-nine.xml`); no concurrent heavy gates.

| MODEL metadata flow | Certified completion | execute calls | binding reads | GETs |
| --- | ---: | ---: | ---: | ---: |
| Repeated getters | 49.4899s | 47,699 | 2,571 | 645 |
| Same-read metadata + known digest | 41.0434s | 40,307 | 2,109 | 645 |

Both one callback/two initialization replays/18qualified receipts/zero
exceptional recovery/independent final cert. Removed462 getters and binding
reads,7392execute calls(15.5%), again16 per getter. Public _record1481->1019,
inclusive25.15->16.75s. Observed8.45s difference is one pair, not latency SLO.
The identical physical GET counts in both profiles confirm preserved reads;
40k+queries still exceed the intended multi-tenant performance target.

## Delta MODEL transcript (2026-10-11, source in progress)

Normal final_certification commits now reconstruct only MODEL calls belonging
to the current records, including every part needed for their record merge.
The initialization Event remains in scope. Unknown/eager, recovery, rebuild and
final certification keep full transcript reconstruction. Existing native SQL
source/witness/index/counter integrity runs before delta reconstruction; its
same-phase policy is reused, not a cross-request authorization cache. Duplicate
ledger/witness reads are omitted after that native check. Global budget counters
come from verified native state, never from the partial Python call table.

Receipt qualification computes remaining work against exact manifest part keys
and tenant/run-scoped native settled calls. It cannot treat the current record's
settlement as full-run completion, or rely on a missing unit projection to hide
work. Independent final physical/semantic verification remains unchanged.

This is NOT the final incremental state root: indexed_state, preflight volume,
Task history, manifest membership and receipt fingerprint still scan history.
Normal commit transaction still includes physical proof reads. No bounded SQL
complexity or latency improvement is claimed until measured and these scans are
replaced by sealed atomic facts. Production receipt composition remains OFF.

Remaining complete-system work:

1. Persist and seal native MODEL delta facts and their revision under the same
   run lock as event/call/ledger writes. Initialization validates the legacy
   prefix once; no missing/ambiguous root may silently upgrade it.
2. Normal commit consumes exact prior root plus newly settled calls and result
   identities. Use CAS/fence and idempotency, atomic budget/counters/checkpoint/
   receipt updates. New MODEL tail is a delta, not a full-recovery trigger.
3. Replace source fingerprints, global preflight and remaining-work scans with
   root-bound facts. Recovery/final certification independently retain full proof.
4. Add operation-scoped native authorization with explicit before/after-I/O
   guards and reliable revocation versions; no long-TTL permission cache.
5. Move physical proof outside long transactions, then revalidate exact versions,
   authority/fence/root and retention in a short atomic acceptance transaction.
6. Qualify Worker protocol/capability and rolling upgrades before enabling normal
   receipts. Test tenant isolation, stale Worker, STOP/revocation, duplicate/crash,
   races and certification failure. Add fixed-batch/history-growth SQL gates,
   then serial nine-record and concurrent tenant measurements.

No runtime migration, source-root seal, capability activation, restart or live
acceptance is performed by the transcript slice alone.

### Admitted incremental MODEL boundaries

The invocation now enables deferred historical boundary I/O only after actual
native admission matches caller policy AND initial manifest membership and
frozen official policy have been verified. Explicit final_certification mode
then uses original verified in-process values, not repeatedly rereading history
before/after every callback. Current loads, reservation/settlement, per-result
acceptance and independent final physical/semantic proof remain required.
Every boundary retains fresh authority and original snapshot/policy/retention
deadlines. Eager mode is unchanged. This intentionally moves detection of
unrelated historical object loss to independent certification; it is the user's
approved incremental acceptance contract, not public per-step final assurance.

Delta transcript alone measured nine2s1 pass65.36s:60.2254s/56639execute/745GET,
18qualified/zero exceptional recovery/final cert. Query count is32 above the
prior same-read fixture: transcript scoping alone is NOT a SQL speedup claim.
Latest boundary-deferral nine2s native workload passed (49.2905s measured
completion, 47599 Connection.execute, 2331 binding reads, 508 object GETs).
All18 receipts qualified, zero exceptional recovery, two initialization replays,
nine model HTTPs and one independent final certificate retained. This controlled
Host/model/S3 fixture is not live E2E or a business accuracy claim. Callback count
changed10->9 because slices are time-budgeted; this is not a fixed-callback
causal comparison, p95, concurrency SLO or bounded-query acceptance.

Final focused native matrix4 pass73.54s (zero skips): eager compatibility,
record-scoped incremental proof, unrelated native index corruption refusal,
and unrelated historical object corruption allowed by delta but refused by full
proof. The first object-loss assertion expected the wrong exception family;
corrected to the exact ArtifactObjectIntegrityError raised by native full proof,
without changing production exception handling. Latest invocation/recovery/
boundary/paging pure148 pass2.88s. Earlier native5 pass146.16s predates final
boundary deferral and is not used as current-version evidence.

Remaining workload SQL includes29967 business executes,11551 resets,4667 clock
reads and1414 timeout configurations. Authority fanout remains the dominant
structural problem: physical reads repeatedly reload Task binding, Event tail,
lease fence, active segment and Host snapshot descriptor. Original versioned
authority and sealed MODEL state work above remains IN PROGRESS. Do not enable
production receipts or claim complete-system completion from these results.

## Database-maintained MODEL revision root (2026-10-11)

Additive migration87 tracks every mutation to MODEL Session Events, independent
witnesses, calls and ledger under an exact deployment/namespace/run key. Updates
moving scopes invalidate both identities. Statement truncates conservatively
invalidate all roots. A guarded UUID generation plus monotonic bigint revision
cannot be edited, deleted, reset or truncated by ordinary direct SQL; only nested
native mutation triggers advance it. Revision writes share the source transaction,
rollback and row-version serialization. Privileged DDL/trigger disabling remains
outside this runtime database-role boundary, as with existing append-only guards.

Migration seeds generation identities only, NOT verified execution receipts.
The existing exact native commit verifier and full fingerprint still run before
new receipt mint. Mint then freezes the current revision in the same locked
transaction. New receipt reads compare the exact current revision plus migration
checksum rather than recomputing the whole MODEL fingerprint. Old receipts with
no revision still use their original fingerprint; legacy prefixes are not upgraded
from projections. New MODEL tails still require explicit delta/full verification.
RecoveryReadSnapshot records the revision lookup for fresh final revalidation.
Fresh Task/Host/lease/STOP/expiry, predecessor and certificate gates are unchanged.

This removes normal receipt READ history-scan complexity, not the number of its
three SQL reads; it is not yet an incrementally maintained budget state machine.
Receipt mint, indexed_state, Task-policy history, preflight and membership scans
remain. Triggers add native mutation work that Connection.execute counters do not
measure individually. No fleet activation or production migration was performed.

Native final14 pass113.40s: root update/delete/truncate/rollback/isolation guards,
separately committed mutation invalidates prepared proof, bounded new receipt
read (historical fingerprint function forbidden), legacy exact fallback, receipt
chain/duplicate retries/abort/retention/deadline/corruption and composition guards.
Earlier native initialization matrix4 also passed; initial combined5 pass35.63s.
The first receipt matrix11 pass/1 fail was an error-text compatibility assertion;
retained the original public refusal text and extended the expiry fault injection
to observe the new native revision lookup. Production behavior was not weakened.
Pure161 pass2.35s. Latest nine2s native workload1 pass58.63s: certified completion
53.5462s,49393 execute,2413 binding reads,518 GET,10 callbacks,18 qualified
receipts,zero exceptional recovery,two initialization replays and independent
final certification. The preceding version49.2905s/47599execute/508GET had9
callbacks; this root slice is NOT a demonstrated nine-record latency or query
count improvement. Its proven gain is bounded receipt-read history complexity.
Full mutation triggers introduce write overhead; real scale/history-growth and
concurrent load remain required before rollout or any performance/SLO claim.

## Revision-bound receipt mint (2026-10-11 follow-up)

The qualified commit verifier still validates native MODEL source/index/budget
and current result evidence under the existing run/stream transaction. Mint now
captures the v87 root directly; it no longer constructs an additional O(history)
fingerprint merely to discard it on the next normal read. Root-bound witnesses
retain the v1 envelope with a null legacy fingerprint. Root-less mint/read keeps
the original exact fingerprint fallback. A missing/changed root on a root-bound
receipt refuses, never downgrades. No scalar revision arithmetic authorizes a
new delta, and no historical corruption or final certificate check is removed.

Continuation qualification now includes `database-maintained-model-revision/87`.
The shared qualification digest changes, preventing fingerprint-only Worker
identity from matching the new contract. Old readers fail closed on a null
fingerprint. Deploy/control-plane and Worker qualification must move together;
this is not mixed-fleet activation or a production migration.

Historical fingerprint capacity remains a legacy fallback condition, not a
version-root budget. Receipt-body read size and native acceptance limits remain.
The first matrix13 pass/1 fail exposed that obsolete capacity assertion; it was
split into legacy and root paths. Updated native matrix15 pass121.08s/zero skips
includes mint/read history scans forbidden, missing-root refusal, mutation and
rollback, predecessor, deadline, original legacy capacity and independent final
certification. Qualification/readiness pure34 pass with14 environment-gated
native skips before the separate native continuation validation.

Still OPEN: incremental native budget facts, Task/Host authority fanout,
membership/preflight scans, shorter physical-proof transactions and tenant/fleet
SLO/live acceptance. Production receipts OFF; no restart, primary edits,
merge/push or deployment. Serial nine-record measurement follows separately.

Serial native nine workload1 pass55.64s: certified completion50.4048s,
49375 Connection.execute,2413 binding reads,518 GET,10 callbacks,18 qualified
receipts,zero exceptional recovery,two full initialization replays and one
independent final certification. Previous v87 control53.5462s/49393execute had
the same callbacks/bindings/GET: exactly18 redundant fingerprint executes are
removed (one per mint). The observed3.14s improvement is a single-run comparison,
not a causal latency/SLO claim. Inclusive commit time6.010s->4.973s is nested;
do not add it to other phase measurements. Counters exclude implicit transaction,
cursor and trigger-internal SQL. Workload uses native PG/Worker but controlled
Host/model/S3; real tenant concurrency and semantic accuracy remain unproven.

Final continuation/readiness/capability/native revoke-epoch-expiry race matrix:
69 pass122.37s/zero skips. Final make check GO (Ruff, Mypy1094, eval30), actual
tracked+untracked file-size2572 GO and git diff --check GO. Focused native tests
do not establish production mixed-fleet rollout or a full repository test gate.

## Exact incremental native MODEL facts (2026-10-11, v88)

Normal budget-state proof now has an inductive native root, not a Python cache
or an assumed scalar revision delta. New migration88 maintains one exact scoped
summary of initialized/reserved/usage Events, witnesses, calls, charged tokens
and unresolved calls. Event appends bind a single Session and frozen policy;
every witness insert must match the exact native scoped source row; new calls
must match their reservation Event and key and have no receipt; only first
settlement of unchanged reservation identity can replace its full charge with
usage from the exact native receipt Event. Ledger writes must match derived
call facts. All transitions serialize on the summary row and share rollback
with Events/index/ledger. Duplicate retries do not advance counters.

The normal read uses one indexed summary/ledger lookup with matching migration
checksum, policy, Session, exact source/call/witness cardinalities and budget
bounds. Unique source/witness and reservation identities plus per-row equality
checks establish the representation bijection; counts alone do not authorize
unverified representations. Current Task policy is still independently derived,
not cached. Existing fence/authority/STOP/physical checkpoint/deadline boundaries
are unchanged. Eager mode remains on independent native history scans; only
actual `final_certification` admission uses the fast budget proof. Full recovery
and final certification still independently replay complete native sources and
original objects rather than certifying the summary.

Unsupported source/witness updates, deletes/truncates, reservation rewrites,
repeated settlement or mismatched ledger writes invalidate the fast path.
Moving scopes invalidates both. Invalidation cannot be reset by ordinary SQL;
repairing a projection does not requalify its root. These cases use the original
independent native scans and still refuse corruption. Migration seeds existing
runs as invalidated: no automatic blessing of historical projections. Explicit
verified legacy requalification is not implemented; legacy runs remain slower.
As with v87/append-only guards, privileged trigger disabling or DDL is outside
the trusted runtime DML boundary; production DB-role enforcement is a rollout
prerequisite, not a superuser-tamper guarantee. Fleet qualification now binds
`database-maintained-model-summary/88`, excluding revision-only older consumers.

New native5 pass10.74s: exact root counters agree with independent full scans
before reservation, after reservation/settlement and retry; admitted normal
index uses one root read; missing migration checksum falls back; unsupported
changes/rollback/guarded edits, migrated legacy and repaired-projection refusal.
Pure105 pass0.60s with4 environment-gated native readiness skips. Static1096
sources/eval30 and actual2575-size/diff checks GO before final matrix results.
Initial native matrix43 pass/3 fail227.43s: three older certification-error
assertions expected a MODEL/authority error although the existing incomplete-set
gate runs first. Without migration88 the exact same three failures reproduced
in63.44s. Updated only those rejection-text assertions; no production gate moved
or removed, and their budget/source immutability assertions remain.

Final native MODEL matrix48 pass228.11s, Worker/continuation/fleet matrix82
pass225.65s, both zero skips. These matrices ran in separate fixture schemas in
parallel and are regression evidence, not latency measurements. Final actual
tracked+untracked file-size2575 and diff checks GO.

Separate serial native nine:1 pass58.12s, `/tmp/cov-model-summary-nine.xml`.
Measured after fixture setup/first handoff through certified completion:
52.1280589s/49237execute/2413binding reads/518GET/10callbacks/18qualified,
zero exceptional full recovery/two MODEL initialization replays/independent
final certification. Prior same-callback run50.4047997s/49375execute has equal
bindings/GET:138 executes removed, but this run is slower. No overall latency
gain or SLO claimed. Trigger-internal SQL is excluded from execute counts.
Business30895execute22.4137s/reset11904/clock4847/timeout-config1591. Inclusive
Artifact record837calls12.6309s, commit18calls5.2329s, continuation27calls2.2634s,
publication2calls5.9035s are nested, not additive. Controlled Host/model/S3 and
native PG/Worker prove this scenario only, not real tenant load or semantics.

Remaining roots: Task/Host history/authority fanout, preflight and manifest
membership, shorter object-proof transactions, legacy requalification and
tenant/fleet/SLO/live acceptance. This bounded MODEL-facts proof does not make
the whole invocation O(1). No production migration/restart/activation/merge/push.
