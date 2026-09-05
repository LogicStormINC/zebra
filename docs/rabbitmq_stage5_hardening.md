# Stage 5 — rollout hardening audit

Owner: Luke Ding. Status: fixed acceptance scope; groups 1–2 accepted.
Stages 3 and 4 passed their isolated prerequisites. This document separates
implemented hardening from production activation.
Parent: `Zebra_Trench_RabbitMQ可靠投递与服务质量实施方案_v1.0.md`, sections 7, 12–15.

## Fixed acceptance groups

1. Atomic tenant/user active and queued admission limits, bounded database
   Outbox backlog, and fair oldest-first pickup across active scopes.
2. Explicit default-off scope allowlist rollout plus a physically separate,
   side-effect-free bounded shadow lane and message-id reconciliation.
3. Fallback-first pause/drain/restore/rollback state machine; no lease stealing,
   queue purge, Outbox deletion or dual execution during transitions.
4. Frozen replay and retention windows with bounded terminal-only cleanup,
   preserved receipts/tombstones, expired-message quarantine and privacy erasure
   coverage for diagnostic records.
5. Backup/restore reconciliation of PostgreSQL authority against stale broker
   hints, including generation/state checks and a recorded fresh-restore drill.
6. Privacy-safe low-cardinality metrics and readiness thresholds for Outbox age,
   claim latency, retries, fallback, quarantine and broker alarms.
7. Actual three-node quorum broker fault/majority/restart/rolling-upgrade
   acceptance with pinned versions and deterministic cleanup; explicitly not a
   managed-production HA claim.
8. Final cross-service fault matrix plus real-model streaming, refresh/replay,
   multi-user isolation and authenticated file-download browser regression.

Current stage: **2/8 = 25%**. The denominator is frozen before implementation;
drafts and pre-existing partial seams do not count until tested and independently
reviewed. Production activation remains a separate operator decision.

## Code evidence (2026-09-05)

1. Trench `TrenchAiTurnStore.submit` already checks one active turn per
   conversation and a user active-turn limit. The conversation lock does not
   serialize the user limit across different conversations. Reuse admission and
   add an atomic user quota boundary; do not build a second admission service.
2. Zebra `CommandWakeupConsumer` and Trench `TrenchAiTurnDispatcher` already have
   bounded execution capacity and independent control capacity. These are
   process-local limits, not durable tenant quotas across replicas.
3. Zebra `discover_command_pickups` already has stable keyset pagination and
   independent execution/control lanes; recovery has its own cursor and resolves
   canonical scope. Global FIFO alone is not tenant fairness. Preserve these
   bounded selectors rather than reverting to recent-session scans.
4. The current local broker provisioner caps ready queues at 4 MiB with
   reject-publish, DLQ at 1 MiB/24 h and diagnostics at 4 MiB/7 d. Those limits
   do not cap PostgreSQL Outbox admission. A full broker can shift unbounded
   pressure into the database; scope backlog admission needs separate proof.
5. Zebra command recovery already limits generation count to five and total
   age to 24 h. Envelope timestamp syntax validation is not a universal replay
   age check. Use canonical creation time and the existing recovery budget when
   defining the replay contract; do not trust the broker's timestamp as authority.
6. Trench broker recovery has bounded candidate pagination, lease and due-time
   checks. The inspected path does not have Zebra's total generation/age cap.
   Retry delay alone does not provide a terminal retry budget.
7. Trench event replay is user/workspace authorized and paginated at 200;
   Zebra AG-UI has exact cursors and authorization deadlines. Those are not a
   persistent retention watermark or an expired-cursor contract. Do not delete
   replay evidence based on a transport cleanup policy.
8. Governed-memory tombstones and artifact retention pruning are existing
   domain-specific examples, not broker deduplication implementations. Command
   receipts, Inbox, retirement audit and Outbox require their own minimal
   preserved evidence before any payload cleanup. Never delete business effect
   receipts together with transport Inbox rows.

## Acceptance boundary still open

The approved plan additionally requires fallback-first drain/rollback,
privacy-safe metrics, bounded replay/cleanup,
backup restore reconciliation, broker fault/HA evidence and final real product
regression. The current single-node test broker is not proof of production HA.
Freeze concrete retention/replay windows before adding destructive cleanup.
Maintain the distinction between database tests, process faults, real-model
browser/download tests and production activation in the completion ledger.

## Group 1 acceptance — capacity and fair pickup

`RABBIT-ROLLOUT-CAPACITY-01` is accepted at the isolated database boundary.
Trench serializes each user's cross-conversation admission with a PostgreSQL
transaction advisory lock before evaluating the existing active-turn quota.
Zebra applies one global-then-scope lock order, separate execution/control
scope ceilings, a hard unpublished-Outbox ceiling and a reserved control slice.
Live admission, recovery, backfill and the v48-compatible database trigger all
share the bounded Outbox invariant. A full exact retry remains idempotent; an
existing pending row whose exact generation-zero command Outbox is absent or
wrong does not bypass capacity.

Pickup keeps its forward keyset cursor while periodically scanning a frozen
high-water ring of active scope heads. Continuous tail traffic cannot extend a
frozen ring, a newly active scope behind the current probe enters the next ring,
and a stable backlog beyond sixteen pages remains reachable. Both paths have
matching partial indexes and actual `EXPLAIN` evidence.

Acceptance evidence: Trench focused configuration and actual-PostgreSQL quota
tests passed; Zebra focused migration/pickup tests passed 25/25, combined actual
PostgreSQL/API regression passed 146/146, and the exact old-writer negative
migration regression passed 2/2 after the combined run. Independent SPEC and
QUALITY reviews both passed with no Critical or Important finding. This is not
a production activation or a general business billing quota.

## Group 2 acceptance — scoped rollout and exact shadow evidence

`RABBIT-ROLLOUT-SHADOW-01` is accepted at the isolated delivery boundary.
Both products default every unlisted scope to database fallback and share one
audited scope authority across publisher, broker consumer and fallback pickup.
Execution and control handoff acquire the rollout advisory lock and recheck the
required mode inside the mutation transaction, so a mode flip cannot authorize
the stale lane. Shadow writes use non-blocking scope/global advisory locks and
therefore never delay formal admission.

Shadow delivery has a separate bounded Outbox, exchange, queue, transport and
consumer principal. Configuration compares percent-decoded AMQP users, and the
provisioned ACLs restrict formal and shadow users to mutually exclusive queues.
Legacy credential files remain valid for formal roles; `prepare-shadow` appends
new identities atomically without rotating existing bytes, preserves mode 0600
and leaves the original unchanged on replacement failure. Reconciliation starts
from eligible formal Outbox rows and counts mirrors/observations only when the
full formal message ID, shadow message ID, scope key and envelope digest agree.

Acceptance evidence: Zebra focused regression passed 63/63 and actual PostgreSQL
rollout/control regression 30/30; Trench focused regression passed 32/32 and
actual PostgreSQL reconciliation passed 1/1. An isolated RabbitMQ instance
proved mutually exclusive formal/shadow ACLs for Zebra commands, Trench turns
and Trench source fetches. Zebra `make check` passed file-size 1893, Ruff, Mypy
847 and eval 10/10. Trench `make check` passed Python 120+67, both frontend
production builds, ToC 33 tests/lint, migrations and diff check. Independent
SPEC and QUALITY reviews passed with no Critical or Important finding. No
production activation, commit, merge or push is implied.
