# Stage 3 — Zebra command delivery

Owner: Luke Ding. Status: implementation in progress, no original activation.
Parent: `Zebra_Trench_RabbitMQ可靠投递与服务质量实施方案_v1.0.md`, section 9.

## Direct control compatibility (accepted)

The public Task cancellation path now composes its operation from the actual
cloud DSN. Verified Host identity is checked against the frozen Task binding,
including the current `agent.run` permission. Generic trusted cloud callers use
an explicitly injected scope and canonical Session identity evidence; history
read scope is not converted into cancellation authority. Execution-grant expiry
does not prevent an independently authorized cancellation.

v48 adds direct operation identity and generalizes the existing cleanup queue to
one `cleanup_id` with exactly one command or direct-operation anchor. The shared
Session cancellation transaction writes terminal Events/projections and revokes
the exact old lease before committing the cleanup obligation. No fake accepted
command, new cleanup queue, engine call in the transaction, or cloud-wide Session
container deletion is introduced. Optional `Idempotency-Key` supports scoped
replay; repeated no-header cancellation keeps the existing terminal conflict.

The response retains its fields and successful HTTP status, but the cloud
workspace status is honestly `cancelled`, not `destroyed`: physical removal is
asynchronous. Local snapshot/control behavior remains separate; cloud user
SUSPEND explicitly returns unsupported without mutation. Parent-owned actual
PG/Docker tests pass 6 cases in 32.44 s, including direct cancellation and
preservation of an unrelated same-Session container.
Final combined actual PG direct/API/ACP/migration, legacy control/cleanup,
runtime-instance and lease-clock regression: 91 passed in 90.63 s. SPEC passes
with 39 independent local cases; QUALITY also passes. Local focused 44 passed;
make check passes (834 typed files, 10 evals). Slice accepted 5/5, original off.
Full local suite collected at the direct-control stable snapshot: 3,184 passed,
671 infrastructure/opt-in cases skipped in 752.64 s. This is separate from the
91 actual-PG and 6 actual-Docker checks, not evidence that skipped cases passed.
Task-target changes made after collection require their own later validation.

SPEC also identified an existing Task-target boundary: Task cancellation selects
the active Segment outside the cancellation transaction. A cancel that wins first
invalidates a prepared handoff through stream/fence changes; a handoff that wins
with a terminal source causes cancellation to conflict. However, a suspended
source and a Task retry after rollover still need exact target/CAS validation.
`RABBIT-ZEBRA-TASK-CONTROL-TARGET-01` tracks this prerequisite; no cross-rollover
Task cancellation guarantee is inferred from the direct Session transaction tests.

The follow-up Task-target slice is now accepted 5/5: final 65 actual PG cases in
59.56 s and 18 shared PG handoff/migration/authority/workspace cases in 6.74 s,
make check (835), SPEC/QUALITY. Session-before-Task NOWAIT target CAS rejects
obsolete active selection; same-key Task replay uses the original operation's
Session and revalidates membership and caller identity. The actual handoff tests
exercise both winners, not only sequential API mocks. PG child TASK_PREPARED now
preserves verified frozen HostContext, allowing namespace replay, child command
admission and cancellation; the original expiry is preserved and the existing
authority resolver still rejects expired grants.

SPEC caught a two-read error in the first identity-propagation patch: context A
was returned after another query validated B. A shared single-query validator
now returns the exact validated context. The regression uses a real PG connection
proxy with controlled read results; it does not claim a concurrent writer drill.
An inherited PG workspace test's hidden missing-fixture issue was corrected with
explicit fixture imports; no production constraint was relaxed.

## Fixed acceptance groups

1. Common PostgreSQL command admission: canonical Event, pending index and
   separate Broker Outbox atomically persisted; duplicate IDs and rollback proven.
2. Bounded pending/backfill/recovery queries: old sessions, stable pagination,
   live-admission overlap and published-but-unhandled recovery.
3. Fenced relay: mandatory confirms, stable physical retry identity, no network
   while holding database locks.
4. Inbox/handoff: authoritative scope verification and the existing Session
   Lease/Fence in one transaction, shared with fallback pickup.
