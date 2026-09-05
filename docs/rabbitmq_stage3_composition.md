# Stage 3 — process composition and final acceptance

Owner: Luke Ding. Status: Review; isolated acceptance complete, not enabled in original services.
Parent: `rabbitmq_stage3_commands.md`, acceptance group 6.

## Composition boundary

Reuse the accepted bounded command consumer, confirmed relay, scoped recovery,
sanitized quarantine relay and exact runtime cleanup adapters. The process must
compose them with the **same actual CloudComposition DSN and deployment namespace**.
No separate lease authority, task database, control queue state machine or broad
Session container sweeper is needed.

- Default broker publish/consume flags remain false; the compatible fallback path
  remains available. Missing flags cannot initiate broker connections.
- Once a deployment has opted into durable admission, disabling broker publishing
  does not suppress the transactional pending/Outbox records.
- Receipt-aware DB pickup and broker pickup share the same claim/lease semantics.
  They replace the old normal recent-Session consumer for migrated deployments;
  the old consumer must not run alongside them or be re-enabled on rollback.
- RUN slots cover actual execution-Future lifetime. Independent cancellation,
  recovery and cleanup must not wait behind long model execution.
- Preserve existing child wakeups and memory-finalization recovery explicitly.
  Do not accidentally remove those responsibilities while replacing the loop.
- Shutdown stops new claims and drains real work; it must not pretend that a
  Python thread has stopped because its awaiting coroutine was cancelled.
- Runtime identity and exact cleanup use the same pinned engine configuration.
  Startup migration/backfill and operator historical retirement remain explicit,
  not side effects of accepting a normal request.
- Mode changes require explicit quiesce/drain, operator cutover, then restart.
  No live hot-switch is promised while the old scanner is executing. An old loop
  observing a new migration marker stops polling and drains rather than starting
  another old command. This guard does not replace the quiescent cutover boundary.

## Preserve the old fixture database

The retained `rabbitmq-product-e2e` PostgreSQL volume contains the earlier Stage 2
`zebra_e2e`/`trench_e2e` pair, including an earlier unreleased v35 checksum. Do not
rewrite its migration ledger, drop the database, or use `down -v`.

The proposed fresh Stage 3 pair is exactly `zebra_stage3_e2e` /
`trench_stage3_e2e`, on the same owned test PostgreSQL instance and role. Extend
the existing test fixture to select only these two fixed database pairs and
validate all three DSNs (container Zebra, host Zebra, host Trench) consistently.
The current Trench fixture hardcodes `POSTGRES_DB=trench_e2e`; it must honor the
validated pair, not merely accept a new host DSN that it then ignores.

For the retained volume, create missing allowlisted databases with autocommit
after verifying the owned endpoint and role. Existing databases are preserved;
an init SQL edit alone does not run again on an initialized volume. Record the
old migration ledger digest before and after. Apply current migrations and
bootstrap authority only in the new Zebra database, Trench migrations only in
the new Trench database. Reuse the retained run's private credential dictionary;
regenerating fixture secrets would mismatch the existing PostgreSQL volume.

The fresh pair was created on the owned PostgreSQL endpoint with owner `e2e`.
The retained Zebra migration ledger SHA-256 before creation was
`782f744c5473a0060bf152da345cb03ff4d601db2a50f3bea731f708fc27bfb7`.
No database was dropped or ledger rewritten; fixture selection/migration and the
post-run digest comparison were separate checks. Zebra's fresh database now has
48 migrations through v48 and its isolated control-plane epoch; Trench's fresh
database reached Alembic `5e6f708192a3`. The old Zebra ledger digest still matches
after migration. At that checkpoint, fixture selection, Host registry bootstrap
and process activation were pending; later acceptance is recorded below.

Before any fresh-pair worker startup, the parent verified the exact loopback
host/port/database/role and zero `session_events`, then explicitly invoked
`begin_command_backfill` for `rabbitmq-product-e2e`. It returned `complete` with
no historical high-water mark: durable command admission is enabled only in the
new empty database. This was an operator fixture step, not an application
startup side effect or an old-database cutover.

Keep project/network names, source mounts, approved ports, TLS CA, runtime
workspace child and synthetic identities within the existing isolated boundary.
Never reuse the user's browser token or source credentials.

## Dependency probe (observed)

On 2026-09-04, an ephemeral read-only, no-network container using the retained
pinned worker image inspected installed modules. Results:

| Module | Present |
|---|---|
| `psycopg` | yes |
| `ag_ui` | yes |
| `aio_pika` | no |

