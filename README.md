![Zebra Agent](./assets/logo.png)

# Zebra Agent

Zebra Agent is an embeddable Agent Runtime service whose product target is
the **cloud agent**: an independent, multi-session execution plane (control
plane, stateless workers, sandbox fleet) consumed by business systems. The
local agent — the local SQLite profile with its optional desktop and CLI
operator surfaces — exists to develop, mature and prove the runtime; it is
the development vehicle and compatibility baseline, not the product goal.
Local-first execution is therefore a development strategy, while cloud
composition is the delivery target. Zebra turns Agent requests into durable,
streamable, stoppable, resumable, and auditable execution while remaining
independent of the business system that calls it.

Zebra owns Task, Conversation, Session, Model, Context, Tool, Agent Memory,
Artifact, Worker, Sandbox, streaming, concurrency, and recovery. It does not own
user registration, organizations, memberships, business RBAC, subscriptions, or
billing. Authentication is external; the selected default is Authelia through
OIDC. The calling business system supplies signed Agent authority, an opaque
namespace for isolation, and technical execution limits.

Coding and Git delivery are optional tool domains. The normal desktop flow is
task input, truthful execution evidence, approval or clarification when required,
and durable result review.

## Product Boundary

```text
Authelia / external identity
             │ OIDC
             ▼
Business system / API gateway
  users · organizations · membership · business authorization · billing
             │ signed Agent authority + opaque namespace
             ▼
Zebra Agent Runtime
  task · conversation · session · model · tool · memory · artifact
  stream · worker · sandbox · concurrency · HA · recovery · usage evidence
```

Zebra validates the external authority and enforces Agent-specific Policy,
Approval, Sandbox, namespace isolation, and technical limits. It never expands
the caller's authority and does not query or duplicate the caller's user,
membership, subscription, or billing database.

Business quota and Zebra execution limits are distinct. The business system
decides entitlements; Zebra enforces supplied ceilings such as concurrent tasks,
model tokens, runtime seconds, CPU, memory, disk, and network. Zebra emits usage
and audit evidence for external capacity or billing systems but never calculates
prices or invoices.

## Current Status

The `cloud-agent` mainline now composes the API and stateless Worker explicitly
over PostgreSQL, MinIO/S3 and Redis live fan-out. Host admission freezes the
verified authority, Agent Definition and Host Tool manifest before execution;
Workers consume those durable snapshots rather than rediscovering mutable
capabilities. The accepted Cloud line has passed the unfiltered repository suite
against real PostgreSQL and MinIO (`2938 passed / 0 failed / 11 skipped`) and the
real HTTP boundary from RS256 Host Grant verification through Worker completion.

This is Cloud Runtime readiness, not a claim that every business-system rollout
is complete. The real Trench cross-service gate still requires its 16 deployed
HTTP, PostgreSQL, Redis, object-store, Grant, cookie and operator inputs. The
outbound Host Tool credential resolver is also still a compatibility seam; it
must be replaced by the deployment's workload-identity, OAuth or mTLS issuer
before production custom writes. Kubernetes/fleet operations and that
credential deployment remain operator work. See [docker/README.md](./docker/README.md)
for the application/dependency Compose split. Read
[PROGRESS.md](./PROGRESS.md) for the live project snapshot and
[docs/AGENT_TASKS.md](./docs/AGENT_TASKS.md) for task ownership and status. The
adaptive execution boundary is specified in
[docs/自适应Agent循环与预算治理方案_v1.0.md](./docs/自适应Agent循环与预算治理方案_v1.0.md).

## Capability Baseline

### Execution and recovery

- durable event store and deterministic projections
- adaptive Harness loops: model/tool call counts are unlimited by default while
  caller-supplied hard ceilings remain available as explicit execution contracts
- progress-preserving budget handling: an oversized hard-budget batch starts
  nothing and suspends recoverably instead of partially executing or failing
- model-native Subagent selection: direct answers and parent tools stay local;
  only an explicit valid bounded research call creates a non-recursive child
- recoverable tool failures return structured evidence to the model so it can
  correct the call, choose an alternative, or answer within remaining budgets
