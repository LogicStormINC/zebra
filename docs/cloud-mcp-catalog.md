# Cloud MCP tool catalog persistence

## Remote SSE adapter acceptance update (2026-09-08)

The earlier fake-IP blocker below is resolved: one exact hostname exclusion in
Mihomo restored public DNS without disabling SSRF checks or global fake-IP.
Repository discover_mcp_tool_catalog negotiated 2024-11-05 and discovered fetch
in 1.71s. CloudMcpTransport then returned actual example.com documentation text
with isError=false (7.47s total). Probe scope and authority were fixtures; this
is real remote adapter evidence, not durable Worker or browser authorization.
An initial five-second discovery timeout occurred; default limits were retained.
No private endpoint path or credential was persisted. Runtime preflight gaps
below remain separate deployment/UI work.

## Live environment preflight (2026-09-08)

The running acceptance API/Worker are healthy but do not have extension/MCP
enable flags or an MCP key mount. Their actual PostgreSQL database is at v50;
extension_configurations and mcp_catalog_versions are absent. The active Trench
frontend settings do not yet expose Skill/MCP management. No live extension E2E
has run. Code/test completion must not be presented as runtime readiness.

Before live acceptance: deliver Trench settings/BFF; review and apply the current
migrations to the intended runtime database; rebuild/restart the matching API
and Worker with operator key/config; configure a real HTTP MCP target. Validate
normal chat alongside extension calls, cancellation, persistence and isolation.
The preflight made no database, container or secret changes.

## Worker catalog and frame-authority composition (EXT-MCP-WORKER-01)

`prepare_worker_mcp` consumes recovered Turn coordinates, current session/fence
and an explicit `WorkerMcpSource`. It loads only each pinned catalog digest and
revision in the recovered exact scope, then composes `CloudMcpTransport` with
the existing execution authority resolver. Each frame obtains Worker evidence;
none auth checks current config and lease, Bearer uses credential release.
Preparation does not rediscover remote tools. Missing source with nonempty MCP
selection fails instead of falling back to process MCP configuration.

This helper must be called only with a trusted recovered extension; it is not a
replacement for recovery verification or policy/effect admission. The default
Worker lifecycle now calls it behind the operator execution flag. Captured-network tests
cover pinned read, actual tools/call framing, no secret read for public MCP,
missing composition and stale fence. Real Trench E2E remains pending; no live
service or production credential changes were made.

Startup integration finding: the Worker does not provide `VerifiedHostGrant`
refresh; it uses `BoundHostExecutionAuthorityResolver` and
`ExecutionAuthoritySnapshot` revalidation. The helper now accepts
`McpWorkerAuthority(session_id, snapshot)` instead of an HTTP Grant provider.
Release reloads the authoritative Task ceiling for that session and verifies
binding digest, issuer/namespace, definition/policy digests, Agent execution
capability and expiry. Worker recovery and release share frozen principal and
workspace derivation. Existing HTTP Grant consumers retain their checks.

This internal evidence wrapper is not a token or a new authorization system.
Production composition must obtain the snapshot from existing attempt
revalidation, never reconstruct it from request data or extend its lifetime.
Default lifecycle/recovery/startup wiring is now implemented. The startup source
replays the current Turn's durable authority chain before each HTTP frame; closed
or mismatched Turns and absent/denied/expired evidence fail before transmission.
The existing pre-attempt revalidation remains the producer of that evidence.
Tests use the actual BoundHostExecutionAuthorityResolver with isolated fixtures,
not a deployed Worker. Replay currently reads session history per frame; profile
long sessions before adding an authority projection.

### Operator rollout

- Set `ZEBRA_CLOUD_MCP_WORKER_ENABLED=true` on API and Worker together. API also
  requires extension reads and `ZEBRA_CLOUD_EXTENSION_TURN_ADMISSION_ENABLED`;
  Worker requires PostgreSQL cloud mode and `ZEBRA_CLOUD_EXTENSION_WORKER_ENABLED`.
- Mount the same operator MCP encryption key using `ZEBRA_MCP_SECRET_ROOT`,
  `ZEBRA_MCP_KEY_HANDLE`, `ZEBRA_MCP_KEY_VERSION`. Shared startup validation rejects
  missing/insecure keys. Existing refresh/credential-management switches remain
  independent; this execution switch does not grant configuration management.
