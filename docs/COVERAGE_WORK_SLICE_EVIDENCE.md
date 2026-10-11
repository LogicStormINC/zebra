# Coverage work-slice performance evidence — 2026-10-10
Status: bounded component validation; performance/SLO acceptance is not GO.
Branch/worktree: codex/cov-exec-01; no integration, activation, restart or push.

## Qualified atomic continuation comparison — 2026-10-11

Reused frozen native9 records/117bytes/18 unique batches/9 controlled MODEL HTTP
requests/one certificate. Actual scratch PG/Worker; synthetic Host/model/S3.
First handoff after fixture setup to certified completion, four cases serially;
not repeated p95, live E2E, real business accuracy or mixed-tenant acceptance.
XML /tmp/cov-atomic-frozen-load-20261011.xml:4 passed205.97s, zero skips,
4 eager cases deselected. Loaded before later explicit qualified-receipt assertions.

| Receipt route / slice | Seconds | Execute calls | GET | Recovery constructors | Callbacks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Off / 2s |66.6344|75984|1997|27|10|
| Qualified / 2s |50.5764|63584|907|0|10|
| Off / 60s diagnostic |37.7172|45010|717|0|1|
| Qualified / 60s diagnostic |34.7905|45226|717|0|1|

Execute calls count Connection.execute only, excluding cursor API and implicit
BEGIN/COMMIT/ROLLBACK. Handoff includes fresh fixture consumer lifecycle and
qualification, not pure production pickup. GET excludes bytes/other operations.
Recovery constructors exclude commit replay and independent final verification.
Inclusive nested phase times are NOT additive. Qualified2s public _record2343/
23.2394s, commit18/5.1344s, normal preparation27/1.0558s, final verification2/
2.7112s. Full recovery is eliminated here; SQL/time targets remain far unmet.
60s diagnostic adds216 executes for18 receipts and changes no GET count; do not
attribute timing noise to faster execution without repeat observations.
Remaining root work: shared Artifact/authority fanout and native commit MODEL
history replay, qualified fingerprint scaling, rollout and mixed-tenant acceptance.
Hardened qualified2s passed67.92s, zero skips/7 deselected:
/tmp/cov-atomic-frozen-load-hardened-20261011.xml. Actual18qualifiedreceipts,
zero recovery constructors, one cert,9 MODEL HTTP;62.3807s/65682execute/929GET/
11callbacks. Time slicing varies with environment; retain this slower observation,
not just the first faster result. No production receipt activation.

## Implemented

- Configured Worker work slices: 32 units, 8 MiB input, 2 seconds by default.
  ZEBRA_COVERAGE_WORK_UNITS, ZEBRA_COVERAGE_WORK_INPUT_BYTES and
  ZEBRA_COVERAGE_WORK_MILLISECONDS configure scheduling, not admission budgets.
  Each accepted unit still commits independently; finish the first legal unit
  to avoid starvation, then yield before another unit exceeds the slice target.
  Dependencies, cancellation, current authority and model budgets remain checked.
- RR READ ONLY preparation reuses exact SELECT results within one invocation.
  Private serialized results prevent caller mutation; 32 MiB serialized capacity
  falls back to native reads. This is not a total process-memory ceiling.
  Clock reads remain fresh. Before finalization, release cached rows and replay
  every original native query with exact multiset digests and original row locks.
- Statement and lock timeout configuration share one native statement. Final
  revalidation applies one deadline wrapper, rather than recursively configuring
  timeouts around another timeout configuration. Earlier deadlines always win.
- Production Worker binding lookup previously called ensure_for_session,
  rebuilding Task/Segment/event indexes during every authority read. Its new
  Session loader checks the root projection, exact native handoff lineage and
  latest binding in one RR read-only transaction. No cached binding or mutation.
  Old explicit admission/rebuild paths remain unchanged. The controlled load
  fixture has a simplified binding loader, so these timings do not measure the
  improvement from this additional production wiring repair.

## Controlled nine-record measurements

Every run uses nine bodies native part 0..8, each 13 bytes, total 117 bytes.
Each record has part + record_merge: 18 accepted units and nine preset clear
model replies. Worker and PostgreSQL are real; Host/model/S3 transports are
controlled. Fixture admission/setup excluded; first handoff through certified
completion included. SQL execute includes business, clock, timeout and reset.

