# Cloud MCP encrypted credential storage

Status: EXT-AUTH-01C through EXT-AUTH-01I implemented for review;
Worker activation and deployed end-to-end acceptance are not included.

## Boundary

- Core owns the binding, sealed value and storage Port. Security retains the
  existing import names and AES-GCM implementation. Storage does not import
  security or decrypt credentials.
- PostgreSQL v55 adds `mcp_credential_versions`. Stored secret fields are only
  nonce and authenticated ciphertext; master keys remain in SecretStore.
- Every query compares deployment, issuer, namespace, principal, workspace,
  connection and credential reference, in addition to a compact index digest.
  Reads return encrypted history, not use authorization.

## Transactions

Save locks the exact existing MCP configuration parent. Its current endpoint
and authentication mode must match the binding. The same lock serializes
credential creation/rotation with configuration updates. A foreign key prevents
orphan connection references. Credentials are created at revision 1; subsequent
saves append expected+1 and reject conflicting revisions. No UPDATE or DELETE
operation is exposed, and prior ciphertext versions remain retrievable.

Standalone ciphertext `save` does not change the parent configuration or authorize
the Agent. Management `publish` instead inserts a fresh credential reference at
revision 1 and updates the connection reference/authentication state in the same
transaction, guarded by its expected configuration revision. Failure rolls back
both records. It preserves enabled state and does not implicitly enable a connection.
The shared write path locks the parent alone, then reads its revision payload in
a fresh statement: a waiting joined lock query can otherwise retain stale data.

## Management authority

`McpCredentialManagement` requires an already verified Host grant with explicit
`extensions.manage`; subject and workspace come from that grant, not request data.
Read/run permission cannot provision or revoke. Bearer/API-key tokens are sealed
before storage and never returned; responses contain connection metadata only.
Each replacement gets a fresh reference. OAuth token injection is rejected pending
the dedicated authorization exchange. The HTTP composition must verify the grant
freshly before invoking this internal service.

Revoke increments the configuration revision, records revoked state and disables
the connection atomically. Historical ciphertext remains for controlled retention;
reading it is not authorization to use it. Provisioning after revoke does not
automatically re-enable the connection. `ready` means a credential was provisioned,
not that an upstream authentication probe succeeded.

## Validation and limitations

### Lease-fenced execution resolver (EXT-AUTH-01G)

`McpExecutionCredentialResolver` connects the existing lease store, fresh verified
grant provider and internal credential release to the per-frame HTTP resolver.
Trusted composition supplies recovered session/Turn/digest, connection, endpoint,
current lease fence and the policy-approved operation. JSON parameters are frozen
canonically; non-handshake frames must match both method and complete parameters.
Tools, resources and prompts map to their independent snapshot permission sets.
Credential release now requires an explicit target endpoint and compares it to
the frozen connection before reading ciphertext, preventing token relabeling.

Every frame checks the live lease before fetching authority and after credential
lookup; missing, expired, released, wrong-session or changed-fence leases fail
closed. PostgreSQL lease reads also join the current control-plane epoch. This
does not reserve a lease across a network operation or recall an in-flight call.
The synchronous resolver must run with HTTP on a blocking thread, not inside an
active async event loop. Credentials and request parameters remain absent from repr.

Effectful operations still use `FencedEffectToolGateway`, not a new MCP ledger.
Its shared execution path now rechecks ownership after loading claimed payload
and immediately before invoking the actual tool. Lease loss takes the existing
uncertain path; if the stale fence prevents that write, new-owner claim recovery
remains authoritative. No automatic no-effect retry is inferred from the failure.
Existing terminal-result replay semantics are retained.

These adapters are not yet wired into Broker routes or production Worker tool
selection. Live operation policy, trusted recovered-binding composition, MCP
catalog admission and deployed multi-service acceptance remain required.

### Per-frame HTTP credential seam (EXT-AUTH-01F)

`McpHttpSession` accepts an internal credential resolver. Each outbound frame,
including initialize and initialized notification, invokes it again with the
exact pinned endpoint and a separate decoded copy of the serialized frame.
The resolver must enforce live lease, operation policy, trusted digest and
credential authority; it returns an endpoint-bound Bearer credential only.
No arbitrary headers, environment mutation or cross-request credential cache
are introduced. Supplying both scoped resolver and environment credentials fails
closed, without falling back to a shared administrator credential.

