# Zebra 智能体接入与治理中台前端产品需求文档

**文档版本：** v1.0  
**文档状态：** Draft  
**产品形态：** PC Web 管理控制台  
**编写日期：** 2026-08-26  
**代码评估基线：** `LogicStormINC/zebra@efd4e2938d14c6598e9c60503830abf5360fa0bf`  
**首个试点业务：** Trench  
**后续目标业务：** Jazz 及其他内部业务系统  

---

## 1. 文档目的

本 PRD 定义 Zebra 智能体接入与治理中台的前端产品范围、信息架构、页面结构、核心流程、权限模型、交互规范、技术实现边界和验收标准。

该中台面向平台管理员、接入工程师、Agent 发布人员、运行运维人员、安全审计人员和业务观察人员，主要解决以下问题：

1. 新业务系统接入 Zebra Cloud Agent 的过程依赖人工配置和代码修改。
2. Host 入站信任、出站 Connector、Capability Manifest、AgentDefinition、策略和配额分散管理。
3. 后端 Tool 与前端 Hook 缺少统一注册、验证、发布、绑定和回滚界面。
4. Task、Attempt、Orchestration、Subagent、Effect、Client Effect 和 Artifact 缺少统一运行观测入口。
5. Agent 接入后的权限、成本、异常、审计和发布状态难以形成完整运营闭环。
6. Trench、Jazz 等业务接入时，平台团队缺少标准化的自助接入流程和验收工具。

---

## 2. 代码现状与产品前提

### 2.1 当前代码现状

当前 Zebra 仓库包含以下应用：

```text
apps/api
apps/cli
apps/config
apps/worker
```

当前仓库尚未包含正式的管理端 Web 应用。

`packages/agent-control-plane` 已经存在，但当前应用服务仍很薄，主要承担路由动作和权限范围定义。Host Authority、Connector Registry、Agent Registry、Task Binding、Orchestration、Subagent Delegation、AG-UI 等能力已经分别存在于 Core、Storage、API、Worker 和 Integration 层。

### 2.2 前端建设前提

中台前端基于以下架构前提设计：

```text
Zebra Agent Platform
├── Agent Control Plane
├── Host Backend Integration Plane
├── Host Client Integration Plane
└── Runtime / Data Plane
```

中台前端只调用 Management API 和 Runtime Query API，不直接访问 PostgreSQL、Redis、对象存储或 Worker。

### 2.3 产品定位

产品名称建议：

> Zebra Agent Platform Console

中文名称：

> Zebra 智能体接入与治理中台

核心定位：

> 为多业务系统提供 Agent 接入、能力适配、发布治理、运行观测、前端 Hook 管理和安全审计的一站式平台。

---

## 3. 产品目标

### 3.1 核心目标

| 目标 | 说明 | 衡量方式 |
|---|---|---|
| 降低接入成本 | 将 Host 接入从工程配置流程转为可视化向导 | 新 Host 首次接入所需人工步骤减少 |
| 建立统一治理 | 统一管理 Host、Connector、Manifest、Agent、Policy 和 Quota | 所有运行 Task 都可追溯到固定版本和 Digest |
| 提升运行可观测性 | 统一查看 Task、Attempt、Tool、Effect、Client Effect 和 Orchestration | P0 故障可在单一任务详情页定位 |
| 支持前后端协同 Agent | 同时管理 Host Backend Tool 和 Frontend Hook | 可完成 Readable 注入与 Client Action 执行闭环 |
| 提供安全边界 | 将权限、资源、版本、凭据引用和审批纳入平台治理 | 越权场景产生零业务写入 |
| 支持多业务复制 | Trench 接入经验可直接复制到 Jazz | 新业务接入无需修改 Zebra Core 和 Worker 业务分支 |

### 3.2 非目标

V1 不包含以下能力：

1. 面向外部开发者的公开 Agent Marketplace。
2. 任意 JavaScript、DOM Selector 或浏览器脚本控制。
3. 在管理后台中直接编写业务系统 Hook Handler 代码。
4. 在管理后台中保存明文 Secret、Token、密码或私钥。
5. 通过前端 Hook 完成正式业务数据库写入。
6. 完整的移动端管理后台。
7. 跨部署区域的全局多活控制台。
8. 面向普通终端用户的业务 Copilot UI。
9. 通用低代码业务页面生成器。

---

## 4. 用户角色

### 4.1 角色定义

| 角色 | 核心职责 |
|---|---|
| Platform Owner | 平台最高负责人，管理环境、全局策略、发布门禁和高风险操作 |
| Platform Admin | 管理 Host、Connector、Manifest、Agent、Policy 和绑定 |
| Integration Engineer | 完成业务系统接入、Manifest 配置、Hook Profile 配置和 Conformance |
| Agent Publisher | 创建 AgentDefinition、发布 Agent Release、维护模型与能力配置 |
| Runtime Operator | 监控 Task、Worker、Effect、Client Session 和运行异常 |
| Security Auditor | 查看权限、审计、越权拒绝、凭据引用和高风险操作 |
| Business Observer | 只读查看本业务 namespace 的 Task、Usage、Artifact 和运行状态 |
| Support Engineer | 处理接入联调和运行故障，具备受限诊断权限 |

### 4.2 权限原则

1. 管理 API 使用 Platform Operator Identity。
2. 运行 API 使用 HostGrant 或受控的内部查询身份。
3. 普通业务 HostGrant 无权修改 Connector、Manifest、AgentDefinition、Policy 和 Quota。
4. 高风险操作要求二次确认、原因填写和审计记录。
5. 前端根据权限隐藏不可用操作，同时保留服务端最终授权校验。
6. 只读用户无法通过直接 URL 或请求重放执行写操作。

---

## 5. 核心用户场景

### 5.1 新业务系统接入

Integration Engineer 通过接入向导完成：

```text
注册 Host
→ 配置入站信任
→ 发布出站 Connector
→ 提交 Backend Manifest
→ 发布 Frontend Capability Profile
→ 绑定 Agent Release
→ 配置 Policy 与 Quota
→ 运行 Conformance
→ Dry Run
→ Canary
→ Production
```

### 5.2 Agent 发布

Agent Publisher 完成：

```text
创建 Draft
→ 配置 Capability Ceiling
→ 选择 Model、Tool、Memory、Runtime Policy
→ 校验
→ Materialize Version
→ 发布 Release
→ 绑定 Host 或 namespace
→ Canary
→ Promote
```

### 5.3 运行故障诊断

Runtime Operator 完成：

```text
检索 Task
→ 查看 Task Binding
→ 查看 Event Timeline
→ 查看 Attempt
→ 查看 Model 和 Tool 调用
→ 查看 Host Effect 和 Client Effect
→ 查看 Subagent 与 Orchestration
→ 定位失败原因
→ 执行允许的恢复操作
```

### 5.4 前端 Hook 接入

前端工程师和 Integration Engineer 完成：

```text
创建 Frontend Profile
→ 定义 Readable
→ 定义 Action
→ 生成 Hook 代码片段
→ 前端集成
→ 运行 Mounted Capability 检查
→ 执行 Client Effect E2E
→ 发布 Profile Revision
```

### 5.5 安全审计

Security Auditor 完成：

```text
选择时间范围和 namespace
→ 查看 Grant、Binding、Connector、Effect 和发布操作
→ 查看拒绝原因
→ 导出审计证据
```

---

## 6. 产品设计原则

