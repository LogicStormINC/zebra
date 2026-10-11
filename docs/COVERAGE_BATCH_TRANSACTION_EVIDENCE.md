# Coverage batch transaction evidence — 2026-10-11

Task COV-EXEC-01; owner Luke Ding / Codex; `codex/cov-exec-01` in the
isolated `cov-exec-01` worktree. Accepted plan:
`COVERAGE_BATCH_TRANSACTION_PLAN.md`. This is component implementation,
**not completion of the full SQL root-cure or a release acceptance**.

## Shared consumer read-phase continuation

The shared CoverageArtifacts.load_payload entrance opts into the existing
readonly bounded Port. Snapshot reads, MODEL checkpoint/policy reads and
publication readback use one prepared reader, not separate guarded get/read/get
calls. Successful context exit is required before returning a usable result.
It checks full lifecycle metadata (including previously missing identities),
retention and fresh authority; normal coalesced object I/O has no database owner.
Already-owned/custom proof contexts retain original per-getter guarded reads,
not a claim of unlocked I/O. Metadata must match its adapter's configured
deployment before any callback/SQL. No permission/lineage cache introduced.
Native incremental MODEL boundaries with the exact native clock have one fresh
guard. Injected clocks remain callbacks and keep a post-callback authority check.
Fresh-fence callbacks, writes and physical/provider I/O guards remain separate.

First smoke13 passed/two failed in30.47s: test replacement mistakenly followed
the new fence, and expiration violated created_at<=retained_until. Corrected
fixture setup (pinned original fence and older created_at), not production checks.
Corrected158 passed43.95s; clock-review correction then160 passed29.30s:
`/tmp/cov-shared-read-smoke.xml`, `/tmp/cov-shared-read-corrected.xml`,
`/tmp/cov-shared-read-final-smoke.xml`. Independent review also identified the
owned-transaction fallback, missing deployment equality and corruption tests
still patching only the original reader. Fixed all three before final validation.
Final shared/verified/prepared/clock48 passed60.51s:
`/tmp/cov-shared-read-final-guards.xml`. Unknown-digest load has2metadata SQL and
2authority callbacks vs prior3/3; known-digest remains2/2. This component test
uses controlled callbacks, not a whole-execution SQL or fleet latency claim.
Fault cases cover exit-time metadata changes, expiration, revoked authority,
original fence replacement, missing-row concurrent insertion, scoped and guarded
fallback byte/digest/metadata corruption, injected clock/fence revocation,
owned-transaction compatibility and cross-deployment refusal before SQL.

Expanded pre-final-source native process was interrupted after42 passed529.43s
when review changed its loaded modules; it is NOT full/final-source validation.
Retained `/tmp/cov-shared-read-native-boundaries.xml`. Final-source critical
MODEL replay/fence-loss, final originals tamper, accepted-batch replay, locked
proof, bootstrap and fleet-boundary85 passed172.48s:
`/tmp/cov-shared-read-final-native.xml`. Local SQLite/snapshot/core compatibility
199 passed3.30s: `/tmp/cov-shared-read-local-compat-final.xml`. A first compatibility
command referenced a nonexistent test file; no tests ran, not a validation pass.
Static size/Ruff/mypy1114/eval30 pass; actual tracked+untracked2612 size checks
and diff check pass. Independent final review found no further actionable issue.
Final-source serial strict `/tmp/cov-shared-read-nine-strict.xml`: independent
certified completion17.57618850s, **10485application SQL**,225GET,4callbacks,
5accepted/qualified batches,one initialization replay/zero exceptional recovery,
same9records117bytes18units/nine MODEL. **<=1000 gate FAIL**. Server15619calls
(13570top/2049nested),inclusive715.32ms non-additive. Client categories sum10485:
business6604,clock1948,reset1419,timeout514. Exclusive phases also sum10485:
outer3834,metadata562,publication1698,executor1387,MODEL1728,commit413,initial6,
continuation243,revalidation240,final374. Common scoped metadata queries now
attribute to their caller, not CloudCoverageArtifacts._record; phase movement
is not saved SQL. Meter scope/qualification/threshold are unchanged.
Earlier4callback/5batch10922 has437more client calls (~4.0%), but elapsed16.4840s
was lower; do not claim latency improvement or a controlled attribution from
two wall-clock runs. The latest previous12180/6batch run has a different shape.
Server still1127lease pins/877lineage reads/1419DISCARD ALL: remaining root is
repeated adapter preparation/guards, not one slow unindexed statement. Whole
plan incomplete: Worker-wide bounded phase entry/exit, final immutable retention
proof outside locks, history/fleet fairness/load/live and independent semantic
labels remain OPEN. Runtime receipts OFF;
no business migration/restart, integration, commit or push performed.

