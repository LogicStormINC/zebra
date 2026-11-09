# Redis AOF recovery and authoritative Turn observation (2026-10-24)

## Scope and current result

User authorized bounded Redis recovery, draft-observer isolation, no-model
regression, API activation and original Run status synchronization. No model,
search, task retry, database clearing or Search/MCP restart was authorized.

- Conversation: `conv_1792826364201_add73f`.
- Trench Turn: `d92c7d63-4d73-4735-916b-b5c135558399`.
- Run: `7d40e850-14a9-42e6-8bc7-7dc0e9bd178a`.
- Task/Segment: `96d1a13e-668f-4d8f-8f91-9cf374737100`.
- Original Zebra facts: 128 events; six model requests/responses; zero web.search.
- Actual execution ended at 2026-10-24 07:19:58 UTC. Worker lease released.
- Trench originally remained running, repeatedly reclaiming observation with
  `transient_prefix_unavailable`, not reexecuting the model.
- Original Turn has now synchronized to **failed**, observation problem null.
  No success was fabricated. Original events, Run identity and request preserved.

The product conversation was subsequently soft-deleted at
`1792827671670` (07:41:11 UTC). Its owner still matches the Turn. The deletion is
preserved. A normal history snapshot correctly refuses a deleted conversation;
we did not resurrect it or bypass ownership. Native owned Turn/observation reads
verify failed/null. The available browser is logged out; no authenticated page
acceptance is claimed.

## Roots and repair

### Redis persistence

`trench-redis` repeatedly exited while loading
`appendonly.aof.1680.incr.aof`; startup reported bad AOF format. At inventory it
had restarted 87 times. Trench API could not resolve/connect to its restarting
Redis endpoint, and all temporary stream publication failed.

Stopped only this Redis container. Archived its entire data volume, with modes
retained, before touching any data. Private backup:

`/home/ubuntu/releases/20261024-redis-observer/redis-data-before.tar`

SHA256: `cc324a0c69ea78c1446ce883ac10da696d34e9eb531548bf219dcf9899f0f62e`.

Native redis-check-aof on an extracted offline copy confirmed:

- Base RDB 75,700,435 bytes: checksum valid.
- Incremental AOF 5,241,331 bytes: valid through byte 5,239,854.
- Invalid suffix: 1,477 bytes; native fix truncates only this suffix.

The checker requires a writable file handle even in inspection mode, so the
initial read-only mount check could not open the RDB. It was retried only on the
copy. Native repair, subsequent whole-manifest validation and isolated
network-none Redis loading succeeded on that copy. Before replacement, `cmp`
proved every retained byte equals the original prefix. Replaced only that one
incremental file; base/manifest/dump and full original archive retained.

Restarted the same Redis container with the same image/config/volume. PONG,
loading=0, AOF enabled and last write/rewrite status=ok verified. No FLUSH,
volume removal, disabling persistence, package upgrade or global tuning.
The invalid suffix cannot be recovered from this AOF; do not describe recovery
as lossless. No PostgreSQL execution facts were removed.

Host rebooted at 06:08:56 UTC; AOF failure surfaced on startup. Current kernel
journal has no matching filesystem/I/O error. This does not prove why the
suffix became corrupt or establish a hardware fault.

### Temporary stream blocked durable facts

Shared dispatcher `_execute` opened/published Redis drafts inside the outer
execution observer exception boundary. Any draft error closed the upstream GET
before durable terminal events. `_heartbeat` likewise let Redis renewal failure
terminate observation before processing cancellation. Retrying observation hit
the same cache dependency repeatedly.

The smallest change catches only `TransientTurnUnavailable` at draft open,
publish and renewal boundaries. It disables drafts for that observation, closes
the temporary handle, then continues the existing admitted Run's authoritative
stream. Further draft frames are dropped without repeated attempts or SQL.
A new claimed observation gets its own fresh default state.

Database ownership reads, durable lease renewal, canonical writes, cancellation,
grant checks and upstream decoder errors remain outside this catch. Authority
loss still aborts. Redis/OSError/timeout during temporary-handle cleanup cannot
reverse a terminal fact; cancellation is not suppressed.

No schema, frontend, engine selection, model reasoning, v2 protocol, security
limits or Trench product semantics changed.

