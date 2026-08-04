# CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01

## Handoff And Dispatch Mutation Authority Conformance Audit

- Status: `Done` / audit result `PASS`
- Date: `2026-08-03`
- Base under audit: `zebra-cloud-trench@765ede43`
- Branch: `codex/cloud-agg-fence-handoff-dispatch-con-01`
- Worktree: `/Users/lukeding/.codex/worktrees/cloud-agg-fence-handoff-dispatch-con-01/zebra-agent`
- Owner: `governance/planning`
- Parent gate: `CLOUD-AGG-FENCE-01` remains `Locked`
- Follow-up implementation and evidence are now merged into
  `zebra-cloud-trench@5a5b9275`.
- Authority: sidebar ChatGPT authorized this governance audit only. It did not
  authorize production implementation, test or migration changes.

## Decision summary

The initial audit at `765ede43` was `BLOCK-GAP`. Its separately authorized
successors are now complete: reserve/abort use an explicit administrative CAS
boundary, dispatch claim/ACK carries operation and stream/pointer revisions with
the canonical Worker authority, and both dedicated PostgreSQL runners are checked
in and reproducible. The resulting conformance verdict is `PASS`; this closeout
does not unlock the parent gate or select a runtime profile.

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
| Reserve | `PostgresSessionHandoffStore.reserve()` locks the source Lease boundary, then reads and locks stream/Workspace/Lease facts before the idempotent operation insert (`session_handoffs.py:88-186`). | `PASS`: reservation uses an explicit administrative source-facts CAS split; stale stream, fence, workspace and task facts fail before insert. |
| Commit | `commit_handoff_in_transaction()` locks the operation, source Lease advisory boundary, source stream, Task active segment and Workspace facts, then appends parent/child Events, projections, Task rollover, Envelope, dispatch outbox and committed operation on one connection (`.../session_handoff_transactions.py:55-194`). | `PASS` for atomic v8 commit and source-fact CAS, subject to the missing reservation authority. |
| Envelope and publication | `_insert_envelope_and_dispatch()` writes the immutable Envelope and `handoff_dispatch_outbox` before the operation status update (`.../session_handoff_transactions.py:265-304`). v8 composite foreign keys bind source, target, handoff and artifact identity. | `PASS` for same-transaction publication and relational identity binding. |
| Abort | `abort_authorized_in_transaction()` locks the operation, checks reservation/request identity and `AdministrativeMutationCAS`, locks Lease/stream/Workspace facts, then applies `preparing -> aborted` CAS (`session_handoff_authority.py:55-135`). | `PASS`: wrong namespace, stale stream/facts, replay mismatch and commit race are rejected or converge without partial writes. |
| Dispatch claim | `PostgresHandoffDispatchStore.claim_for_child()` locks outbox, operation, child stream and pointer, validates operation/revisions and current LeaseFence, then stores the claim token and canonical authority (`session_handoff_dispatch.py:30-157`). | `PASS`: stale stream/pointer, namespace and two-worker races are fenced before claim. |
| Dispatch ACK | `_acknowledge()` locks operation, stream, pointer and dispatch row, checks operation/revisions, current LeaseFence, token, owner, epoch, expiry and status, and treats an authorized replay as idempotent (`session_handoff_dispatch.py:161-257`). Workspace-aware ACK also holds the stream/Workspace lock. | `PASS`: stale receipt, pointer/stream drift, namespace mismatch and concurrent replay are zero-write or equivalent replay. |
| Worker recovery | `SessionHandoffRecoveryGate.recover()` passes the acquired fence into the cloud dispatch seam; the dispatch receipt exposes canonical `WorkerMutationAuthority` for subsequent ACK (`apps/worker/src/zebra_agent_worker/session_handoff.py:68-164`). | `PASS`: compatibility callers may supply the legacy fence shape, while the cloud fenced receipt is authority-bound. |
| v8 schema | `handoff_migration.py` enforces namespace composite keys, immutable Envelope, operation uniqueness, Envelope identity FKs and complete claim receipt shape. | `PASS` for structural constraints; SQL constraints do not replace authority predicates. |

## HD-01..HD-12 acceptance matrix

`PASS` means the scoped path is proven. `PARTIAL` means an implementation or
evidence slice exists but the parent gate cannot accept it. `BLOCK-GAP` is the
overall result for a gate with an unproven mutation path.

