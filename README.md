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

The current `cloud-agent` line is a feature-complete local Beta and a Cloud
single-host production candidate. It includes:

- durable provider-to-desktop Assistant streaming
- stable Task identity with recoverable context compaction and automatic,
  backend-internal execution segmentation
- DeepSeek Flash/Pro profiles with fail-closed capability validation
- trusted-local, rootless OCI, and production gVisor runtime classes
- PostgreSQL-authoritative Cloud control-plane composition, MinIO Artifact
  storage, durable child delegation, and frozen Host admission bindings
- bounded Cloud Context materialization and explicit child inheritance modes
- pull-request and `main` quality gates for backend, desktop, and real gVisor

Cloud deployment does not change the product boundary above. Trench owns
CopilotKit React v2 and its Runtime/BFF, while Zebra exposes an AG-UI adapter and
retains durable Task/Event/Policy authority. The Cloud profile now composes one
PostgreSQL control-plane authority, MinIO-backed Artifacts, Effect durability,
frozen Host manifests, signed authority, and stateless Workers; the local profile
remains the SQLite compatibility baseline. Kubernetes/multi-region operations,
production Trench acceptance, ACP, and optional code-intelligence remain outside
the verified baseline.

The `cloud-agent` mainline composes the API and stateless Worker explicitly
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
- one-generation Cloud materialization of recent History, active Capsule, and
  confirmed governed Memory, with revision/scope drift failing closed
- durable children choose `fresh`, `capsule`, `fork_tail`, or `resume`; Zebra
  never copies the complete parent context or its authority implicitly
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
- multi-region or Kubernetes production readiness
- completed Trench production cutover or cross-service operational acceptance
- centralized production Credential/Egress Broker services
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

## Zebra Cloud Agent 接入教程

本教程面向需要接入 Zebra Cloud Agent 的业务系统（下文称为
**Host**）。我们先使用原生 `/sessions` HTTP 接口创建 Agent Session，
再通过 Host Tool 协议把业务系统中的自定义工具安全地开放给 Zebra Worker。

如果前端使用 CopilotKit，浏览器应始终连接 Host 自己的 BFF，由 BFF 与 Zebra
交换授权。浏览器不得签发 Zebra Grant，也不得持有 Host 签名私钥。

### 1. 选择合适的接入面

| 接入需求 | Zebra 接口 | 推荐调用方 |
|---|---|---|
| 创建、查询、停止或订阅 Agent Session | `/sessions`、`/tasks` | Host 后端/BFF |
| 向 CopilotKit 投影 Agent 事件 | `/agui/commands`、`/agui/threads/.../stream` | CopilotKit Runtime/BFF |
| 读取或修改 Host 业务数据 | Host Tool manifest 与 invoke 接口 | Zebra Worker |
| 接入通用开发者工具 | MCP 配置 | Zebra 运维方 |

业务数据应通过 Host Tool 接入，因为工具的 scope 和资源绑定来自已签名的
Host Grant。MCP 适合通用集成，但不能绕过 Host 的业务授权边界。

完整请求链路如下：

```text
浏览器 -> Host BFF -> 单请求签名 Host Grant -> Zebra API
                                             -> PostgreSQL admission
                                             -> 无状态 Worker
                                             -> 已冻结的 Host Tool 合同
                                             -> Host Tool API
```

PostgreSQL 是执行事实的权威来源；Redis 仅用于实时投递和缓存；MinIO/S3
保存 Artifact 字节，Artifact 元数据仍保存在 PostgreSQL。

### 2. 部署 Cloud 组合

本地验证时，先启动依赖 Compose 项目，再启动独立的 Zebra 应用 Compose
项目：

```bash
cp docker/.env.example docker/.env
cp docker/.env.application.example docker/.env.application

# 在 docker/.env.application 中设置这些部署相关值。
# ZEBRA_RUNTIME_CLASS=gvisor
# ZEBRA_RUNTIME_IMAGE=registry.example/zebra-runtime@sha256:<64位十六进制摘要>
# ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA=true

docker compose --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  up -d --wait postgres redis-live minio minio-init
docker compose --env-file docker/.env.application \
  -f docker/compose.application.yml \
  up -d --build --wait zebra-migrate zebra-api zebra-worker
curl --fail http://127.0.0.1:18080/health
```

Cloud profile 采用 fail-closed：必须显式提供 PostgreSQL DSN、部署 namespace、
授权 namespace、memory cursor 签名密钥、S3 配置、`gvisor`、
带 digest 的 Runtime 镜像，以及由存储层强制执行的 workspace quota，
否则服务不会静默降级到 SQLite。