### 6.1 版本不可变

已发布的以下对象不允许原地编辑：

```text
Connector Profile Version
Backend Capability Manifest Version
Frontend Capability Profile Version
AgentDefinition Version
Agent Release
Policy Version
TaskBindingSnapshot
ClientRunBindingSnapshot
```

修改操作统一采用“创建新版本”。

### 6.2 Digest 可见

所有关键页面显示：

```text
Revision
Digest
Status
Created By
Created At
Effective Scope
```

Digest 默认显示前 12 位，支持复制完整值和打开版本差异。

### 6.3 事实与投影分离

前端应清晰区分：

```text
Durable Fact
Projection
Live Status
Derived Metric
```

例如 Task Event 是事实，Task 列表中的聚合状态属于投影，Redis Live Stream 属于加速通道。

### 6.4 高风险操作显式化

以下操作必须使用风险确认弹窗：

```text
Revoke
Force Cancel
Rollback Binding
Disable Host
Promote to Production
Approve Sensitive Effect
Release Controller Lease
```

确认弹窗必须显示影响范围、不可逆性、当前 revision、目标 revision 和审计原因。

### 6.5 禁止显示明文凭据

平台只显示：

```text
credential_ref
workload_identity_ref
secret provider
last rotated at
health status
```

任何明文 Secret 都不进入页面、日志、浏览器存储或前端错误信息。

---

## 7. 信息架构

### 7.1 一级导航

```text
概览
接入中心
Agent 资产
运行中心
前端能力
质量与发布
治理与审计
系统设置
```

### 7.2 完整导航树

```text
概览
└── 平台总览

接入中心
├── 接入向导
├── Host 应用
├── 入站信任
├── Connector
├── Backend Manifest
└── Namespace Binding

Agent 资产
├── AgentDefinition
├── Agent Release
├── Capability Profile
├── Model Policy
├── Tool Policy
├── Memory Policy
└── Runtime Policy

运行中心
├── Task
├── Orchestration
├── Subagent
├── Approval 与 Clarification
├── Host Effect
├── Artifact
└── Worker 状态

前端能力
├── Frontend Profile
├── Hook Contract
├── Client Session
├── Client Run Binding
├── Client Effect
└── Mounted Capability Inspector

质量与发布
├── Conformance Run
├── Dry Run
├── Rollout
├── Evaluation
└── Release Gate

治理与审计
├── Policy
├── Quota
├── Usage 与成本
├── Audit Log
├── Security Findings
└── Effect Reconciliation

系统设置
├── Environment
├── Operator 与角色
├── Feature Flag
├── Credential Provider
├── Notification
└── Platform Health
```

### 7.3 推荐路由

```text
/overview

/integrations/onboarding
/integrations/hosts
/integrations/hosts/[hostId]
/integrations/trust
/integrations/connectors
/integrations/connectors/[connectorId]
/integrations/backend-manifests
/integrations/backend-manifests/[manifestId]
/integrations/bindings

/agents/definitions
/agents/definitions/[definitionId]
/agents/releases
/agents/capability-profiles
/agents/policies/models
/agents/policies/tools
/agents/policies/memory
/agents/policies/runtime

/runtime/tasks
/runtime/tasks/[taskId]
/runtime/orchestrations
/runtime/orchestrations/[runRef]
/runtime/subagents
/runtime/approvals
/runtime/host-effects
/runtime/artifacts
/runtime/workers

/frontend/profiles
/frontend/profiles/[profileId]
/frontend/hooks
/frontend/client-sessions
/frontend/client-bindings
/frontend/client-effects
/frontend/mounted-inspector

/quality/conformance
/quality/conformance/[runId]
/quality/dry-runs
/quality/rollouts
/quality/evaluations
/quality/release-gates

/governance/policies
/governance/quotas
/governance/usage
/governance/audit
/governance/security
/governance/reconciliation

/system/environments
/system/operators
/system/feature-flags
/system/credentials
/system/notifications
/system/health
```

---

## 8. 全局页面框架

### 8.1 页面结构

```text
┌──────────────────────────────────────────────────────────────────┐
│ Zebra Logo  环境选择  Namespace  全局搜索  告警  用户菜单        │
├───────────────┬──────────────────────────────────────────────────┤
│ 左侧一级导航  │ 页面标题              主操作按钮                  │
│               │ 面包屑                状态与版本信息              │
│               ├──────────────────────────────────────────────────┤
│               │ 主内容区                                          │
│               │                                                   │
│               │                                                   │
└───────────────┴──────────────────────────────────────────────────┘
```

### 8.2 顶部栏

顶部栏包含：

1. 产品 Logo 和名称。
2. Environment Selector。
3. Deployment Namespace Selector。
4. 全局搜索。
5. 待处理 Approval 数量。
6. Uncertain Effect 数量。
7. 平台健康状态。
8. 当前用户和角色。

### 8.3 左侧导航

1. 默认宽度 248px。
2. 支持折叠为图标模式。
3. 显示当前模块和页面高亮。
4. 根据 RBAC 隐藏无权访问模块。
5. 运行异常模块显示角标。
6. 页面刷新后保留折叠状态。

### 8.4 全局搜索

支持搜索：

```text
Task ID
Session ID
Run Ref
Host App ID
Namespace ID
AgentDefinition
Agent Release
Connector ID
Effect ID
Artifact ID
Client Session ID
Digest
```

搜索结果按实体类型分组，并支持键盘导航。

### 8.5 全局环境提示

非生产环境顶部显示环境色条。

Production 环境执行写操作时，确认弹窗必须显示：

```text
当前环境
当前 Host
当前 namespace
操作对象
影响范围
```

---

## 9. 平台总览页

### 9.1 页面目标

让 Platform Owner 和 Runtime Operator 在一个页面掌握平台接入规模、运行质量、安全风险和成本状态。

### 9.2 页面布局

第一行 KPI：

```text
已接入 Host
已发布 Agent
过去 24 小时 Task
Task 成功率
等待与阻塞 Task
Uncertain Effect
今日 Token
今日成本
```

第二行图表：

```text
Task 趋势
成功率趋势
模型 Token 与成本趋势
Host 调用延迟
```

第三行：

```text
高优先级告警
最近发布
最近接入
待处理审批
```

### 9.3 KPI 交互

1. 每个 KPI 支持点击跳转到预置筛选列表。
2. 时间范围支持 1h、24h、7d、30d 和自定义。
3. 支持按 Host、namespace、Agent Release 过滤。
4. 数据刷新频率默认 30 秒。
5. Task 和 Effect 类指标支持 Live 更新。

### 9.4 空状态

尚未接入 Host 时显示：

```text
欢迎使用 Zebra Agent Platform
开始第一个 Host 接入
查看接入文档
导入示例配置
```

---

## 10. 接入中心

## 10.1 Host 列表页

### 列表字段

| 字段 | 说明 |
|---|---|
| Host 名称 | 业务系统显示名称 |
| Host App ID | 稳定机器标识 |
| Owner | 负责人或团队 |
| Environment | dev、staging、production |
| Inbound Trust | healthy、warning、invalid |
| Connector | 当前绑定版本 |
| Backend Manifest | 当前发布版本 |
| Frontend Profile | 当前发布版本 |
| Agent Releases | 已绑定数量 |
| Conformance | 最近一次结果 |
| Status | draft、active、suspended、revoked |
| Updated At | 最近更新时间 |

### 列表操作

