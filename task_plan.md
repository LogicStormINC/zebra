# Task Plan

## CLOUD-MEMORY-PG-01 - PostgreSQL Governed Memory Authority

1. `completed` - Re-audit v1-v9 migrations and aggregate transaction patterns,
   then freeze the smallest v10 schema and lock order against the reviewed contract.
2. `completed` - Implement namespace-bound PostgreSQL reads, authority/tombstone scan,
   Worker candidate aggregate and administrative review aggregate with receipts.
3. `completed` - Add repeatable SQLite import/rebuild tooling while keeping runtime
   composition gated on a coherent cloud authority bundle.
4. `completed` - Prove migration, namespace/query parity, CAS/concurrency, rollback,
   response-loss replay and snapshot scan against real PostgreSQL 17.5; review and
   integrate into `zebra-cloud-trench`.

### Decisions

- PostgreSQL v10 is the sole cloud governed-Memory fact contract; Mem0 remains a
  derived index and stays outside this task.
- Reuse the existing PostgreSQL transaction, migration and aggregate authority
  patterns; do not add a generic Unit of Work or change local SQLite behavior.
- Runtime cutover remains gated until all authoritative stores are available in one
  coherent cloud composition.
- Do not land an optional Worker Memory seam before terminal finalization, authority
  active-set validation and the Event/Projection/Memory bundle share one recoverable
  cloud boundary; the reviewed prototype was removed rather than preserve split state.

## CLOUD-MEMORY-CON-01 - Governed Memory Mutation Contract

1. `completed` - Freeze the smallest validated authority, revision, operation,
   tombstone and aggregate request/result types.
2. `completed` - Extract deterministic candidate/promotion/review planning from current
   services while retaining behavior-compatible local wrappers.
3. `completed` - Prove invalid authority, stale shapes, no-text tombstones, pure plans,
   canonical digests and local Memory regressions.
4. `completed` - Run Core static/test/eval gates, review the slice and integrate it into
   `zebra-cloud-trench` without SQL or runtime wiring.

### Decisions

- Add a focused cloud authority Port rather than weakening the local
  `MemoryStorePort.upsert()` signature with optional revisions and authority.
- Pure planners generate mutations and Events but perform no I/O; existing services
  remain compatibility wrappers for the SQLite profile.
- Canonical replay results contain identifiers/revisions/Event references only, never
  Memory text or provider data.

## CLOUD-MEMORY-PG-PLAN-01 - PostgreSQL Governed Memory Authority Plan

1. `completed` - Inventory the current SQLite Memory fact source, all mutation/read
   callers, Event coupling, scope semantics and Mem0 delivery boundary.
2. `completed` - Freeze PostgreSQL identity, revision/CAS, atomic review, namespace,
   query/search, migration, rebuild and recovery contracts.
3. `completed` - Split Core contract, PostgreSQL adapter and Mem0 delivery successors
   with non-overlapping owned paths and dependency gates.
4. `completed` - Review the plan against current code and architecture, record evidence
   and close the docs-only card as Done.

### Decisions

- Zebra governed `MemoryRecord` remains the fact source; Mem0 is a rebuildable derived
  semantic index and never receives authority over lifecycle or content.
- A PostgreSQL delivery ledger cannot safely depend on the current SQLite-only
  `MemoryStorePort`, so governed-memory migration precedes `MEM-GW-DEL-01`.
- Do not preserve blind last-writer-wins `upsert` as the cloud mutation contract;
  review, supersession, Event and Session Projection require an explicit aggregate.

### Closeout

- Review accepted the integrated docs-only contract `2c43af0f`; PostgreSQL
  governed Memory is the cloud fact source and Mem0 remains a rebuildable
  derived index.
- The current contract is `366` lines and its reference, diff and Eval `10/10`
  evidence is accepted. No implementation or runtime selection was added.
- `CLOUD-MEMORY-PG-PLAN-01` is `Done`; the Core and PostgreSQL authority cards
  remain the next implementation gates.

## CLOUD-ART-OBJ-CON-01 - Artifact Object And Metadata Authority Contract

1. `completed` - Audit the existing local Artifact authority, MinIO baseline and
   cloud aggregate dependency gaps.
2. `completed` - Write ADR-017 with the provider-neutral identity, lifecycle,
   compensation, fencing, reconciliation and non-goal decisions.
3. `completed` - Link the architecture, aggregate inventory and Trench task plan to
   the ADR without duplicating its protocol.
4. `completed` - Validate links and terminology, record evidence and prepare the
   Review handoff.
5. `completed` - Formally audit the integrated ADR and dependency baseline, then
   close the card as Done without selecting an Artifact adapter.

### Decisions

- PostgreSQL metadata and object bytes jointly form Artifact payload authority;
  neither Event-derived projections nor temporary signed URLs are facts.
- `artifact://` is stable identity; provider locator and credentials stay internal.
- Freeze the failure protocol before choosing an SDK, adapter or migration.

### Closeout

- Review covered integrated ADR-017 commit `486fd884`; aggregate fencing and the
  Compose/MinIO dependency baseline are `Done`.
- ADR-017 is linked from the production architecture, aggregate inventory and
  Trench breakdown; its terminology/link/size/diff evidence is accepted. No code,
  migration, Compose service, API route or runtime selection changed.
- Artifact lifecycle, object adapter, payload authority, Effect linkage and read
  composition remain separately gated.

## CLOUD-ART-PAYLOAD-PG-01 - Shared Artifact Payload Authority

1. `completed` - Audit the current local payload Port, Worker/Event write paths,
   PostgreSQL migration serialization and MinIO dependency baseline.
2. `completed` - After Handoff v8 is integrated, claim the card and add migration v9
   plus a focused cloud lifecycle Port; do not add optional fence parameters to the
   local compatibility Port.
3. `completed` - Implement fenced reserve, conditional object put/head, Event URI
   binding, finalize, compensation, prune and management reconcile as explicit steps.
4. `completed` - Prove the PostgreSQL/MinIO fault matrix, concurrent idempotency,
   namespace isolation and cross-process reads with an isolated host runner.
5. `completed` - Formally audit the integrated v9 chain and dependency evidence,
   then close the card as Done without selecting Runtime or adding v10.

### Decisions

- v8 remains exclusively owned by Handoff; Artifact implementation starts at v9.
- The existing `ArtifactPayloadStorePort` and SQLite file store remain local-only.
- Tool output must obtain its stable URI before Event append; the post-Event
  `ToolRunIndexer` fallback cannot be the cloud payload authority path.

- Use a synchronous low-level botocore client. Do not add boto3, s3transfer, MinIO
  SDK, an async AWS SDK or hand-written SigV4.
- MinIO bucket versioning is part of the v9 test/dependency contract so finalize,
  compensation and prune retain exact object-version evidence.
- v9 owns one authoritative `artifact_payload_metadata` table, not a second Artifact
  projection. Its composite identity is `(deployment_namespace, artifact_id)`; it
  also uniquely binds `(namespace, session, idempotency_key)` and the intended Event
  sequence. `(namespace, artifact_id)` is the provider-neutral logical object locator;
  the S3 adapter alone derives its private key, so PostgreSQL does not duplicate that
  provider-specific encoding.
- Required lifecycle is `staged -> finalized -> pruning -> pruned`, with
  `staged -> compensated`; `missing` remains a read inspection outcome. A monotonic
  lifecycle revision and row lock serialize every transition.
- Reserve stores request hash, expected Event sequence, digest/size/type/retention,
  logical object identity and the complete reservation fence. Verified upload records the
  exact object version while still staged. Finalize binds the canonical Event ID and
  sequence after checking its Session and `artifact_uri`.
- Event outcome uncertainty never triggers deletion. Worker compensation requires a
  proven absent Event and exact-version delete; stale-fence rows move to bounded,
  explicitly authorized management reconcile.
- The Worker coordinator never deletes an object inline after object I/O begins: the
  current lifecycle has no fenced pre-delete claim, so checking authority after S3
  deletion is unsafe. Known absence can use the Worker compensation primitive from a
  caller that already owns safe cleanup evidence; orchestration failures remain staged
  for audited management reconcile.
- Keep the cross-system orchestration in one focused Tool-output Artifact commit
  service. `ToolRunIndexer` remains a pure Event projection and object I/O never runs
  inside a PostgreSQL transaction.
- Effect linkage, API read composition, runtime profile selection and Desktop stay
  in their dedicated successor cards.

### Closeout

- Review covered v9 commits `f0e714c8`, `3443da58`, `9e26dc26`, `8fcc8995` and
  `b87760b6`; lifecycle, object, Artifact authority and Handoff v8 dependencies
  are `Done`.
- Recorded PostgreSQL `19/19`, Core `17/17`, PostgreSQL+MinIO `30/30`, Worker/
  Runtime `260/260` and Storage `131/131` evidence is accepted. No Compose run or
  production edit was made by this review slice.
- Effect linkage, read composition, delivery APIs and Runtime/provider selection
  remain separately gated.

## CLOUD-EFFECT-PAYLOAD-ATOMIC-01 - Effect Payload And Intent Linkage

1. `completed` - Audit the current EffectGuard, fenced outbox and Artifact v9
   transaction seams; freeze lock order, idempotency and failure outcomes.
2. `completed` - Stage and verify the immutable Effect request object under the current
   Worker fence without extending the local SQLite payload Port.
3. `completed` - Commit intent Event, Effect outbox row and Artifact finalization in one
   PostgreSQL transaction, then remove the guarded cloud composition rejection.