| Run | Work target | Callbacks | Certified seconds | SQL execute | Object GET |
| --- | --- | ---: | ---: | ---: | ---: |
| Previous proof-read baseline | one unit | 18 | 261.70 | 224929 | 3521 |
| Initial slice | 2s | 15 | 183.66 | 195050 | 3246 |
| Initial diagnostic | 60s | 1 | 96.73 | 98296 | 1062 |
| RR row reuse | 2s | 14 | 167.22 | 180491 | 3089 |
| RR diagnostic | 60s | 1 | 73.45 | 98296 | 1062 |
| Final timeout + timing instrumentation | 2s | 14 | 180.50 | 178760 | 3173 |
| Final diagnostic + instrumentation | 60s | 1 | 69.96 | 98296 | 1062 |
| Coalesced first-read guards | 2s | 12 | 154.12 | 162309 | 2831 |
| Coalesced guard diagnostic | 60s | 1 | 75.30 | 98296 | 1062 |
| Active-lease preflight | 2s | 11 | 144.69 | 152882 | 2534 |
| Active-lease diagnostic | 60s | 1 | 99.53 | 98296 | 1062 |

Single-machine measurements vary; instrumentation and slice boundaries also
change workload. These are individual observations, not p50/p95 or live E2E.
Do not call the 60-second diagnostic the default, or increase defaults to hide
normal continuation overhead. Final default measured SQL counts: business 99938,
reset 60836, clock 13900, timeout configuration 4087.

Final default nested phase timers: preparation 41 calls / 59.08s;
CloudCoverageArtifacts._record 25110 / 137.66s; commit 18 / 21.44s;
final native revalidate 26 / 2.44s. Timers are inclusive and NOT additive.
The one-callback diagnostic still has 6241 _record calls / 57.88s and 98296 SQL
execute calls. Changing work granularity alone cannot meet the target.

Raw evidence is under evals/coverage_acceptance/worker-work-slice*.xml. Safety
selection work-slice-native-safety-20261010.xml: 73 passed / 3 load deselected,
zero leaked scratch schemas; this precedes the final binding missing-root repair.
Final binding and full-source gates are recorded separately; do not substitute
earlier gates for that final source. Keep the earlier default-suite process-tree
PermissionError evidence rather than silently overwriting it.

Final read-only binding source: work-slice-native-binding-final-20261010.xml,
five passed in 26.29s, zero leaked scratch schemas. Includes an actual Worker
certification using fresh native binding reads, latest renewed grant visibility,
invalid handoff refusal, non-mutating indexes and missing root projection refusal.
Earlier binding XML retains the regression-fixture FK setup error; repaired
fixture removes mutable indexes first, retaining binding/Events and all constraints.

Final frozen-source default suite: 6736 passed / 1542 prerequisite skips in126.55s
(work-slice-final-source-suite-20261010.xml). Separate native safety73 and final
binding5 passed; instrumented load2 passed. Ruff, Mypy1083, tracked size2382 and
eval30 passed; new untracked source/test/docs lengths also checked manually.
Independent source review GO applies only to this bounded slice, not the SLO.

## Guard fanout follow-up (2026-10-10)

RecoveryArtifactReads first-read path previously surrounded a facade read with
another pair of _record calls: four fresh authority/metadata guards for one I/O.
The adapter now shares its immediately checked pre-read record with the facade's
internal physical-read method; that method performs the fresh post-read guard.
Cold reads use two guards; cached reads still use two. No authority TTL/cache,
cross-callback proof reuse or continuation protocol change. Bounds, native snapshot
comparison, digest/size validation and independent final object rereads remain.
Tests use the actual facade method rather than a replacement read helper. Native
adapter checks use an ordinary transaction, proving guard composition; separate
preparation gates establish the RR READ ONLY/final-revalidation boundary.
Scoped source review GO is not performance/SLO or real-service acceptance.
Controlled load: two passed in237.84s, zero fixture schemas, raw XML
artifact-guard-load-20261010.xml. Default single observation improves180.50 to
154.12s, with changed slice boundaries (14 to12 callbacks); not isolated p95.
Default business91157/reset54666/clock13064/timeout3423 executes; nested _record
20262/118.31s, prepare35/40.32s, commit18/20.76s, revalidate22/1.92s. Inclusive
timers overlap. One-callback diagnostic75.30s versus69.96s has unchanged98296 SQL
and1062 GET: no improvement on that path. Keep the negative result; this slice
does not fix steady-state commits or normal-continuation full-history scans.
Default suite before the native fixture repair:6736 passed/1544 skips122.92s
(artifact-guard-final-suite-20261010.xml); Ruff/Mypy1083/size2382/eval30 passed.
Concurrent fault selection retained46 passed/one WorkerCapabilityLostError at
handoff, zero schemas (artifact-guard-native-final-20261010.xml). This is not a
passing fault matrix; serial reproduction and its outcome are recorded separately.
Serial reproduction:46 passed/one identical capability refusal50.05s, zero
schemas (artifact-guard-native-serial-20261010.xml). Manual native_handoff did
not run a continuous process heartbeat but reused its initial30s capability
across many callbacks. Shared fixture now closes the old capability and qualifies
a fresh actual consumer per manual handoff, matching normal-load replacement.
No production TTL or permission gate relaxed; revoked capability audit rows remain.
Repaired native-enabled selection:58 passed/zero skips231.01s, zero schemas
(artifact-guard-native-repaired-20261010.xml). Includes pure adapter regressions
and native preparation/continuation/crash/tamper/final physical deletion/bytes
cases; not all58 are native tests. Keep both earlier failed fixture runs.
Final source default suite after fixture repair:6736 passed/1544 prerequisite
skips122.39s (artifact-guard-final-source-20261010.xml); Ruff/Mypy1083 clean.
Tracked source-size gate2382 and manual changed/untracked lengths passed;
eval release30/30 passed. Source review GO is scoped, not latency/SLO GO.