- worker leases, cancellation, recovery, suspension, and snapshot restore
- correlated model, tool, approval, clarification, artifact, memory, and trace evidence
- backend-internal handoff safety contracts with authority narrowing and side-effect replay guards
- stable Task projection, cross-Segment event cursor, and active-Segment command routing
- bounded prior user/Assistant checkpoints for context-correct terminal follow-ups

### Runtime, policy, and tools

- typed general and coding tool profiles with independent Policy authority
- bounded local file, command, patch, Git, Web, Skill, MCP, and Research paths
- `trusted-local`, `oci-rootless`, and `gvisor` runtime classes
- production fail-close on missing gVisor, mutable images, authority drift, or
  incompatible snapshots
- core and non-local deployments default-deny network access; explicit
  `local + trusted-local` mode gives Desktop/API/CLI/Worker one operator trust
  boundary, including automatic upgrade of existing Tasks without approval popups
- bounded HTTPS/URL/redirect/size controls; direct connections retain public-DNS
  checks, while trusted local execution honors the operator's system HTTPS proxy
- non-local MCP and side-effecting operations retain approval gates; trusted local
  still enforces workspace paths, tool schemas, runtime boundaries, and audit

### Model and context

- OpenAI-compatible provider adapter with public Assistant text streaming
- model-aware context-window planning and hard outbound request gates
- deterministic compaction with durable, transparent Context Capsules
- Artifact-backed bounded projection for large tool outputs
- provider continuation with deterministic Capsule fallback
- DeepSeek stable and default-off Beta capability profiles

### Operator surfaces

- CLI, FastAPI, worker, and Tauri/React desktop composition roots
- replay-plus-tail SSE with cursor recovery
- real-Chromium regression coverage for long streaming, reload recovery,
  cancellation, and completed-Task follow-up across an invisible Segment
- durable approval and clarification continuation
- artifact, diff, audit, memory, commit, and guarded pull-request operations
- context inspection and manual compaction; internal execution boundaries are not user controls

## Explicit Boundaries

The current repository does not claim:

- Kubernetes or distributed Sandbox orchestration
- a completed production rollout into a real Host such as Trench
- a production workload-identity/OAuth/mTLS issuer for outbound Host Tools
- ACP or optional code-intelligence adapters
- unrestricted browser automation or autonomous production deployment

The following are external business responsibilities, not deferred Zebra
features: registration/login UI, user and organization directories, membership
and invitations, business RBAC, subscriptions, plans, billing, and invoices.

Production gVisor support is Linux-first. Restore creates a fresh sandbox from
durable state; it is not process-memory checkpointing. Workspace disk hard quota
must be enforced by the production storage layer.

Provider credentials belong only in ignored backend configuration. Never place
them in frontend storage, request payloads, tracked files, responses, or logs.

## Repository Shape

- `apps/`: API, CLI, config, and worker composition roots
- `packages/`: control-plane, core, context, integrations, observability,
  orchestration, runtime, security, storage, and tools
- `UI/desktop/`: React, Ant Design X, Lobe UI, and Tauri desktop workspace
- `tests/`: deterministic, contract, smoke, and integration coverage
- `evals/`: release and provider evaluation cases
- `docs/`: architecture, governance, acceptance records, and operator runbooks
- `docker/`: dependency and Zebra application Compose lifecycles plus optional
  auxiliary-service overlays

`agent-core` remains infrastructure-independent. Other packages may depend on
core; packages must not import from applications.

## Cloud Agent Integration Tutorial

This tutorial is for a business system (the **Host**) integrating with Zebra's
Cloud API. It uses the native `/sessions` HTTP surface first, then adds custom
business tools through the Host Tool protocol. CopilotKit clients should keep
their browser connected to the Host BFF and let that BFF exchange authority with
Zebra; the browser must not mint Zebra grants or hold Host signing keys.

### 1. Choose the integration surface

| Need | Zebra surface | Recommended caller |
|---|---|---|
| Create, inspect, stop or stream an Agent session | `/sessions` and `/tasks` | Host backend/BFF |
| CopilotKit event projection | `/agui/commands` and `/agui/threads/.../stream` | CopilotKit Runtime/BFF |
| Read or change Host business data | Host Tool manifest and invoke endpoints | Zebra Worker |
| Generic external developer tooling | MCP configuration | Zebra operator |

Use Host Tools for business data because their scope and resource bindings come
from the signed Host Grant. MCP is useful for generic integrations, but it must
not become a shortcut around the Host's business authorization.