```text
创建 Host
进入详情
继续接入
运行 Conformance
暂停接入
查看审计
```

### 筛选条件

```text
Status
Environment
Owner
Trust Health
Connector Status
Conformance Result
是否具有 Frontend Profile
```

---

## 10.2 Host 详情页

### 页面头部

显示：

```text
Host 名称
Host App ID
Environment
Status
Owner
Current Connector
Backend Manifest
Frontend Profile
Active Agent Releases
Last Conformance
```

### Tab 结构

```text
Overview
Inbound Trust
Outbound Connector
Backend Capabilities
Frontend Capabilities
Namespace Bindings
Agent Bindings
Conformance
Usage
Audit
```

### Overview 内容

1. 接入完成度。
2. 依赖健康状态。
3. 已绑定 namespace。
4. 过去 24 小时 Task。
5. Task 成功率。
6. Effect 异常。
7. Client Session 活跃数。
8. 版本漂移告警。
9. 最近操作记录。

---

## 10.3 Host 接入向导

### 向导步骤

#### Step 1 基础信息

字段：

```text
Host Name
Host App ID
Owner Team
Environment
Description
Contact
Tags
```

校验：

1. Host App ID 全局唯一。
2. ID 发布后不可修改。
3. Production Host 必须填写 Owner 和 Contact。

#### Step 2 入站信任

字段：

```text
Issuer
Audience
JWKS URI
Allowed Origins
Algorithms
Policy Version
Namespace Strategy
```

页面能力：

```text
Test JWKS
Verify Sample Grant
Preview Parsed Claims
Check Origin
Check Clock Skew
```

禁止展示完整 Token。

#### Step 3 出站 Connector

字段：

```text
Connector ID
Base URI
Manifest Path
Invoke Path
Reconcile Path
Protocol Versions
Workload Identity Ref
Credential Ref
Network Policy Ref
Timeout Policy
Retry Policy
```

页面能力：

```text
Endpoint Health Check
TLS Check
Manifest Fetch
Credential Ref Check
Network Policy Check
```

#### Step 4 Backend Manifest

支持：

```text
上传 JSON
粘贴 JSON
从 Connector 拉取
可视化编辑
```

校验内容：

```text
Tool Name
Capability
Grant Scope
Resource Binding
Risk
Idempotency
Timeout
Output Limit
Effect Reconcile
Contract Digest
```

#### Step 5 Frontend Capability Profile

字段：

```text
Frontend App ID
Profile Revision
Build ID
Allowed Origins
Readables
Actions
Components
Client Policy
```

页面提供 React Hook 示例代码和 Runtime Mount 检查。

#### Step 6 Agent 与策略

选择：

```text
Agent Release
Capability Profile
Policy
Quota
Model Policy
Runtime Policy
Approval Policy
```

显示最终 Effective Capability Preview。

#### Step 7 验证与发布

依次执行：

```text
Schema Validation
Backend Conformance
Frontend Conformance
Dry Run
Binding Preview
Security Review
Canary Plan
```

所有 P0 检查通过后才能发布到 Production。

### 向导通用交互

1. 每一步自动保存 Draft。
2. 支持退出后继续。
3. 页面右侧显示接入检查清单。
4. 已发布对象修改时自动进入新版本流程。
5. 每一步显示修改对象和影响范围。
6. 最终发布前显示完整 Diff。

---

## 11. Connector 管理

## 11.1 Connector 列表

字段：

```text
Host App ID
Connector ID
Latest Revision
Bound Revision
Status
Base URI
Protocol
Credential Ref
Health
Updated At
```

## 11.2 Connector 详情

Tab：

```text
Overview
Versions
Namespace Bindings
Health Checks
Manifest
Credential Reference
Network Policy
Audit
```

### 版本规则

1. Published Revision 不可编辑。
2. 更新 Endpoint、Path、Credential Ref 或 Protocol 时创建新 Revision。
3. Deprecated Revision 可以继续服务已绑定 Task。
4. Revoked Revision 对新旧调用全部 fail closed。
5. 绑定升级需要 expected revision。
6. 支持查看版本 Diff。
7. 支持回滚 namespace binding 到历史 Revision。

### Revoke 交互

确认弹窗显示：

```text
受影响 Host
受影响 namespace
运行中 Task
等待中的 Client Effect
未完成 Host Effect
最近 24 小时调用量
```

---

## 12. Backend Capability Manifest

## 12.1 Manifest 列表

字段：

```text
Host App ID
Manifest ID
Revision
Protocol Version
Tool Count
Read Tools
Write Tools
Reconcile Tools
Digest
Status
Conformance
```

## 12.2 Manifest 编辑器

页面采用三栏布局：

```text
左栏 Tool 列表
中栏 Tool Contract 表单
右栏 JSON 与校验结果
```

### Tool Contract 表单

字段：

```text
Name
Description
Capabilities
Required Grant Scopes
Arguments Schema
Resource Bindings
Risk
Parallel Safe
Idempotency
Timeout
Max Output Bytes
Effect Reconcile Capable
```

### 校验规则

1. Tool Name 唯一。
2. Capability 必须来自已发布词汇表。
3. Resource Binding 只能使用受限 JSON Pointer。
4. Write Tool 必须声明 Idempotency。
5. 可能产生未知结果的写 Tool 必须支持 Reconcile。
6. Argument 和 Result Schema 有大小上限。
7. Manifest 中不得包含 Secret。
8. 与本地 Tool 重名时发布失败。

### 发布前检查

```text
Schema
Digest
Scope
Resource Binding
Risk
Idempotency
Reconcile
Compatibility
Conformance
```

---

## 13. Frontend Capability Profile

## 13.1 页面目标

统一管理业务前端通过 Hook 注入给 Zebra Agent 的 Readable、Action、Component 和 Human Interaction 能力。

## 13.2 Profile 列表

字段：

```text
Host App ID
Frontend App ID
Profile Revision
Build ID
Origins
Readables
Actions
Components
Mounted Clients
Digest
Status
Conformance
```

## 13.3 Profile 详情页

Tab：

```text
Overview
Readables
Actions
Components
Origins 与 Build
Hook Code
Mounted Snapshot
Client Policy
Versions
Conformance
Audit
```

---

## 13.4 Readable 编辑

字段：

```text
Name
Description
JSON Schema
Sensitivity
Max Bytes
Redaction Rules
Update Strategy
Context Priority
Resource Binding
```

Sensitivity：

```text
public
internal
confidential
restricted
```

Update Strategy：

```text
on_mount
on_change
manual
debounced
```

页面提供：

```text
示例值校验
脱敏预览
Prompt Context 预览
大小估算
```

禁止接入：

```text
Cookie
Token
Secret
完整 Redux Store
完整 Zustand Store
高频鼠标轨迹
完整业务数据表
```

---

## 13.5 Action 编辑

字段：

```text
Name
Description
Capability
Parameters Schema
Result Schema
Risk
Resource Bindings
Execution Mode
Timeout
Max Result Bytes
Requires Controller
Requires User Confirmation
Allowed Routes
```

Risk：

```text
presentation
navigation
local_state
user_interaction
```

Execution Mode：

```text
fire_and_receipt
receipt_required
human_confirmed
```

页面校验：

1. Action 名称必须属于当前 Host 或平台命名空间。
2. Action 不允许声明正式业务写入能力。
3. 参数和返回值必须通过 JSON Schema。
4. Resource Binding 必须引用已授权资源类型。
5. 高风险 Action 必须要求 Controller。
6. `human_confirmed` 必须配置确认 UI。

