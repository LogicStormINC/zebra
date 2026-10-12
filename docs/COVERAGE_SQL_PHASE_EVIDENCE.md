# Native coverage SQL operation boundaries

Owner: Luke Ding / Codex. Task: COV-SQL-PHASE-01. Date: 2026-10-12.
Branch: `codex/cov-sql-phase-01`, based on `1388aca7`.

## Verdict

**In progress; strict performance gate FAIL. Not release-approved.**
Normal continuation no longer performs exceptional full recovery. This does not
make its overall SQL cost acceptable. The remaining root is nested authority,
projection, publication and original-proof operations, not query spelling.

The user subsequently authorized local integration for manual testing only.
See `COV_SQL_MANUAL_TEST_20261012.md` for the integration/build record and operator
commands. No business database migration, service restart or push is authorized
in this preparation step. Source integration does not close the SQL gate.

## Reproducible measurement boundary

Tests use an isolated PostgreSQL scratch database and fixture-owned schemas.
The workload has nine controlled records, 117 input bytes, 18 accepted units
and nine controlled model responses. Signed Host and object transport are
fixtures: neither live provider origin nor business semantic accuracy is proved.

Measurement begins after fixture setup, before the first native handoff, and
ends at independently certified completion. Connection/Cursor execute and
executemany are counted without double counting. One executemany is one client
call; implicit transaction commands need the separate server monitor. The
current server monitor is unavailable. Nested phase times are not additive.

Earlier `object_gets=0` observed only the old fake-client method, not native SDK
HEAD/GET sends. The current fixture also counts native transport attempts;
these are controlled transport counts, not live object-service telemetry.

| Source checkpoint | Work slice | Client SQL | Certified seconds | Gate |
| --- | ---: | ---: | ---: | --- |
| Native atomic before read-only observation | 60,000 ms | 9,401 | 18.3101 | FAIL |
| Read-only observation before physical-read sibling repair | 60,000 ms | 7,856 | 15.3941 | FAIL |
| Before private publication separation | 60,000 ms | 8,032 | 15.4024 | FAIL |
| Before private publication separation, normal continuation | 2,000 ms | 13,072 | 25.0928 | FAIL |
| Private publication separation, before Host exit repair | 60,000 ms | 6,599 | 13.7492 | FAIL |
| Private publication separation, before Host exit repair | 2,000 ms | 11,067 | 21.1640 | FAIL |
| Host exit repair checkpoint | 60,000 ms | 7,976 | 15.9130 | FAIL |
| Host exit repair checkpoint | 2,000 ms | 14,654 | 29.5664 | FAIL |
| Qualified preparation + per-object publisher, before outer semantic owner | 60,000 ms | 8,513 | 31.1152 | FAIL |
| Qualified preparation + per-object publisher, before outer semantic owner | 2,000 ms | 16,805 | 52.6762 | FAIL |
| Outer native semantic owner | 60,000 ms | 8,405 | 29.3450 | FAIL |
| Qualified final proof and native checkpoint publication owner | 60,000 ms | 7,745 | 40.5162 | FAIL |
| Qualified final proof and native checkpoint publication owner | 2,000 ms | 17,745 | 76.9410 | FAIL |
| Fresh readonly observation and native executor, final reviewed source | 60,000 ms | 6,848 | 38.5006 | FAIL |
| Fresh readonly observation and native executor, final reviewed source | 2,000 ms | 16,292 | 72.1584 | FAIL |
| Unified native evidence owner, post-review source | 60,000 ms | 6,411 | 37.9034 | FAIL |
| Unified native evidence owner, post-review source | 2,000 ms | 15,653 | 73.4954 | FAIL |

These are single controlled runs, not a latency distribution or live p95.
An earlier atomic run failed functionally; its legacy fallback is not an
apples-to-apples atomic baseline. Parallel-test timing is not serial evidence.
The strict threshold remains **at most 1,000 client calls**, unchanged.

