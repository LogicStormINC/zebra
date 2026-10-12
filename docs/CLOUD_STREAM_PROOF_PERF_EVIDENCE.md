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
