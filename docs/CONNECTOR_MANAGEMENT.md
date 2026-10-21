# Native outbound Host connector management v1

2026-10-21; CA-P1-01B2; owner Luke Ding.
[Native OpenAPI](contracts/host-connector-management-v1.openapi.json) ·
[design](superpowers/specs/2026-10-21-connector-management-design.md) ·
[plan](superpowers/plans/2026-10-21-connector-management.md).

This interface publishes an operator-approved immutable connector Profile and changes its
Host/namespace Binding through CAS. It reuses the native connector registry and B1 current
Host approval; it does not replace Task/manifest/Coverage authority or implement Go orchestration.
[Inbound Host trust](HOST_REGISTRY_MANAGEMENT.md) remains a separate operation.

## Configuration and permissions

Use the same optional `ZEBRA_HOST_REGISTRY_MANAGEMENT_CONFIG`, scoped `rthm_` service credential,
private regular0400/0600 file and explicit native approval operator as B1. Add `connectorProfile`
and grant only the required `connector.read`/`connector.write` actions. Existing B1-only files
remain valid with the same fingerprint and gain no connector authority. No new end-user token:
Agent developers still use identity_key/access_token/refresh_token.

The optional template is camelCase, all fields required; nullable fields must explicitly be null:

```json
{
  "connectorProfile": {
    "hostAppId": "host-a",
    "connectorId": "connector-a",
    "profileRevision": 1,
    "baseUri": "https://host.example",
    "manifestPath": "/tools/manifest",
    "invokePathTemplate": "/tools/invoke",
    "reconcilePathTemplate": "/tools/reconcile",
    "supportedProtocolVersions": ["host-tools/v1"],
    "workloadIdentityRef": "workload-a",
    "credentialRef": "credential-a",
    "networkPolicyRef": "network-a",
    "manifestBindingPolicy": "declared",
    "status": "published"
  }
}
```

This fragment supplements the full B1 file, including its required registry template and scope.
The Profile Host must equal that approved Host. Only references are accepted, not resolved credentials.
New templates require a strict positive safe integer revision, published status, and explicit declared/legacy
manifest policy; bare HTTPS origin has no credentials/path prefix/query/fragment. Paths use the native
static-path contract. Text/versions are bounded and strict; no request-selected URL/secret/scope.
These checks do not prove DNS/egress policy, credential-resolver readiness, Host protocol support or connectivity.
Historical nullable-policy Profile models/digests/readers remain unchanged.

Updating actions/template/credentials/expiry advances the same Host trustRevision and canonical configuration
fingerprint, approved explicitly with the existing tool:

```sh
uv run python -m zebra_agent_api.host_registry_admin \
  --deployment-namespace product-a-dev --expected-revision 1
```

The example requires the private file to contain trustRevision2, configured native database and future expiry.
No approval or DDL runs on service startup. The approval binds deployment/product/environment/Host/namespace
and is checked in the same transaction as each operation. Empty actions revokes this shared management channel;
removing only connector actions preserves explicitly granted B1 actions after compatible replicas load the new config.
An approval change fences old B1 AND B2 file replicas together. Coordinate files/replicas; no zero-interruption claim.

## HTTP and unknown results

GET/PUT `/management/v1/host-connector`, `host-connector-management/1`.
Use the existing five single exact-match X-Runtime deployment/audience/product/environment/trust-revision headers
and independent service Bearer. Query/cookies/duplicate credentials/scope headers rejected. GET has no body.
PUT Content-Type:application/json requires exactly:

```json
{"expectedRevision": 0, "operationId": "7dd8c389-67d8-4643-a1e4-a0cf57d5a8a9", "active": true}
```

GET exposes actual `binding` (including inactive), actual pinned `profile`, configured `approvedProfile`,
current `revision` and `replayed:false`, with contractVersion. No binding means binding/profile null and revision0;
GET does not publish or repoint anything. Profile descriptors include profileDigest; historical null policy is explicit
on this management wire while its original native digest remains unchanged. A missing actual profile fails503.

