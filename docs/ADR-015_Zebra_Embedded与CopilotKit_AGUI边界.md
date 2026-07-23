# ADR-015：Zebra Embedded 与 CopilotKit / AG-UI 集成边界

| 字段 | 值 |
|---|---|
| 状态 | Accepted for architecture；implementation Locked |
| 日期 | 2026-07-23 |
| 决策者 | Maintainer direction + Zebra architecture baseline |
| 影响范围 | Zebra Embedded、Trench Host、AG-UI、前端协同、持久状态 |

## 背景

Zebra Embedded 需要嵌入 Trench 页面，支持流式消息、工具展示、共享状态、
Frontend Tool 和 durable approval。早期草案提出建设 Zebra React SDK，包含
Provider、hooks、状态同步和组件渲染。

这会重复 CopilotKit React v2 已提供的前端能力，并让 Zebra 同时维护 Python
Runtime、AG-UI 协议和 React SDK 三个兼容面。更重要的是，前端 SDK 很容易被
误用为 Task、Thread、Approval 或 State 的事实源，破坏 Zebra 已有的 durable
event/replay 边界。

CopilotKit 当前正式架构由 React frontend、Host application server 内的
Copilot Runtime 和 AG-UI-compatible agent backend 组成：

- [CopilotKit v2 API](https://docs.copilotkit.ai/reference/v2)
- [CopilotKit Architecture](https://docs.copilotkit.ai/concepts/architecture)
- [Copilot Runtime](https://docs.copilotkit.ai/a2a/backend/copilot-runtime)

## 决策

### 1. 不建设 Zebra React SDK

取消以下计划：

```text
@zebra-agent/core
@zebra-agent/react
@zebra-agent/ag-ui
ZebraProvider
useZebraRun
useZebraContext
useZebraSharedState
useZebraFrontendTool
useZebraApproval
useZebraArtifact
useZebraPresence
```

Zebra monorepo 不增加 TypeScript SDK workspace，也不承担 Trench UI 组件的
版本发布。

### 2. Trench 直接采用 CopilotKit React v2

生产拓扑固定为：

```text
Trench React
→ @copilotkit/react-core/v2
→ Trench Copilot Runtime / BFF
→ AG-UI
→ Zebra Embedded
```

Trench 使用 `<CopilotKit runtimeUrl="/api/copilotkit">`、`useAgent`、
`useAgentContext`、`useFrontendTool`、`useInterrupt` 和必要的 renderer。

生产禁止通过 `agents__unsafe_dev_only` 从浏览器直连 Zebra。该路径只允许
compatibility spike。Copilot Runtime 必须运行在 Trench 服务端，负责登录态
验证、Header allowlist、HostSessionGrant 交换和 agent routing。

### 3. Zebra 只实现 AG-UI 服务端 Adapter

Zebra 在 `agent-integrations` 和 API composition boundary 内实现薄 AG-UI
adapter：

- 接受版本化 `RunAgentInput`；
- 将稳定 Task ID 暴露为 `threadId`；
- 将 Segment attempt 投影为不透明 `runId`；
- 将 Domain Event 确定性投影为 AG-UI Event；
- 支持 SSE、cursor replay、cancel 和 durable interrupt resume；
- pin `ag-ui-protocol` 版本并通过 golden fixtures 检测协议漂移。

AG-UI 是外部 wire projection，不进入 `agent-core` 的基础设施依赖，也不成为
新的 Event Store。

### 4. Zebra durable state 始终是权威

以下事实不委托给 CopilotKit：

- Task、Segment、Session Event 和 message lineage；
- Policy、Approval、Clarification 和 open interrupt；
- Tool Call、Effect Ledger、Action/Business Receipt；
- Artifact、Snapshot、replay cursor 和 recovery；
- namespace authority 和技术配额。

CopilotKit Threads 或 Enterprise persistence 可以作为 Host UI 能力评估，但
不能替代 Zebra Task/Event Store，也不能被 Zebra recovery 依赖。

### 5. Durable approval 使用标准 AG-UI interrupt

Zebra Policy 先持久化 Approval/Clarification，然后以 `RUN_FINISHED` interrupt
outcome 对外投影。在终止事件前发送恢复所需的 State/Messages snapshot。

Trench 通过同一 `threadId` 的 `resume[]` 回答。Zebra 验证 interrupt ID、
expiry、response schema、authority 和 idempotency。`useHumanInTheLoop` 或任意
LLM 选择的 frontend interaction 都不能绕过该流程。

参考：[AG-UI Interrupts](https://docs.ag-ui.com/concepts/interrupts)。

### 6. CopilotKit 不覆盖的协议仍由 Zebra/Trench 实现

- HostSessionGrant 与 opaque `namespace_id`；
- Surface Lease 和页面 presence；
- Shared State ownership/version/conflict/resync；
- Frontend Capability Manifest 和 Action Receipt；
- Artifact signed access 和 structured provenance；
- Host Tool scope intersection、Trench re-authorization 和 Business Receipt。

## 安全约束

1. 浏览器只向 Trench BFF 证明登录态，不直接提供 Zebra service credentials。
2. BFF 生成的服务端 Header 覆盖同名浏览器 Header。
3. Zebra 独立验证 issuer、audience、JWKS、algorithm、jti、expiry、origin、
   namespace、resource refs、scopes 和 technical limits。
4. 原始 Grant 不进入 Event Store、Artifact、trace 或日志。
5. CORS 使用 exact origin allowlist，production 不允许 wildcard。
6. Trench Backend Tool 在执行时重新做业务授权；Zebra approval 不替代它。

## 兼容性门禁

进入生产实现前必须完成两个独立 Spike：

1. Zebra 仓库验证 Python AG-UI encoding、event mapping、interrupt/resume、
   reconnect 和 replay；
2. Trench 仓库验证 CopilotKit v2 Runtime/BFF、HttpAgent、Header policy、
   frontend tool 和 UI rendering。

Spike 必须固定：

- CopilotKit 和 `ag-ui-protocol` 精确版本；
- OSS/Enterprise 能力边界和许可证决策；
- 生产连接方式与升级策略；
- unknown event、schema drift 和 downgrade 行为。

## 结果

### 正向结果

- 删除一套重复的 React SDK 和发布流水线；
- 复用 CopilotKit 当前 v2 UI、hooks 和 Runtime；
- Zebra 保持 Headless、protocol-first 和 frontend-neutral；
- Trench 可更换 UI 组件而不改变 Zebra durable core；
- AG-UI adapter 可以通过 contract tests 独立演进。

### 成本与风险

- CopilotKit 和 AG-UI 仍在快速演进，必须 pin 版本并做每日/升级契约测试；
- 一些 CopilotKit persistence/operations 能力可能涉及 Enterprise 产品，不能
  在未确认许可证前成为硬依赖；
- Surface Lease、durable approval 和 Receipt 仍需 Zebra/Trench 自己实现；
- 跨仓库 E2E 需要明确版本矩阵和可重复环境。

## 被拒绝的方案

### Zebra 自研 React SDK

拒绝。重复现有能力，扩大维护和兼容面，并容易产生第二事实源。

### 浏览器直接连接 Zebra AG-UI

拒绝用于生产。失去 Trench 服务端 auth、Header policy、routing 和中间件边界。

### CopilotKit 作为持久 Task/Thread 权威

拒绝。与 Zebra durable Event Store、replay、approval 和 recovery 合同冲突。

### Zebra API 内嵌 Copilot Runtime

拒绝。Copilot Runtime 属于 Host application server，并以 Node/Trench 生命周期
运行；Zebra 只提供协议端点。

## 后续任务

任务顺序、Owned paths 和阶段门禁见：

- [`Zebra Embedded 生产级目标架构.md`](./Zebra%20Embedded%20生产级目标架构.md)
- [`Zebra Embedded与Trench实施任务拆解_v1.0.md`](./Zebra%20Embedded与Trench实施任务拆解_v1.0.md)
- [`AGENT_TASKS.md`](./AGENT_TASKS.md)
