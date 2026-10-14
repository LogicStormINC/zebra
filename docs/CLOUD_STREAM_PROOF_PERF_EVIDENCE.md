# CLOUD-STREAM-PROOF-PERF-01 slice1 evidence

2026-10-13. Human owner Luke Ding; executor Codex. Base249f4e6d,
branch codex/cloud-stream-proof-perf-01. Local implementation evidence only;
new admission remains OFF. No push, deployment or paid provider execution.

## Change and retained authority boundary

One explicit StreamProofReader snapshot opens a fresh TaskIO connection and
READ ONLY REPEATABLE READ transaction under the existing cumulative2s deadline.
The snapshot delegates the existing Task header/source-membership, Run/anchor,
Task page, native binding-lineage, bounded Turn evidence and full-epoch lease
queries. No mutable authority result is cached, no store connection is implicitly
borrowed, and source predicates/count/byte ceilings are unchanged.

Worker activation uses four separately closed fresh snapshots: locator,
ordinary-v2 privacy eligibility, issue and resolve. The original aim was about
three; keeping locator/eligibility separate avoids introducing a sink-spanning
context solely to save one connection. Issue and resolve always reopen and
observe committed intervening mutations. API bind and each qualification obtain
one fresh snapshot apiece, including the immutable accepted command read.
Standalone storage callers retain their original transaction semantics.

The callback still binds the actual canonical Harness model request and open
Turn. Source membership/index/coordinate/order/handoff, strict coverage,
current executable Run/anchor, request suffix/attempt/call, full lease epoch/
token/owner/expiry and fresh Host self-digest/original identity pin all retain
their existing checks. Trusted distinct PublicExpression work and valid API
renewal remain allowed. No Recorder, appender or proof-write path changed.

## Actual local samples and scope

Attempt03 configured native suite:45 passed/no skips,92.90s. Its fixture includes
an oversized historical response, a timer fact between request and callback,
actual model hooks and10/100 provider frames; the historical response does not
hydrate during callback proof. Client SQL counters include SET statements;
actual libpq sockets and commits are recorded independently.

| Same stage, separate fixtures | Historical audit ffe8f38b | Slice1 base249f4e6d + worktree |
|---|---:|---:|
| Locator through issue and resolve SQL/call |81|72|
| Fresh connections/call |18|4|
| Commits/call |18|4|
| SET statements/call |13|4|
| Callback activation samples |297.5ms, one sample|124.1/120.8ms, two calls|
| Provider-frame SQL,10 and100frames |0|0|

The historical81SQL audit was recorded2026-10-13 on ffe8f38b and used a
different isolated fixture. The slice1 fixture has oversized history and a timer
fact. This is a historical same-stage comparison, not a paired same-fixture
benchmark; no latency improvement or p95 certification is inferred.

The slice1 two-call activation counter is144SQL/8sockets/8commits/8SET. Factory
initialization is measured separately:16SQL/3sockets/3commits/3SET,52.5ms. The
first callback including factory initialization is88SQL/7sockets/7commits/7SET,
176.6ms as the sum of measured non-overlapping stages. Factory plus both
activations is160SQL/11sockets. The entire measured two request/response flow,
including factory and canonical persistence/checkpoint work, is528clientSQL.
Setup/bootstrap/accepted-command submission precede that measurement; they
are excluded explicitly, so528 is not a whole signed HTTP invocation cost.
The earlier readonly297.5ms audit excluded factory/HTTP/provider/SDK too; no
inclusive old-vs-new factory or end-to-end TTFT comparison is inferred.

API actual native bind is18SQL/1socket/1commit/1SET,24.7ms wall time in
attempt05. Qualification against its actual Redis descriptor is32SQL/1socket/
1commit/1SET,36.8ms wall time. These include the source
qualification, binding, current Run/request suffix, Turn and lease reads. API
proof is not removed from future callback-to-browser or invocation-to-browser
latency accounting. No browser/provider-network p95 result is claimed here.

These are local samples, not a p95/capacity/SLO certification. Historical source
qualification remains O(history). Connection reduction alone is not quiet-read
acceptance: unchanged Session13/Task12/AG-UI13 SQL per30s cycle remains above
0.2SQL/subscriber/s. Slice2, total HTTP/SDK SQL/TTFT, ten-minute idle,
1/10/100subscribers, relay/quota/STOP and joint runtime gates remain open.