active=true publishes only the approved immutable Profile and atomically CAS-binds its exact revision;
existing same key/full model/digest is idempotent, conflicting content gets409. expected0 creates an absent binding.
active=false requires a current binding and expected revision, increments Binding revision and disables it;
it neither publishes the new desired Profile nor repoints to it. A later approved active=true may explicitly reactivate.
A desired Profile2 plus current Profile1 remains visibly different until a successful activating apply.

Successful Profile publication, Binding change, receipt and audit commit together. A stale CAS/freeze conflict
or failed receipt/audit rolls back all newly attempted effects. Separate B2 receipts allow the same UUID in B1
without mixing operation meanings. Identical request under unchanged current approval returns its ORIGINAL snapshot
with replayed=true; it is not current state. Reusing an operation with different payload returns409.

503 can mean an unconfirmed COMMIT whose effect already happened. Authenticate currently, then replay the exact
operation under the same approval or GET current state; never create a new operation and retry blindly.
After trust rotation, old receipt fingerprint is not replayable with the new config; current GET reconciles.
Audit contains IDs/revisions/fingerprints and active state, no raw credential, JWT or secret material.

Errors/no-store match B1:400 invalid;401 credential;403 scope/action/expiry;409 CAS/immutability/receipt/freeze;
429 rate limited withRetry-After1;503 unavailable/unknown. Handler unsupported methods405 Allow:GET,PUT.
Global full-app browser CORS preflight is transport-only200/400 outside the handler; it returns no registry facts.
This is a server-to-server management API, not an anonymous browser-facing endpoint.

## Existing writers, frozen history and limits

Profile publication by BOTH native operator and management API uses the existing manifest-revision advisory lock.
A legacy freeze lacks Host identity: publication is permitted only when a preexisting unique same-Host Profile
already proves ownership. No-owner/ambiguous/different-owner legacy data remains readable by its historical digest
but cannot silently become newly attributed by publishing a Profile. v107 Host-scoped freezes remain independently
scoped and need no cross-Host merge. No manifest is fetched, replaced or regenerated by this management API.

The shared native bind now enforces the supplied expected-current binding_revision. Creation takes1; after current1,
input1 returns2, and stale input1 thereafter fails. Native bind still rejects an inactive Binding. B2 explicitly
supports reactivation using current CAS. Existing valid callers retain their behavior; callers which supplied a desired
next revision instead of the expected current revision must be corrected before upgrade. Both insert/update paths
have database atomicity across processes, with no process-local lock serving as authority.

API locks current native Host approval first, then the manifest revision, Profile and Binding as needed;
there is no external HTTP or secret resolution under locks. Current expiry is checked after row waits and at final
validation; native Task I/O deadlines include transaction exit. Each endpoint8slots (B1+B2 combined16/instance),
body/config16KiB, body0.2s, caller5s after body, DB maximum2s intersected with request/credential deadline.
Timed-out/cancelled workers retain their slot until completion. No application retry; replica count multiplies budgets.
No performance, storageHA or full cloud-readiness claim follows from these limits.

Binding disable affects current resolve_binding lookup. Existing explicit legacy/fallback policy stays in force;
this action does not globally revoke an immutable Profile or cancel running Tasks/streams. Old Task/manifest/Coverage
bytes and recovery references remain intact. Live Profile deprecate/revoke policy is a later independent lifecycle task.

## Upgrade and evidence

v109 adds only B2 receipt/audit tables; Profile/Binding/frozen history is not migrated or rewritten.
Apply explicitly in an authorized environment and coordinate compatible API/Worker and ALL native registry writers
before enabling B2. Native schema startup checks require the exact catalog; an old v108 binary is not an automatic
rollback target. Old publication/CAS writers must not continue concurrently with these stronger guarantees.
Feature rollback closes B2 on a v109-compatible binary, retaining configuration/schema/history/receipts.
New private-file fields on old parsers fail closed, never grant automatic permission.

[Validation](evidence/ca-p1-01b2/validation.json) separates frozen-source native gates, actual owned-PG/HTTP/process,
legacy/native regressions and S3-dependent skips. No production database, service or migration is operated here.
Neither management metadata tests nor a committed binding proves real business IdP, Go controller, model/Task,
Host network/credentials, browser, load or storage failover acceptance.
