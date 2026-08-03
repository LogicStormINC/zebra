# Cloud Provider Continuation PostgreSQL Plan

> Task: `CLOUD-PROVIDER-CONT-PG-PLAN-01`
> Status: `Planning`
> Owner: `lukeding (Cloud Architecture Maintainer)`
> Branch: `docs/cloud-provider-cont-pg-plan`
> Baseline: `zebra-cloud-trench@03efa4f5`
> Scope: architecture and governance only; no production code or migration

## 1. Decision

Create a docs-only planning gate before activating
`CLOUD-PROVIDER-CONT-PG-01`. The implementation card remains `Locked` until
this plan is reviewed and all authority, transaction, lifecycle and management
semantics below are accepted.

This is the next cloud-mainline action because Provider Continuation is the
remaining authority gap before complete PostgreSQL `ControlPlaneStores`
composition. Planning the broader composition first would leave its write
boundary undefined.

## 2. Current State And Problem

The current local contract and SQLite adapter:

- use caller-supplied `tenant_id`, with Worker callers passing `"local"`;
- persist opaque payload before the selection Event is appended;
- do not validate `WorkerMutationAuthority` or the active Lease fence;
- expose an unscoped `sweep_expired()` management operation;
- use `artifact_id` for the Zebra durable row and `reference_id` for the opaque
  provider handle;
- already enforce bounded TTL, payload SHA-256, soft delete and
  provider/model/capability compatibility.

The cloud design must preserve the useful compatibility semantics without
promoting `tenant_id`, provider state or SQLite into cloud authority.

## 3. Authority And Identity

### 3.1 External authority

The immutable external permission identity is:

```text
(authority_issuer, namespace_id)
```

It comes from `OpaqueAuthorityScope`. Zebra must not infer it from a DSN or
reconstruct Tenant, Organization, Workspace, Account or User membership.

Trusted composition validates the external scope and maps it to one internal
`deployment_namespace`. Storage never guesses or changes that mapping.

### 3.2 Resource identity

The logical cloud resource identity is:

```text
(authority_issuer, namespace_id, continuation_id)
```

`continuation_id` is Zebra's durable continuation resource identifier. During
implementation review it must be mapped explicitly to the current
`ProviderContinuationArtifact.artifact_id`; it is not the provider's opaque
`ProviderContinuationRef.reference_id`.

The PostgreSQL physical key remains consistent with existing aggregates:

```text
PRIMARY KEY (deployment_namespace, continuation_id)
```

The row also persists `authority_issuer` and `namespace_id`, with a uniqueness
constraint over `(authority_issuer, namespace_id, continuation_id)`. Every read
and write checks both the internal partition and the persisted external identity
so a composition mapping error fails closed rather than crossing namespaces.

## 4. Mutation Authority And Fence

Provider Continuation must not introduce a second `continuation_fence_token`.
Every Worker mutation reuses the existing `WorkerMutationAuthority` and its
complete `LeaseFence`.

Inside the same PostgreSQL transaction, the adapter validates:

- canonical `deployment_namespace` and exact `session_id`;
- `expected_stream_revision` against the locked Session stream;
- current Lease owner and Lease identity;
- current Lease epoch and fencing token;
- database-time Lease expiry.

Stale, expired, foreign-namespace or wrong-Session authority is rejected before
any continuation row or Event is changed. Last-write-wins behavior is forbidden.
Administrative lifecycle operations use `AdministrativeMutationCAS` plus an
explicit management scope; they never synthesize Worker authority.

## 5. Transaction Boundary

PostgreSQL stores the continuation bytes, metadata and canonical selection Event
in one database, so they must share one transaction and one lock order:

```text
BEGIN
  lock and validate current Lease fence
  lock and validate Session stream revision
  validate external authority mapping
  reserve or mutate the scoped continuation row
  append the canonical Event at the expected sequence
  bind the row to the committed Event id and sequence
COMMIT
```

The transaction returns the canonical stored Event and continuation receipt.
Lost-response retry must return that canonical result after matching the same
idempotency key and request digest; it must not create a second row or Event.

The following flows are forbidden:

- payload commit followed by a separate Event append;
- Event append that references an absent or uncommitted continuation;
- external provider I/O inside the transaction;
- a second Session/Projection save after the aggregate commit.

Opaque payload export occurs before the transaction. Failure before commit has
no durable effect; commit uncertainty is resolved by idempotent read-back.

## 6. Proposed Persistence Contract

The implementation card may refine names, but not the following semantics.

Required identity and scope fields:

- `deployment_namespace`, `authority_issuer`, `namespace_id`;
- `continuation_id`, `session_id`, provider `reference_id`;
- `provider`, `model_name`, `capability_version`.

Required integrity and lifecycle fields:

- opaque payload bytes, `payload_sha256`, `size_bytes`;
- `source_hash`, `created_at`, `expires_at`, `deleted_at`;
- lifecycle revision or equivalent compare-and-swap value;
- committed Event id and Event sequence;
- idempotency key and canonical request digest;
- accepted Lease owner, epoch and fencing token as audit evidence.

Provider credentials, access tokens and replayable secrets are forbidden. The
opaque provider payload remains unreadable outside the scoped adapter contract.

## 7. TTL, SHA And Lifecycle

Cloud behavior preserves SQLite compatibility:

- every stored payload has a bounded `expires_at` derived from the smaller of
  provider expiry and configured maximum TTL;
- read rejects expired, soft-deleted, SHA-mismatched or incompatible rows;
- SHA-256 and byte size are verified on read and on idempotent retry;
- Worker deletion is a soft-delete transition and is fence validated;
- expiration does not rewrite or delete historical Events;
- hard delete is not a Worker operation.

The externally observable states are `active`, `expired` and `soft_deleted`.
Expiration is computed from database time; sweep may materialize cleanup state
but cannot make an expired payload readable again.

## 8. Event Reference Integrity

The canonical continuation-selection Event must contain a bounded Zebra
reference, not opaque bytes. At minimum it identifies:

- `continuation_id`;
- `authority_issuer` and `namespace_id`;
- provider/model/capability compatibility fields;
- `payload_sha256`;
- the existing selection mode and source hash when required for replay.

The Event envelope already supplies Event id, Session id, sequence, actor and
timestamp. Lease evidence belongs in the authoritative row/audit receipt unless
the existing Event contract explicitly requires it; the plan does not duplicate
the full `WorkerMutationAuthority` into every Event payload.

Within the committed transaction, every Event reference resolves to exactly one
scoped row with matching SHA. Soft-deleted and expired rows remain auditable even
when payload reads are denied.

## 9. Read And Recovery Rules

Recovery requires both trusted scope and exact Session membership. It validates:

- external authority identity and mapped `deployment_namespace`;
- `session_id` ownership;
- provider, model and capability version;
- active lifecycle and TTL;
- stored payload SHA and size.

Cross-namespace, cross-authority and cross-Session reads return no payload and
must be distinguishable in internal audit evidence from ordinary absence. The
public compatibility surface remains provider neutral.

## 10. Management Sweep

The current global `sweep_expired()` is not a cloud contract. Management sweep
requires an explicit scope:

```text
(authority_issuer, namespace_id, deployment_namespace)
```

An authority-wide batch may enumerate approved namespaces, but each database
mutation remains namespace-scoped. Sweep:

- uses database time and bounded batches;
- takes an administrative CAS/management authorization;
- records an append-only management audit receipt;
- is idempotent and safe under concurrent Worker reads/deletes;
- never changes historical Events or broad-deletes all tenant data.

Physical payload purge, retention duration and compliance erasure are separate
policy decisions. This card freezes only expiration and soft-delete management.

## 11. Implementation Split And Owned Paths

After this plan is `Done`, `CLOUD-PROVIDER-CONT-PG-01` may be activated with
these implementation lanes:

1. Core cloud mutation/read contract: add a focused cloud Port that requires
   authority; keep the local `ProviderContinuationStorePort` and SQLite adapter
   behavior-compatible rather than adding optional authority parameters.
2. PostgreSQL adapter and the next serialized migration: implement the physical
   key, constraints, transaction, idempotency and management audit contract.
3. Worker seam: replace store-before-Event with one injected aggregate commit
   path when the cloud profile is explicitly composed.
4. Real PostgreSQL tests: prove migration immutability, fence rejection,
   namespace isolation, atomic Event binding, lost-response retry, TTL/SHA,
   soft-delete and scoped sweep.

The implementation task must declare exact files and reserve the next migration
number only when it is activated. This planning card does not reserve a migration.

## 12. Unlock And Acceptance Gates

`CLOUD-PROVIDER-CONT-PG-01` remains `Locked` until all are true:

- this plan is reviewed and marked `Done`;
- the authority identity, physical key, fence, transaction and lifecycle rules
  above are accepted without open ambiguity;
- `CLOUD-AGG-FENCE-CON-01` and `CLOUD-SCOPE-CON-01` remain integrated `Done`
  dependencies;
- the next PostgreSQL migration number and ownership are re-audited;
- exact implementation Owned paths, human owner, branch and isolated worktree
  are registered;
- the expected Event type/payload change and local SQLite compatibility boundary
  are named before code changes.

Implementation acceptance must include:

- stale/expired/wrong-Session/wrong-namespace authority rejection;
- atomic rollback and no dangling Event references;
- canonical idempotent replay after a lost commit response;
- cross-process recovery and cross-authority denial;
- TTL, SHA, compatibility and soft-delete parity;
- management-scoped, audited and concurrent sweep;
- real PostgreSQL Compose evidence and migration checksum verification.

## 13. Mainline Order

The dependency order is:

```text
CLOUD-PROVIDER-CONT-PG-PLAN-01
  -> CLOUD-PROVIDER-CONT-PG-01
  -> CLOUD-CONTROL-PLANE-PG-01
  -> CLOUD-DELIVERY-TXN-PG-01
  -> CLOUD-AGG-FENCE-01
```

Completing this plan unlocks only review/activation of the Provider Continuation
implementation card. It does not activate later cards automatically.

## 14. Explicit Non-Goals

This planning slice does not modify or select:

- application or package production code;
- PostgreSQL schema or migration files;
- Runtime/backend selection or API/Worker composition;
- Provider HTTP adapters or external provider integration;
- Desktop or local SQLite behavior;
- Redis live fan-out, Mem0 or semantic-memory consumers;
- Docker application services, deployment or credentials;
- broader Control Plane, Delivery transaction or Trench/CopilotKit wiring.