---

## 13.6 Component 编辑

V1 仅支持注册式组件：

```text
Component ID
Description
Props Schema
Allowed Slots
Max Instances
Requires Resource Binding
```

Agent 只选择 Component ID、Props 和 Slot。

页面明确禁止：

```text
任意 JSX
任意 HTML
任意 Script
任意 CSS
远程组件代码
```

该模块可在 V1.1 解锁，V1 首次发布可以只读展示数据模型。

---

## 13.7 Hook Code 页面

页面根据 Profile 生成：

```text
ZebraAgentProvider
useZebraReadable
useZebraAction
useZebraApproval
useZebraClarification
```

支持：

```text
React
Next.js App Router
CopilotKit Adapter
```

示例代码只包含 Contract Name、Schema 和 Provider 配置，不生成业务 Handler 实现。

### 代码片段功能

1. 一键复制。
2. 选择 TypeScript 或 JavaScript。
3. 显示所需 npm 包。
4. 显示 Frontend Profile Digest。
5. 显示当前 Build ID。
6. 显示 BFF 接入说明。
7. 显示禁用 Direct Browser 模式的提示。

---

## 13.8 Mounted Capability Inspector

页面用于查看真实浏览器当前挂载能力。

字段：

```text
Client Session ID
Task ID
Run ID
Route
Frontend Build
Profile Digest
Mounted Snapshot Digest
Controller 或 Observer
UI Revision
Heartbeat
Mounted Readables
Mounted Actions
Mounted Components
Drift Status
```

操作：

```text
查看 Snapshot
比较 Published Profile
释放 Controller
强制断开 Client Session
查看 Pending Client Effect
复制诊断包
```

Drift 类型：

```text
profile_digest_mismatch
unknown_action
action_not_mounted
schema_mismatch
origin_mismatch
build_mismatch
stale_ui_revision
stale_fence
```

---

## 14. Agent 资产

## 14.1 AgentDefinition 列表

字段：

```text
Name
Definition ID
Latest Draft
Latest Version
Published Release
Capability Ceiling
Model Policy
Tool Profile
Runtime Profile
Status
Updated At
```

## 14.2 AgentDefinition 详情

Tab：

```text
Overview
Draft
Versions
Release
Capabilities
Model Policy
Tool Policy
Memory Policy
Runtime Policy
Evaluation
Host Bindings
Audit
```

### Draft 编辑

支持：

```text
基础信息
Capability Profile Ref
Model Policy Ref
Tool Profile Ref
Skill Snapshot Digest
Memory Policy Ref
Security Policy Ref
Evaluation Profile Ref
Runtime Profile Ref
```

### 发布流程

```text
Draft
→ Validate
→ Materialize Version
→ Release Gate
→ Publish
→ Canary
→ Promote
```

### Release 状态

```text
draft
published
deprecated
revoked
```

---

## 15. Policy 与 Quota

## 15.1 Policy 列表

Policy 层级：

```text
Platform
Environment
Host
Namespace
Agent Release
Task Type
Frontend Profile
```

Policy 类型：

```text
Capability Policy
Model Policy
Tool Policy
Runtime Policy
Network Policy
Approval Policy
Client Action Policy
Memory Policy
Artifact Policy
```

## 15.2 Effective Policy Simulator

输入：

```text
Host
Namespace
Agent Release
Backend Manifest
Frontend Profile
HostGrant Scopes
ClientGrant Scopes
Resource Refs
```

输出：

```text
Effective Capabilities
Effective Backend Tools
Effective Client Actions
Effective Limits
Required Approvals
Rejected Reasons
Binding Preview
```

该页面是接入联调和权限排查的核心工具。

## 15.3 Quota

维度：

```text
Concurrent Tasks
Model Tokens
Tool Calls
Runtime Seconds
Artifact Bytes
Client Actions
Subagents
Orchestration Nodes
```

支持：

```text
Soft Limit
Hard Limit
Warning Threshold
Reset Cycle
Override
```

---

## 16. Conformance 与 Dry Run

## 16.1 Conformance 列表

字段：

```text
Run ID
Host
Environment
Backend 或 Frontend
Profile Revision
Triggered By
Started At
Duration
Passed
Failed
Skipped
Status
```

## 16.2 Conformance 详情

测试分组：

```text
Schema
Auth
Scope
Resource
Namespace
Idempotency
Timeout
Output Bound
Uncertain Effect
Reconciliation
Client Fence
UI Revision
Unmount
Reconnect
Replay
Zero Host Branch
```

每个测试显示：

```text
Status
Duration
Reason Code
Evidence
Request Digest
Response Digest
Related Audit
```

敏感请求和响应只显示脱敏摘要。

## 16.3 Dry Run

Dry Run 支持：

```text
生成受限测试 Grant
创建测试 Task
选择 Agent Release
选择 Backend Manifest
选择 Frontend Profile
注入测试 Resource Ref
观察 Task Binding
观察 Tool 与 Client Effect
查看最终 Gate
```

Dry Run 产生独立 namespace 或明确的测试标记，禁止写入 Production 业务数据。

---

## 17. Runtime Task 列表

### 17.1 字段

```text
Task ID
Title
Host
Namespace
Agent Release
Status
Active Segment
Orchestration
Subagents
Current Wait Reason
Model Tokens
Cost
Created At
Updated At
```

### 17.2 Status

```text
queued
running
waiting_approval
waiting_clarification
waiting_children
waiting_client_effect
suspended
blocked
uncertain
completed
failed
cancelled
```

### 17.3 筛选

```text
Status
Host
Namespace
Agent Release
Model
Wait Reason
Has Client
Has Subagent
Has Uncertain Effect
Created Range
Cost Range
```

### 17.4 批量操作

V1 只允许：

```text
导出
添加标签
批量取消非终态 Task
```

批量取消需要 Operator 权限和审计原因。

---

## 18. Task 详情页

### 18.1 页面目标

成为运行诊断的统一入口。

### 18.2 页面布局

```text
┌ Task Header: ID / Status / Host / Agent / Actions ┐
├────────────────────────────────────────────────────┤
│ 左侧主区                               │ 右侧信息栏 │
│ Timeline / Orchestration / Calls       │ Binding    │
│ Effects / Client / Artifacts           │ Limits     │
│                                         │ Usage      │
└────────────────────────────────────────────────────┘
```

### 18.3 Header

显示：

```text
Task ID
Title
Status
Host
Namespace
Agent Release
Current Segment
Current Attempt
Created At
Elapsed
Cost
```

允许操作：

```text
Suspend
Resume
Cancel
Open Approval
Download Diagnostic Bundle
```

禁止在 Task 详情中修改 Agent Release、Connector Revision 或 Binding。

### 18.4 Tab

```text
Overview
Timeline
Orchestration
Attempts
Model Calls
Tools
Host Effects
Client
Artifacts
Memory
Binding
Usage
Audit
```

---

## 18.5 Overview

展示：

```text
当前状态
当前等待原因
任务目标
AgentDefinition Snapshot
Task Binding Digest
Host Capability Snapshot
Frontend Binding
最近错误
最近 Tool
最近 Client Effect
当前预算
```

---

## 18.6 Timeline

事件按 durable sequence 展示。

筛选：

```text
Session
Attempt
Model
Tool
Approval
Clarification
Subagent
Orchestration
Effect
Client Effect
Artifact
Memory
Terminal
```

