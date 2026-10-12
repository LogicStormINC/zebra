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
quiet cycle and measured <=0.2SQL/subscriber/s. Historical source qualification
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
1/10/100 idle measurements count startup, hints, grant refresh and reconnect
SQL over observed subscriber-seconds; report history scans and latency too.
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