4. `completed` - Prove cross-Worker read, stale-fence rollback, schedule failure,
   response-loss recovery and provider/database fault windows with PostgreSQL+MinIO.
5. `completed` - Formally audit the integrated Effect/Artifact transaction and
   dependencies, then close the card as Done without adding v10.

### Decisions

- PostgreSQL remains the only transactional authority; S3-compatible object I/O is
  verified before the database aggregate commit and is never held inside its lock.
- Unknown outcomes preserve staged evidence for reconciliation and never authorize
  automatic Effect replay or inline object deletion.
- No v10 migration is required: v9 metadata, the existing Effect outbox and their
  deferred Event bindings express the aggregate without a duplicate Artifact FK.

### Closeout

- Review covered integrated binding implementation `4480ca66`; Artifact v9 and
  Effect Outbox dependencies are `Done`.
- Recorded PostgreSQL+MinIO `53/53`, Tools/Worker/Runtime `418/418`, Storage
  `131/131` and current-HEAD focused `13/13` evidence is accepted. No Compose run
  or production edit was made.
- Delivery APIs, read composition, provider selection and Runtime startup remain
  separately gated.

## CLOUD-ART-READ-COMP-01 - PostgreSQL Artifact Read Composition

1. `completed` - Audit the existing API/SQLite read contract and the PostgreSQL
   Model/Tool plus payload lifecycle query seams.
2. `completed` - Implement namespace-scoped PostgreSQL Model/Tool reads and reuse the
   existing Artifact projection sanitizer and ordering logic.
3. `completed` - Compose cloud payload lifecycle/object reads into the existing API
   contract without adding an Artifact authority table or migration.
4. `completed` - Prove SQLite/PostgreSQL parity, namespace isolation, redaction,
   lifecycle states and Event-rebuild recovery with isolated PostgreSQL/MinIO tests.
5. `completed` - Formally audit the integrated read composition and dependency
   evidence, then close the card as Done without adding a mutation path.

### Decisions

- Model/Tool projections remain rebuildable indexes derived from canonical Events;
  payload metadata plus immutable object evidence remain the only payload authority.
- Reuse `SessionArtifactReadPort` and the existing API serialization/access policy;
  do not fork cloud routes or duplicate redaction rules.
- This task does not choose the complete cloud control-plane runtime backend.
- Cloud content additionally binds the v9 Event ID/sequence and exact object version;
  a canonical URI alone is not sufficient authority.
- Legacy one-step prune is disabled whenever a non-local read capability is injected.

### Closeout

- Review covered integrated read composition implementation `934de7b0`; Model/Tool
  v6 and Artifact v9 dependencies are `Done`.
- Recorded PostgreSQL+MinIO `39/39`, full `1943` with `145` skips, static/Eval
  evidence and current focused read `17/17` plus one skip are accepted. No Compose
  run or production edit was made.
- Delivery APIs, Session History, full Control Plane and Runtime/provider selection
  remain separately gated.

## CLOUD-ART-LIFECYCLE-CON-01 - Cloud Artifact Lifecycle Contract

1. `completed` - Freeze the smallest cloud-only domain and Port surface while
   preserving the local Artifact Port unchanged.
2. `completed` - Implement frozen request/result/receipt types, typed failures and
   Worker/management authority-separated Protocol methods.
3. `completed` - Prove validation, immutability, public exports, Protocol shape and
   local compatibility with focused Core tests.
4. `completed` - Run Core Ruff/Mypy/tests/file-size gates, record evidence and integrate
   the focused branch into `zebra-cloud-trench` without touching v8.
5. `completed` - Formally audit the integrated Core contract and dependencies, then
   close the card as Done without adding an adapter or migration.

### Decisions

- This contract-only card is independent of migration v8 and unlocks v9 without
  weakening Handoff's migration ownership.
- Add focused cloud-only modules instead of optional cloud fields on the local Port.
- Keep orchestration, storage error mapping and lifecycle transition enforcement in
  later adapters/services; Core only makes invalid requests unrepresentable.

### Closeout

- Review covered integrated Core implementation `0444c5d9`; aggregate fencing and
  Artifact authority dependencies are `Done`.
- The cloud-only lifecycle Port/domain and authority-separated Protocol methods
  remain provider-neutral. Recorded `45/45`, `290/290` and static/size evidence,
  plus current-HEAD focused `21/21`, are accepted; no Compose or production edit
  was made.
- Object storage, PostgreSQL metadata, Worker orchestration, Effect linkage, read
  composition and Runtime remain separately gated.

## CLOUD-ART-OBJECT-S3-01 - S3-Compatible Immutable Artifact Object Adapter

1. `completed` - Claim the object-only adapter card and freeze botocore/MinIO
   configuration, error mapping and internal key boundary.
2. `completed` - Implement conditional put, verified head/read and exact-version delete
   against the reviewed Core object Port.
3. `completed` - Enable bucket versioning and prove canonical retry, conflict, mismatch,
   namespace isolation and cross-client behavior on isolated MinIO.
4. `completed` - Run storage/compatibility/static gates, record evidence and integrate
   without touching PostgreSQL migrations or lifecycle orchestration.
5. `completed` - Formally audit the integrated adapter and dependency order, then
   close the card as Done without adding lifecycle or Worker orchestration.

### Decisions

- This object-only card is independent of active migration v8.
- Add direct botocore only; do not add boto3/s3transfer, MinIO SDK, async AWS SDK or
  hand-written SigV4.
- Internal keys are derived only from canonical namespace and Artifact ID; file names,
  provider locators, credentials and ETags never enter Core identity.

### Closeout

- Review covered integrated object adapter `ce22ae8d`; Artifact lifecycle,
  authority and Compose/MinIO dependencies are `Done`.
- Recorded MinIO `15/15`, storage `130` with `87` skips, strict Mypy/Ruff/diff
  evidence and current-HEAD adapter `14/14` plus one MinIO-gated skip are accepted.
  No Compose run or production edit was made.
- PostgreSQL metadata, lifecycle orchestration, Effect linkage, read composition,
  SQLite and Runtime remain out of scope.

## CLOUD-AGG-HANDOFF-CON-01 - Fenced Handoff Dispatch Contract

1. `completed` - Trace actual Worker claim/ACK callers and reject unrelated Port cleanup.
2. `completed` - Add claim token and full LeaseFence receipt semantics to the
   portable dispatch Port, SQLite migration and Worker recovery path.
3. `completed` - Prove legacy-claim requeue, token rotation, stale fence/expiry ACK
   rejection and local/API compatibility.
4. `completed` - Run Core/Storage/Worker gates, record evidence and move to Review.
5. `completed` - Formally audit the integrated diff and dependency status, then
   close the card as Done without adding PostgreSQL or changing composition.

### Decisions

- Preserve unused legacy `SessionHandoffPort` batch wrappers for compatibility;
  only the independently injected dispatch Store becomes the strict Worker path.
- Use a standard-library random token and do not touch PostgreSQL migrations.

### Closeout

- Review covered `f7d73dd3` and `4492f475`; aggregate fencing, Lease fencing and
  the staged Handoff contracts are all `Done`. The historical task branch is not
  merged as a separate delta because the corrected implementation is already on
  the cloud mainline.
- The recorded `290` related tests, changed-scope Ruff, strict Mypy and diff
  checks are accepted; a current-HEAD focused regression run passed `22/22`.
  No Compose execution or production edit was made by this review slice.
- This closeout leaves PostgreSQL Handoff v8 as a separate Review gate and does
  not unlock Runtime, Worker startup, Provider HTTP or application Compose.

## CLOUD-AGG-HANDOFF-PG-01 - PostgreSQL Handoff And Dispatch Aggregate

1. `completed` - Rebase the frozen Handoff aggregate boundary on v1-v7 and split
   the oversized migration catalog without changing historical checksums.
2. `completed` - Add v8 PostgreSQL Handoff operation/envelope/dispatch schema
   and one connection-scoped atomic commit using existing Event, Lease, Workspace
   and Task primitives.
3. `completed` - Implement database-time fenced dispatch claim/reclaim/ACK and prove
   concurrency, stale authority, rollback, lost-response and recovery behavior.
4. `completed` - Run real PostgreSQL and microservice gates, record host evidence and
   move to Review without selecting the runtime backend.
5. `completed` - Formally audit the integrated v8 diff and dependencies, then close
   the card as Done without changing runtime or provider composition.

### Decisions

- PostgreSQL owns the cloud Handoff fact source; SQLite receives no further feature work.
- Reuse v5 Task rollover and existing Event/Workspace/Lease transaction primitives;
  do not duplicate their rules inside the Handoff adapter.
- v8 is serialized on this task; Artifact payload cannot edit migrations concurrently.
- Bind reserve and commit through one canonical request hash, keep child Workspace
  projection Event-rebuildable, and thread the acquired LeaseFence into Worker recovery.

### Closeout

- Review covered `a678938b`, `d23d824c` and `cfe40713`; aggregate fencing,
  Workspace, Task and portable Handoff dispatch dependencies are all `Done`.
- The recorded PostgreSQL v1-v8 `20/20` and Core/Storage/API/Worker `822/822`
  evidence is accepted, with scoped Ruff and diff checks; a current-HEAD
  Core/Worker focused regression run passed `17/17`. No new Compose execution or
  production edit was made by this review slice.