Host-exit checkpoint serial long-slice distribution: 4,634 business calls, 2,063 database-clock
calls and 1,279 connection resets. Artifact publications used 1,270 exclusive SQL
calls. Nine MODEL invocations used 2,079; final lifecycle verification used 798.
Both long and short slices had **zero exceptional full recovery transcripts**.
Host-exit checkpoint short slices accepted six batches, qualified six receipts and used five
Worker callbacks. Before the Host exit repair, short slices used four callbacks.
Consequently the short totals are not a fixed-batch cost comparison. The required
post-Host check cannot be removed to recover the lower interim measurement.

Host-exit checkpoint logs/JUnit files: `/tmp/zebra-sql-phase-host-exit-long-20261012.*`
and `/tmp/zebra-sql-phase-host-exit-short-20261012.*`. The applicable test is
`tests/worker/test_coverage_work_load.py::test_native_normal_work_slices`, with
the native-atomic / incremental / verified-load / scoped-batches parameters and
`ZEBRA_COVERAGE_ENFORCE_SQL_BUDGET=1`.

The preparation/publisher checkpoint uses `sys.setprofile` code-frame observation
instead of monkeypatching production methods, which would disable native delegate
qualification. All 72 preparation checks qualified; their CPU cost was 0.088s.
Long-slice exclusive SQL: publisher2239, MODEL1647, executor1595, other1704,
commit296, final lifecycle798. Short callbacks6/batches7/qualifiedreceipts7,
exceptional recovery0. Logs: `/tmp/zebra-sql-phase-native-prepare-{long,short}-20261012.*`.
Profiling changes wall-clock overhead and short-slice partitioning: these seconds
are diagnostic, NOT a direct latency comparison with earlier instrumentation.
SQL increased despite successful preparation qualification: required physical
publication guards outweigh the removed helper entries. Do not claim improvement
of the complete chain. The outer semantic owner then removed108 SQL entries
without removing any actual I/O guard: native90/90 qualifications, model1647,
executor1487, publication2239, recovery0. Log/JUnit:
`/tmp/zebra-sql-phase-semantic-long-20261012.*`. The full <=1000 gate STILL FAILS.
Do not extrapolate a nine-record query reduction to high-concurrency acceptance.

Latest checkpoint-owner serial runs certify with zero exceptional recoveries.
Long: one callback/two accepted batches; SQL categories business4494,
clock1955/reset1296. Exclusive phases: other1692, preparation6, publisher2239,
record228, executor1379, MODEL1395, commit152, final654. Native transport attempts:
GET107/HEAD1/PUT43. Short: seven callbacks/eight batches; GET200/HEAD1/PUT49.
Native authority entries1430/2450 and descriptor entries757/1231 show the
amplification is still above actual object I/O. Native preparation90/90 qualifies.
Logs/JUnit: `/tmp/zebra-sql-phase-checkpoint-owner-{long,short}-20261012.*`.
The observer changes CPU overhead and short-slice partitioning; no direct
latency or fixed-batch short-slice improvement is claimed.

Final follow-up implementation: split a fresh single-SQL
readonly lease/epoch/lineage observation from existing locked write checks;
borrowed native transactions keep the latter. The core preparation hook is
guarded by default. Only the exact source-owned native executor delegates pure
CPU preparation to already-guarded adapters. `_live` and final certification
remain unchanged. These components are NOT a full operation-owner solution.

Final reviewed source reproduces **6,848 long / 16,292 short** client SQL, with
one/two and seven/eight callbacks/accepted batches respectively. Both independently
certify, with zero exceptional recovery transcripts. Compared with the previous
checkpoint-owner counts, this removes 897 (11.58%) and 1,453 (8.19%) calls; it
does not meet the unchanged 1,000-call budget. Short object GET attempts changed
from 200 to 204, so the short result is not a fixed-I/O comparison or p95 claim.

