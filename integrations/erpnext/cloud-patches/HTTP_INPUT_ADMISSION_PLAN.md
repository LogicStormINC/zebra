# ERP Cloud native attachment admission repair: review proposal

Status: investigation and exact deployed source snapshot only. No runtime patch, migration, image build, or remote mutation has been performed. This proposal is awaiting the parent agent's independent review before implementation.

## Verified baseline and root cause

The isolated ERP containers are pinned by current immutable image identity in `baseline/containers.txt`:

- API: `sha256:2156443eea6ad9330853d16ece204dfa0995a41e5b5b677063386216797daaef`.
- Worker: `sha256:33b93abc4b257d0639730f2e2c388d765f092d7979a03b117f6387b0049c0e18`.

Both installed migration catalogs end at 105 (`scoped_plugin_installations`). A read-only PostgreSQL query also confirms applied version 105. The local main checkout is newer (107) and must not supply the patch's catalog or build source.

`baseline/` now contains 38 exact deployed source files, including the Core artifact models, LeaseFence, shared row parser, Host authentication/JWT/registry implementation, and native handoff/outbox transaction. `baseline/sha256.json` binds every file. All 26 captured shared package files were independently hashed in the running ERP Worker; they match the API exactly (`baseline/worker-shared-sha256.json`).

The failing initial route is `POST /tasks` -> `create_session` -> `create_queued_session` -> `persist_initial_attachments` -> `store_initial_text_attachments` -> `store_text_attachments` -> legacy `ArtifactPayloadStorePort.store_payload`. The Cloud composition deliberately supplies `PostgresCloudArtifactPayloadStore`, whose generated-output API requires real Worker lease fencing and has no `store_payload`. The same legacy path appears in `app.append_session_message`, reached by both Task and Session append routes. Adding a method shim or granting HTTP fake Worker authority would violate the storage contract.

There is no existing HTTP input artifact ingress authority/coordinator. `CloudToolOutputArtifactCoordinator` handles generated outputs under a real Worker fence and cannot serve this HTTP admission. Native schema 9 also enforces `UNIQUE (deployment_namespace,event_id)`, so four attachments sharing one canonical user event would fail even after the interface mismatch were fixed. This constraint must remain effective for the Worker lane.

AGUI run commands are execution triggers over admitted input; their official validated message models do not establish an independent native attachment storage admission. Raw custom `attachments` must neither be silently ignored nor become another ungoverned bytes source.

## Authority and immutable contract

Add a small typed Core input batch contract containing:

- Verified-transport-derived current `HostContextEnvelope`, authority issuer, and expected Task binding digest. The HTTP adapter constructs this only after validating an actual `VerifiedHostGrant`; clients cannot supply this structure.
- The exact target user/clarification event identity and sequence, plus ordered prepared attachment references and immutable object receipts.
- Each reference binds attachment ID, owning message event, safe filename, MIME, size, SHA-256, and the existing document/image provenance fields. Attachment IDs remain server-generated native IDs.

The actual deployed verification authority is `PostgresHostGrantRequestAuthorizer.authorize` in API `host_auth.py`: bounded unverified hints select an active `HostRegistryRecord`; `PyJwtHostGrantDecoder` verifies the JWT signature using `CachingJwksKeyResolver`; `HostGrantVerifier` checks allowed algorithm, claims, audience/issuer, origin, scopes and resources. `PostgresHostAuthorityStore.consume_grant` then SHARE-locks the registry, compares the complete record used for verification, checks `active`, algorithm and PostgreSQL clock expiry, atomically consumes the jti in `host_grant_replay_ledger`, and records accepted evidence in `host_grant_audit`. Only its committed accepted result reaches the HTTP adapter.

Extend the secret-free verified result with a typed consumed-grant evidence record: accepted audit/ledger association, SHA-256 of the verified bearer (already calculated as `HostGrantAttempt.grant_digest`), algorithm, exact expiry, authority issuer, Host namespace/app, policy_version, and a canonical digest of the complete trusted registry snapshot (issuer, audience, JWKS URI, allowed origins, algorithms, policy_version, active). The deployed registry has no monotonic revision column; the content digest is the trust-policy revision for this patch, not an invented SQL counter. Preserve the distinction between the bearer digest and `host_context_digest`, which hashes normalized context and is not signature proof. No bearer, private key or credentials are stored in the input proof.

