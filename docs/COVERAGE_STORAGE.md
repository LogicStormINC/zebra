# Coverage persistence boundary

COV-STO-01 extends the committed COV-CON-01 contract. It does not enable
exhaustive processing in the running Zebra or Trench application.

## Authority and atomicity

The existing Session Event Store remains authoritative. Coverage tables are
derived indexes; `coverage_continuations` records dormant continuation intent,
not an independently executing queue. No model or Worker may certify coverage
by writing a counter.

- `CoverageRunBinding` binds Task, Session, business namespace, contract and
  immutable snapshot. The records live in a governed `artifact://UUID` payload.
- Manifest and batch payloads use canonical UTF-8 JSON. Artifact SHA-256 is
  checked separately from the scoped manifest digest; equal counts do not
  substitute for exact record/part/check/version identity.
- Artifact preflight uses the existing `ArtifactPayloadStorePort`. It checks
  Session identity, lifecycle, retention, bytes and metadata. Remote URLs are
  not valid coverage Artifact references. Uncommitted objects do not count.
- Mutations reuse the Session advisory boundary and full current lease fence,
  then Task/run/stream locks. The current active Segment and persisted cloud
  Host binding must agree. Terminal source Events and accepted STOP are checked
  even if Session projections lag.
- Task binding renewal uses that same existing Task lock before reading or
  appending revisions. Renewal cannot race between final validation and Event
  commit. Lease/authority checks repeat after projection work before commit.
- A batch Event, exact-unit updates, receipt and continuation intent commit in
  one PostgreSQL transaction. Partial failures roll everything back. Identical
  retries return the original receipt; changed input or overlapping units fail.
- Coverage Events retain the full acceptance epoch/token/owner fence. Replay
  validates this historical descriptor without requiring that old lease to
  remain current. Current mutations still require the live full fence.
- Explicit rebuild replays source Events and their immutable Artifacts in one
  transaction. Missing or corrupt evidence aborts rebuild without replacing a
  previously usable index. Rebuild does not append another execution Event.

## Persistence and scale boundary

Migration 78 adds runs, exact expected-unit keys, accepted batch receipts and
continuation intent. It deliberately leaves 61-77 reserved for the primary
checkout's unrelated pending migrations. Checksums of existing migrations do
not change. Do not run this branch's migration catalog against a newer live
database: combine all pending migrations during explicit integration first.

Expected-unit membership and missing-work lookups are indexed in PostgreSQL.
First-version run mutations serialize on the existing Session lease. This is
not a multi-Worker per-batch claim protocol. No second scheduler or global lock
is introduced.

The first adapter materializes an Artifact capped at 32 MiB during binding/rebuild;
it is not a streaming billion-record importer. Oversized evidence must fail
closed rather than be truncated. Sharded manifest ingestion and claim epochs
belong to the snapshot/executor integration, not a hidden fallback here.

Cancellation still requires the current lease and matching Task/Host namespace,
but does not require unexpired input evidence or unchanged execution policy:
expired or inaccessible evidence must not prevent stopping a run. New progress
is refused if the pinned Task binding changes. A stopped Session is not silently
reactivated; same-Session continuation needs a fresh explicit boundary later.

Administrative replay currently materializes the run's Event descriptors and
decoded batch results before replacing indexes. This has O(run-history plus
decoded-results) memory cost; streaming/staged replay remains necessary before
claiming unbounded dataset support. Replay is not on the interactive answer
path and does not silently drop work.

## Not certification

Counts and accepted receipts prove storage membership only. They do not prove
model semantic correctness, current external Trench entitlement/revocation,
complete body reads, cross-record analysis, or safe publication.

The constructor requires a composed governed Artifact adapter. Tests can use
SQLite payload storage beside real disposable PostgreSQL to test transaction
semantics; that evidence is not a real MinIO/model/browser acceptance result.

Remaining delivery path:

1. TRN-COV-SNAPSHOT-01: immutable authorized Trench snapshot and frozen bodies.
2. COV-EXEC-01: bounded reads/checks, accepted-result validation, batch claims,
   recovery, budgets and consumption of continuation intent.
3. COV-GATE-01: persisted review/certificate projections, exact-set certificate,
   current Host authority checks and fail-closed report publication.
4. COV-UI-01: progress/coverage evidence and truthful partial/published state.
5. COV-ACCEPT-01: real coupled object-store/model/browser fault and load tests.

## Validation

Evidence is recorded in the task card and WORKLOG after focused regressions,
spec review, quality review and full local gates. Live services are neither
restarted nor migrated by this task.

Final local evidence (2026-10-07): 85 isolated PostgreSQL and related boundary
tests; 70 focused core/Artifact tests; full pytest 4,948 passed / 939 environment
skips. `make check` passes (sizes, Ruff, Mypy 1,016 files, eval 30/30). Both
independent reviews passed after the recorded fixes. This evidence is not
deployment or an exhaustive processing acceptance certificate.