5. Bounded scheduling and independent control: ACK after durable handoff and
   successful local scheduling; CANCEL never waits behind long RUN execution.
6. Default-off composition, rollback and actual PostgreSQL/Rabbit fault acceptance.

Current completion: **5/6 = 83.3%**. Groups 1–5 accepted; group 6 remains open.
In-progress groups count as zero. The group count
measures acceptance coverage, not effort or production readiness.

## First slice: RABBIT-ZEBRA-ADMISSION-01

Use the existing `append_event_in_transaction` PostgreSQL seam, not individual
HTTP handlers. Its callers include public command submission, approval resume,
client-effect receipt/resume and internal child wakeups. Non-command events and
SQLite behavior stay unchanged. Existing Effect Outbox is not reused or renamed.

The admission migration switch is a durable per-deployment database row, missing
or false by default. This ensures every transaction producer makes the same
choice without implicit process-global environment reads. Enabling it is an
explicit rollout operation, not a side effect of importing code or migrating.
This slice does not compose Rabbit publisher or consumer processes.

For enabled deployments, scope comes from authoritative session projection and
frozen task binding: tenant is the verified Host namespace, workspace is the
Host workspace reference. Namespace agreement and existing binding validation
are required. A missing/inconsistent binding fails the admission transaction;
there is no implicit public/deployment fallback or physical-path identity.
References must satisfy the existing bounded envelope contract; never truncate.

The accepted Event remains the business authority. Pending and Broker Outbox are
rebuildable delivery indexes. Idempotent append paths use the original canonical
command/event IDs, sequence and occurrence time. Internal child wakeups
intentionally use different Event and payload idempotency keys; preserve that
existing epoch-based behavior instead of rewriting it to fit an HTTP-only shape.

All new tables are additive. No new worker lease or Effect authority is added.
Follow-on recovery must not treat session projection sequence as proof that every
accepted command was handled. Rollout requires old-session and control-path
acceptance before normal command polling can be disabled.

## Group 1 acceptance evidence

Focused/common-seam plus real PostgreSQL tests: 36 passed in 12.58 s, including
the actual API, approval, client receipt and child terminal producers. Initial
producer fixtures required valid approval FSM setup and the child status argument;
these were corrected without changing production FSM or method contracts.
Existing real-PG task-admission/client-effect/tenant tests: 14 passed in 1.48 s. One inherited
tenant test expected Host access to unbound operator sessions; its assertion was
aligned to the already-hardened guard and explicit operator access retained.
No production permission logic was relaxed. A table-existence test now checks
current_schema(), rather than counting all isolated test schemas in the database.
Full make check passed: file-size gate, Ruff, Mypy (794 source files) and 10 evals.
Independent SPEC and QUALITY both pass, each independently running 17 unit cases.
Group 1 is accepted; slice RABBIT-ZEBRA-ADMISSION-01 is 5/5 (default-off schema,
shared canonical admission, frozen scope, four-producer rollback, tests/reviews).

The unreleased v35 was refined during testing; baseline reruns use a fresh
isolated schema, without rewriting an applied migration checksum. New focused
PG cases each create and dispose their own schema. Original databases are untouched.
Outbox scheduling uses database clock_timestamp(), not caller Event time;
the envelope preserves the Event instant in UTC for stable retry hashes.

Approval currently commits its decision before submitting the RESUME command.
This slice's atomic promise is RESUME + pending + Outbox, not the preceding
approval decision. Client-effect receipt and child settlement already use wider
transactions, so their wakeup failures must roll back those companion writes too.

## Discovery slice accepted

`RABBIT-ZEBRA-DISCOVERY-01` adds explicit, bounded historical backfill and scoped
pending discovery only. Group 2 remains open until recovery generations pass too.
The existing worker `command_consumer.py` scans recent sessions and starts reading
after session.current_sequence. `session_projection.apply_event` advances that
sequence for every event, not just handled commands. Therefore neither value is
proof of command consumption; copying that predicate into the new queue would
silently lose older accepted intents.

