# Native Host registry management v1

Date2026-10-21; CA-P1-01B1, owner Luke Ding. [OpenAPI](contracts/host-registry-management-v1.openapi.json),
[design](superpowers/specs/2026-10-21-host-management-design.md),
[plan](superpowers/plans/2026-10-21-host-management.md).

This optional interface manages one operator-approved inbound Host trust binding.
It reuses the native HostRegistryRecord, PostgreSQL registry and current Host admission/replay checks.
Outbound connector profiles/bindings are separate; B1 does not implement their management.
Go must consume the published public contract, never access Runtime SQL or internal modules.

## Credential, scope and explicit preparation

Use an independent random256-bit `rthm_` credential followed by43URL-safe characters.
Only its SHA256 digest is stored in the private configuration. `rtmg_` target-description,
operator tokens, platform administrator and Agent access/refresh tokens cannot authenticate this route.
The native operator prepares configuration; this interface cannot approve its own credentials.

Set `ZEBRA_HOST_REGISTRY_MANAGEMENT_CONFIG` to an absolute regular JSON file,0400/0600,max16KiB.
All fields below are required; digest/deadline are illustrative. The registry template always has active=true;
HTTP PUT chooses true/false but cannot select a different Host, issuer, audience, JWKS or Origin.

```json
{
  "deploymentId": "runtime-a",
  "deploymentNamespace": "product-a-dev",
  "audience": "overdoze-management",
  "productId": "a",
  "environment": "dev",
  "trustRevision": 1,
  "credentialSha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "expiresAt": "2026-11-01T00:00:00Z",
  "actions": ["host-registry.read", "host-registry.write"],
  "registry": {
    "hostAppId": "host-a",
    "namespaceId": "tenant-a",
    "issuer": "https://broker.example",
    "audience": "runtime-agent-a",
    "jwksUri": "https://broker.example/.well-known/jwks.json",
    "allowedOrigins": ["https://business.example"],
    "algorithms": ["RS256"],
    "policyVersion": "v1",
    "active": true
  }
}
```

Prepare the native database with the EXISTING explicit migration command in an authorized environment;
B1 requires additive v108. Nothing migrates/approves on API startup. This document authorizes no production action.
Set the existing `ZEBRA_DATABASE_URL` and private config environment variables for the native operator tool:

```sh
uv run python -m zebra_agent_api.host_registry_admin \
  --deployment-namespace product-a-dev --expected-revision 0
```

Approval initializes revision1; subsequent approval requires configured trustRevision=expected+1.
The native key is deployment_namespace+host_app_id+namespace_id. Deployment identity, management audience,
product/environment and Host binding remain immutable for that key. Credential, registry template,
actions or expiry changes require a new revision and current approval; merely replacing files is insufficient.
The shared approval stores only canonical configuration fingerprint, binding/scope/revision and expiry.
Updating an approval fences all old-file replicas, even if their old credentials remain unexpired.
To revoke management access, approve the next config with actions=[]; the parser/operator explicitly permit this.
This revokes management authority, not existing Host admission. Apply active=false to disable the Host itself.

## HTTP and reconciliation

GET/PUT `/management/v1/host-registry`, contract `host-registry-management/1`.
Use HTTPS ingress plus network restriction. Each request requires Bearer and single exact-match headers:
`X-Runtime-Deployment`, `X-Runtime-Audience`, `X-Runtime-Product`, `X-Runtime-Environment`,
`X-Runtime-Trust-Revision`. No query/cookies/duplicate headers. GET has no body.
PUT uses exactly Content-Type:application/json, a canonical UUID operationId and:

```json
{"expectedRevision": 0, "operationId": "7451420a-5d68-4482-94aa-de45b050206a", "active": true}
```

Expected0 creates absent registry; otherwise use the current GET revision. Successful apply increments revision;
active=false preserves the row and all grant/history evidence. active=true may explicitly reactivate it.
The response contains contractVersion, registry (camelCase fields above or null before creation), revision,
and replayed. Identical operation/payload returns the original committed snapshot with replayed=true;
a changed payload or stale CAS gets409. Snapshot replay is not current state: GET reconciles current state.
Token/config approval must still be current before any receipt can be read.