Long exclusive SQL: handoff/general authority 1,589, preparation 6, publication
1,825, record reads 226, executor 1,109, MODEL 1,287, acceptance 152, final
lifecycle 654. Categories: business 3,741, clock-containing 1,883, resets 1,224.
The clock category includes authority statements with a DB timestamp; only 294
are standalone `SELECT clock_timestamp()`. Native authority observations 1,358
include 677 borrowed locked checks; Host descriptor entries 721. Actual object
transport attempts are GET107/HEAD1/PUT43, not 721 downloads.

Short exclusive SQL: handoff/general authority 8,255, preparation 6, publication
2,221, record reads 502, executor 1,529, MODEL 1,287, acceptance 704, continuation
preparation 486, read revalidation 504, final lifecycle 798. Categories: business
9,039, clock-containing 3,783, resets 2,518, timeout configuration 952. Native
observations 2,382 include 1,133 borrowed checks; descriptor entries 1,197;
GET204/HEAD1/PUT49. Repeated cold native preparation and mandatory boundaries,
not exceptional recovery, amplify the short-slice cost.

Final logs/JUnit: `/tmp/zebra-sql-phase-read-observation-final-{long,short}-20261012.*`.
Both strict pytest runs exit 1 on the existing SQL-budget assertion, after
functional certification checks succeed. Interim long6,848/38.7237s before the
qualification review fixes remains diagnostic, not the final source result.

## Implemented, bounded improvements

### Unified evidence operation (2026-10-12, current implementation)

The exact native Worker composes `PostgresCoverageEvidenceOperation`, rather
than separately acknowledging publication and then opening public usage or
acceptance operations. A durable bounded reservation precedes object transport;
each actual PUT/verified GET retains fresh entry/exit revocation checks outside
the mutation transaction. One post-upload owner locks the run and atomically
settles full metadata, receipt/materialization Events and either MODEL usage or
unit acceptance. Acknowledgement and verified byte-cache seeding follow owner
commit. MODEL precharge and independent final original-byte certification are
unchanged. No cached authority, changed SQL threshold or runtime activation.

Acceptance prefetch selects affected record checkpoints, observations and merge
batches, not all finalized historical objects. It uses full metadata equality
and rejects overflow instead of truncating proof. A single fresh readonly SQL
snapshot returns lease/epoch/lineage facts plus requested full metadata; actual
object I/O still has its own guards. Foreign or modified delegates retain the
guarded generic path or refuse before staging. Legacy native prerequisites are
checked before upload; they cannot silently inherit incremental certification.

Interim serial measurements after Worker integration were long6,442SQL38.7739s
(1 callback/2 batches), short14,104SQL71.3073s (6 callbacks/7 batches).
Both certified with zero exceptional recovery. These precede final kind/MIME,
reader-selector pins and prerequisite guards and are NOT final-source acceptance.
Their unchanged <=1000 gate FAILS. Long required GET107/HEAD1/PUT43;
short GET182/HEAD1/PUT48. Short partitions differ from the previous run, so no
fixed-batch improvement or latency distribution is claimed. Logs/JUnit:
`/tmp/zebra-evidence-owner-final-{long,short}-20261012.*` (names retained;
despite their original names, classify them as interim evidence).

The coordinator alone does not eliminate outer entry fanout. Interim long
exclusive SQL: general handoff/authority1545, publication835, metadata114,
executor827, MODEL576, unified usage1233, unified acceptance652, final654,
preparation6. Native authority1082 entries include423 locked checks; descriptor
703 entries exceed the actual107 GET attempts. The remaining implementation
gap is shared operation-owned authority/proof facts through the locked kernels
and outer guarded consumers, not SQL spelling or omission of final validation.
Strict gate and multi-tenant fleet acceptance remain open.

Post-review serial tests now produce **6,411 long / 15,653 short** SQL calls.
Both independently certify, with zero exceptional recovery. Long uses one
callback/two batches and GET107/HEAD1/PUT43; short uses seven/eight and
GET204/HEAD1/PUT49, matching the previous reviewed source's partition/I/O counts.
Reduction versus6,848/16,292 is437 (6.38%) /639 (3.92%). No statistically
demonstrated latency improvement: one instrumented run is not live p95; short
wall time is slightly higher. The <=1000 assertions still fail. Logs/JUnit:
`/tmp/zebra-evidence-reviewed-{long,short}-20261012.*`.