Before object I/O, require an actual `VerifiedHostGrant` plus this consumed evidence, `agent.run`, fresh expiry and exact Task identity/binding. Initial admission uses the binding frozen in the same Task admission. Follow-up uses fresh native Task lineage and binding. Inside the final transaction, recheck the accepted audit/ledger association against the proof, exact registry policy snapshot and `active` under a SHARE lock, expiry using `clock_timestamp()`, and current Task binding digest under its native lock. The input metadata stores the verified grant digest/expiry/trust-policy digest/accepted audit association alongside Task binding digest and issuer. This is an explicit HTTP authority proof, never Worker lease evidence.

Signature verification linearizes at the native decoder/verifier call; accepted one-time grant consumption linearizes at the native replay-ledger commit. Canonical input admission linearizes at the final transaction commit, with registry/Task locks held until that commit and DB clock checked immediately before mutation. Registry disable/policy change committed before the final lock is rejected; a concurrent change waits until the admission transaction completes. Expiry is checked at the final mutation boundary, not guaranteed to precede wall-clock commit acknowledgement after arbitrary network delay. No model execution is dispatched until canonical admission commits and the native execution command is separately accepted.

There is no deployed per-token revocation list and no SQL signature re-verification. The JWKS resolver caches keys for 300 seconds; removal of an upstream JWKS key is not immediately observable during that cache window or between signature verification and commit. This patch must not claim instantaneous key revocation. Immediate revocation available to this ingress is the native registry active/policy transition checked under the final lock. ERP user/company permission is rechecked by the Host when issuing the current grant; Cloud cannot infer a later ERP permission change from SQL. These existing temporal boundaries are recorded honestly, and a future stricter revocation contract would require an explicit native authority extension.

Object storage remains the existing immutable S3 object store, not local disk or a new upload service. `put_if_absent` verifies the supplied digest and size; the resulting receipt must exactly match namespace, artifact ID, digest and byte count. If a provider ACK is lost, recover only via the existing verified object expectation/version contract. Never delete an object just because an ACK or transaction result is unknown.

No raw file body is added to canonical event payloads, command events, public recovery SSE, idempotency response bodies, or browser resource metadata. Canonical user events carry only native refs.

## Dedicated ERP database is a release prerequisite

Read-only inventory by the parent confirms ERP Cloud and Trench Cloud currently use the same PostgreSQL target and role. Namespace isolation does not isolate `zebra_schema_migrations`; applying106 there would modify shared schema and could make unchanged Trench105 fail its freshness guard on restart. **No shared-database DDL or schema-version spoofing is permitted.**

Before native106 release, create a dedicated ERP Cloud database and role and transfer the existing ERP105 namespace state under a reviewed operator procedure. Stop only ERP API/Worker for a consistent snapshot, retain exact original database/rows, and preserve all existing ERP Task/Run/event/grant/profile identities. Parent inventory found139 public tables:132 deployment_namespace-scoped, six definition/release tables scoped by namespace_id plus authority_issuer, and the schema migration ledger. Parent will verify the actual ERP namespace closure (including history/continuation) before export. Its proposed procedure copies schema pre-data, selected namespace rows plus all migration ledger rows, then post-data constraints/indexes; validates all foreign keys without disabling replication triggers; and compares destination counts/digests while proving no other tenant namespaces were copied.

Migration106 and both patched images point exclusively at that new dedicated database/role. Namespace selection/export, credential configuration, backup, cutover and rollback are the parent's separately reviewed operator work. Until those checks pass, this patch remains source-prepared and is not deployable. Shared Trench keeps its database/schema105 and original services unchanged.

## Separate schema lane without weakening generated output fencing

Add migration 106 only to the dedicated ERP database copied from deployed105, named `http_input_attachment_admission`. Do not edit the existing migration 9 checksum.

The migration adds an explicit authority discriminator with default `worker` for all existing rows, plus HTTP input proof fields (frozen Task binding digest, authority issuer, verified grant digest/expiry, accepted grant audit association, and trust-policy snapshot digest). Worker lease columns become nullable only under a new complete disjoint CHECK:

- `worker`: all current epoch/fencing-token/owner values remain required, HTTP proof fields are null. Existing Worker reserve/record/finalize/compensate behavior and lease checks remain unchanged.
- `http_input`: all Worker lease fields must be null; HTTP proof fields and canonical user event binding are required. These rows enter already finalized with verified immutable object receipt and exact user-event binding. Their CHECK explicitly permits lifecycle `finalized`, `pruning`, and `pruned`, requires finalization/event/object evidence in all three states, and forbids `staged` or `compensated`; authorized retention management can therefore prune them. They cannot masquerade as staged Worker output.

Replace the global unique event constraint with a partial unique index on `(deployment_namespace,event_id)` where authority is `worker`. HTTP input allows at most four distinct artifact rows per admitted user event, enforced by the typed admission batch and transaction validation. Existing primary key and session/idempotency uniqueness remain. The existing generated-output unique-event rule is retained exactly by the worker-only partial unique index; it is not globally weakened. Every row still has the existing foreign keys to its native session stream and exact canonical event.

Worker mutation entrypoints continue to require the genuine Worker fence; add a lane check when locking a payload for Worker mutations so they cannot change HTTP admission proofs. Existing authorized retention pruning may handle HTTP rows only through its explicit management path. No fabricated reservation epochs, tokens, owner IDs, or administrative operator identities are allowed.

The captured deployed `artifact_payload_rows.artifact_payload_from_row` currently reconstructs reservation/object/event evidence without parsing lease columns. The captured `CloudArtifactPayloadRecord` likewise has no LeaseFence field; `LeaseFence` itself requires a real epoch, positive token and owner and must remain unchanged. Therefore nullable HTTP fence columns cannot merely flow through the old unlabelled reader:

- Add a typed `authority_kind` discriminator and optional typed HTTP proof to the Core read record, with a validator requiring the proof only for HTTP input. `ArtifactReserveRequest` stays the shared immutable payload coordinate shape and does not acquire any fabricated Worker fence.
- Make `artifact_payload_from_row` inspect the discriminator. For worker rows, validate the three existing fields with the unchanged `LeaseFence` model and reject HTTP proof. For HTTP rows, require all three lease fields null and validate complete HTTP proof plus finalized/pruning/pruned lifecycle. Missing/unknown discriminators in migrated real rows fail closed.
- Existing stored Worker rows receive explicit default worker origin through migration; API and Worker get the identical discriminator-aware Core record/parser overrides. `CloudArtifactPayloadReader` continues reading verified object versions through its existing record contract. It cannot misinterpret HTTP proof as a Worker reservation authority.
- Worker transition helpers reject HTTP rows even with a genuine Worker lease; the separate existing administrative retention path can transition finalized HTTP rows through pruning/pruned without overwriting their immutable HTTP proof. Add read-model tests for both lanes and every allowed/rejected lifecycle.


## Initial Task flow

1. Preserve parsing and model/document/image validation before admission. Reject absent or invalid verified Host authority before object I/O.
2. Build bootstrap events and derive the exact frozen binding once.
3. Prepare immutable native refs, stage objects, and attach refs to the existing bootstrap user event without writing canonical state.
4. Extend `TaskAdmissionRequest` with an optional typed input batch. Existing callers with no attachments remain unchanged.
5. Inside `PostgresTaskAdmissionTransaction.admit_in_transaction`, claim the existing canonical idempotency receipt, admit bootstrap events/projections/Task/binding, validate the batch against the exact admitted user event and current binding, and insert the finalized input metadata before commit. Any failure rolls back the whole admission.
6. Existing idempotent replay returns the original receipt and original refs, never another canonical Task or model run. Staged objects from a concurrent losing request may remain unreachable; see orphan semantics below.

## Follow-up, rollover and clarification flow

