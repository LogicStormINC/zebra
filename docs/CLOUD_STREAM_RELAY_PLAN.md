# Cloud stream RELAY implementation plan

Claimed2026-10-14 from Ready after local component integration0f8c1716.
Human owner: Luke Ding; executor: Codex; branch codex/cloud-stream-relay-01.
Owned paths are the exact source/test lists below plus this focused plan and
AGENT_TASKS/PROGRESS/task_plan/WORKLOG governance. The reviewed proposal is adopted
with fresh migration tail100 and reserved additive101. Existing COV write ownership
explicitly transfers new session_streams notification fields and checkpoint
notification-before-ACK changes only; canonical append/Recorder/proof mutation
ownership remains unchanged. No push/deploy/business DB/paid provider access.

Full-runtime inclusive80% is a later gate including RELAY, not a circular
prerequisite. Retain PERF69=59P10F and eight unknown output differences plus one
preHTTP timeout; component acceptance does not certify fullHTTP/fulltest.
CAPACITY/GC, CONTROL/display ACK and immediate Task-wide wake are separate slices.

## Storage and migration

Reuse session_streams.current_version, not a per-Event outbox. Add published_through
(default-1), claim_owner, monotonic claim_fence, lease_expires_at, claimed_through,
next_attempt_at. Pending=current>published. Check -1<=published<=current, fence>=0,
claimed frontier<=current and all-or-none owner/lease/claim shape. Never reset fence.
Existing-row published=current is an explicit pre-cutover historical exclusion,
not delivery proof. ALTER/default/backfill/check/index in one locked transaction;
new sequence0 is pending. Both events._advance_stream and coverage batch CAS already
advance the row inside canonical/borrowed transactions: no appender/Recorder edits.

Fresh source tail100: projector_scoped_scalar_fanout via migration_catalog_tail.
Reserve additive101 for stream_hint_relay; preserve all historical migrations.
Add migration module/catalog entry; preserve prior checksums. Exact-version startup
validation means old-binary rollback requires an explicit compatible artifact/plan.

Due discovery uses namespace-bound indexable timestamps for both unclaimed backoff
and expired claims; no volatile clock in an index predicate. Capture DB time after
locking. SKIP LOCKED+LIMIT32 bounds returned rows, not scan visits: prove bounded
plans with many leased/not-due/acknowledged rows. Include index/WAL/HOT effects of
indexed current_version in append accounting despite zero additional append SQL.

## Claim, publication, settle and one total deadline

Fresh READ COMMITTED TaskIO claim/settle connections; reject an active same-DSN/ns
borrow_work_unit before opening (probe only, never enter/exit/close its wrapper).
Atomically capture current and increment fence; commit and close before Redis.
No source-row lock or caller-owned connection spans publication. Success settles
only exact ns/Session/owner/fence/claimed-through/unexpired DB lease, advances published
only through that claim and leaves newer appends pending. Failed/uncertain publish
keeps pending and schedules retry. Lost settle/cancellation leaves lease reclaim;
stale ACK/foreign identity cannot settle another claimant. Duplicate hints are safe.

One total monotonic tick deadline covers PG connect/query/commit/release, Redis
connect/TLS/send/read, and settle/retry. Central default tick budget2s; batch<=32.
Reserve cleanup time before issuing work; do not start another item without remaining
budget. An in-flight operation must be socket/query clipped, not merely checked
between items. If no budget remains for settle, leave the lease pending/reclaimable.
Reuse task_io_deadline and factor redis_transient_deadlines with a narrow time-only
redis_io_deadline context; effective deadline=min(current parent, current public-
output deadline if any, tick deadline). This carries time, never publisher authority.
Redis pool connection is exclusively checked out, clips its own connect/socket
options, resets on every send/read and restores/releases/disconnects on failure.
Never mutate pool-wide/global timeout options or shared reader/fanout sockets.