## Native operation transaction continuation

The existing PostgreSQL work-unit now admits exact-owner reentry, including its
typed deadline borrower. A separate socket with the same database/schema cannot
take ownership. Nested adapters cannot commit/reset/reconfigure the owner; a
caught nested failure poisons and rolls back the enclosing operation. Borrowers
still cannot escape scopes or cross threads; a tighter deadline still applies.
MODEL initialize/reserve/settle/state, accepted-batch commit and certification
compose their existing native transaction with nested database adapters. Worker
local authority/tail checks use a short database-only phase, released before
external Host I/O. No authority callback, lease/STOP check, independent original
proof or DISCARD ALL cleanup was removed or cached. Existing locked proof I/O
has NOT been moved out of lifecycle/run transactions; that separate gate remains.
Fleet qualification now includes `exact-owner-short-transaction/1`.

Native operation regression proves two MODEL-policy guard callbacks use the same
backend and exactly one DISCARD ALL, while still making two NEW post-lock lineage
reads. A callback's same-transaction revocation is immediately refused and rolls
back both the revocation fixture and the whole operation. Initial boundary suite
had60 passed/one failure: the test expected CoverageRefusedError, but the actual
storage contract raises ValueError for an invalid Host binding. Corrected only
the exact exception assertion; the two focused operation tests then passed12.01s.
Earlier work-unit/locked-read/MODEL smoke51 passed215.80s. XMLs retained:
`/tmp/cov-operation-boundaries.xml`, `/tmp/cov-operation-transactions.xml`,
`/tmp/cov-operation-smoke.xml`.

Pre-deadline-fix serial strict native measurement, no concurrent native tests:
`/tmp/cov-operation-nine-strict-final.xml`.

| Metric | Operation transaction source |
| --- | ---: |
| Independent certified completion | 16.4840 s |
| Application database calls | **10,922** |
| <=1,000 release gate | **FAIL** |
| Original object GET | 225 |
| Worker callbacks / accepted batches | 4 / 5 |
| Qualified receipts / sealed membership hits | 5 / 5 |
| Initialization replay / exceptional full recovery | 1 / 0 |
| Server calls / top-level / nested | 16,346 / 14,297 / 2,049 |
| Server inclusive execution time | 725.86 ms (nested, not additive) |

Same9records/117bytes/18units/nine MODEL calls. Application categories:
business6772/clock2072/reset1564/timeout514; exclusive phases sum exactly10922:
outer3484,metadata1727,publication1698,executor1099,MODEL1638,commit413,
initial6,continuation243,revalidation240,final374. Previous source16.0781s10806
had four accepted batches, not five: no fixed-batch gain/regression or p95 claim.
The short-unit composition removes redundant owner sockets but does not remove
the repeated guarded adapter entries; whole execution still misses its gate.
Server fingerprints confirm1251 lease pins,1001 post-lock lineage reads,
1640 BEGIN/1647 COMMIT and1564 DISCARD ALL. Inclusive server work725.86ms is
far below measured16.4840s; nested time overlaps and is not a latency budget.
The unresolved root is execution-phase protocol/adapter fanout, not a missing
index on a single slow query. Fresh authority at actual external-access and
mutation boundaries must be preserved when reducing these entries.

Two earlier metering attempts are NOT performance evidence: one lacked the test
database's pg_stat_statements extension, another detected statistics eviction.
Created the extension and increased ONLY the disposable test database capacity
to50000, restarted ONLY that test container, then ran the strict test above.
The meter remains fail-closed on resets/evictions, and the application measurement
boundary still includes failed attempts, handoffs, cleanup and final proof.
No business schema/configuration/service changed. Actual fleet/MinIO/provider/
Trench latency, independent semantic labels and the full root cure remain OPEN.

Read-only review found one P2: an older deadline wrapper inside a borrower could
reinstall its longer SQL timeout after a newer shorter wrapper. Shared
RecoveryDeadlineConnection.execute now enters the existing minimum-deadline
ContextVar around configuration/delegation/checks/cursor creation. Owner identity
and rollback remain unchanged. A native positive-deadline regression uses a20s
owner/0.2s nested budget and pg_sleep(3), requiring server cancellation in<2s,
not a late post-query refusal; it also checks rollback of the preceding insert.
Work-unit/recovery/report/API/operation suite51 passed28.65s before adding that
explicit insert assertion; final rerun is recorded below. MODEL acceptance/final
proof/batch replay/core execution suite56 passed602.66s before the deadline fix.
Read-only re-review found no further actionable issue; not live concurrency GO.

