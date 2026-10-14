# Cloud stream fresh-proof and quiet-read performance plan

2026-10-13. Task CLOUD-STREAM-PROOF-PERF-01 is In Progress after CLIENT
local acceptance at249f4e6d.
Luke Ding owns the task; Codex executes. Local integration into
cloud-agent-trench is authorized; push and deployment are not.

## Measured problem and evidence boundaries

A readonly native audit on ffe8f38b used isolated PostgreSQL/Redis fixtures:

| Activation stage | Client SQL | Fresh connections | Sample time |
|---|---:|---:|---:|
| Request locator, Turn/binding, eligibility | 27 | 6 | about102ms |
| Fresh issue proof | 27 | 6 | 98.8ms |
| Fresh resolve proof | 27 | 6 | 97.0ms |
| Total | 81 | 18 | 297.5ms |

The total comprises68SELECT and13SET,18commits and no pool checkout. Each issue
and resolve costs: qualified Task header8, latest Run7, request suffix4, lease1,
binding2, Turn5 SQL. Earlier actual Harness samples measured about0.4s activation
and zero per-frame SQL at10/100frames. These are local samples, not p95 or
provider-to-browser first-token measurements. Bootstrap, command admission,
HTTP grants, provider and SDK costs were excluded from activation accounting.

One matched quiet cycle costs Session13SQL/4connections, Task12SQL/3connections,
AG-UI13SQL/2connections with the current Run checkpoint prepared. Dividing by30s
implies0.433/0.400/0.433 SQL/subscriber/s, before other HTTP/command costs. Earlier
AG-UI10SQL observation lacked its current checkpoint and is a lower bound.
No ten-minute or100-subscriber result is inferred. Owned fixtures were cleaned;
no source files changed during the audit.

## Slice1: explicit bounded fresh proof batch

Reuse existing connection-level queries in an explicit short READ ONLY
REPEATABLE READ transaction. Keep locator, issue and resolve snapshots separate;
resolve must observe mutations after issue. Return bounded typed data to existing
Worker validation rather than duplicate its domain rules. Retain256headers,
1MiB/2s source bounds and2048/1MiB Turn bounds plus namespace/schema guards.

Aim for18 to about3 connections and13 to3 SET statements. About71SQL would still
remain, so this slice alone does not meet the quiet SQL target. The initial
implementation retains four fresh locator/eligibility/issue/resolve snapshots;
no sink lifecycle extension solely to save one socket. Report measured totals
and any gap against the original three-connection target. Measure from
before request eligibility through activation, alongside callback-to-browser
and full invocation-to-browser latency; never remove proof time from TTFT.

Do not implicitly borrow through connect_task_io: it deliberately opens fresh
connections and current methods reset isolation, so naive borrowing conflicts
with transaction state. Use explicit helpers first. An installed pool is a
later option only with proven DNS/borrow/query/cancel/return deadlines and
connection release. No new dependency is required.

## Slice2: complete source-qualified frontier

Combine existing full membership, index, coordinate/order, lineage/handoff and
coverage qualification into one explicit SQL result that includes highwater
and status. If the qualified frontier is unchanged, skip empty replay and the
separate status query. Changed frontiers use existing bounded pages. AG-UI
must qualify canonical source, Run anchor and checkpoint frontier together;
projection state alone cannot grant authority. Targets are2-4 client SQL per
quiet cycle and measured <=0.2SQL/subscriber/s over600s steady observation,
including authorization refresh. Startup/reconnect totals are reported separately;
the matched-v1 inclusive total SQL reduction gate remains >=80%. Historical source qualification
may still scan O(history); do not claim constant work or solve by longer sleeps.

## Invariants and required validation

- Independent issue and resolve snapshots reject intervening coverage, Run or
  anchor, ordinary call, Turn, epoch/token/owner, Host digest/identity/expiry
  mutations; legitimate renewal and trusted ancillary PublicExpression work.
- Preserve namespace/schema isolation, count/bytes/time limits, snapshot
  consistency, cancellation and connection release under errors and deadlines.
- Terminal drain, handoff and missed-hint recovery remain correct; frame SQL0.
- Actual signed HTTP plus SDK comparison counts all client SQL with equivalent
  offered/completed work. Measure ten-minute idle and1/10/100 subscribers,
  realistic source history and first-token latency. Report source scans,
  connection count and tail latency separately from SQL statement reduction.