Create owned Redis publisher/client once per Worker lifetime, not per tick. Expected
transport/timeout/settle failure stays in relay backoff and returns fixed outcome;
it must not raise into shared maintenance exponential backoff or starve recovery.
Drain marks helper closed first, rejects new ticks, waits bounded active tick exit,
then closes only its owned client/pool. Repeated close is safe; never close a reader.

## Independent frontier key and actual consumers

Canonical frontier metadata uses a DISTINCT key suffix (for example :frontier).
Preserve original full-Event key, RedisLiveEventFanout.publish/read_after and local/
SQLite behavior. A legacy/custom full-Event consumer never sees metadata entries;
do not call parser failure plus degraded polling mixed-wire compatibility.
Cloud stops best-effort full-Event publication through cloud composition; upgraded
raw/AGUI/V2 readers wait for frontier hints and hydrate qualified PG content only.
Old consumers on the preserved old key retain their original durable catchup behavior;
no claim of receiving new full-Event live pushes from a metadata-only cloud writer.

Add optional canonical frontier capture/wait methods beside checkpoint notification
methods. Cloud StreamWake selects optional frontier methods before original full-
Event custom fallback. AsyncRedisNotifications exposes explicit frontier key choice;
replace canonical Session key with frontier in raw and V2's<=4-key wait set, never
add a fifth key. AGUI keeps checkpoint readiness key separate; V2's canonical wake
uses frontier. Checkpoint/canonical hints do not certify each other's readiness.
Malformed/cross-ns/frontier hints cause bounded reconciliation, never authority.

Frontier publication validates bounded namespace/Session/through/schema, uses atomic
Lua MAXLEN+TTL, no Event payload. Full-Event legacy publishing remains unchanged.
Task raw tail watches active Segment; other-member/parent appends retain existing
30s reconciliation, subject to healthy scheduler/deadlines. No extra member queries,
Task-wide notification promises, provisional content or private/coverage body relay.

## Checkpoint retry, fairness and callback policy

_notify_checkpoint reports success/failure in BOTH ready-head and new-head branches.
ACK only confirmed publish plus original summary/CAS/privacy/revision/frontier guards.
Old-head ACK cannot clear a newer requested frontier. Already-ready head re-notifies
without frame rebuild/recommit. No Redis failure enters projection_failed _defer,
which exhausts at8; no ACK on failed/skipped notification. Durable work stays pending.

Cooldown per EXACT ProjectionScope (ns/task/anchor/projector), bounded512 entries,
1..30s exponential jitter-free default; retain failure count across retry-at expiry,
prune entries idle>5min first, evict oldest when capacity reached. Eviction/restart
may retry earlier, never drop
pending or ACK. Cooldown check occurs in poll_once after setting _after_scope to the
candidate and before materialize_once. Continue to later scopes; wrap cursor after
empty page. Never let first failing scope block >32 later scopes; do not shortcut
scope validation. Success removes cooldown; transport failures do not alter durable
projection attempts or dependency_wait. Long outages retain retryable pending work.

Callback None permitted only explicit local/disabled policy. Cloud composition must
reject required missing callback before worker starts; consumer failclosed guard
also preserves pending if miscomposed. Do not treat None as publish confirmation.
If changing ordinary/coverage consumers, declare policy for both; existing local
and standalone tests keep their explicit no-notification baseline.

## Both maintenance entrances and cadence

One helper in WorkerLoopService invoked from maintenance_once AND poll_once. Due
eligibility at most once per1s; set next-at before work, nonblocking overlap guard,
expected failure isolated. CommandWorkerProcess background uses maintenance_once;
legacy run uses poll_once. Inline scheduling is a RATE ceiling, not1s delivery SLO:
long execution/other maintenance may delay calls. No new poller/process/dependency.
Existing0.1s AGUI bootstrap+ordinary/coverage polls, all empty relay/GC maintenance,
claims/setup/commit/settle/retries and WAL remain in later inclusive totals. GC is
not implemented here and not silently excluded from subsequent full-runtime gates.

## Claimed source paths (15)

