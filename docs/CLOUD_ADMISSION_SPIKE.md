# Cloud admission SQL spike investigation

Task CLOUD-ADMISSION-SPIKE-01; 2026-10-17; base3aeb7c3e.

## Decision and proof boundary

Historical A2 driver spans85.7336ms (SELECT GREATEST) and53.4383ms
(coordinate UPDATE) have no simultaneous server/wait/scheduler record.
They cannot be retrospectively assigned to a unique cause. Native and actual
HTTP controls have not reproduced those exact spikes. No production SQL,
index, trigger, authorization, pool policy, SDK or Trench behavior change is
justified by those isolated values. Existing API pool and previous67-SQL
admission remain the baseline. This slice corrects private measurement and
records the actual bottleneck; it does not claim a production speedup.

## Measurement correction

Previous private observer obtained its global statistics lock before stopping
the SQL clock. New raw driver end, thread CPU end and wall end are captured
immediately on execute return, before scheduler reads/statistics locks.
Observer overhead is reported separately. Current observer overhead does
not prove it caused either historical spike.

Connection startup options enable session-only native PostgreSQL
Parse/Bind/Execute duration logs. Parameter values are suppressed. Collector
retains only statement kind, duration, PID and timestamp for the two target
statements, never parameter values/full database logs. Pool construction
uses Connection.connect, not the psycopg.connect alias; both must be covered
for diagnostic logging. No global PostgreSQL settings are changed.

PID and statement occurrence order associate native protocol durations with
driver spans. Server log timestamps have millisecond precision; ordering
resolves adjacent records. Parse/Bind include planning/protocol work; Execute
includes native trigger work and any server waits/descheduling. Client minus
server is an aggregate residual (network, driver, wakeup and measurement),
not a pure network RTT. Native EXPLAIN separates planning/execution/triggers.

For the target statements only, an independent bounded sampler records
pg_stat_activity wait_event_type/wait_event, pg_blocking_pids and backend
/proc/PID/schedstat. Client thread schedstat and thread_time are separate.
Samples can miss waits shorter than the sampling interval; no sampled lock
is not an absolute zero-lock guarantee. Server scheduler deltas cover only
the sampled interval, not the entire SQL. They are not instruction-level CPU
profiles. The observer's own monitoring SQL is outside application request
counts; both page labels use identical monitoring.

## Native and HTTP controls

Two fresh native backends, four independent committed bootstrap Tasks each:
SELECT GREATEST driver0.312–0.594ms in the corrected server-correlated batch;
UPDATE1.616–7.580ms. SELECT server0.221–0.465ms; UPDATE1.483–7.374ms.
Target residuals0.079–0.514ms. No sampled lock blockers. Native namespace has
no enabled projectors, so it is a lower storage-contract control, not a
substitute for actual Trench-authorized HTTP behavior.

Four fresh-authority actual HTTP controls (execute=false): total104.6–165.5ms;
SELECT0.513–1.684ms; UPDATE5.650–18.082ms. Native server durations closely
track the driver, target residual0.123–0.694ms. Samples include an occasional
DataFileRead, CPU-active intervals and client waits, without blockers.
No commands or models are submitted by readiness/native controls.

Native UPDATE EXPLAIN in actual freshly authorized admission (executed once):

| Event | Planning ms | Execution ms | Projection work trigger ms | Source metadata trigger ms |
|---|---:|---:|---:|---:|
| 0 | 0.149 | 10.808 | 5.107 | 3.478 |
| 1 | 0.068 | 4.553 | 2.192 | 1.610 |
| 2 | 0.067 | 4.589 | 2.188 | 1.558 |

First UPDATE byte-bound trigger0.054ms; no JIT, shared reads0 in this probe.
The two projection triggers dominate reproducible UPDATE execution, not
byte-bound JSON calculation. They maintain durable source/block/queue
invariants and cannot simply be disabled or deferred outside the transaction.
The first-backend-use cost is already mitigated by the existing API pool;
cold first use and a second newly created pooled backend remain possible.

A bounded no-model calibration uses pg_sleep80ms, a held advisory lock and
an injected caller pause80ms. It identifies PgSleep81.98ms, a concrete
blocking PID/advisory wait82.38ms, and driver0.241ms versus caller81.11ms
respectively. It creates no durable objects and releases its own lock.
Runnable native calibration: pipe the private calibrate.py into the normal
API container Python. It requires that container's configured DB role to
read pg_stat_activity; scheduler reads additionally require its existing
local diagnostic superuser permissions. These permissions are not product
API requirements and are not expanded by this task.

## Fixed real-page observations

A1/B1/B2/A2 labels are matched repeated baselines with identical production
sources, existing pool and diagnostic code. They are not a production
before/after comparison. Each has exactly one fresh-authority execute=false
readiness Task before the real UI send. Same official PostgreSQL18/Redis8
web-search prompt; high thinking, Flash, v2 and autonomous tool choice
retained. No forced sources/tools or fifth Run.