## Runnable checks and preserved failures

The configured native endpoints are loaded from the owned private0600 baseline
env file; credentials are neither displayed nor committed. Every native test
uses its own disposable database/namespace and Redis prefix; no FLUSHDB or
shared-service restart occurs. The retained logs/xml are under the worktree's
.artifacts/stream-proof-perf/attempt-* directories, outside committed sources.

- Attempt01: runtime15pass; selected-source mypy4clean. Native35pass/1fail82.29s.
  The failed current-anchor test monkeypatched the old store accessor, which an
  explicit connection helper correctly no longer calls. The test now appends a
  real durable newer Run command/anchor and verifies issue and resolve rejection.
- Attempt02:43pass/2fail91.47s. The new epoch-mutation test incorrectly incremented
  a UUID; corrected to a new UUID. Existing AG-UI blackhole recovery measured
  1.1919s against the unchanged1s assertion. No timing threshold or source
  behavior was patched. Runs briefly overlapped; contention is a possible
  explanation, not an established cause.
- Attempt03:45pass/no skips92.90s, including that unchanged AG-UI blackhole check.
- Attempt04: current native45 plus standalone binding/lease/Task/Worker callers:
  138passed/31skipped144.80s. All31 skips require the absent header_scratch env:
  resource-binding7, scalar-header11, bounded-Worker-replay13. They are not
  counted as verified by that run.
- Attempt05: newly owned isolated PG17.5/header_scratch on localhost32786,
  configured31 formerly skipped cases plus6 portable header/Worker cases, API proof and
  isolated unchanged AG-UI blackhole check:33pass/6fail/no skips30.64s.
  All11 scalar-header and13 native bounded
  Worker-replay cases pass; API proof and isolated blackhole pass. Resource
  binding1pass/6fail because its fixture adds a second thread to the already
  thread-bound command fixture; existing scope validation rejects ambiguity.
- Attempt06: clean accepted base249f4e6d CLIENT worktree reproduces the exact
  same resource-binding6fail/1pass7.39s. DirectControl/fixture/policy are unchanged;
  no unrelated ambiguity fix or permission weakening was made.
- make check passed:3022files/no size violations, Ruff clean, mypy1265source
  files clean, deterministic eval30/30. Final attempt07 repeats all checks GO.
  Full make test is reserved for completed
  two-slice PERF/overall integration, not claimed by this slice.

Native checks independently exercise issue-to-resolve coverage/index and full
lease epoch/token/owner/expiry changes; existing suites exercise current Run,
Turn, actual call and Host mutations plus valid renewal/ancillary expression.
Repeatable-read consistency, later-snapshot freshness, foreign namespace,
foreign-schema rejection, read-only transaction mode, escaped snapshot closure,
and inherited0.1s TaskIO cancellation/release are checked. A cancelled snapshot
cannot extend the parent deadline; its connection closes and a new snapshot
still succeeds.

## Remaining review boundary

Configured final native45 and shared-helper checks, including the31 previously
skipped cases, are recorded above. Six unrelated inherited fixture failures are
explicitly baseline-reproduced. The owned scratch container is retained for
independent reviewers; its generated env stays private0600 and is excluded from
source/proof archives and commits. Frozen source/proof copies plus SHA256
manifest are under a private0700 slice1 freeze directory; raw logs/xml remain
private0600 and are not committed. Independent SPEC then QUALITY review precedes
any commit/integration. Connection-count improvement is not PERF completion.

## 2026-10-13 - Proof PERF slice1 accepted locally

Independent SPEC and QUALITY GO at frozen f9f777f344f6f2a12e4646b7e11743d2f7047c19281cad9ec4208fe6fd4df116.
Four fresh Worker snapshots reduce measured activation to72SQL/4connections;
factory16SQL/3connections separate; API bind18/qualify32SQL, each1connection.
FrameSQL0. Historical81/18 baseline uses a different fixture, no paired latency
claim. QUALITY native45/runtime15/shared48 plus4 lifetime scenarios passed;
SPEC native45/runtime15/shared30 passed. All22source/18proof live/archive hashes
verified independently. Six unrelated resource-binding fixture failures match
accepted249f4e6d. Scoped slice1 only; whole PERF and inclusive quiet target OPEN.
Post-review root changes only acceptance/governance docs before explicit owned
commit/local integration; no push/deploy. New admission remains OFF.