1. packages/agent-storage/src/agent_storage/postgres/stream_hint_relay.py (new)
2. packages/agent-storage/src/agent_storage/postgres/stream_hint_relay_migration.py (new)
3. packages/agent-storage/src/agent_storage/postgres/migration_catalog_tail.py
4. packages/agent-runtime/src/agent_runtime/stream_hint_relay.py (new)
5. packages/agent-core/src/agent_core/ports/live_event_fanout.py (optional frontier Port)
6. packages/agent-integrations/src/agent_integrations/redis_live_fanout.py
7. packages/agent-integrations/src/agent_integrations/redis_live_fanout_async.py
8. packages/agent-integrations/src/agent_integrations/redis_transient_deadlines.py
9. packages/agent-integrations/src/agent_integrations/ag_ui/checkpoint_consumer.py
10. apps/api/src/zebra_agent_api/session_streaming.py
11. apps/api/src/zebra_agent_api/stream_v2_reader.py (canonical waiting key only)
12. apps/api/src/zebra_agent_api/factory.py
13. apps/worker/src/zebra_agent_worker/live_event_runtime.py
14. apps/worker/src/zebra_agent_worker/worker_loop_service.py
15. apps/worker/src/zebra_agent_worker/loop.py
COV write handoff covers new notification writes on session_streams. No recorder,
canonical appender, coverage finalizer, command outbox/cleanup or work-schema edits.
Typed config added only if actual configurable cadence/TTL is requested; bounded
central defaults otherwise. Any extra source path must be claimed before coding.

## Claimed tests and checks (no acceptance yet)

- NEW tests/agent_storage/test_stream_hint_relay_native.py: borrowed rollback/reject;
  sequence0/default and coverage batch; migration blocked writer before/after baseline;
  migration idempotence/rollback; two claimants/expiry/stale ACK/ns/owner/fence/shape;
  claim-old/append-new/settle preserves pending; commit-kill-publish/publish-kill-settle;
  failure/uncertainty/cancel; due-plan visits for leased/backoff/acknowledged rows.
- NEW tests/agent_runtime/test_stream_hint_relay.py: same tick deadline across Redis
  stall+PG settle stall; insufficient remaining budget; cancellation/no double settle;
  overlapping entrances/repeated drain/owned pool close; no global socket mutation.
- tests/agent_integrations/test_redis_live_fanout.py: distinct keys; actual old/full-
  Event reader stays unaffected; new frontier reader/schema/namespace; atomic TTL;
  reset/restore exclusive timeout including TLS; legacy/local publishing unchanged.
- NEW tests/agent_integrations/test_stream_frontier_notifications.py: async key choice,
  raw/AGUI/V2 replace canonical key with<=4 waits; old/custom reader call shape and
  durable catchup; cursor advances over duplicate/irrelevant hints without body read.
- tests/agent_integrations/test_ag_ui_checkpoint_consumer.py: ready/new-head failure
  beyond8 cycles then restart; no duplicate frames/ACK; cloud None rejected; >32 scopes
  first repeatedly failing/cooling while later healthy completes; cooldown512 eviction,
  exact-scope isolation/cursor skip/wrap; newer frontier preserved; local None policy.
- tests/worker/test_ag_ui_projection_work.py: both maintenance entrances/one cadence,
  expected relay failure still permits recovery; owned client once/start/drain/close.
- Native acceptance: rollback yields no hint; committed terminal recovers after kill
  without model/tool reexecution; transient10/100frames add zero PG relay rows/SQL;
  report all empty-maintenance SQL/WAL/connection costs and payload bytes. Then focused
  Ruff/mypy/file limits/diff and existing relevant tests; later full Worker/signedHTTP/
  browser/SQL80% acceptance remains independent and does not block implementation.

Migration compatibility tests: tests/agent_storage/test_postgres_migrations.py
and test_branch_migration_catalog.py may add only the new catalog tail or immutable
historical comparison for101. Preserve old oracle strength. Audit same-family
fixture/caller incompatibilities up front and declare any extra owned path before
editing. Run one coherent native/focused validation and consolidated review at
the slice end; do not resume per-test repair/review loops.