Backfill uses stable (session_id, sequence) order and a durable high-water/cursor,
not producer timestamps. Explicit cutover establishes a short, timeout-bounded
barrier with concurrent Event inserts before enabling live admission. Each batch
commits its derived records and cursor together; invalid historical scope stops
the batch without skipping identities. No consumer starts as a side effect.

Backfilled pending rows are discovery candidates, not permission to rerun old
business work. The later handoff/consumer slice must reconcile canonical command
receipts and lifecycle state under the existing Lease/Fence before execution.
It must not infer that all historical RUN/RESUME intents are safe to execute.

Discovery validation: 60 combined focused/real-PG cases passed in
19.64 s (24 discovery + 36 admission), full make check passed with 796 typed files.
The cutover barrier is an explicit maintenance operation: it briefly blocks all
Event inserts, with five-second lock acquisition timeout. It is not a claim of
zero impact across deployments, and is never invoked by ordinary startup.
Independent SPEC and QUALITY pass (16 discovery validation cases each; quality
also reran 17 admission unit cases). This slice is 5/5, not all of group 2.

Additional dormant storage regression: 193 passed, 344 skipped in 3.12 s without
infrastructure credentials. This is separate from the real-PG acceptance above.

## Confirmed handoff prerequisite: expired heartbeat resurrection

An isolated real-PG probe of the existing PostgresLeaseStore found that a heartbeat
started before expiry, then blocked behind a row lock until after expiry, succeeds
with the old fence. Probe: acquire a synthetic three-second lease; hold its row
FOR UPDATE; start heartbeat; independently verify clock_timestamp() > expires_at;
release lock. Result: heartbeat accepted with the original fence, get() reports an
active lease. No original namespace or runtime was involved.

The pre-fix lease SQL used transaction_timestamp() for expiry checks and renewal,
so lock wait time does not age its test. Group 4 must fix this shared lease boundary
and add blocked-lock regression coverage before broker/fallback handoff is enabled.
This is a confirmed existing defect, not a passing acceptance case or a reason to
introduce a second execution lease. Discovery work does not alter lease semantics.

Pre-fix shared-caller baseline: real-PG workspace, handoff dispatch, effect payload
transactions and model/tool projection tests pass 38 cases in 10.96 s. Existing
lease plus producer baseline passes 29 cases with one test-isolation failure:
the timezone test overwrites DSN options and loses search_path. The lease-clock
slice will preserve those options rather than weakening runtime epoch validation.

RABBIT-ZEBRA-LEASE-CLOCK-01 is now accepted 5/5: shared post-lock DB clock,
full-fence/lock-order compatibility, UTC/DST correctness, actual PG regressions,
and independent SPEC/QUALITY. Final combined suite: 81 passed in 27.27 s; full
make check passed (796 typed files). Each reviewer independently passed the three
DST unit cases. No original runtime was changed. The assertion authorizes its
post-lock check instant; it does not promise validity after arbitrary later waits.

## Relay acceptance

RABBIT-ZEBRA-RELAY-01 is accepted 5/5: short DB claim/settle transactions,
bounded asynchronous confirmed publication, canonical identity validation,
stable physical retry identity and actual fault tests/reviews. The additive v37
index supports expired publishing rows; v35/v36 are unchanged. Poison rows get a
fixed diagnostic, never raw exception text. Cancellation leaves an expiring claim.

Actual isolated PG/Rabbit and prior admission/discovery/clock suite: **111 passed
in 49.94 s**. A real confirmed publication followed by injected confirmation loss
produced two identical physical message bodies and one published Outbox row with
two attempts. A separate connection obtained FOR UPDATE NOWAIT during publication,
proving no Outbox row lock spans network IO. Only the synthetic test messages were
acknowledged; queues were not purged. This proves transport retry, not exactly-once
business execution. Full make check passes (799 typed files); SPEC and QUALITY
each independently pass 21 tests, skipping infrastructure they did not connect to.
Original runtime activation remains off. Inbox and existing Lease/Fence handoff
must still establish execution deduplication and recovery responsibility.

## Historical reconciliation boundary