The request path is:

```text
browser -> Host BFF -> signed one-request Host Grant -> Zebra API
                                                   -> PostgreSQL admission
                                                   -> stateless Worker
                                                   -> frozen Host Tool contract
                                                   -> Host Tool API
```

PostgreSQL is the execution authority. Redis is only live delivery/cache, and
MinIO/S3 stores Artifact bytes whose metadata remains in PostgreSQL.

### 2. Deploy the Cloud composition

For local infrastructure validation, start the dependency project and then the
separate Zebra application project:

```bash
cp docker/.env.example docker/.env
cp docker/.env.application.example docker/.env.application

# Set these deployment-specific values in docker/.env.application.
# ZEBRA_RUNTIME_CLASS=gvisor
# ZEBRA_RUNTIME_IMAGE=registry.example/zebra-runtime@sha256:<64-hex-digest>
# ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA=true

docker compose --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  up -d --wait postgres redis-live minio minio-init
docker compose --env-file docker/.env.application \
  -f docker/compose.application.yml \
  up -d --build --wait zebra-migrate zebra-api zebra-worker
curl --fail http://127.0.0.1:18080/health
```

The Cloud profile fails closed unless it receives a PostgreSQL DSN, deployment
and authority namespaces, a memory-cursor signing key, S3 settings, `gvisor`, a
digest-pinned Runtime image and storage-enforced workspace quota. A real task
also needs the selected model provider configuration and its named credential in
both API and Worker containers. Inject that credential through the deployment's
secret manager; do not commit it to either example env file. The bundled Compose
is a composition/health baseline, not a production Sandbox fleet or secret
delivery system.

### 3. Register the Host trust boundary

Before Zebra accepts a request, an operator registers the Host issuer for each
opaque business namespace. Migrations must already be complete. The example
uses the host-mapped PostgreSQL port from the dependency Compose stack:

```bash
export ZEBRA_DATABASE_URL='postgresql://zebra:local-only-change-me@127.0.0.1:15432/zebra'
export ZEBRA_DEPLOYMENT_NAMESPACE='local-zebra'

uv run python - <<'PY'
import os
from agent_storage import HostRegistryRecord, PostgresHostAuthorityStore

store = PostgresHostAuthorityStore(
    os.environ["ZEBRA_DATABASE_URL"],
    deployment_namespace=os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"],
)
store.upsert_registry(HostRegistryRecord(
    host_app_id="trench",
    namespace_id="tenant-123",
    issuer="https://api.trench.example.com",
    audience="zebra",
    jwks_uri="https://api.trench.example.com/.well-known/jwks.json",
    allowed_origins=("https://trench.example.com",),
    algorithms=("RS256",),
    policy_version="agent-policy-v1",
))
PY
```

`issuer`, `jwks_uri` and browser origins must use exact HTTPS values; wildcard
origins and symmetric JWT algorithms are rejected. Treat this registry as
operator configuration, not a per-request API. Register it before starting the
API, or restart the API after a registry change so its exact CORS origin set is
rebuilt.

### 4. Mint a single-use Host Grant

The Host backend signs one short-lived JWT for **each Zebra HTTP request**. The
JWT payload uses these exact claim names (the numeric timestamps below are only
shape examples; calculate them at issuance time):

```json
{
  "iss": "https://api.trench.example.com",
  "aud": "zebra",
  "sub": "opaque-user-reference",
  "jti": "a-new-random-id-for-this-request",
  "iat": 1787461200,
  "nbf": 1787461200,
  "exp": 1787461500,
  "host_app_id": "trench",
  "namespace_id": "tenant-123",
  "workspace_ref": "workspace-456",
  "resource_refs": [{"type": "trench.event", "id": "evt-789"}],
  "scopes": ["agent.run", "trench:event:read"],
  "limits": {
    "max_runtime_seconds": 300,
    "max_model_tokens": 100000,
    "max_artifact_bytes": 10485760
  },
  "origin": "https://trench.example.com",
  "policy_version": "agent-policy-v1"
}
```

Sign it with the private key matching the registered JWKS (`RS256` or `ES256`).
Zebra verifies signature, issuer, audience, time window, exact origin, required
`agent.run` scope and structural integer limits, then atomically consumes `jti`
in PostgreSQL. Reusing the same JWT is therefore a `403`; use Zebra's
`Idempotency-Key` for application retries and mint a fresh Grant for every retry,
read, stream connection and stream reconnect.