- Refresh enabled HTTP MCP connections first; admission selects the current
  user's stored catalogs, no client Task/Turn allowlist and no live discovery.
- The switch defaults off. With it on, even an empty selected catalog cannot
  fall back to process MCP/stdio settings. No local Agent behavior is changed.
- Before rollout completion, verify an actual conversation invoking a configured
  remote MCP, terminal persisted output, restart, cancellation and tenant isolation.
  Captured HTTP framing is not a substitute for that cross-service acceptance.

## Public MCP execution authority (EXT-MCP-AUTH-02)

Anonymous endpoints are not exempt from execution authorization. The internal
release service now shares snapshot authorization between credential release and
anonymous use: same live Host Grant, Task execution capability, exact scope,
Turn digest, operation name and endpoint. Snapshot authorization returns frozen
configuration only and is not itself a current-configuration check.

`McpExecutionCredentialResolver.authorize_anonymous` combines that check with
an exact live connection read and Worker lease/fence validation before and after
the read. Missing config authority, disabled/changed connections, stale scope or
lost leases reject the frame. This path never reads or decrypts credentials.
Bearer release continues to use the existing locked credential-use read.

Both hooks remain internal: production composition must supply trusted recovered
coordinates and a policy-approved operation. No public authorize/decrypt API or
default Worker activation is introduced. Cloud transport callback wiring and
recovery/startup remain necessary before live Agent/browser acceptance.

## Automatic Turn selection (EXT-MCP-ADMISSION-01)

`CloudExtensionTurnAdmission` optionally accepts the persisted catalog store.
With that composition, new Turns automatically select current-scope enabled
none/Bearer connections with usable authentication and matching current-revision
catalogs. Tool permissions are derived from stored catalog names, not request
payloads or user-written Task allowlists. Existing Turn bindings continue to
reuse their snapshot rather than silently selecting different tools on resume.

Selection makes no remote requests and reads no credentials. Unrefreshed/missing
catalogs are skipped so ordinary conversation still works; wrong scope, repeated
connection identities, mismatched metadata and pagination cycles fail closed.
The existing execution limit is 32 tools; exceeding it reports an error instead
of silently truncating. Scans are bounded to four pages of 100 connections.
Execution must still check current revocation/configuration before each call.

The API default startup does not yet inject the catalog store, because production
Worker recovery/authority wiring is not complete. No nonempty MCP snapshot is
sent into that unsupported Worker by default. This is selection implementation
and isolated database acceptance, not live Agent or Settings/browser closure.

## Pinned HTTP execution adapter (EXT-MCP-EXEC-01)

`CloudMcpTransport` accepts an exact recovered snapshot, matching immutable
catalogs and a required per-frame authority callback. It validates connection
and digest, maps internal aliases back to original remote names, validates
arguments and uses existing `McpHttpSession` framing and bounded untrusted output.
Model definitions are prepared without remote discovery. Only none/Bearer auth
is accepted; callbacks must verify current scope, revocation, policy and fence.
Credentials remain inside per-frame transport; request metadata is not forwarded.

The existing `LocalToolGateway` can accept this transport explicitly, reusing
MCP search/describe and proxy execution. Mixing process MCP config with this
transport fails. Local default behavior is unchanged. Negotiated protocol drift
requires catalog refresh before tools/call. No Worker production recovery gate
has been removed and no user has to supply aliases or Task bindings.

Acceptance exercises the actual Harness tool gateway and HTTP JSON-RPC framing
against a captured network boundary, including tools/call, Bearer per-frame
release and revocation before send. This is not a real remote MCP service or
Trench/browser acceptance. Remaining: automatic scoped admission and production
Worker authority/startup composition, then Settings and end-to-end validation.

## Remote tool names (EXT-MCP-NAMES-01)

Cloud discovery preserves remote identifiers exactly, using the existing bounded
opaque identifier contract. It no longer applies the local 32-character alias
pattern to remote names. The shared schema parser accepts a cloud-supplied safe
alias (`t` plus 30 SHA-256 hexadecimal characters), but keeps `remote_name`
unchanged in the persisted catalog. Paging rejects alias collisions as well as
duplicate remote names. This alias is internal parsing metadata, not a user
allowlist or an execution grant; Worker routing still needs composition.