Worker execution currently takes session_id/worker/TTL, not command_id.
HARNESS_ATTEMPT_STARTED generally records attempt_number, not the originating
command. Neither a later attempt/terminal event nor projection.current_sequence
or lease checkpoint proves an arbitrary RUN/RESUME was handled. MESSAGE has a
specific USER_MESSAGE_RECEIVED idempotency key (`<command-key>:message`), which
proves input append only; its matching turn_id terminal can prove that Turn closed.
Client-effect and child settlement receipts similarly prove their own operations,
not the resulting parent continuation's completion.

New handoffs need an explicit canonical command/Event and lease-fence association.
Historical commands without sufficient evidence remain requires_reconciliation;
do not claim completed or replay automatically. Existing child continuation's
uncertain-prior-model-call guard and pending-Turn-close reconciliation remain
authoritative. Rabbit delivery cannot improve missing historical evidence.

Storage handoff RABBIT-ZEBRA-HANDOFF-01 accepted 5/5: v38 conservative origin,
canonical trusted-scope validation, atomic Inbox/receipt/existing Lease, fallback/
broker races and rollback, independent reviews. Only the new Event INSERT marks
live; duplicates/backfill never upgrade origin. Live itself does not prove an old
unassociated polling worker has not run it: final cutover must use the common
receipt seam for both paths, with no untracked legacy execution overlap.

Initial 118 PG tests passed in 59.80 s. Quality review then found a terminal-state
race: an old worker could commit terminal while handoff waited for its lease lock.
The corrected helper checks projection after acquiring lease serialization and
rolls tentative lease changes back via savepoint on terminal. Actual cancelled/
completed/failed lock-wait tests plus clock suite: 40 passed in 35.40 s. Shared
lease/workspace/handoff/effect/model-projection callers: 54 passed in 14.87 s.
Full make check passes (801 typed files); SPEC and final QUALITY pass. Busy,
unsupported MESSAGE/control and earlier-unreconciled commands get no execution
lease; historical ambiguity is recorded, not completed. Group 4 remains open.

RABBIT-ZEBRA-RECEIPTS-01 accepted 5/5: v39 adds precise started/handled Event IDs
and an execution floor sampled from canonical stream head after lease acquisition.
The floor only rejects attribution of older Events; it is never a handled watermark.
An exact full-fence receipt plus a later canonical START is required before a
definite pause/Turn/session terminal can mark that command handled. Arbitrary
model responses never do. Primary worker Event/projection/receipt/pending update
is atomic; already-projected replay is idempotent. Handoff removes early business
row locks so worker lease-to-receipt ordering is preserved.

Initial PG execution exposed nine invalid test payloads (empty suspension and
clarification data); fixtures were corrected against unchanged production contracts.
Final 61 receipt/handoff/clock tests passed in 58.73 s; 54 shared caller tests passed
in 14.49 s; make check (803) and SPEC/QUALITY pass. The completed-tool continuation
currently writes a raw START then reconciles projections/receipt in another
transaction. This is exact later reconciliation, not retroactive atomicity. The
next worker-entry slice forwards its existing recorder to remove that raw-start
gap when composed. No consumers or original runtime are enabled.

RABBIT-ZEBRA-CLAIMED-EXECUTION-01 accepted 5/5: public existing-lease entry,
same-fence recovery/heartbeat/cleanup, shared execution path, recorder forwarding,
actual PG execution and independent reviews. Final **42 passed in 8.28 s**.
The PG fixture uses real event/projection/lease/receipt stores, a temporary local
runtime, explicit test authority and scripted model. Auxiliary local continuation/
effect stores are isolated; this is not real cloud/model acceptance. Initial
fixture omissions (indexes, auxiliary stores, pinned policy) were corrected without
weakening production guards. The result reaches SESSION_COMPLETED; handled receipt
correctly stays on the earlier TURN_COMPLETED and matching turn_id. Expired and
successor fences cannot execute or release the successor. Full make check (803)
and SPEC/QUALITY pass. No normal consumer path has been activated yet.

## Recovery acceptance

