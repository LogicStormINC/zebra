# RabbitMQ stage 2 prerequisite — Trench Turn fencing

Date: 2026-09-04. Task: RABBIT-TURN-FENCE-01. Human owner: Luke Ding.
Branch: codex/rabbitmq-foundation-01, approved isolated Zebra/Trench worktrees.

## Scope and failure reproduced

The existing dispatcher checked worker names without a monotonic lease fence.
An expired worker, including a previous execution with the same owner name,
could renew or write after takeover. Broker multi-consumer activation would
increase this risk. This slice strengthens the existing database dispatcher;
it does not implement the separate broker Outbox/Inbox or activate RabbitMQ.

- Additive BIGINT `lease_fence`, default 0; claim increments it under row lock.
- Every worker mutation/read requires the claimed fence, matching owner, active
  status and unexpired database-clock lease. Public payloads do not expose it.
- Lock Turn then execution Outbox; check database time AFTER both locks.
  A real PostgreSQL test initially reproduced renewal returning true after
  expiry while waiting on the Outbox lock. It now returns false.
- Shutdown releases individual claim/fence pairs. Heartbeat loss or exception
  cancels the local stream without sending a stop for a successor's remote run.
  Explicit user cancellation still sends the existing remote stop command.
- Internal execution uses persisted principal/workspace/conversation identity,
  not identity fields in request JSON. Idempotent admission checks ownership
  before returning an existing Turn.
- Existing projection helpers moved out of the store to maintain source limits.
  No new dependency, frontend change or source-ingestion change.
- Repeated PostgreSQL runs exposed mixed admission/claim clocks: newly admitted
  work was temporarily unclaimable. Admission now uses DB time too. A deterministic
  SQLite extreme-skew test failed before the fix; real PostgreSQL claims also
  cover application clocks 60 seconds ahead and behind the database.

## Validation

Parent reran the following from the isolated Trench root:

```bash
PYTHONPATH=packages/models/src:packages/core/src:services/api/src:services/state_derive/src \
TRENCH_FENCE_POSTGRES=1 \
/Users/lukeding/Desktop/playground/2026/product/Trench/.venv/bin/python -m pytest -q \
  tests/api/test_trench_ai_turn_store.py \
  tests/api/test_trench_ai_turn_dispatcher.py \
  tests/api/test_trench_ai_turn_fencing.py \
  tests/api/test_trench_ai_turn_fencing_postgres.py \
  tests/api/test_trench_ai_product_api.py \
  tests/api/test_trench_ai_product_store.py \
  tests/test_benchmark_turn_pickup.py
```

**53 passed**: 16 focused store/dispatcher/fencing, 9 real PostgreSQL,
22 product API/store compatibility and 6 benchmark safety checks.
Scoped Ruff passes for all ten changed/new Python files. Zebra `make check`
also passes: size gate, Ruff, Mypy 791 source files, release eval 10/10.
The final 9-case PostgreSQL suite additionally passed three consecutive runs
(2.98, 3.00 and 2.90 seconds). These repeats are not distinct new scenarios.

Real PostgreSQL scenarios: two simultaneous claimants; same-owner takeover
rejects all stale mutations; renewal delayed beyond expiry by either Turn or
Outbox row locks; duplicate cursor projection is atomic; cancellation races
completion without duplicate assistant result; migration backfills an existing
Turn and its next claim receives fence 1.

Fixture: `trench-turn-fence-acceptance`, PostgreSQL 17.5 on loopback random port,
task label `RABBIT-TURN-FENCE-01`, tmpfs data. Each test creates and drops only its
random schema. It refuses an unlabeled container or non-loopback port. To
reproduce, start that exact disposable fixture with database `rabbitmq_fence`,
user `postgres`, password `fence-test-only` and the task label before the command.
The original Trench interpreter is reused read-only; sources are isolated.

```bash
docker run --rm -d --name trench-turn-fence-acceptance \
  --label codex.task=RABBIT-TURN-FENCE-01 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=fence-test-only \
  -e POSTGRES_DB=rabbitmq_fence -p 127.0.0.1::5432 \
  --tmpfs /var/lib/postgresql/data postgres:17.5-alpine3.21
docker exec trench-turn-fence-acceptance pg_isready -U postgres
# Run the tests above, then remove only the disposable test fixture:
docker stop trench-turn-fence-acceptance
```

## Remaining delivery gates

Independent spec and quality reviews pass after fixing the admission clock.
Spec re-review independently ran 13 fencing tests including all final 9 PG cases.
Quality review independently ran 23 tests including the then-7-case PG suite;
the parent's final run above includes the two additional clock-skew parameters.
No original database migration, service restart, merge or commit was performed.
Full Trench suite/browser E2E is not claimed. This protects local DB writes; it
does not claim exactly-once external tool effects or remote command fencing.
Deployment must apply the additive migration before the new code and drain old
workers before multi-consumer activation; old binaries do not enforce fences.
The disposable PostgreSQL container was stopped and automatically removed after
acceptance; its tmpfs synthetic data is gone. Original Zebra remains clean and
original Trench's tracked-diff SHA-256 is unchanged:
`918bc8a6307051b39eec9439bea3b5c8c84ecc230851b32b1848d7a331e1fbc3`.

Next slice: atomic business admission + broker Outbox, scoped Inbox + fenced
claim-by-ID handoff, bounded capacity, durable retry/recovery and default-off
composition. Then real PostgreSQL/Rabbit crash injection, Zebra command delivery,
source scheduling, rollout/rollback and browser cross-service acceptance.