The session validates exact endpoint equality, token size and visible ASCII
before sending. Callback mutation cannot change the already-serialized request
or pinned endpoint. Authorization failures and HTTP/socket diagnostics suppress
raw exception chains that could contain secrets. No request retry is added.
Existing no-resolver local transport behavior remains compatible.

The test composition connects internal release to the HTTP session and proves
that revocation between handshake and tools/call stops that frame. HTTP is
captured at the opener boundary in these tests, not a deployed remote MCP server.
Worker/lease/dispatch-ledger composition, durable outcome_unknown recording,
API-key header templates, cloud tool discovery and actual broker routes remain
pending. The resolver is not itself a lease verifier or an execution authority.
Final composition must run this synchronous session off the event loop and keep
authorization/transport deadlines bounded; no activation is made here.

### Internal runtime release (EXT-AUTH-01E)

The internal `McpCredentialRelease` service resolves the root Task authority,
checks a live `agent.run` grant against its exact principal/workspace binding and
loads the immutable snapshot at server-provided session/Turn/digest coordinates.
It verifies the returned coordinates/digest again and requires the requested
tool/resource/prompt in that connection's frozen permission ceiling.

The PostgreSQL use-read locks the connection parent, compares the entire current
configuration with the frozen one and reads the exact published reference at
credential revision 1 under the same lock. Disabled/non-ready, rotated, revoked
or changed connections fail closed. Management publication always uses a fresh
reference at revision 1; later standalone ciphertext history is never implicitly
selected as a runtime replacement. The service checks the complete returned
binding before decryption and checks grant expiry again after storage waits.

Release returns redacted `SecretMaterial` to internal Broker transport only.
There is no HTTP decrypt endpoint, model tool, Worker payload or UI response.
The trusted caller must obtain coordinates/digest from the validated execution
binding and enforce live execution lease, operation policy and egress policy.
No caller wiring is activated by this slice. Grant expiration here is not remote
OAuth token expiry; OAuth remains unsupported by release.

Revocation/use serialize at the parent lock: a revocation committed before the
use-read invalidates that read. A release authorized before revocation cannot be
recalled, nor can an already-dispatched remote request. Credentials must not be
cached by callers across operations; final transport composition must keep the
release-to-send interval bounded. This is not a claim of live Worker cancellation.

Tests run against disposable PostgreSQL schemas and real encryption with generated
fixture keys. They cover restart readback, immutable history, each identity field,
same IDs for two users, deployment isolation, concurrent CAS, parent absence,
endpoint/auth-mode mismatch, payload corruption and pre-I/O validation.

No existing service schema is migrated by this work. Deploying this code with
schema validation enabled requires the operator-controlled v55 migration first.
No API or unscoped ciphertext listing is added. Key management, trusted execution
binding/lease integration, OAuth refresh serialization/expiry, audit, final HTTP
transport composition and Trench Settings remain separate work. Successful
historical ciphertext read must never bypass runtime authorization. Internal
old-snapshot rejection tests do not establish deployed Worker/browser acceptance.

Related design: [Cloud extensions](cloud-skills-http-mcp-design.md).

### Protected credential management HTTP ingress (EXT-AUTH-01H)

The existing protected API accepts POST and DELETE at
`/v1/extensions/mcp-connections/{connection_id}/credentials` only when cloud
extension management is enabled and `create_http_app` receives an explicitly
composed `McpCredentialManagement`. Local and unconfigured instances return 404.
This is an adapter, not automatic production activation: trusted composition
must supply the intended PostgreSQL store, deployment namespace and SecretStore
backed protector. Browser input must never supply the encryption master key.

Both operations require a verified Host Grant with `extensions.manage` and one
strong quoted positive revision in `If-Match`. POST accepts only JSON
`{"token":"..."}` (maximum 8192 request bytes, no duplicate fields, nonempty
visible ASCII token); DELETE accepts no body. Query parameters and client scope
fields are rejected. Scope comes exclusively from the verified grant. No GET
endpoint exposes credentials. Responses contain public connection metadata,
`Cache-Control: no-store` and the new ETag, never token, ciphertext or credential
reference. Missing precondition is 428, stale revision 409, unknown scoped record
404, malformed input 422, oversized input 413 and storage/protection failure 503.
Storage errors are sanitized rather than forwarded to callers.

