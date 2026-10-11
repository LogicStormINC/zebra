# Versioned execution authority and transaction boundaries (2026-10-11)

## Scope and authority

COV-EXEC-01, Luke Ding/Codex, branch `codex/cov-exec-01`, isolated worktree.
Claimed before coding. This is a component implementation, NOT completion of
the system performance plan. Production execution receipts remain OFF.

Migration90 maintains monotonic lineage revisions in the native transaction.
Handoff changes, projection identity/namespace changes and binding changes
advance both affected Session and root versions. Ordered unique old/new roots
avoid reversed row-lock ordering. Ordinary direct version edits are forbidden;
deletion/recreation does not reset the version. Truncate invalidates roots or
is refused by existing independent guards. Privileged DDL/trigger bypass is
outside this guarantee; restricted runtime DB roles remain a rollout condition.

A context brackets one independent native lineage/binding validation with
version reads. Afterwards every execution boundary freshly checks the version,
full latest binding JSON, active segment, status, STOP, epoch, lease and expiry.
There is no grant TTL, permanent permission cache or cross-wake context reuse.
The lease pin and post-lock authority read MUST remain separate statements:
combining them allowed a lease waiter to use a pre-revocation SQL snapshot.
Regression proves revocation committed while waiting is visible afterwards.

Normal continuation may share the current wake's already-qualified context
only when database/deployment, Session, full binding and fence match exactly.
Its read-only lineage check does not grant a lease or mutation right. Exceptional
recovery independently prepares its context, historical proof and native command
fence. Current Host/source checks remain live in both paths. Old schema has an
explicit legacy path; fleet digest includes execution-authority/90 and rejects
v89-only consumers. New fleet readiness requires exact migration checksums.

## Shared write and Artifact boundaries

All native coverage writes use one shared post-lock authority read instead of
separate clock/segment/binding/namespace/manifest/STOP reads. Existing Task/run/
stream locks, full native fence and immutable source validation remain intact.
Duplicate manifest source Events still refuse. This is not cached write authority.

Explicit `postgres_work_unit` shares authority and metadata reads in one short
transaction. Nested adapters cannot commit/reconfigure it; caught nested failures
poison the unit and roll everything back. Borrowing across thread/namespace is
forbidden, including passing an already-created borrow to another thread; escaped
borrows fail after exit. Tighter deadlines still apply.
Public Artifact Host checks and object I/O happen outside this new read unit.
This does NOT remove all external I/O from existing commit/publication locks.

Only incremental `final_certification` admission enables callback-local verified
bytes reuse. Full fresh lifecycle identity includes the actual object version;
metadata/retention/current authority remain checked. Cache is bounded to256
entries/32MiB; it is never shared across wakes, tenants or independent final
certification. Pure incremental proof scopes may reuse bytes under native row
pins. Unknown derivers cannot use the pure shortcut. Final proof phases always
read originals afresh, including arbitrary-deriver fallback. Physical corruption
of unchanged incremental objects can therefore be discovered at final
certification, as explicitly approved by the user; failed certification cannot
publish a formal answer. This does not relax metadata/permission revocation.

## Measurement contract and regression gates

Nine-record native Worker workload uses117 input bytes,18 accepted units and9
controlled model calls. Counter starts after fixture setup, before first handoff,
and ends at independent certified completion. Host/model/S3 transports are
controlled, not live Trench or real tenant load. Count covers `Connection.execute`,
not cursor calls, implicit transactions or trigger-internal SQL. Phase timings
are inclusive/nested and must not be summed. SQL fingerprints contain no params.

The service-loader counter alone omits direct context preparation. A new separate
full-validation counter includes dispatch and recovery preparation. Its normal
atomic gate allows three cold qualifications per wake (new-owner handoff,
service loading and dispatch preparation) plus independent recovery preparation;
repeated per-Artifact/per-boundary preparation fails. New-owner admission is NOT
the running wake's continuation and cannot reuse the old owner's context.
Strict commands with no consumer capability now refuse before expensive proof
preparation; this negative-only preflight never grants admission or replaces
the final locked capability, lease and authority checks. Non-strict routing
still permits an ordinary consumer without a strict capability.
Native boundary gate requires two statements per leased authority check and one
per read-only lineage check, with no history traversal. These are structural
regression gates, NOT an overall SQL budget or production latency SLO.

Initial serial v90 result, before the final same-wake preparation fix:

