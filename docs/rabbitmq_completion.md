# RabbitMQ completion ledger

Updated: 2026-09-05. Owner: Luke Ding. Scope: approved isolated implementation.

## Counting rule

Completion is the number of fully implemented, tested and independently reviewed
acceptance groups divided by the fixed group count below. In-progress groups count
as zero. This measures acceptance coverage, not effort, production readiness or
elapsed time. Any added group must be recorded explicitly; never shrink the
denominator to make progress look larger. Report the current slice and stage
separately after each continuation. Deployment/activation is always separate.

## Stage 2 — Trench Turn (10 groups)

| # | Acceptance group | Status |
|---|---|---|
| 1 | All writer fences, lease loss, real PG races and clock skew | Complete |
| 2 | Separate broker schema and atomic admission/idempotency/rollback | Complete |
| 3 | Shared claim-by-ID/next and scoped atomic Inbox+lease handoff | Complete |
| 4 | Fenced relay, confirms/returns, stable physical retry identity | Complete |
| 5 | Bounded consumer, execution slots, post-handoff scheduling/ACK | Complete |
| 6 | Due/expired/published-unhandled recovery, retry generations | Complete |
| 7 | Durable sanitized rejection/quarantine and conflicting messages | Complete |
| 8 | Default-off composition, backfill, fallback and rollback | Complete |
| 9 | Integrated PG/Rabbit crash matrix, duplicates, isolation, recovery | Complete |
| 10 | Cross-service/browser regression and measured pickup/stream latency | Complete |

Current stage: **10/10 = 100%** at the isolated acceptance boundary.
Original runtime activation: **not enabled**.

## Completed slice — RABBIT-TURN-E2E-01

Isolated fixture, real-model HTTP/replay, multi-user scope, native browser file
download, proxy-visible streaming, refresh/terminal-state regression, independent
reviews and evidence: **7/7 = 100%**. Focused backend 103 passed, fixture 27 passed,
frontend 8 passed; final spec/quality each independently pass 64 SSE/guard cases.
Browser first visible text 4.795s, continuous increments until about 18.3s;
native downloaded bytes/hash verified. See [product evidence](rabbitmq_stage2_product_e2e.md).
Full frontend typecheck has three recorded inherited fixture errors; not a full
gate or production readiness claim.

## Completed slice — RABBIT-TURN-CONSUMER-01

Shared bounded slots, durable handoff before scheduling/ACK, atomic scheduling
failure recovery, duplicate/error/cancellation/shutdown tests and independent
reviews. **5/5 = 100%** accepted. Parent combined suite 65 passed; independent
spec and quality each reran 28 cases. Actual PG/Rabbit prefetch-2, capacity-1
test completes and persists two answers without concurrent over-claiming.

## Completed slice — RABBIT-TURN-QUARANTINE-01

Durable sanitized rejection, confirmed diagnostic Outbox, restricted topology,
malformed/conflict/duplicate/failure tests, independent reviews: **5/5 = 100%**.
Spec review 11 + 31 cases, quality 11 + 17 cases; actual PG/Rabbit suite 4 passed
including concurrent receipt/fence/migration and safe confirmed diagnostics.

## Completed slice — RABBIT-TURN-COMPOSE-01

Default-off validation/admission, managed relay/consumer/recovery lifecycle,
reconnect/log safety, dead-owner cancellation recovery, fallback/rollback tests
and independent reviews: **6/6 = 100%** accepted. Spec re-review independently
passes 56 tests; quality passes 56 + 13 tests. A real-client replay defect found
in initial review was fixed before acceptance. Parent combined real PG/Rabbit
tests pass 10 cases, including abrupt process exits and live rollback.

Group 9 is accepted at the local integration boundary: synthetic dead-owner lease
expiry/recovery is explicitly injected; signed cancellation uses HTTP MockTransport
in dedicated tests. No real-model/browser or production HA evidence is implied.
Group 10 was subsequently authorized and accepted in RABBIT-TURN-E2E-01 above.