Existing task recovery reconstructs input/context, not a general in-flight model
program counter. Persisted MODEL_RESPONSE_RECEIVED without a definite handled
boundary cannot automatically be consumed or replayed safely. Provider continuation
restores context selection, not proof that the next model request did not happen.
Expired started commands therefore require explicit reconciliation in this slice.

Only published/no-handoff and expired, provably unstarted handoffs may receive an
approved new wake generation. A NULL started ID alone is insufficient: inspect
canonical post-floor evidence after existing lease serialization. Preserve prior
receipt/fence/floor/Inbox in durable attempt history; old-generation delivery must
never reclaim execution. Approval, pending generation and successor Outbox commit
together. New message causation refers to the previous physical message; physical
retries within that generation retain identity. Existing active leases, handled,
terminal, historical and exhausted operations never revive automatically.

An actual PG EXPLAIN check also identified a selector inefficiency: comparing
available_at directly with volatile clock_timestamp() left time as a Filter,
with only namespace in Index Cond. Sampling DB time first and passing it as a
bound query parameter adds the due-time range to Index Cond. Selection may use
that snapshot, but every ownership decision still samples DB time after locks.
This is planner evidence, not a throughput benchmark; full queue fairness/load
acceptance remains separate.

Accepted RABBIT-ZEBRA-RECOVERY-01: 5/5. Combined actual PG/Rabbit regression
129 passed; final recovery matrix 44 passed in 33.70 s, including poison-first
small/large batches, scope mismatch protection, propagated DB failure and both
fallback/recovery race orders. Make check (806) and SPEC/QUALITY pass. Invalid
derived rows only quarantine their own trusted-scope pending record using fixed
codes; canonical evidence and other tenants remain untouched. Group 2 accepted.
This is not generic model continuation or runtime activation.

## Control and composition audit boundary

The old command consumer synchronously waits for RUN execution and scans recent
sessions after projection sequence. New mode must replace that consumer, never
run both. Retain child wakeup producers and memory finalization independently.
Cloud already disables the generic ready-session scan; preserve local behavior.

CANCEL/STOP require a separate bounded control lane which cannot wait on RUN
capacity or on prior RUN handled receipts. A shared Rabbit queue/prefetch alone
does not ensure delivery under full RUN credit; an independent bounded PG control
scan is sufficient without adding another queue. Control must verify canonical
identity/scope/generation, serialize lease/stream, revoke the current fence and
persist terminal Events/projections plus a control receipt atomically. External
runtime cleanup occurs afterward, never inside the DB transaction. Revocation
blocks future fenced writes but cannot retract an already issued external effect
or instantly interrupt a blocking model HTTP request.

Existing cloud user snapshot suspension is not resumable by the current worker;
only trusted waiting-children logical suspension has a supported cloud restore
path. Do not fabricate snapshot metadata or report generic resumability. The
control slice must expose an explicit unsupported outcome for unsupported cloud
suspend, retaining local snapshot behavior. Control outcomes must not be forged
as old worker handled receipts; predecessor checks need exact control evidence.

The real Trench continuation path is Task message append followed by AG-UI RUN,
not SessionCommandKind.MESSAGE. Nonterminal AWAITING_TURN keeps the same Session;
only terminal Tasks roll to another Segment. Historical RUN commands without
exact receipts therefore block later RUN under the new predecessor guard. Before
cutover, explicitly coordinate old commands: terminal Session wakeups can record
canonical-terminal no-op; nonterminal cutover retirement must be an audited
operator decision (scope, command range, evidence Event, actor and reason), never
inferred completed execution from projection sequence. No existing endpoint
provides that coordination today. Activation must wait for this compatibility
test using the actual Task messages then RUN path. Existing core task rollover
must not be silently forced for all conversations.

Consumer scope is resolved from canonical accepted Event and frozen Task binding
inside the configured deployment namespace. Raw IDs are lookup hints only;
envelope.scope is not the trusted scope argument. Existing binding checks and
execution authority freshness checks remain mandatory and distinct.

## MESSAGE acceptance