The container exited and was removed. No original container was changed. Source
mounts alone therefore cannot enable broker worker composition with this image.
Build a new isolated dependency image from the repository's locked requirements
or a test-only derived layer; verify its digest/imports. Do not install packages
at application startup or silently mutate the original acceptance image tag.
Current `uv.lock` records aio-pika 10.0.1, aiormq 7.0.0 and pamqp 4.0.1; the build
must use the complete locked dependency closure, not just copy host macOS wheels.
The existing production Dockerfile uses `uv sync --frozen --all-packages --no-dev`,
which does not select the optional `rabbitmq` extra. Rebuilding it unchanged is
insufficient. The local dry-run of that command with `--extra rabbitmq` succeeds;
provide an explicit image-build selection while preserving the default image.
The image context also needs to exclude nested local secret files: the old
`.dockerignore` excluded `docker/.env`, but not `docker/rabbitmq/.env`. Do not
send that file as build context or include it in an image layer.
The first build attempts hit the desktop credential-helper/keychain error
`-25293`. A private temporary Docker configuration with empty public-registry
auth entries and the existing CLI plugin path avoided automatic helper lookup.
Its explicit Unix endpoint matched the existing OrbStack daemon ID before use.
No user Docker credentials or login configuration were changed; the original
pinned public base-image references were retained.

The standard Dockerfile build subsequently completed using
`ZEBRA_INSTALL_RABBITMQ=true`, target `worker-engine`. The new, separately tagged
dependency image ID is
`sha256:d4572fbb045b2c38f9404a82b90026831ff8698f28d43987bea8bc5fab5cfcf7`.
A disposable read-only/no-network container imported the modules and reported
aio-pika 10.0.1, aiormq 7.0.0, pamqp 4.0.1 and psycopg 3.3.4. The retained image
tags were not overwritten. This is dependency/build evidence, not a running
worker or cross-service acceptance.

## Pre-implementation entry-point audit

The original worker loop constructed the old normal command consumer.
Compose the replacement where the existing execution service and cloud bundle
are already available. Bind `execute_claimed_session`, with the same lease TTL,
not the entry point that acquires a new lease. Preserve child wakeups explicitly;
calling the complete old poll loop would reintroduce the old scanner.

For recovery, bounded `discover_command_pickups` pages can provide hints that
`resolve_command_pickup` validates against the canonical binding. Handoff leaves
the pending row pending until an exact handled receipt marks it done, so this
selector also covers claimed/unhandled work. Recovery must use its own cursor
and both command lanes, deduplicate verified scopes per page, and retain the
existing scoped recovery proof. Incoming broker scope is not authority.

Quarantine publishing uses `publish_diagnostic`, not the ordinary envelope
publisher, and relay credentials rather than the read-only consumer identity.
Track delivery callbacks, execution futures and memory-recovery work during
shutdown; close the shared model client only after those users have drained.
The worker entry summary currently prints `database_path`; redact the cloud
database target before enabling the new process, because a DSN may carry a
password. These are composition obligations, not accepted runtime evidence.

## Required final evidence

### Fresh-pair fixture checks (2026-09-05)

The fixture sub-slice passed independent SPEC and QUALITY reviews. Parent checks
passed 55 Zebra and 78 Trench cases. `select_database_pair` validates the old
configuration then copies it into one of the two exact three-DSN pairs;
`configure_broker` is a pure transformation using caller-provided credentials.
Trench derives `POSTGRES_DB` from that validated pair. The Host bootstrap keeps
the existing endpoint, namespace, role and source-import guards.

Rabbit credentials/flags are worker-only; defaults remain off. The test worker
has a ten-minute graceful-drain ceiling. The additive initialization SQL is for
fresh volumes only and does not modify retained volumes. The operator retained
the original credential dictionary, selected the new pair and replaced the
three dependency-image IDs with the verified new image above. No secret was
rotated and no original tag was overwritten.

### Process composition checks (2026-09-05)

The process/configuration slice has 68 focused tests passing and `make check`
passing (842 typed files, 10 eval cases). The parent independently ran the four
PostgreSQL composition tests: 4 passed in 3.01 s. They exercise persistent cutover
markers, actual DSN selection and mutual exclusion of old/new consumers; they do
not run a real migrated worker process.

A disposable container using the retained worker image, read-only isolated source
mounts and `--network none` confirmed `aio_pika` is not installed. Importing the
current worker entry point and loading default settings succeeded; publish and
consume were false, scan fallback true, and `aio_pika` remained unimported.
The container exited and was removed. Independent reviews and real-process
fault/browser acceptance remain separate gates below.

The pre-quality-fix local regression snapshot completed with **3219 passed,
692 skipped in 88.91 s**. Infrastructure-dependent skipped cases are not counted
as exercised. SPEC independently passed 68 focused cases; QUALITY subsequently
identified shutdown admission and robust-consumer cancellation races. This
snapshot is therefore a baseline, not acceptance of the final corrected code.
The parent also ran all 17 `tests/agent_storage/test_postgres_command_*.py`
files against real isolated PostgreSQL schemas: **279 passed in 264.08 s**.
This covers the storage and cutover composition regressions, not the subsequent
shutdown/transport fixes or a real model process.