- Handoff v8 is now a closed aggregate gate. Artifact, Context administrative
  recovery, Control Plane and runtime/provider paths remain separately in Review
  or locked.

## CLOUD-AGG-CTX-PG-01 - Fenced Context Lifecycle Aggregate

1. `completed` - Trace capsule, active-pointer and Event-derived projection
   boundaries; freeze the Context-specific authority transaction.
2. `completed` - Add PostgreSQL v7 lifecycle state, pointer CAS and full-fence
   Worker/API seams while preserving v1-v6 migration checksums.
3. `completed` - Prove canonical retries, stale fence, administrative CAS,
   pointer/content constraints and rollback with real PostgreSQL tests.
4. `completed` - Formally audit the integrated diff and dependencies, then close
   the card as Done without changing composition or runtime selection.

### Decisions

- Capsule content, Context Events, active pointer and required Session/Workspace
  projections commit within the Context-specific fenced transaction.
- Do not write Task/Segment indexes or introduce a generic transaction abstraction;
  manual compact remains outside this card.
- Migration v7 is additive and preserves v1-v6 names/checksums; runtime selection
  remains owned by the Control Plane card.

### Closeout

- Review covered `0c170c5d`, `2e2a5276` and `6d541f79`; all direct dependencies
  Fence Contract, Workspace, Task and Model/Tool v6 are `Done`.
- Recorded evidence is sufficient: isolated PostgreSQL `14/14`, focused
  SQLite/Worker `11/11`, changed-scope Ruff, strict Mypy and diff checks. No new
  Compose execution or production edit was made by this review slice.
- Handoff, Artifact, Control Plane and all runtime/provider paths remain locked or
  separately in Review.

## CLOUD-AGG-CTX-ADMIN-PG-01 - PostgreSQL Administrative Context Recovery

1. `completed` - Trace manual compact and historical recovery API paths and retain
   manual compact as a local-only capability for now.
2. `completed` - Add an explicitly injected PostgreSQL recovery path using the
   existing administrative Context CAS and canonical transaction result.
3. `completed` - Prove stale revision, missing/stale pointer, namespace isolation,
   projection atomicity and HTTP compatibility on real PostgreSQL.
4. `completed` - Run API/storage gates, record evidence and move to Review.
5. `completed` - Reconcile the dedicated recovery adapter/test paths during formal
   review and close the card as Done without adding a selector or migration.

### Decisions

- YAGNI: do not invent a PostgreSQL administrative new-capsule transaction.
- Do not perform a second Session/Workspace save after the aggregate commit.
- Administrative recovery locks the Session stream and requires the current database
  Session/Workspace projections to exactly match the caller's CAS facts before append.
- Runtime profile selection remains owned by `CLOUD-CONTROL-PLANE-PG-01`.

### Closeout

- Review covered integrated implementation `ac9801c2` and activation record
  `d11cf9e9`; Context lifecycle and Workspace dependencies are both `Done`. The
  governance card now explicitly names the PostgreSQL recovery adapter and
  focused matrix test used by the implementation.
- The recorded PostgreSQL `19/19`, API/Storage `323/323` with `14` skips, Ruff,
  strict Mypy and diff checks are accepted. No Compose execution or production
  edit was made by this review slice.
- This closeout leaves manual compact, backend selection, Runtime, Provider HTTP,
  Desktop and application Compose selection out of scope and separately locked or
  in Review.

## CLOUD-AGG-TASK-PG-01 - PostgreSQL Task And Segment Index

1. `completed` - Trace the SQLite Task/Segment projection, explicit rebuild and
   Handoff connection-scoped rollover contracts; freeze the PostgreSQL boundary.
2. `completed` - Add the next additive migration and namespace-scoped PostgreSQL
   adapter without allowing reads to trigger writes.
3. `completed` - Prove concurrent rollover CAS, unique Task event order, idempotent
   rebuild, namespace isolation and transaction rollback on real PostgreSQL.
4. `completed` - Run microservice gates, record host evidence and move the card to
   Review.
5. `completed` - Formally audit the integrated diff and dependency status, then close
   the card as Done without changing composition or runtime selection.

### Decisions

- AgentTask remains an Event/lineage-derived index, not a new command authority.
- Preserve a connection-scoped rollover primitive so the later Handoff aggregate
  can update Task state inside its own transaction.
- Explicit rebuild acquires the same Task advisory lock as rollover, strictly
  validates paired Handoff Events and deterministically replaces derived rows.
- Migration edits are serialized on this branch; other sessions may audit later
  cards but must not modify the migration hotspot concurrently.

### Closeout

- Review of `2675c56a` against the declared Owned paths found no boundary
  violation; its direct authority dependency `CLOUD-AGG-FENCE-CON-01` is `Done`.
- The recorded PostgreSQL `32/32`, regression, static and Eval evidence is
  sufficient for closure. No new Compose execution or production edit was made
  by the review slice.
- `CLOUD-MODEL-TOOL-PG-01` remains the next dependency-ordered Review target;
  Control Plane and all Runtime/Worker/Provider composition remain locked.

## CLOUD-MODEL-TOOL-PG-01 - PostgreSQL Model And Tool Projections

1. `completed` - Trace Model/Tool Event-derived projection and Worker index/replay
   boundaries; keep Artifact payloads out of management replay.
2. `completed` - Add namespace-scoped PostgreSQL v6 projections with full-fence
   validation and deterministic same-event replay.
3. `completed` - Prove stale writes, content conflicts, partial projection recovery
   and migration behavior with focused Worker and PostgreSQL tests.
4. `completed` - Formally audit the integrated diff and dependencies, then close
   the card as Done without changing composition or runtime selection.

### Decisions

- Model Call and Tool Run remain Event-derived indexes, never a second authority.
- Management replay reads committed Events and does not write Artifact payloads;
  Worker indexing validates the complete current Lease fence.
- The v6 migration and projection adapter remain separate from Context, Handoff,
  Control Plane and runtime backend selection.

### Closeout

- Review covered `4acd8ae8`, `5e44c0b7` and `d6e3f5c2`; both direct dependencies
  `CLOUD-AGG-FENCE-CON-01` and `CLOUD-AGG-WORKSPACE-PG-01` are `Done`.
- Recorded evidence is sufficient: focused Worker `7/7` and isolated PostgreSQL
  v6 migration/projection `7/7`; no new Compose execution or production edit was
  made by this review slice.
- `CLOUD-AGG-CTX-PG-01` remains a separate Review card, and all runtime,
  application-profile and provider paths remain locked.

## CLOUD-AGG-WORKSPACE-PG-01 - Fenced Workspace Projection

1. `completed` - Trace Workspace projection shape, replay semantics and existing
   PostgreSQL Event/Session transaction helpers; freeze the smallest Adapter API.
2. `completed` - Add the additive Workspace migration and PostgreSQL adapter with
   transaction-local `WorkerMutationAuthority` validation and monotonic revision CAS.
3. `completed` - Add deterministic contract/fault tests and the host Docker Compose
   real-PostgreSQL runner without selecting the adapter at runtime.
4. `completed` - Run static/Core/storage gates, record final host evidence and move the
   card to Review.
5. `completed` - Formally audit the integrated diff and dependency status, then close
   the card as Done without changing composition or runtime selection.

### Decisions

- Workspace remains an Event-derived projection. The adapter must support safe
  replay and reject stale overwrites; it does not create a new fact source.
- Reuse existing PostgreSQL database, epoch, Lease and projection row helpers. Do
  not add a generic Unit of Work, broker or backend selector.
- The fenced transaction owns Event + Session + Workspace. Model Call and Tool Run
  indexes remain replayable follow-up projections for their dedicated card.
- Desktop and local-agent composition remain out of scope.

### Closeout

- Review of `8b924d74` against the declared Owned paths found no boundary
  violation; the sole dependency `CLOUD-AGG-FENCE-CON-01` is `Done`.
- The recorded PostgreSQL `80/80`, regression, static and Eval evidence is
  sufficient for closure. No new Compose execution or production edit was made
  by the review slice.
- `CLOUD-AGG-TASK-PG-01` remains the next dependency-ordered Review target;
  Control Plane and all Runtime/Worker/Provider composition remain locked.

## CLOUD-AGG-FENCE-CON-01 - Worker Mutation Fencing Contract

1. `completed` - Reuse the existing LeaseFence/domain vocabulary and trace the
   smallest shared mutation context required by Worker-owned aggregate writes.
2. `completed` - Add one infrastructure-neutral authority contract plus focused
   type/validation tests; do not modify existing Store Ports prematurely.
3. `completed` - Prove current/stale authority representation, API administrative
   CAS separation, Ruff, strict Mypy and focused Core tests.
4. `completed` - Record the accepted contract, move the card to Review and unlock
   only the first dependency-safe PostgreSQL adapter card.

### Decisions

- Prefer one shared value object over adding the same namespace/fence/stream
  revision parameters independently to every Store Port. Aggregate-specific CAS
  values remain in their own requests.
- Keep Worker authority and administrative CAS as separate strict types; never
  represent the difference with `LeaseFence | None`.
- Do not introduce a generic Unit of Work or transaction callback in Core. Each
  coarse-grained aggregate Adapter owns its database transaction.
- This card defines authority input only. PostgreSQL transactions, migrations,
  composition and runtime backend selection stay in their implementation cards.

## CLOUD-AGG-FENCE-PLAN-01 - Worker Aggregate Fencing Path Inventory

1. `completed` - Trace every authoritative Worker-owned aggregate from Port to
   adapter and mutation caller, including its current transaction boundary.