## Active-lease recovery preflight (2026-10-10)

Recovery previously prepared full proof before discovering that the current
Worker lease was active and only deferring the command. A fresh native read-only
active hint now selects a short deny-only preflight. In a savepoint it takes the
original lease-boundary/epoch/lease lock order, then conditionally updates only
the scoped live pending command's retry timestamp by the existing60s delay.
Epoch, unreleased/unexpired lease, due time and enabled rollout must all match.
No approval, receipt, proof or outbox is written. A miss rolls back/releases the
savepoint before external preparation; fenced continuation retains full proof.
Inactive hints bypass the extra lock round, preserving existing advisory queue
ordering. This does not implement the normal-continuation fast protocol.

Native preflight + original recovery suite:58 passed49.24s, zero scratch schemas
(active-lease-native-final-20261010.xml). Tests prove no preparation on an
active lease, scope/epoch/release/expiry/fence fallback, secondary-connection
NOWAIT/advisory lock availability at preparation, retry-page fairness and both
original refresh/expiry and advisory-queue races. Scoped independent source GO.
Preserve first run53pass/4fail (two fixture errors plus old lock-wait expectations)
and second56pass/1fail (extra lock round let fallback overtake recovery). Fixes
use valid expiry fixture and no repeated epoch bootstrap; original race tests
are unchanged. Ruff/Mypy1083 clean.

Controlled load2 passed253.23s, zero schemas (active-lease-load-20261010.xml).
Default144.69s/152882 SQL/2534 GET with11 callbacks, versus prior154.12s/12.
Prepare32 calls still equals3*callbacks-1 (prior35=3*12-1): this workload does
not isolate an active-lease proof saving. No causal speedup claim. Default nested
prepare32.54s, _record17835/112.12s, commit18/17.47s, revalidate20/1.58s.
Diagnostic99.53s versus prior75.30s is worse with unchanged98296 SQL/1062 GET,
6241 authority-record reads; retain this negative observation. Phase timers are
inclusive. Normal continuation and per-unit authority/commit costs remain OPEN.
Proof safety selection66 passed117.70s, zero scratch schemas
(active-lease-proof-safety-20261010.xml): includes pure contract cases and
actual Worker/native crash, uncertain-model, tamper and independent physical-read
checks. Not all66 are native. Final default full-source6736 passed/1557
prerequisite skips126.14s (active-lease-source-final-20261010.xml); eval30/30 and
tracked size2382 passed, changed/untracked sources/tests/docs checked manually.
Generated XMLs, including both failed attempts, are preserved under
evals/coverage_acceptance/active-lease-*.xml; native load ran alone on scratch PG.

## Remaining

1. Normal continuation must avoid full crash-recovery scans without weakening
   atomic outbox, uncertain-execution, generation, fence or STOP checks.
2. Incremental commit must verify exact current/dependent native receipts rather
   than replay the entire run for every unit. Final certification stays independent.
3. Batch current authority and Artifact metadata queries, without TTL-caching
   revocation decisions; real Host immediate-revocation semantics remain required.
4. Measured SQL plans/index tuning, model bounded concurrency and 100/1000 legal
   profile load; 20-run distributions and 1/4/16-task fairness remain unverified.
5. Real broker/process/Host/provider/S3/Trench/browser latency and UI progression.
   Independent business labels are absent: no semantic-accuracy acceptance claim.

Targets in COVERAGE_PERFORMANCE_PLAN.md remain open: warm nine-record p95 <=5s,
SQL <=1000, normal recovery scans zero, and UI progress <=500ms.
# 2026-10-10 incremental-validation follow-up (source only)

