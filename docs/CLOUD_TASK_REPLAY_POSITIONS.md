# Immutable Task replay positions

Status: implementation in progress for CLOUD-PROGRESS-OUTPUT-01. This is not a
claim of activated migration, bounded SSE replay or live acceptance.

## Authority and ordering

The canonical Event row retains nullable storage-only `task_id` and
`task_sequence`. Assignment is one-way: unassigned to exactly one Task position.
The source Session/Event identity and an assigned position cannot be rewritten.
The public SessionEvent contract and local execution behavior stay unchanged.
Late predecessor metadata is legal and receives a new Task tail position;
Task ordering is not Segment concatenation. Projection state must survive a
Segment being revisited.

`task_event_index` remains derived. A missing cell is repaired from source
coordinates, never from `created_at`, segment order or a newly computed ordinal.
Canonical Segment ownership cannot be changed underneath assigned coordinates.
An inconsistent membership or legacy reservation fails closed and needs explicit
operator review, rather than silently invalidating previously emitted cursors.

## Allocation and lock order

PostgreSQL queues an unconditional, deferred INSERT constraint trigger. At
commit it rereads current membership and the source row, then takes the Task
advisory domain (hash seed 61), distinct from Session/lease seed 0. Lease,
stream, artifact, memory and command admission locks precede Task allocation.
The trigger allocates one position and derived cell in the same transaction.
Bootstrap events inserted before membership are assigned by the existing Task
composition boundary. SQLite uses its existing single-writer transaction and
an INSERT trigger; handoff/context writers share that database rule.
Initial admission is the narrow exception: its new UUID Task and source stream
are not visible to another transaction, so membership can precede the initial
command/wakeup binding. Existing Tasks must follow Task-last. Multi-Task
maintenance orders Task keys consistently; mixed writer versions and explicit
early `SET CONSTRAINTS ... IMMEDIATE` are unsupported activation configurations.

## Legacy data and rollout

Schema migration only installs the additive columns, constraints and triggers.
An explicit resumable backfill validates/adopts existing index reservations and
assigns unindexed tails in batches of at most 256 metadata rows. Per-Task phase,
cursor and allocation high-water mark are durable; no historical bodies are read.
Invalid gaps, identity mismatches or source-order inversions are not guessed.
Tasks awaiting backfill cannot accept new positioned source writes.
SQLite-to-Postgres import retains source coordinates when present; legacy
snapshots use the explicit backfill contract before activation.

Stop the old writers before migration/backfill and activate all API/Worker
writers together. Seed-0 Task writers and seed-61 allocators cannot be mixed.
Process restarts remain user-operated. Real PostgreSQL concurrency, rollback,
idempotency, late metadata, backfill interruption and index-hole repair are
required gates before this design is marked complete.