Long exclusive SQL: general1545, preparation6, legacy publisher835, metadata114,
executor827, MODEL576, unified usage1206, unified acceptance648, final654.
Short: general8091, preparation6, publisher835, metadata282, executor1157,
MODEL576, unified usage1206, unified acceptance1712, continuation486,
read revalidation504, final798. Authority1060/1958 entries include379/649
locked checks; Host descriptor681/1145 entries remain disproportionate to
actual107/204 GETs. Shared operation-owned authority facts in outer consumers
and normal continuation preparation are still required. This task stays open.

Review corrections preserve safety rather than silencing failures:

- Qualified native operations use fresh local locked authority, not Host I/O,
  inside the mutation transaction. Host/object I/O retains outside-TX guards.
  A postcommit Host revocation refuses acknowledgement of private internal
  evidence; it does not roll back committed usage or authorize a formal answer.
- Oversized or legacy-unsealed native eligibility is decided before staging /
  I/O. Only this typed refusal falls back to full guarded public proof; later
  integrity, revocation or mutation faults never become fallback permission.
- An uploaded staged MODEL response is recoverable only after original request,
  manifest membership, retained full metadata, physical version and bytes have
  been proved. Approval/handoff compare the exact recovery proof and reread the
  original version. Unsettled usage remains unsettled until a fresh Worker fence
  commits it. Missing/corrupt responses and STOP still refuse; no second MODEL.
  Independent final certification is unchanged and never consumes this cache.
- Real Worker crash/positive/missing/corrupt/STOP4 pass41.65s; recovery/read/
  invocation contracts123 pass10 infrastructure skips3.32s. Earlier native
  evidence/fault40 pass437.16s and public publication39 pass87.55s precede these
  review corrections; the post-review fault matrix and fresh full suite are
  running and are not yet GO. Initial full9024 pass2662 skip12 fail revealed
  a test double missing the actual `_remember_verified` method; focused14 now
  pass, not a substitute for the fresh full rerun. No tests or thresholds deleted.
- Post-review fault matrix:63 pass/2 stale trigger-error expectations626.15s.
  Both failures were canonical Task Event immutability refusals, not successful
  corruption. Exact DB-error expectations now preserve rollback and idempotence;
  current related12 pass130.37s. The broad matrix predates those test-only
  corrections and is not falsely relabeled as65-pass. Quality review additionally
  found a staged-original finalizer `TimeoutError` escaping the recovery batch;
  only that transport timeout now becomes `CoverageRecoveryDeferred`. New/old
  timeout/read/transcript19 pass2.68s; independent reviewer reran the new1-pass
  check and returned scoped GO. Current full rerun predates that small timeout
  correction, whose evidence remains separate. File-size/Ruff/mypy1243/eval30 GO.
- Fresh full rerun completed: **9036 pass /2680 infrastructure-prerequisite
  skips /0 failures in1153.74s**. Log/JUnit:
  `/tmp/zebra-evidence-current-full-20261012.*`. Collection predates only the
  finalizer timeout patch and two PG trigger-expectation corrections; their
  focused19/12 and independent1 checks remain separate final-patch evidence.
  Missing DB/real provider/runtime prerequisites were not faked to turn skips
  into acceptance. The explicit serial PG SQL gates still FAIL and this full
  suite does not certify multi-tenant scale, live latency or semantic accuracy.

- Source-owned native preparation checks exact Worker callbacks, typed binding /
  policy, facade / metadata / publisher identities and actual delegates. Only
  frozen CPU work and fence copying use zero-SQL helpers; changed delegates fall
  back to guarded methods. Admission, pre-charge, model I/O, post-response,
  settlement and delivery barriers remain fresh. The private semantic wrapper
  delegates its pure formatting boundary only to this exact native invocation.