User explicitly approved incremental acceptance with independent final certification.
`validation_mode=final_certification` is admission/policy-bound; absent/eager JSON
is byte-compatible. Budget reservations skip unrelated checkpoint reads; scoped
preflight still enforces global source/byte ceilings. Commit verifies all parts
of the selected records plus native source/budget facts. Final/read/rebuild/recovery
remain unfiltered. Full accepted-batch replay is retained: an unvalidated record
hint can conceal duplicate selected dependencies, so that optimization was removed.

Coalesced verified reads retain fresh pre/post authorization and full metadata
identity; streaming Task-policy scan and same-recovery model replay reuse landed.
Budget-only rebuild fix preserves full original proof and final retention without
requiring accepted-result manifest lifecycle when no accepted result exists.

Validation:

- Final default suite: 6,848 passed / 1,565 prerequisite skips, 129.42s;
  `/tmp/coverage-incremental-default-final-20261010.xml`. Native PostgreSQL
  regressions require the scratch database and are checked separately.
- Native repaired rebuild + historical damage: 8 passed, 137.27s;
  `/tmp/coverage-incremental-retention-20261010.xml`.
- Extended historical/current damage and Worker rebuild matrix: 37 passed,
  873.88s; `/tmp/coverage-incremental-final-guards-20261010.xml`. This process
  imported before the later checkpoint metadata query coalescing follow-up.
- Preserve initial failure evidence: 4 failed / 31 passed, interrupted after840.12s
  to inspect budget-only rebuild errors; `/tmp/coverage-coalesced-safety-20261010.xml`.
- Scoped source review GO after removing the unsafe batch hint. Ruff, mypy1085,
  tracked file-size gate2382 and deterministic eval30 passed; this is not live GO.

Controlled Worker/PG measurements, nine13-byte inputs,18 accepted units,9 preset
model replies. Timer: after fixture admission through certified completion;
Host/model/S3 transports controlled, callbacks manually handed off. Single samples,
not p50/p95 or a business semantic accuracy claim. Default suite overlapped the
first sample; timings are not isolated comparative measurements.

| Mode / work slice | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| Previous eager /2s |144.69|152882|2534|11|
| Previous eager /60s diagnostic |99.53|98296|1062|1|
| Intermediate coalesced eager /2s |117.02|118542|2562|11|
| Intermediate coalesced eager /60s |64.25|70899|1062|1|
| Incremental /2s |100.77|99495|2224|10|
| Incremental /60s diagnostic |67.31|66101|954|1|

Latest raw XML: `/tmp/coverage-incremental-load-20261010.xml` (2 passed177.21s).
Intermediate XML: `/tmp/coverage-coalesced-load-20261010.xml`.
The latest diagnostic is slower than intermediate despite lower SQL; no isolated
latency saving is established. Inclusive `_record`51.03s/3815calls and commit10.60s
overlap. Diagnostic SQL: business38635/reset21434/clock6033. Default prepare29calls,
19.04s inclusive; normal continuation still invokes recovery. **5s/1000SQL SLO OPEN.**

Remaining: authenticated complete batch lookup, fresh bounded authority batching,
normal-continuation protocol, larger/repeated load, independent labeled semantic
dataset and paired live/UI admission. Read-only Trench audit found ordinary chat
still submits execute=false + separate RUN, not strict atomic execute=true admission.
Protocol v3 requires old Worker drain of persisted v2 pending work; no automatic
migration, merge, push, primary checkout edit or runtime activation performed.

## 2026-10-10 checkpoint metadata/root-query follow-up

Reuse verified-read metadata after checkpoint_source's native row/Event pin.
Physical read pre/post guards, locked metadata equality, receipt and retention
remain. Root Session binding lookup avoids an identical second query within
the same RR transaction; no authority decision is cached. Source review GO.

Native metadata gate retained:72 passed/1 failed601.51s, at
`/tmp/coverage-proof-metadata-reuse-20261010.xml`. Incomplete coverage reached
full proof before missing-set rejection. Follow-up moves missing/exact-set/report
validation ahead of expensive lifecycle proof under run lock; denial only,
complete sets still pass all proof. Repair regression forbids full proof for an
incomplete set. Native remainder42 passed207.35s (68 deselected), publication
and boundary52 passed97.11s; /tmp/coverage-metadata-repaired-20261010.xml and
/tmp/coverage-publication-order-20261010.xml. Final default6853 passed/1565
prerequisite skips146.54s; /tmp/coverage-metadata-final-default-20261010.xml.
Mypy1085, scoped Ruff, file-size gate2382 and eval30 passed. Source-only review GO.