每个事件显示：

```text
Sequence
Event Type
Actor
Timestamp
Causation
Correlation
Payload 摘要
Policy Version
Model Profile
```

支持：

```text
查看 JSON
复制 Event ID
跳转关联 Tool 或 Effect
基于 Cursor 重放
```

---

## 18.7 Orchestration

使用 DAG 视图展示：

```text
Node
Role
Child Task
Status
Dependencies
Budget
Evidence
Gate
Retry
Isolation
```

交互：

```text
点击 Node 打开侧边详情
跳转 Child Task
查看 Plan Revision
比较 Replan
查看 Completion Gate Receipt
```

颜色语义：

```text
灰色 blocked
蓝色 running
紫色 waiting
绿色 completed
红色 failed
橙色 uncertain
```

---

## 18.8 Attempts 与 Model Calls

Attempt 显示：

```text
Attempt Number
Authority Snapshot
Lease Fence
Model
Input Tokens
Output Tokens
Reasoning Tokens
Tool Calls
Duration
Outcome
```

Model Call 详情显示：

```text
Provider
Requested Model
Resolved Model
Role
Thinking Mode
Tool Choice
Latency
Retry
Finish Reason
Usage
Error
```

Prompt 内容默认折叠并受权限控制。

---

## 18.9 Tools

字段：

```text
Tool Call ID
Tool Name
Execution Location
Risk
Scope
Arguments Digest
Status
Duration
Receipt
```

Execution Location：

```text
zebra
host
sandbox
client
```

支持按 Tool Location 和 Risk 筛选。

---

## 18.10 Host Effects

显示：

```text
Dispatch ID
Tool
Operation ID
Status
Idempotency Key
Claim Owner
Attempt
Evidence
Reconciliation
```

Uncertain Effect 提供：

```text
查看证据
执行 Reconcile
标记已解决
升级人工处理
```

任何人工解决操作必须写入审计。

---

## 18.11 Client Tab

包含四个子区：

```text
Client Run Binding
Active Controller
Mounted Capabilities
Client Effects
```

Client Effect 字段：

```text
Effect ID
Action
Expected UI Revision
Client Session
Fence Status
Status
Scheduled At
Delivered At
Receipt At
Result Digest
Error Code
```

支持：

```text
查看 Contract
查看 Receipt
查看 AG-UI Event
释放 Controller
取消过期 Effect
```

不允许在后台点击“代执行”浏览器 Hook。

---

## 18.12 Binding

展示不可变快照：

```text
AgentDefinition Snapshot
Agent Capability Ceiling
Host Capability Snapshot
Connector Profile Revision
Backend Manifest Digest
Frontend Profile Digest
Client Run Binding
Zebra Policy Digest
Effective Capabilities
Effective Limits
Resource Refs
```

支持：

```text
复制 Digest
查看来源版本
比较当前已发布版本
显示 Drift
```

---

## 19. Client Session

## 19.1 Client Session 列表

字段：

```text
Client Session ID
Host
Namespace
Frontend App
Build
Origin
User Subject Hash
Controller 或 Observer
Task
Run
Route
UI Revision
Heartbeat
Status
```

Status：

```text
connecting
active
observer
stale
expired
revoked
disconnected
```

## 19.2 Client Session 详情

Tab：

```text
Overview
Mounted Capabilities
Controller Lease
Effects
State Snapshots
Heartbeat
Audit
```

操作：

```text
Revoke Session
Release Controller
Promote Observer
Download Diagnostic Bundle
```

Promote Observer 需要 expected revision 和权限校验。

---

## 20. Client Effect

## 20.1 列表

字段：

```text
Effect ID
Task
Run
Action
Host
Frontend App
Client Session
Status
Expected Revision
Created At
Expires At
Receipt
```

## 20.2 状态

```text
pending
delivered
succeeded
failed
declined
unavailable
stale_ui_state
expired
uncertain
cancelled
```

## 20.3 详情

显示：

```text
Action Contract Digest
Arguments Digest
Client Binding Digest
Fence Hash 摘要
Expected UI Revision
Idempotency Key 摘要
Receipt
Result Digest
Handler Version
Error Code
Event Timeline
```

前端只显示 Fence Hash 摘要，不显示原始 Fence Token。

---

## 21. Approval 与 Clarification

### 21.1 列表

字段：

```text
Type
Task
Host
Namespace
Reason
Requested By
Requested At
Deadline
Status
```

### 21.2 详情

Approval 显示：

```text
Tool
Risk
Arguments 摘要
Resource Refs
Effect Preview
Policy
Requester
```

Clarification 显示：

```text
Question
Response Schema
Context
Related Tool
```

### 21.3 操作

```text
Approve
Reject
Respond
Escalate
```

所有决定带：

```text
Actor
Reason
Timestamp
Idempotency Key
```

---

## 22. Usage 与成本

### 22.1 维度

```text
Host
Namespace
Agent Release
Model
Task Status
Tool
Client Action
Subagent Role
Orchestration Run
```

### 22.2 指标

```text
Input Tokens
Output Tokens
Reasoning Tokens
Model Cost
Runtime Seconds
Tool Calls
Host Calls
Client Actions
Artifacts
Task Count
Success Rate
P50/P95 Duration
```

### 22.3 功能

```text
趋势
分组
Top N
预算对比
异常增长
导出 CSV
```

---

## 23. Audit Log

### 23.1 字段

```text
Audit ID
Actor
Actor Type
Action
Resource Type
Resource ID
Environment
Host
Namespace
Before Digest
After Digest
Reason
Result
Timestamp
Correlation ID
```

### 23.2 可审计操作

```text
Host 注册
Trust 更新
Connector 发布
Connector 绑定
Manifest 发布
Frontend Profile 发布
Agent Release
Policy 更新
Quota 更新
Revoke
Rollback
Approval
Effect Reconciliation
Controller Lease 释放
Feature Flag
Production Promote
```

### 23.3 导出

1. 按时间范围导出。
2. 按 Host 和 namespace 限制范围。
3. 导出包含校验摘要。
4. 导出文件生成 Artifact 并记录审计。

---

## 24. Rollout

### 24.1 发布对象

```text
Connector Binding
Backend Manifest
Frontend Profile
Agent Release
Policy
```

### 24.2 Rollout 策略

```text
Dry Run
Canary 5%
Canary 25%
Canary 50%
Production 100%
Rollback
```

### 24.3 门禁

```text
Conformance Passed
Security Review Passed
Error Rate
P95 Latency
Task Success Rate
Uncertain Effect Rate
Client Effect Failure Rate
Budget
```

### 24.4 回滚

回滚采用 Binding Revision 切换。

回滚前显示：

```text
目标版本
影响 namespace
运行中 Task
新 Task 生效规则
旧 Task 固定快照规则
```

---

## 25. 状态与视觉规范

### 25.1 状态颜色

| 语义 | 颜色 |
|---|---|
| 正常、完成、通过 | Green |
| 运行、处理中 | Blue |
| 等待、需输入 | Purple |
| 警告、即将过期 | Amber |
| 失败、拒绝、撤销 | Red |
| 不确定 | Orange |
| 草稿、未开始 | Gray |

颜色必须与文字和图标共同表达状态，不能只依赖颜色。

### 25.2 ID 与 Digest

