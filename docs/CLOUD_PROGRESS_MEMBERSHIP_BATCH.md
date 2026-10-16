# Bounded transaction-local progress membership batch

Task `PROGRESS-MEMBERSHIP-BATCH-01`, owner Luke Ding, executor Codex.
Branch `codex/progress-membership-batch-01`, base `de12228a`.

## Cause and minimum change

After verifying a canonical page, `advance_worker_progress` previously fetched
each output's stored signature independently, then queried that signature again
while folding the same page. With128 distinct outputs this requires256 indexed
membership SELECTs in the same two-second I/O scope.

Reuse the existing bounded IN-query pattern from `worker_receipts_covered`.
Collect exact signatures of PUBLIC_OUTPUT events on the already-verified page;
reject conflicting same-page IDs; fetch all matching stored signatures with one
namespace/Task/anchor/projector-scoped query; reject stored conflicts and reuse
the same map for folding. Identical repeats still count once. Empty output pages
perform no membership query. The standalone point membership Port stays intact.

One production function changes. Canonical page validation already limits this
map/query to256events/1MiB, each output ID to160characters, so SQL parameters and
returned rows remain bounded. No value survives the transaction. The existing
head row lock serializes advancement; CAS, fresh fenced writes, Run boundaries,
unknown-commit behavior and32KiB state hydration are unchanged. No new Port,
cache service, pool, dependency, schema, retry or longer deadline.

## Evidence and proof boundary

Both native workloads use one disposable PostgreSQL server per fixed comparison,
fourA/fourB in ABBA/ABBA order and independent fresh namespaces/epochs. A replaces
only advance_worker_progress with de12228a's function; B uses the candidate.
Counts cover measured operations only, excluding seeding/migrations. Receipts
retain counts, not query parameters/prompt text/credentials.

Single-response plus public-commentary comparison: SQL55→54, connections9→9,
event pages2→2. Median229.15→253.00ms; no stable latency improvement is established.
All ordinary cases publish exactly one output with no pending commentary gap.
Delaying the old point-signature SELECT with pg_sleep(3) causes the original to
stop1840.92ms after confirmed canonical output; the candidate avoids that point
query and completes251.93ms. Both have one canonical output, so the distinction
is checkpoint convergence, not permission to append or replay an output.

| Median for recovering128 canonical outputs | Original A | Candidate B |
| --- | ---: | ---: |
| Signature membership SELECTs | 256 | 1 |
| All explicit SQL | 398 | 143 |
| TaskIO connections | 3 | 3 |
| Elapsed native time | 269.45 ms | 122.10 ms |

All eight backlog cases converge to the exact same128-output progress count and
persisted head. Total recovery SQL is reduced64.1%; this small fixed sample's
median recovery time falls54.7%. These percentages apply to this128-output
catch-up workload only. Ordinary single-output SQL falls just1.8%, with no stable
latency gain. No whole-Run/browser first-body gain or SLA can be inferred.

## Validation and activation boundary

The existing default no-model gate has one extra real-SQLite index/fold check.
It failed original per-output queries before source edits and now covers one
batch read, identical same-page/stored dedup, conflicting same-page/stored
identity rejection and transaction rollback. Run/canonical ports are isolated in
that unit check; real authority/concurrency behavior belongs to native tests.

Existing SQLite/core/recovery/commentary tests74passed; existing native PG
progress/Run/concurrent-CAS/commentary/unknown-ack/fence tests11passed. Native
A/B duplicate/conflict controls:8cases passed, covering same-page and stored-ID
identity conflicts, identical dedup and unchanged rollback frontier in both
modes. No framework or fixture is added or repaired.

Clean tracked-source `make check` passes: file-size3094, whole-source Ruff,
mypy1283, deterministic eval30 and both existing standalone fault gates. This
uses the same clean export as prior slices, excluding historical private
artifacts without changing lint configuration or unrelated code.

Final normal Worker506d0d80 is healthy with zero restarts.79retained/replaced
source identities and original six Compose/environment/commands/search checks
pass. API907fcc00 image and exact start timestamp remain unchanged. Current
source digest matches the overlay. Zero active Host intents and unchanged prior
images were checked before replacing only Worker. Local cloud-agent-trench FF
preserves unrelated dirty work; there is no main-merge/remote acceptance claim.
No model call, historical Run replay, schema migration, business write, push,
npm publication or remote deployment. Safe receipts live under
`.artifacts/progress-membership-20261016/`.