Private independent artifacts: spec-review-20261013 and
quality-independent-20261013-01 under .artifacts/stream-proof-perf. Existing
failure traces remain private; owned test passwords were rotated and excluded
env files refreshed before renewed checks. Frozen logs are unchanged and their
old credentials invalid. No production credentials or services involved.

2026-10-13 root: slice1f91906dc locally integrated into cloud-agent-trench;
primary native10/no skips18.702s. Fresh17dirty-file manifest hash-exact after
FF plus original41non-UI dirty hashes unchanged; current combinedUI hash exact.
No SDK changes/retest, push or deployment. Slice2 exact readonly source/core/API/
integration and two native-test paths claimed before code on same PERF card,
owner Luke Ding/executor Codex/branch codex/cloud-stream-proof-perf-01. Preserve
optional-port SQLite compatibility, fresh integrity/privacy checks, parent
Session coordinates and AG-UI full membership; inclusive quiet target remains
OPEN including paused-generation authority refresh.

## Slice2 implementation evidence - still OPEN

New source heads consolidate complete bounded membership/index/frontier/order/
handoff-origin/coverage presence and requested Session status into one metadata
SELECT. Optional read Port preserves SQLite/non-head paths. AG-UI now adds full
canonical membership proof even on empty observations, composing the shared
Run and checkpoint head inside the same fresh readonly2s snapshot. Final design
is2SQL/1socket for Session/Task and4SQL/1socket for AG-UI, including readonlySET;
actual final-path counts still require the complete rerun. Historical first
prototype measured AG-UI3SQL but duplicated Run/checkpoint SQL and was deleted.

Native attempts remain private and distinct. Attempt4 head11/no skips4.677s;
attempt6 tail10/no skips4.891s; initial bounds26/no skips9.522s. Broader attempt10
ran138/no skips317.865s:132pass and6new regressions. Three readonly query-shape
assertions required leading SELECT; three cold physical seek checks exposed
scope joins and full stop-header selection choosing broader covering scans.
No tests or planner settings were weakened. Ordered stop-position+point-header
lookup, scalar scope InitPlans and bounded Python source-row validation fix the
shared Run read. Official attempt13 cold1000/10000/100000 TOAST/restricted-role
checks3/no skips7.923s pass; final broader and HTTP checks remain pending.

Actual HTTP smoke attempt4 passed signed admissions on all three routes, but
its old2s requested timer observed15.318s Session/55SQL,15.289s Task/52SQL and
3.462s AG-UI/179SQL. These are distinct startup/reconnect/replay observations on
an earlier implementation, not600s acceptance. The179SQL total already exceeded
the entire120SQL budget of a600 subscriber-second cell, motivating consolidation
of shared Run/checkpoint metadata reads before long measurements. Earlier smoke
failures were fixture problems (bootstrap target/queue enrollment/missing Host
namespace); source/auth guards were preserved and failures retained privately.

Literal makecheck stopped on8I001 import-order findings solely in immutable
slice1 archived source copies. Archives were not changed or relocated. Equivalent
current-source gates passed with ruff --extend-exclude .artifacts, mypy1267 source
files, file-size gate3025 files and eval30. Final gates after remaining changes
and independent SPEC/QUALITY/freeze are still required. No commit/push/deploy;
new admission remains OFF and whole PERF/SQL SLO/product GO remain OPEN.

Slice2 actual HTTP revealed an additional production command-outcome read absent
from the original observer-only audit. It previously added7SQL/1socket per cycle.
The shared readonly outcome SELECT now composes with the source/Run/checkpoint
snapshot, reusing the Run and exact Host row parser:5SQL/1socket including SET
when the exact composed reader/store/database match;4SQL without outcome. Custom
readers or stores retain their callable fallback. Control, generation, receipt,
terminal and paired-handoff precedence remain unchanged. Attempt19 standalone
outcomes10/no skips pass. Attempt20 focused50:49pass/1new fixture failure from a
stale observation header; genuine projection refresh fixes the fixture. Attempt21
new composed-head check passes: same-frontier outcome changes, wrong workspace
and mutated binding digest fail closed. Full mypy1267 passes after this change.

