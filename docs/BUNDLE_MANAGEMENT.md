# Scoped native Bundle contract and validation — CA-P2-01C

## Boundary and dependencies

CA-P2-01A owns immutable Bundle syntax, component closure and public artifacts.
CA-P2-01B owns approved assembly, v2 Definition/Task snapshots and compatible
Worker recovery. This prerequisite exposes their native validation semantics to
the Go control plane without requiring a Definition write to validate a draft.

| Operation | Result |
| --- | --- |
| GET `/management/v1/bundle-contract` | Native schema/catalog, exact supported subset and immutable contract digest. |
| POST `/management/v1/bundle-validation` | Validate one raw Bundle against the native contract and current private execution catalog; return a scoped receipt. |
| Store/publish Bundle, create Version/Release/Task | Unsupported by these credentials and endpoints. |
| Worker placement, provider call, script execution, deployment | Not performed. |

The previous `/management/v1/target` contract and its `bundleManagement=unsupported`
descriptor remain unchanged. That descriptor does not advertise this separate,
explicitly provisioned validation contract or imply Bundle persistence/publication.
Existing Host publishing remains separately authorized and revalidates approvals.

Public producer artifacts live in [bundle-validation-v1](contracts/bundle-validation-v1/):
`openapi.json`, `contract.json`, positive and negative vectors. The original
[Bundle v1 artifacts](contracts/runtime-bundle-v1/) remain byte-for-byte unchanged.
The schema alone does not enforce canonical hashes, closure or approval ceilings;
consumers must call native validation rather than replicate Python rules in Go.

## Operator configuration

These routes fail closed until the operator sets `ZEBRA_BUNDLE_MANAGEMENT_CONFIG`
to an absolute mounted private JSON file. GET does not need an execution catalog;
POST additionally needs `ZEBRA_RUNTIME_BUNDLE_CONFIG`, as described in
[Runtime assembly](RUNTIME_BUNDLE_ASSEMBLY.md).

The new credential is `rtbv_` followed by43 URL-safe characters, generated using
`secrets.token_urlsafe(32)`. Store only its SHA256 hex digest. It has no management
administrator, Host publisher, business-user or Agent execution authority. Old
`rtmg_`, `rthm_`, operator and Agent tokens cannot access these routes.

Example approval (all identifiers and digest here are illustrative):

```json
{
  "schema_version": "cloud-agent.bundle-management-approval/1",
  "scope": {
    "authority_issuer": "https://overdoze.example",
    "namespace_id": "tenant/example",
    "product_id": "product/example",
    "environment": "development",
    "target_id": "target/example",
    "deployment_id": "deployment/example"
  },
  "audience": "overdoze",
  "trust_revision": 1,
  "credential_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "expires_at": "2099-01-01T00:00:00Z",
  "actions": ["bundle.contract.read", "bundle.validate"]
}
```

The scope namespace must equal the actual composed deployment namespace (`local`
for local API composition). Full scope includes issuer, namespace and target;
matching only product/environment is insufficient. Identifiers follow Bundle v1.
Trust revision is an integer from1 through9007199254740991. Actions are unique,
explicit and nonempty; read does not imply validate. Expiry must be UTC endingZ.
Unknown/duplicate fields and malformed JSON fail closed.

Approval files must be regular, mode0400 or0600 and at most16KiB. The shared
execution catalog reader now also requires a private regular0400/0600 file and
at most256KiB; FIFO/device/directory files are refused without blocking. Existing
relative execution-catalog paths remain accepted. Operator-mounted paths never
come from public requests. Use an atomic file replacement when rotating approval.
No private approval, execution catalog or baseline key is returned by the HTTP API.

The new API-only management setting is excluded from the CA-P2-01B baseline HMAC.
Adding or rotating this path therefore does not make retained v2 workers
incompatible. All previously pinned setting fields retain their original bytes
and meaning; execution-setting or baseline-key changes still require a compatible
retained worker. No historical snapshot or stored proof is rewritten.

## Request and receipt flow

1. Go selects the exact registered target, expected full scope and current trust.
2. GET with the dedicated Bearer Token and the five scope headers below. Compare
   the returned full scope and trust with the target; pin `contractDigest`.
3. Freeze the intended draft revision and exact envelope input/digest in Go.
4. POST the raw envelope as `application/json`, adding the pinned
   `X-Runtime-Bundle-Contract` header. There is no wrapper and no operation ID.
5. Match the receipt's contract/input/scope/trust against the frozen intent and
   current target trust before recording validation evidence using Go CAS.