- Fresh SPEC then QUALITY review precedes local commit/integration. Full total
  SQL/TTFT and strict coverage <=1000 remain independent acceptance gates.

## Path and sequencing boundary

At claim explicitly transfer only readonly COV paths: postgres agent_tasks,
task_replay_headers, task_admission, worker_replay_reader, leases and
stream_read_preflight; declare focused batch/head modules before writing.
Worker transient_output_runtime/composition and narrow Session/Task/AG-UI
readers/contracts may change. Recorder, mutation and proof writes remain outside
this task. One owner/branch/worktree; no overlapping CLIENT implementation.

Estimated additional work80-150k tokens and6-11 effective hours for the two
slices, subject to native regression results. This is an estimate, not a cap.

## Slice2 readonly audit and implementation guardrails

The quiet-path trace counts Session empty page3 plus Task lookup1, qualified
Task header8 and Session status1; Task empty page3 plus qualified header8 and
status1. AG-UI Run header6 plus prepared checkpoint head7 currently omits the
full membership proof on an empty page. The consolidated head must add that
proof, so the current13 statements are not equivalent authority. These counts
remain single-cycle observations rather than long-running acceptance.

One SET plus one metadata SELECT is plausible using bounded membership rows
and aggregates/EXISTS/LATERAL. Reuse existing qualification predicates: root
and active membership, <=256 ordered predecessor-linked Segments, ready source
frontiers, exact source/index counts and coordinates, canonical Segment order,
durable handoff scalar origin and Task-wide coverage presence. Preserve Run
executable/control/legacy selection, duplicate-anchor rejection and stop
coordinate; checkpoint scope, last source and latest/terminal frame guards.

Return requested Session position/status separately from active Task position.
A parent Session after child handoff retains its original cursor. Unchanged
highwater never justifies skipping privacy, status or source-integrity checks.
AG-UI must capture canonical qualification, requested Run and checkpoint in
one fresh snapshot, including absent/pending/control/legacy cases. Existing
metadata97 coverage view includes malformed/null admissions; certificate or
admission validity cannot replace coverage presence. No migration is expected.

Required native regressions include same-highwater corruption/privacy/status
changes, membership/index/order/handoff failures,257-member rejection, parent
handoff, silent-event advancement, missed hints and terminal draining; stale
or ahead checkpoints, wrong Run/scope, missing frame source references and
zero-frame positions. Test with a restricted metadata-only role. Ten-minute
1/10/100 idle measurements report600s steady SQL (including hints and grant
refresh), startup, reconnect and inclusive total separately; report observed
subscriber-seconds, history scans and latency too.
Transient authority remains separate and expires at the minimum of30seconds,
Lease expiry and Host expiry. Head consolidation cannot extend that authority.

Exact slice2 source/core/API/integration/test ownership must be amended before
writing; this audit grants no new source paths.

Idle acceptance must distinguish no-generation quiet streams from a paused,
open provisional generation. Slice1 API qualification costs32SQL per refresh;
a2SQL source head alone cannot meet an inclusive0.2SQL/subscriber/s target
if fresh authority repeats every30seconds. Count all Host/Lease/source refresh
queries. If this remains above target, add a narrowly claimed consolidation
follow-up; do not extend authorization expiry or polling to hide it.

## Slice2 implementation choice and measurement boundary

The optional Postgres-only stream head uses one readonly SET plus one complete
source metadata SELECT for Session/Task. AG-UI uses the same fresh snapshot for
that proof, the shared one-SELECT Run header, and shared one-SELECT checkpoint
head:4client SQL including SET. This deletes a duplicate Run/checkpoint query
rather than maintaining two predicate implementations. Existing SQLite and
non-head fallback paths remain. Changed pages and frame delivery still execute
fresh source/privacy guards; an unchanged frontier is qualified on every cycle.

The Run consolidation retains an executable stop-position seek then point
header lookup in the same SELECT. Full stop-header projection had encouraged
covering-index scans with499 filtered rows in the1000-Event probe; joining the
scope had visited999 command rows before LIMIT. Scalar scope InitPlans restore
bounded index seeks without planner switches. Official1000/10000/100000 cases
with8MiBTOAST and a role lacking payload privilege pass unchanged physical
visit/filter/index assertions. Complete source proof still scans O(history).