Final-source serial strict `/tmp/cov-operation-deadline-nine-strict.xml` retains
the same complete boundary: certified23.4505s, **12180application calls**,
18052server(15950top/2102nested),248GET,5callbacks/6accepted-qualified batches,
six membership hits,one initialization replay/zero exceptional recovery/nine MODEL.
SQL<=1000 **FAIL**. Business7482/clock2275/reset1737/timeout686; exclusive phases
sum12180: outer4251,metadata1883,publication1756,executor1143,MODEL1638,commit477,
initial6,continuation324,revalidation320,final382. Inclusive server979.25ms is
nested/not additive. Callback/batch shape differs from both the earlier4/5 run
and4/4 baseline; no speedup or p95 claim, and all failed measurements retained.
The deadline repair is a correctness fix, not evidence that the SQL gate is met.
Final deadline/work-unit/recovery/report/API/operation regression51 passed27.71s
with the explicit deadline-interrupted insert rollback assertion included:
`/tmp/cov-operation-final-deadlines.xml`. Earlier51-pass and56-pass results are
retained with their source boundary above, not conflated with this final run.
Final make check: Ruff/Mypy1114-source/eval30 GO; actual tracked+untracked2611
file limits and diff check GO. Removed only this run's disposable PostgreSQL
container and anonymous volume, verified both absent; XMLs retained. No business
data/schema/runtime or primary checkout changed. Task remains In Progress.

## Execution context and native canonical finalization continuation

- Native finalization no longer loops through generic append/finalize adapters.
  It locks the exact batch once, validates current authority and recorded receipts,
  CAS-advances the stream, set-inserts one canonical Event per object, set-updates
  all lifecycle bindings, and set-inserts individual mutation audit hashes.
  The whole delta rolls back on interruption; retry preserves finalized objects.
  Exact post-callback Event/lifecycle validation remains mandatory.
- Optional bounded readonly execution scope uses one entry and one exit metadata
  page, with fresh authority at both boundaries, exact full-record comparison,
  <=1000 unique identities/32MiB and escaped-reader refusal. No transaction spans
  physical I/O. Executor source bytes, prior observations and report pages opt in;
  runner/MODEL calls and writes occur only after successful exit. Local fallback
  and oversized record fallback retain their previous individually guarded reads.
- Known pure locked proof prefetches <=1000 lifecycle identities and corresponding
  canonical Events per page: two queries for 1 or 9 exact proofs, including repeat
  reads. Both Event ID and URI lookup are retained; conflicting foreign/session
  Events are not filtered out. Full pinned metadata, per-object Event/fence/hash,
  exact bytes/digests and original final proof remain independently validated.
  Unknown callbacks cannot enable reuse. Cache cap8192 identities falls back to
  original native proof, not skipped verification. Scope exit clears all pins.
- Migration94 adds exact deployment/URI materialization lookup; the fleet digest
  distinguishes batched native Events, readonly execution scope and proof pages.
  Source validation is separate from operator migration/rebuild/activation.
- Initial native finalization publication25 passed. Prepared execution reads,
  batch publication/fault/race cases, bootstrap and MODEL composition76 passed
  in254.66s. Earlier expiry fixture violated the existing retention constraint;
  corrected its creation time, not the constraint. Replacement test now uses the
  captured original fence. Concurrent retry test waits for the winning commit
  before its fresh-snapshot retry; production typed conflict is unchanged.
  A mistaken test filename ran no tests and is not validation evidence.
- Pre-prefetch complete strict run `/tmp/cov-context-batch-nine-strict.xml`:
  independent certification completes; SQL gate **FAIL**, 12,571 application
  calls,20.4653s execution,247GET,5 callbacks/6 qualified batches,9 MODEL calls,
  one initialization replay/zero exceptional full recovery. Server18,557
  (16,461top/2,096nested),992.76ms inclusive DB execution; nested time overlaps.
  Application categories: business7,813/clock2,275/reset1,797/timeout686.
  Exclusive phase counts sum exactly: outer4,275, metadata1,883, publication1,756,
  executor1,143, MODEL1,680,commit560,initial6,continuation324,revalidation320,
  final624. This is not comparable to the earlier four-callback11,772 run as a
  fixed-workload gain. Wall time is predominantly protocol/adapters rather than
  server query execution; proof batching alone cannot meet the release gate.