6. Future publication must independently validate current authority, assets and
   draft/Version/Release gates. A validation receipt cannot authorize publication.

Required single headers on both routes:

```text
Authorization: Bearer <dedicated rtbv_ credential>
X-Runtime-Deployment: <scope.deployment_id>
X-Runtime-Audience: <approval.audience>
X-Runtime-Product: <scope.product_id>
X-Runtime-Environment: <scope.environment>
X-Runtime-Trust-Revision: <approval.trust_revision>
```

GET returns `contractVersion=bundle-validation/1`, `contractDigest`, `contract`,
`scope`, `trustRevision` and `observedAt`. The static contract has its own
`contractDigest`, calculated over the entire static document except that field.
Scope/trust/time are transport metadata and are not part of the static pin.

POST checks strict native bytes/digest/closure/ABI, full scope, approved image,
baseline, provider, output schema and build-evidence references, then constructs
the same strict `RuntimeAssembly` used by publication. Current executable subset:
approved OpenAI-compatible Chat, thinking `auto`, plain-text output, configurable
model/instructions and18 pinned domains. Strict Bundle v2 Coverage, unversioned
local Skills/MCP and unsupported adapters remain subject to P2B Worker refusal;
this endpoint does not inspect a future Definition's capabilities or run a Worker.

The receipt contains `contractVersion`, `contractDigest`, `bundleDigest`,
`assemblyDigest`, `approvalDigest`, full `scope`, `trustRevision`, `observedAt` and:

```json
{
  "checks": {
    "bundle": "passed",
    "assetApproval": "passed",
    "worker": "not_checked",
    "publication": "not_performed"
  }
}
```

`approvalDigest` hashes the resolved public execution catalog, excluding
`baseline_key`; it identifies that validation snapshot. It does not guarantee
that catalog remains current after the response. No provider secrets are present.
Private approval is read and authorized again immediately before response, and
must equal the initial approval including full scope, actions and expiry. A
rotation during validation refuses the stale result even if Token and headers
otherwise still match. There is no cached authority or mutable validation state.

## Capacity and failure contract

One shared limit allows at most8 in-flight calls per API instance across both
routes, covering body reception and configuration/validation work. Body reception
has a0.2s deadline and max256KiB; background work has a1s caller deadline. CPU/file
work runs off the event loop. A timeout or disconnect retains its slot until
the actual thread finishes; late exceptions are retrieved. There is no DB lock,
remote call, retry task or durable record in this protocol.

Only the declared method is allowed on each route. GET body, query parameters,
cookies, content encoding, duplicate security/framing headers and non-JSON POST
are refused. Every response is `Cache-Control: no-store`. Error bodies contain
only `{"error":{"code":"..."}}`, never raw validation errors or private paths.

| HTTP | Code | Consumer behavior |
| --- | --- | --- |
|400|INVALID_ARGUMENT|Fix framing/headers/body; do not retry unchanged.|
|401|UNAUTHENTICATED|Supply current dedicated credentials.|
|403|SCOPE_MISMATCH / PERMISSION_DENIED|Reconcile target scope/current authorization.|
|405|METHOD_NOT_ALLOWED|Use the route's declared method.|
|409|CONTRACT_MISMATCH|Fetch the native contract again and revalidate the draft.|
|422|BUNDLE_REJECTED|Fix native semantics or obtain explicit asset approval.|
|429|RATE_LIMITED|Honor `Retry-After: 1`; bound retries in the caller.|
|503|MANAGEMENT_UNAVAILABLE|Reconcile operator configuration; caller may retry with a bound.|

Repeated validation is safe because it writes nothing. This file-backed approval
is not a globally linearizable revocation service: replicas must receive the
operator's shared current approval, and Go must fence current target trust.
Per-instance limits multiply with replicas; no production QPS/HA claim is made.

## Verification and next dependency

[Evidence](evidence/ca-p2-01c/README.md) records producer vectors, independent
loopback subprocess HTTP, auth/scope/action/rotation/deadline/capacity negatives,
no-mutation checks, fixed old baseline digest, preserved Worker/Coverage and full
gates. Local HTTP acceptance does not prove production IdP, provider, OCI image,
Worker readiness or multi-replica deployment behavior.

Next is OD-P2-01A in Overdoze: pin this published producer commit/artifact digest,
implement Go draft/CAS/validation intent and consume the scoped native receipt.
OD-P2-01B then pairs the two services for behavior acceptance. CA-P3 native-script
runner, new independently configurable pinned domains, effective publishing and
deployment remain separate tasks. No production migration or deployment occurs.