1. 使用等宽字体。
2. 默认折叠中间部分。
3. 支持复制。
4. 鼠标悬停显示完整值。
5. Digest 支持打开 Diff。

### 25.3 表格

1. 列配置可保存。
2. 筛选条件进入 URL。
3. 支持服务端分页。
4. 支持列排序。
5. 支持固定关键列。
6. 高风险对象不提供行内编辑。

### 25.4 JSON 与代码

1. 使用只读或受控 Monaco Editor。
2. 支持 JSON 格式化。
3. 支持 Schema 错误定位。
4. 禁止渲染未经净化的 HTML。
5. Secret 字段自动遮蔽。

---

## 26. 权限矩阵

| 功能 | Owner | Admin | Integration | Publisher | Operator | Auditor | Observer |
|---|---:|---:|---:|---:|---:|---:|---:|
| 查看平台总览 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 注册 Host | ✓ | ✓ | ✓ |  |  |  |  |
| 发布 Connector | ✓ | ✓ | ✓ |  |  |  |  |
| Revoke Connector | ✓ | ✓ |  |  |  |  |  |
| 发布 Backend Manifest | ✓ | ✓ | ✓ |  |  |  |  |
| 发布 Frontend Profile | ✓ | ✓ | ✓ |  |  |  |  |
| 发布 Agent Release | ✓ | ✓ |  | ✓ |  |  |  |
| 修改 Policy | ✓ | ✓ |  |  |  |  |  |
| 修改 Quota | ✓ | ✓ |  |  |  |  |  |
| 查看 Task | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cancel Task | ✓ | ✓ |  |  | ✓ |  |  |
| 处理 Approval | ✓ | ✓ |  |  | ✓ |  |  |
| Reconcile Effect | ✓ | ✓ |  |  | ✓ |  |  |
| 释放 Client Controller | ✓ | ✓ | ✓ |  | ✓ |  |  |
| 查看审计 | ✓ | ✓ |  |  | ✓ | ✓ |  |
| 导出审计 | ✓ | ✓ |  |  |  | ✓ |  |
| Promote Production | ✓ | 受限 |  | 受限 |  |  |  |

所有权限仍需服务端校验。

---

## 27. 前端技术方案

### 27.1 应用位置

建议新增：

```text
apps/platform-web
```

建议独立 TypeScript workspace：

```text
pnpm-workspace.yaml
apps/platform-web
packages/platform-ui
packages/platform-api-client
packages/platform-contracts
```

该 workspace 不加入 Python `uv` workspace。

### 27.2 推荐技术栈

```text
Next.js App Router
React
TypeScript
Tailwind CSS
shadcn/ui
TanStack Query
TanStack Table
React Hook Form
Zod
React Flow
Monaco Editor
ECharts 或同类图表库
```

### 27.3 渲染边界

Server Component 负责：

```text
App Shell
登录态
初始权限
静态页面结构
初始查询
```

Client Component 负责：

```text
实时 Task
SSE
表格交互
图表
表单
DAG
Diff
Monaco
Client Session Inspector
```

### 27.4 网络边界

Production 固定：

```text
Browser
→ Platform Web BFF
→ Zebra Management API / Runtime API
```

浏览器不直接访问 Zebra API。

BFF 负责：

```text
OIDC Session
CSRF
Operator Token Exchange
Host Scope
Namespace Scope
Request Correlation
Rate Limit
```

### 27.5 状态管理

```text
Server State
TanStack Query

筛选和分页
URL Search Params

表单
React Hook Form + Zod

短期 UI 状态
组件内部状态或轻量 Store

实时状态
SSE Event Store
```

禁止将 Task、Effect、Connector 或 Release 事实保存在前端全局 Store 中作为权威状态。

### 27.6 SSE

1. 支持 Last Event ID。
2. 页面隐藏时降低刷新。
3. 断线指数退避。
4. 重新连接后先 durable replay，再进入 live tail。
5. 重复 Event 通过 Event ID 去重。
6. 超过积压阈值时触发全量重新查询。

### 27.7 建议目录

```text
apps/platform-web/
├── src/
│   ├── app/
│   │   ├── (auth)/
│   │   ├── (console)/
│   │   │   ├── overview/
│   │   │   ├── integrations/
│   │   │   ├── agents/
│   │   │   ├── runtime/
│   │   │   ├── frontend/
│   │   │   ├── quality/
│   │   │   ├── governance/
│   │   │   └── system/
│   │   └── api/
│   ├── features/
│   │   ├── hosts/
│   │   ├── connectors/
│   │   ├── manifests/
│   │   ├── frontend-profiles/
│   │   ├── agents/
│   │   ├── tasks/
│   │   ├── orchestration/
│   │   ├── client-effects/
│   │   ├── conformance/
│   │   └── audit/
│   ├── components/
│   ├── lib/
│   └── styles/
├── tests/
└── package.json
```

### 27.8 API Client

1. Management API 和 Runtime API 分别生成 Client。
2. Client 从 OpenAPI 自动生成。
3. 页面禁止手写散落的 fetch。
4. Error 统一映射为 Problem Details。
5. 请求自动附加 Correlation ID。
6. 写请求默认携带 Idempotency Key 或 expected revision。

---

## 28. API 依赖清单

### 28.1 当前可部分复用

| 前端模块 | 当前能力 |
|---|---|
| Task 列表与详情 | 已存在 Task、Session、Event、Artifact 等接口基础 |
| AG-UI Stream | 已有 Command、Stream、Cursor 和 Interrupt 基础 |
| AgentDefinition | 已有 Draft、Validation、Version、Release API 基础 |
| Orchestration | 已有 Core 和 PostgreSQL 领域能力 |
| Host Authority | 已有 PostgreSQL Registry 和 Grant 校验 |
| Connector | 已有 Domain 和 PostgreSQL Registry |
| Durable Subagent | 已有 Child Task、Parent Wakeup 和 Binding 收窄链路 |

### 28.2 需要补充的 Management API

```text
/platform/v1/hosts
/platform/v1/host-authorities
/platform/v1/connectors
/platform/v1/backend-manifests
/platform/v1/frontend-profiles
/platform/v1/frontend-bindings
/platform/v1/policies
/platform/v1/quotas
/platform/v1/conformance-runs
/platform/v1/rollouts
/platform/v1/audit
/platform/v1/usage
```

### 28.3 需要补充的 Client Runtime API

```text
/v1/client-sessions
/v1/client-sessions/{id}/heartbeat
/v1/client-sessions/{id}/mount
/v1/tasks/{taskId}/runs/{runId}/client-bindings
/v1/client-effects
/v1/client-effects/{id}
/v1/client-effects/{id}/receipts
```

### 28.4 API 未完成时的前端原则

1. Mock 仅存在于 Storybook、测试和开发环境。
2. Production Build 禁止启用 Mock。
3. 页面以 Feature Flag 控制未完成模块。
4. 不通过直接数据库连接绕过 API。
5. 不在前端临时推导安全决策。

---

## 29. 安全要求

1. 管理后台使用 OIDC 登录。
2. Session Cookie 使用 HttpOnly、Secure 和 SameSite。
3. 写操作启用 CSRF 防护。
4. 页面启用严格 CSP。
5. 禁止 `dangerouslySetInnerHTML` 渲染外部内容。
6. JSON 和 Markdown 预览经过净化。
7. Secret 只显示引用和健康状态。
8. 所有复制操作进入前端审计埋点。
9. 高风险操作需要二次认证或 Step-up Authentication。
10. Production Promote 和 Revoke 支持双人审批。
11. URL 不包含 Token、Grant、Secret 或原始 Fence。
12. 浏览器日志不打印完整请求体。
13. Error Boundary 只展示安全错误摘要。
14. 导出文件进行权限和范围校验。
15. 前端权限只改善体验，服务端保持最终授权。