Attempt14 broader136:135pass/1existing AG-UI blackhole recovery timing failure,
1.009334s against the unchanged1s limit. Isolated attempt15 and instrumented16
pass; attempt17 recovery0.901284s includes two actual asynchronous Redis waits
of0.251951s and0.252165s and78 client SQL. These are isolated recovery observations,
not a final broad-suite GO. Deadline/threshold checks have not been weakened.

Exact-timer HTTP attempt5 six2s cells passed transport/recovery on the earlier
composition: quiet Session/Task77SQL each and AG-UI186; paused Session/Task115
and AG-UI254. These remain distinct from newer evidence. Attempt7 six healthy6s
cells on one Run/one subscriber pass, with unchanged runtime/harness hashes:
quiet Session44SQL(startup44), Task44(44), AG-UI93(89); paused Session63(44),
Task63(44), AG-UI127(103). Observed windows6.007..6.101s; connected subscriber
seconds6.095..6.565. These short diagnostics do not establish600s SQL acceptance.
AG-UI startup89 plus5SQL/30s cycles already exceeds120SQL at one subscriber
before reconnect/Lease cost. No long matrix has started merely to confirm that
lowerbound. Further measured, narrowly claimed consolidation remains required.

Actual HTTP tracing attempt10 (healthy AG-UI6s, one subscriber) retains93/127SQL
quiet/paused, startup88/105. Exclusive quiet costs: HTTP target2, JTI/registry6,
Task access3, bind9, prepare3, qualified heads14, Page4, Event projection headers24,
Segment checkpoint15, per-frame Run2, post-Page source2, remaining tail6, factory3.
Paused adds19 actual temporary qualification SQL and one projected source position
(header/scalar/tail totals32/20/8). Initial proof/catchup/empty-head calls occurred
at0/.0307/.3842s quiet and0/.0294/.4024s paused; no30s steady cycle was observed.
This exposes duplicate fresh checkpoint head/frame/scalar reads during restoration.

The optional Event restore snapshot now shares existing readonly helpers inside
one fresh RR/2s context: captures exact head/frame, retains Segment membership and
cell metadata byte admission before bounded values, rejects expired/closed/wrong
scope/position reads, and releases the actual socket before any external frame
yield. Fresh Run guards remain per frame. Materializer preparation behavior is
unchanged; binding ledger reads occur only during its existing preparation path.
Attempt24 original checkpoint/observer plus new lifetime/byte checks:91pass,
8explicit missing-header-env skips,297.119s; retained runtime/harness fingerprints.
Attempt25 reruns with both private native environments plus cached deadline/int
regression. No native GO may be inferred from attempt24's skipped header cases.

Attempt8 separate canonical progress/reconnect correctness workload passes all
six10s cells with exact output identity and complete-record ACKs. Quiet total SQL
Session/Task220 each and AG-UI328; paused296/296/434. Each includes133 producer
Recorder/Consumer SQL, retained as offered-work totals. These are not the idle
workload, and subtracting producer SQL does not create matched idle evidence.


Authoritative metric correction: spec sections13/20.1 define <=0.2SQL/s over
600s steady supplemental reads, including actual authorization/renewal SQL.
Startup/reconnect are separate I; inclusive matched-v1 >=80% reduction remains
a separate full-runtime gate. Earlier all-in120 reasoning above is a historical
plan error, not the authoritative acceptance boundary. Attempt11 AG-UI idle-resume
130 total/startup65 over35.056753s is a diagnostic, not steady SLO failure.