- Exact native MODEL checkpoint publication consumes the native verified
  acknowledgement instead of opening a second prelookup/readback phase.
  Foreign callbacks and non-checkpoint publication keep the generic path.
  Independent certification owns a fresh bounded original-byte cache which is
  cleared at scope exit, never the incremental execution cache. Each separate
  post-append certification starts empty and physically verifies originals.
- Publisher guards every actual put and verified read, both before and after.
  Revocation during object one refuses before object two. No object I/O borrows
  its native transaction. After upload, receipt recording and Event finalization
  share one post-lock transaction; callback failures roll both back to revision0.
  Deterministic object versions remain recoverable; standalone receipt hooks
  retain their original behavior. This is NOT atomic MODEL usage settlement.
- Workload observation no longer replaces security-qualified source delegates.
  Its regressions verify unchanged identities, nested phase restoration and
  profiler restoration after exceptions. Capability configuration changes bind
  these source-owned preparation and publication contracts; stale Workers cannot
  inherit qualification from an old configuration digest.
- Native authority observation is read-only. It does not project a borrowed,
  possibly uncommitted Event tail. Private publication reads its fresh fenced
  canonical revision without updating UI aggregates, and native Artifact sync
  is read-only too. Continuation and finalization consume the committed tail.
  Native revision CAS, post-lock validation and deterministic Artifact recovery
  remain authoritative, not the lagging recorder's sequence.
- Host descriptor return rechecks local authority before consumption. A native
  regression changes actual SQL authority during an otherwise successful Host
  read and verifies refusal before certification. This extra boundary is included
  in the current performance measurement, not hidden from the budget.
- Native writes borrowed from an outer work unit suppress premature live hints.
  Success and rollback checks cover Event append, singleton/batch projection and
  projection commits. No uncommitted Event is advertised as committed; durable
  replay remains the visibility mechanism.
- Native Task position repair uses bounded pages and bulk SQL. Exact no-op
  byte bounds no longer mutate sealed original rows. Late Task coordinates are
  allowed by additive migration 99 only when canonical business content is
  unchanged; historical migration bodies/checksums are unchanged.
- Optional native Worker projection batches apply at most 128 contiguous
  canonical Events, writing each aggregate once. Native rollback, fence expiry,
  foreign scope, gaps, noncanonical state and exact retry remain checked.
- MODEL original proof consumers forward the existing bounded proof reader.
  Metadata without its matching Event is not a complete cached proof.
- Known pure derivation coalesces retention checks until scope exit. Physical
  object I/O still checks current authority before and after each actual read;
  unknown callbacks retain the guarded path.
- Payload reuse requires equality of the complete lifecycle record, not merely
  an Artifact ID or digest. Prepared and locked readers reject revocation during
  object one before reading object two, including mismatched-cache cases.
- `COVERAGE_UNIT_ATTEMPTED.attempt_number` is the unit reservation counter, not
  the Harness attempt identity. Normal short-slice replay no longer conflicts
  with the Harness counter. Invalid unit counters and stale output still refuse.

## Required root implementation, not more isolated SQL cuts

### Cost floor and the next coherent owner

The reviewed source still separately owns Artifact metadata reads, immutable
publication, MODEL usage settlement and unit acceptance. Zero-SQL CPU hooks
cannot eliminate their independent transactions. For this controlled workload,
43 actual PUT plus107 GET under the current full entry/exit barrier imply roughly
600 local authority statements alone (two local observations in each guard,
before and after each I/O). The226 write-fact checks plus their corresponding
lease statements add roughly452, before metadata, DML and resets. These are an
architectural estimate, not additive profiler counters or a proven lower bound
for a consolidated implementation. Observations1,358 already include677 locked
fallbacks; never add those counters as1,358+677 independent guards.

