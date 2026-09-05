# Stage 4 — durable source fetch scheduling

Owner: Luke Ding. Status: 7/7 groups in Review after isolated acceptance.
Original services and source credentials remain unchanged.
Parent: `Zebra_Trench_RabbitMQ可靠投递与服务质量实施方案_v1.0.md`, section 10.

## Fixed acceptance groups

1. Explicit source execution scope and credential-reference identity, validated
   against existing source/subscription records; additive migration and backfill.
2. Atomic durable schedule/FetchCommand admission and shared per-source fenced
   claim; concurrent schedulers cannot create simultaneous active executions.
3. Separate source delivery Outbox/Inbox, bounded relay/consumer/recovery using
   approved broker contracts and the same authoritative claim path as fallback.
4. All managed/default RSS, scraper, ARQ, fallback and direct entry paths respect
   the shared migration/eligibility boundary; no old/new double scheduling.
5. Durable fetch results distinguish valid empty feeds, malformed responses,
   configuration evidence, transient errors and rate limits; bounded recovery
   and safe user-visible diagnostics preserve credential isolation.
6. Actual PostgreSQL/Redis failure and duplicate tests plus fetched new content
   visible in authorized history/timeline; another user's private source remains
   inaccessible. Redis rejection cannot advance success or a content cursor.
7. Default-off process composition, explicit cutover, fallback/rollback and
   independent review with recorded terminal database evidence.

Current stage: **7/7 = 100%** at isolated database/broker/product/process
boundaries. This fixed denominator measures acceptance coverage, not effort or
production readiness. Do not count drafts as passed.

First card `RABBIT-SOURCE-SCOPE-01` only adds explicit binding, read validation
and bounded operator CAS backfill. It does not activate scheduling, mutate source
discovery or introduce a credential vault. Unknown bindings are ineligible;
public service authorization requires explicit operator attestation. Principal
bindings and credential references remain non-executable; the final
identity-integrity card deliberately does not add secret resolution or execution.
Existing scope identity is immutable in this slice. An operator cannot silently
convert a shared source into a private one by rebinding it.

Scope-binding slice accepted on 2026-09-05: explicit ORM/additive migration
`6f708192a3b4`, request-config fingerprint, bounded operator preview/apply and
atomic revision/config CAS. Parent **29 passed in 1.48 s**, including three
actual PostgreSQL checks using generated schemas only: migration and visibility,
whole-batch rollback/concurrent CAS, and config change while the operator waits
on a real row lock. Independent SPEC/QUALITY pass; QUALITY reran 26 local cases
and explicitly skipped three PG cases without the private DSN. Implementer also
ran 114 envelope/source-route regressions. Existing source CRUD/discovery,
credential payloads and scheduler entry points are unchanged. This accepts the
first implementation slice, **not** all of group 1; Stage 4 remains **0/7**.

## Current-code evidence refreshed on 2026-09-04

In the isolated Trench checkout:

- `packages/core/src/trench_core/orm/source.py` has global `enabled`, `owner`,
  polling interval and `extra_config`, but no durable FetchCommand or source
  execution fence. Empty `owner` is not proof that a source is public/shared.
- `services/rss_ingest/src/trench_rss_ingest/worker.py` selects enabled managed
  RSS rows and gates them with Redis `last_polled`. Default `:/` routes are
  excluded from that loop and scheduled separately. The marker is schedule
  timing, not proof of successfully persisted article content.
- RSS ARQ jobs and the fallback loop call existing ingest functions directly.
  `services/worker/src/trench_worker/tasks.py` additionally gates scraper jobs
  with stored last-success timestamps. These entry points must share the cutover
  boundary, not compete under separate queue-specific deduplication.
- `packages/core/src/trench_core/redis.py:push_raw` uses a transaction pipeline
  and approximately trims its stream at 50,000 entries. It has no per-fetch
  receipt. `push_events_once` already provides a stable canonical-event Lua
  deduplication seam; reuse it rather than claiming deduplication is entirely
  missing. Its partial-script-error and restart behavior still needs real tests.
- The Normalize `DedupStore` is an in-process optimization, not the sole durable
  correctness boundary. Verify existing canonical IDs/database upserts and Redis
  publication together before adding another deduplication mechanism.
- `trench_ai_social_sources.py` currently maps 401, 403, 429 and 503 together to
  `configuration_required`. A rate limit or transient outage does not prove a
  missing token. Preserve the actual response classification and show a safe
  configuration action only when supported by real diagnostic evidence.

## Scope and safety boundaries

Reuse authorized subscription periods/history filtering. A user pausing or
removing their subscription must not globally disable another user's shared feed.
Credential references belong to their verified scope; broker payloads carry no
tokens, cookies, signed URLs or source bodies. Configuration is through the safe
settings path, not pasted into conversation messages.

This stage migrates **fetch scheduling**, not the entire raw/events/documents
storage pipeline. Successful Redis acceptance is the existing handoff boundary;
no zero-content-loss promise follows from it after Redis loss or stream trimming.
Any durable raw spool requires separate approval. Test lost responses and stable
content identity, but never represent transport acceptance as timeline visibility.