1. Propagate verified Host grant evidence and request idempotency from both Task and Session append routes to one shared Cloud append adapter. Claim/check the complete canonical request receipt before selecting a mutable target. Its immutable hash binds root Task, text, options, clarification identity and ordered attachment names/types/content digests. Same key and hash replays the exact original receipt; changed intent rejects.
2. For an active appendable segment, lock the native root Task then stream in the established order, choose and verify the active segment from that locked state, perform exact stream CAS, append the ref-bearing canonical event, update native projections/read state, insert finalized HTTP input rows and complete the replay receipt in one transaction. No post-commit receipt save is authoritative.
3. For a terminal source, extend the existing typed `SessionHandoffCommitRequest` with an optional prepared follow-up input batch and its canonical request/receipt coordinates. Reuse the native HandoffOperation's durable idempotency claim to retain the exact target identity. Stage objects against that stable target before final commit. Include the complete follow-up request hash in the immutable handoff intent so the same operation cannot mean different attachment/options content.
4. Compose the existing `commit_handoff_in_transaction` with the exact follow-up event, metadata, projections/read state and replay receipt **inside its same caller transaction**. Its existing child bootstrap, native active-segment mapping and `handoff_dispatch_outbox` insertion remain invisible until the attached human input and HTTP metadata are committed too. The existing API `_rollover()` followed by a separate `append_session_message()` is not used for this Cloud attached-follow-up path.
5. A crash after durable operation claim/object staging but before final commit leaves a recoverable pending operation and no active target/outbox/input. Retry resolves the same operation/target after fresh grant checks. A crash or lost ACK after final commit returns the stored complete receipt without another rollover, input event, outbox item, or dispatch. A committed old operation without the required atomic input receipt fails closed for explicit reconciliation; do not silently reinterpret it or replay original business Runs.
6. Two concurrent terminal follow-ups serialize on the root Task and operation/input receipt. After the winner creates an active human turn, a distinct request cannot append another conflicting turn or manufacture another rollover from stale terminal state: reject with native pending-turn/revision conflict and no dispatch. Same-key concurrent calls replay the one original receipt. Same-key changed content rejects even if the active segment moved.
7. No model command or handoff delivery may dispatch from a target lacking its committed canonical input rows. Preserve original Task/Run/events and completed source state. No-attachment local SQLite compatibility remains unchanged; Cloud follow-up authorization/idempotency must still use one coherent admission boundary.


## AGUI policy

ERP sends files through initial Task or message admission exactly once. AGUI run/resume consumes the established canonical input and does not receive another raw attachment body. Any independent attachment-shaped AGUI intent must produce a clear bounded rejection unless it explicitly matches canonical admitted refs under the same Task; never silently drop it or dispatch a second intake. This includes direct AGUI commands and queued message commands: either support their typed admitted-ref association or reject their attachment field before acceptance. No command may claim attachments that Worker recovery cannot read.

## Expected implementation files

New files, mirrored under `overrides/` only after review:

- `packages/agent-core/src/agent_core/domain/http_input_attachments.py`: typed consumed-grant proof, immutable prepared batch, and exact reference/receipt validation.
- `packages/agent-storage/src/agent_storage/postgres/http_input_attachments.py`: verified immutable object preparation and transaction-only metadata/append helpers, using existing task binding, CAS, event and projection helpers.
- `packages/agent-storage/src/agent_storage/postgres/http_input_attachment_migration.py`: deployed-baseline migration 106.
- `apps/api/src/zebra_agent_api/http_input_attachments.py`: verified-grant adapter and canonical attachment preparation/shared append composition.
- Focused deterministic tests plus review/runbook notes.

Existing deployed files expected to change:

- Core `domain/cloud_artifact_payloads.py`, `domain/cloud_artifact_requests.py` only if needed for the shared tagged read proof; `ports/task_admission_transaction.py` and `ports/session_handoff.py`: typed atomic input batch contracts. `domain/leases.py` remains unchanged.
- Storage `postgres/task_admission.py`, `postgres/session_handoff_transactions.py` and its adapter `postgres/session_handoffs.py`: atomic initial/input and rollover/input hooks; preserve operation target and no early outbox dispatch.
- Storage `postgres/artifact_payload_rows.py`: strict discriminator-aware parser shared by API/Worker.
- `agent-storage/postgres/migration_catalog_tail.py`: register only new106 atop deployed105.
- `agent-storage/postgres/artifact_payload_transaction_support.py`: preserve Worker-only mutation lane.
- `agent-storage/postgres_composition.py`: explicit HTTP input object writer composition; ordinary reader stays unchanged.
- API `session_queue.py`, `session_attachment_persistence.py`, `app.py`: route Cloud input to typed admission; keep local helper separate.
- API `task_routes.py`, `task_api.py`, `task_session_api.py`, `routes.py`: propagate verified authority/idempotency to the shared append path, including rollover.
- Security `host_grant.py` plus API `host_auth.py`: carry the actual consumed secret-free grant evidence and exact registry trust-policy snapshot after native signature verification and jti acceptance.
- API `session_handoff.py`: prepare typed exact follow-up intent/target and compose the atomic native commit instead of separate rollover/append.
- API `ag_ui_command.py` and command submission adapter only as needed to fail closed on independent unsupported attachment fields.