2. `completed` - Classify PostgreSQL adapter and Lease-fence coverage gaps without
   changing production code.
3. `completed` - Write the reviewable path inventory and split implementation into
   dependency-ordered, non-overlapping task cards with real PostgreSQL tests.
4. `completed` - Validate documentation consistency, move the planning card to
   Review and leave the parent gate Locked until its prerequisites are merged.

### Decisions

- This task is documentation-only. It cannot select a runtime backend, implement
  an adapter, claim multi-Worker safety or change Desktop/local-agent code.
- The smallest coherent implementation card owns one aggregate family and its
  PostgreSQL tests; shared composition is deferred to a final integration card.

## CLOUD-LEASE-01 - Lease And Event/Effect Delivery Parent Gate

1. `completed` - Fast-forward the reviewed cloud and microservice repair stack onto
   the isolated local `zebra-cloud-trench` business branch.
2. `completed` - Reconcile the separate Lease `34/34`, Outbox `49/49` and combined
   Consumer/PostgreSQL `58/58` evidence against the frozen parent contract.
3. `completed` - Write the combined acceptance record with guarantees, exclusions
   and the explicit no-exactly-once/no-production-cutover boundary.
4. `completed` - Run document consistency checks, close the parent gate as Done and
   leave full aggregate fencing locked.

### Decisions

- The existing consumer host script is already the combined matrix; no duplicate
  Compose runner or broker is needed.
- Desktop is outside this microservice gate. Core/API/Worker/storage/PostgreSQL,
  dependency Compose and release Eval remain in scope.

### Closeout

- Review accepted `docs/CLOUD_Lease_Effect_联合验收记录_v1.0.md` and the recorded
  Lease `34/34`, Outbox `49/49`, consumer `58/58`, backend `1851 passed, 60
  skipped`, file-size `901` and Eval `10/10` evidence.
- The gate is limited to one-namespace fenced Lease plus Event/Effect delivery;
  it does not claim exactly-once external execution, complete aggregate fencing,
  runtime selection or production readiness.
- `CLOUD-LEASE-01` is `Done`; `CLOUD-AGG-FENCE-01` remains `Locked`.

## BASE-EVT-SIZE-01 - Context Event Contract Extraction

1. `completed` - Confirm `ContextCapsuleCreatedPayload` is the smallest cohesive
   move and the existing context-events module is its natural owner.
2. `completed` - Move the payload model and preserve registry/public imports.
3. `completed` - Run context contract tests, microservice file-size gate, Ruff, strict Mypy,
   complete repository tests and release Eval.
4. `completed` - Move the card to Review and re-evaluate the cloud integration gate.

### Decisions

- Production parsing, retry and safe unadvertised-tool rejection are correct and
  remain unchanged.
- Baseline repairs stack locally on the reviewed cloud branch only to restore its
  merge gate; they do not authorize a push, merge, backend selection or rollout.
- Microservice acceptance excludes `UI/desktop`; it covers Core, API, Worker,
  storage, integrations, security, Docker-managed dependencies and release Eval.

## BASE-MDL-EXPECT-01 - Provider Rejection Contract Expectations

1. `completed` - Reproduce both failures and trace typed rejection callers.
2. `completed` - Advertise the positive tool and assert typed DeepSeek rejection.
3. `completed` - Pass provider `41/41`, security trio `3/3`, Ruff and full-suite
   reduction to `7 failed, 1846 passed, 60 skipped`.
4. `completed` - Move the card to Review and activate the SCM fixture card.

## BASE-SCM-CRED-01 - Time-Stable SCM Credential Fixtures

1. `completed` - Prove fixed expiry drift across all five failures.
2. `completed` - Introduce one deterministic valid test expiry only in fixtures.
3. `completed` - Pass pull-request `25/25`, SCM/broker `40/40`, Ruff and full-suite
   reduction to `2 failed, 1851 passed, 60 skipped`.
4. `completed` - Move the card to Review and activate the Worker race card.

## BASE-WKR-CANCEL-01 - Durable Cancellation Finalization Race

1. `completed` - Reproduce and trace stale finalization state.
2. `completed` - Converge only typed durable interruption at finalization.
3. `completed` - Pass focused `3/3`, Worker `77 passed, 1 skipped`, Ruff, Mypy and
   full-suite reduction to `1 failed, 1853 passed, 60 skipped`.
4. `completed` - Move the card to Review and activate the UI size card.

## CLOUD-EFFECT-CONSUMER-01 - Worker Fenced Effect Consumer

1. `completed` - Trace Worker recovery, Lease lifecycle, tool execution and
   fenced Effect dispatch boundaries; freeze the minimum integration seam.
2. `completed` - Add background Lease heartbeat and loss propagation around the
   existing Worker execution lifecycle with fenced release on every exit.
3. `completed` - Guard external Effect execution with durable claim/terminalization
   and explicit uncertain reconciliation without automatic replay.
4. `completed` - Add deterministic crash, stale-fence and lifecycle regressions.
5. `completed` - Run focused/full validation, record evidence and preserve the
   stacked result for review without claiming production cutover.

### Decisions

- Work is stacked on locally reviewed `CLOUD-EFFECT-OUTBOX-01@69e34c0c`; the
  original dirty `main` worktree remains untouched.
- The user's continuation activates this local implementation slice only. It
  does not mark any dependency merged or authorize push, rollout or Store selection.
- Reuse the existing Lease and Effect dispatch contracts. Do not add a broker,
  Redis, generic Unit of Work, new dependency or cloud backend selector.
- The host Docker Compose PostgreSQL 17.5 consumer matrix passes `58/58`; its
  dedicated container, volume and network were removed after the run.

## CLOUD-EFFECT-OUTBOX-01 - Fenced Effect Dispatch Aggregate

1. `completed` - Reconcile the frozen Lease/Effect contract with existing
   PostgreSQL Event, Lease and Effect-ledger primitives; freeze the minimum types.
2. `completed` - Implement additive migration plus atomic schedule, claim, terminal,
   reconciliation and retry operations behind full Lease-fence validation.
3. `completed` - Add real PostgreSQL and deterministic contract tests for namespace,
   concurrency, stale fences, idempotency and crash rollback.
4. `completed` - Run focused/full validation, record evidence and preserve the result
   as an importable cloud-mainline bundle.

### Decisions

- Work is based on verified cloud integration commit `31969e22`; the original
  repository remains read-only and its dirty `main` worktree is untouched.
- This slice does not modify Worker, Tool Gateway, Redis, broker or runtime Store
  selection; those remain owned by `CLOUD-EFFECT-CONSUMER-01` or later gates.
- Deterministic Core/storage validation is green. The isolated host-run Docker
  Compose PostgreSQL 17.5 matrix passes `49/49`; the task is ready for Review.
- Recovery discovery, old-epoch reconciliation, terminal rollback, response-loss
  idempotency, namespace isolation, concurrent claim/reconcile CAS and retry-key
  conflict cases are present in the real PostgreSQL matrix. Trigger-backed fault
  injection covers schedule insert, terminal update and retry insert rollback.

## CTX-MEM-01 - Issue #197 Context Continuity And Governed Recall

1. `completed` - Verify issue `#197`, compare Codex, Claude Code, Pi Agent and
   Hermes, register one path-bounded task, and establish an isolated worktree.
2. `completed` - Land the v1.1 design baseline and executable implementation
   plan before changing runtime behavior.
3. `completed` - Add exact-tail compaction and one stricter original-history retry,
   then classify persistent context overflow as recoverable suspension.
4. `completed` - Add evidence-gated, conflict-safe candidate promotion and append
   its review events through the existing memory governance flow.
5. `completed` - Add SQLite FTS-backed relevant recall with stable-rule lane,
   deduplication, repo isolation and a token budget.
6. `completed` - Run focused, full, static and Eval gates; update durable evidence,
   commit, push and open the focused PR.

### CTX-MEM-01 Errors Encountered

- The first baseline command used nonexistent paths
  `tests/agent_core/test_context_window.py` and
  `tests/worker/test_execution_errors.py`; no tests ran. The actual context test
  is `tests/agent_core/test_context_window_gate.py`, and worker coverage is in
  lifecycle/finalization suites. The corrected baseline passed `33` tests.

## MEM-MEM0-ADP-01 - Mem0 Gateway Adapter

1. `completed` - Review the proven Mem0 REST contract, Core Gateway values and
   existing integration HTTP patterns.
2. `completed` - Claim a dedicated stacked branch with exact integration,
   test and governance paths.
3. `completed` - Implement disabled-safe configuration, opaque namespace mapping,
   strict REST decoding and bounded circuit-breaker behavior.
4. `completed` - Implement publish/search/delete over the Core Port with
   `infer=false`, provider-ref lookup and degraded error normalization.
5. `completed` - Add focused contract/fault tests, run repository validation and
   record the stacked handoff.

### Decisions

- Use the installed `httpx` dependency directly; the Mem0 SDK adds no needed
  contract and would leak provider behavior upward.
- Provider-ref persistence remains `MEM-GW-DEL-01`. This Adapter consumes a
  narrow lookup Port for delete and never creates a hidden in-memory fact source.
- Disabled and failed Mem0 paths return typed Gateway outcomes and never alter
  authoritative `MemoryStorePort` state.

## MEM-MEM0-SPIKE-01 - Mem0 OSS Contract And Operations Probe