## Lock-conflict investigation: still open

Original sequence125 is a successful sixth model response (provider normalized
error null, tool_calls finish, one proposed tool). Both its model-call projection
and Worker progress head through125 exist. Subsequent sequence126/127 records
`LockNotAvailable` as generic model_execution_failed; no next tool execution.
Worker logs also show slow event/projection mutations and a checkpoint budget
timeout after canonical commit. These are storage/progress failures after a
successful provider response, not a confirmed provider outage.

No old transaction or blocking PID remains at inspection. Historical server
logs for this time are unavailable: PostgreSQL has logging_collector off and
its current process stderr points to /dev/null; Docker logs stop before the
current postmaster start. Worker continuation classification retained the error
type but not its traceback/SQL identity. Therefore the exact failed SQL,
historical holder and whether it competed with lease renewal, another writer or
projection work **cannot be established from the retained evidence**.

Task I/O uses a bounded lock_timeout up to50ms, which makes short contention
relevant, but this alone does not prove the original error arose on that path.
Do not increase timeout, suppress lock errors, auto-retry a model or rewrite the
failed result based on that hypothesis. A separate narrowly scoped diagnostic
slice should retain sanitized SQLSTATE, internal operation/stack identity and
lock-wait evidence without query arguments, credentials or full bodies. No
Worker/database configuration change was made here. The lock incident is not
claimed fixed.

## Validation and activation

Focused tests first reproduced seven failures (six terminal/cache combinations
and heartbeat cancellation), with an authority-loss control passing. After the
fix, 53 tests pass, zero skipped, using dedicated local Redis on32782 and
PostgreSQL on32783 plus SQLite. Coverage includes:

- Redis creation/publication outage with completed, failed and partial results;
- existing Run resume-only identity, no extra execution, one cache attempt;
- draft renewal failure still processes cancellation;
- DB ownership loss is not swallowed;
- real Redis scope, fencing, gaps, fixed TTL and corruption handling;
- one versus100 drafts retains constant SQL cadence;
- observation retries, durable Turn persistence and restart recovery.

Isolated local test containers and their anonymous test volume were removed.
Ruff passes with existing UP038 in untouched dispatcher retry expression
excluded; compileall and diff checks pass. No broad old-test cleanup.

Built from exact running backend after verifying all three original source
hashes, copying only those changed files. Image runtime configuration matches
its base. New image:

`trench-backend:redis-observer-20261024`

ID: `sha256:4189371860046904b649035eeb32e34230741bc2719e38b5fc2efa392ba1cfa4`.

Actual image passed a network-none no-model dispatcher failure check. That
self-check models store cursor-group idempotence; it is isolated test evidence,
not intercepted HTTP or a new real Run.

After zero active worker leases, pending commands and active Turns, recreated
only Trench API, preserving its complete prior Compose chain plus:

`/home/ubuntu/releases/20261024-redis-observer/trench-override.json`.

API healthy; all env/mount/security/runtime parameters and schema unchanged.
Frontend, Zebra API/Worker, Search, Yahoo egress and MCP retained container
identities/start times/restarts. Exa cooldown hash unchanged. Original event
hash stayed `e3a7b4630f7a25a8fe1b8c3b7b2d7a8cfb2d55cc9402694fa660e94ab93d5d42`.
All Turn status/answer/request/cursor rows unchanged across API activation.
Native owned read confirms original failed status and cleared observation
problem; restoration occurred naturally after Redis recovery, before API update.

Trench source commit `77bcb7f` on `codex/cloud-redis-observer-20261024`.
No push or main merge. Prepared repair is deployed; source awaits maintainer
integration. Preserve unrelated primary worktree changes.

## Evidence and rollback

Private operational evidence resides in
`/home/ubuntu/releases/20261024-redis-observer/`; safe copies and test scripts in
`.artifacts/cloud-redis-observer-20261024/` in the task worktree. Original Redis
archive is retained on the server, outside Docker volumes.

For API rollback, use deployment-plan.private.json before_files and recreate
only trench-api with the prior image, after an idle check. Do not restore the
known corrupt AOF merely to roll back application code. Do not reuse once-only
activation receipts for another deployment. Search/MCP are never rollback
participants in this slice.