### 5. Create and stream a session

Assume the Host BFF has put a newly signed token into `HOST_GRANT`. Use a stable
idempotency key for the logical create operation:

```bash
export ZEBRA_URL='https://zebra.example.com'
export HOST_ORIGIN='https://trench.example.com'
export CREATE_KEY='trench-task-01JABC123'

CREATE_RESPONSE="$(curl --fail-with-body "$ZEBRA_URL/sessions" \
  -H "Authorization: Bearer $HOST_GRANT" \
  -H "Origin: $HOST_ORIGIN" \
  -H "Idempotency-Key: $CREATE_KEY" \
  -H 'Content-Type: application/json' \
  --data '{
    "title": "Summarize event evt-789",
    "prompt": "Read the granted event and summarize the evidence.",
    "workspace": "/workspaces/tenant-123/task-01JABC123",
    "execute": true,
    "tool_profile": "general",
    "policy_profile": "workspace_write",
    "network_profile": "none",
    "max_model_calls": 8,
    "max_tool_calls": 16
  }')"
SESSION_ID="$(printf '%s' "$CREATE_RESPONSE" | jq -r '.session_id')"
```

A Cloud create returns `201`, a durable `session_id`, and an accepted `run`
command; the Worker completes it asynchronously. Repeating the identical body
and key with a fresh Grant returns the identical `201` body. Reusing the key with
a different body returns `409 idempotency_conflict`.

Read status or consume replay-plus-tail SSE with another fresh Grant:

```bash
curl --fail-with-body "$ZEBRA_URL/sessions/$SESSION_ID" \
  -H "Authorization: Bearer $HOST_GRANT" -H "Origin: $HOST_ORIGIN"
curl -N "$ZEBRA_URL/sessions/$SESSION_ID/stream?after_sequence=-1" \
  -H "Authorization: Bearer $HOST_GRANT" -H "Origin: $HOST_ORIGIN" \
  -H 'Accept: text/event-stream'
```

Persist the last SSE `id` and reconnect with `after_sequence=<last-id>` and a
fresh Grant. The durable PostgreSQL replay path remains lossless if Redis live
fan-out is unavailable.

For CopilotKit, keep this authorization inside the Host BFF. Submit `run`,
`resume` or `stop` to `/agui/commands` with `threadId`, `runId`, strict integer
`expectedRevision`, optional official AG-UI `input`, and an `Idempotency-Key`.
Consume `/agui/threads/{threadId}/runs/{runId}/stream` with a fresh Grant. AG-UI
is a command/projection adapter; Zebra's Task/Event Store remains the durable
authority.

### 6. Add a custom Host Tool

A custom business tool is hosted by the business system, not installed inside
`agent-core`. The Host exposes an HTTPS manifest and bounded invoke endpoint.
This read-only example binds `event_id` to exactly one granted business resource:

```json
{
  "workloadIdentity": "workload/zebra-worker",
  "tools": [{
    "name": "events.get_event",
    "description": "Read one granted event.",
    "requiredArguments": ["event_id"],
    "argumentProperties": {"event_id": {"type": "string"}},
    "parallelSafe": true,
    "capabilityVersion": "1",
    "executionLocation": "host",
    "scopes": ["trench:event:read"],
    "risk": "read",
    "timeoutSeconds": 10,
    "maxOutputBytes": 32768,
    "idempotency": "required",
    "receiptSchemaVersion": "1",
    "resourceBindings": [{
      "argumentPointer": "/event_id",
      "resourceType": "trench.event",
      "required": true,
      "matchMode": "exact"
    }]
  }]
}
```

Implement the current v1 wire endpoints:

- `GET /manifest` returns the JSON above.
- `POST /tools/events.get_event/invoke` accepts `toolCallId`, `toolName`,
  `arguments`, effective `scopes`, granted `resources`, `workloadIdentity` and
  `idempotencyKey`.
- A successful call returns `{"output":"<bounded string>","metadata":{...}}`.
  Only safe metadata such as `trace_id`, `request_id` and `provider_operation_id`
  is retained by Zebra.