| Gate | Result | Evidence | Gap or required follow-up |
| --- | --- | --- | --- |
| HD-01 Authority propagation | `PASS` | Reserve/abort use explicit `AdministrativeMutationCAS`; dispatch receipts carry `WorkerMutationAuthority` with namespace, Session, LeaseFence and stream revision. | Administrative CAS is intentionally distinct from Worker LeaseFence. |
| HD-02 Persistence-boundary enforcement | `PASS` | Reserve, abort, claim and ACK validate authority and current facts inside their PostgreSQL transaction before mutation. | No remaining gap in the scoped paths. |
| HD-03 Aggregate and identity binding | `PASS` | Request hash, operation identity, Envelope FKs and namespace/child dispatch keys bind the operation; abort checks the complete reservation. | No remaining gap in the scoped paths. |
| HD-04 Stale authority rejection | `PASS` | Auth tests cover stale facts, workspace drift, wrong namespace, stale CAS and commit race; dispatch tests cover expiry/reclaim, old token, generation change and stale receipt. | No remaining gap in the scoped paths. |
| HD-05 Revision/pointer fencing | `PASS` | Dispatch claim/ACK carry and compare expected stream and pointer revisions; Workspace-aware ACK locks the source facts. | No remaining gap in the scoped paths. |
| HD-06 Zero-write | `PASS` | Focused auth/dispatch tests assert unchanged operation/outbox/aggregate state after wrong authority, drift and injected rollback cases. | No remaining gap in the scoped paths. |
| HD-07 Single-winner concurrency | `PASS` | Concurrent reserve, abort-vs-commit, two-worker claim and concurrent ACK replay matrices are green. | No remaining gap in the scoped paths. |
| HD-08 Idempotent replay | `PASS` | Reserve/commit replay and authorized dispatch claim/ACK replay return equivalent results without duplicate transitions. | No remaining gap in the scoped paths. |
| HD-09 Namespace isolation | `PASS` | Namespace is present in all queries/keys; wrong-namespace abort and receipt attempts fail with zero writes. | No remaining gap in the scoped paths. |
| HD-10 Transactional boundary | `PASS (scoped)` | Commit writes Events, projections, Task rollover, Envelope, dispatch and operation status on one connection; claim and ACK each use one connection. | Delivery-audit records are not part of Handoff v8; any future cross-aggregate publication must keep this boundary explicit. |
| HD-11 Evidence traceability | `PASS` | `tests/compose/session_handoff_authority/run-postgres-tests.sh` passes `15/15` and `tests/compose/session_handoff_dispatch/run-postgres-tests.sh` passes `14/14` on PostgreSQL `17.5-alpine3.21`, with explicit PASS markers and cleanup; tested successor commits are `6a04f1cd` and `6c1ceffa`. | Evidence is reproducible from merged `zebra-cloud-trench@5a5b9275`. |
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

### Test inventory on the audit base and successors

- `tests/agent_storage/test_postgres_session_handoffs.py` contains seven
  focused tests for complete commit, reserve idempotency, stale facts, changed
  request, late rollback, immutable Envelope and concurrent successor winner.
- `tests/agent_storage/test_postgres_handoff_dispatch.py` contains the original
  focused tests plus successor coverage for operation/revision binding, stale
  pointer/stream zero-write, wrong receipt/namespace, two-worker claim and
  concurrent ACK replay.
- These tests require `ZEBRA_TEST_POSTGRES_DSN` and are environment-gated; the
  successor runners provide the checked-in Compose entry points below.

### Successor evidence

The two dedicated successor runners are checked in and were run from the merged
mainline:

```text
tests/compose/session_handoff_authority/run-postgres-tests.sh
tests/compose/session_handoff_dispatch/run-postgres-tests.sh
```

Results were `15 passed` with `ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=PASS` and
`14 passed` with `ZEBRA_HANDOFF_DISPATCH_POSTGRES_TEST_RESULT=PASS`. Both runners
used `postgres:17.5-alpine3.21` and removed their containers, volumes and networks.
The earlier delivery runner collection failure was outside this audit's dedicated
Handoff/dispatch evidence path and is not used as a pass claim.

## Closure evidence

The separately authorized successors provide the required closure evidence:

1. Reserve/abort use explicit administrative CAS and dispatch uses Worker authority.
2. Focused PostgreSQL tests cover stale, namespace, token, expiry, stream, pointer,
   zero-write, concurrency and replay behavior.
3. Dedicated runners are checked in, pinned to PostgreSQL 17.5 and reproducible.

## Local closeout

The initial sidebar review returned `CLOSEOUT-OK` for `Planning -> Review` with
the audit result `BLOCK-GAP`; it did not authorize implementation. After the
separately completed AUTH-01, DISPATCH-01 and their PostgreSQL runners, local
review at `zebra-cloud-trench@5a5b9275` records `PASS` and closes this audit as
`Done`.

- `CLOUD-AGG-FENCE-01` remains `Locked`;
- no Runtime/API/Worker selector, application Compose, SQLite, Redis, Mem0,
  Provider HTTP, CopilotKit/Trench or production rollout is authorized.

All three follow-up gates are now closed independently; the parent gate remains
locked until the remaining aggregate conformance and broader production evidence
are evaluated.