| Measure | v89 baseline | initial v90 |
| --- | ---: | ---: |
| Certified completion |56.0948s|28.1386s|
| Execute calls |49137|19643|
| Service binding reads |2413|6|
| Object GETs |518|282|
| Wakes |10|6|
| Qualified receipts |18|18|
| Exceptional full recovery |0|0|

Different wake counts prevent attributing all savings to one helper. The initial
v90 full-validation counter subsequently revealed27 validations, not6: recovery
preparation still repeated. The stricter gate failed and the same-wake sharing
fix followed. This initial result is superseded for the final source; final
serial evidence and exact test outcomes are recorded below after validation.

Final serial v90 source, same fixture and measurement boundary:

| Measure | v89 baseline | final v90 |
| --- | ---: | ---: |
| Certified completion |56.0948s|30.5219s|
| Execute calls |49137|20403|
| Service binding reads |2413|7|
| All native binding validations |not instrumented|20|
| Object GETs |518|287|
| Wakes |10|7|
| Qualified receipts |18|18|
| Exceptional full recovery |0|0|
| Full MODEL initialization replays |2|2|

All20 full validations are7 service,7 dispatch and6 cold new-owner preparation.
Initial full-counter run found27; same-wake reuse alone left22. The first proposed
two-stage budget incorrectly omitted legitimate cold new-owner qualification.
The corrected three-stage gate would still reject22; early missing-consumer
refusal removes unqualified proof preparation. First serial pass had17 total
validations (6service/6dispatch/5handoff),27.9448s19303execute/280GET/6wakes;
`/tmp/cov-execution-authority-final-serial-v2-nine.xml`,1 passed255 deselected,
33.32s pytest time. After strengthening actual borrowed-object thread checks,
final source remeasurement has20 validations and the values above; both pass.
This does not omit failed/negative attempts from the counter. Final source artifact:
`/tmp/cov-execution-authority-final-serial-v3-nine.xml`,1 passed255 deselected,
35.06s pytest time; reported completion30.5219s excludes fixture setup. The2s
work-slice deadline produces varying wakes, so neither run is a p95 claim.

Remaining amplified SQL is measured, not closed:2353 lease/epoch reads,1956
current-lineage reads,1004 locked metadata reads,815 plain metadata reads and
3257 connection resets. `_record` executes753 times, inclusive6.2234s; two final
original-proof phases take inclusive2.1288s. Counter excludes trigger-internal
SQL; phase timing is nested. The58.5% observed execute reduction and45.6%
completion reduction are a single controlled comparison with different wake
counts, NOT causal attribution to one helper, p95 or a multi-tenant capacity SLO.

Validation: final native authority/work-unit/capability/continuation/dispatch
matrix51 passed166.35s, zero skips. Initial expanded run49 passed2 failed:
missing-consumer preflight correctly changed rejection order. The two intended
legacy-method tests now supply qualified credentials and retain exact refusal/
no-objects/no-partial-state assertions; production guards were not relaxed.
Latest native work-unit matrix3 passed2.59s includes cross-thread borrowed-object
use/entry refusal. Pure bounded/locked readers55 passed1.20s. Earlier
native bind-guard/write/publication/MODEL/final-proof matrix53 passed, including
post-append rollback and unrelated-object corruption refusal. Bounded read,
locked proof and capability pure matrix56 passed1 deselected. Readiness/routing
matrix96 passed7 environment-gated skips. `make check`: size/Ruff GO, Mypy1103
sources GO, eval30/30 GO. These do not establish live transport or semantics.

## Remaining system-level work

- Reduce remaining per-Artifact authority/lifecycle fanout at explicit operation
  boundaries, not with permission TTLs or by disabling revocation checks.
- Move final original-object/Host verification out of Task/run/lifecycle lock
  windows with exact prepare/revalidate/publish boundaries. Current final
  corruption/race refusal must remain independently covered.
- Seal remaining MODEL volume/membership and unsupported-history work; ordinary
  version checks do not make the entire invocation constant work.
- Existing per-process execution slots, queue backlog bounds and scoped fair
  pickup are retained. They do not prove fleet-wide per-tenant concurrent limits,
  noisy-neighbor fairness or database capacity at high tenant count.
- Establish overall SQL/rows/transaction-lock budgets and native multi-tenant
  history-growth load/p95 acceptance. Tiny controlled data does not satisfy this.
- Coordinated migration/fleet rollout, real Trench progressive output and live
  canary/rollback remain unverified. No independent labelled business set was
  supplied; real semantic accuracy is unknown.

No primary checkout edits, business migration, build/restart, production activation,
commit, merge, push or deployment was performed for this slice.