Attempt25 original checkpoint/observer and new snapshot checks pass100/no skips
with both private native environments,301.644s. Attempt26 boundary/lifetime/byte
checks pass3,1.594s. Attempt27 native blackhole recovery passes at0.689943s/44SQL;
two actual Redis waits0.250356/0.251120s. Prior broader1.009334s failure is retained.
The specific shared source/Run/head/outcome SELECT now takes2SQL/1socket including
SET; standalone wrappers reuse the same SQL bodies and Python row validators.
Attempt28 focused native43/no skips passes; attempt29 original standalone physical
seek cases3/no skips pass,6.990s. Neither proves the composed LATERAL planner.

Actual composed100k-control/8MiB-history diagnostics: attempt30 passed the bounded
API and observed462.045ms EXPLAIN, but did not retain its full plan. Attempt31
failed the unchanged2s TaskIO deadline; that material failure remains unresolved
by its unavailable plan. Attempt32 was interrupted after an exporter Path error;
attempt33 bounded API qualified but exporter used the wrong pytest option name.
Attempt34 passes1/no skips,73.018s including owned fixture cleanup: bounded API
qualifies within2s; full private EXPLAIN saved before extraction. Query SHA256
00388e81da400fb7247988509ec07281a294527de9bc928f14ccc4715af17a39 matches33.
Execution487.194ms/planning16.316ms: SOURCE WindowAgg100006rows x1, external disk
sort26472KiB,6612/6619 temp blocks read/write, source Aggregate435.783ms.
Actual Run executable anchor visits2 candidates x1; stop and first-command seeks
visit1 each x1. NoPayload role executes the actual combined SELECT and fails
closed with InsufficientPrivilege: this is NOT successful metadata-only-role or
historical TOAST nonhydration certification. O(history) qualification and its CPU,
spill and deadline ceiling remain explicit. No optimizer settings, longer API
deadline, polling/expiry changes or query-filter test relaxation were used.


Timestamp-aligned healthy HTTP attempt12: quiet AG-UI/one subscriber,35.001537s
common steady window;59 startup SQL by actual start timestamp,4 steady SQL,
0 post-window,63 inclusive total. Short steady rate0.114281SQL/subscriber/s;
SLO remains false because the window is <600s, with no Lease renewal observed.
Separate idle-resume attempt13 observes35.062980s/34.913793 connected seconds,
117 inclusive SQL (61 startup/56 reconnect-window/0 post-window by SQL starts).
All actual admission, validated cursor, fresh source/head and complete heartbeat
continuation barriers pass; no steady SLO denominator for this reconnect workload.
Both retain unchanged start/end source+harness fingerprints. No long matrix yet.
Current-source gate attempt03 passes equivalent Ruff excluding .artifacts, full
mypy1267, file-size3025/0 violations, eval30 and diff-check. Literal make check
fails21 artifact-only Ruff diagnostics:8 immutable slice1 source-copy I001 plus
13 in historical attempt12 planner probe. Artifacts were preserved unchanged;
no root config or global ignore was introduced. Final affected regression runs
as attempt35; source reviews and600s acceptance remain pending.


Final affected native regression attempt35 passes187/no errors/failures/skips,
500.534s. Original100k checkpoint fixture233.674s (prior225.413s); original
Session/Task/AG-UI blackhole recovery tests pass. Instrumented AG-UI recovery
0.679128s/42SQL. Actual composed100k API qualifies within unchanged2s; full
private plan606.106ms, NoPayload role fails closed. Current query SHA256
b908cee6c64f5000e2d80b4ca9b30cfb2aa93ac6d613c6958cd5a2806ec59afe follows the
post34 whitespace fix; no retrospective query-hash claim for30/31. Negative31
and prior broader timing failure remain retained. Pre-matrix source review and
18healthy600s cells are pending; no whole-PERF/SQL/product GO or commit yet.


Reviewed matrix attempt01 stops after2 complete cells: quiet Session1 steady
600.001839s/50SQL/0.0833331 per subscriber-second, startup44/total94; Session10
600.000993s/392SQL/0.0653332, startup413/total805. Each has3 real Lease heartbeats,
0post-window SQL, all subscribers admitted and unchanged runtime/harness hashes.
Session100 fails startup HTTP503 before common steady barrier; no partial PASS.
Attempt01 freeze manifest b398abd32811c2ed79b7094d0ee46c834976065edef9a9f5b9b0a2243d0b1ea4
retains complete/start/error JSON and private raw-log hash reference. Whole18-cell
acceptance is OPEN; no source fix, expiry/ramp/window extension or production action.