Local HTTP/stdio discovery retains its original name validation. Schema checks,
pagination limits, credential checks and public HTTPS controls remain shared and
unchanged. Cloud configuration remains HTTP-only despite reusing transport-neutral
schema parsing code from the existing module. No stdio transport is activated.

## Current catalog inspection (EXT-MCP-CATALOG-01E)

`GET /v1/extensions/mcp-connections/{id}/catalog` reuses the composed management
service and its deployment gate. It requires `extensions.read` (not manage),
accepts no body/query/If-Match, and returns current configuration revision,
catalog digest, tool count, names, descriptions and JSON input schemas.
Responses are no-store; no connection credential reference or ciphertext is
serialized. Descriptions and schemas remain untrusted external metadata.

Inspection reads only persisted metadata for the exact current revision. Missing
catalogs return 404 instead of falling back to older configuration; configuration
changes during read return 409. Scope/configuration mismatches and backend
errors cannot disclose stored metadata. Expiry is checked before and after reads.
No discovery, credential release or catalog publication occurs on this path.

This endpoint supports the upcoming Settings UI; it does not authorize execution.
Users configure and enable MCP once; AI tool choice and internal execution
binding are automatic, not a new user-facing Task/Turn permission workflow.

Execution wiring inspection: `extension_turn_admission.py` currently selects only
Skills, `extension_recovery.py` rejects nonempty MCP snapshots, and
`tool_gateway_runtime.py` still obtains MCP servers from process settings plus
the Task allowlist. Cloud execution must replace that source with scoped persisted
catalogs and automatic server-owned selection, not ask the user to fill that
legacy allowlist. Preserve the local path; reuse the existing release service's
scope/revocation checks and execution fence for the cloud path. This remains
unimplemented, so successful catalog inspection is not Agent execution proof.

Validation: focused 16 passed / 5 DB skipped; actual isolated PostgreSQL with
captured upstream HTTP 21 passed. Full rerun 4165 passed / 865 skipped in 132.16s;
make check passed (901 typed sources, Eval 10/10). No live upstream/browser proof.

## Automatic refresh startup (EXT-MCP-CATALOG-01D)

`ZEBRA_CLOUD_MCP_REFRESH_ENABLED=true` independently enables automatic composition
of the management refresh service. It requires automatic credential storage
(`ZEBRA_CLOUD_MCP_CREDENTIALS_ENABLED=true`), cloud extension read/manage flags,
cloud/production PostgreSQL composition, current schema and the configured
operator master-key mount. Missing prerequisites stop startup. Credential storage
alone leaves refresh disabled. See [.env.example](../.env.example).

The refresh service shares the exact credential-store object and protector with
credential management. Its catalog store uses the same resolved cloud DSN and
deployment namespace. Automatic refresh refuses a separately injected credential
service, preventing accidental mixing of secret or database authorities. Advanced
explicit refresh-service injection remains available and caller-owned.

Startup performs no remote MCP discovery. Only a verified management POST triggers
network access. Automatic composition does not alter scope grants, enable Worker
tools, create connections, change enabled state, or configure ingress limits.
The caller still supplies If-Match; URL/token/configuration comes from existing
scoped server records. No running deployment or secret mount was changed by this
implementation. Distributed refresh coordination, queueing and ingress concurrency
limits remain rollout work, not implicit guarantees of this synchronous endpoint.

Startup tests cover default-off, prerequisite rejection, shared authority and no
network at boot. Real PostgreSQL tests construct the API without injecting a
credential or refresh service, provision a Bearer token through HTTP, refresh,
verify persisted digest, restart, and repeat successfully. Remote MCP responses
are captured fixtures rather than a live upstream service.

Validation: focused 50 passed / 3 DB skipped; actual isolated PostgreSQL plus
captured HTTP matrix 14 passed; full 4159 passed / 864 skipped in 134.53s.
make check passed (901 typed sources, Eval 10/10). No deployment activation.

## Protected management refresh (EXT-MCP-CATALOG-01C)