- For writes, require idempotency, persist the provider operation ID before the
  business mutation, and implement the profile's reconcile endpoint. An unknown
  timeout outcome must be reconciled to `succeeded`, `failed_no_effect` or remain
  `uncertain`; never blindly repeat the write.

The Host must independently verify `X-Zebra-Workload-Identity`,
`X-Zebra-Host-App`, `X-Zebra-Namespace`, `X-Zebra-Grant-Id` and
`X-Zebra-Workspace-Ref`, then match the arguments against the `resources` array
in the body. `X-Zebra-Host-Auth` is the lowercase hex HMAC-SHA256 of this exact
UTF-8 input, using canonical JSON (sorted keys and no insignificant spaces):

```text
METHOD\nPATH\nGRANT_ID\nWORKSPACE_REF\nHOST_APP_ID\nNAMESPACE_ID\nCANONICAL_JSON_BODY
```

Reject any argument outside the granted resources. Zebra also rejects
private/IP-literal/redirecting connector targets and oversized responses.

Register an immutable connector profile, then bind the Host namespace to that
exact revision:

```bash
uv run python - <<'PY'
import os
from agent_core.domain.host_connectors import (
    HostConnectorBinding, HostConnectorProfileVersion,
)
from agent_storage.postgres.host_connectors import PostgresHostConnectorRegistry

registry = PostgresHostConnectorRegistry(
    os.environ["ZEBRA_DATABASE_URL"],
    deployment_namespace=os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"],
)
registry.publish_profile(HostConnectorProfileVersion(
    host_app_id="trench", connector_id="trench-main", profile_revision=1,
    base_uri="https://api.trench.example.com",
    manifest_path="/manifest",
    invoke_path_template="/tools/invoke",
    reconcile_path_template="/tools/reconcile",
    supported_protocol_versions=("host-capability-protocol/1",),
    workload_identity_ref="workload/zebra-worker",
    credential_ref="credentials/trench-host-tools",
))
registry.bind(HostConnectorBinding(
    host_app_id="trench", namespace_id="tenant-123",
    connector_id="trench-main", profile_revision=1,
    binding_revision=1,
))
PY
```

On the first admission for this profile revision, Zebra fetches and freezes the
manifest before its atomic Task transaction. The binding stores the real digest;
the Worker reads the frozen copy and performs no live discovery. To change tools,
publish revision 2 and move the namespace binding. Existing Tasks retain their
original revision and digest. Missing, revoked, unreachable or drifted pinned
profiles fail closed.

> **Current production gate:** the default outbound connector path still derives
> a compatibility HMAC credential from `credential_ref`. It proves the protocol
> and freeze/recovery contracts, but it is not a secret-management design. Keep
> custom tools read-only in staging until the deployment supplies a real
> `HostWorkloadCredentialResolverPort` backed by workload identity, OAuth or mTLS.
> Isolated protocol tests reproduce the current HMAC with
> `compat:<credential_ref>`; never use that deterministic value as a deployed
> credential.
> The current frozen `HostToolManifest.to_payload()` serializer also does not
> preserve arbitrary declared `resourceBindings`; Trench's recognized vocabulary
> retains its compatibility mapping, but a new Host vocabulary must not be
> enabled until its binding survives a frozen-manifest round trip. Do not rely
> only on the live manifest response or Host-side checks.

### 7. Validate before enabling a Host

Run the Host-neutral contract suite and the Cloud HTTP boundary tests:

```bash
uv run pytest -q tests/conformance/host_v1
uv run pytest -q tests/agent_storage/test_postgres_http_auth_boundary_e2e.py
uv run pytest -q tests/agent_storage/test_postgres_host_manifest_freeze.py
```

Then exercise the deployed Host with: anonymous/invalid Grant rejection, wrong
origin, missing scope, ungranted resource, consumed-`jti` replay, identical
idempotent replay, conflicting replay, Worker restart, stream cursor reconnect,
Host timeout and zero unintended business writes. Trench has a fail-closed
nine-scenario runner at `tests/compose/trench_read_e2e/run_acceptance.py`; it
prints `ZEBRA_TRENCH_READ_E2E=BLOCKED` until all 16 real deployment inputs exist.

Common failures:

| HTTP/result | Meaning | Check |
|---|---|---|
| `401 missing_or_invalid_host_grant` | no usable bearer Grant | BFF exchange and header |
| `403 host_grant_rejected` | signature, claim, scope or consumed `jti` failed | registry, JWKS, clock and fresh Grant |
| `403 host_origin_not_allowed` | browser origin is not exact | registry and `Origin` header |
| `409 idempotency_conflict` | one key has two request meanings | stable key plus byte-equivalent JSON body |
| `503 host_manifest_unavailable` | pinned Host cannot be frozen | profile, HTTPS reachability and manifest |
| Tool `scope_denied` / `resource_denied` | Tool exceeds the Grant | manifest scope/binding and JWT resources |
| Tool `output_too_large` | Host exceeded its contract | `maxOutputBytes` and bounded projection |

Never put Host signing keys, model credentials or outbound Host credentials in a
browser, request body, manifest, connector profile, database row, Artifact or
log. Persist only opaque references and secret-free audit digests.

## Local Development

Prerequisites: Python 3.12, `uv`, Node 22.17.0, and pnpm 10.28.2.

```bash
make sync
make test
make check
```

Run the real browser streaming gate after `make sync`:

```bash
cd UI/desktop
pnpm exec playwright install chromium
pnpm e2e
```

The gate starts the live Vite Desktop, FastAPI, Worker path, and an isolated
SQLite event store. Only the external model endpoint is replaced by a local,
deterministic OpenAI-compatible streaming provider.

Useful entry points:

```bash
uv run zebra-agent --help
make api-serve
make ui-dev
```

Start local provider configuration from `.env.example` and keep real values in
ignored files.

## Operator Entry

Start with [docs/operator_runbook.md](./docs/operator_runbook.md).

Focused references:

- service boundary: [docs/ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md](./docs/ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md)
- Embedded target: [docs/Zebra Embedded 生产级目标架构.md](./docs/Zebra%20Embedded%20生产级目标架构.md)
- CopilotKit/AG-UI boundary: [docs/ADR-015_Zebra_Embedded与CopilotKit_AGUI边界.md](./docs/ADR-015_Zebra_Embedded与CopilotKit_AGUI边界.md)
- Embedded task roadmap: [docs/Zebra Embedded与Trench实施任务拆解_v1.0.md](./docs/Zebra%20Embedded与Trench实施任务拆解_v1.0.md)
- production Runtime: [docs/生产级Runtime实施方案_v1.0.md](./docs/生产级Runtime实施方案_v1.0.md)
- context lifecycle: [docs/上下文生命周期与混合压缩架构方案_v1.0.md](./docs/上下文生命周期与混合压缩架构方案_v1.0.md)
- context continuity and governed memory v1.1: [docs/上下文连续性与治理记忆改进方案_v1.1.md](./docs/上下文连续性与治理记忆改进方案_v1.1.md)
- Task continuity and internal Segments: [docs/ADR-013_用户任务连续性与内部执行分段.md](./docs/ADR-013_用户任务连续性与内部执行分段.md)
- automatic rollover roadmap: [docs/透明Context_Segment与自动Rollover实施方案_v1.0.md](./docs/透明Context_Segment与自动Rollover实施方案_v1.0.md)
- historical handoff safety contract: [docs/阶段性Session_Handoff与短线程链架构方案_v1.0.md](./docs/阶段性Session_Handoff与短线程链架构方案_v1.0.md)
- DeepSeek profiles: [docs/DeepSeek_V4_模型适配与专项优化方案_v1.0.md](./docs/DeepSeek_V4_模型适配与专项优化方案_v1.0.md)
- CI gates: [docs/主线CI质量门禁说明_v1.0.md](./docs/主线CI质量门禁说明_v1.0.md)
- architecture: [docs/Codex-like工程Agent平台最终架构设计_v1.0.md](./docs/Codex-like工程Agent平台最终架构设计_v1.0.md)

## Governance Entry

| Question | Source of truth |
|---|---|
| What is the product and how do I run it? | `README.md`, operator runbook |
| What is true on the current mainline? | `PROGRESS.md` |
| What task is active, owned, or locked? | `docs/AGENT_TASKS.md` |
| What architecture boundaries apply? | final architecture document |
| What did the original implementation sequence require? | `docs/实施任务拆解与阶段验收.md` |
| Who owns and reviews a change? | RACI reference and the current task card |

Repository precedence and working rules are defined in `AGENTS.md`.
