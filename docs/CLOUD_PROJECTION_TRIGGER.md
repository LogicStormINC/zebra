# Projection trigger plan reuse

Task CLOUD-PROJECTION-TRIGGER-01, base04a5c48d, 2026-10-17.

## Measured cause

Native auto_explain nested profiling on a fresh backend then a second distinct
fresh-authority execute=false Task on the same backend shows eight routing
queries per Event, with internal execution0.219–0.806ms versus total trigger
3.753–7.549ms. Difference includes native planning/PLpgSQL/diagnostic overhead,
not a pure planning measurement. Source metadata retains source/head/segment
checks and writes plus nested business guards. The initial metadata-ready
UPDATE often affects zero rows; it remains necessary for explicit repair.
Routing rechecks enabled projector versions in each statement; the existing
mid-route disable contract requires those reads. No such guard is removed.

An isolated database A/route-only/both/A native control, two committed Tasks
on each fresh backend, changes only function plan_cache_mode. Repeated queue
trigger cost2.2–6.0ms becomes0.35–0.52ms; metadata1.3–2.4ms becomes0.62–0.81ms.
First invocation still compiles, and its latency is not guaranteed to improve.
Generic-plan reuse removes repeated planning work, not authority queries or
business SQL. Native profile logging overhead is excluded from the separate
no-logging control. Native controls do not substitute for actual UI acceptance.

## Minimum implementation

Additive migration103 contains only two ALTER FUNCTION statements, setting
plan_cache_mode=force_generic_plan on route_task_projection_work() and
write_projection_source_metadata(text,uuid). No function body, query, trigger,
index, data, native guard or global server setting changes. PostgreSQL
restores the caller setting on function return. Released67/68/98/100/102
migration checksums remain frozen. SQLite behavior is unchanged.

The existing point-key/bounded SQL is the intended generic-plan workload.
Statistics/schema changes can invalidate cached plans. Different production
cardinality can change planner choices; actual nested plans and bounded
source/queue regressions are required, rather than a universal p95 claim.

## Validation and page protocol

Standalone check scripts/check_projection_trigger_plans.py uses an isolated
ZEBRA_TEST_POSTGRES_DSN. Red on missing function configuration, green on
configuration scope/source coordinates/block/queue/explicit repair and
source-business rollback guard. Caller force_custom_plan remains in effect
outside these functions. Historical checksums asserted.

Focused run:43 passed/21 scratch-dependent skipped/3 large read-plan cases
excluded. Configuring the existing scratch container failed authentication;
its credentials/state were left unchanged. An owned temporary header_scratch
DB on the existing local test server then ran the missing native matrix:
42 passed/1 repair I/O-budget failure; the single failure reproduced on one
bounded recheck. That fixture installs historical routing through v100 and
never applies v103; no source/test-budget repair is included. This is a
recorded validation limitation, not a full-suite green claim. Standalone
v103 scope/source/block/queue guard check passes; default clean tracked-source
make check passes after final source freeze. The native mid-route-disable
regression now explicitly exercises the v103 routing function setting. One related test
setup selects released v102 explicitly instead of assuming the final migration
is always a routing-function body. No partial fixture schema is expanded. Existing legacy API image was already
at catalogv101 while the database wasv102 before this task; it remains
unchanged and is not part of the accepted normal API/Worker composition.

Fixed four actual page Runs A1/B1/B2/A2 use the same v103 catalog/images and
observer, same official PostgreSQL18/Redis8 search prompt, high/Flash/v2 and
autonomous tool choice. One fresh-authority execute=false readiness Task each.
Only the two native function-local settings change: A=original defaults;
B=generic. No ledger rollback or historical Run replay. Final normal service
uses v103/generic on both functions and matching API/Worker migration catalog.
All outcomes retained, no favorable fifth Run; no Trench product changes.

## Actual page results and normal activation

Fixed four authenticated real-page Runs, no fifth Run:

| Label | First body s | Whole turn s | Nonempty app SQL | Models/tools | Candidates |
|---|---:|---:|---:|---|---:|
| A1 | 13.598 | 16.488 | 3177 | 3/4 | 1 |
| B1 | 12.397 | 15.327 | 3201 | 3/4 | 1 |
| B2 | 22.121 | 25.099 | 4918 | 5/7 | 1 |
| A2 | 14.537 | 21.940 | 3507 | 4/4 | 2 |

All completed,15 execution model responses high/Flash/retry0,19 successful
autonomous tools and0 tool failures; v2/fresh authority preserved. B2 chose
extra searches/fetches/model rounds; A2 generated two candidates. Do not
attribute these work differences to the native plan setting or discard them.

First-body means A14.068s/B17.259s; whole-turn means A19.214s/B20.213s;
whole nonempty SQL means A3342/B4059.5. No whole-page improvement, p95 or
whole-turn SQL reduction is proven. Matched A1/B1 both3 models/4 tools have
body13.598/12.397s, but one pair is not a stable latency guarantee.

Every POST Tasks:67 business SQL +7 empty pool health checks =74 driver
executions,6 fresh-authority registry/clock/replay/audit SQL,0 ordinary
physical connects during the request. Six startup Cloud requests retain
156 business SQL +13 empty checks; Worker startup448 executions/33 empty/
5 Task I/O opens unchanged. Query-plan reuse caches plans, not query results;
authorization and live projector enabled/privacy checks continue to execute.
Observer sampling and native EXPLAIN controls are separate diagnostic SQL,
not included in application business counts, and exist equally for both labels.

| Label | First coordinate UPDATE ms | Mean next two UPDATE ms | Mean next two server ms |
|---|---:|---:|---:|
| A1 | 25.153 | 9.470 | 9.211 |
| B1 | 23.742 | 3.969 | 3.679 |
| B2 | 20.030 | 4.751 | 4.293 |
| A2 | 16.526 | 10.330 | 8.732 |

Page repeated UPDATE means A9.900ms/B4.360ms (about56% lower), native server
A8.972ms/B3.986ms. First UPDATE A20.839ms/B21.886ms: no cold first-use gain
proven. Overall initial index means75.58/77.78ms and admission-body111.02/
161.82ms do not improve in this small cohort; first INSERT means17.16/53.10ms
also vary substantially. Keep these unfavorable observations. The demonstrated
benefit is repeated trigger plan work, not guaranteed overall admission latency.

Separate no-logging isolated control after first use: source trigger average
1.6663→0.7054ms (about58% lower), routing3.7090→0.4126ms (about89% lower).
Actual fresh-authority nested profiles retain the same454 recorded plans/six
updates, including8 routing SQL per Event; both A/B have no sequential scan
nodes. Logging/profiling overhead limits direct comparison of nested-profile
trigger totals with normal execution. No native query or guard is removed.

Local additive migration103 applied once; schema ledger remains103 throughout
A/B, only the two function settings toggle. Final normal state: both generic,
function bodies hash-identical to before migration, global plan_cache_mode=auto
and log_min_duration_statement=-1. Native functions restore caller settings.

Normal API eb4f695bf3e8 and Worker932dfe32fda7 contain only the matching
migration catalog/new migration overlays; Search245b675ff61b is unchanged.
Original six Compose files, environment hashes, entrypoints/commands,
109 registered source hashes, healthy/zero-restart checks pass. Actual normal
API image passes the standalone native check in an owned disposable DB.
Two fresh actual HTTP execute=false Tasks return201 after restoration.
Twelve live no-model controls (including two whose diagnostic cleanup failed
after their committed responses) reconcile0 accepted commands/0 model requests.
B2 original result reopens read-only on normal service with high visible;
screenshot saved, DOM observers and loopback receiver removed. Primary local
integration preserves27 unrelated dirty entries. No push/npm/remote deployment.

## Evidence and remaining boundary

Private evidence .artifacts/cloud-projection-trigger-20261017 includes
nested-A.safe.json, nested-plans-A.safe.json, bench.safe.json and final page
observations. Historical85.7/53.4ms spikes remain without simultaneous native
evidence; plan reuse does not retroactively attribute or guarantee their
removal. Real-page whole-turn performance and SQL totals are reported
separately from trigger cost and unchanged statement counts.