| Label | First body s | Whole turn s | Application nonempty SQL | Models/tools | POST Tasks ms |
|---|---:|---:|---:|---|---:|
| A1 | 13.082 | 16.193 | 3202 | 3/4 | 251.2 |
| B1 | 12.894 | 16.490 | 3200 | 3/4 | 237.8 |
| B2 | 15.511 | 18.188 | 3937 | 4/5 | 197.9 |
| A2 | 14.814 | 22.088 | 3492 | 4/4 | 273.7 |

All four completed;14 execution model responses, all high/Flash/retry0,
17 successful autonomous tools,0 failed tools. B2 chose an extra search/model
round; A2 generated two candidates. Preserve these outcomes; no unrelated
quality/fixture repair is added. First-body metric includes the eventually
committed prefix seen in temporary output; A2 whole turn includes revision.

Every POST Tasks retains67 business SQL plus7 existing empty pool health
checks (74 driver executions),6 fresh-authority registry/clock/replay/audit
SQL,0 ordinary physical connects during the request. Six startup Cloud
requests retain156 business SQL plus13 empty checks; Worker startup retains
448 driver executions/33 empty/5 Task I/O opens. There is no SQL reduction
or production latency improvement in this diagnostic slice. Observer queries
and EXPLAIN/control probes are outside application counts, not nonexistent
database load. No causal A/B average is appropriate for identical sources.

| Label | SELECT driver/server ms | First coordinate UPDATE driver/server ms |
|---|---|---|
| A1 | 5.665/4.999 | 26.838/26.538 |
| B1 | 3.109/2.598 | 17.659/17.417 |
| B2 | 1.910/1.696 | 24.214/23.921 |
| A2 | 10.785/8.181 | 43.402/42.644 |

Current A2 UPDATE43.402ms = server42.644ms + residual0.758ms. Native server
parts: Parse0.118/Bind0.240/Execute42.286ms. Wait samples contain one
DataFileRead and active CPU intervals, no blockers. Across40.129ms of
sampled span, backend schedstat grows36.395ms runtime and2.952ms runqueue
wait; client CPU0.211ms/client runqueue0.374ms; observer overhead0.234ms.
This supports server computation with smaller scheduling/I/O contributions
in this instance. It does not prove every millisecond belongs to a specific
trigger, nor retroactively identify the historical53.4ms query.

Current A2 SELECT10.785ms = server8.181ms + residual2.604ms (Parse0.557,
Bind3.596, Execute4.028ms). Samples include DataFileRead; sampled4.669ms
contains runtime2.674ms/runqueue1.398ms. B2 readiness SELECT8.402ms has
server1.602ms/residual6.800ms; A2 readiness SELECT9.677ms has server2.040ms/
residual7.637ms. Their delayed monitor samples fall outside the raw span
and are excluded from wait attribution. No valid packet-arrival trace was
captured, so these residuals cannot be uniquely split into network vs GIL/
libpq wakeup/VM scheduling. Client runqueue alone cannot settle that split.
The historical85.7ms SELECT is still not reproduced or uniquely attributed.

## Validation and normal runtime restoration

31 diagnostic/readiness/normal Tasks were reconciled against durable events:
0 accepted commands and0 model requests. Calibration assertions passed for
server timeout, a concrete advisory blocker and caller pause. Four page
summaries assert exact conversation/Task identity, completed/v2/high/Flash/
retry0,67 business admission SQL and6 fresh-authority SQL. Source unchanged,
so no unrelated full test/fixture repair cycle or new full-suite claim.
`git diff --check` validates the focused documentation slice.

Original normal API13e19eadb56d, Worker1a2270dfbf0b and Search245b675ff61b
restored; original six Compose files, environment hash, entrypoint/commands,
107 source fingerprints, healthy/zero-restart checks passed. Two actual fresh
HTTP execute=false controls on restored normal API returned201. Diagnostic
session logging ends with those replaced connections; global log_duration
remains off and log_min_duration_statement=-1. Original B2 result is reopened
read-only after restoration. Observers and loopback receiver are removed at
closeout; local staged integration preserves27 unrelated primary entries.
No push, package publication, migration, production-source or Trench change.

## Artifacts and next boundary

Private evidence is under .artifacts/cloud-admission-spike-20261017:
native-spike.safe.json, update-explain.safe.json, sql-server-*.safe.json,
calibration.safe.json, canonical-*.safe.json and page-B2.jpg.

An optimization of projection trigger work must first identify a redundant
nested query while preserving source-order guards, privacy/frontier updates,
projector fanout, command anchors and transaction rollback. No broad migration
or native guard removal is included here. Historic85.7/53.4 attribution and
stable p95 remain OPEN; a matched source-level fix needs its own justified
production diff and actual post-change acceptance.