真实任务还需要 API 和 Worker 同时配置选定的模型供应商及其命名凭证。
凭证必须由部署环境的 Secret Manager 注入，不要写入示例 env 文件。仓库内
Compose 只用于组合与健康检查基线，不等同于生产 Sandbox Fleet 或生产级
密钥分发系统。

### 3. 注册 Host 信任边界

Zebra 接收请求前，运维方需要为每个不透明业务 namespace 注册 Host issuer。
执行下面的代码前必须先完成数据库迁移。示例使用依赖 Compose 映射到宿主机的
PostgreSQL 端口：

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

`issuer`、`jwks_uri` 和浏览器 Origin 必须是精确的 HTTPS
值；系统拒绝通配符 Origin 和对称 JWT 算法。Host Registry 属于运维配置，
不是每次请求都调用的业务 API。

应在 Zebra API 启动前完成注册；如果 Registry 已修改，需要重启 API，让
服务重新构建精确的 CORS Origin 集合。

### 4. 签发一次性 Host Grant

Host 后端必须为**每一次 Zebra HTTP 请求**签发一个短期 JWT。JWT payload
使用以下精确 claim 名称；示例时间戳只表示字段形状，生产环境必须在签发时
动态计算：

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

使用与已注册 JWKS 匹配的私钥进行签名（`RS256` 或
`ES256`）。Zebra 会验证签名、issuer、audience、有效时间、
精确 Origin、必需的 `agent.run` scope，以及整数类型的限制字段，
随后在 PostgreSQL 中原子消费 `jti`。

因此重复使用同一个 JWT 会得到 `403`。业务重试应使用 Zebra 的
`Idempotency-Key`，并为每次重试、查询、建立流连接和流重连签发
新的 Grant。

### 5. 创建并订阅 Session

假设 Host BFF 已将新签发的 token 放入 `HOST_GRANT`。同一次逻辑
创建操作必须使用稳定的幂等键：

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
    "title": "汇总事件 evt-789",
    "prompt": "读取已授权事件并汇总其中的证据。",
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

Cloud create 成功时返回 `201`、持久化的 `session_id`，
以及已接受的 `run` command；Worker 在后台异步执行。使用新 Grant、
相同请求体和相同幂等键重试，会得到完全相同的 `201` 响应体；
相同幂等键配不同请求体则返回 `409 idempotency_conflict`。

使用另一个新 Grant 查询状态，或者订阅 replay-plus-tail SSE：

```bash
curl --fail-with-body "$ZEBRA_URL/sessions/$SESSION_ID" \
  -H "Authorization: Bearer $HOST_GRANT" -H "Origin: $HOST_ORIGIN"
curl -N "$ZEBRA_URL/sessions/$SESSION_ID/stream?after_sequence=-1" \
  -H "Authorization: Bearer $HOST_GRANT" -H "Origin: $HOST_ORIGIN" \
  -H 'Accept: text/event-stream'
```

Host 应持久化最后收到的 SSE `id`，重连时传入
`after_sequence=<last-id>` 并使用新 Grant。即使 Redis 实时
fan-out 不可用，PostgreSQL 的持久化 replay 路径仍是无损的。

如果使用 CopilotKit，授权交换仍然放在 Host BFF 内。向
`/agui/commands` 提交 `run`、`resume`
或 `stop`，请求包含 `threadId`、`runId`、
严格整数类型的 `expectedRevision`、可选的官方 AG-UI
`input`，以及 `Idempotency-Key`。随后使用新 Grant
订阅 `/agui/threads/{threadId}/runs/{runId}/stream`。

AG-UI 只是 command/projection 适配层；Zebra Task/Event Store 仍然是持久化
执行事实来源。

### 6. 接入自定义 Host Tool

自定义业务工具应部署在业务系统内，而不是安装进 `agent-core`。
Host 对外暴露 HTTPS manifest 和受约束的 invoke 接口。下面的只读示例将
`event_id` 精确绑定到 Grant 中唯一获准访问的业务资源：

