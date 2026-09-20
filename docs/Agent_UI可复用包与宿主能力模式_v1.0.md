# Agent UI 可复用包与宿主能力模式 v1.0

## 目标

Zebra 是完整的 Cloud Agent Runtime，Trench 只是第一个 Host。前端以可拆分为
独立 npm 包为边界设计，不把订阅、资讯或 Trench API 写进通用组件。

## 稳定边界

通用 Agent UI 只消费以下 Host 无关能力：

- 会话与 Durable Turn 的创建、暂停、继续、重放和终态；
- 标准化执行事件，包括公开进度、工具状态、审批、澄清、产物和最终回答；
- 模型、思考强度和产品级能力模式；
- 附件输入、上下文用量、待处理补充消息和错误恢复。

业务系统通过 adapter 提供 API client、身份、文案、建议、附件策略和 Host Tools。
`AgentComposer`、执行时间线与消息渲染不得直接依赖 Trench 领域类型。

## 能力模式

浏览器只能选择稳定的产品级枚举，不能申请原始 Zebra 权限：

用户界面使用“探索 / 研究 / 专家”描述 Agent 的工作风格，避免直接暴露
Tool profile 和权限术语；下表中的枚举仅用于内部协议兼容。

| 模式 | Tool profile | Policy profile | 网络 | 默认预算 |
|---|---|---|---|---|
| `research` | `research_coordinator` | `workspace_write` | `mcp-proxy-only` | 10 model / 16 tool |
| `general` | `general` | `full_access` | `mcp-proxy-only` | 16 model / 32 tool |
| `coding` | `coding` | `full_access` | `mcp-proxy-only` | 24 model / 64 tool |

这里的 `full_access` 不是绕过治理：高风险工具仍经过 Policy、审批、Grant、沙箱、
网络出口和审计。Host adapter 负责把产品枚举映射为服务端批准的 preset。

## 生命周期

Tool、Policy、网络和预算在 Zebra Task admission 时冻结。能力模式变化必须改变
task generation，创建 successor task，并携带有界的 Host 会话上下文。前端显示的
模式因此与实际执行权限一致；旧客户端未提交模式时保持 `research` 兼容默认值。

## npm 拆分路径

1. 保持通用 composer、timeline、message renderer 只接收 props 和稳定事件类型。
2. `@zebra-agent/ui-contracts` 已建立，发布事件、状态、能力模式、完成评估和
   adapter 接口；它不依赖 React 或任何 Host 领域包。
3. 抽出 `@zebra-agent/react`，提供无业务依赖的组件与 hooks。
4. Trench 仅保留 adapter、主题、业务文案和 Host Tool 展示扩展。

当前只物理拆出稳定 contracts；React 组件继续保留在第一个 Host 内，等第二个 Host
接入并验证相同交互后再抽 `@zebra-agent/react`，避免过早冻结样式 API。