Controlled load ran without other assistant-started tests, same nine117byte
fixture and timer as above. Two single samples, not distributions. This process
imported before the incomplete-set ordering follow-up; complete-case gates are
unchanged, but it is not a frozen-final-source measurement.

| Work slice | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |112.95|95165|2254|10|
| 60s diagnostic |81.62|63329|954|1|

`/tmp/coverage-metadata-load-20261010.xml`:2 passed208.36s,2 eager deselected.
Diagnostic SQL fell from66101 to63329; object GET unchanged954. Default SQL
99495 to95165, but both observed times worsened. No latency improvement claim.
Diagnostic `_record`3617calls/60.97s and commit18/11.81s are overlapping inclusive
times, not additive. Default recovery prepare remains29calls/19.59s. Structural
query coalescing alone is insufficient; normal continuation and batched fresh
authority remain the major open implementation work. No SLO/live/activation GO.

## Locked-policy SQL reuse (2026-10-10)

Changes: one native Task policy per locked verifier/replay/scoped-preflight chain;
standalone and subsequent phases remain fresh. Combined stream/history witness
preserves missing/pruned/exact count/min/max refusal in one statement. Conflicting
commit retry refuses before MODEL proof. No cross-phase authorization or byte cache.
Timing categories and GET/phase counters now freeze at the same completion boundary,
before post-completion validation SQL; category counts must sum to measured executes.

Validation:

- focused55 passed0.66s; wider109 passed/55 prerequisite skips0.93s.
- default6864 passed/1565 prerequisite skips129.15s;
  `/tmp/cov-policy-default-20261010.xml`.
- selected real-PG atomic retry, multipart proof/certification and independent
  final certification6 passed/58 deselected116.12s;
  `/tmp/cov-policy-native-20261010.xml`.
- Ruff, Mypy1085, file size2382 and deterministic eval30 passed.
- Read-only source review GO for current locked/RR callers, not performance GO.

Actual Worker/PostgreSQL, controlled Host/model/S3; nine records,117bytes,18units,
explicit final_certification. No real broker/provider/browser or semantic labels.

| Work window | Seconds | SQL executes | GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |89.9846|98485|2430|11|
| 60s diagnostic |56.5517|63005|954|1|

`/tmp/cov-policy-reuse-20261010.xml`:2 passed155.56s,2 eager deselected.
Diagnostic prior63329→63005 executes,954 GET unchanged. Default95165→98485
executes with10→11callbacks; neither comparison isolates a stable latency effect.
These are single observations, not p95 or matched repeated samples.
Diagnostic business36726/reset20444/clock5835; default business56690/reset29923/
clock8883/timeout2989. Diagnostic `_record`3617calls/42.018s,commit18/8.289s;
default `_record`9274calls/59.292s,prepare32/17.987s,commit18/7.871s.
Inclusive times overlap and cannot be added. Getter authority fanout, short-TX
reset cost and full normal-continuation replay still dominate. ≤1000 executes,
≤5s controlled p95, bounded mixed-tenant capacity and live/UI gates remain OPEN.
No full-plan completion, merge, primary edit, runtime replacement or activation.

## Locked proof reader and final-phase deduplication (2026-10-10)

- Private same-commit reader pins co-located full lifecycle records. Entry/exit
  and physical pre/post authority remain. Only the exact pure semantic deriver
  reuses pinned records; custom/None derivers reread. Expiry is checked on each
  use. The verifier does not mutate metadata or release pins; commit writes
  follow scope exit. Record capacity8192 overflows to guarded reads, not refusal.
- All verified manifest/result/observation/checkpoint bodies share32MiB within
  one verifier invocation. No proof bytes or records cross phases; independent
  certification/recovery retain physical checks. Invalidated readers reject use.
- One complete final-phase verifier proves accepted source equality then aggregate
  results, replacing repeated constructors. An immediately repeated source proof
  before any write is removed. Post-append/retry/cross-TX checks remain new phases.
- Read-only source review GO for these exact scopes, not runtime/SLO acceptance.
  Reader/verifier targeted52 pass0.30s; final lifecycle constructor/fresh-phase
  regression12 pass0.21s. Ruff/Mypy1086/size2382/eval30 pass.
- Pinned-reader native corruption/authority/fence guards16 pass274.54s,
  `/tmp/cov-pinned-record-native-20261010.xml`. This run loaded source before final
  publication deduplication. Default prior pinned-source6885 pass/1565 prerequisites
  132.60s. Final publication default6886 pass/1565 prerequisites123.42s;
  `/tmp/cov-final-phase-default-20261010.xml`. Native publication and multipart
  source/sequence/retention/certification54 pass/zero skips182.76s;
  `/tmp/cov-final-phase-native-20261010.xml`. Final Ruff/Mypy1086/size2382/eval30 GO.

