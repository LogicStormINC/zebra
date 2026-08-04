# CLOUD-LIVE-01 Redis Live Event Fan-out

Status: `In Progress`

Branch: `codex/cloud-live-01`

Target mainline: `zebra-cloud-trench`

## Boundary

This slice adds an ephemeral Redis Streams delivery seam. PostgreSQL Event
replay remains the durable authority; Redis loss, truncation or corruption must
fall back to replay and must not change Task, Event, Approval, Receipt or
Artifact facts. The adapter is not selected by API/Worker startup in this slice.

The stream key is versioned and scoped to the trusted deployment namespace and
Session UUID. The payload carries the namespace and canonical Event metadata so
an accidentally shared or tampered stream fails closed rather than leaking a
different namespace.

## Replay-plus-tail contract

1. Capture a Redis stream barrier before reading the durable PostgreSQL cursor.
2. Replay PostgreSQL Events from the caller's `after_sequence`.
3. Read Redis entries after the captured barrier.
4. Drop entries whose canonical sequence is already covered by the durable
   replay, while advancing `next_cursor` past every inspected entry.
5. Deliver only newer canonical Events and continue from the returned
   `LiveEventBatch.next_cursor`.

The barrier closes the handoff race: entries appended while PostgreSQL replay is
running remain after the captured Redis cursor. Redis does not decide whether an
Event exists; it only supplies a transient tail.

## Evidence matrix

| ID | Contract | Evidence | Result |
|---|---|---|---|
| LV-01 | Core envelope/cursor/batch are immutable and Redis-free | `tests/agent_core/test_live_event_fanout.py` | `19 passed` |
| LV-02 | Namespace/session isolation and barrier binding | `tests/agent_integrations/test_redis_live_fanout.py` | `PASS` |
| LV-03 | Durable duplicate filtering still advances cursor | focused regression for `LiveEventBatch.next_cursor` | `PASS` |
| LV-04 | Exact bounded XADD and strict schema/metadata validation | fake-client regression matrix | `PASS` |
| LV-05 | Package import and dependency graph are reproducible | `tests/agent_integrations` | `123 passed, 3 skipped` |
| LV-06 | Real Redis `8.2.1-alpine` publish/barrier/tail behavior | `tests/compose/live_fanout/run-redis-tests.sh` | `PENDING HOST EVIDENCE` |

## Host validation

Run from the implementation worktree:

```bash
cd /Users/lukeding/.codex/worktrees/cloud-live-01/zebra-agent
tests/compose/live_fanout/run-redis-tests.sh
```

The runner renders its Compose file, starts a dedicated Redis service on
`127.0.0.1:16381` by default, emits
`ZEBRA_LIVE_FANOUT_REDIS_TEST_RESULT=PASS` on success, and removes its network,
container and volumes in the exit trap. A PASS must be returned before this
card moves to `Review` or is merged to `zebra-cloud-trench`.

## Explicit non-goals

- API/Worker live routing or startup selection;
- `docker/compose.application.yml` or Zebra application images;
- PostgreSQL migration, Redis lease/fencing, Pub/Sub or a durable outbox;
- SQLite, Mem0, CopilotKit/Trench or production rollout.