Consequently removing resets alone, adding an index, or combining only readonly
authority/metadata cannot satisfy1,000. The next coherent implementation is one
source-owned **bounded evidence-operation owner** across producer/read preparation,
publication and settlement:

1. A fresh bounded readonly snapshot returns authority facts and selected full
   metadata together. Host attestation retains fresh local return revalidation;
   every actual object read keeps fresh guards and complete-record exit comparison.
   The observation grants no later mutation right and holds no execution I/O lock.
2. Persist exact MODEL reservation before transport. Upload/verify frozen objects
   outside transactions. Stage deterministic evidence so crashes never require
   a second model request or lose an immediate charge.
3. One post-upload fenced transaction owns receipt/checkpoint finalization,
   usage settlement and eligible observation/result Events. Native internal
   helpers consume that exact transaction's post-lock facts and frozen inputs
   instead of reopening public proof/read adapters. Preserve canonical Event
   identities, receipt revisions, stream CAS, budget charges and final full-record
   validation. Extensible callbacks use the generic path or exact fresh revalidation.
4. Preserve independent final original readers and post-certificate rollback;
   settlement acknowledgements never substitute for certification. Short wakes
   restore only the bounded operation continuation, not another cold producer
   traversal. Measure physical operations, transaction phases and all client SQL
   again before promising the gate is feasible or activation is safe.

Required regressions include every crash between reservation/upload/receipt/usage/
unit acceptance, exact replay and no duplicate model charge/Event, same-transaction
callback mutation, lease/deadline expiry after lock waits, revoked Host returns,
tenant isolation and post-append original-proof failure. This structural owner
is still **unimplemented**, not concealed behind the successful pure-hook tests.

### 1. One owner for each native operation

Split the actual invocation into pure preparation, external I/O, fenced database
mutation, and delivery/certification. A trusted source-owned native composition
may delegate these boundaries to its actual operation owner. A caller flag,
protocol implementation, declared callback name or cached permission alone
must not qualify it. Changed dependencies and injected callbacks keep guarded
fallback or refuse.

Pure work: frozen request construction, digest/schema validation, deterministic
derivation and retrieval of the immutable current fence. It must execute zero
SQL and zero Host requests. STOP may arrive during CPU work; no subsequent I/O,
mutation or successful delivery may cross its fresh boundary after that STOP.

External work: actual Host/model/object requests have fresh entry/exit guards.
No database transaction remains open across network I/O. A Host callback can
change local authority, so the exit guard must observe that change too.

Native writes: one short owned transaction validates the post-lock fresh
snapshot, lease, epoch, STOP, active segment, binding and current budget. Internal
pure helpers reuse those pinned facts rather than reopen their public adapters.
Never combine lock acquisition with a stale pre-wait authorization snapshot.

### 2. Native MODEL settlement owns checkpoint publication

Keep the reservation durable before the model request and the charge durable
immediately after receipt. Do not send a model request twice after a crash.
Co-locate checkpoint metadata/receipt finalization and settlement where their
ownership permits it. Read/pin current affected originals in bounded sets; do
not replay unrelated historical originals at every unit. Preserve exact
deterministic Artifact identities, staged recovery and immutable source Events.
Move extensible callbacks outside the pure mutation kernel; any callback within
the transaction requires exact post-callback lifecycle/Event revalidation.

### 3. Final certification remains independent

Read original bytes, exact accepted/expected sets, source Events, budgets and
current lifecycle independently before formal publication. Recheck after the
certificate append and refuse/roll back races or expiry. Incremental payload
caches and continuation receipts never substitute for this gate. An immutable
object-retention proof would be a separate contract, not an assumed shortcut.

### 4. Admission and fleet budget are explicit

Account for cost by admitted records, parts, model calls and batch count, not
only SQL per request. Bound pages, buffers, I/O, lock/statement deadlines and
normal continuation work. Maintain tenant fairness at queue admission and
worker scheduling. Do not hold global locks, load full history, silently widen
timeouts, disable namespace cleanup or increase the SQL acceptance threshold.