---

## 30. 性能与可用性要求

### 30.1 性能

| 指标 | 目标 |
|---|---|
| 首屏可交互 | 常规网络下小于 3 秒 |
| 列表查询 P95 | 小于 2 秒 |
| 页面切换 | 小于 1 秒显示骨架 |
| Live Event 延迟 | 正常条件下小于 2 秒 |
| 1000 行表格 | 页面交互无明显卡顿 |
| DAG 100 Nodes | 交互可用 |
| JSON 256KB | 编辑器可用 |

### 30.2 可用性

1. API 失败显示可重试状态。
2. SSE 失败自动重连。
3. 离线期间保留只读缓存。
4. 写操作失败不乐观提交关键状态。
5. 发布流程支持草稿恢复。
6. 长任务支持后台运行和通知。
7. 页面刷新后保留 URL 筛选。
8. 所有终态操作显示明确结果。

### 30.3 可访问性

1. 支持键盘操作。
2. 状态不只依赖颜色。
3. 表单有 Label 和错误关联。
4. 弹窗有焦点锁定。
5. 图表提供文本摘要。
6. 关键页面满足 WCAG AA 级可访问性目标。

---

## 31. 埋点与产品指标

### 31.1 接入效率

```text
Host Onboarding Start
Step Completion
Validation Failure
Conformance Failure
Dry Run Success
Time to First Task
Time to Production
```

### 31.2 运营效率

```text
Task Search
Task Diagnostic Bundle
Effect Reconcile
Controller Release
Audit Export
Rollout Promote
Rollback
```

### 31.3 前端 Hook

```text
Profile Published
Hook Mounted
Action Available
Action Not Mounted
Client Effect Succeeded
Stale UI Revision
Stale Fence
Reconnect Recovery
```

### 31.4 核心产品指标

```text
平均 Host 接入周期
一次 Conformance 通过率
Task 故障平均定位时间
Task 恢复成功率
Client Effect 成功率
Uncertain Effect 收敛时间
每 Host 运行成本
新业务零 Core 修改比例
```

---

## 32. MVP 范围

### 32.1 P0 页面

```text
登录与全局 Shell
平台总览
Host 列表与详情
Host 接入向导
Connector 列表与详情
Backend Manifest 编辑器
Frontend Profile 编辑器
Hook Code 页面
AgentDefinition 与 Release
Task 列表与详情
Orchestration DAG
Client Session
Client Effect
Conformance
Audit Log
```

### 32.2 P1 页面

```text
Policy Simulator
Quota
Usage 与成本
Rollout
Effect Reconciliation
Mounted Capability Inspector
Approval 与 Clarification 工作台
Platform Health
```

### 32.3 P2 页面

```text
Generative UI Component Registry
Agent Team 管理
高级 Evaluation
跨环境 Promotion Pipeline
外部开发者门户
Marketplace
```

---

## 33. 版本规划

### Phase 1 前端基础

```text
App Shell
OIDC
RBAC
OpenAPI Client
Design System
Global Search
Environment Context
```

### Phase 2 接入中心

```text
Host
Trust
Connector
Backend Manifest
Namespace Binding
Onboarding Wizard
```

### Phase 3 Agent 与运行中心

```text
AgentDefinition
Release
Task
Timeline
Attempts
Tools
Artifacts
Orchestration
```

### Phase 4 前端能力

```text
Frontend Profile
Hook Code
Client Session
Client Run Binding
Client Effect
Mounted Inspector
```

### Phase 5 治理与生产

```text
Conformance
Policy
Quota
Usage
Audit
Rollout
Production Gate
```

---

## 34. 修改边界

### 34.1 第一阶段前端 Owned Paths

建议：

```text
apps/platform-web/**
packages/platform-ui/**
packages/platform-api-client/**
packages/platform-contracts/**
pnpm-workspace.yaml
package.json
docs/Zebra_智能体接入与治理中台前端PRD_v1.0.md
```

### 34.2 允许的后端协同路径

只有对应 API 卡激活后允许修改：

```text
packages/agent-control-plane/**
apps/api/src/zebra_agent_api/platform_*.py
apps/api/src/zebra_agent_api/client_*.py
packages/agent-core/src/agent_core/domain/client_*.py
packages/agent-storage/src/agent_storage/postgres/client_*.py
```

### 34.3 禁止修改

前端任务卡禁止修改：

```text
apps/worker/**
packages/agent-runtime/**
packages/agent-security/**
现有 Effect 语义
现有 Lease 与 Fence 语义
TaskBindingSnapshot 领域规则
Host 业务数据库
Trench 业务 API
```

### 34.4 业务代码边界

共享平台前端禁止出现：

```text
if host === "trench"
if host === "jazz"
Trench 专用字段分支
Jazz 专用字段分支
业务数据库字段
业务页面路由逻辑
```

业务展示插件放置在：

```text
apps/platform-web/src/integrations/trench/**
apps/platform-web/src/integrations/jazz/**
```

插件只能提供显示名称、文档链接、示例 Profile 和业务侧跳转，不得修改平台权限和运行语义。

### 34.5 安全边界

前端代码禁止：

```text
直接数据库访问
持久化 Operator Token 到 localStorage
持久化 HostGrant
显示明文 Secret
自行决定 Effective Capability
绕过 expected revision
绕过 Idempotency Key
执行任意 JavaScript
执行任意 DOM Selector
```

---

## 35. 验收边界

### 35.1 全局 Shell

1. 登录后可根据角色显示导航。
2. Environment 和 namespace 上下文始终可见。
3. 全局搜索可以定位 Task、Host、Agent 和 Effect。
4. Production 环境具有明确视觉提示。
5. 页面刷新后筛选条件和路由不丢失。

### 35.2 Host 接入

1. 能够从 Draft 开始完成七步向导。
2. 每一步可保存和恢复。
3. Published Version 无法原地编辑。
4. Conformance 未通过时 Production 发布按钮禁用。
5. 最终发布显示完整 Diff 和影响范围。
6. 普通 HostGrant 无法进入管理写接口。

### 35.3 Connector 与 Manifest

1. Connector 新版本发布后旧版本仍可查看。
2. Namespace Binding 使用 expected revision。
3. Revoke 需要高风险确认。
4. Manifest Editor 能定位 Schema 错误。
5. Resource Binding、Risk 和 Idempotency 显式显示。
6. 页面不显示明文 Credential。

### 35.4 Frontend Profile

1. 能创建 Readable 和 Action Contract。
2. Action 无法声明正式业务写入。
3. 能生成 React Hook 示例。
4. Mounted Snapshot 只允许收窄 Profile。
5. Profile Digest 漂移可被检测。
6. Client Session 页面可以区分 Controller 和 Observer。
7. Client Effect 可以完整显示 Request 和 Receipt。
8. Fence 原值不会出现在页面。

### 35.5 Agent

1. 能完成 Draft、Validate、Version、Release 流程。
2. 能查看 Capability Ceiling。
3. 能查看 Release 与 Host Binding。
4. Revoke 后状态立即更新。
5. 运行中 Task 仍显示固定快照。