Relay/recovery completed **6/6 = 100%** with 60 combined tests and one actual
PG/Rabbit lost-confirm/duplicate/dead-owner test. See
[delivery evidence](rabbitmq_stage2_delivery_evidence.md).

## Previous completed slice — RABBIT-TURN-HANDOFF-01 (8 groups)

1. Separate Outbox/Inbox tables, indexes, constraints and additive migration.
2. Explicit migration-mode atomic admission; unconfigured path unchanged.
3. Duplicate admission stable identity and complete transaction rollback.
4. Shared fenced claim-next/by-ID implementation.
5. Inbox+lease in one transaction; duplicate cannot start another execution.
6. Namespace/scope/digest/reference/state verification with no victim mutation.
7. Deterministic and real PG concurrent/rollback/migration regression tests.
8. Independent spec/quality reviews, recorded evidence and original-state check.

Current slice: **8/8 = 100%**, implemented, tested and independently reviewed.
Evidence: [atomic handoff acceptance](rabbitmq_stage2_handoff_evidence.md).
Final targeted suite 174 passed; new slice 37 cases (25 SQLite + 12 PostgreSQL).
This completion does not include deployment, broker publishing or consumption.

## Recorded continuations

| Date / slice | Slice completion | Stage-2 completion | Activation |
|---|---|---|---|
| 2026-09-04 starting point after fence acceptance | Fencing accepted | 1/10 = 10% | Off |
| 2026-09-04 RABBIT-TURN-HANDOFF-01 | 8/8 = 100% | 3/10 = 30% | Off |
| 2026-09-04 RABBIT-TURN-RELAY-01 | 6/6 = 100% | 5/10 = 50% | Off |
| 2026-09-04 RABBIT-TURN-CONSUMER-01 | 5/5 = 100% | 6/10 = 60% | Off |
| 2026-09-04 RABBIT-TURN-QUARANTINE-01 | 5/5 = 100% | 7/10 = 70% | Off |
| 2026-09-04 RABBIT-TURN-COMPOSE-01 + integrated crash acceptance | 6/6 = 100% | 9/10 = 90% | Original off |
| 2026-09-04 RABBIT-TURN-E2E-01 | 7/7 = 100% | 10/10 = 100% | Original off |

Overall six-stage plan is not reduced to an equal-weight percentage: later stages
have different scope. Stages 0/1 have local evidence; stage 2 has isolated acceptance;
stage 3 (Zebra commands) is **6/6 = 100%** and stage 4 (sources) is **7/7 =
100%** at the isolated acceptance boundary; stage 5 rollout hardening remains
pending.
See [stage 3 boundaries](rabbitmq_stage3_commands.md).
AGUI-OUTCOME-01 is accepted **5/5 = 100%**: actual PG 101 passed (86.02 s),
API/projection 52 passed (3.35 s), make check (838), independent SPEC/QUALITY.
See [Task/run outcome evidence](rabbitmq_stage3_agui_outcomes.md).
COMPOSE-01 is accepted: actual process fault matrix 15 passed, real broker
restart/redelivery, migrated fallback/restore, real-model stream and cancellation,
browser route/title/draft and actual reply/asset-page downloads verified.
Final local suite 3223 passed/692 skipped before the added harness; actual PG
279, live relay/quarantine 7 and make check 842 separately passed. See
[composition evidence](rabbitmq_stage3_composition.md). No skipped cases count as
exercised; no production activation or HA claim is made.
Stage 4's acceptance denominator is frozen before implementation and is now
**7/7 = 100%**. Group 2 is accepted after `RABBIT-SOURCE-SCHEDULE-01` reached
**6/6 = 100%**: local 116 passed/4 explicit-PG skipped, parent random-schema
PostgreSQL 4/4, targeted static checks and independent SPEC/QUALITY. This proves
source-wide schedule/fence and atomic command/source-Outbox admission only;
Redis IO, broker delivery, fetch execution, private credentials and activation
remain open. See [source scheduling boundaries](rabbitmq_stage4_sources.md). Existing canonical
Redis deduplication is reused, not represented as wholly absent. Source scheduling
does not imply a durable raw-content migration.