Each receipt binds the native key, operationId, approved trust fingerprint/revision, expected registry revision
and applied template/active flag. Registry change, successful audit and receipt commit atomically.
Unconfirmed COMMIT/transport loss yields503; it does not mean no effect occurred. Reauthenticate currently,
then replay the identical operation or read current state; never invent a new operation and retry blindly.
After trust rotation, an old operation fingerprint cannot be replayed under the new configuration;
use current GET to reconcile before planning a new change.

Errors are sanitized error.code with no-store:400 INVALID_ARGUMENT;401 UNAUTHENTICATED;
403 SCOPE_MISMATCH/PERMISSION_DENIED;409 CONFLICT;429 RATE_LIMITED (Retry-After:1);
503 MANAGEMENT_UNAVAILABLE (including stale approval and uncertain outcome).
Unsupported handler methods405 with Allow:GET,PUT. The full app global CORS middleware
handles browser preflight (Origin plus Access-Control-Request-Method) before this handler,
returning200/400 without this contract/no-store headers. It returns no registry/authentication facts
and grants no credential authority. This server-to-server interface requires no browser CORS support. No DSN/file paths, credentials or signed grants in responses/audit.

## Consistency, capacity and upgrade

Approval/read/apply share a per-native-binding PostgreSQL advisory transaction lock before approval-row lock;
different Host bindings have independent locks. Current shared approval and database clock expiry are checked,
including after registry row-lock waits and before return/receipt/audit. Effective deadline is capped by expiry.
Legacy privileged registry upsert still works and advances registry revision, so stale API CAS fails.
Native Host consume_grant already locks/rechecks current active registry; disabling blocks later admission,
without cancelling already admitted Tasks or promising native push revocation.

Eight requests/instance, immediate429, request/config/body16KiB, body budget0.2s, caller5s after body.
The existing Task I/O boundary caps DB work at2s and intersects current request/credential deadlines,
including DNS, locks and transaction exit. No application retry, no external HTTP under locks.
Timed-out/cancelled thread work retains its slot until completion. Replica count multiplies per-instance budgets;
these are bounds, not measured throughput or storageHA claims.

Absent optional config fails closed503 without eagerly composing execution stores. Configured mode requires
PostgreSQL and an exact actual deployment namespace; no SQLite write fallback. No connection/DDL on route registration.
Existing read-only target.describe contract/credential remains unchanged.

Before enabling B1: apply v108 explicitly and upgrade ALL privileged registry writers to the revision-aware version.
Existing SQL readers ignore the additive column, but native startup schema validation requires
an exact catalog: an unmodified v107 binary can reject a v108 database. Do not treat additive DDL
as automatic mixed-binary rollout/rollback compatibility. Use binaries supporting v108 for admission/Workers
under their normal coordinated upgrade procedure. Older writer binaries do not advance revision, so mixed old/new writers are unsupported for CAS. Rollback closes this optional route and keeps schema/history; never drop management evidence or revert DB data.
A feature rollback closes B1 on a v108-compatible binary; it does not reconnect an old v107 binary.
Old writers must not resume concurrently with enabled B1. No automatic migration or deployment is performed here.

## Evidence boundary

[Validation](evidence/ca-p1-01b1/validation.json) records current source/gates and independently reviewed limits.
[Migration preservation](evidence/ca-p1-01b1/migration-preservation.json) seeds a v107 registry and
consumed grant, applies v108, and checks unchanged row/timestamps/ledger/audit plus continued replay rejection.
Tests use their own disposable PostgreSQL containers; no existing DSN or business data is consumed by the new tests.
Two independent store processes prove CAS/replay against shared storage; actual FastAPI transport tests use the same
real persistence. Neither is a complete business IdP/Go controller/connector/Task/model/UI or productionHA acceptance.