Actual loopback HTTP probes use real RS256/registry/Postgres JTI admission for
each subscriber/reconnect. Trusted fixture bootstrap reuses a genuinely verified
15-minute Host envelope before SESSION_CREATED/Task/Turn construction. Native
Recorder/Harness model hooks and the actual checkpoint Consumer are fixture
boundaries, not full Worker/provider/SDK acceptance. One Run serves1/10/100
independent subscribers per route. The common600s window begins only after all
HTTP admissions and initial full-recovery notices; an independent timer closes
the observation. Count startup, reconnects, hints and real Lease heartbeats over
actual connected subscriber-seconds; persist start/end runtime/harness hashes.

A no-flush paused provider is distinct from periodic callback flushing. Redis
DISCOVER drops an expired descriptor after its30s authority lifetime; existing
writer renewal happens on the next flush. A permanently OPEN descriptor and
32SQL every30s must not be assumed. Measure actual qualification/reset/renewal
behavior; never extend expiry or polling to satisfy the SQL target.

Production command outcomes are part of the head budget: actual HTTP invokes
this guard even when the canonical frontier is quiet. The optional typed head
result carries outcome metadata captured with the same qualified source/Run/
checkpoint snapshot and actual Host identity. Reuse the existing Host parser,
including its legacy same-Task parent fallback; never replace it with cached
permissions. The optimized callable must match the concrete reader/store and
same database/namespace; custom adapters keep their existing fallback. Current
head cost is5SQL with outcome,4SQL without, not an inclusive SLO claim.

Healthy diagnostic and planned resume timelines are separate. Planned resume
uses the last complete SSE record ACK, a fresh JTI, then genuine Recorder status
progress and the actual checkpoint Consumer after all reconnect HTTP admissions.
Every subscriber must ACK the injected canonical output identity in a complete
record before the cell passes. Producer progress SQL is a separately named phase
and remains visible in total accounting. Preserve per-cell start/error evidence;
only a completed same-fingerprint600s observation may enter long acceptance.

## Actual HTTP idle and continuation workloads

Healthy idle and planned idle reconnect perform no injected canonical business
progress. Count every real HTTP/auth/Host/JTI/source/outcome/Lease SQL, startup,
reconnect and observation query over connected subscriber-seconds. Reconnect
must admit all subscribers, validate the completed-record resume cursor, execute
fresh qualified head cycles and deliver complete real SSE heartbeats. A socket
HTTP200 alone is insufficient. Apply <=0.2 SQL/subscriber/s to600s steady observation including authorization;
report startup/reconnect and inclusive total separately against matched-v1 >=80%.

A separate short continuation correctness workload appends one actual Recorder
PUBLIC_OUTPUT and runs the real Consumer after reconnect. Every subscriber must
consume and ACK that exact canonical event/output identity in a complete record.
All producer and consumer SQL stays in that workload's total; never subtract it
and claim an equivalent idle workload. These probes are component signedHTTP
acceptance, not full Worker/provider/SDK acceptance or a measured SQL saving.

The measured five-statement quiet snapshot and actual cold/reconnect overhead
motivate further total-cost reduction; a35s total is not the steady idle gate. The next owned follow-up composes a specific
single metadata SELECT plus SET from existing source/Run/checkpoint/outcome SQL
bodies and row validators. Standalone readers reuse those same predicates and
parsers. No generic query compiler, cross-snapshot authority cache or longer
polling/expiry is introduced. Conditional legacy parent recovery remains counted.
LATERAL composition requires renewed physical seek/filter/TOAST/restricted-role
checks; do not infer equivalent planner behavior from statement reduction.

## Authoritative metric correction2026-10-13

Spec section13 defines <=0.2 SQL/s for ten-minute **steady** supplemental reads,
including authorization refresh; section20.1 explicitly records startup/reconnect
as separate I. Full admission-to-convergence SQL has a separate matched-v1 >=80%
reduction gate. Earlier this focused plan incorrectly imposed <=120 SQL over all
startup/reconnect plus600s. That extra constraint is withdrawn as a plan error,
not a measured improvement or a change to the spec. Preserve all historical
probe totals and failure records; do not subtract costs to claim equivalent work.
Attempt11's130 SQL/startup65 over35s is a diagnostic, not a steady SLO failure.
Final harness must report distinct startup/steady/reconnect and inclusive totals.