1. `completed` - Inspect the pinned running Mem0 OpenAPI/source without reading
   secrets or issuing memory writes.
2. `completed` - Combine the reviewed Store, Gateway and Compose prerequisites
   in an isolated stacked worktree and claim the Spike paths.
3. `completed` - Add a deterministic OpenAI-compatible embedding stub and isolated
   Compose test overlay with no external credential.
4. `completed` - Exercise authenticated `infer=false` add/search/update/history/
   delete, namespace filters, duplicate delivery, restart and failure behavior.
5. `completed` - Record exact observed contracts, run focused/repository gates and
   preserve the separate real-provider credential gate.

### Decisions

- The deterministic provider validates Mem0 OSS/server/pgvector semantics only;
  it does not satisfy real-provider compatibility.
- The Spike remains isolated from the long-running dependency volumes and never
  changes Zebra's governed `MemoryStorePort` authority.

## MEM-GW-CON-01 - Provider-neutral Agent Memory Gateway Contract

1. `completed` - Audit the governed `MemoryStorePort`, authoritative Store
   composition, Mem0 direction and task dependency boundary.
2. `completed` - Claim an isolated stacked worktree on `CLOUD-STO-AUTH-01` with
   provider-neutral Core/test ownership only.
3. `completed` - Implement validated publish/search/delete values and Protocol.
4. `completed` - Prove confirmed-only publication, opaque authority, revalidatable
   hits, partial/degraded behavior and provider-independent schemas.
5. `completed` - Run focused and repository validation, record evidence and handoff.

### Decisions

- `MemoryStorePort` remains authoritative for governed lifecycle and content.
- Gateway hits intentionally omit memory text and Zebra confidence; callers must
  resolve `MemoryId` through the Store before prompt admission.
- Mem0 is the first planned adapter, but no provider or transport type enters Core.

## MEM-GW-DEL-PLAN-01 - Memory Delivery Ledger v11 Plan And Task Split

1. `completed` - Ask the sidebar ChatGPT planning session to review the real
   `zebra-cloud-trench@ac9801c2` baseline and the current Mem0/v10 contracts.
2. `completed` - Confirm that the original `MEM-GW-DEL-01` card is not safe to
   unlock: atomic enqueue, typed certainty and scoped reset/rebuild are missing.
3. `completed` - Freeze the three-table v11 model, operation state machine,
   unknown-result quarantine and batch search revalidation rules.
4. `completed` - Register four path-bounded child cards and keep the parent
   `MEM-GW-DEL-01` `Locked` until their dependency gates are satisfied.
5. `completed` - Validate the docs-only split, record the Git object repair
   observation and hand off the first activation decision. `git diff --check`
   passes; `make check` remains blocked only by the inherited Desktop stylesheet
   size violation (`561/500`).

### Decisions

- `memory_delivery_scopes`, `memory_delivery_operations` and
  `memory_provider_mappings` contain metadata and digests only; never Memory text,
  provider bodies or credentials.
- `unknown` is a terminal quarantine decision for automatic delivery. It is not a
  retryable error and must not be inferred from a free-form detail string.
- `MEM-GW-DEL-CON-01` and `MEM-MEM0-RESET-SPIKE-01` are the first possible child
  activations. `MEM-GW-DEL-PG-01` follows Core; `MEM-GW-DEL-RUN-01` follows both
  the PG ledger and the reset/rebuild gate.
- The default Worker/API composition and local SQLite profile stay unchanged until
  a later cloud composition gate supplies one verifiable Store/Host namespace.

## MEM-GW-DEL-CON-01 - Core Memory Delivery Certainty Contract

1. `completed` - Claim `codex/mem-gw-del-con-01` with exact Core/domain/Port/test
   owned paths after the v11 plan review and explicit maintainer continuation.
2. `completed` - Add provider-neutral scope, operation, certainty and state-transition
   values with focused Core tests.
3. `completed` - Prove illegal status/certainty combinations and package boundaries;
   do not add SQL, HTTP, Mem0 or Worker wiring.
4. `completed` - Move the child to `Review` with exact evidence before PG work starts:
   `361` Core/Mem0 tests, strict Core Mypy, Ruff, diff check and Eval `10/10` pass;
   the full suite has only the inherited Desktop size-gate failure.

## MEM-MEM0-RESET-SPIKE-01 - Scoped Mem0 Namespace Reset And Rebuild Probe

1. `completed` - Activate `codex/mem0-reset-spike-01` with exact Compose/proxy/test
   owned paths after the sidebar ChatGPT review; keep Core, PG ledger and Worker
   successors locked.
2. `completed` - Run the isolated Compose probe; the pinned OpenAPI exposes no
   documented bounded pagination (`page/page_size` or `offset/limit`), so the test
   fails closed before any publish and cleans its project/volumes.
3. `completed` - Record the operator authorization and upper-bound result; `top_k`
   is not treated as pagination and no global `/reset` endpoint is substituted.
4. `completed` - Mark the child `Blocked` because exact scoped enumeration cannot be
   proven; preserve the parent lock and do not start the runtime consumer.

## MEM-GW-DEL-PG-01 - PostgreSQL v11 Delivery Ledger And Atomic Enqueue

1. `completed` - Activate `codex/mem-gw-del-pg-01` after `MEM-GW-DEL-CON-01`
   integration and explicit v10 authority transaction ownership. The blocked
   scoped-reset Spike is an independent management gate; the parent and runtime
   cards remain locked.
2. `completed` - Add v11 migrations and metadata-only delivery/mapping tables.
3. `completed` - Attach publish/delete enqueue to the v10 authority mutation in
   the same transaction; implement independent claim/CAS and batch hit
   revalidation.
4. `completed` - Run fresh/v1-v10 upgrade/checksum, migration rollback, duplicate
   replay, stale ACK, namespace, unknown/in-flight quarantine and real PostgreSQL
   Compose matrices. No application container or provider HTTP path was started.

### Closeout

- Review covered integrated implementation `a30c8b5e`; PostgreSQL v11 delivery
  metadata, atomic authority enqueue, independent claim/CAS and batch revalidation
  are accepted.
- Recorded host Compose evidence is `24/24`; the parent ledger and runtime
  consumer remain locked by the independent scoped-reset enumeration block.
- `MEM-GW-DEL-PG-01` is `Done`; no Mem0 HTTP, Worker default or local SQLite
  composition was enabled.

## MEM-MEM0-RESET-ALT-01 - Scoped Reset Alternative Validation

1. `completed` - Claim the sidebar-planned test-only task on
   `codex/mem0-reset-alt-01`; keep production packages, Provider HTTP, Worker,
   Desktop and local SQLite composition out of scope.
2. `completed` - Add an isolated PostgreSQL Compose spike that validates
   logical generation reset, mapping-based deletion and unknown-publish orphan
   boundaries without provider enumeration.
3. `completed` - Record the `B/PARTIAL` verdict and synchronize the task registry,
   PROGRESS, findings, WORKLOG and the focused compatibility evidence document.
4. `completed` - Run focused static checks, the new Compose runner, and the
   existing delivery/storage regression matrices before moving the card to
   `Review`; do not unlock `MEM-GW-DEL-RUN-01` on a partial result.

### Closeout

- Review accepted the explicit `B/PARTIAL` verdict: logical generation reset
  and known mapping deletion work, but an unknown provider orphan remains
  unrecoverable from the ledger.
- The host Compose result is `2 passed` with
  `ZEBRA_MEM0_RESET_ALT_VERDICT=B`; the current sandbox has no PostgreSQL
  service and reports `2 skipped`.
- `MEM-MEM0-RESET-ALT-01` is `Done` as validation only. Mem0 consumer, parent
  ledger and Runtime remain locked.

## MEM-PROVIDER-DEL-COMPLIANCE-01 - Provider Deletion Compliance Contract

1. `completed` - Ask the sidebar ChatGPT planning session to select the only
   legal Ready successor after the reset alternative returned `B/PARTIAL`.
2. `completed` - Define deterministic recovery, deterministic physical
   deletion, complete scoped coverage and fail-closed provider admission in
   `docs/ADR-018_Memory Provider Deletion Compliance Contract.md`.
3. `completed` - Add provider-neutral specification tests for the mandatory
   capabilities, Mem0 capability matrix and Runtime lock boundary.
4. `completed` - Run focused specification, static, documentation and repository
   checks; record the final admission verdict without changing production code.

### Decisions

- The contract is a governance/specification boundary and does not implement a
  Provider HTTP client, Mem0 adapter, Worker, Desktop, SQLite or Runtime path.
- Mem0 is currently denied from the Memory mainline: logical fencing and known
  mapping deletion are proven, while ambiguous-create recovery and complete
  scoped physical deletion remain `FAIL/UNPROVEN`. Future re-entry requires new
  upstream capability evidence and a new admission run.
- `MEM-MEM0-RESET-SPIKE-01` stays `Blocked`; `MEM-GW-DEL-RUN-01`, its parent and
  Runtime composition stay `Locked` until a provider passes this contract.

### Review handoff

- ADR-018 and the specification test are complete; the focused suite passes
  `2`, and changed-path Ruff, format, Mypy, compilation and `git diff --check`
  pass.
- `make check` is blocked only by the inherited file-size gate in two untouched
  paths (`561/500` Desktop stylesheet and `765/700` PostgreSQL test file).
- Contract verdict is `PASS`; Mem0 admission and Runtime remain `BLOCKED`.

## MEM-PG-NATIVE-ADMISSION-SPIKE-01 - PostgreSQL-Native Memory Admission