## Open gates and risks

- Preparation and per-object publication owners are implemented, but the complete
  operation chain/MODEL-publication-settlement consolidation remains OPEN.
  Final measured6,848 long/16,292 short calls are not root-performance acceptance.
  Source review has no remaining finding in its scoped readonly/preparation/
  qualification boundaries; it does not certify the whole architecture or SLO.
- Remaining dominant duplication is above the owned adapter: executor `_live`,
  facade sync/authority/publication wrappers
  and singleton read scopes. Do not broaden exact-type reader eligibility or
  substitute a permission TTL. Actual per-object entry/exit checks stay mandatory.
- Qualification and fault tests must cover mutated delegates, same-transaction
  revocation, post-lock permission changes, physical I/O, settlement callbacks,
  crash/replay/no-double-charge and post-append certification rollback.
- Current focused checks: pure progress 32; Task repair 16; native migration /
  membership / source / proof-prefetch 45; reader/progress/resume group 100.
  Counts overlap other subsets and must not be summed as a full-suite result.
- Borrowed publication/catalog group: 30 pass. Paging/catalog regressions: 24
  pass. Direct publication sync/native dispatch: 18 pass before the Host exit
  repair; dispatch source rerun: 18 pass, one test expected the wrong exception
  layer (the intended authority refusal occurred). Corrected Host exit/authority
  focused group: 2 pass. Final recorder-lag/Host exit/native dispatch group:
  **19 pass in 67.34s**. Multiple private publications use the current SQL stream
  revision even while the recorder intentionally lags; finalization catches up.
- Preparation/publisher regressions30 pass68.42s, generic MODEL145 pass2.71s,
  non-mutating phase observer2 pass0.17s. Authority/dispatch/observer21 pass72.16s
  before the outer semantic follow-up. These are overlapping focused subsets.
- Semantic-owner/native authority/dispatch21 pass100.16s before the captured
  classifier repair; final classifier/factory/metadata/deriver/foreign-callback
  and post-model revocation2 pass22.90s. Unknown or replaced classifiers are not
  invoked to qualify themselves. Final pure/reader/model183 pass15 prerequisite
  skips3.49s. Non-mutating physical operation counters have observer2 pass0.15s.
- Final checkpoint-publication/preparation9 pass47.29s; locked/prepared/shared
  read43 pass29.54s; scoped publication faults43 pass94.94s preceded the final
  checkpoint acknowledgement field correction. Final9 reran after correction.
  These overlapping focused groups are not a fresh full-suite acceptance.
- Read-observation/authority/executor30 pass167.96s; final enhanced native
  executor/preparation/publication11 pass58.73s. The final group includes Host
  property-before-type rejection, subordinate Host/transport/artifact/authority
  delegate replacement, hostile definition equality and generic guarded fallback.
  Pure executor/progress/observer29 pass2 prerequisite skips2.45s. These overlap
  earlier groups and do not replace a fresh full suite.
- Final static passes2,920-size, Ruff, mypy1,238 and eval30. Critical publication /
  physical-I/O / proof-reader regressions pass80 in81.57s, run separately after
  both serial measurements. They cover first-object revocation, no later I/O,
  post-upload transaction ownership, atomic receipt/Event rollback, exact replay,
  full-record proof/cache changes and independent final-byte ownership. This
  focused group does not make the strict SQL or fresh full-suite gate green.
- Checkpoint-owner static check passes file sizes (2,920 files), Ruff, mypy (1,237 source
  files) and 30 deterministic eval cases. Full regression completed at 9,019
  passed / 2,556 prerequisite skips / 7 failures. The catalog tail and optional
  prefetch compatibility fixes account for those failures; their focused 24 pass
  do not constitute a fresh all-green full-suite run.
- Serial strict query budget, high-concurrency tenant isolation/fairness, real
  model/Host cross-service acceptance and live latency distribution remain open.
  No independently labeled business dataset is available for real semantic
  accuracy acceptance.