### 35.6 Task

1. Task 列表支持服务端分页和组合筛选。
2. Task 详情可以查看完整 Event Timeline。
3. 可以跳转 Child Task。
4. 可以查看 Orchestration DAG。
5. 可以查看 Binding、Effect、Client Effect、Artifact 和 Usage。
6. SSE 断线后可以从 Cursor 重放。
7. Redis 不可用时页面可以通过 PostgreSQL 查询恢复。
8. 只读用户无法 Cancel 或 Resume。

### 35.7 审计与安全

1. 所有管理写操作产生 Audit Log。
2. Audit 可以按 Host、namespace、Actor 和 Action 查询。
3. 导出范围受权限限制。
4. 页面和日志无 Secret 泄漏。
5. 直接调用无权 API 返回 403。
6. 前端隐藏按钮不能作为安全控制的唯一手段。

### 35.8 多业务接入

1. fake-host-a 和 fake-host-b 使用同一页面与流程。
2. 新 Host 只增加配置、Manifest、Profile 和业务 Adapter。
3. 平台共享页面不增加 Host 名称分支。
4. Trench 接入完成后，Jazz 接入无需重写 Task、Agent、Connector 和 Frontend Profile 页面。

---

## 36. E2E 验收场景

### 36.1 Backend Agent 场景

```text
创建 Host
→ 发布 Connector
→ 发布 Backend Manifest
→ 发布 Agent Release
→ 创建 Dry Run Task
→ Agent 调用 Host Read Tool
→ 页面显示 Tool Receipt
→ Task Completed
```

### 36.2 Frontend Hook 场景

```text
发布 Frontend Profile
→ React Hook Mount
→ Client Session Active
→ Task 绑定 Controller
→ Agent 调用 Client Action
→ Client Effect Pending
→ 浏览器执行 Hook
→ Receipt Succeeded
→ Task Resume
→ 页面显示最终结果
```

### 36.3 Subagent 场景

```text
Parent Task
→ Durable Child Task
→ Parent waiting_children
→ Child Completed
→ Parent Wakeup
→ Parent Resume
→ Task 详情显示 ParentChildLink
```

### 36.4 Orchestrator 场景

```text
Orchestrator Proposal
→ Plan Validation
→ Plan Snapshot
→ Child Nodes
→ Completion Gate
→ Synthesis
→ Task Completed
```

### 36.5 多 Tab 场景

```text
Tab A Claim Controller
→ Tab B 成为 Observer
→ Tab B 尝试 Receipt
→ 请求被拒绝
→ Tab A 断线
→ Lease 过期
→ Tab B 通过 CAS 成为 Controller
```

### 36.6 回滚场景

```text
Frontend Profile Revision 4 Canary
→ Client Effect Failure Rate 超阈值
→ Rollout Blocked
→ Binding 回滚 Revision 3
→ 新 Run 使用 Revision 3
→ 旧 Run 保持固定快照
```

---

## 37. 前端实施任务拆解

### 基础框架

```text
PLATFORM-WEB-ADR-01
PLATFORM-WEB-BOOTSTRAP-01
PLATFORM-WEB-AUTH-01
PLATFORM-WEB-RBAC-01
PLATFORM-WEB-DESIGN-SYSTEM-01
PLATFORM-WEB-API-CLIENT-01
PLATFORM-WEB-SSE-01
```

### 接入中心

```text
PLATFORM-WEB-HOST-01
PLATFORM-WEB-ONBOARDING-01
PLATFORM-WEB-TRUST-01
PLATFORM-WEB-CONNECTOR-01
PLATFORM-WEB-BACKEND-MANIFEST-01
PLATFORM-WEB-BINDING-01
```

### Agent 和运行

```text
PLATFORM-WEB-AGENT-DEF-01
PLATFORM-WEB-AGENT-RELEASE-01
PLATFORM-WEB-TASK-LIST-01
PLATFORM-WEB-TASK-DETAIL-01
PLATFORM-WEB-ORCHESTRATION-01
PLATFORM-WEB-EFFECT-01
PLATFORM-WEB-ARTIFACT-01
```

### 前端能力

```text
PLATFORM-WEB-FRONTEND-PROFILE-01
PLATFORM-WEB-HOOK-CODE-01
PLATFORM-WEB-CLIENT-SESSION-01
PLATFORM-WEB-CLIENT-EFFECT-01
PLATFORM-WEB-MOUNTED-INSPECTOR-01
```

### 治理

```text
PLATFORM-WEB-CONFORMANCE-01
PLATFORM-WEB-POLICY-01
PLATFORM-WEB-QUOTA-01
PLATFORM-WEB-USAGE-01
PLATFORM-WEB-AUDIT-01
PLATFORM-WEB-ROLLOUT-01
PLATFORM-WEB-PROD-GATE-01
```

---

## 38. 首批建议激活顺序

第一批：

```text
PLATFORM-WEB-ADR-01
PLATFORM-WEB-BOOTSTRAP-01
PLATFORM-WEB-DESIGN-SYSTEM-01
PLATFORM-WEB-AUTH-01
PLATFORM-WEB-API-CLIENT-01
```

第二批：

```text
PLATFORM-WEB-HOST-01
PLATFORM-WEB-CONNECTOR-01
PLATFORM-WEB-BACKEND-MANIFEST-01
PLATFORM-WEB-AGENT-DEF-01
```

第三批：

```text
PLATFORM-WEB-TASK-LIST-01
PLATFORM-WEB-TASK-DETAIL-01
PLATFORM-WEB-ORCHESTRATION-01
```

第四批：

```text
PLATFORM-WEB-FRONTEND-PROFILE-01
PLATFORM-WEB-HOOK-CODE-01
PLATFORM-WEB-CLIENT-SESSION-01
PLATFORM-WEB-CLIENT-EFFECT-01
```

第五批：

```text
PLATFORM-WEB-CONFORMANCE-01
PLATFORM-WEB-AUDIT-01
PLATFORM-WEB-ROLLOUT-01
PLATFORM-WEB-PROD-GATE-01
```

---

## 39. 最终验收定义

V1 可以正式发布的条件：

1. Trench 可以通过中台完成 Host、Connector、Backend Manifest、Frontend Profile 和 Agent Release 接入。
2. 接入过程中无需直接修改 PostgreSQL。
3. Task 详情可以完成 P0 故障定位。
4. Durable Subagent 和 Orchestration 可以完整观测。
5. React Hook 可以完成 Readable 注入和 Client Action Receipt 闭环。
6. Client Effect 支持暂停、恢复、重放和多 Tab Fence。
7. 所有管理写操作具有权限和审计。
8. Published Version 不可原地编辑。
9. Production 发布具有 Conformance、Canary 和 Rollback。
10. Jazz 接入时，共享平台页面和 Zebra Worker 不增加 Jazz 专用分支。

---

## 40. 产品完成后的目标体验

新业务系统接入 Zebra 时，接入人员只需完成以下工作：

```text
注册 Host
配置 Trust
发布 Connector
提供 Backend Manifest
提供 Frontend Profile
选择 Agent Release
运行 Conformance
完成 Dry Run
执行 Canary
```

平台自动完成：

```text
版本固定
Digest 校验
能力求交
资源绑定
策略求交
配额检查
运行观测
Effect 审计
Client Effect 审计
发布和回滚
```

最终形成一套可自助接入、可验证、可观测、可回滚、可审计的 Cloud Agent 平台前端。