1. `completed` - Ask the sidebar ChatGPT planning session for the only legal
   successor after ADR-018; choose the PostgreSQL-native candidate and defer
   Mem0 from the active critical path.
2. `completed` - Add a test-only PostgreSQL authority/retrieval schema and
   isolated dependency-only Compose profile; do not add production code.
3. `completed` - Prove deterministic identity/recovery, atomic projection,
   generation write fencing, complete scoped deletion, namespace isolation and
   minimum recall with eight independent real-PostgreSQL cases.
4. `completed` - Run the focused Compose matrix and changed-path static checks,
   record `ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS`, and keep Runtime locked.

### Decisions

- The PostgreSQL-native architecture was admitted by the reviewed Spike, and
  `MEM-GW-PG-NATIVE-01` is now explicitly activated for the storage-only slice.
- The Spike's schema is test-only and per-schema; it is not a migration and does
  not select PostgreSQL at any runtime composition root.
- The focused runner starts only PostgreSQL 17.5 and passed `8` cases. Existing
  delivery/storage results remain regression evidence (`24`; `295 passed, 1
  skipped`).
- `PASS` does not unlock Worker, Provider HTTP, Desktop, SQLite, Redis or
  Runtime. Mem0 remains `Provider admission: DENIED` and `Mainline candidate:
  DEFERRED`.

### Review handoff

- `tests/compose/postgres_native_memory_admission/run-postgres-tests.sh` emits
  `ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS` and cleans its container, volume and
  network. Eight tests pass in the isolated PostgreSQL 17.5 profile.
- The full `tests/agent_storage` matrix passes `303 passed, 1 skipped` (`295`
  predecessor cases plus `8` admission cases), so the new test does not regress
  the PostgreSQL storage baseline.
- Changed-path Ruff, format, Mypy and `git diff --check` pass. `make check`
  remains blocked only by the two inherited file-size violations recorded in
  ADR-019.

### Closeout

- Review accepted ADR-019, its test-only per-schema boundary and the recorded
  real PostgreSQL `8/8` admission matrix with explicit `PASS` verdict.
- Current-head validation has no PostgreSQL service and therefore reports
  `8 skipped`; it does not supersede the host Compose evidence.
- `MEM-PG-NATIVE-ADMISSION-SPIKE-01` is `Done`; only the separately activated
  PostgreSQL-native storage implementation proceeds. Mem0 and Runtime remain
  denied/deferred or locked.

## MEM-GW-DEL-RUN-01 - Mem0 Delivery Consumer And Management Rebuild

1. `pending` - Start only after the PG ledger and scoped reset Spike are reviewed,
   and the Adapter dependency is governance-integrated.
2. `pending` - Map provider responses to typed certainty and consume operations with
   independent claims; quarantine unknown publish outcomes.
3. `pending` - Add management-only generation rebuild: complete v10 scan, delivery
   high-watermark drain, atomic switch, then safe old-generation purge.
4. `pending` - Run PostgreSQL+Mem0 fault, outage, delete, search and rebuild tests;
   do not modify default local composition.

### Decisions

- This remains a Mem0-specific, deferred card with `Locked` admission. It is not
  a successor to the PostgreSQL-native path and must not be activated by its
  `PASS` result.

## MEM-GW-PG-NATIVE-01 - PostgreSQL-Native Memory Backend Implementation

1. `completed` - Activate the sole storage successor after the reviewed native
   admission `PASS`; claim `codex/mem-gw-pg-native-01` with frozen Owned paths.
2. `completed` - Freeze a production PostgreSQL migration and provider-neutral
   storage API from ADR-018/019 without changing local SQLite composition.
3. `completed` - Implement authority/retrieval atomic commit, deterministic
   operation recovery, generation CAS/reset, complete scoped delete and native
   recall under `packages/agent-storage`.
4. `completed` - Run fresh/v11-upgrade migration checks and the isolated real
   PostgreSQL storage matrix; keep Runtime, Worker, Provider HTTP, Desktop,
   Redis and SQLite composition as separate locked gates.

### Activation boundary

- The maintainer explicitly activated this card on 2026-08-02. Its production
  scope is storage only; an application or Runtime integration requires a new
  task card after this implementation is reviewed.
- The test-only admission schema is a design input, not a production migration.
  Production tables must use the repository migration registry and transaction
  conventions, with no constructor DDL or provider calls.
- Mem0 remains denied/deferred under ADR-018/019. No reset, enumeration or
  orphan-recovery work is a prerequisite or hidden part of this card.

### Review handoff

- Production v12 and the storage-only `PostgresNativeMemoryGateway` are
  complete. The focused isolated PostgreSQL 17.5 runner passes `10` cases and
  the full `tests/agent_storage` matrix passes `313 passed, 1 skipped`.
- The existing v11 delivery runner passes `24`; changed-path Ruff, format,
  strict Mypy, compilation and diff checks pass. `make check` reaches only the
  two inherited file-size violations recorded in `WORKLOG.md`.
- This card is ready for review/merge. Runtime composition remains a separate
  locked gate and Mem0 remains denied/deferred.

### Closeout

- Review covered integrated storage implementation `91fd5964`, migration v12,
  atomic authority/retrieval projection, operation recovery, generation CAS,
  complete scoped deletion and deterministic native recall.
- Recorded Compose PostgreSQL `10/10`, full storage `313 passed, 1 skipped` and
  delivery `24 passed` evidence is accepted. Current-head validation without a
  PostgreSQL service reports `18 skipped`.
- `MEM-GW-PG-NATIVE-01` is `Done`; it remains storage-only. Runtime, Worker,
  Provider HTTP, Desktop, SQLite, Redis and Mem0 are not selected.

## CLOUD-LEASE-PG-01 - PostgreSQL Epoch And Lease Adapter

1. `completed` - Audit the reviewed PostgreSQL migration/Adapter patterns and
   freeze the epoch bootstrap/rotation plus Lease SQL state machine.
2. `completed` - Add explicit epoch and Lease migrations without constructor DDL.
3. `completed` - Implement namespace-scoped database-clock acquire, heartbeat,
   release, read and restore-rotation behavior behind the Core Port.
4. `completed` - Add real PostgreSQL race, collision, takeover, stale-fence,
   clock-skew, namespace and migration tests.
5. `completed` - Run focused/full/quality validation, independent review, durable
   evidence and a local commit without composition or push.

### Decisions

- This branch is stacked on local `CLOUD-LEASE-CON-01@816a1e3b`; continuation is
  a local implementation waiver, not permission to merge, push or cut over.
- Reuse the existing psycopg migration and transaction patterns from
  `CLOUD-PG-01`; do not add an ORM, pool, testcontainers or constructor DDL.
- PostgreSQL transaction time is the only ownership clock. Callers provide TTL,
  never an expiry timestamp.
- Do not modify Store composition, API, Worker or Effect execution in this card.

## CLOUD-LEASE-CON-01 - Core Lease And Fencing Contract

1. `completed` - Trace every Lease and handoff fence caller, freeze the
   additive typed contract and register exact compatibility changes.
2. `completed` - Add `LeaseFence`, Core Lease errors and full-fence Port semantics.
3. `completed` - Make SQLite Lease generations durable, CAS heartbeat/release and
   separate handoff fencing from checkpoint.
4. `completed` - Adapt Worker claim ordering and add focused Lease/handoff/claim
   regressions without background heartbeat or PostgreSQL.
5. `completed` - Run focused/full/quality validation, independent review, durable
   evidence and local commit.

### Decisions

- This local branch is stacked on reviewed plan commit `e373786b`; the user's
  continuation is a task-specific local waiver, not a merge or release waiver.
- Keep the contract backend-neutral: SQLite uses an injected clock for local
  determinism while PostgreSQL DB-clock authority remains the next card.
- Do not add background heartbeat, Effect dispatch, PostgreSQL or composition.
- API handoff reserve is the only additional caller discovered after claim; its
  exact adapter and route test paths were added before implementation.
- Two direct Lease setup tests also use the old concrete acquire signature;
  their exact paths were added rather than retaining caller-clock compatibility.

## CLOUD-LEASE-PLAN-01 - Lease, Fencing And Effect Dispatch Contract

1. `completed` - Audit current Lease, Effect ledger, handoff outbox and Worker
   lifecycle behavior and identify stale-writer and crash windows.
2. `completed` - Create an isolated stacked branch and register one docs-only
   task with exact owned paths while keeping the parent Locked.
3. `completed` - Define control-plane epoch, monotonic Lease fencing,
   database-clock TTL and checkpoint-independent ownership semantics.
4. `completed` - Define atomic Effect dispatch, durable intent discovery/claim,
   uncertain-effect reconciliation and path-bounded follow-up cards.
5. `completed` - Reader-test the contract, run documentation gates, record durable
   evidence and commit the local review slice.

### Decisions

- Do not implement the original `CLOUD-LEASE-01` as one card; it crosses Core,
  PostgreSQL, tool execution and Worker lifecycle ownership boundaries.
- Keep ordinary API/System Event writes on `EventStorePort`; only leased Worker
  mutations use a focused fenced aggregate Port.
- Do not introduce a generic inbox before an external broker or consumer exists.

### Closeout

- Review covered the integrated Lease/fencing and Effect dispatch contract
  `e373786b`; epoch, database-time fencing, aggregate boundaries and the
  at-least-once/uncertain-effect crash matrix are accepted.