The corrected process slice passed incremental SPEC (65 cases) and QUALITY
(86 combined cases, plus four focused regressions). Shutdown now synchronously
closes new consumer admission while draining submitted Futures; cancellation
targets the originally registered RobustQueue, and repeated cancellation cannot
truncate the single shutdown sequence. CLI batch/cadence values actually apply,
with an explicit configured batch ceiling instead of silently ignoring them.
Final parent local suite: **3223 passed, 692 skipped in 77.99 s**. Parent actual
PostgreSQL/Rabbit relay/quarantine regression: **7 passed in 3.22 s**. These
accept the process/configuration code slice; fresh fixture wiring and the final
real-process/browser matrix are still open. Stage 3 remains 5/6.
Parent `make check` also passed: 842 typed files, all file-size/Ruff gates and
10 eval cases. An additional real broker check registered a consumer on the
empty isolated Zebra ready queue, cancelled its original queue registration,
reconnected that client and verified through the management API that the tag
was not restored. The client closed afterward; no broker restart, queue purge
or diagnostic message consumption occurred. A stale-module import in the
long-lived operator REPL failed before connecting on the first attempt; the
actual test used a freshly reloaded transport. All pytest runs used fresh
subprocesses and were unaffected by that operator REPL cache.

1. Default-off startup and migrated fallback-only startup without broker access.
2. Real PG/Rabbit handoff, duplicate delivery, loss of publisher confirmation,
   process exit after handoff/before ACK, and safe recovery terminal states.
3. Independent cancellation while RUN capacity is occupied, exact cleanup and
   preserved successor/unrelated instances; no engine IO inside DB transactions.
4. Poison/scope/generation rejection with no victim mutation, sanitized durable
   diagnostics, and healthy commands making progress after rejected candidates.
5. Rollback to receipt-aware fallback, preserved Outbox/Inbox and no duplicate
   external effect. Quiescent old-command retirement remains explicit.
6. Actual Trench → Zebra → worker → stream/replay → browser flow: new conversation
   starts only on send, stable route and title, visible incremental response,
   user isolation, real file publication and authenticated browser download.
7. Measure acceptance, pickup, first model token, first visible text and completion
   separately; Rabbit latency improvements do not imply faster model inference.

No item above is marked complete merely because supporting adapter tests pass.
Original activation, commit/merge and production HA are separate evidence levels.

## Fresh Stage 3 product evidence (2026-09-05)

The selected fresh pair, Host registry, authority broker, TLS, Zebra API and
worker are now active in the isolated project. A real migrated fallback-only
worker process first exited successfully after one idle cycle. The subsequent
worker uses publish/consume enabled and DB fallback disabled. Container-to-TLS
Trench readiness passed with both PostgreSQL and Redis ready. The original
services remain untouched.

The fixture subprocess helper now supplies `stdin=DEVNULL`: an actual PTY run
showed `compose exec -T` inheriting and consuming later operator REPL input.
Regression coverage verifies Docker and non-Docker subprocess calls; final
fixture check was 56 passed, with independent incremental QUALITY approval.

Real model, fresh synthetic users, API stream/replay:

- Conversation `conv_rabbit_34e88e23434d481aa7f7fa18eba40133`;
  Turn `3d9fdabf-42a8-4bc9-802e-ea345d802bf9`.
- Admission 102.483 ms, first text 5348.023 ms, complete 7963.227 ms;
  seven deltas, eight durable events, 260 answer characters.
- Duplicate submit returned the same Turn; disconnect/resume replay matched;
  another user was denied snapshot, stream, Turn read and cancel.

Real Agent-created file:

- Conversation `conv_rabbit_322972a4ed5e4fa6892e61ed9d17f962`;
  Turn `53df05dc-d284-4858-90aa-ee96b83afc61`.
- Admission 80.581 ms, completion 8487.883 ms. Actual `files.publish`, authorized
  asset listing and answer download link returned 54 expected bytes;
  SHA-256 `bea9490a25f74b2e1ecec83b301bcabb36b2d02767e6441e20c77359e7d95986`.
- Cross-user listing/download denied. No test-manufactured asset was inserted.
- After these two runs: Trench Turns completed=2, execution and broker Outboxes
  published=2 each, Inbox=2. Zebra pending done=2, Outbox published=2,
  handoff/Inbox accepted=2 each, runtime instances removed=2.

Actual headless Chromium against isolated Next port 3300:

- Two clicks on new conversation issued zero conversation POSTs. Sending created
  route `conv_1788542262522_f71ef9`; semantic title became
  `订阅信息整理十条已提供`. Reload preserved exact route and rendered answer.