Group 3 is accepted after `RABBIT-SOURCE-DELIVERY-01`: Trench local delivery
15 passed/5 explicit-PG skipped, parent actual PostgreSQL delivery+schedule 9/9,
Zebra topology 9/9, isolated live Rabbit source route/ACL 1/1, and post-fix
SPEC/QUALITY pass. It proves the separate source relay/Inbox/receipt and bounded
consumer/recovery/quarantine boundary, including broker-off pre-start crash
recovery. It does not prove network fetch, old-entry cutover, content visibility,
private credentials or activation.

Group 4 is accepted after `RABBIT-SOURCE-CUTOVER-01`: focused source 75 passed/
12 explicit-PG skipped, parent cutover+delivery+schedule 21/21 including actual
PostgreSQL 9, static checks and post-fix SPEC/QUALITY. It proves all legacy
business fetch entry points share the default-off authority without dual
scheduling and that network IO uses a locked, minimal non-secret snapshot.
Durable result semantics, real content visibility and activation remain open.

Group 5 is accepted after `RABBIT-SOURCE-RESULT-01`: combined result, delivery,
schedule, cutover and adapter acceptance 63/63, including actual generated-schema
PostgreSQL retry due-time, conservative downgrade and a controlled
finalize-versus-fallback race. Six safe outcome classes, exact fenced projection,
bounded next-generation retry, superseded old wakeups and migrated log redaction
pass post-fix SPEC/QUALITY. It does not prove fetched content visibility,
credentialed sources, process composition or production activation.

Group 6 is accepted after `RABBIT-SOURCE-E2E-01`: opt-in real pipeline 2/2 and
combined source acceptance 106/106 on actual PostgreSQL, Redis and RabbitMQ where
applicable. One fixture HTTP feed reaches Redis raw, normalize, archive,
authenticated timeline and the signed Host history Tool. Duplicate delivery is
consumed with two ACKs, zero requeues and one canonical raw item; deterministic
Redis rejection fault injection does not advance source success or the normalize
cursor. Two product users remain source/content isolated. Post-fix SPEC/QUALITY
pass. This does not prove credentialed-X access, real Redis outage, live process
composition, business migration or production activation.

Group 7 is accepted after `RABBIT-SOURCE-COMPOSE-01` proved a default-off,
minimal-environment source process with one shared fail-closed cutover selector,
bounded shutdown, broker execution, database fallback, broker restore and
default-off rollback in separate real Python processes. The fallback generation
is atomically marked `superseded`, so broker restoration cannot execute the same
logical work twice. Actual subprocess E2E is 2/2; cleanup leaves Redis DB 14
empty and removes the disposable broker; independent SPEC/QUALITY pass. This
does not prove credentialed-X access, live business migration or production
activation.

Group 1 is accepted after `RABBIT-SOURCE-CREDENTIAL-REF-01` validated existing
credential identity, enabled state and source-platform match during apply and
every eligibility read while retaining principal subscription association.
Missing, inactive, mismatched and drifted references fail closed; the metadata
query never loads credential payloads, and valid references remain explicitly
non-executable. Final source regression is 100 passed/21 explicit-integration
skipped; actual generated-schema PostgreSQL is 5/5 including a controlled lock
race; independent SPEC/QUALITY pass. Stage 4 is complete at the isolated
boundary, not credentialed-X or production activation.

RABBIT-ZEBRA-RECOVERY-01: **5/5 = 100%** accepted. Combined actual PG/Rabbit
129 passed; final 44 recovery cases passed in 33.70 s after poison isolation and
both fallback/recovery race orders. Full make check (806), SPEC/QUALITY pass.
This accepts group 2, not arbitrary in-flight model replay or runtime activation.

RABBIT-ZEBRA-MESSAGE-01: **5/5 = 100%** accepted. 12 actual PG cases in 24.15 s,
31 local cases, expanded 145 cases in 108.00 s, make check (808), SPEC/QUALITY pass.
Canonical input, projections,
lease and Inbox/receipt commit together; duplicate/recovery reuses input identity.
Group 4 remains open for control and historical migration reconciliation.