- `make eval` passes `10/10`, the contract remains `449` lines and no runtime,
  migration, selector, Redis, broker or production claim was added.
- `CLOUD-LEASE-PLAN-01` is `Done`; its Core, PostgreSQL Lease, Effect Outbox
  and Worker consumer children remain independently gated.

## CLOUD-PG-01 - PostgreSQL Event And Projection Storage

1. `completed` - Review the approved migration/recovery model, authoritative
   Store boundary, existing SQLite semantics and real Compose PostgreSQL dependency.
2. `completed` - Register and claim the isolated task with exact owned paths and
   preserve the local stacked merge/CI constraints.
3. `completed` - Add one explicit psycopg dependency, versioned migration runner
   and namespace-scoped Event/Projection Adapters without runtime composition.
4. `completed` - Add SQLite idempotency regression plus real PostgreSQL migration,
   concurrency, idempotency, namespace, projection and replay tests.
5. `completed` - Run focused and repository validation, independently review the
   slice, update durable evidence and commit the local branch.

### Decisions

- Derive expected Event version from `event.sequence - 1` and persist stream
  version with SQL CAS in the same transaction as Event insertion.
- Adapter constructors never run DDL; only the explicit migration runner does.
- Inject one immutable deployment namespace into each Adapter and include it in
  every key and predicate.
- Do not add a pool, ORM, Alembic, testcontainers or partial cloud composition.

### Closeout

- Review covered integrated PostgreSQL Event/Projection implementation `15c386db`;
  migration, Event CAS/idempotency, namespace isolation and replay-safe
  Projection behavior are accepted.
- Recorded real Compose PostgreSQL `14/14`, storage `113/113` and custom-format
  dump/restore `14/14` evidence is accepted. Current-head local validation is
  `8 passed, 14 skipped` without a PostgreSQL service.
- `CLOUD-PG-01` is `Done`; the Lease contract plan is the next review gate.

## CLOUD-PG-PLAN-01 - PostgreSQL Migration And Recovery Model Review

1. `completed` - Trace the authoritative Store composition, PostgreSQL phase
   dependency and existing recovery constraints.
2. `completed` - Register and claim one docs-only task on the authoritative
   Store branch with the CI-billing waiver recorded.
3. `completed` - Define authority scope, migration/cutover invariants and explicit
   abort versus rollback behavior.
4. `completed` - Define backup/PITR, restore validation, fencing/outbox recovery and
   measurable pre-production gates.
5. `completed` - Reader-test the decision document, update governance evidence and
   commit the local stacked review slice.
6. `completed` - Formally audit the decision document and Store dependency, then
   close the card as Done without implementing PostgreSQL.

### Decisions

- Do not dual-write SQLite and PostgreSQL; the flat Store bundle selects one
  authoritative backend for a process profile.
- Do not invent production RPO/RTO. The document defines required measurements
  and an approval field before production traffic.
- This task writes no Adapter, migration executable or cloud dependency.

### Closeout

- Review covered integrated docs-only implementation `e1e71139`; authoritative
  Store composition is `Done`, with the CI-billing waiver explicitly limited to
  local evidence.
- The migration/recovery contract and its reader/link/terminology evidence are
  accepted. No Compose run, production edit, Adapter, migration executable or
  backend selector was added.
- `CLOUD-PG-01` is the next implementation Review gate; Lease, Runtime, Provider
  HTTP, Desktop and application backend selection remain gated.

## CLOUD-STO-AUTH-01 - Complete Authoritative Store Composition

1. `completed` - Audit every API/Worker durable collaborator that can advance a
   Session, gate an effect, or govern memory, including constructor call sites.
2. `completed` - Claim the exact Core/Storage/API/Worker/test/governance paths on
   an isolated branch stacked directly on `CLOUD-STO-SEAM-01`.
3. `completed` - Extend the flat `ControlPlaneStores` with typed Ports and keep
   the local SQLite builder as the only API/Worker constructor root.
4. `completed` - Replace legacy path lookups with injected stores and add A/B
   regressions that prove the unused database is not even created.
5. `completed` - Run focused, full and quality validation, record inherited
   baseline failures, close the card to Review, and commit the local slice.
6. `completed` - Formally audit the integrated diff and dependency order, then
   close the card as Done without selecting a cloud backend.

### Decisions

- Keep one flat composition value. Backend hierarchies, backend enums and a
  PostgreSQL selection switch would add no value before a second adapter exists.
- Context lifecycle and handoff remain aggregate transaction boundaries; future
  adapters implement those Ports atomically instead of exposing their tables to
  API or Worker composition.
- `database_path` remains a local-profile configuration input, not a durable
  authority locator after a `ControlPlaneStores` bundle has been injected.
- Zebra's governed `MemoryStorePort` remains authoritative. Any Mem0 or other
  semantic-memory integration is a separate, derived, degraded-safe Gateway.
- The branch is local and unpushed. Merge order remains
  `EMB-PLAN-01 -> CLOUD-STO-SEAM-01 -> CLOUD-STO-AUTH-01`.

### Closeout

- Review covered integrated implementation `7be231e7`; Embedded architecture and
  the local composition seam are both `Done`, with explicit maintainer activation.
- The declared typed Ports, Storage bundle, API/Worker wiring and A/B tests remain
  the complete scope. Recorded A/B `9 passed`, combined `365 passed`, Eval `10/10`
  and quality evidence are accepted; current-HEAD focused regressions pass `11/11`.
- No Compose execution or production edit was made. Mem0, PostgreSQL, Redis, S3,
  backend selection and Runtime remain separate gates.
## CLOUD-COMPOSE-INFRA-01 - Docker Compose Dependency Baseline

1. `completed` - Audit repository container assets, architecture sequencing and
   Mem0 OSS self-hosting and release behavior.
2. `completed` - Register and claim the dependency-only task on an isolated
   branch stacked behind `CLOUD-STO-SEAM-01`.
3. `completed` - Create the base dependency Compose, optional Mem0 overlay,
   pinned non-root boot-smoke image, safe environment template and runbook.
4. `completed` - Validate rendered contracts and start base plus optional Mem0
   services through real migrations, health and authentication checks.
5. `completed` - Update architecture/progress evidence, obtain independent review,
   run repository checks
   and commit the task without pushing or merging stacked dependencies.
6. `completed` - Formally audit the separated dependency/application boundary and
   existing host evidence, then close the card as Done without running Docker here.

### Decisions

- Dependency containers and Zebra application containers have separate task,
  file and Compose lifecycles.
- `redis-live`, Zebra PostgreSQL, Mem0 PostgreSQL and Mem0 history never share a
  persistence role; Mem0 remains derived and rebuildable.
- `AgentMemoryGateway` is provider-neutral. Mem0 receives only confirmed memory
  with `infer=false`; every retrieval is revalidated against `MemoryStorePort`.
- The pinned Mem0 image and Compose overlay prove boot only. Real write/search,
  idempotency, deletion and namespace behavior remain a separate credentialed Spike.

### Closeout

- Review covered integrated Compose implementation `b23b8e762`; Embedded and
  storage composition prerequisites are `Done`, with maintainer activation recorded.
- The separated dependency stack, optional Mem0 overlay, pinned non-root image,
  health checks, volumes and environment template remain within scope. Existing
  render/hash, health, migration and auth evidence is accepted; no Docker-socket
  operation or production edit was made by this review.
- Mem0 semantics remain gated by its contract/adapter cards; Zebra application
  images, PostgreSQL adapters and Runtime selection are not unlocked.

## CLOUD-STO-SEAM-01 - Control-Plane Storage Composition Seam

1. `completed` - Audit API/Worker SQLite construction, existing Store Ports,
   Agent Memory semantics and the revised dependency order.
2. `completed` - Register and claim the path-bounded task on an isolated stacked
   worktree while preserving the hard `EMB-PLAN-01` merge order.
3. `completed` - Add one flat control-plane Store bundle and local SQLite builder.
4. `completed` - Inject the bundle through API/SSE and Worker flows, prove
   same-path injection and reject partial split backends before any write.
5. `completed` - Run focused, full and quality validation; record remaining Port
   gaps and the next PostgreSQL/memory task without adding a cloud dependency.
6. `completed` - Formally audit the integrated diff and prerequisites, then close
   the card as Done without selecting a cloud backend.

### Decisions

- The user reprioritized Zebra durable storage and memory foundations ahead of
  further Trench work on 2026-07-23.
- PostgreSQL remains durable truth, S3-compatible storage owns payload bytes,
  Redis live state is erasable, and semantic memory remains a separate,
  degraded-safe `AgentMemoryGateway` rather than a `MemoryStorePort` replacement.
- This task composes only the five existing control-plane Ports. Legacy durable
  stores without adequate Ports are recorded in `CLOUD-STO-AUTH-01`; the partial
  bundle fails closed if its database differs from those legacy stores.
- Because PR `#194` is still open, this local branch is stacked and cannot merge
  before `EMB-PLAN-01`; it will not push or merge as part of this local task.

### Closeout

- Review covered integrated implementation `c4c1f593`; `EMB-PLAN-01` is `Done`
  and Runtime Phase A plus maintainer activation are recorded.
- The declared API/Worker wiring, flat Store bundle, SQLite builder, projection
  Port and focused tests remain the complete scope. Current-HEAD composition
  regressions pass `20/20`; no Compose run or production edit was made.
- `CLOUD-STO-AUTH-01` is the next authoritative composition gate; PostgreSQL,
  Redis, S3 and runtime backend selection remain out of scope here.

