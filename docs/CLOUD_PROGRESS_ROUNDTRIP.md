# Source-once projection routing

Task PROGRESS-ROUNDTRIP-01; base `b4d9a526`.

## Evidence and root cause

The connection reuse gain is retained. A three-sample native response/commentary
profile now attributes121.57ms over6 canonical COMMITs to the largest remaining
category, versus46.35ms over9 latest-Run queries. These are aggregate method spans,
not extra elapsed time to add to the operation. A separate disposable PostgreSQL
track_functions sample identifies `route_task_projection_work` self62.861ms out
of deferred allocator total103.274ms over6 events. Function inclusive times nest.

The routing trigger expands the same canonical Task privacy/version classification
into multiple routing statements. Its ready branch contains24 privacy-source
references. Registered projectors are ordinary/coverage exclusive plus explicitly
enabled custom versions. The local runtime currently enables both AG-UI versions;
zero-projector microbenchmarks would not represent its normal routing workload.

## Minimal change

Additive migration102 replaces only `route_task_projection_work`, without tables,
columns, source rewrites or backfill. It computes a transaction-local version array
and privacy frontier once per canonical Event, then passes the scalar result to
the existing set-based routing SQL. The ready branch has2 privacy-source references
within one classifier, instead of24 references across routing statements.

`routed_statements`/`activate_privacy` gain an opt-in preclassified mode. Their
existing default output stays byte-identical, including historic migrations68,
98 and100. Every prior migration name/checksum through101 is verified unchanged.
SQLite and explicit repair retain their existing SQL and behavior.

Preserved boundaries:

- No cross-Event result or authority cache; each trigger freshly classifies its
  source-owned namespace/Task and retains ordinary/coverage exclusivity.
- Current enabled versions are rechecked in every routing statement, including
  privacy activation. A native fault case disables a projector during pending-row
  insertion; this exposed a candidate gap red, then passed with the live guard.
- Set-based fanout stays set-based at the supported four-version maximum.
- Original pending/ACK/revision/Run closure, failure budget and dependency wake rules.
- Unready-header branch, malformed/null admission privacy, late privacy repair.
- Original source lock order, lease fences, canonical COMMIT durability, cumulative
 2s I/O/cancellation, v2 and high thinking. No model or historical Run is replayed.

## Same-work native pair

One disposable server, fixed ABBAABBA with four samples per variant for each
configuration. Original installs the unchanged v100 trigger; candidate installs
v102. Each sample starts with a fresh namespace, explicit projector enable and
bounded bootstrap/repair, then the same fenced response plus one commentary.
Every expected ordinary/custom queue reaches the exact canonical frontier;
coverage stays empty for the ordinary input, with one public output exactly.

| Registered versions | Original median | Candidate median | Elapsed reduction |
| --- | ---: | ---: | ---: |
| Ordinary + coverage |125.600ms|110.060ms|12.4%|
| Same two + two custom versions |127.615ms|109.895ms|13.9%|

Both variants retain59 application-side SQL executions and1 physical connection
per operation. This improvement reduces repeated trigger classification/planning;
it is not another application SQL-count reduction. Previous215→115ms numbers
used a different queue configuration and cannot be chained with this pair.
These operation results do not establish page-first-body or whole-Run gains.
Whole-system80% SQL, STOP/GC/multiworker and actual-page gates remain OPEN.

## Validation and local activation

New resource assertion is red24→green2; historic checksum checks remain green.
Native route-disable fault is red→green. The expanded routing/queue/bootstrap/I/O,
dual-consumer and migration run produced 96 passed, 2 skipped and 3 failed. These
failures are retained, not counted as a passing full regression:

- Two old repair expectations also fail with the unchanged v100 trigger: finishing
  20 headers in one call and expecting a 1.5–2.4s tick conflict with the existing
  100ms repair sub-budget. No budget or historical fixture is changed here.
- The third is a real existing maintenance cleanup hazard: near the 100ms limit,
  inherited statement_timeout can cancel ROLLBACK TO SAVEPOINT; RELEASE then masks
  that error with InFailedSqlTransaction. A fixed three-sample v100-only control
  produced one pass and two identical failures. Explicit repair SQL/default
  builders remain unchanged in this slice. This risk needs a separately scoped
  production fix; this optimization does not resolve it.

Clean tracked-source `make check` passes Ruff, mypy (1284 files), file-size checks
(3097 files), 30 eval cases and both standalone progress fault checks. This is
distinct from the expanded test run above. The final focused native routing and
migration run has 42 passed, 2 skipped and 1 failed. That additional failure expects
one repair call to finish a bootstrap; it returns a resumable prefix (2 of 3) within
the unchanged 100ms sub-budget. The exact assertion was not separately baseline
paired. The native A/B operation uses bounded continuation and verifies the final
frontier for all enabled queues. No full regression pass is claimed. No historical
fixture files are repaired; two catalog assertions simply include new version102.

After checking zero active Host intents, local migration102 was applied through
the normal migrator. The previous live function matched v100 exactly; the final
function and migration ledger match source102. Source-only API and Worker images
are now healthy with zero restarts: API `cfc1dcf8`, Worker `3cb401d3`. Verification
retains 88 source fingerprints, the original six Compose files, environment,
commands, entrypoints and search configuration. Both services were recreated;
the API start time intentionally changes for its matching migration catalog.
The actual Worker libpq18 read-only probe still proves two independent
transactions, one physical socket, default reset and socket close on scope exit.

Private evidence `.artifacts/progress-roundtrip-20261016/` retains profiles, fixed
pairs and gate/activation receipts. Setup initially assumed one bounded repair
call and eight projectors; corrected to bounded continuation and the actual
four-version constant before the final paired run. No application data repair,
provider calls, push, npm publication or remote deployment is performed.