The final proof must include a real HTTP feed fetch through normalization and
persistence into the authenticated history/timeline APIs. A fixture feed and a
public feed must be labeled accurately; neither proves credentialed X access.
Source-specific configuration failures remain explicit, not fabricated content.

## Shared entry-point audit

The shared implementation belongs in core FetchCommand admission/claim/finalize,
not a separate fence in each cron. Managed RSS, default-route RSS, ARQ/fallback
scraper tasks and the standalone scraper CLI must use that boundary when pointed
at a migrated business environment. The CLI may remain an explicitly isolated
diagnostic path, but cannot silently bypass the business rollout gate.

RSS `_record_source_fetch_result` and scraper `record_source_fetch_result` both
write success state today; migrated execution must consolidate that mutation in
fenced finalization. Normalize/canonicalize/archive consume accepted backlog and
must not reapply current fetch eligibility to discard previously received data.

Product-created sources set `owner=user_id` and workspace/product metadata, but
discovery can expose another creator's source and subscriptions can share it.
Thus `owner` is not an authoritative private/public classification. Backfill must
explicitly classify verified public sources; unknown/private/credentialed sources
must not enter shared execution merely because `owner` is empty or populated.
FetchAttempt/raw response/parse attempt records and canonical document/version
IDs already exist. Reuse them; legacy in-memory normalization deduplication is
not equivalent to canonical publication deduplication across process restarts.

The shared envelope already recognizes `trench.source.fetch.ready`, but the
current Rabbit provisioner only installs Trench Turn and Zebra command routes.
Source queue/topology, restricted role permissions and the per-vhost queue limit
must therefore be included explicitly in Stage 4 ownership and acceptance;
having an envelope type alone is not a usable source delivery lane. Do not route
source commands into the existing Trench Turn consumer.

The source lane will use its own source Outbox table: the current Turn relay
selects pending rows without a message-type filter and then only validates
TurnEnvelope. Inserting SourceFetchEnvelope into that Turn table would cause the
old relay to mark it dead. Separate source storage avoids altering accepted Turn
semantics or introducing a generic queue abstraction.

Read-only topology preparation found `/trench` can retain its existing command
and diagnostic exchanges and sanitized diagnostic queue. A dedicated source ready
queue/DLQ would increase its queue count from three to five, within max-queues=8.
Source relay/consumer credentials and exact routing/read ACLs must be opt-in;
old required credential keys and Turn permissions remain unchanged. No topology
or live secret changes have been made for this preparation.

`RABBIT-SOURCE-SCHEDULE-01` is now in Review: source-wide schedule/fence,
FetchCommand and atomic source Outbox, without process activation. Initialization
cannot reset a cooldown/fence; current source configuration and binding revision
must match. Due windows coalesce rather than generate catch-up storms. Actual
claim time extends the next eligible time by the validated polling interval.
Expired work is not automatically replayed; explicit recovery remains a separate
step. A typed Redis handoff checkpoint is a caller attestation, not evidence that
this storage-only slice independently performed Redis IO.

The schedule slice is **6/6 = 100%**: local expanded regression **116 passed /
4 explicit-PG skipped**; parent-generated random-schema PostgreSQL **4/4 passed**
covers migration/namespace and concurrent claims, row-lock DB-clock TTL with
config-winner rollback, expiry while finalization waits, and source Outbox-trigger
whole-transaction rollback. Targeted Ruff, diff and sole-Alembic-head checks pass;
independent SPEC and QUALITY pass, with QUALITY also rerunning six local schedule
cases. This accepts fixed Stage 4 group 2. It does not prove Redis IO, broker
delivery, source-worker execution, private credentials, entry-point cutover,
live migration or fetched-content visibility.

`RABBIT-SOURCE-DELIVERY-01` is now in Review: a separate source Outbox, Inbox
and handoff receipt feed a bounded relay/consumer/recovery loop. Broker and
database fallback share the same transactional source-wide claim; old physical
generations cannot execute. Consumer ACK requires either exact fenced finalize
of a callback-minted Redis checkpoint or confirmed durable sanitized quarantine.
Started or conflicting work is left for explicit reconciliation. Recovery may
reissue only proven accepted-but-not-started work; this includes a broker-off
fallback claim that expires before `started`, without relaxing ordinary lost
broker publication evidence.

Delivery evidence: local delivery **15 passed / 5 explicit-PG skipped**; parent
random-schema PostgreSQL delivery+schedule **9/9**; source topology **9/9**;
isolated live Rabbit source routing and negative ACL checks **1/1**; independent
post-fix SPEC and QUALITY pass. Source topology is explicit opt-in and retains
the accepted Turn lane. This accepts fixed Stage 4 group 3 only. It does not
prove old entry-point cutover, network fetch, Redis content visibility, private
credentials, live migration or process activation.