## EMB-AGUI-SPIKE-01 - Official Python AG-UI Compatibility Spike

1. `in_progress` - Commit the reviewed Embedded architecture baseline without
   the user's unrelated `AGENTS.md` timestamp change, then create the isolated
   stacked worktree and task branch.
2. `pending` - Pin and inspect the official Python AG-UI protocol SDK and encoder.
3. `pending` - Add canonical stream, SSE round-trip, interrupt/resume, and
   unknown-event compatibility fixtures under the task-owned test path.
4. `pending` - Run focused, full, and quality validation; distinguish any
   unrelated baseline failures from task regressions.
5. `pending` - Record the version matrix, observed boundaries, follow-up contract
   decisions, and final branch handoff.

### Decisions

- This is a test-only Spike. No production package, API route, Worker composition,
  Zebra Domain Event, or Trench/CopilotKit code is in scope.
- Maintainer direction explicitly activates the Spike before the architecture
  branch merges. The implementation branch is stacked on `zebra-cloud-trench`
  and must not merge first.
- The generic worktree skill required by `executing-plans` is not installed;
  use Git's native worktree commands with the same isolation guarantees.

## EMB-PLAN-01 - Zebra Embedded Architecture Consolidation

1. `completed` - Audit the draft Embedded architecture, repository source-of-truth
   documents, current cloud activation state, and existing implementation seams.
2. `completed` - Consolidate the draft into one authoritative architecture that
   uses CopilotKit in Trench and removes the custom Zebra React SDK plan.
3. `completed` - Register dependency-ordered Embedded, Trench, cloud, analysis,
   writeback, memory, and GA task cards with explicit owned paths and gates.
4. `completed` - Synchronize durable project progress and worklog records without
   activating implementation tasks prematurely.
5. `completed` - Validate document consistency, file limits, and the final diff.

### Closeout

- Review covered integrated architecture commit `8d1650bf`; Runtime Blueprint
  and service-boundary prerequisites are `Done`, and the CopilotKit direction is
  the accepted maintainer decision.
- Architecture, ADR-015, Trench breakdown, task registry and progress records
  are synchronized. The repository's two unrelated size-gate violations remain
  documented; no implementation or Compose work was activated.
- `EMB-AGUI-SPIKE-01` remains a separately activated Review card; cloud storage,
  Runtime and provider cards retain their own dependency gates.

### Decisions

- `zebra-cloud-trench` owns this architecture and task-registry change only;
  implementation cards use one task, branch, worktree, owner, and PR each.
- Trench owns CopilotKit React v2 and its Copilot Runtime/BFF. Zebra exposes an
  AG-UI adapter and remains the durable Task, Event, Policy, approval, tool
  receipt, and Artifact authority.
- The first production business slice is read-only. Analysis, controlled
  writeback, the optional Memory Gateway, and multi-tenant GA follow explicit gates.

### Errors Encountered

- The first status-search command placed Markdown backticks inside a
  double-quoted shell pattern, so zsh attempted command substitution for
  `Ready` and `In`. No files changed. The replacement check uses literal
  patterns without backticks.
- The repository-wide file-size gate reports two pre-existing violations in
  untouched files: `CodexConversationPane.styles.ts` at 561/500 lines and
  `agent_core/contracts/events.py` at 505/500 lines. All three new documents are
  within their applicable limits; the unrelated baseline was not modified.
- The generic planning skill stop checker reported `0/0 phases` because this
  repository's existing `task_plan.md` uses numbered backticked statuses rather
  than the checker's checkbox headings. The five EMB-PLAN-01 entries above are
  explicitly `completed`; targeted document validation is the completion gate.

## AGENT-DEF-ADR-01 - Definition Authority And Snapshot ADR

1. `completed` - Reconcile the accepted direction with ADR-001/009/012/013/014,
   current Task/Event/Skill/Memory contracts, and local/cloud authority boundaries.
2. `completed` - Write ADR-016 and update the final architecture with only its stable
   decisions and dependency unlock rule.
3. `completed` - Align the proposal, docs guide, PROGRESS and task registry; keep all
   implementation tasks locked.
4. `completed` - Run fresh-reader decision/ambiguity review and documentation gates.
5. `completed` - Record evidence and commit the docs-only ADR branch locally.

### Decisions

- This branch is stacked on accepted-direction commit `663a043d`; it does not
  merge, push or modify the dirty main worktree.
- Gate A may change only architecture/governance documents in its registered
  Owned paths; Python, SQL, API and Docker work remain out of scope.

## Agent Definition V2 - Accepted Direction And Task Activation

1. `completed` - Separate immutable Task Definition configuration from per-Attempt
   execution authority and align namespace with ADR-012.
2. `completed` - Register the ADR, Core, SQLite/PostgreSQL Store, Publication,
   Task binding, Memory, Trust and Eval task chain with dependency-ordered,
   path-bounded gates.
3. `completed` - Run a fresh-reader conflict and execution-order review, then
   validate the documentation diff.
4. `completed` - Record final evidence and commit the accepted-direction update.

### Decisions

- The proposal direction and ADR-016 are locally accepted, but remain non-executable
  until `AGENT-DEF-ADR-01` is merged.
- `AGENT-DEF-ADR-01` is the only active task; all Python/SQL/API/runtime work is
  `Locked`.
- Task identity and Definition configuration remain stable across Segments, while
  external execution authority is revalidated for every Attempt.
- Zebra stores only opaque `(authority_issuer, namespace_id)` isolation keys and
  does not create a Tenant/User/Organization domain.

## ARCH-RUNTIME-V2-PLAN-01 - Runtime V2 Proposal Current-State Alignment

1. `completed` - Compare every proposal lane with current docs, code and task evidence.
2. `completed` - Rewrite the proposal as a current-state delta with explicit authority
   and non-executable status.
3. `completed` - Align the docs guide, PROGRESS and task governance without modifying the
   final architecture or activating implementation.
4. `completed` - Run fresh-reader ambiguity/contradiction tests and documentation gates.
5. `completed` - Record durable evidence and commit the docs-only branch locally.

### Decisions

- Use `origin/main@a6b47c3f` as the review baseline; keep the dirty local main
  worktree and its untracked documents untouched.
- Classify the proposal in `docs/README.md`, not the product README, so an
  exploratory document is not mistaken for the operator or architecture entry.
- A future reusable Agent is named `AgentDefinition`; existing `AgentTask` remains
  the durable user execution identity.
- This proposal may recommend ADRs and locked follow-up cards, but cannot modify
  the final architecture or claim implementation completion.

## CTX-SEG-02 - Follow-up Context And Budget Recovery

1. `completed` - Register and claim the path-bounded repair task on an isolated branch.
2. `completed` - Preserve a bounded prior user/assistant checkpoint across terminal follow-up rollover.
3. `completed` - Remove implicit low call ceilings and suspend recoverably when an explicit hard budget cannot fit a complete batch.
4. `completed` - Hide NoopVerifier status noise while keeping real verifier evidence visible.
5. `completed` - Update durable architecture/status records and run focused, full, Desktop, and quality gates.

## WEB-UX-01 - Trusted Local Read-Only Web Auto Execution

1. `completed` - Register and claim a path-bounded task on an independent branch.
2. `completed` - Treat durable allowlist Web authority as automatic allow and
   explicit local trusted mode as a one-time operator trust boundary.
3. `completed` - Default new Desktop tasks to trusted local Web authority and
   preserve durable profile rendering.
4. `completed` - Run focused, full repository, Desktop, and browser regressions;
   then close the task with durable evidence.
5. `completed` - Upgrade existing local Tasks at execution time, honor the
   system HTTPS proxy, remove local command/MCP approval interruptions, and rerun
   the real old-Task plus full regression chain.

## SUBAGENT-UX-01 - Model-Native Subagent Delegation

1. `completed` - Approve and independently review the model-native delegation
   design, then register a separate owned task and branch.
2. `completed` - Inject manifest-aware parent guidance and require a model-authored
   delegation reason with actionable validation recovery.
3. `completed` - Prove direct, parent-tool, complex delegation, invalid-call retry,
   child non-recursion, and failed-child fallback behavior.
4. `completed` - Update durable architecture/status records and run focused, full,
   static, Eval, and real-model simple-task validation.

## CTX-SEG-01 - Stable Task And Automatic Internal Segments

1. `completed` - Record ADR-013, supersede the explicit user handoff decision,
   and define the dependency-ordered Task/Segment implementation roadmap.
2. `completed` - Remove ordinary Desktop handoff rendering, navigation, and client
   creation actions without changing backend safety contracts.
3. `completed` - Add a deterministic regression that forbids stage handoff controls
   on the ordinary user surface.
4. `completed` - Run Desktop checks/build and repository validation, then update
   durable status, findings, and worklog evidence.
5. `completed` - Add Task/Segment domain and SQLite projection/migration contracts.
6. `completed` - Add Task API, monotonic cross-Segment stream, and active-Segment routing.
7. `completed` - Add deterministic lifecycle controller and automatic safe rollover.
8. `completed` - Bind Desktop to stable Task identity and add cross-Segment regressions.
9. `completed` - Run all gates, update closeout evidence, push, and open the PR.

### Errors Encountered

- The first full test run found `session_handoffs.py` at 526 lines after the
  atomic Task CAS integration. Task-specific storage logic and row types were
  moved to their owned modules; the file is now 497 lines and the gate passes.