RABBIT-ZEBRA-CONTROL-01 storage slice: **5/5 = 100%** accepted. Final 18 actual
PG cases passed in 21.21 s; combined 121 cases in 133.03 s, make check (810),
SPEC/QUALITY pass. Atomic canonical
cancel/fence revocation is proven; network cleanup, independent consumer capacity
and client-visible outcome wiring are not yet composed.

RABBIT-ZEBRA-CUTOVER-01: **5/5 = 100%** accepted. Final combined actual-PG
81 cases passed in 97.03 s after the stream-head guard fix; make check (812),
SPEC/QUALITY pass. Explicit historical retirement lets real Task-message then RUN
continue the same Session. Group 4 awaits the identified shared fenced Task attach
lock-order correction; that prerequisite was subsequently accepted below.

RABBIT-ZEBRA-TASK-LOCK-01: **5/5 = 100%** accepted. Actual PG 7 cases in 7.70 s,
shared Task regression 24 cases in 12.55 s, make check (812), SPEC/QUALITY.
Controlled removal of the new lock reproduces the incorrect lock wait. Group 4
is now accepted; stage 3 **4/6 = 66.7%**. Consumer/composition remain pending.

RABBIT-ZEBRA-CONSUMER-01: **5/5 = 100%** accepted. Final 40 real-PG/runtime/
migration cases in 15.23 s after SPEC fixes, initial combined 72 in 52.39 s;
make check (815), SPEC/QUALITY. Bounded actual Future lifetime and independent
control pickup proven. Durable reconciliation ACKs without execution; transient
requeue is delayed. Group 5 accepted; stage 3 **5/6 = 83.3%**. Quarantine,
safe runtime cleanup, client outcomes and process/fault acceptance remain pending.

RABBIT-ZEBRA-QUARANTINE-01: **5/5 = 100%** accepted. Combined 60 actual PG/
Rabbit/runtime/migration/pickup/consumer cases in 29.02 s; make check (819),
SPEC/QUALITY. Only sanitized diagnostics persist, confirmation precedes ACK,
and poison fallback candidates cannot starve healthy pages. Actual Rabbit proof
is positive confirm plus PG settlement after injected confirmation loss; queue
readback was not attempted under the restricted consumer ACL. Stage 3 remains
**5/6 = 83.3%** until safe cleanup, client outcomes and composition are accepted.

RABBIT-ZEBRA-RUNTIME-INSTANCE-01: **5/5 = 100%** accepted. Final 20 actual PG
cases in 23.33 s, expanded 66 before the final row-lock expiry correction;
make check (827), SPEC/QUALITY. Exact instance identity, pinned engine and
late-create obligations are proven. Cleanup executor is now in progress;
stage 3 remains **5/6 = 83.3%**, original activation remains off.

RABBIT-ZEBRA-RUNTIME-CLEANUP-01: **5/5 = 100%** accepted. 92 actual PG/runtime
cases in 69.09 s, 5 actual PG/Docker cases in 27.08 s, make check (831), both
reviews pass. Exact cleanup, delayed create, absence proof, foreign-label and
same-Session sibling preservation verified with no engine IO in DB transactions.
Live CLI testing caught and corrected plaintext TLS argument behavior. No test
containers remain. Direct control compatibility is now in progress; stage 3
remains **5/6 = 83.3%**, not yet composed or activated.

RABBIT-ZEBRA-DIRECT-CONTROL-01: **5/5 = 100%** accepted. Final 91 actual PG
direct/API/ACP/migration and shared control/cleanup/lease cases in 90.63 s,
6 actual PG/Docker cases in 32.44 s, make check (834), SPEC/QUALITY. Public cloud
cancel commits exact revocation and cleanup without session-wide deletion or
pretending physical destruction is already complete. Stage 3 remains **5/6 =
83.3%**. Existing Task-target rollover/CAS, client outcomes and process acceptance
remain pending; original activation is off.
Full local suite at this slice's stable snapshot: **3,184 passed, 671 skipped**
in 752.64 s; no inference is made about skipped infrastructure cases or later
Task-target changes. Actual PG/Docker evidence is recorded separately above.