No dirty mainline checkout edits, shared Trench service changes, model calls, or business writes are part of this patch preparation.

## Checks required before any release

Use assert-based deterministic tests and existing native fixtures where available; no new framework or dependencies:

- Initial Task accepts one and four real immutable payloads; document/image provenance survives into refs and Worker read recovery.
- One exact canonical event and its up-to-four metadata rows commit atomically with Task binding/projections/idempotency.
- Follow-up/clarification uses the shared transaction; terminal rollover atomically attaches to the chosen child. Inject crash after operation claim, object staging, child bootstrap and before input/outbox commit; verify no early dispatch and exact recovery. Test two concurrent terminal follow-ups (same key and distinct keys), lost ACK, no duplicate rollover/input/outbox/dispatch, and unchanged original Runs.
- Same key retries return original refs; different body/name/MIME/order/options fails. Inject lost ACK after DB commit and prove no duplicate event or dispatch.
- Wrong namespace/principal/workspace/thread/issuer/binding, inactive or changed registry policy, invalid consumed-grant evidence, expired grant, stale stream revision and wrong lineage reject. Race registry disable/policy changes and expiry during staging against final lock/commit. Separately test native JWT rejection and disclose300s JWKS cache and no per-token revocation contract; never call a SQL identity check signature/revocation validation.
- Provider failure leaves no canonical input refs; unknown put/commit outcome never causes unsafe deletion.
- Receipt digest/size/version mismatch, cross-session refs, >4 batch, duplicate artifact ID and non-user input event reject.
- Worker generated-output reserve/finalize still rejects fake/stale leases and cannot mutate HTTP proofs. Partial unique index still rejects two Worker output rows for one event, while permitting four HTTP input rows.
- API/Worker compose the same tagged read record/parser and dedicated-DB106 catalog; disposable PostgreSQL proves105->106 constraints, worker-only uniqueness, four-file HTTP input, and finalized->pruning->pruned HTTP retention. Both read input objects through the existing verified Cloud reader. Shared105 Trench compatibility is proved by leaving its schema/catalog untouched.
- AGUI/queued commands do not accept then discard independent raw attachments.

Compilation/static checks alone do not establish PostgreSQL/S3 acceptance; mocked transaction tests alone do not prove actual migration constraints. These evidence boundaries must remain explicit.

## Image build and release boundary

After reviewed source and tests, prepare two minimal Dockerfiles that extend the exact captured API and Worker base image identities and COPY only reviewed overrides. Both images need identical shared Core/storage106 catalog and reader-compatible input metadata semantics, even if Worker execution sources do not change. Do not rebuild from local main107 or copy its full apps/packages trees.

Dedicated ERP database isolation and identity-preserving105 state-transfer verification are mandatory first. Migration106 runs only in that new database before patched API/Worker start; both freshness catalogs must agree. No106 is applied to the shared database. Back up and retain original isolated ERP configuration/database/object data and exact prior images. This plan does not authorize executing migration/deployment; root coordinates the user's existing release authorization and final gate separately. Shared Trench API/Worker remain untouched.

## Orphan and recovery semantics

Object put precedes canonical commit. A conflict, exception, process crash, or lost ACK can leave immutable objects without admitted metadata. Such objects are not readable through canonical Task resource or Worker attachment readers. They are deliberately not deleted inline because a competing admission or unknown commit may have bound them. Record stage identities for later audited reconciliation/retention; do not claim cleanup completed until that process has evidence. No original Task, Run, conversation or business operation is replayed to manufacture acceptance.

The failed ERP QA conversation `mngo4262kr` and its original dispatch coordinates must be preserved. Its `task_id=null` is an observed Host state, not proof that every native/object side effect is absent; investigate by the original idempotency key before any retry after repair.
