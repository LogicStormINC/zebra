# Cloud stream reliability implementation boundary

Readonly audit2026-10-13 on accepted ffe8f38b. CLIENT is in progress; this plan
is not a correctness or capacity GO. No source changes or service operations
were performed for the audit. Luke Ding owns the roadmap; Codex executes.

## Reuse and actual gaps

Shared postgres/events.py append_event_in_transaction already covers ordinary,
Worker and cancellation Event transactions. Existing command_wakeup_relay
storage/runtime adapters provide bounded claiming, leases, fencing, settlement
and backoff patterns. Their broker_outbox contains execution-command envelopes;
it must not be repurposed for stream notifications.

AG-UI checkpoint_consumer has durable projection work and CAS plus work ACK.
Reuse this queue: committed checkpoints need retryable hints before work ACK,
without repeating checkpoint frames. Session cancellation already records
canonical cancel/projections and revokes leases. command_runtime_cleanup provides
retryable exact-target OCI cleanup, but container cleanup is not a display ACK.

Current live_event_store publish wrappers swallow failures and skip hints for
borrowed transactions. A commit/publish crash therefore has no reliable pending
notification. checkpoint_consumer similarly swallows hint errors then ACKs work.
Redis canonical publish stores full Event JSON and has MAXLEN but no TTL;
checkpoint hints also lack TTL. Durable recovery exists, but relay reliability
and bounded hint memory have not been proved.

Transient Lua already enforces CAS/full fence/idempotence/offsets/single-generation
8MiB/8192rows/fixed TTL. Reuse it. A lane admits256 generations and old keys
remain: theoretical body capacity is about2GiB/lane plus indices/Redis overhead.
The4096 adapter-local handle bound is not a Run/tenant/deployment quota. Closed
keys retain up to1h, not the proposed10-minute ended retention. Worker invalidate
is best effort; a disconnected Worker cannot acknowledge stopped display.

## Serial implementation slices after CLIENT and proof performance

1. RELAY: add a minimal body-free pending frontier in the shared canonical
   transaction, coalesced per Session. Claim/version/fence settlement must not
   delete a newer pending frontier after publishing an older one. Publish only
   after PG commit. Reuse checkpoint work for notification-before-ACK and retry.
2. CAPACITY: extend existing Lua with Run/tenant/deployment byte/count admission
   and bounded expiry accounting. Count all retained generations; duplicate
   frames do not charge again. Ended retention is configurable and clipped;
   crash recovery must reclaim charges without keyspace notifications. Canonical
   hints become bounded metadata with atomic TTL rather than large event bodies.
3. CONTROL: derive a separately retryable temporary invalidation obligation from
   existing canonical cancellation. Target exact old Run/generation/fence;
   retain pending on Redis failure, and distinguish durable cancellation from
   confirmed display closure. Never roll back cancel or invalidate a new Run.

Claim separate focused cards before coding, each with one owner/branch/worktree.
RELAY requires explicit COV write handoff for postgres/events.py and
live_event_store.py, checkpoint commit/work ACK paths, plus an additive migration
number reserved at claim. Keep recorder unchanged unless a demonstrated shared
caller gap requires explicitly transferred recorder ownership. CAPACITY/CONTROL
need frozen WRITER/CLIENT Redis descriptor/control helper handoff.

Existing keys use a lane hash tag. Cross-lane tenant/deployment accounting cannot
silently run multi-key Lua on Redis Cluster. State the supported standalone Redis
boundary or design explicit same-slot behavior before claiming Cluster support.
No new infrastructure/dependency is required by this plan.

## Minimum native checks and reporting

- Outer borrowed transaction rollback leaves no Event/projection/pending task or
  Redis hint. Commit then kill before publish is recovered without model/tool
  reexecution. Publish then kill before settle allows duplicate hints without
  clearing a newer frontier or accepting stale claimant fences.
- Checkpoint commit crash and Redis outage retry hint without duplicate frames.
- Concurrent two-Worker quota admission, duplicates and generation replacement
  never exceed accounting or release retained bytes early. Crash TTL/ended TTL
  and reads-not-renewing recover quotas within bounded work.
- STOP races against new Run and lease takeover affect only the old scope.
  Redis failure retains pending and never reports display closure completed.
- Any number of transient delta frames produces zero PG notification outbox
  rows and zero per-frame SQL. Durable relay/GC SQL remains included in totals.
- Own native namespaces only; preserve coverage/private/Artifact/durable data,
  unrelated services and primary dirty changes. No push or deployment.

Full crash/quota/STOP/100-subscriber and total SQL/TTFT gates remain open. Final
ACCEPTANCE must use the actual runtime, checkpoint consumer, signed HTTP and SDK;
component source inspection and isolated tests cannot replace that boundary.