```json
{
  "workloadIdentity": "workload/zebra-worker",
  "tools": [{
    "name": "events.get_event",
    "description": "读取一个已授权事件。",
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

Host 需要实现当前 v1 wire endpoints：

- `GET /manifest`：返回上面的 manifest JSON。
- `POST /tools/events.get_event/invoke`：接收
  `toolCallId`、`toolName`、`arguments`、
  生效后的 `scopes`、获准访问的 `resources`、
  `workloadIdentity` 和 `idempotencyKey`。
- 成功响应为
  `{"output":"<受大小限制的字符串>","metadata":{...}}`。Zebra
  只保留 `trace_id`、`request_id` 和
  `provider_operation_id` 等安全元数据。
- 写工具必须要求幂等，在业务写入前持久化 provider operation ID，并实现
  profile 指定的 reconcile 接口。超时造成的未知结果必须被对账为
  `succeeded`、`failed_no_effect`，或继续保持
  `uncertain`；绝不能直接重复执行写操作。

Host 还必须独立校验 `X-Zebra-Workload-Identity`、
`X-Zebra-Host-App`、`X-Zebra-Namespace`、
`X-Zebra-Grant-Id` 和 `X-Zebra-Workspace-Ref`，
并将参数与请求体中的 `resources` 数组再次匹配。

`X-Zebra-Host-Auth` 是下面精确 UTF-8 输入的 HMAC-SHA256
小写十六进制结果。JSON 必须使用 canonical 形式：键排序，并移除无意义空格。

```text
METHOD\nPATH\nGRANT_ID\nWORKSPACE_REF\nHOST_APP_ID\nNAMESPACE_ID\nCANONICAL_JSON_BODY
```

Host 必须拒绝任何超出 Grant 资源范围的参数。Zebra 侧也会拒绝私网地址、
IP 字面量、发生重定向的 connector target 和超出约定大小的响应。

发布不可变 connector profile，然后把 Host namespace 绑定到该精确 revision：

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

该 profile revision 第一次 admission 时，Zebra 会先获取并冻结 manifest，
然后才进入原子的 Task 事务。binding 保存真实 digest；Worker 只读取冻结副本，
执行阶段不会再次进行实时 discover。

需要变更工具时，发布 revision 2，再将 namespace binding 切换到新 revision。
已经创建的 Task 继续保留原 revision 和 digest。缺失、已撤销、不可达或 digest
漂移的 pinned profile 一律 fail-closed。

> **当前生产门槛：**默认出站 connector 仍根据 `credential_ref`
> 派生兼容 HMAC 凭证。这足以验证协议、冻结和恢复合同，但不是生产密钥管理
> 方案。在部署环境提供由 workload identity、OAuth 或 mTLS 支撑的真实
> `HostWorkloadCredentialResolverPort` 前，自定义工具应只在
> staging 中保持只读。隔离协议测试会使用
> `compat:<credential_ref>` 重现当前 HMAC；生产环境绝不能把这个
> 确定性值当作真实凭证。
>
> 当前冻结序列化器 `HostToolManifest.to_payload()` 也不会保留任意
> 自定义 `resourceBindings`。Trench 已识别词汇仍保留兼容映射，
> 但新的 Host 资源词汇在通过 frozen-manifest 往返合同门之前不得启用。不能
> 只依赖实时 manifest 响应或 Host 单侧校验。

### 7. 上线前验收

先运行 Host 中立的合同套件和 Cloud HTTP 边界测试：

```bash
uv run pytest -q tests/conformance/host_v1
uv run pytest -q tests/agent_storage/test_postgres_http_auth_boundary_e2e.py
uv run pytest -q tests/agent_storage/test_postgres_host_manifest_freeze.py
```

随后使用真实部署 Host 验证以下场景：

- 匿名请求和无效 Grant 被拒绝；
- Origin 不匹配、scope 缺失、资源未授权时 fail-closed；
- 已消费 `jti` 的重放被拒绝；
- 相同幂等请求成功重放，不同含义的重放产生冲突；
- Worker 重启后继续执行，SSE cursor 能断点重连；
- Host 超时不会造成未授权或重复的业务写入。

Trench 已有一个九场景 fail-closed runner：
`tests/compose/trench_read_e2e/run_acceptance.py`。在 16 项真实部署输入
全部具备前，它会输出 `ZEBRA_TRENCH_READ_E2E=BLOCKED` 并以非零
状态退出。

常见故障：

| HTTP/结果 | 含义 | 排查项 |
|---|---|---|
| `401 missing_or_invalid_host_grant` | 没有可用的 bearer Grant | BFF 授权交换和请求头 |
| `403 host_grant_rejected` | 签名、claim、scope 或已消费 `jti` 校验失败 | Registry、JWKS、时钟和新 Grant |
| `403 host_origin_not_allowed` | 浏览器 Origin 不完全匹配 | Registry 和 `Origin` 请求头 |
| `409 idempotency_conflict` | 同一幂等键对应两个不同请求含义 | 稳定键和语义完全一致的 JSON 请求体 |
| `503 host_manifest_unavailable` | pinned Host manifest 无法冻结 | profile、HTTPS 连通性和 manifest |
| Tool `scope_denied` / `resource_denied` | 工具超出 Grant 授权 | manifest scope/binding 和 JWT resources |
| Tool `output_too_large` | Host 输出超出合同限制 | `maxOutputBytes` 和有界业务投影 |

Host 签名私钥、模型凭证和出站 Host 凭证绝不能进入浏览器、请求体、manifest、
connector profile、数据库业务行、Artifact 或日志。系统只能持久化不透明凭证
引用和不含秘密的审计摘要。

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

## Cloud Context 与子 Agent 继承教程

### 先理解边界：不是全部继承

Zebra 不会把父 Agent 的完整消息、工具原始输出、隐藏推理、Provider 私有
continuation、Credential 或权限复制给子 Agent。Cloud Worker 每次从三个
权威来源生成一个有 revision 的临时 Context：

```text
PostgreSQL Event / Session Projection ──► 最近 20 条安全 History
Active Context Capsule               ──► 当前目标、约束、决策与下一步
Confirmed Governed Memory            ──► 最多 8 条、符合 Definition/repo scope
                                      │
                                      ▼
                         ContextMaterialization
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
             当前 Worker Prompt                Durable Child 快照