Native proof/fault/regression74 passed in585.39s; index/fleet37 passed29.90s.
Locked exact lifecycle/Event queries `[2,2]` for1/9 evidence; execution scope
`[6,6]`; batch reserve/receipt/finalize phase counts `[6,6]/[8,8]/[8,8]`.
XMLs: `/tmp/cov-context-batch-regressions.xml`, `/tmp/cov-prefetch-native.xml`,
`/tmp/cov-prefetch-index-fleet.xml`. These fixtures use actual isolated PostgreSQL
and controlled S3/Host/MODEL transports, not real MinIO/provider/live throughput.

Final-source serial complete strict measurement:
`/tmp/cov-context-prefetch-nine-strict.xml`; no other native workload running.

| Metric | Current source |
| --- | ---: |
| Independent certified completion | 16.0781 s |
| Application database calls | **10,806** |
| <=1,000 release gate | **FAIL** |
| Original object GET | 218 |
| Worker callbacks / accepted batches | 4 / 4 |
| Qualified receipts / sealed membership hits | 4 / 4 |
| Initialization replay / exceptional full recovery | 1 / 0 |
| Server calls / top-level / nested | 16,273 / 14,262 / 2,011 |
| Server inclusive execution time | 648.36 ms (nested, not additive) |

Same nine records/117 bytes/18 units/nine MODEL calls. Application breakdown:
business6646/clock2041/reset1605/timeout514. Exclusive phase counts sum10806:
outer3502,metadata1719,publication1640,executor1073,MODEL1674,commit343,
initial6,continuation243,revalidation240,final366. Repeated post-lock lineage991,
lease pins1234 and DISCARD ALL1605 show unresolved Worker-wide phase authority/
transaction fanout. Never merge the lock and post-lock authority snapshots into
one pre-wait read, suppress tenant cleanup, or relax the whole execution meter.
Prior sealed same-nine/four-callback/four-batch18.2650s12916 provides an observed
2110-call/2.187s reduction, but source shape changed and these are single runs,
not p95/production latency or the root-cure gate. The 20.4653s12571 pre-prefetch
run had five callbacks/six batches and is not a fixed-callback gain comparison.
All failed gates remain retained; partial savings never substitute for acceptance.

Final-source boundary/retry/merge/revocation/Worker/migration suite42 passed,
one failure exposed the inherited hardcoded migration list stopping at78
(`/tmp/cov-context-final-source-boundaries.xml`,102.39s). Updated explicit79-94
expectations only, preserving concurrent idempotency/checksum/epoch and all
schema assertions; all6 native migration tests then passed3.23s
(`/tmp/cov-context-migrations.xml`). No migration ran against a business database.

Final pure executor/batch/report/verified-read regression60 passed3.37s
(`/tmp/cov-context-pure.xml`). Final `make check` passed Ruff, Mypy1114 source
files and30 deterministic eval cases. These checks do not override the failed
whole-execution SQL gate. The isolated native PostgreSQL test container and its
anonymous volume were removed after validation; business services/data untouched.

## Implemented

- Optional core immutable batch Port is composed into the actual Cloud executor:
  <=1,000 unique objects / <=32MiB per publication. Buffer <=999 observations
  plus the result Artifact, <=16MiB observation bytes; flush parts before merges.
  Validate complete ordered returned metadata before accepting units. Legacy/local
  single publication remains supported, including deterministic singleton IDs.
- Native reservation is a scoped, locked selected-key query plus one JSONB set
  insert; verified receipt settlement is one scoped selected-key query, one set
  update and one mutation-ledger insert, not a loop of guarded transactions.
  The 1-object and 9-object test asserts identical phase query counts. Missing
  rows cannot be locked: concurrent inserts use ordered ON CONFLICT DO NOTHING;
  a partial insert rolls the whole delta back as a typed conflict, requiring a
  fresh authority/snapshot retry and exact immutable identity revalidation.
- Upload and exact-version physical byte verification have no database work unit.
  Verified receipts settle atomically, then canonical per-object Events and all
  new finalizations commit together in a separate fresh-fence transaction.
  Post-callback exact batch/Event revalidation prevents a callback mutating rows
  inside the borrowed transaction. Competing legal lifecycle advancement is a
  retry conflict, not accepted stale evidence; identity/byte mutation refuses.
  At this prior slice per-object Event/finalization SQL remained linear; the
  execution-context continuation above replaces it. Final certification still
  performs independent originals under locks and is not optimized away here.