- Seven distinct DOM text samples grew from 40 to 292 characters, first visible
  at 6879.300 ms, final sample at 9538.700 ms. No page runtime errors observed.
  This is rendering evidence, not a model-pickup latency measurement.
- A separate real file request created route `conv_1788542411623_dcf90e` and title
  `Stage3浏览器文件已发布`. Clicking the actual answer download link produced
  `stage3-browser.md`, exactly 35 expected UTF-8 bytes, no download failure;
  SHA-256 `7033a1e79313aed5214f530ef0d6e85b68c5a18b148112af60fc75a78b2f8712`.

Process fault harness under the fixture directory runs the real
`CommandWorkerProcess.run` in child processes with actual isolated PostgreSQL
schemas. Transport, deterministic executor and OCI cleanup are injected, not
evidence of real Rabbit ACK loss or engine cleanup. Parent initial 10 checks
passed in 20.81 s; SPEC and QUALITY independently approved the four process
scenarios (their six non-network checks passed, four PG checks skipped without
private DSN). Final exit-code assertions and further live broker/process
rollback evidence are tracked separately before closing group 6.

Final incremental process matrix: **15 passed in 19.91 s**, including all four
actual-PG subprocess cases and explicit expected exit-code checks after drain.
Both independent reviews approved the process semantics; the added exit checks
close the review's non-blocking suggestion.

Additional actual broker/process checks, without queue purges:

- Republished an already completed canonical envelope twice into the real ready
  queue. The running product worker drained it; all four existing command/start/
  handled/fence tuples were unchanged, with ready=0 and unacked=0 afterward.
- Quiesced the product worker, held one known completed envelope unacknowledged,
  restarted only `rabbitmq-infra-acceptance-rabbitmq-1`, and verified identical
  redelivery on reconnect. ACK on the old channel failed; the redelivered
  envelope was then ACKed. No diagnostic or unrelated message was consumed.
- Restarted the real product worker with publish/consume false, fallback true.
  New real-model Turn `1bd3ebbf-a895-4647-b5c6-5d202f0b835b` completed, replay and
  isolation passed: admission 78.422 ms, first text 5317.351 ms, completion
  7386.965 ms, six deltas. Existing receipts were unchanged. Its Outbox remained
  pending while publication was off, as required; no delivery intent was lost.
- Restored broker-only mode after draining fallback. That retained Outbox row
  became published without re-executing its completed command.
- Real-model cancellation requested immediately after a durable START on Turn
  `eace3441-1239-4163-b43e-7babf39e38b3`: HTTP acceptance 17.579 ms, final Trench
  status cancelled, canonical Zebra `session_cancelled` and `turn_cancelled`,
  control receipt cancelled, cleanup done, runtime removed. A previous manually
  timed cancellation raced ordinary completion; it is not used as proof of
  remote interruption. This real test covers one active execution; the occupied
  capacity independence assertion is covered by the deterministic process case.
- Asset-page browser download matched the reply-link bytes exactly.

Terminal fresh-pair state: Trench 5 completed / 2 cancelled, broker Outbox 7
published. Zebra pending 7 done / 1 cancelled (includes control intent), Outbox
8 published, runtime instances 7 removed, cleanup 1 done, control 1 cancelled.
Generated fault schemas remaining=0. Mounted application source digest is
unchanged across the real tests. Original Zebra remains only user-modified
`AGENTS.md`; original Trench tracked diff SHA-256 remains
`918bc8a6307051b39eec9439bea3b5c8c84ecc230851b32b1848d7a331e1fbc3`.

Stage 3 group 6 is accepted on the combined, separately labeled evidence above:
**Stage 3 6/6 = 100% isolated acceptance**. Single-node broker restart is not HA;
Stage 4 source scheduling and Stage 5 production hardening remain unaccepted.

Post-cancellation recovery regression also completed a new real-model Turn
`7b2cd2ad-8207-4653-b359-a3e4ba055354`: admission 64.564 ms, first text
5823.129 ms, completion 7416.932 ms, five deltas, exact replay and cross-user
denial. This confirms the worker remains usable after cancellation/cleanup.
The old database migration ledger was re-read after the full live sequence;
its version/name/checksum/applied-at digest still exactly matches the retained
pre-run digest above. No history or migration ledger was rewritten.

Eight real execution samples had PostgreSQL pending-row insertion → handoff-row
insertion intervals of 139.363, 119.430, 298.749, 102.918, 45.428 (fallback),
202.694, 162.879 and 182.455 ms. These same-DB timestamps approximate admission
pickup, not exact commit timestamps or a load-test p95. Recorded first model
request → first model delta intervals were 508.608–1083.501 ms; these use worker
event timestamps and are separate from browser first-visible text. The remaining
end-to-end delay includes Trench admission, authority/context/runtime preparation
and streaming/projection. No claim that RabbitMQ accelerates model inference is
made from these small samples.