Intermediate body-cache Worker/PostgreSQL load (controlled Host/model/S3;
nine records117bytes/18units; before pinned-record/publication changes):

| Window | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |110.4637|96419|2358|11|
| 60s diagnostic |56.1311|60593|855|1|

`/tmp/cov-verified-body-load-20261010.xml`:2 pass177.45s,2 eager deselected.
Default tests ran concurrently; times are not isolated latency evidence. Previous
scoped-reader diagnostic60593SQL/954GET became60593SQL/855GET. Verified body
reuse reduces physical repetition, not the remaining full-authority SQL tree.
No p95, mixed-tenant, provider/browser or semantic accuracy claim.
Normal continuation/full recovery separation, exact indexed membership, authority
fanout, connection lifecycle/capacity and mixed-tenant fairness remain OPEN.

Frozen final source load (same measurement boundary, no concurrent heavy gate):

| Window | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |81.0788|85685|2007|10|
| 60s diagnostic |43.7284|54293|717|1|

`/tmp/cov-final-proof-load-20261010.xml`:2 pass134.86s,2 eager deselected.
Diagnostic business32010/reset17114/clock5169; default business49687/reset25464/
clock7877/timeout2657. Diagnostic `_record`2663calls/27.457s and commit18/5.253s;
default `_record`7618/46.812s,prepare29/16.490s,commit18/5.691s. Nested inclusive
times are not additive. Compared with the preceding body-cache diagnostic,
60593→54293 executes,855→717GET. Default callbacks11→10, so aggregate reductions
cannot isolate per-callback savings. Single observations are not p95 or matched
repeated latency samples. Both SQL/time goals remain far from satisfied.
All test processes ended. Scratch contains one residual fixture schema of
unestablished ownership; preserved, not silently dropped. No merge, activation,
mixed-tenant/live/browser acceptance or full-plan completion claim.

### Native BEGIN and short canonical pages (2026-10-10)

Binding reads configure RR/read-only at BEGIN using existing psycopg methods,
including deadline/borrow composition. Reset and fresh native lineage remain.
Locked/RR batch scans terminate on short pages; full pages still query again.
Focused17 pass/6 prerequisites; native binding/reset13 pass7.92s at
`/tmp/cov-native-begin-20261010.xml`. Source-only reviewer found no scoped blocker.

| Window | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |81.3504|85643|2007|10|
| 60s diagnostic |49.1902|54282|717|1|

`/tmp/cov-native-begin-load-20261010.xml`:2 pass139.20s,2 eager deselected.
No concurrent heavy gate. Certified-completion boundary unchanged. The fixture
uses a fixed binding loader, not load_session_task_binding: only short-page gains
are represented here; native-BEGIN savings require their own workload evidence.
Default business49650/reset25473/clock7877/timeout2643; diagnostic business31999/
reset17114/clock5169. Default prepare29/18.105s,_record7627/48.573s,commit18/5.234s;
diagnostic _record2663/30.349s,commit18/6.225s. Times are inclusive/non-additive.
Previous single-sample SQL85685/54293 became85643/54282; no observed time gain or
p95 claim. Authority/recovery amplification and capacity/fairness remain OPEN.

Ruff/Mypy1086/size2382/eval30 pass. First default run6890 pass/1567 prerequisites/
1 failure119.13s, `/tmp/cov-native-begin-default-20261010.xml`: unmodified runtime
timeout test failed SIGKILL with PermissionError. Isolated runtime14 pass1.24s,
`/tmp/cov-native-begin-runtime-recheck-20261010.xml`. Full rerun6891 pass/1567
prerequisites119.62s, `/tmp/cov-native-begin-default-recheck-20261010.xml`;
supplemental verifier/reader35 pass0.21s. Preserve failed evidence. No zero-schema
claim: only the previous unknown-owner schema
remains and was not deleted.

### Generation audit: bounded query count (2026-10-10)

Approval and execution handoff share coverage_generation_usage. It previously
queried history volume, history rows and each historical accepted-unit prefix
separately. History count/bytes now use window aggregates in the bounded row
query; all unique cutoffs use one ordered canonical-event prefix scan. Batch
deltas precede cutoff markers at equal sequence, preserving inclusive boundaries.
Exact deployment/session/coverage namespace/run filters remain. Conflicting
repeated cutoffs reject; equal-count crash cutoffs share one marker. Missing/gapped
history, oversized history, invalid watermarks and non-progress still reject.
Fresh configured checkpoint proof, authority, lock and clock checks are unchanged.

