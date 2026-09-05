# Trench relay and recovery acceptance

Date: 2026-09-04. Owner: Luke Ding. Isolated sibling worktrees on
`codex/rabbitmq-foundation-01`; no original application switch or migration.

## Implemented boundary

- DB-clock, namespace-scoped SKIP LOCKED relay claims and monotonic relay fence.
- Publication occurs after commit. Only confirmed publication becomes published.
- Failed/unknown publication retries identical bytes/message ID/generation without
  consuming business execution attempts. Errors persist safe enum codes only.
- Expired owners and same-owner ABA settlement cannot overwrite a newer claim.
- Recovery serializes Turn, execution Outbox and latest canonical hint; only
  active, authorized, due work without a valid execution lease can recover.
- Published-unhandled and accepted-owner-loss recovery create a single next
  generation with stable business identity and prior-message causation.
- Scheduling failure can atomically defer/release the fenced claim and insert
  the next wakeup. Future hints, dead operations and terminal Turns stay closed.

## Evidence

- Combined relay/recovery and existing handoff suite: **60 passed in 6.32s**.
  New relay/recovery local coverage: 17; new real PG concurrency cases: 6.
- Spec review independently passed 23 cases. Quality review independently
  passed 17 local and 6 PostgreSQL cases; no critical/important findings.
- Real RabbitMQ + PostgreSQL acceptance: **1 passed in 1.43s**. Broker receives
  a message but the publisher intentionally loses its confirmation. Retry uses
  the same body, duplicate handoff obtains no second execution lease. After
  simulated owner expiry, recovery publishes generation 1 and obtains fence 2.
  Persisted publish attempts are [2, 1]; business execution attempts are 2.
- The live test explicitly advances only synthetic DB backoff timestamps. It
  uses the exact labelled disposable PG container and exact guarded loopback
  acceptance broker; it never connects to the user's application database.
- Scoped Ruff checks pass. Existing optional transport supplies mandatory
  publication/positive Basic.Ack semantics; no new dependency.

Tests in isolated Trench:
`tests/api/test_trench_ai_broker_relay.py`,
`tests/api/test_trench_ai_broker_recovery.py`,
`tests/api/test_trench_ai_broker_delivery_postgres.py`,
`tests/api/test_trench_ai_broker_delivery_live.py`.

Follow-up regression also passes in real PostgreSQL: 101 unrecoverable pending
hints precede one stale published hint; `sweep(limit=1)` reaches only that later
eligible Turn. Final PG delivery suite: **7 passed in 3.86s**. This is not a
latency benchmark. Original Zebra is still clean; original Trench tracked diff
hash remains `918bc8a6307051b39eec9439bea3b5c8c84ecc230851b32b1848d7a331e1fbc3`.

Slice acceptance: **6/6 = 100%** (relay claim, confirm/retry, stale fence,
recovery generation, atomic reschedule, independent/real-service tests).
Stage 2: **5/10 = 50%**. Consumer capacity/ACK, rejection diagnostics,
composition, complete fault matrix and browser E2E remain pending. Local code
acceptance is not runtime activation, merge or production HA evidence.

## Bounded consumer continuation

`RABBIT-TURN-CONSUMER-01` shares a semaphore between DB polling and broker
handoff. Reservation precedes database claim, transfers only after local task
creation, and releases on execution completion rather than delivery ACK.
Scheduler failure requires the atomic deferred successor before ACK. Ambiguous
commit/cancellation remains recoverable; ACK failure cannot release live capacity.
Quarantine is an injected async boundary, not yet a runtime implementation.

Parent suite: **65 passed in 3.07s**. Spec review: **28 passed in 1.51s**;
quality review: **28 passed in 1.49s**, no actionable findings. Existing runtime
and default DB polling remain in use. Source/test sizes are below limits.

Actual PG/Rabbit combined tests: **2 passed in 1.86s**. The new case publishes
two canonical Turns with prefetch 2 and execution capacity 1. The first task
blocks after handoff/ACK; the second Turn retains attempt_count 0 until the
first finishes. Both synthetic answers then reach persisted completed state.
The runtime is intentionally synthetic: this is not an LLM or browser test.

Consumer slice **5/5 = 100%**; stage 2 **6/10 = 60%**. No service switch.

## Sanitized quarantine continuation

`RABBIT-TURN-QUARANTINE-01` stores only generated UUID, configured namespace/role,
safe error code, SHA-256, byte count and DB timestamp. The receipt also supplies
the fenced diagnostic Outbox; raw input and attacker-supplied IDs are not stored.
Strict matching DTOs are separate from the business envelope. A dedicated
diagnostic exchange/queue is distinct from the restricted native raw DLQ.
Migration `5e6f708192a3` is additive and was applied only inside test schemas.

Spec review independently passes 11 Trench cases and 31 cross-copy/topology
cases. Quality review passes 11 Trench and 17 Zebra-only cases, no actionable
findings. Implementer combined Trench quarantine/consumer/transport suite: 61
passed. Zebra `make check`: pass, 792 typed source files and eval 10/10.

Parent actual PG/Rabbit suite: **4 passed in 2.56s**. New checks inject malformed
bytes containing a fake secret, observe only a safe confirmed diagnostic, verify
duplicate receipt/no duplicate diagnostic/no business mutation; verify actual PG
migration columns/PK/unique/index parity, eight concurrent identical receipt
inserts and parallel claim/same-owner ABA fencing. Both real relay ACLs and safe
diagnostic routing were exercised after provisioning the isolated test broker.

Quarantine slice **5/5 = 100%**; stage 2 **7/10 = 70%**. Composition/ORM registration
and fallback-off cancellation recovery G20 remain next. User services untouched.