- MODEL checkpoints and usage settlement stay immediate. Native tests interrupt
  observation publication before it starts and after its acknowledgement is lost,
  replace the Worker, resume and certify: one HTTP request and unchanged exact
  usage/charge receipts in both cases. Fleet continuation qualification includes
  `bounded-set-reservation-receipt-atomic-finalize/1`; old record-seal-only
  consumers cannot match. Locked proof readers explicitly refuse batch writes.
- Core executor commits bounded exact unit batches: parts flush before merges,
  failed derivation does not commit an incomplete batch, and deterministic
  original observations remain reusable after interruption. Cloud opts in;
  default local behavior remains unchanged. Native acceptance updates exact
  delta keys with one statement; a partial/duplicate match rolls back.
- Trusted native proof adopts the owner's exact transaction. Nested metadata
  adapters cannot commit, roll back, close, change schema, escape scope or cross
  threads. Direct deadline connections allow only the actual bounded timeout
  suffix, not arbitrary libpq options. Final Artifact publication borrows its
  existing transaction; this does not move external I/O outside final locks.
- Known pure proof phases pin complete native lifecycle records and check current
  authority on entry and exit. Exit revocation refuses before acceptance/commit.
  Public readers and arbitrary callbacks retain physical pre/post-I/O guards.
  Retention, identity, exact object version and byte digest remain checked.
  No TTL permission cache, cross-phase grant reuse or skipped final originals.
- Existing verified-reader Port returns metadata and bytes together. Executor
  uses it for known frozen digests instead of a preliminary getter plus read.
  Legacy readers retain their previous independently validated path.
- Migration91 maintains MODEL source/original byte bounds with the native Event
  transitions. Qualified incremental volume preflight reads one scoped root
  plus current policy; metadata mutation invalidates volume without erasing
  charges. Legacy, malformed, incomplete or invalidated roots use full proof.
  Even before the first accepted batch, qualified budget preflight can avoid
  replaying every object; independent final certification stays mandatory.
- Migration92 adds deployment/tenant/run/exact-key lookup indexes. A 5,000-row
  synthetic EXPLAIN ANALYZE case uses these indexes rather than a sequential
  scan. This is query-plan evidence, **not fleet load**.
- Migration93 seals exact ordered unit membership and full record metadata from
  the validated original manifest at first bind. Native guarded transitions
  verify separate SHA256 chains for exact keys and ordered record/part metadata;
  selected record lookup is bounded to the commit's <=1,000 keys. Exact JSONB
  equality remains mandatory on the fixed-size indexed part candidate. MODEL
  reservation and first settlement bind canonical source Events and consume each
  exact part once. Unsupported mutation invalidates the root transactionally;
  rollback restores it, repair/rebuild cannot silently reseal existing history.
- Qualified `final_certification` normal commit/retry uses the sealed expected
  count/digest, selected records and exact current-batch source proof. No full
  original manifest parsing or all-key SQL parameter upload in this path. Legacy,
  eager, arbitrary derivers, exceptional recovery and final certification retain
  full independent proof. Original manifest bytes can become corrupt after seal;
  incremental retry may proceed, but independent final certification refuses.
  This is the explicitly approved deferral, not an immutable-retention claim.
- Worker qualification includes volume/91, bounded acceptance, operation proof
  authority, delta indexes/92 and sealed exact membership/93. Fingerprint-only,
  revision-only, v90-only, volume-only and indexed-only consumers cannot match
  the new qualification digest. The intermediate unit-only93 composition is
  also rejected; current qualification explicitly includes sealed record metadata.
- Workload counter includes Connection.execute, Cursor.execute and executemany,
  reset/timeout statements, failure paths, handoffs and final certification.
  Frozen fingerprints must sum to the exact application counter. Optional
  `pg_stat_statements.track=all` separately measures top-level and nested work;
  reset/eviction makes that evidence fail rather than silently undercount.
  Strict SQL release mode fails when the complete path exceeds 1,000 calls.

## Prior sealed-membership native nine-record measurement

Controlled nine records, 117 input bytes, 18 accepted units, nine controlled
MODEL calls; 2-second work-slice setting. Setup is outside the execution timer;
the endpoint is independent final certification. All execution handoffs,
connection resets and final verification stay inside the old boundary.