RABBIT-ZEBRA-MESSAGE-01 accepted 5/5: 12 actual PG cases in 24.15 s; expanded
message/handoff/receipt/recovery/worker regression 145 passed in 108.00 s.
Make check (808) and independent SPEC/QUALITY pass. The core message validator
builds canonical input inside the lease/stream transaction; v41 records exact
input_event_id. Duplicate or approved recovery reuses it, including clarification.
Open-Turn or invalid input rolls back tentative lease/input before recording
reconciliation. Original services remain off; Trench direct Task message + RUN
compatibility and historical migration are separate pending acceptance.

## Control storage acceptance

RABBIT-ZEBRA-CONTROL-01 accepted 5/5: final 18 actual PG tests in 21.21 s;
combined control/message/handoff/receipt/recovery 121 passed in 133.03 s.
Make check (810) and SPEC/QUALITY pass. Cancellation waits only for the existing
lease/stream write boundary, not RUN completion, and atomically revokes that
fence, closes any open Turn, cancels Session and records exact control evidence.
Older pending commands are linked to the cancelling control, not given fabricated
worker handled receipts. Duplicate, invalid scope/generation, historical/dead
candidates and rollback cases preserve canonical evidence. Runtime cleanup is a
durable pending obligation; no cleanup network request or capacity-saturated
consumer acceptance is claimed yet. Cloud user SUSPEND has explicit unsupported
outcome; the exact receipt allows following supported commands past that intent.

## Remaining composition checks

Long synchronous worker calls must not use the same finite thread pool as control
DB operations. Reserve bounded execution capacity before lease acquisition and
keep it until actual execution finishes, not merely until an async wrapper is
cancelled. Shutdown must stop admission first, settle ownership under the exact
fence and distinguish an uninterruptible HTTP call from completed worker drain.
The existing heartbeat already runs independently; do not acquire another lease.

Recovery/rejection receipts are currently DB-visible only. Composition must add
an authorized, run-correlated client outcome path so a rejected or uncertain
command does not leave AG-UI/SSE waiting indefinitely. Do not expose raw errors,
invent successful completion, or interpret arbitrary model output as a terminal.
Runtime cleanup obligations also require a bounded, retryable post-commit worker;
the control storage acceptance does not count those obligations as performed.

## Historical cutover acceptance

RABBIT-ZEBRA-CUTOVER-01 accepted 5/5. Final cutover/control/handoff/message
regression: 81 actual-PG cases in 97.03 s; make check (812), SPEC/QUALITY pass.
Explicit operator preview/apply validates active Task, frozen scope, canonical
stream/projection, exact historical backfill set, real closed conversation Turn,
title-only tail and no unreleased lease. Immutable audit and cancelled pending
commit together without changing business Events. Old deliveries return retired
no-op; actual Task append returns 201 and following RUN can acquire in the same
Session. Early fixture mistakes (201 expectation, invalid random Segment FK) were
corrected without weakening production contracts. SPEC found missing stream-head
validation; shared preview/apply now rejects drift or missing head. Missing-head
test injects that read only, keeping FK constraints and remaining DB operations.

Operator retirement uses try-advisory and lease NOWAIT so it cannot hold the
root Task/Session advisory while waiting for a Worker row lock. Shared audit also
found a constructible inversion in the public fenced Task-attach adapter: it
takes lease/stream before the same root advisory. No current worker-runtime caller
was found, so this is not evidence of a production incident. Correct its shared
source-Session advisory ordering and validate root/non-root concurrency before
accepting group 4. Uniform deployment requires draining old related transactions;
no advisory-key rewrite or mixed-version live-upgrade guarantee is proposed.

TASK-LOCK accepted 5/5: 7 real PG cases in 7.70 s and 24 shared Task cases in
12.55 s; make check (812), SPEC/QUALITY. A controlled subprocess removing only
the new Session lock fails the regression on transactionid vs advisory wait.
This closes group 4. Bounded consumer/control scheduling is the next slice;
cleanup, client outcomes and process composition remain unaccepted.

## Post-commit cleanup safety audit