Focused44 pass/8 prerequisite skips0.27s. Native52 pass/zero skips71.78s at
`/tmp/cov-generation-audit-native-20261010.xml`, including actual Worker handoff
and native prefix isolation/freshness. Source-only reviewer found no blocker.
Query-count regressions cover0/1/6/64/1000 generations: one query without proof
prefixes, two with prefixes, rather than one query per generation. This is bounded
round trips, not constant database work: history and canonical rows still scan,
and prefix sorting grows with the matching rows. No new counter, cache or migration.
Frozen-source native workload, with no concurrent heavy gate:

| Window | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |78.6969|85170|1987|10|
| 60s diagnostic |49.2711|54282|717|1|

`/tmp/cov-generation-audit-load-20261010.xml`:2 pass136.33s,2 eager deselected.
Default business49406/reset25356/clock7865/timeout2543; diagnostic business31999/
reset17114/clock5169. Default prepare29/16.310s,_record7510/46.076s,commit18/5.456s;
diagnostic _record2663/30.670s,commit18/6.032s. Inclusive times are not additive.
Measurement runs from first handoff after fixture setup to certified completion;
real PostgreSQL/Worker, controlled117-byte9-record snapshot, model/object transports.
Compared with the preceding default single sample:85643→85170SQL and81.3504→
78.6969s. Diagnostic SQL is unchanged: it does not perform continuation generation
audits. Default time-based callback boundaries can vary the read mix (2007→1987GET),
so do not attribute all aggregate differences to this one query change or call a
single observation p95. Getter authority fanout and normal recovery remain dominant.
Ruff/Mypy1086/size2382/eval30 pass. Full default6903 pass/1568 prerequisite skips
125.58s, `/tmp/cov-generation-audit-default-20261010.xml`; final focused rerun44
pass/8 prerequisites0.27s. Skips are not native pass evidence; the52 native tests
above ran separately with PostgreSQL enabled. All test processes ended.
Read-only scratch inventory retains the same unknown-owner fixture schema; no
cleanup, merge, push, runtime replacement or production acceptance is claimed.

### Final lifecycle locked metadata reads (2026-10-10)

Reused the existing private locked proof reader around each complete publication
lifecycle. Only the exact known pure semantic deriver enables pinned-record
reuse; unknown derivers keep the original public path. Budget replay, native
evidence pins, exact source/per-batch checks and aggregate verification receive
the active reader. No incremental keys, mutable facade swap or global cache.
Budget/source byte caches remain independent; after append, retry and cross-TX
proofs remain fresh. Entry/exit, physical pre/post authority, expiry and8192-record
fallback remain. Scope returns None and invalidates before append. Source review
GO; test review required explicit evidence that the post-append injection ran.

Focused initial67 pass/1 failure0.36s, `/tmp/cov-final-scope-focused-20261010.xml`:
test clock advanced only the private reader, not unknown-deriver public fallback.
Fixed both clock mocks, without changing production expiry logic. Final focused68
pass0.29s at `/tmp/cov-final-scope-focused-review-20261010.xml`; scoped Ruff/Mypy3
pass. Initial native54 pass/zero skips136.65s at
`/tmp/cov-final-scope-native-20261010.xml`: publication locks/expiry/STOP/revocation,
retry/rebuild/read and new final-scope success/object/authority injection tests.
After review, the injection tests now require append-hook execution, the injected
object-reader call and exact error, or exact AUTHORITY_INVALID reason. Hardened
native rerun and frozen workload/full gates remain pending; initial native count
alone is not evidence that those stronger assertions have passed.

Frozen source load (no concurrent heavy gate):

| Window | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |72.8697|76349|2017|10|
| 60s diagnostic |37.4566|45010|717|1|

`/tmp/cov-final-scope-load-20261010.xml`:2 pass119.14s,2 eager deselected.
Default business44710/reset21873/clock7197/timeout2569; diagnostic business27067/
reset13460/clock4483. Default prepare29/17.450s,_record6771/36.078s,commit18/6.123s;
diagnostic _record1753/19.072s,commit18/5.629s. Times are inclusive/non-additive.
Same real PostgreSQL/Worker, controlled9-record117-byte/model/object transports;
first handoff after setup to certified completion. Diagnostic retains one callback
and717GET: preceding54282→45010 executes,2663→1753 public _record calls. It shows
reduced authority/metadata fanout, not fewer independent byte proofs. Default
85170→76349 executes; time-based work slicing varied reads1987→2017, so aggregate
timing72.87s vs78.70s is not an isolated causal estimate or p95. Both SQL/time goals
remain unmet. Hardened native rerun and full default gate are still pending.

