# Bounded Worker progress connection reuse

Task RUN-HEADER-PLAN-01; original source base `3cc045bc`.

## Root cause and decision

Retained A1/A2 actual-search traces attribute approximately2.26s of SQL time
across both Runs to latest/explicit Run metadata reads. This SQL time is inside
progress catch-up, not additional time to add to the existing residual totals.
Native read-only EXPLAIN on both original Tasks shows planning5.16–8.23ms and
execution0.61–1.20ms in the initial four-query sample. Most elapsed database
work is not fetching historical bodies. Physical connections are also recreated
for every adapter call, losing backend state and paying repeated handshakes.

Bounded read-only experiments tested CTE materialization, parameter joins and
correlated parameter binding. Results were mixed or slower. None of these SQL
rewrites is included; all production Run queries, source bounds and indexes
remain unchanged. Plan timings are diagnostic samples, not a performance SLA.

The minimal retained change reuses the existing synchronous callback connection
scope with explicitly bounded sockets. It does not create a global pool, cache
query results, add a dependency/Port or merge independent transactions.

## Implementation boundary

- `postgres_connection_scope(bounded=True)` requires an existing Task I/O
  deadline. An ordinary parent scope can span a coverage model call; the bounded
  child owns and closes its own sockets before returning to that parent.
- Only matching nested bounded deadlines share the short scope. Progress
  catch-up/publication opt in under their existing cumulative2s budget and lock.
- `TaskIoConnections.connect` still validates and clamps every borrow's budget,
  retains native cancellable waits, and retains the cancellation cleanup reserve.
  Reuse additionally requires libpq17+ native cancellation: later borrows can
  have less time left than the socket's initial server timeout. Older clients
  keep fresh connections/server timeouts. No query retry or longer budget is added.
- Bounded keys include complete connection settings, cursor mode, PG environment
  and scoped deadline, separate from ordinary connection keys. Service-based DSNs
  continue resolving configuration on every connection attempt and bypass reuse.
- Every adapter still commits or rolls back independently, then executes existing
  DISCARD ALL and resets client transaction defaults. No locks or snapshots are
  retained between adapter calls. Reset failure closes the socket after preserving
  acknowledged success; unknown COMMIT errors still escape and are never replayed.
- Already-closed sockets are discarded without attempting another rollback.
  Cleanup attempts every retained socket, including abandoned borrows, and
  secondary close errors cannot replace query/unknown-COMMIT/callback failures.
  These three cases were reproduced red before the shared cleanup fix.
- Under a Task I/O deadline, ordinary database.connect routes to the bounded
  connector before the unbounded callback factory. Explicit existing transaction
  work units retain their previous ownership/ordering semantics.

All Run/namespace/anchor/source-page/body byte gates, lease fences, STOP checks,
canonical writes, checkpoint CAS, public commentary policy and v2 behavior stay
on their original fresh SQL paths. Flash/high is unchanged. No model is invoked.

## Paired native measurements

One disposable PostgreSQL server, fixed ABBAABBA order, four samples per variant.
Each sample uses a fresh namespace, the same canonical response and one progress
commentary output. Original uses the base connector; candidate uses the new
bounded reuse. Canonical lease checks, commits, checkpoint membership and exact
output counts execute normally. No sandbox or provider is called.

| Whole measured synchronization operation | Original median | Candidate median |
| --- | ---: | ---: |
| Adapter borrows |9|9|
| Physical connections |9|1|
| Explicit SQL statements |50|59|
| DISCARD ALL resets |0|9|
| Elapsed time |214.695ms|115.305ms|

Physical connections decrease88.9%; measured elapsed time decreases46.3%.
SQL increases18%, entirely from preserved reset statements. This slice improves
connection waiting; it must not be described as another SQL reduction. Each
candidate sample is faster than each original sample in this small local set,
but this is not a real-page or whole-Run latency estimate. Retained v2 no-frame-SQL
behavior and prior bounded query reductions are unchanged. Whole-system80% SQL,
page first-body, STOP/revocation/takeover and capacity/GC gates remain OPEN.

An initial candidate pair measured271.655→120.210ms. After the final cleanup
fault fixes the same fixed pairing was rerun, yielding the final values above;
both sets are retained and neither is a whole-Run estimate.

Private receipts under `.artifacts/run-header-plan-20261016/` retain all initial
plans and discarded SQL experiments as well as the fixed native pair. No failed
samples are omitted. No application DB DDL, manual data repair or original-Run replay was performed.

## Verification and delivery

134 distinct focused checks pass:74 SQLite/core/Worker recovery and commentary
cases, plus60 connector/scope/work-unit/native progress cases. Two optional
shared-DNS scratch experiments skip because their separately guarded environment
is not configured; no fixture was weakened to enable them. New native checks
cover fresh transactions, reset/rollback, cursor/thread separation, cumulative
query and deferred-COMMIT timeout, unknown acknowledgement, service/env isolation,
bounded child lifetime, older-libpq fallback and all three secondary-close fault
boundaries. The initial test put SET TRANSACTION after a SELECT; this was
corrected before implementation and the original source then failed the intended
socket-reuse assertions.

Clean tracked-source `make check` passes: Ruff, mypy1283 files, file-size3095,
eval30 and both existing standalone progress fault checks. One new test import
order was corrected; no historical test infrastructure or fixture was repaired.
No full test-suite or model/page latency acceptance is claimed.

Normal Worker image `8336bda6` activated under the zero-active-intent guard.
API `907fcc00` exact image/start timestamp is unchanged; API/Worker are healthy
with zero restarts.82 source fingerprints retain all80 prior identities plus
two newly checked paths, with intentional Worker overlay hashes updated. Original
six-file Compose, environment, entrypoints/commands and search configuration match.
An actual read-only probe inside the new Worker confirms libpq18, one physical
connection for two transactions, readonly state reset and socket closure at scope
exit. It calls zero models and reads no conversation bodies.

Local integration preserves27 unrelated primary dirty entries. No push, npm
publication, remote deployment or model/Run replay.