Owned diagnostic01 records22admitted/4recovered, task_preflight_unavailable503.
Diagnostic02 preserves original async/thread callbacks and records48admitted/
21recovered; failing request47 has sequential thread queues0.195976/0.286007/
0.348198/0.454180s. Source-query work5us consumed0.348s dispatch; remaining request
deadline declines1.692/1.307/0.821/0.471s across submissions. Final async callback
CancelledError at0.471804s returns503; worker starts with0.016471s remaining and
raises TimeoutError after0.022426s. No OperationalError class; max queue0.483480s,
394 preflight worker operations and3265 SQL retained. This proves cumulative2s
startup deadline exhaustion through repeated thread dispatch, not steady SQL
failure. New diagnostic module is explicitly claimed before writing, non200 body
bounded4KiB, only allowlisted status/reason/retryable/index persisted. Production
source remains unchanged; review required before any new600s matrix.

## Startup dispatch and native connection follow-up, 2026-10-13

The original reviewed runtime stopped long matrix attempt01 after two accepted
quiet Session cells; the 100-subscriber startup returned503. Preserve attempt01
and all subsequent short failures: diagnostic01/02, startup-matrix01/02/03.
Diagnostic02 observed CancelledError/TimeoutError at the cumulative2s request
boundary after serial executor queues; no PostgreSQL OperationalError evidence.
One raw dispatch preserved tenant→source→prepare guards but remained insufficient.
Diagnostic04 measured constructor1.301s CPU (64.1% admission-loopCPU); shared
client candidate03 removed construction but still failed51admitted/2recovered.
Its actual offered spacing26.562ms was denser than the old32.117ms; neither
constructor reuse nor earlier isolated100 passes proved stable admission.

Final narrow readonly reuse combines raw Session→Task/latestRun/bind inside one
explicit StreamProofReader RR snapshot with original SQL helpers and validators.
Standalone bind/qualify remain fresh; custom/subclass, absent-reader, AGUI and
legacy paths retain fallback. Compatibility checks exact native Task identity,
DSN and bundle/database namespaces, including publisher-replaced store bundles.
Socket-generator telemetry separately records successful sockets, all establish
attempts and driver-connect elapsed; yield/send/return/failure regression passes.
Elapsed sums across concurrent requests are not wall time or historical estimates.

Focused native gate attempt10:49passed/0skips20.233s. Attempt09's fixture-only
TypeError required a dataclass input for actual publisher replacement; raw proof
retained. Attempt07 was a nonexistent test-path collection error, not a test GO.
The inherited local cursor fixture keyword TypeError reproduced on f919; its
minimal compatibility repair forwards the unchanged coverage flag. All original
Host/tenant/cursor/privacy assertions remain active.

Actual healthy HTTP startup matrix04 completes all6cells: quiet/paused ×
Session/Task/AGUI ×100subscribers on one Run, not100independent executing Runs.
All600-barrier requirements are still OPEN: these windows are only5.00s,
Lease heartbeats0, every slo_pass=false. All100 subscribers admitted/recovered,
100unique loopback peer ports verified, source/harness fingerprints unchanged.
Actual shared-client mean issuance27.14–28.30ms with configured25ms ramp.

| mode/route | startupSQL | steadySQL | postSQL | inclusiveSQL |
|---|---:|---:|---:|---:|
| quiet Session |4003|0|0|4003|
| quiet Task |4003|0|0|4003|
| quiet AGUI |5799|4|0|5803|
| paused Session |5279|624|0|5903|
| paused Task |5529|374|0|5903|
| paused AGUI |7804|599|0|8403|

Paused qualification crossing the common steady boundary remains counted, not
reclassified as startup. Actual driver-connect elapsed sums30.31–34.86s and
SQL elapsed sums31.79–67.76s are separate concurrent sums. No600steady SLO,
inclusive matched-v1 reduction, full Worker/SDK/browser/capacity or product GO.
Private exact attempts reside under .artifacts/stream-proof-perf; failed raw logs
remain immutable outside the sanitized review freeze. No commit/push/deploy.

