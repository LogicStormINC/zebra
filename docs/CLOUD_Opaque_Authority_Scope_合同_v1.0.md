# Cloud Opaque Authority Scope 合同 v1.0

## 1. Purpose

This contract closes the cloud read-scope boundary needed by
`CLOUD-PROVIDER-CONT-PG-01` and `CLOUD-SESSION-HISTORY-PG-01`. It gives a
PostgreSQL composition a typed, fail-closed representation of the external
authority scope without creating a Zebra Tenant, User, Organization, or
membership domain.

The contract is an input boundary only. It does not select a backend, add a
database migration, or resolve external business membership.

## 2. Canonical identity

The durable external identity is the pair:

```text
(authority_issuer, namespace_id)
```

Both values are opaque strings supplied by the trusted Host/authority
composition. They must be non-blank, trimmed, and stable for the lifetime of a
request. `namespace_id` is not interpreted as a tenant, organization, user, or
subscription identifier.

The current PostgreSQL adapters use an injected `deployment_namespace` as the
internal storage key. Mapping the external pair to that key belongs to the
trusted composition boundary and is not inferred from a DSN, credential, or
database row by this contract.

## 3. Session allow-list

Read composition may carry an optional explicit `allowed_session_ids` tuple.

- `None` means the caller has authority for the complete external namespace;
  it is only valid when produced by trusted composition, never from an
  unverified request body.
- A non-empty tuple limits reads to those exact UUID session identities.
- An empty tuple is a valid deny-all scope and must return no session data.
- IDs are normalized to canonical lowercase UUID strings, deduplicated by
  rejection, and bounded at `MAX_HISTORY_SCOPE_SESSIONS` (20).
- A current Session ID is not implicitly added to the allow-list.

The allow-list is a read boundary, not a second source of Session authority.
Event and Projection stores remain the durable execution authorities.

## 4. Fail-closed invariants

Implementations must reject or deny when:

1. either identity value is blank or contains surrounding whitespace;
2. an allowed session ID is not a UUID or appears more than once;
3. a read asks for a Session outside the explicit allow-list;
4. a namespace mapping is missing or mismatched;
5. a caller attempts to derive namespace or issuer from the database DSN;
6. a storage adapter silently falls back to an unscoped query.

No `Tenant` model, membership lookup, business RBAC, or cross-namespace fallback
may be added to satisfy this contract.

## 5. Ownership and sequencing

`CLOUD-SCOPE-CON-01` owns only the Core value object, normalization tests and
this contract. It does not implement PostgreSQL Session History or Provider
Continuation storage. Those adapters consume the value after this contract is
reviewed and explicitly activated.

The next legal implementation candidates are:

```text
CLOUD-SCOPE-CON-01
├── CLOUD-PROVIDER-CONT-PG-01
└── CLOUD-SESSION-HISTORY-PG-01
```

Neither successor may activate runtime backend selection or introduce a Zebra
Tenant domain. `CLOUD-CONTROL-PLANE-PG-01` remains the final composition gate.