Host Grant Broker remains the authority exchange service, not a secret vault.
Its configured allowed scopes must explicitly admit `extensions.manage` for
management requests (`extensions.read` separately for listing). Default scopes
are not expanded: an ordinary execution grant cannot acquire management rights.
Provisioning does not enable a disabled connection. Revocation and ciphertext
publication reuse the existing atomic revision-CAS service. Worker dispatch,
Trench settings wiring and deployed browser
acceptance are separate outstanding work; these HTTP tests do not prove them.

### Operator-mounted master-key startup (EXT-AUTH-01I)

Automatic API composition is explicitly enabled by
`ZEBRA_CLOUD_MCP_CREDENTIALS_ENABLED=true`; it also requires cloud/production
profile and both cloud extension read/manage flags. The same resolved cloud
bundle supplies the control plane, extension metadata and ciphertext store DSN
and deployment namespace. Injecting a separate extension/control-plane store
while requesting automatic credentials is rejected. Advanced explicit service
injection remains caller-owned; it does not expand HTTP grant permissions.

Configure `ZEBRA_MCP_SECRET_ROOT` as an absolute, operator-controlled secret
mount, `ZEBRA_MCP_KEY_HANDLE` as its relative SecretStore handle and
`ZEBRA_MCP_KEY_VERSION` as the exact version. The existing LocalSecretStore
document format is `{ "version": "v1", "value": "<base64 32-byte key>" }`,
located at `<root>/<handle>.json`. This is a read-only mounted **master key**,
not a local user credential database. A secret manager or orchestrator should
supply the mount; the application neither generates nor writes it. No token
or master-key value belongs in environment examples, browser requests, Skill
packages, repositories or Agent sandboxes. Production mount provisioning and
secret-manager lifecycle remain operator responsibilities.

Startup checks exact key version, strict Base64/256-bit size, path containment
and no group/other file permissions (0400/0600). Missing/invalid keys stop startup
with a sanitized error. Use a read-only mount accessible only to the API process;
permissions of parent directories and prevention of mount replacement are the
operator's responsibility. Key readiness does not imply database writes are
healthy: schema admission remains mandatory and operation failures stay 503.

Disabled configuration performs no secret file I/O. Keys are not cached: rotation
uses a new immutable handle/version, preserves old documents for historical
decryptability and restarts API with the new active reference. Do not overwrite
an old handle in place. This composition does not activate Worker MCP tools,
provide OAuth exchange, or configure Trench settings automatically.

Validation: real PostgreSQL credential/extension matrix 61 passed; crypto 30
passed; default full suite 4022 passed / 841 skipped (eleven new DB cases passed
in the dedicated real run). make check passed: 885 typed sources, Eval 10/10.

EXT-AUTH-01D validation: expanded real matrix 73 passed; crypto 30 passed;
full default suite 4029 passed / 846 skipped in 129.50s. Five new DB tests ran
separately against disposable schemas. make check passed: 886 sources, Eval 10/10.

EXT-AUTH-01E validation: expanded matrix 122 passed (real PostgreSQL plus crypto);
final full 4044 passed / 850 skipped in 125.73s; make check passed (887 sources,
Eval 10/10). First full run had one real DeepSeek response-format failure;
isolated and full retries passed unchanged. See WORKLOG.md for original evidence.

EXT-AUTH-01F validation: 52 focused HTTP tests (15 new); full 4059 passed /
850 skipped in 129.37s; make check passed (888 sources, Eval 10/10). HTTP opener
capture proves frame behavior, not production Broker/Worker/remote acceptance.

EXT-AUTH-01G validation: focused 52 passed / 4 DB skipped; dedicated isolated
PostgreSQL matrix 44 passed including existing terminal dispatch replay. Final
full 4073 passed / 850 skipped in 128.59s; make check passed (889 sources,
Eval 10/10). No live schema migration or deployed Worker/Broker acceptance.

EXT-AUTH-01I validation: 98 focused passed / 2 DB skipped; isolated PostgreSQL
startup/HTTP/management matrix 54 passed. Normal app construction (no injected
credential service), restart/decrypt, foreign-user rejection and owner revoke
were verified. Full 4113 passed / 852 skipped in 122.86s; make check passed
(892 sources, Eval 10/10). No running service or master-key mount was configured.