The current OCI adapter's `destroy_session` filters only `zebra.agent.session`;
`provision` also invokes that session-wide deletion. Existing labels carry spec
and attempt but not deployment/scope/full LeaseFence. Container IDs live only in
the adapter's process-local maps. Therefore connecting the cleanup obligation to
this API is unsafe on a shared engine: a same-UUID Session in another deployment
or a newer execution instance could be removed. DB scope checks alone do not
narrow that external deletion target.

Before cleanup activation, register an execution instance under the existing
fence before container creation. Persist namespace/scope/Session/full fence,
instance identity and trusted engine identity; label the container consistently
and record the exact container ID after creation. A crash between create and ID
recording must be recoverable by the pre-registered instance identity. Cleanup
resolves only the cancelled fence's instances, verifies exact external identity,
and performs network work after its claim transaction commits. Missing legacy
ownership evidence means reconciliation, never session-wide fallback deletion.
The shared provision pre-cleanup must obey the same boundary. No revoked fence
is not permission to delete every runtime for the Session.

Required tests: same UUID across namespaces/scopes, successor fence preservation,
create-before-ID-write crash, wrong engine/labels, retry after deletion failure,
already absent target, and stale cleanup settlement. Canonical cancellation and
actual runtime termination remain separate proof levels. This is a verified
implementation gap, not evidence that an original user container was deleted.

AG-UI currently tails canonical Task Events. Command-only unsupported/reconciliation
receipts do not become a terminal stream event. Add an authorized exact accepted
Event/run mapping to durable outcomes and reuse RUN_ERROR for explicit failure;
do not infer ownership from the Session's latest error, invent Event cursors, or
report successful execution. Reconnect must reproduce the same settled outcome.

## Consumer review findings

Initial combined pickup/migration/runtime/control/handoff suite passed 72 cases
in 52.39 s, but SPEC found that the consumer requeued an already durable
requires-reconciliation receipt indefinitely. That outcome must ACK without
execution, unlike transient capacity/lease contention. Transient requeue also
needs bounded delay to avoid broker hot loops. These fixes and re-review gate
consumer acceptance; the passing initial suite alone does not close group 5.

Consumer accepted after those fixes: final 40 PG/runtime/migration cases in
15.23 s, make check (815), SPEC/QUALITY. Slots follow actual synchronous Future
completion, with separate control DB capacity and keyset lane discovery. Broker
ACK follows durable outcome or successful execution submission; submit failure
retains exact recovery responsibility. No process activation or real-model
capacity-saturation claim. Group 5 is accepted; group 6 retains quarantine,
instance-safe cleanup, client outcomes, composition and real fault acceptance.

## Runtime instance implementation boundary

Use an optional narrow instance lifecycle collaborator in OCI and inject it for
cloud worker execution; do not change SandboxSpec/digest with ephemeral fence
values. Reuse RuntimeHandle.handle_id as the per-provision identity, including
separate setup and agent containers. Reserve before create, record the returned
exact ID, then refuse start/execute if authority was revoked. Cloud construction
must fail closed when the lifecycle is absent; local construction stays compatible.
The engine identity must represent its pinned endpoint/configuration, not only
the executable name `docker`. Do not persist engine credentials.

In particular reserve→cancel→late create cannot be treated as completed cleanup
after one empty container scan. A provisioning reservation with uncertain create
result remains an obligation. Label/name recovery covers create-before-ID-write
crashes; failure to delete retains the exact target for retry. Lifecycle tracking
and cleanup executor are separate bounded slices; no generic fleet framework is
needed. Old unowned resources require explicit reconciliation.

## Final fixture database boundary

The retained Stage-2 `zebra_e2e` public schema contains an earlier draft v35
checksum. Do not rewrite its migration ledger or blindly restart migration over
it. Per-test fresh schemas have validated current migrations through v45; that
does not make the old public schema compatible. Final composed acceptance needs
an explicitly pinned fresh Stage-3 Zebra/Trench database pair in the existing
isolated PostgreSQL fixture, preserving the Stage-2 databases and evidence.
Fixture target validation must explicitly allow only those owned test targets;
no arbitrary database override or original database cleanup is authorized.

