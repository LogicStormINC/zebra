# Run-owned bounded database sockets

Task RUN-BOUNDED-SOCKETS-01; human owner Luke Ding; executor Codex; based48912c4.
This slice targets physical connection setup, not a further SQL reduction.

## Root cause and smallest retained change

The previous callback scope reuses sockets during one progress publication,
then closes them. Four sequential normal response/commentary publications on
current v102/two enabled projectors open four physical connections, run224
explicit queries/reset statements, and spend26.8–30.9ms in connection opening.
The existing model/tool facades already filter irrelevant Events correctly;
no duplicate indexing fix is needed.

Reuse the existing ConnectionScope explicitly for one cloud execution attempt
through the shared execute_claimed_with_stale_retry entry. Each stale retry
gets a new owner. The490line execution.py stays untouched; no new abstraction,
Port, process/global pool or dependency is added. Local execution does not opt in.
Ordinary adapters keep their existing composition pool/connection behavior.
Ordinary coverage scopes still own their original separate callback lifetime.
Default bounded callbacks outside this explicit owner still close at callback exit.

Only native libpq17+ bounded Task I/O borrowers with an active task_io_deadline
can reuse the Run owner's idle sockets. Complete DSN, cursor and PG environment
keys remain isolated; service-based DSNs and older libpq retain fresh connectors.
Copied thread contexts cannot borrow the owner's sockets. Every adapter still
commits/rolls back independently, runs full DISCARD ALL and resets client defaults.
Every callback starts its original fresh2s cumulative budget; the owner does not
create a Run-wide I/O deadline or extend a shorter budget. Native cancellation,
unknown-COMMIT propagation and every canonical/authority/STOP query remain.
No query result, transaction, lock, snapshot or authority row is cached.

## Idle disconnect risk resolved before adoption

A database can terminate a socket while the Agent waits on a model/tool. A real
scratch probe terminates only its own idle backend; the initial candidate then
fails its next query with AdminShutdown. Direct libpq input/status/result probing
also fails this test and is removed; available input is not an adequate transport
liveness guarantee. See the [native asynchronous protocol documentation](https://www.postgresql.org/docs/18/libpq-async.html).

Reuse installed psycopg_pool.ConnectionPool.check_connection, without constructing
a pool: one empty protocol query when an idle socket enters a new callback budget.
Renew native deadlines before that check. On an OperationalError, discard the
socket and connect afresh within the same remaining deadline, before ANY business
statement is sent. No application query or COMMIT is replayed. TimeoutError still
escapes. Errors/races after a business statement starts retain normal failure and
unknown-outcome semantics; this is not a general transparent retry mechanism.

The own-backend termination check is now green, alongside fresh/shorter deadlines,
transaction reset, unknown COMMIT, Run cleanup, ordinary adapter isolation,
cloud-only entry wiring and the existing eight-idle-socket ceiling.
Idle sockets occupy database sessions until attempt exit; normally one in this
measured workload, at most eight retained per owner. Multiworker capacity is a
separate open gate; this is not a process-pool or capacity acceptance claim.

## Final paired evidence

One disposable PostgreSQL server, identical current v102, fixed ABBAABBA,
four samples per mode for each enabled-projector configuration. Fresh namespace,
four distinct model_call_ids, same four response/commentary facts and exact final
head/queues; no model or sandbox runs. Initial private workload accidentally
reused one call ID and correctly failed the canonical commentary identity check;
fixed before the baseline, without changing any fixture or production validator.

| Four-publication operation | Original | Final Run reuse |
| --- | ---: | ---: |
| Physical connections |4|1|
| Explicit query/reset statements |224|224|
| Additional empty health requests |0|3|
| Total counted driver execute calls |224|227|
| Two projectors, median elapsed |393.115ms|375.910ms|
| Four projectors, median elapsed |505.455ms|376.840ms|
| Two projectors, median opening time |25.322ms|6.049ms|
| Four projectors, median opening time |30.918ms|6.775ms|

Physical connections decrease75%; median elapsed improves4.4%/25.4% in this
small local pair. Driver execution calls increase1.3% due to the explicit liveness
checks; no SQL reduction is claimed. Larger elapsed differences are not attributed
solely to opening time: backend warmth/host variability are not isolated here.

An earlier pre-health-check pair measured510.230→413.640ms and510.355→388.420ms
(18.9%/23.9%). Retained as intermediate evidence, not final delivery performance.
The changed baseline itself shows variability. Neither cohort establishes actual
page-first-body gain or removes the retained11–13s exclusive Worker residual.

## Verification and delivery

One runnable no-framework/no-fixture check:

```
ZEBRA_TEST_POSTGRES_DSN=... uv run python scripts/check_run_bounded_sockets.py
```

It uses only its own connections (including termination of its own idle backend).
Existing focused regression results:23native scope/commentary checks and30claimed
execution/progress-entry/preflight checks pass. The23native cases also pass after
the final health helper, including reset/rollback, thread/cursor/environment/service
isolation, older-libpq fallback, cumulative query/deferred-COMMIT cancellation and
primary-error preservation. Two real native cross-callback publication controls
reject expired lease and superseded Run, leaving canonical highwater/output intact.
New-check Ruff import/closure findings were corrected; no old fixture changes.

Final clean tracked-source make check passes: Ruff, mypy1285, size3102, eval30
and existing progress fault gates. Zero-active-intent guarded Worker-only source
overlayce680c30 is active, healthy/zero restarts.93source fingerprints and original
six Compose/env/commands/entrypoints/search match; API7eb869c9 exact image/start
are unchanged. Actual Worker libpq18/model-free shared-entry probe verifies two
callbacks, one socket, renewed budget after the first expires, full reset and
close at attempt exit. This probe uses native database reads and a stub execution
body; it is not authenticated real-page/model acceptance.
Local integration preserves primary27unrelateddirtyentries. No schema/migration, historical Run replay,
new model call, provider/high/v2 change, push/npm publication or remote deployment.
Overall SQL80%, actual page SLA, STOP/revocation/takeover, Redis faults, GC/capacity
and multiworker acceptance remain OPEN.

Private receipts: .artifacts/run-bounded-sockets-20261016/.
