# CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01

## Handoff And Dispatch Mutation Authority Conformance Audit

- Status: `Review` / audit result `BLOCK-GAP`
- Date: `2026-08-03`
- Base under audit: `zebra-cloud-trench@765ede43`
- Branch: `codex/cloud-agg-fence-handoff-dispatch-con-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-handoff-dispatch-con-01/zebra-agent`
- Owner: `governance/planning`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`
- Authority: sidebar ChatGPT authorized this governance audit only. It did not
  authorize production implementation, test or migration changes.

## Decision summary

The existing Handoff v8 implementation has a sound atomic commit path and a
substantially fenced child-dispatch claim/ACK path, but it does not yet prove the
full Worker aggregate authority contract required by the parent gate.

The audit is `BLOCK-GAP` for three reasons:

1. Handoff reservation and abort writes do not accept or validate the canonical
   `WorkerMutationAuthority` (or an explicit administrative CAS). They persist
   caller-supplied source facts and identify the operation only by namespace and
   operation/idempotency keys.
2. Dispatch claim/ACK carries a `LeaseFence`, but not the canonical authority's
   expected stream revision or a durable operation identity. The claim path
   validates the current LeaseFence but does not fence a stale stream/pointer;
   there is no concurrent two-worker claim matrix or replay contract for ACK.
3. The repository has no checked-in Handoff/dispatch PostgreSQL Compose runner.
   The accepted `20/20` result is historical evidence recorded against the
   integrated Handoff commit, not a reproducible command tied to this audit SHA.
   The only existing delivery transaction runner was attempted unchanged here,
   but its isolated uv environment stopped at collection because `psycopg` was
   not installed; the PostgreSQL container itself became healthy and was cleaned
   up.

No implementation successor is activated by this result. The exact missing
   enforcement and evidence are recorded below for a separately authorized card.

## Audit boundary

### Writable governance paths

- `docs/AGENT_TASKS.md`
- `PROGRESS.md`
- `task_plan.md`
- `docs/Zebra Cloud 主线当前状态与后续工作.md`
- this document

### Read-only implementation targets

- Core Handoff events, domain, Handoff and Lease Ports
- `packages/agent-context/src/agent_context/session_handoff.py`
- PostgreSQL Handoff, dispatch, Lease, Event and delivery-audit adapters
- PostgreSQL migration catalog, especially v8
- Worker Handoff recovery, claims, runtime authority and finalization seams
- focused Handoff/dispatch/delivery tests, evals and existing Compose runners
- closeout evidence for `CLOUD-AGG-HANDOFF-PG-01` and delivery transaction

The audit changed no implementation, test, migration, Compose, runtime, SQLite,
Redis, Mem0, CopilotKit/Trench or root `AGENTS.md` file.

## Source trace

| Mutation path | Observed source and boundary | Finding |
| --- | --- | --- |
| Reserve | `PostgresSessionHandoffStore.reserve()` inserts `handoff_operations` in its own connection (`packages/agent-storage/src/agent_storage/postgres/session_handoffs.py:55-143`). It receives `source_lease_fence` plus free-form revision strings, but never calls `assert_current_lease_fence()` or validates the source stream and workspace in that write transaction. | `BLOCK-GAP`: no canonical Worker authority at reservation boundary. |
| Commit | `commit_handoff_in_transaction()` locks the operation, source Lease advisory boundary, source stream, Task active segment and Workspace facts, then appends parent/child Events, projections, Task rollover, Envelope, dispatch outbox and committed operation on one connection (`.../session_handoff_transactions.py:55-194`). | `PASS` for atomic v8 commit and source-fact CAS, subject to the missing reservation authority. |
| Envelope and publication | `_insert_envelope_and_dispatch()` writes the immutable Envelope and `handoff_dispatch_outbox` before the operation status update (`.../session_handoff_transactions.py:265-304`). v8 composite foreign keys bind source, target, handoff and artifact identity. | `PASS` for same-transaction publication and relational identity binding. |
| Abort | `PostgresSessionHandoffStore.abort()` locks by namespace/operation id and updates status (`.../session_handoffs.py:160-184`). It does not receive a fence, expected stream revision or operation request identity. | `BLOCK-GAP`: stale or unauthorized abort is not fenced. |
| Dispatch claim | `PostgresHandoffDispatchStore.claim_for_child()` selects one pending/expired child row with `FOR UPDATE SKIP LOCKED`, checks the current child LeaseFence and stores a random claim token plus full fence (`.../session_handoff_dispatch.py:27-85`). | `PARTIAL`: LeaseFence is checked, but stream/pointer revision is not part of the authority contract. |
| Dispatch ACK | `_acknowledge()` checks current LeaseFence, child, token, owner, epoch, expiry and status in one update (`.../session_handoff_dispatch.py:116-155`). Workspace-aware ACK holds a workspace share lock across comparison and ACK (`:93-114`). | `PASS` for stale receipt rejection; no operation-id replay semantics. |
| Worker recovery | `SessionHandoffRecoveryGate.recover()` passes the acquired `LeaseFence` into child claim/ACK; workspace drift suspension uses `WorkerMutationAuthority` only for the subsequent Event/projection transaction (`apps/worker/src/zebra_agent_worker/session_handoff.py:68-164`). | `PARTIAL`: recovery propagates a fence, but the Handoff Port itself remains LeaseFence-shaped. |
| v8 schema | `handoff_migration.py` enforces namespace composite keys, immutable Envelope, operation uniqueness, Envelope identity FKs and complete claim receipt shape. | `PASS` for structural constraints; SQL constraints do not replace authority predicates. |

## HD-01..HD-12 acceptance matrix

`PASS` means the scoped path is proven. `PARTIAL` means an implementation or
evidence slice exists but the parent gate cannot accept it. `BLOCK-GAP` is the
overall result for a gate with an unproven mutation path.

| Gate | Result | Evidence | Gap or required follow-up |
| --- | --- | --- | --- |
| HD-01 Authority propagation | `BLOCK-GAP` | Worker recovery uses the acquired `LeaseFence`; dispatch receipts persist epoch/token/owner. | `SessionHandoffPort.reserve/commit/abort` and `HandoffDispatchStorePort` expose no canonical `WorkerMutationAuthority` with namespace, owner, epoch, token, expiry and expected stream revision. |
| HD-02 Persistence-boundary enforcement | `BLOCK-GAP` | Commit and ACK validate facts inside their PostgreSQL connection. | Reserve and abort write before any equivalent current-authority predicate; dispatch claim has no stream/pointer predicate. |
| HD-03 Aggregate and identity binding | `PARTIAL` | Commit request digest, Envelope checks, composite FKs and `(namespace, child)` dispatch uniqueness bind the main aggregate. | Abort is operation-id-only; the matrix lacks a cross-method proof that caller-controlled IDs cannot select another authorized operation. |
| HD-04 Stale authority rejection | `PARTIAL` | Historical/current tests cover stale source facts, expired/reclaimed dispatch, old token and same-owner new generation ACK rejection. | No reserve/abort stale-authority tests; no explicit wrong namespace/owner/epoch zero-write matrix. |
| HD-05 Revision/pointer fencing | `PARTIAL` | Commit locks `session_streams` and Task active segment and compares source facts; Workspace-aware ACK locks Workspace. | Dispatch claim/ACK does not carry or compare expected stream revision/active pointer; a checked-in regression is missing. |
| HD-06 Zero-write | `PARTIAL` | Handoff stale workspace and injected late failure tests compare aggregate counts; stale ACK leaves the row claimed. | No complete row-count sentinel across Event/Handoff/pointer/projection/dispatch/idempotency/audit for every wrong authority case, especially reserve/abort. |
| HD-07 Single-winner concurrency | `PARTIAL` | `test_concurrent_successors_have_exactly_one_winner` proves one Handoff successor. | No two-worker concurrent `claim_for_child()`/ACK race assertion in the focused PostgreSQL tests; historical sequential second-claim coverage is insufficient. |
| HD-08 Idempotent replay | `PARTIAL` | Reserve is idempotent; committed Handoff replay returns the equivalent result and marks `idempotent_replay`. | Dispatch has no operation id; repeated ACK is a conflict after the first write, and no equivalent replay result is specified or tested. |
| HD-09 Namespace isolation | `PARTIAL` | All PostgreSQL queries and v8 keys include `deployment_namespace`. | No Handoff/dispatch test creates identical IDs in two namespaces and proves cross-namespace read/mutation rejection with zero writes. |
| HD-10 Transactional boundary | `PASS (scoped)` | Commit writes Events, projections, Task rollover, Envelope, dispatch and operation status on one connection; claim and ACK each use one connection. | Delivery-audit records are not part of Handoff v8; any future cross-aggregate publication must keep this boundary explicit. |
| HD-11 Evidence traceability | `BLOCK-GAP` | Registry/WORKLOG record historical PostgreSQL v1-v8 `20/20`, Core/Storage/API/Worker `822/822`, and current focused `17/17` at the integrated Handoff history. | No exact Handoff Compose runner/command is present in this checkout and the historical record is not tied to audit SHA `765ede43`. Existing delivery runner attempt failed collection because isolated uv lacked `psycopg`. |
| HD-12 Scope integrity | `PASS` | This branch changes only the five registered governance paths and this audit document. | Preserve the boundary through review/merge; do not auto-activate a successor. |

## Evidence ledger

### Historical Handoff evidence

- `docs/AGENT_TASKS.md` and `WORKLOG.md` record the integrated Handoff v8
  PostgreSQL aggregate/dispatch/migration matrix as `20/20`, including stale
  facts, concurrent successor, injected late rollback, immutable Envelope and
  lost-response replay.
- The same records cite Core/Storage/API/Worker `822/822` with `102` environment
  skips, scoped Ruff and `git diff --check`, plus a current-HEAD Core/Worker
  focused regression of `17/17`.
- The implementation commits are `d23d824c` (fenced dispatch) and `cfe40713`
  (atomic Handoff aggregate). The audit base is later `765ede43`; no Handoff
  implementation change was made between those commits and this audit.

### Test inventory on the audit base

- `tests/agent_storage/test_postgres_session_handoffs.py` contains seven
  focused tests for complete commit, reserve idempotency, stale facts, changed
  request, late rollback, immutable Envelope and concurrent successor winner.
- `tests/agent_storage/test_postgres_handoff_dispatch.py` contains seven
  focused tests for exact fence claim/ACK, reclaim rotation, generation change,
  workspace drift, database-time facts, workspace locking and artifact FK.
- These tests require `ZEBRA_TEST_POSTGRES_DSN` and are environment-gated; there
  is no `tests/compose/handoff*` or `tests/compose/dispatch*` runner in this
  checkout.

### Existing runner check

The only existing runner in the declared delivery-audit scope was run unchanged:

```text
tests/compose/delivery_transaction/run-postgres-tests.sh
```

The `postgres:17.5-alpine3.21` container became healthy, then uv created an
isolated environment and test collection failed with
`ModuleNotFoundError: No module named 'psycopg'`. The runner emitted
`ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=FAIL` and its container,
volume and network cleanup completed. This is an environment evidence gap, not
a code-pass claim.

## Required closure evidence

Before this audit can move to `Done` or authorize any successor, a separately
authorized follow-up must provide, without changing this governance card's
scope:

1. A canonical authority shape for reserve, commit, abort, claim and ACK, or an
   explicit documented split between administrative CAS and Worker LeaseFence.
2. PostgreSQL zero-write tests for wrong namespace, owner, epoch, token, expiry,
   stale stream and stale pointer, including reserve and abort.
3. A concurrent two-worker claim/ACK race and an explicit replay contract for
   the same authorized operation.
4. Cross-namespace identical-ID isolation assertions.
5. A checked-in existing-style PostgreSQL Compose runner, or an exact
   reproducible host command and dependency lock evidence that can be tied to
   the tested mainline SHA.

## Sidebar closeout

Sidebar ChatGPT returned `CLOSEOUT-OK` and approved `Planning -> Review` with
the following non-authorizations:

- audit result remains `BLOCK-GAP`;
- `CLOUD-AGG-FENCE-01` remains `Locked`;
- implementation and successor activation are both `false`.

The required follow-up is to register two separately locked cards: one for the
minimal Handoff reserve/abort authority/CAS boundary and one for dispatch
operation, stream/pointer, replay, race and namespace fencing. A third gate must
provide a reproducible PostgreSQL 17.5 focused runner with a working `psycopg`
test environment. Until those cards receive independent activation and closeout,
do not unlock `CLOUD-AGG-FENCE-01` or select a runtime profile.