`RABBIT-SOURCE-CUTOVER-01` is now in Review. A single default-off mode selects
legacy, broker intent or exact database fallback; broker and fallback cannot be
enabled together. Managed/default RSS, scraper ARQ and both legacy fallback
loops enter the same admission authority, while migrated workers keep only one
cron trigger. Standalone scraper use requires explicit diagnostic intent.
Before any IO, the complete source/binding/schedule/command/fence chain is
revalidated under lock and a minimal non-secret immutable request snapshot is
created. A configuration race cannot redirect an admitted fetch. Existing
fetchers and Redis push are reused; migrated legacy status writes are suppressed
until the durable result card defines their replacement.

Cutover evidence: focused source suite **75 passed / 12 explicit-PG skipped**;
parent cutover+delivery+schedule **21/21**, including actual PostgreSQL **9**;
targeted static checks and post-fix SPEC/QUALITY pass. This accepts fixed Stage 4
group 4 only. Empty/result classification, real content visibility, private
credentials, live migration and process activation remain open.

`RABBIT-SOURCE-RESULT-01` is now in Review. Fenced execution returns one of six
sanitized outcomes: content success, valid empty, malformed, configuration
required, rate limited or transient error. Exact command/fence, canonical Outbox
generation, FetchAttempt and available parse evidence are validated in one
transaction before source status changes. A successful content result additionally
requires the existing Redis handoff checkpoint. Retry-After and exponential
delay are bounded by generation and command age; old physical generations remain
auditable as `superseded` and cannot be relayed. Broker and database fallback
share one atomic handoff transaction and post-lock database-clock due check.
Migrated logs expose only source IDs, fixed codes and counts, never target URLs,
headers, bodies, credentials or raw exception text.

Result evidence: combined result/delivery/schedule/cutover/adapter acceptance
**63/63**, including actual PostgreSQL generated-schema due-time, downgrade and
controlled finalize-versus-fallback races. Sentinel-log and malformed-shape
regressions pass; targeted static checks and independent post-fix SPEC/QUALITY
pass. This accepts fixed Stage 4 group 5 only. It does not prove real content
visibility, cross-user API isolation, credentialed X access, process composition
or production activation.

`RABBIT-SOURCE-E2E-01` is now in Review. One real loopback HTTP feed traverses
the accepted PostgreSQL command/Outbox, RabbitMQ relay and consumer, fenced RSS
execution, Redis raw handoff, existing normalization and archive workers, then
the authenticated product timeline and signed Host history Tool. The test uses
random PostgreSQL schema and Rabbit queue identities plus an exclusive bounded
lease for its dedicated Redis database. Duplicate delivery is observed through
the real consumer with two ACKs, zero requeues and one raw item. Deterministic
Redis rejection fault injection proves no source-success or normalize-cursor
advance. A second user's private seeded source/event remains inaccessible to the
first user and vice versa.

Pipeline evidence: the opt-in real E2E is **2/2** and the combined source suite
is **106/106** on actual PostgreSQL, Redis and RabbitMQ where applicable. Cleanup
leaves Redis DB 14 empty and removes the dedicated broker container; post-fix
SPEC/QUALITY pass. This accepts fixed Stage 4 group 6 only. It does not claim a
real Redis outage, credentialed-X execution, process composition, live business
migration or production activation.

`RABBIT-SOURCE-COMPOSE-01` is now in Review. One default-off source process
composes the accepted scheduler, relay, consumer, recovery and quarantine
adapters. Broker and database-fallback execution use the same fail-closed
cutover selector as every legacy scheduler, so an opt-in profile cannot create
old/new double scheduling. The process receives only source transport and
storage settings, drains for 45 seconds, and restores muted broker-client loggers
without exposing connection credentials.

Composition evidence: actual independent Python subprocesses completed broker
execution, database fallback and broker restore; a fourth default-off rollback
process exited before mutation. Terminal state is three Commands, Inbox rows,
receipts and results, with two published Outbox generations and one auditable
fallback `superseded` generation that cannot publish after restore. Actual
subprocess E2E is **2/2**, Redis DB 14 is empty after cleanup, the disposable
RabbitMQ container was removed, and independent post-fix SPEC/QUALITY pass.
This accepts fixed Stage 4 group 7 only. It does not claim credentialed-X
execution, live business migration or production activation.

`RABBIT-SOURCE-CREDENTIAL-REF-01` is now in Review. Binding apply and every
eligibility read validate a non-secret credential reference against the existing
credential identity, enabled state and source platform. Missing, inactive,
mismatched and later drifted references fail closed with fixed safe codes.
Principal bindings still require the exact active user/workspace/subscription
association. The query selects only platform and enabled metadata; credential
payloads are neither loaded nor returned. A valid reference remains
`credential_execution_unavailable`, so no private or credentialed source is
activated.

Credential-reference evidence: final source regression **100 passed / 21
explicit-integration skipped**; focused actual generated-schema PostgreSQL
**5/5**, including a controlled credential-writer versus binding-apply lock race;
targeted Ruff/format/diff checks and independent SPEC/QUALITY pass. This accepts
fixed Stage 4 group 1 and closes Stage 4 at **7/7 = 100%**. It does not claim
credential secret resolution, credentialed-X fetching, live business migration
or production activation.
