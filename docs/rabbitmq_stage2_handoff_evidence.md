# Stage 2 — atomic Trench broker handoff

Task: RABBIT-TURN-HANDOFF-01. Date: 2026-09-04. Owner: Luke Ding.
Approved isolated branch: codex/rabbitmq-foundation-01 in Zebra and Trench.
Independent spec and quality reviews pass; completion is recorded in
[the completion ledger](rabbitmq_completion.md).

## Delivery boundary

This slice implements database handoff, not running RabbitMQ consumers:

- Separate `trench_ai_broker_outbox` and `trench_ai_broker_inbox`; existing
  `trench_ai_turn_outbox` still means execution delivery, not broker publication.
- Explicit `TrenchAiTurnStore(..., broker_namespace=...)` enables migration-mode
  atomic hint admission. No namespace means the old path does not access new
  tables. This is NOT the eventual broker publish flag. Production composition
  will persist admission hints independently of outbound availability.
- `accept_broker_wakeup` verifies canonical DB hints and principal ownership,
  then commits Inbox outcome and fenced execution lease together. Caller must
  reserve capacity before invoking it; actual semaphore/ACK wiring is a later gate.
- Polling and by-ID handoff share the same locked execution claim implementation.
  Duplicate handoff never returns another execution claim, even after expiry.
  The existing DB fallback remains the recovery path until generation sweeping
  is implemented. No message is ACKed by this database-only slice.
- Mismatched/unknown hints raise safe errors without touching a victim Turn.
  Consumer-level durable sanitized rejection remains pending; errors do not
  authorize ACK or raw dead-letter publication.

Migration `4d5e6f708192` follows fence migration `3c4d5e6f7081`. It only adds
broker tables/indexes and does not backfill or remove existing Turns. Backfill,
flags and rollout remain separate gates. No original service uses the new
constructor setting, and no original database has received this migration.

## Independent PostgreSQL check

Parent-owned test: `tests/api/test_trench_ai_turn_broker_postgres.py` in isolated
Trench. It reuses the previous guarded, loopback-only disposable PostgreSQL
fixture, creating a random schema per case. No live user identity/model call.

```bash
PYTHONPATH=packages/models/src:packages/core/src:services/api/src:services/state_derive/src \
TRENCH_FENCE_POSTGRES=1 \
/Users/lukeding/Desktop/playground/2026/product/Trench/.venv/bin/python -m pytest -q \
  tests/api/test_trench_ai_turn_broker_postgres.py
```

Fixture setup/cleanup command is in [fencing evidence](rabbitmq_stage2_fencing_evidence.md).
The original interpreter is reused read-only with isolated source paths.

Scenarios: simultaneous duplicate admission; broker vs broker and broker vs
fallback claim; forced INSERT failure at admission and handoff with complete
rollback; forged scope, namespace and changed same-ID contents; duplicate after
simulated owner loss with fallback recovery; additive migration preserving
existing Turns, with actual PG columns/PK/unique constraints/indexes compared
against ORM metadata.

## Verification results

- New tests: **37 passed** (25 SQLite contract/migration checks and 12 real PG
  cases). Independent spec review reran all 37 successfully after corrections.
- Combined targeted suite: **174 passed in 9.95 seconds**. This includes the 37
  new cases, 53 previous Turn/API/store/benchmark cases and 84 envelope cases;
  it is not a full Trench repository or frontend test run.
- Final 12-case PG suite additionally passed three consecutive runs: 2.93,
  2.83 and 2.72 seconds. These repeats are not new scenarios.
- Scoped Ruff passes all eight changed/new Python files. No new dependency.
- Zebra `make check` passes: size gate, Ruff, Mypy 791 source files and release
  eval 10/10. New untracked files were also checked directly for size limits.

Review corrections:

1. Broker publishing state was incorrectly named `leased` (execution Outbox
   vocabulary). A failing `publishing` regression preceded the one-line fix;
   pending/publishing/published now all support canonical handoff.
2. Escaped Unicode expanded a valid principal key beyond VARCHAR(640). Both
   reviewer and parent reproduced the failure in real PG. Canonical UTF-8 JSON
   avoids this artificial expansion; a 64-character CJK user and 64-character
   non-BMP workspace now admit and hand off successfully.
3. Canonical hint state is refreshed after all ordered locks; real lock-wait
   testing proves a hint marked dead during the wait never receives a lease.
4. Broker cancellation noop does not change the existing polling cancellation
   recovery path. Admission locks the conversation to serialize duplicate races.

Independent quality review reports no actionable findings; it separately reran
25 SQLite cases and inspected the PG tests. Real PG execution is evidenced by
the parent and spec-reviewer runs above, not claimed as an extra quality run.

Slice completion: **8/8 = 100%**; stage-2 acceptance groups: **3/10 = 30%**.
These are fixed-checklist completion ratios, not effort estimates or deployment
percentages. No commit, merge, original migration or service switch occurred.
Disposable PostgreSQL was stopped and auto-removed after validation; synthetic
tmpfs test data was discarded. Original Zebra remains clean. Original Trench's
tracked-diff SHA-256 remains unchanged:
`918bc8a6307051b39eec9439bea3b5c8c84ecc230851b32b1848d7a331e1fbc3`.

## Remaining stage-2 gates

Fenced relay and publisher recovery; bounded consumer scheduling/manual ACK;
retry and recovery wake generations; durable rejection/quarantine; composition
flags/backfill/fallback/rollback; integrated PostgreSQL/Rabbit failure matrix;
cross-service browser tests and measured latency. No whole-stage or production
completion claim follows from these DB tests.