Public control compatibility must be composed before activation: existing
Task/Session cancel routes call SessionControlService, whose cloud path builds a
runtime without a lease and performs session-wide deletion before canonical
cancellation. A mandatory safe lifecycle will correctly reject that path but
cannot be shipped as a silently broken cancel API. Route cloud cancellation
through authorized canonical cancellation and deferred exact-instance cleanup,
preserving supported generic cloud authority as well as Host-bound commands.
Trace all callers and retain local snapshot/control behavior; transport acceptance
must not be represented as already physically stopped.

Engine compatibility references used for the pinned adapter: [Docker CLI routing](https://docs.docker.com/reference/cli/docker/),
[Docker TLS](https://docs.docker.com/engine/security/protect-access/),
[Docker daemon info](https://docs.docker.com/reference/cli/docker/system/info/),
and [Podman remote URL/connection selection](https://docs.podman.io/en/stable/markdown/podman.1.html).
The existing isolated Docker TCP fixture remains supported; explicit TLS may not
be silently downgraded. Podman selectors are verified from its manual and mocked
adapter tests, not a running local Podman service. Daemon ID comparison detects
accidental drift but is not cryptographic authentication or an atomic Docker/DB
transaction. Full instance/container identity checks remain necessary.

Runtime instance slice accepted 5/5: final 20 actual PostgreSQL cases in 23.33 s,
expanded 66 cases before the final expiry correction, make check (827), SPEC and
QUALITY pass. QUALITY caught authority/lease expiry while waiting for an instance
row; authorize now rechecks both after that wait under the existing lock order.
Tests observe the real lock wait and DB deadline. No live Podman or composed
cloud cancel claim. Exact post-commit cleanup is the next claimed slice.
Controlled subprocess replacement with the pre-fix authorize implementation
fails both new expiry tests (2 expected failures, 3.99 s); production source and
the original checkout were not altered by this negative check.

Public cancellation audit distinguishes routes: cloud Session cancel/stop/suspend
already submit commands (202), but Task cancel, ACP and legacy worker callers
still use SessionControlService. Preserve direct Task 200 cancellation semantics,
inject the actual cloud DSN and verified caller authority, and share the canonical
cancel/projection/lease transaction with the command wrapper. Generic direct
cancellation needs its own operation/terminal-event cleanup anchor; do not forge
an accepted command to satisfy the v42 receipt FK. Execution grant expiry must
not prevent an otherwise authorized caller from cancelling. Cloud snapshot-based
SUSPEND stays explicitly unsupported; local behavior remains unchanged.

Exact cleanup accepted 5/5: 92 actual PG/runtime tests (69.09 s), 5 real PG/Docker
tests (27.08 s), check (831), SPEC/QUALITY. A live Docker CLI rejects the previous
explicit --tlsverify=false plaintext invocation by trying to load certificates;
omitting TLS flags after clearing ambient overrides fixes that path while leaving
explicit TLS verification intact. Initial multi-Session tests incorrectly retried
epoch bootstrap; fixtures now reuse the same epoch without changing production.
Real tests prove absence/late create/label mismatch and sibling preservation,
assert no engine IO within cleanup DB transactions, and remove only their owned
synthetic containers. The final owned-container listing is empty. Direct control,
client outcomes and full process composition remain separate acceptance work.

Outcome audit: AG-UI must resolve the executable accepted Event within the actual
Task/Segment, not the currently active Segment or latest matching run name.
Multiple distinct executable anchors sharing a run ID are ambiguous; a control
command sharing that ID is not automatically a second executable anchor. Read
fixed outcomes from exact current-generation receipts/pending/outbox under the
same composed DB and trusted scope as authorization. Physical publish retries,
raw quarantine and cleanup reconciliation are not run execution failures.
RunError receipt notifications have no SSE id and do not advance canonical cursors.
Reconnect can repeat the settled notification. Validate exact input cursor event
identity/bounds, and prevent later unrelated run terminals from being projected
as this run's result. These are verified existing gaps, not yet fixed here.
The HTTP tenant guard also currently reads binding from settings.database_url;
direct-control scope plumbing must use the same actual composition as mutation.
