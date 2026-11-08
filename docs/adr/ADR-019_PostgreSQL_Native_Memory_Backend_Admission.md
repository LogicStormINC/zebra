# ADR-019: PostgreSQL-Native Memory Backend Admission

- Status: `Accepted`
- Date: 2026-08-02
- Task: `MEM-PG-NATIVE-ADMISSION-SPIKE-01`
- Verdict: `PASS` for architecture admission only

## Decision

Admit the PostgreSQL-native Memory Backend architecture for the next design and
implementation gate. The admission evidence proves that Zebra can keep Memory
authority, retrieval projection, deterministic operation identity, generation
fencing and scoped physical deletion inside one PostgreSQL boundary without a
Provider enumeration API.

This is a test-only architecture admission. It does not select PostgreSQL at a
runtime composition root, deploy a Worker, or make Runtime ready. The next
production implementation card remains `MEM-GW-PG-NATIVE-01` and stays `Locked`
until separately activated. Runtime, Worker, Provider HTTP, Desktop, SQLite
composition and Redis remain locked.

Mem0 is removed from the current Memory mainline admission path:

```text
Provider admission: DENIED
Mainline candidate: DEFERRED
Future re-entry: new upstream capability evidence + a new admission run
```

The historical `MEM-MEM0-RESET-SPIKE-01` remains `Blocked`, and the Mem0-specific
delivery consumer remains `Locked` and deferred from the active critical path.

## Candidate boundary

The candidate keeps all content-bearing state in one PostgreSQL transaction:

```text
Memory mutation
  -> authoritative Memory row
  -> retrieval projection (FTS/structured/vector payload)
  -> COMMIT
```

The authority row contains the opaque namespace, scope, generation, Memory ID,
operation identity and lifecycle state. The retrieval projection is derived and
must not be committed without its authority row. Audit records may retain
operation ID, Memory ID, scope fingerprint, generation, timestamp and result,
but never Memory text, summaries, embeddings or other content-bearing payloads.

The test schema is intentionally local to the admission Spike. It is not a
production migration and does not alter the existing `agent-storage` package.

## Mandatory capabilities

### Deterministic identity and recovery

Zebra creates `memory_id` and `operation_id` before persistence. The database
enforces one operation identity per namespace. If PostgreSQL commits and the
client loses the response, reconnecting with `operation_id` returns the one
committed result. Reusing the operation cannot create a second content-bearing
Memory, even when the retry carries a regenerated request ID.

### Authority and retrieval atomicity

The authority row and retrieval projection are inserted in the same transaction.
A failure while building the projection rolls back the authority row, operation
record and projection together. A successful commit leaves both rows present.
There is no asynchronous consumer or repair job in this admission path.

### Generation write fencing

Every write locks the scope row and checks the caller's expected generation in
the database. A writer that observed generation `g` cannot commit after a reset
has advanced the scope to `g + 1`. Read-time filtering alone is not sufficient;
the write boundary itself must reject the stale generation.

### Complete scoped physical deletion

Reset locks the exact namespace/scope, advances the generation, and deletes all
old content-bearing authority and retrieval rows before commit. The operation
audit rows remain because they contain no Memory content. No provider list,
`top_k`, global reset or best-effort cleanup is used to prove coverage.

### Cross-scope isolation and minimum recall

Namespace and scope are predicates on every authority, deletion and recall
operation. Identical Memory IDs in different namespaces remain independent.
Recall joins authority to its current-generation retrieval projection, excludes
deleted rows, applies optional topic/type filters, limits results with `top_k`,
and breaks ties by Memory ID. `top_k` is only a result limit; it is never a
reset, rebuild or deletion-completeness primitive.

## Capability matrix

| Capability | Evidence | Result |
| --- | --- | --- |
| Deterministic identity | Namespace-scoped operation uniqueness and pre-generated Memory ID | `PASS` |
| Ambiguous commit recovery | Commit, lose response, lookup by operation, idempotent retry | `PASS` |
| Authority/retrieval atomicity | Successful commit and injected pre-projection rollback | `PASS` |
| Generation write fence | Stale writer rejected after generation advance | `PASS` |
| Complete scoped physical deletion | Authority and retrieval content rows reach zero; audit remains | `PASS` |
| Cross-namespace isolation | Same Memory ID in two namespaces; reset one only | `PASS` |
| Minimum recall contract | Current generation, scope, status, topic, limit and deterministic tie-break | `PASS` |
| PostgreSQL-native architecture admission | All mandatory capabilities above | `PASS` |

## Acceptance evidence

The isolated runner is:

```text
tests/compose/postgres_native_memory_admission/run-postgres-tests.sh
```

It starts only `postgres:17.5-alpine3.21`, uses a unique project, network and
volume, and removes all three on exit. The host result is:

```text
8 passed in 0.92s
ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS
ZEBRA_PG_NATIVE_MEMORY_TEST_RESULT=PASS
```

The eight cases cover deterministic identity/replay, response-loss recovery,
successful atomic commit, rollback, stale-generation rejection, complete reset,
cross-namespace isolation and minimum recall. The predecessor evidence remains
the regression floor: focused delivery `24 passed`; the full
`tests/agent_storage` matrix with these eight new cases passes `303 passed, 1
skipped` (`295` predecessor cases plus `8` admission cases).

`make check` is still blocked by the two pre-existing file-size violations
outside this task: the Desktop stylesheet at `561/500` and
`tests/agent_storage/test_postgres_governed_memories.py` at `765/700`.

## Admission and follow-up

`PASS` means only that the PostgreSQL-native architecture satisfies ADR-018's
deletion and recovery contract in the isolated test boundary. It does not mean:

- production migrations or API/Worker wiring are complete;
- Runtime may select PostgreSQL;
- the Worker or Consumer may start;
- Mem0 is admitted or its historical orphan is repaired; or
- performance, vector quality or data migration is complete.

The next implementation card may be made `Ready` only after an explicit
activation of `MEM-GW-PG-NATIVE-01`. If that implementation later fails any
ADR-018 capability, it returns to `Locked`; no Runtime task is unlocked by this
Spike alone.