The specific shared-fragment composition is implemented:2SQL including SET in
one fresh readonly RR snapshot for source/Run/checkpoint and compatible outcome;
standalone readers use the same SQL bodies and Python validators. Actual composed
100k plan retains physical Run point seeks while full SOURCE remains O(history),
with measured disk sort and a retained unchanged2s failure in attempt31. Positive
attempt34 does not establish stable100k or100-subscriber compatibility. Final
native/static gates and source SPEC/QUALITY review precede a pre-matrix freeze.
Then18 healthy600s cells (2modes x3routes x1/10/100 independent subscribers on one
Run) use exact reviewed runtime/harness hashes, without injected business progress
or reconnect during steady. Startup/post-window/total and actual Lease renewals
remain visible. Full Worker/SDK/browser and paired inclusive >=80% SQL remain open.

The first reviewed600 matrix stopped after two complete quiet Session1/10cells
and an actual100startup503. Narrow cumulative-deadline dispatch and explicit
readonly snapshot reuse are now followed by six real healthy100-subscriber5s
cells, all admitted/recovered with100unique peers. This is bounded startup proof;
paused qualification599/624/374SQL crossing5s steady is included unchanged.
Current source gates and fresh SPEC then QUALITY must assess refreshed frozen
hashes before retrying18healthy600cells. Prior successful cells remain historical
on their old hashes, not resumed as accepted current-runtime measurements.
All failed100attempts and inherited fixture reproduction stay visible. Shared
client actual27.14–28.30ms issuance is reported; no ramp/expiry/deadline change.

Post-JTI raw preparation now uses one explicit RR connection for original tenant,
source, mapping/latestRun/bind and requested-parent highwater helpers. Native
actual post-JTI1socket verified in64focused checks and all100Session/Task HTTP
operations across six short healthy cells; custom wrapped binding deny hooks and
SQLite/legacy/unknown callback/AGUI fallback remain. No query predicates removed,
mutation/auth/JTI/pool/executor changes or cross-phase mutable authority cache.
Second600attempt again stopped at100startup503; original92exception remains
unobserved despite diagnostic05 shortpass. Retain both partial matrices and all
fixture/validation failures. Fresh frozen-source SPEC then QUALITY required;
only subsequent18healthy600cells can establish the steady SQL gate.

## 2026-10-13 - Slice2 compatibility follow-up ready for independent review

Accepted ed796 frozen SPEC GO followed by QUALITY NO-GO is preserved: nominal
131 native checks did not cover custom namespace/highwater public hooks. Original
method identity guards now honor publisher and underlying EventStore hooks.
Raw/AGUI shared proof eligibility also honors native Task map/latest/header/Run/
checkpoint/Event/frame/segment/cell/page hooks, authority bind/bind_snapshot, and
old-signature prepare callbacks. Optional-head and restore consumers choose their
existing fallback before shortcuts; SQLite and explicit nonnative Ports unchanged.

AGUI one fresh request RR closes before tail/backpressure. Initial identity-only
Taskheader is allowed only after original native V2 binding qualified the same
Task in that snapshot; full checkpoint SOURCE remains mandatory. No auth/cache,
expiry/deadline/ramp/pool/executor/write change. Matrices06/07 real startup failures
remain: observed TimeoutError, respectively subscriber83 and73. Matrix06 measured
Hostqueue.563s/post-JTIqueue.903s and headentry parentremaining.126s. Matrix07 measured
Hostqueue.425s/post-JTIqueue.919s, parentremaining.316s and headexecute.1695s;
1socket alone did not establish capacity. Original unobserved failure92 remains
unclassified; no PG error inferred. Both prior partial600 matrices stay incomplete.

Native AGUI snapshot103/198.631s (011b), scoped dedup103/198.124s (222f), shared
compatibility2/12.113s plus affected104/217.825s (0562), callback25/15.141s (35e2)
passed without skips. Fixture failures and original f919 stale-hook proof remain.
Diagnostic08/matrix08 on222f are historical five-second evidence. Final matrix09
on35e2 completed six100-subscriber cells, each100 admissions/recoveries/distinct
TCP peers and actual post-JTI1socket; all1269 start/end/live hashes match. Lease0,
SLOFalse throughout: no600 steady, stable capacity or matched-v1 inclusive80% claim.

Current runtime SHA35e2ccb1daa5dcaa4ac2ea5fa6320ff42a75f35d5657457c482157b44c761c04.
New private source/safe-proof freeze precedes fresh serial SPEC then QUALITY.
Full make test,18healthy600 matrix, reliability/fullruntime/product gates OPEN;
no commit/integration/push/deployment. Historical literal make check artifact-only
Ruff failures remain distinct from passing equivalent current-source gates.