| Metric | First record-seal run | Serial repeat |
| --- | ---: | ---: |
| Certified completion | 21.3039 s | 18.2650 s |
| Application database calls | **14,371** | **12,916** |
| SQL target | <=1,000 — **FAIL** | <=1,000 — **FAIL** |
| Object reads | 242 | 218 |
| Worker callbacks | 5 | 4 |
| Accepted batches / qualified receipts | 6 / 6 | 4 / 4 |
| Sealed membership reads / qualified roots | 6 / 6 | 4 / 4 |
| MODEL initialization full replays | 1 | 1 |
| Exceptional full recovery transcripts | 0 | 0 |
| Server statements | 21,134 | 19,132 |
| Server top-level / nested statements | 19,005 / 2,129 | 17,096 / 2,036 |

Result file: `/tmp/cov-membership-records-nine-strict.xml` (ephemeral evidence).
Repeat: `/tmp/cov-membership-records-nine-strict-repeat.xml`. Both tests failed
on SQL budget, not business certification. Same-four-callback prior unit-only
seal had12,912 calls: the selected-record query adds one per accepted batch,
four in this run. No overall query-count or latency improvement is claimed.
Business certification assertions passed; the **test failed** on the SQL budget.
Server BEGIN/COMMIT and implicit/internal work are included in server totals;
these totals are not interchangeable with explicit application method calls.
Nested execution times overlap callers and must not be added as wall time.

Earlier observations retained, not selected as the only favorable result:
v92 18.0889s/12,912 calls/218 GET/4 callbacks/server18,823; initial v93 unit-only
seal 19.0184s/12,912 calls/218 GET/4 callbacks/server19,198. The latest record-seal
first run has another continuation and two more acceptance batches; it is NOT a
fixed-callback latency or SQL saving comparison. Seal qualification 6/6 and
repeat4/4/zero all-key SQL uploads establish the component path, not the target.
v3 20.8706s/14,945 calls/244 GET/5 callbacks; v4 17.8327s/13,480 calls/
225 GET/4 callbacks. Latest is not faster than v4. Historical v90
30.5219s/20,403 counted Connection.execute only, so it is **not** a strictly
comparable all-client-call baseline. None of these single runs proves p95,
real-provider latency, Trench E2E or production multi-tenant throughput.

Strict reproduction, using an already configured **isolated test** DSN:

```sh
ZEBRA_COVERAGE_SERVER_SQL=1 ZEBRA_COVERAGE_ENFORCE_SQL_BUDGET=1 \
uv run pytest -q --tb=line \
  'tests/worker/test_coverage_work_load.py::test_native_normal_work_slices[verified-metadata-receipt-budget-scoped-batches-verified-load-native-atomic-2000-incremental-first_create]' \
  --junitxml=/tmp/cov-batch-root-nine-strict.xml
```

Do not use a business database, reset shared statistics, run concurrent workload
tests against the same observation instance, or omit strict mode for release.
Diagnostic mode records the same budget failure without asserting it; it is not
a release gate. Own ephemeral PostgreSQL had statistics capacity increased to
100,000 after the initial strict run correctly rejected eviction evidence.

## Regression evidence

- Current record-seal/native membership, ordinary storage and index regression:
  **44 passed**,104.08s, `/tmp/cov-membership-records-native.xml`.
- Expanded record tamper/final original corruption/rollback/legacy/duplicate
  settlement guards and 5,000-row exact part/selected-record lookup plans:
  **19 passed**,89.56s, `/tmp/cov-membership-records-boundaries.xml`.
  The unsupported-record mutation test initially restored the wrong ordinal;
  the test was corrected, not the database nonnegative constraint weakened.
- Current pure verifier/bounded batch/operation reader/server SQL meter: **65
  passed,20 skipped**,0.75s. Skips are environment-gated native checks, not passes.
  Current static gate: Mypy1,108 sources/Ruff/eval30/tracked size passed;
  tracked+untracked2,600 actual path size and `git diff --check` passed.
- The earlier unit-only v93 broad native matrix was **92 passed**,633.42s;
  this is prior component evidence, not the current record-seal full matrix.
- Expanded current MODEL/receipt/publication/readiness/recovery matrix initially
  had **94 passed,11 failed**,653.47s. One failure was the already corrected
  ordinal-restoration test; ten were a stale shared recovery fixture patching
  `effect_input` in its former module after authority extraction. Patch the actual
  authority module, keep its independent binding/time fallback; no production
  recovery guard is relaxed. All eleven are covered by corrected focused reruns:
  membership19 above, plus **46 passed**,24.87s, recovery transcript/native bounds/
  updated unit-and-record consumer readiness,
  `/tmp/cov-membership-recovery-fixture-corrected.xml`. The initial broad failure
  remains recorded; this is composed regression evidence, not a fresh full run.