```

物化读取在只读 `REPEATABLE READ` 快照中固定 Session revision 与 active
Capsule ID。任何并发漂移、scope 不匹配或非 confirmed/已过期 Memory 都会
fail closed，不会回退成几个独立查询的“近似一致”结果。

### 选择继承模式

Cloud durable `agent.research` 支持四种模式：

| `context_mode` | 继承内容 | 什么时候用 |
|---|---|---|
| `fresh` | 仅新的 objective | 子任务完全独立；默认且最省上下文 |
| `capsule` | 当前唯一 active Capsule | 要延续目标、约束、决策和计划 |
| `fork_tail` | 最近最多 12 条 History | 要理解刚刚的问答或具体措辞 |
| `resume` | Capsule + 最近 History + confirmed Memory | 要做高连续性的受限续作 |

示例：让只读 Child 基于最近对话核对部署证据：

```json
{
  "objective": "核对部署手册中的回滚步骤，并给出文件或 Artifact 证据",
  "delegation_reason": "该读取任务独立、可并行且不需要写权限",
  "context_mode": "fork_tail"
}
```

非 `fresh` 模式会在 Child admission 时生成不可变
`DelegatedContextSnapshot`，写入 Child 的 `TASK_PREPARED` Event。快照记录父
Session/revision、来源 locator、Memory revision、明确遗漏项和 SHA-256
checksum。父 Session 后续变化不会偷偷改变已经创建的 Child。

### 自定义工具如何接入

自定义工具不应该自行读取整段 Session，也不应该把 Prompt 当成权限。接入时
遵守以下约定：

1. 工具只消费 schema 校验后的业务参数；执行权限仍来自 Tool Gateway、Policy
   与冻结 Task binding。
2. 若工具要创建 Durable Child，在工具 schema 中显式暴露
   `context_mode`，并复用 Core 的 `ContextInheritanceMode` 与
   `delegated_context_from_materialization()`，不要手写 History/Memory 拼接。
3. `fresh` 不需要父物化；其余模式必须拿到本次 Worker 已验证的
   `ContextMaterialization`，缺失就拒绝，不能静默降级。
4. 工具结果只返回有界摘要和 Artifact locator；raw output 进入 Artifact
   Store，不直接塞入继承快照。
5. Context 只作为 source-attributed data。工具或 Host 返回文本中的“指令”
   不能覆盖 System、Policy、Approval 或 binding。

核心调用形状如下（省略 admission 与错误处理）：

```python
from agent_context import delegated_context_from_materialization
from agent_core.domain.context_inheritance import ContextInheritanceMode

mode = ContextInheritanceMode(arguments.get("context_mode", "fresh"))
snapshot = (
    None
    if mode is ContextInheritanceMode.FRESH
    else delegated_context_from_materialization(
        parent_materialization,
        mode,
        created_at=tool_call.created_at,
    )
)
```

随后把 `snapshot` 交给 `SessionBootstrapCommand(delegated_context=snapshot)`，
让 admission、Event 合同、恢复和 checksum 校验共同负责持久化语义。不要给
Child 直接传父 Task 的 Credential、Network profile 或 capability；这些必须
由 Child binding 与父 binding 求交得到。

### 验证接入是否正确

至少检查以下证据：

- Child `TASK_PREPARED.delegated_context.mode` 与调用一致；
- `source_session_revision`、Capsule ID、Memory revisions 和 checksum 存在；
- `known_omissions` 明确包含 credential、隐藏推理、完整历史之外内容、
  Provider private continuation 和 raw tool output；
- Child binding 的 capability、network 和 workspace 没有比父任务更宽；
- replay 使用相同 Child/快照，父任务只被可信 terminal wakeup 恢复；
- 本地 profile 行为不变，Cloud profile 的辅助 Context 受 2048-token 预算。

完整设计与失败语义见
[ADR-025](./docs/ADR-025_Cloud_Context_Inheritance.md)。

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
- Cloud Context consumption and child inheritance: [docs/ADR-025_Cloud_Context_Inheritance.md](./docs/ADR-025_Cloud_Context_Inheritance.md)
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