RABBIT-ZEBRA-TASK-CONTROL-TARGET-01: **5/5 = 100%** accepted (target CAS,
pinned replay, canonical Host identity, regression evidence, independent reviews).
Final 65 actual PG cases in 59.56 s; 18 shared PG handoff/migration/authority/
workspace cases in 6.74 s; make check (835), SPEC/QUALITY. Suspended-source
rollover cannot produce a successful cancellation of the obsolete target;
same-key retry stays pinned. Child identity is replayable without extending
expired authority. Stage 3 remains **5/6 = 83.3%**; AG-UI outcomes now in progress.

RABBIT-ZEBRA-RELAY-01: **5/5 = 100%** accepted. Actual PG/Rabbit combined suite
111 passed in 49.94 s, including confirmed-message retry with identical bytes
after confirmation loss and transaction-free network publication. Full make check
passes (799 typed files), independent SPEC/QUALITY each pass 21 cases. This accepts
group 3, not business exactly-once execution or original runtime activation.

RABBIT-ZEBRA-HANDOFF-01 storage slice: **5/5 = 100%** accepted after the
terminal-during-lease-wait review fix, 40 race/clock and 54 shared caller cases.
RABBIT-ZEBRA-RECEIPTS-01: **5/5 = 100%** accepted, 61 actual PG cases and
54 shared caller cases; exact start/handled association is not arbitrary output
completion. These are prerequisites inside group 4, which remains open until
worker execution, multi-command handling and recovery boundaries are integrated.

RABBIT-ZEBRA-ADMISSION-01: **5/5 = 100%** accepted. Actual PG/focused 36,
existing PG baseline 14, full make check and independent SPEC/QUALITY pass.
No broker activation, commit, merge or original runtime change is implied.

RABBIT-ZEBRA-DISCOVERY-01: **5/5 = 100%** accepted (cutover, atomic cursor,
bounded scoped discovery, race/rollback tests, independent reviews). Combined
focused/real-PG 60 and make check pass. Stage 3 remains **1/6**: recovery generations
and canonical command handling must still close group 2. A real-PG expired-heartbeat
defect was confirmed as a handoff prerequisite.

RABBIT-ZEBRA-LEASE-CLOCK-01: **5/5 = 100%** accepted. 81 real-PG/targeted cases,
make check and both independent reviews pass. Stage 3 remains **1/6** until the
remaining delivery and handoff groups are accepted; relay implementation proceeds.

RABBIT-ROLLOUT-CAPACITY-01: **Stage 5 group 1/8 = 12.5%** accepted. Trench
cross-conversation user admission is atomic. Zebra applies bounded scope and
Outbox admission with a reserved control slice across live, recovery, backfill
and old-writer paths. Forward pickup plus a frozen active-scope-head ring closes
both far-tail and dynamic-scope starvation. Actual PostgreSQL/API regression is
146/146; final exact old-writer negative migration proof is 2/2; independent
SPEC/QUALITY pass. No commit, merge, production activation or later Stage 5
group is implied.

RABBIT-ROLLOUT-SHADOW-01: **Stage 5 group 2/8 = 25%** accepted. Unlisted scopes
remain on database fallback; publisher, consumer and fallback use one audited
scope authority, with transaction-locked mode rechecks for both execution and
control. Shadow delivery is physically separated and bounded, uses an independent
percent-decoded Rabbit principal/ACL, never blocks formal admission, and reports
success only for exact formal/shadow message, scope and digest matches. Legacy
credentials upgrade atomically without rotation. Zebra focused/actual-PG passed
63/30, Trench focused/actual-PG passed 32/1, isolated broker ACL acceptance and
both full `make check` gates passed, followed by independent SPEC/QUALITY pass.
No production activation, commit, merge or push is implied.