Current-source gate attempt04: literal make check exits2 on42 Ruff diagnostics,
all paths under immutable .artifacts copies/probes; no archive/config changes.
Equivalent full Ruff excluding .artifacts passes; full mypy1267files passes,
file-size gate3025files/0violations, deterministic eval30passes. Explicit new
source/test lengths remain under500/700. Full make test is still a later gate,
not waived; source/frozenproof review and18actual600windows remain pending.

## Complete post-JTI raw snapshot follow-up, 2026-10-13

Long matrix02 on reviewed5130hashes stopped after quiet Session1/10 passed600s:
Session1 startup43/steady50/inclusive93, rate0.08333331; Session10 startup403/
steady392/inclusive795, rate0.06533314. Both had3Lease renewals, exact partitions,
full recovery and stable hashes. Quiet Session100 failed98admitted/15recovered,
subscriber92HTTP503 principal_binding_unavailable. Its gate had1connect attempt,
0success/0SQL; the exception was swallowed by the existing tenant gate. No
observed exception CLASS; no attribution to PostgreSQL capacity. Immutable
attempt02 manifest59fbe233201dc019cfdc708ec1c24c34c341270be229e3c0809776a662a7b42e
retains2completecells plus failing start/error and raw-log hash reference.

Diagnostic05 adds native mapping/binding/connect/resolver CLASS+deadline-only
tracing and actual Host authorization queue. It passes100subscribers/5s with
4003SQL/1502sockets and zero classifier exceptions; prior92cause stays unobserved.
Host queue max0.677615s, raw queue0.664587s; no production change at that stage.

The approved readonly follow-up keeps original tenant→source→mapping/latestRun/
bind/requested-highwater SELECTs and parsers in one explicit fresh RR snapshot.
Namespace/highwater wrappers factor their original SELECT+row parser only.
Direct-control snapshot eligibility requires exact original load method and reader
identity, native type, DSN and namespace; custom reader, instance/subclass method,
wrapped deny hook or database mismatch retains original standalone behavior.
Diagnostic timing moved below this compatibility boundary; inspect.unwrap is
not permission to bypass a wrapped custom hook. Core Ports remain optional,
SQLite/unknown callback/AGUI/legacy paths retain existing behavior. Entry/expiry/
post-authorization/exit2s checks remain; connection closes before stream return.
No appender/CAS/publication/proof writes, auth/JTI/executor/pool changes or cache.

Native gates11–15 retained:11collection NameError from postponed annotation;
12request fixture lacked is_disconnected;13actual socket count3 exposed coverage
runtime Protocol branch fallback (proof intentionally implements a narrower API);
14new cold after_sequence fixture expected400 despite existing stripping behavior;
15expiry fixture missed local UTC/datetime imports. Fixes preserve source/cursor
semantics: explicit proof branch without fake full-Port methods and a signed
future durable cursor. Final gate16:64passed/0skips40.374s, including actual
publisher-replaced full post-JTI1socket, parent future-cursor400, expiredHost403,
source guards and7native custom-reader/method/wrapped/subclass/DSN/ns cases.

Short matrix05 all6healthy cells complete100admitted/recovered/uniqueTCPpeers on
one Run; all1269 runtime/harness hashes stable. Original configured25ms ramp,
2s admission and60s recovery remain. Actual mean issue27.26–29.54ms. Every
short slo_pass=false and Lease0; no600acceptance or100executing-Run capacity.

| mode/route | startupSQL | steadySQL | postSQL | inclusiveSQL | total sockets |
|---|---:|---:|---:|---:|---:|
| quiet Session |3803|0|0|3803|1002|
| quiet Task |3703|0|0|3703|1002|
| quiet AGUI |5795|8|0|5803|1602|
| paused Session |5267|436|0|5703|1102|
| paused Task |5013|590|0|5603|1102|
| paused AGUI |7816|587|0|8403|1802|

Every100raw Session/Task operation has1actual TaskIO connection inside its
post-JTI worker interval. AGUI retains5peroperation. Boundary summary preserves
100complete recovery notices and100distinct ingress TCP ports percell; paused
qualification crossing5s steady remains included. Canonical actual-start export
SHA ec7073adc62fb60f268ee0aeea6dc0358eb2604398e5984dd7c3aac1c856c2cc uses
json.dumps(sort_keys=True, indent=2) plus newline; per-file hashes authoritative.
An auxiliary bare-Python export failed httpx import; harness uv start capture
succeeded before actualcase and is preserved, no fabricated prehash timestamp.

