# Coverage persistence implementation plan

**Goal:** persist immutable coverage inputs and accepted batches without losing
events, double counting retries or admitting stale Workers.

**Architecture:** existing Session Event Store is authoritative; coverage SQL
tables are rebuildable exact-membership indexes. Existing Session lease fences
serialize mutations. Immutable governed Artifacts precede the Event transaction;
uncommitted orphan Artifacts never count. A continuation intent is committed
with the Event but does not activate a new executor or queue.

**Stack:** Python 3.12, Pydantic, psycopg, PostgreSQL; existing Artifact Port.

- [x] Baseline core contracts and migration checks.
- [x] Add bounded run binding contract and coverage Event types.
- [x] Add migration 78 for runs, expected units, accepted batches and intents.
- [x] Implement explicit run binding, atomic batch acceptance and replay using
  existing lease/task/event transactions; verify Artifact scope and bytes.
- [x] Real isolated PostgreSQL tests: idempotency, conflict/rollback, fencing,
  expiry/cancellation, scope/version drift, exact membership and rebuild.
- [x] Spec review, then quality review; repair findings and run full gates.
- [x] Update task/progress/worklog with actual evidence and remaining work.

Final evidence: 85 isolated PostgreSQL/related boundary checks; 70 focused
core/Artifact checks; full suite 4,948 passed and 939 environment skips;
`make check` passed. Reviews required and verified historical lease descriptors,
Task binding renewal serialization and final post-projection lease validation.

Owned files are enumerated in COV-STO-01. Validation: focused pytest followed
by `make test` and `make check`. Tests use a newly created disposable PostgreSQL
container only. Live Trench, Zebra and existing object stores are out of scope.

Unfinished product path after this slice: Trench immutable snapshot service,
bounded batch executor/claims, review and certification gates, UI evidence,
real model/object-store/browser/capacity acceptance and deployment.