An explicitly injected `McpCatalogRefresh` enables
`POST /v1/extensions/mcp-connections/{id}/refresh` when cloud extension management
is enabled. No default service or Worker capability is activated. The request
requires a verified `extensions.manage` grant, a strong quoted configuration
revision in `If-Match`, no query parameters and no body. Caller cannot supply
endpoint, scope, schema or token. Responses contain connection ID, config revision,
catalog digest and tool count, plus no-store and the configuration ETag.

The refresh service loads the exact scoped configuration and checks revision.
Before each HTTP frame it checks grant expiry and configuration equality;
only initialize, initialized notification and tools/list are admitted. Anonymous
discovery uses a frame authorization hook; Bearer discovery resolves published
ciphertext via existing locked `get_for_use`, verifies the complete credential
binding and decrypts internally. Bearer connections must be enabled and ready
under that existing use-store contract; this slice does not relax it for testing
disabled authenticated connections. Unsupported auth modes remain unavailable.

After discovery, the service checks scope/configuration again and publishes using
the atomic revision-checked catalog store. Existing catalogs survive discovery
failure. Historical data never grants execution permission. Returned catalog
configuration must match the original request. Grant expiry is rechecked before
return, but a request expiring during DB commit may have committed already; retry
must respect current revision and catalog identity, not assume rollback.

Missing auth/permission, malformed input, missing precondition, stale revision,
missing scoped connection and storage/transport failure are separate HTTP statuses.
Internal details and secret-store errors are sanitized. Per-frame authorization
failures become generic upstream-unavailable errors, not diagnostic disclosure.

This endpoint is synchronous async HTTP with blocking transport offloaded to a
thread. It is not yet a RabbitMQ refresh job. No distributed refresh scheduling,
cross-request rate limit or automatic startup composition is claimed. Production
activation requires those rollout choices and ingress limits; Trench Settings
wiring and full live-server/browser acceptance remain pending.

Validation: 38 focused passed / 3 DB skipped; 21 captured HTTP plus isolated
PostgreSQL checks, including public and Bearer-mode HTTP-to-store refresh.
Full 4154 passed / 862 skipped in 132.64s; make check passed (900 sources,
Eval 10/10). No running environment was activated.

## HTTP discovery adapter (EXT-MCP-CATALOG-01B)

`discover_mcp_tool_catalog` reuses `McpHttpSession` and the same paging/schema
parser as existing HTTP tools. It negotiates the protocol, reads all supported
tool pages and returns a complete catalog bound to the supplied connection.
It does not publish to storage or grant permission to refresh. Trusted management
composition must authorize before invoking it and publish the complete return
value with the existing exact-revision store. No public refresh route is active.

Bearer mode requires an endpoint-bound resolver on initialize, initialized
notification and every list request. Missing credentials and API-key/OAuth modes
fail before network I/O; none-mode refuses any credential resolver. Connection
enabled state may be false for management testing; authentication must be usable.
No environment credential name is supplied. No global auth state is introduced.

Existing transport limits remain stricter than storage bounds: 16 tools per
server, four list pages, 16 KiB schema, five-second per-frame timeout. This is
not a five-second total refresh deadline. Unsupported names/schemas, duplicate
names across pages, repeated cursors or oversized responses reject the whole
result. No partial catalog is returned. No tools capability yields an empty
catalog, distinct from malformed discovery. Session headers and remote server
instructions are not persisted. Descriptions retain the parser's untrusted label.

Pure parsing helpers are reused from the existing stdio module, but this adapter
accepts only an HTTP connection and never invokes a subprocess/stdio transport.
Its fixed internal parser alias is not a published execution alias; scoped
execution alias generation belongs to the still-pending admission layer.

Tests capture the HTTP opener while exercising real JSON-RPC serialization and
response parsing. A separate real PostgreSQL test publishes the discovered
catalog and verifies failed refresh preserves it across store reconstruction.
This is not a live remote-server or browser acceptance test.

Validation: focused 45 passed / 1 DB skipped; captured HTTP plus isolated actual
PostgreSQL matrix 23 passed; full 4139 passed / 860 skipped in 130.33s.
make check passed (897 typed sources, Eval 10/10).