## Managed composition validation (independent review in progress)

Default-off Trench composition now wires the existing fenced store, bounded
dispatcher, relay, consumer, diagnostic Outbox and independent recovery. Migration
mode requires workload authority. Invalid flag combinations fail closed; initial
AMQP connection errors do not block startup. A dedicated cancellation slot recovers
expired cancelled execution without invoking model execution. Cancellation requires
an exact-run AG-UI cancellation terminal, not merely stop-command acceptance.

Parent actual PG/Rabbit suite: **7 passed, 1 opt-in benchmark skipped in 4.90s**.
Added normal managed delivery with DB polling disabled, unavailable broker with
DB fallback, and live rollback: fallback starts before Rabbit handoff stops,
cannot steal a valid lease, then resumes the same run under fence 2 after local
shutdown. The final replayed answer is committed and Broker Outbox rows remain.
These scenarios use synthetic runtimes, not user credentials or a real model.

Same-run performance check: **1 passed in 78.76s**, 1000 Turns per route,
concurrency 8, serial admission with seeded 20ms nominal jitter. Both modes use
migration-mode admission, real PostgreSQL and the same managed runtime composition;
only broker publishing/consumption versus normal DB polling differs. All 2000 Turns
reach database completed state with one claim each. A former unconditional 250ms
sleep per published message was replaced by bounded, cooperative batch draining
and a 25ms idle wait before this measurement.

| Route | Commit-ack to claim p50 / p95 / p99 | Conversation creation + admission p95 |
|---|---|---|
| DB polling | 139.494 / 250.067 / 392.187ms | 30.105ms |
| RabbitMQ | 35.727 / 53.939 / 81.768ms | 26.760ms |

Pickup p95 improves by 78.4%, passing the stage-0 local pickup gates of at least
30% improvement, p95 at most 150ms and p99 at most 300ms. This is one controlled
local run, not a production capacity/HA result, HTTP acceptance measurement or
model/first-token/browser latency. Admission measurements include creation of the
synthetic conversation and therefore must not replace the earlier pure-store
admission baseline. They also do not establish pre-migration admission regression.

Reproduce from isolated Trench with the guarded synthetic PG/Rabbit fixtures:
set `TRENCH_FENCE_POSTGRES=1`, `ZEBRA_RABBITMQ_LIVE=1`,
`ZEBRA_RABBITMQ_LIVE_ADAPTER=trench`, `TRENCH_BROKER_BENCHMARK=1` and run
`tests/api/test_trench_ai_broker_delivery_live.py -q -s -k same_run_managed`.
Use `PYTHONPATH=packages/models/src:packages/core/src:services/api/src:services/state_derive/src`
from isolated Trench. Its existing Python interpreter is
`/Users/lukeding/Desktop/playground/2026/product/Trench/.venv/bin/python`;
before `pytest.main`, add the isolated Zebra optional transport dependencies with
`site.addsitedir('/Users/lukeding/.codex/worktrees/rabbitmq-reliability/zebra-agent/.venv/lib/python3.12/site-packages')`.
This only reads installed packages; never point the fixture at an original
application database or queue. The parent combined deterministic/real-PG suite
passes **142 cases in 18.87s**; this does not resolve a review finding by itself.

Initial spec review found a real-client defect: ordinary event reading stops at
the first terminal, so an earlier approval hid a later cancellation. The dedicated
`trench_ai_zebra_cancellation.py` observer now reuses the signed transport while
continuing past earlier terminal events; ordinary chat behavior stays unchanged.
Thirteen HTTP MockTransport tests verify actual grant signing, exact run binding,
no model/task writes, terminal ordering, idle/total deadlines and stream closure.
Spec re-review passes 56 cases; quality review passes 56 + 13 cases independently.

Final parent PG/Rabbit suite: **10 passed, 1 benchmark skipped in 7.45s**. Three new
tests run a genuine child process that calls `os._exit(17)` without cleanup before
handoff, after the Inbox/lease transaction, or after ACK. The canonical operation
then completes once. Dead lease expiry and recovery invocation are injected in
the synthetic schema to avoid waiting the full TTL; this is not a measured
automatic-recovery RTO. A first test assertion incorrectly expected internal
attempt_count in the public response; corrected to verify the authoritative ORM.
Management consumer counts can briefly lag close, so queue cleanup now waits at
most 10 seconds for observed zero consumers and still fails closed otherwise.

The 110-case existing product API/identity/assets/sources/timeline regression
suite passes. Zebra `make check` passes: 792 Mypy files and eval 10/10. Alembic
has a single head `5e6f708192a3`; complete offline upgrade SQL generation passes.
No original database migration was run. Original Zebra remains clean on
`cloud-agent-trench`; original Trench tracked diff fingerprint is unchanged.
Final combined deterministic/real-PG suite including the new signed cancellation
regressions: **155 passed in 19.16s**. Scoped Ruff checks and diff checks pass.

Slice **6/6 = 100%**; stage 2 **9/10 = 90%**. Group 10 (real-model/browser) awaits
operator confirmation for reuse of development model/workload authority in an
isolated environment. This is not full-plan completion; stages 3–5 remain pending.

After acceptance, confirmed zero AMQP connections and removed only the guarded
`rabbitmq-infra-acceptance` Compose container/network/test volume and labelled
`trench-turn-fence-acceptance` temporary PostgreSQL container. Disposable synthetic
data was discarded, not backed up. No original application container or data was
removed. Resume by recreating these guarded fixtures, then complete authorized
real-model/browser acceptance before moving through the remaining plan gates.