Hardened native injection rerun3 pass/zero skips54.47s at
`/tmp/cov-final-scope-hardened-native-20261010.xml`, after the frozen workload:
success uses two distinct invalidated scopes; object refusal matches the injected
physical-reader failure after append, authority refusal is exact AUTHORITY_INVALID;
both refuse with zero committed certificate Events. Append-hook execution is
required, preventing earlier unrelated failures from passing the test. Reviewer
confirmed the strengthened source assertions address both evidence gaps. Full
default6913 pass/1571 prerequisite skips126.87s at
`/tmp/cov-final-scope-default-20261010.xml`; Ruff/Mypy1086/size2382/eval30 pass.
Skips are not native pass evidence. All test processes ended. Scratch read-only
inventory retains only the earlier unknown-owner fixture schema; preserved,
not silently deleted. No merge/push, primary checkout edits, restart/activation,
real model/broker/browser, mixed-tenant acceptance or whole-plan completion claim.

## Recovery bounded-query coalescing — 2026-10-10 (source only)

The two volume/row pairs for Session Events and coverage_units now use two native
SELECT statements instead of four. MATERIALIZED full-scope bounds and guarded
LATERAL rows preserve counts/bytes, empty sentinels, tenant/session/run predicates
and ordering; oversized inputs transfer only the bound sentinel. Aggregate fields
are removed before canonical Event replay/digest. Two scans per statement remain.
No authority/object checks, reset, final certification or continuation protocol
were removed. Native source changes remain in codex/cov-exec-01, not activated.

Reviewer initially NO-GO: WITH prefix was incompatible with SELECT-only recovery
snapshot. Wrapped in outer SELECT without widening adapter permissions. Initial
raw-query/native32 pass16.63s is not final adapter evidence. Final actual RR
adapter selection57 pass/zero skips16.72s:
`/tmp/cov-recovery-query-adapter-native-20261010.xml`. Eight native cases cover
empty/exact/excess byte/excess count for both queries, cross-scope isolation,
exact snapshot reuse and native revalidation refusal after scoped source deletion.
Focused7 pass/8 prerequisites1.73s; proof counters assert one history and one unit
query per invocation, bounded denial before MODEL replay. Reviewer source GO.

Frozen workload `/tmp/cov-recovery-query-load-20261010.xml`:2 pass113.85s,
2 eager deselected. Same9 records/117bytes/18 accepted units/9 semantic calls;
real PG/Worker, controlled signed Host/model/object transports, measured after
fixture setup first handoff to certified completion, no concurrent heavy gates.

| Window | Seconds | SQL executes | Object GET | Callbacks |
| --- | ---: | ---: | ---: | ---: |
| 2s |70.6750|75772|1987|10|
| 60s diagnostic |33.1746|45010|717|1|

Default business44384/reset21702/clock7179/timeout2507; prepare29/15.954s,
public _record6600/36.287s, commit18/5.272s, revalidate18/1.259s. Diagnostic
business27067/reset13460/clock4483; prepare2/0.0205s,_record1753/16.228s,
commit18/4.340s. Phase times inclusive/non-additive. Versus previous default
76349 executes, reduction577 is not an isolated causal estimate: time-based
slicing changes proof read mix/GET count. Diagnostic SQL/GET/callback counts
unchanged; its first two prepare calls have no previous live receipt/full proof.
Timing changes are single observations, not p95 or SLO. Main fanout, normal
continuation full recovery and mixed-tenant capacity/fairness remain OPEN.
Additional real crash/no-progress/approval tamper selection7 pass/zero skips75.66s
at `/tmp/cov-recovery-query-fault-native-20261010.xml`. Strengthened native query
tests independently vary every scope field; mutation keeps both exact native
count and bytes unchanged (explicit assertions) but revalidation rejects full
row changes. Final10 pass/zero skips1.94s:
`/tmp/cov-recovery-query-exact-native-20261010.xml`. Earlier strengthened10 pass
2.07s is retained separately, before explicit same-byte assertions. Full default
6915 pass/1579 prerequisite skips130.14s:
`/tmp/cov-recovery-query-default-20261010.xml`. `make check`: size2382/Ruff/
Mypy1086/eval30 pass after fixing one test-only101-character line. Source review GO;
reviewer suggestion to assert exact mutation bounds incorporated and rerun.
No skipped prerequisite is counted as native validation. Processes finished;
read-only scratch inventory retains only the earlier unknown-owner schema,
preserved without deletion. No service restart, runtime activation or merge/push.