- Compatibility: program-only binds do not persist MODEL sealed-record metadata;
  original batch retry plus qualified MODEL selected proof remain valid. **3
  passed**,9.33s, `/tmp/cov-membership-ordinary-compatibility-corrected.xml`.
  An initial new test mislabeled its existing MODEL fixture as program-only;
  replaced that assumption with an explicit program contract/digest fixture.
- MODEL candidate volume/summary and receipt initialization: **30 passed**,
  289.62s, `/tmp/cov-batch-root-model-regression-v5.xml`.
- Worker readiness/native capability admission: **55 passed**, 36.49s,
  `/tmp/cov-batch-root-fleet-regression-v5.xml`.
- Pre-first-commit budget, volume root/history growth and final proof boundaries:
  **10 passed**, 95.38s, `/tmp/cov-batch-root-growth-boundaries-v5.xml`.
  Adding 1,000 non-MODEL history Events leaves normal volume preflight at two
  queries; this does not establish MODEL-history or full-workflow constant cost.
- Native query-plan cases and adopted transaction cases passed. Independent
  publication observer runs on another thread/connection, sees committed state,
  and verifies revocation rolls the owning publication transaction back.
  A nested same-thread adapter now intentionally sees the owning transaction.
- Pure executor/verified readers/batches/locked proof/volume scope/server meter:
  **143 passed**, 2.63s. Static gate: Mypy 1,106 sources, Ruff, tracked file-size
  checks and eval30 passed. Actual tracked+untracked 2,597-path size check passed.
- Two initial regression expectation mistakes were corrected, not production
  gates removed: invalidated ledger must fall back to physical proof (not zero
  reads); a nested borrowed adapter is not an independent publication observer.
  Expired metadata fixtures now satisfy created-at/retention database constraints.

## Governed Artifact batch measurements and regressions

Same complete execution timer, same serial native PG and controlled S3/MODEL;
failed budget assertions are retained rather than converted into passing tests.

| Metric | Set-based receipts | Final batch revalidation | Current race-safe repeat |
| --- | ---: | ---: | ---: |
| Certified completion | 19.5519 s | 23.0696 s | 19.6260 s |
| Application calls | 11,582 | 13,031 | 11,772 |
| Server statements | 17,212 | 19,188 | 17,472 |
| Top-level / nested server | 15,140 / 2,072 | 17,023 / 2,165 | 15,361 / 2,111 |
| Object reads | 218 | 247 | 225 |
| Worker callbacks / accepted batches | 4 / 4 | 5 / 6 | 4 / 5 |
| SQL target <=1,000 | **FAIL** | **FAIL** | **FAIL** |

Files: `/tmp/cov-artifact-batches-nine-strict.xml` and
`/tmp/cov-artifact-batches-final-nine-strict.xml`; current final-source repeat
`/tmp/cov-artifact-batches-current-nine-strict.xml`. Matched-four-callback client
saving is1,334 (~10.3%); elapsed time is worse than18.2650s, not a latency gain.
The five-callback run is not comparable with the four-callback baseline without
that qualification. Exact boundary includes handoffs, reset SQL and final proof.
Current final-source repeat saves1,144 calls vs12,916 (~8.9%) with four callbacks
but five accepted batches instead of four; this is not fixed-batch/p95 evidence.
Clock2,141/reset1,671/timeout514/business7,446 sum11,772. Exclusive current counts:
outer3,547, initial6, metadata2,098, publication1,974, executor872, MODEL1,674,
commit498, continuation243, revalidation240, independent final620; sum11,772.
431 metadata facade entries and26 publication entries remain. Current qualification
5/5, one initialization full replay, zero exceptional full recovery, nine MODEL
calls and independent certificate complete. The test still fails on SQL budget.

Current native batch/Worker/readiness/locked-reader suite:124 passed76.05s.
Native MODEL/crash/charge/original tamper/independent-final proof:23 passed253.31s.
Native new buffered publication/replacement replay:2 passed31.65s. Controlled
transports, not real provider/MinIO/browser acceptance. Pure executor/read/report/
Artifact checks:88 passed8 native-gated skips5.03s; the native locked-reader tests
are separately in the124. Current make check Ruff/Mypy1110/eval30 passed after
the final buffer-replay test addition.
Actual tracked+untracked file-size check2604 passed; git diff --check passed.