Current-source gate05: literal make check exits2 on87Ruff diagnostics, all under
historical .artifacts copies/probes; no archive/config edits. Equivalent full Ruff
excluding artifacts, full mypy1267, file-size3025/0violations and eval30 pass.
Fresh SPEC→QUALITY on refreshed freeze precedes any new18healthy600matrix;
full make test/inclusive matched-v1/fullruntime/product gates remain OPEN.

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

| matrix09 mode/route | startupSQL | steadySQL | postSQL | inclusiveSQL |
|---|---:|---:|---:|---:|
| quiet Session |3803|0|0|3803|
| quiet Task |3703|0|0|3703|
| quiet AGUI |5400|3|0|5403|
| paused Session |5242|461|0|5703|
| paused Task |5172|431|0|5603|
| paused AGUI |7590|413|0|8003|

Actual windows5.0645–5.0887s; post-JTI successful connection histogram{1:100}
for every route/mode. Source canonical serializer is json.dumps(sort_keys=True,
indent=2) plus newline. Complete safe records and raw-log hashes are retained in
.artifacts/stream-proof-perf/http-startup-matrix-attempt09/safe-cell-summary.json.

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

### 2026-10-14 matrix04 completed; full-suite gate remains open

Frozen a4b2: all18 actual600s steady cells pass;54Lease, alladmitted/recovered,
unique TCP peers/one post-JTI socket each. Root1269maps/1430freeze hashes GO.

| Mode/route/N | Startup | Steady | Post | Inclusive SQL | SQL/subscriber/s |
|---|---:|---:|---:|---:|---:|
| quiet/session/1 | 41 | 50 | 0 | 91 | 0.083333 |
| quiet/session/10 | 383 | 392 | 0 | 775 | 0.065333 |
| quiet/session/100 | 3803 | 3856 | 0 | 7659 | 0.064267 |
| quiet/task/1 | 40 | 50 | 0 | 90 | 0.083333 |
| quiet/task/10 | 373 | 392 | 0 | 765 | 0.065333 |
| quiet/task/100 | 3703 | 3862 | 0 | 7565 | 0.064367 |
| quiet/agui/1 | 57 | 50 | 0 | 107 | 0.083333 |
| quiet/agui/10 | 539 | 396 | 0 | 935 | 0.066000 |
| quiet/agui/100 | 5401 | 3814 | 0 | 9215 | 0.063567 |
| paused/session/1 | 43 | 67 | 0 | 110 | 0.111667 |
| paused/session/10 | 495 | 470 | 0 | 965 | 0.078333 |
| paused/session/100 | 5363 | 4220 | 0 | 9583 | 0.070333 |
| paused/task/1 | 40 | 69 | 0 | 109 | 0.115000 |
| paused/task/10 | 521 | 434 | 0 | 955 | 0.072333 |
| paused/task/100 | 5069 | 4429 | 27 | 9525 | 0.073816 |
| paused/agui/1 | 66 | 67 | 0 | 133 | 0.111666 |
| paused/agui/10 | 768 | 427 | 0 | 1195 | 0.071166 |
| paused/agui/100 | 7596 | 4219 | 0 | 11815 | 0.070317 |

Private safe-summary SHA572123c8628563abb837f7cc82ddd25ed0694e5dbdfc3e680b28a9fa406af2ef.
Clean validation literal make check: exit0. Original full make test: exit2 after
one inherited unbounded test oracle; partial9930pass/96fail/1fixtureerror/228skip.
Bounded oracle repair passes2native; remaining1825 cases run separately, not GO.
Local cloud=False guard now changes runtime to e28cf; old matrix is a4b2 evidence.
Cloud=True predicates unchanged per limited review; full current review pending.
One Run/100subscribers is not100executingRuns; matched-V1 inclusive80%/reliability
and full-runtime/browser/product acceptance remain OPEN. No push/deployment.
