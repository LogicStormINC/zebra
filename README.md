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
the verified baseline. See [docker/README.md](./docker/README.md). Read
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
- `packages/`: core, context, integrations, observability, runtime, security,
  storage, and tools
- `UI/desktop/`: React, Ant Design X, Lobe UI, and Tauri desktop workspace
- `tests/`: deterministic, contract, smoke, and integration coverage
- `evals/`: release and provider evaluation cases
- `docs/`: architecture, governance, acceptance records, and operator runbooks
- `docker/`: dependency Compose and optional auxiliary-service overlays; no Zebra
  application image exists yet

`agent-core` remains infrastructure-independent. Other packages may depend on
core; packages must not import from applications.

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