Failures corrected, not counted as passing evidence: initial removed fixture
import / bad zero-index event sequence / bootstrap receipt-fault target; subsequent
expanded135 pass1 true concurrency failure (unique reservation key), fixed by
whole-delta conflict rollback. Two buffer-replay fixture failures traced missing
native body import and Source-vs-Adapter confusion; use the actual Host adapter
with governed Cloud Artifacts, not fabricated body references. The corrected
native two-case execution proves the real buffering/charge/replay path.

## Why the SQL goal still fails

First record-seal run explicit fingerprints: 2,169 DISCARD ALL, 1,634 lease/epoch pins,
1,322 fresh lineage/binding/STOP reads, 900 standalone clock reads,
582 metadata getters, 686 timeout configuration calls, 463 Event-tail reads.
An operation still composes repeated Artifact getters and lifecycle transitions,
each entering its own authority/transaction path. Indexed queries are individually
small, but their multiplicity dominates. Trigger SQL is real additional work.
Sealed membership and reservation/receipt batches are component-verified. Bulk
reads/authority and per-object Event/finalization fanout remain; adding more
indexes alone cannot meet this gate. Prior exclusive (non-nested)
phase SQL attribution sums to the exact 14,371 calls:

| Exclusive phase | Application calls |
| --- | ---: |
| Worker handoff/authority/other | 4,318 |
| Artifact metadata reader | 2,542 |
| Artifact publisher | 2,800 |
| Executor outside nested phases | 1,204 |
| MODEL invocation outside nested phases | 1,674 |
| Batch commit | 559 |
| Initial preparation | 6 |
| Continuation preparation | 324 |
| Prepared-read revalidation | 320 |
| Independent final lifecycle proof | 624 |

These categories expose fanout; collapsing meters or excluding handoffs cannot
be used to meet the gate. Most remaining calls are not the membership predicate.
Serial repeat exclusive counts: outer3,545, initial6, metadata2,343,
publisher2,676, executor1,139, MODEL1,674, commit434, continuation243,
revalidation240, final616; sum12,916. Artifact read/publication5,019 dominates
membership/commit, confirming the same structural next target.

## Remaining required implementation — NOT complete

1. **Execution manifest/history growth acceptance.** The sealed normal commit
   path is implemented; executor initialization and independent exceptional/final
   proof still read full original data. Validate bounded execution pages and
   MODEL-history growth across processes; current synthetic selected-key tests
   are not a full native fleet scale or constant-cost whole-execution proof.
2. **Complete batch governed evidence lifecycle.** Bounded set reservation and
   receipt settlement plus atomic finalization are implemented. Canonical Event
   append/audit/finalization now uses set statements. Bounded readonly execution
   and locked proof pages are implemented; whole-Worker authority/transaction
   fanout is still unresolved. Artifact publication and coverage acceptance remain separate durable
   transactions: interruption leaves reusable unaccepted evidence, not a false
   accepted result. Preserve that recoverable law or prove stronger composition
   before combining them; do not claim whole lifecycle constant SQL yet.
3. **Short final certification transaction.** External original reads still
   occur under native run/lifecycle locks, including the post-append proof.
   Exact-version immutable retention evidence is required before moving those
   reads out. Versioning alone is not retention; do not drop the second read.
4. **Fleet-scale execution.** Checkpoint/re-admission separation, shared opaque-
   tenant quotas/backpressure, fair scheduling and real native multi-tenant
   p50/p95/lock/connection-wait workload acceptance remain open.
5. **Release/live closure.** Apply migrations to an authorized test deployment,
   rebuild/restart by the agreed operator process, validate live Trench streaming
   and execute faults/cancellation/owner replacement across processes. Independent
   labeled semantics are unavailable; controlled cases are not business accuracy.

No primary-checkout edit, business migration, service restart, activation,
commit, merge or push. Runtime receipt activation remains OFF. Task In Progress.
Earlier disposable `zebra-cov-sql-native-20261011` was removed. Owned disposable
`zebra-cov-membership-native-20261011` was also removed after all native tests
finished. Only generated test databases were discarded; XML results remain in
`/tmp`. Business databases, volumes and pre-existing containers are untouched.
Own batch-test `zebra-cov-artifact-batch-native-20261011` and its generated anonymous
PostgreSQL volume were removed after every native/meter session completed.
The temporary test DB is discarded; all cited XML files remain. No live service
or reusable business volume was deleted.