## 2026-10-13 - Canonical observation failure: bounded graceful-close fix

Reviewed289e freeze SPEC70/no-skips54.259s and QUALITY110/no-skips232.532s plus
47adapter probes passed. Matrix03 on35e2 then completed nine quiet600 cells;
pausedSession1 recovered before client RemoteProtocolError around291s. Observed
TaskIOconnect TimeoutError after successful resolver was nearby, but original
native server linkage/infrastructure cause remains unproven. Immutable failure
capture dc17dfda49c6f2f1f76d95da1c49107ca865b4316e7d2f9d719994dca485c097 retains
nine results/start/end maps and raw hash references;289e remains unchanged.

Harness-only capture records ASGI exception/leaf CLASS, phase and monotonic times
before original re-raise; cancellation remains separate. Failed windows now retain
scheduledend versus actualexit, completedLeasecount and incomplete/SLOFalse.
Capture gates01/02 each4pass/1unexecuted async-test registration failure retained;
repository asyncio.run convention fixed this; gate03 passed5/0skips .986s.
Controlled launcher01 failed missing tests import BEFORE native startup, retained.
Controlled02 on11af injected once only in native connect after real recovery at
fresh canonical Sessionhead: server ASGI TimeoutError during streaming followed
by client RemoteProtocolError. Partial30.1753s/requested45, Lease0/SLOFalse.
This proves controlled mechanism, not the original infrastructure cause.

One natural pausedSession1 diagnostic on11af completed actual steady600.000979s
(ended-started); observe return600.089277s includes cleanup; connected600.098204s.
Startup41/steady69/post0/inclusive110SQL, rate.11499981235,3Lease heartbeats,
1actualpeer/full recovery,0ASGI exceptions. No repeat or18-cell acceptance.

Minimal optionA changes only V2 pending.result typed TimeoutError/OperationalError:
check frozenGrant deadline/disconnect, emit existing draft reset then retryable
observation_unavailable notice with another boundary check, then graceful close.
Original finally cleanup remains; no automatic retry, sourcecache, provisional
continuation or Task failure. Unknown/custom/integrity errors and CancelledError
retain original behavior; outer deadline_frames unchanged. Existing HTTP consumer
already rejects premature StopAsyncIteration: earlier possible falsePASS concern
was unconfirmed and corrected, no redundant harness guard added.

Focused A gate01:6pass/7RuntimeError cleanup failures53.657s, retained. Direct
reader test closed Redis asyncclient in a second loop; test-only same-loop fix.
Gate02:13pass/0fail/error/skip52.224s. Six typedfault cases cover Session/Task/AGUI;
unknown/cancel identity and between-notice deadline/disconnect checks pass.
ActualHTTP controlled fresh-head connectfault requested600 emits complete SSE
reset then observationnotice, closes without ASGIexception, and triggers existing
healthy-window EOF assertion at30.189602s/Lease0/incomplete/SLOFalse. No weakened
subscription check, second natural600, fullmatrix rerun or infrastructure repair.

Current runtime1269 SHA a4b2e24b39abcfe32c4fd4d81b8f2a0be31c58db9e8e676249f5213161e2f743.
New focused test SHA a25706248158748594c8b377dfe337f7fed904447af57c75fdf3dff654290431.
Current-source Ruff/fullmypy/filelimits/eval/diff pass; literal make check exits2
on277Ruff findings, every location historical .artifacts copies/diagnostic scripts.
No archive/config modification. NEW private freeze requires fresh SPEC then QUALITY;
prior reviews are historical. Full make test,18healthy600, matched-v1 inclusive80%,
reliability/fullruntime/product acceptance remain OPEN; no commit/integration/push.

## User-directed component closure — 2026-10-14

Single frozen69 batch completed59P10F; literal make check GO. Consolidated
SPEC/QUALITY allow component local acceptance, with10 retained unresolved failures
and fullHTTP/fulltest/80/runtime/browser gates OPEN. Original172 evidence remains
93 current-source plus79 historical passes; currentv10072 GO and historical18 long
cells keep separate provenance. No further microfix/review/native loop.
After owned commits/local integration, claim independent RELAY with fresh migration
tail (currently100, prospective101); then capacity/GC and STOP.
