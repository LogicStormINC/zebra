# Worker progress head SQL consolidation

## Scope and measured reason

Task PROGRESS-HEAD-LOCK-01, base `6858b2b5`. Existing real search traces attribute
3.862/2.489 seconds of exclusive Worker time to progress catch-up, and
3.148/1.980 seconds to canonical append. These categories exclude nested model
and tool waits; SQL and connection intervals overlap them rather than adding
another independent cost. See `CLOUD_WEB_WAIT_PROFILE.md`.

The canonical recorder's model/tool adapters already discard irrelevant event
types before opening storage connections. No change to those adapters is justified.
The shared progress advancement path does perform redundant work on every page:
an initialization INSERT even when a head already exists, then a separate
PostgreSQL row-lock SELECT before reading the bounded head.

## Minimal change

`WorkerProgressStoreMixin._progress_head` optionally appends PostgreSQL
`FOR UPDATE` to its existing byte-gated SELECT. Advancement first uses this
locking read. Only an absent head takes the existing INSERT ON CONFLICT path,
then rereads and locks the winning row in the same transaction.

For an existing PostgreSQL head, these head-specific statements fall from three
to one. SQLite retains BEGIN IMMEDIATE and reduces two statements to one.
Cold initialization still requires three statements on PostgreSQL; SQLite cold
initialization adds one read. No schema, Port, dependency, pool or cross-transaction
cache is introduced. Read-only callers do not request a row lock.

Unchanged boundaries:

- Fresh canonical Run/namespace/anchor and bounded canonical page verification.
- Database CASE gate, actual UTF-8 byte equality, at most32KiB state hydration.
- One transaction, row lock, CAS, rollback and stale winner handling.
- First-use races must reread the INSERT winner; no process-local assumption.
- Fresh authority/STOP checks and original cumulative2s I/O deadline.
- Unknown canonical write outcomes are still failures; no model/tool/write retry.

## Deterministic checks

The existing no-model default gate now asserts that hot advancement executes no
initialization INSERT and only one head SELECT. It fails against the original
source, passes after the change, and retains membership/signature conflict checks.

The existing PostgreSQL frontier concurrency test now forces both transactions
to observe a missing head before either INSERT, and separately aligns two
existing-head locking reads. Exactly one advances and the other receives
CheckpointStale in both cases; the stored frontier equals the winner.

74 SQLite/core/Worker recovery and commentary regressions plus12 native
PostgreSQL cases pass in a disposable database. All checks call zero models.
No old fixtures or observation infrastructure were repaired.

## Same-work native A/B

One disposable PostgreSQL server; fixed ABBAABBA order, four samples per variant.
A uses the original advancement function at6858b2b5; B uses the candidate.
Each sample has a fresh namespace and the same canonical response plus one
commentary output. Native canonical append, progress transactions and identity
checks run normally; no provider or sandbox is called.

| Whole measured operation | Original median | Candidate median |
| --- | ---: | ---: |
| Explicit SQL statements |54|50|
| Task I/O connections |9|9|
| Bounded event page reads |2|2|
| Redundant head INSERTs |2|0|
| Separate head-lock SELECTs |2|0|
| Wall time |215.49ms|215.04ms|

The SQL reduction is4/54=7.4% for this operation. There is no measurable stable
latency improvement and no connection reduction. This is not a whole-Run or
page-first-body measurement. External/provider waits and the remaining Worker
connection/transaction costs are unchanged. The whole-system80% SQL target,
STOP/revocation/takeover convergence and capacity/GC acceptance remain OPEN.

Private receipts: `.artifacts/progress-head-lock-20261016/` contains the
red/green evidence, fixed native pair, disposable-run results and activation
fingerprints. No raw credentials or user content belong in this document.

## Delivery boundary

Clean tracked-source `make check` passed: Ruff, mypy1283 files, size gate3094
files, eval30 and both existing standalone progress fault checks. The first gate
caught one new103-character signature; it was wrapped and the same gate passed.
No full test-suite or real-page latency acceptance is claimed.

Worker-only normal-service activation completed under the zero-active-intent
guard. Worker image `03bc01aa` and API `907fcc00` are healthy with zero restarts;
all80 source fingerprints and original six Compose files, environment, commands,
entrypoints and search service match. API exact image and start timestamp are
unchanged. Source hashes match the activated overlay. Local integration preserves
unrelated primary dirty work; no push, npm publication, remote deployment,
provider call or Run replay.
