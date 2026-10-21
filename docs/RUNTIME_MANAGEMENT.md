# Runtime scoped management v1 — CA-P1-01A

Date: 2026-10-21. Owner: Luke Ding. Scope: a read-only management descriptor for
independent control planes. [Native OpenAPI](contracts/runtime-management-v1.openapi.json)
is owned by cloud-agent; consumers pin its source commit and SHA-256, not Python imports.

GET `/management/v1/target` is explicitly composed into `create_http_app`. It is
separate from HostGrant/task admission, the legacy operator token and `/health`.
The endpoint performs no Host/connector write, migration, deployment or business call.
Absent/invalid private configuration returns503 in local and cloud profiles alike.

## Credentials and expected identity

Set `ZEBRA_RUNTIME_MANAGEMENT_CONFIG` to an absolute, private regular JSON file
(max16KiB, mode0600/0400). Read it on every request; replace it atomically when
rotating, revoking or advancing the trust revision. Do not cache old credentials.
Use the same current configuration source across replicas; local copies alone do
not provide distributed revocation. Consumers must additionally fence observations
against the platform's shared current trust revision, rejecting stale replicas.

Example configuration (the digest is illustrative, not a usable credential):

```json
{
  "deploymentId": "runtime-a",
  "deploymentNamespace": "product-a-dev",
  "audience": "overdoze-management",
  "productId": "product-a",
  "environment": "dev",
  "trustRevision": 1,
  "credentialSha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "expiresAt": "2026-11-01T00:00:00Z",
  "actions": ["target.describe"]
}
```

The namespace must match the actual composition's deployment namespace (`local`
for a local profile). Deployment ID is explicitly assigned once per deployment,
shared by replicas; never generate it per Pod. Product/environment are opaque
scope identifiers for this trust binding, not a new business-user directory.

Provision an independent 256-bit random URL-safe credential with prefix`rtmg_`
and43following URL-safe characters. Store only its SHA-256 digest here; the
caller holds the secret in a mounted private file. Never reuse operator/management
user/Agent/HostGrant credentials. Scope/action are fixed in configuration; the
client cannot increase them with headers. Expired/removed/rotated credentials fail.
No IdP, browser Publishable Key or user refresh flow is introduced.

The request sends `Authorization: Bearer <opaque-credential>` and all of:
`X-Runtime-Deployment`, `X-Runtime-Audience`, `X-Runtime-Product`,
`X-Runtime-Environment`, `X-Runtime-Trust-Revision` matching the configured values.
Reject duplicate authorization/scope headers, query strings and request bodies.
Methods other than GET return405. Credentials and raw configuration errors never
appear in responses. Authentication is constant-time digest comparison.

## Descriptor and failure semantics

Return `runtime-management/1`, exact deployment/namespace/audience/scope/revision,
UTC observation time, actual API package version and the code's latest migration
number. `checks.database` and `checks.worker` remain`not_checked`;
Bundle management and native script ABI remain`unsupported` in this slice.
The code migration number is not evidence of an applied database migration.
A200 proves this credential/identity contract only, not readiness, effective
Release, Worker availability, capacity, business admission or storage HA.

All responses use `Cache-Control:no-store`. Errors contain only`error.code`:
400 INVALID_ARGUMENT;401 UNAUTHENTICATED;403 SCOPE_MISMATCH;
405 METHOD_NOT_ALLOWED;429 RATE_LIMITED with Retry-After:1;
503 MANAGEMENT_UNAVAILABLE. Do not map failure to anonymous capability discovery.

The API bounds file bytes and concurrent configuration reads (8per instance), with
a1second configuration caller budget and a0.2second empty-body check. Timed-out reads retain their slot until the actual thread
finishes, preventing retry-created unbounded background reads. File access is only
for local/projected regular configuration, not arbitrary request-selected paths.
Replica count multiplies the per-instance budget; this is not a global rate limiter.
Serve through a trusted HTTPS ingress and restrict management network reachability.
No performance/production HA target is claimed from these limits or unit tests.

## Compatibility and validation

The route/configuration are additive and disabled by default. No existing tables,
Host registry CLI semantics, user identity, Task admission, Coverage formats or
historical proofs change in this A slice. Subsequent [CA-P1-01B1 Host management](HOST_REGISTRY_MANAGEMENT.md)
adds a separate GET/PUT contract, independent credential and explicit v108/CAS/audit. Outbound connector
management is separately provided by [B2](CONNECTOR_MANAGEMENT.md). This read-only endpoint's credential must never authorize B1/B2 writes.

Focused tests cover actual HTTP composition, wrong tokens/scopes/expiry, strict
configuration, two apps sharing rotations and bounded timed-out reads. Full
`make test`/`make check` results are recorded with the task's delivery evidence,
separately from real Go/Python integration, production and fault/load acceptance.
[Final validation](evidence/ca-p1-01a/validation.json) records both completed gates,
skipped checks, the initial lazy-composition regression and the corrected rerun.

## CA-P2-01A offline Bundle validation

[Native Bundle v1](RUNTIME_BUNDLE.md) adds producer-owned schema/catalog and a
bounded offline validator. It does not add an HTTP action or widen rtmg_ credentials.
The descriptor still reports bundleManagement/nativeScriptAbi=unsupported; valid
declared configuration is not a stored/effective Bundle or Worker assembly proof.

## CA-P2-01C validation entry

[Scoped Bundle contract and validation](BUNDLE_MANAGEMENT.md) adds separately
authorized GET contract and pure POST native validation endpoints. Old artifacts,
Definition/Task formats and the existing target descriptor are unchanged.
Persistence/publication, Worker readiness and native scripts remain outside this
validation contract. The API-only settings path preserves the P2B baseline HMAC.