EXT-MCP-CATALOG-01A implements the persistence boundary, not remote discovery,
Task admission or Worker activation. The existing Worker MCP snapshot rejection
remains in place until the authority ceiling and execution adapter are composed.

## Contract

`McpToolCatalog` pins the complete scoped connection configuration, protocol
version and up to 256 tool definitions. Tool names are unique and sorted. Each
definition stores its description and canonical JSON input schema text rather
than a mutable nested dictionary. Schemas must be JSON objects describing object
inputs; duplicate keys, non-finite numbers and oversized documents are rejected.
The schema byte limit is 64 KiB and total catalog limit is 1 MiB. These are storage
bounds, not proof that an arbitrary JSON Schema is executable by the runtime.
Existing discovery/schema validation and name mapping must still run before use.

The digest covers configuration and all definitions; identity, endpoint,
credential reference, revision, protocol or schema changes change the digest.
Remote descriptions remain untrusted data. No token, request headers or HTTP
session identifiers are part of this contract. Resource and prompt catalogs are
not implemented by this tool-only slice.

## PostgreSQL v56

`mcp_catalog_versions` is scoped by deployment, issuer, namespace, principal,
workspace, connection and configuration revision. Digest is not authorization:
queries compare all coordinates in addition to the compact scope hash. The
catalog references an existing configuration revision through a foreign key.

Publication reuses the existing exact-parent lock and reads the configuration
after acquiring that lock. If the full current connection differs from the one
used for discovery, publication fails without replacing the previous catalog.
Publish only after successful, bounded discovery; a discovery error has no
publication operation and therefore cannot clear the previous catalog.

Definition payloads are immutable. Re-publishing an identical digest verifies
payload equality and advances its publication sequence, so A → B → A selects A
as the latest accepted refresh without duplicating the definition. Corrupted
existing payloads are rejected, not overwritten. "Latest" means latest accepted
publication for the requested configuration revision, not a guarantee of the
remote service's current implementation. Concurrent discovery jobs must still
be coordinated by the future refresh composition; this store does not order
requests by when network discovery started.

Exact reads require the expected digest. Latest reads require an explicit
configuration revision; they never fall back to an older configuration. Readback
reconstructs and validates the model, identity and digest. Historical reads remain
possible after configuration changes; they do not grant permission to execute.

## Deployment and next steps

Migration is registered but was applied only to disposable test schemas. A running
API still using v55 needs the normal operator migration before restarting code
that requires v56; no live schema migration was performed in this task.

Remaining: catalog read routes and management UX, frozen Task MCP
ceiling and Turn selection, Worker dispatch plus fresh credential/lease checks,
and Trench Settings E2E. Do not remove the Worker's deny gate just because this
catalog store exists. See [extension design](cloud-skills-http-mcp-design.md).

Validation: 11 deterministic checks; 37 actual PostgreSQL catalog/credential
checks in disposable schemas; full 4124 passed / 859 skipped in 133.57s.
make check passed: 896 typed sources, Eval 10/10. No remote MCP or browser
acceptance is claimed by these storage checks.
# Remote SSE compatibility (2026-09-08)

User-approved transport=sse adds legacy HTTP+SSE protocol 2024-11-05 without
changing default Streamable HTTP negotiation or enabling cloud stdio. Discovery
and CloudMcpTransport share McpSseSession and existing schema/output validation.
Each GET/POST rechecks live authority and resolves endpoint-bound credentials.
The server-issued message URL must be same-origin HTTPS, without userinfo,
fragment, whitespace or backslashes. GET and POST use the existing DNS-validated,
IP-pinned public HTTPS socket handler, no proxy/redirect/environment credentials.
Sessions close on success/failure; streams are bounded; no automatic replay of
possibly executed calls. Current slice supports tools discovery/call, not new
resources/prompts/notification subscription capabilities.

Live target probe through the repository adapter was blocked before GET:
local DNS returned 198.18.4.94 (non-global benchmark range, consistent with
fake-IP DNS). A query to 1.1.1.1 returned the same mapping. No guard was bypassed.
Earlier independent client success is not adapter/Worker/Trench acceptance.
Use real public DNS in the execution environment before rerunning live acceptance.
No private target URL, user data or credentials were stored in the repository.
