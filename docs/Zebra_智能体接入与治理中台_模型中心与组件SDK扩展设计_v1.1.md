# Zebra 智能体接入与治理中台：模型中心、单 Agent、多 Agent 与组件 SDK 扩展设计

**文档版本：** v1.1  
**文档状态：** Draft for Architecture Review  
**编写日期：** 2026-08-26  
**适用文档：** 《Zebra 智能体接入与治理中台前端产品需求文档 v1.0》  
**代码评估基线：** `LogicStormINC/zebra@efd4e2938d14c6598e9c60503830abf5360fa0bf`  
**核心范围：** 项目配置、Prompt、知识、记忆、Skill、MCP、Plugin、模型治理、Token 与成本、单 Agent 配置、多 Agent 配置、TypeScript SDK、LobeHub UI 组件体系  

---

## 1. 本次扩展的最终结论

Zebra 中台需要继续扩展，并正式形成以下十个逻辑中心：

```text
Zebra Agent Platform Console
├── 项目中心
├── Agent Studio
├── Multi-Agent Studio
├── Prompt 与上下文中心
├── 知识与记忆中心
├── 能力资产中心
├── 模型中心
├── 接入中心
├── 运行与成本中心
└── 开发者中心
```

其中，模型配置不能仅表现为一个模型下拉框。模型配置应形成完整的 **Model Control Plane**，统一管理：

```text
Provider
Connection
Credential Reference
Model Catalog
Capability
Role Profile
Invocation Policy
Context Budget
Routing
Fallback
Concurrency
Rate Limit
Token Budget
Pricing
Cost Ledger
Evaluation
Canary
Rollback
```

组件侧建议拆分为 Headless SDK 和 LobeHub UI 视觉层：

```text
@zebra-agent/contracts
@zebra-agent/client-core
@zebra-agent/react
@zebra-agent/ui-lobe
@zebra-agent/platform-widgets
@zebra-agent/next
@zebra-agent/copilotkit-adapter
@zebra-agent/devtools
create-zebra-agent
```

这样可以同时满足：

1. 中台自身快速开发。
2. Trench、Jazz 等业务前端低成本接入。
3. React 18 和 React 19 项目的兼容。
4. Next.js、Vite、Tauri 等不同宿主的接入。
5. 业务项目选择 Headless Hooks 或完整视觉组件。
6. LobeHub UI 升级时，业务项目无需直接承受其全部变化。
7. Zebra 的协议、安全、幂等和恢复语义保持统一。

---

## 2. 当前 Zebra 代码验证结论

### 2.1 已具备的模型基础

当前 Zebra 已经具备以下模型领域能力：

```text
ModelRole
ModelInvocationPolicy
ModelThinkingMode
ModelReasoningEffort
ModelToolChoice
ModelUsage
ModelCallMetadata
ModelContextWindow
Context Window Hard Gate
DeepSeek Role Router
Model Call Projection
Token Usage Parsing
Cost 字段
```

当前角色包括：

```text
classifier
summarizer
analyst
planner
reviewer
executor
```

当前上下文模型已经能够表示：

```text
context_tokens
max_output_tokens
reasoning_reserve_tokens
compaction_reserve_tokens
protocol_reserve_tokens
auto_compact_token_limit
compaction_trigger_reserve_tokens
```

当前 Model Event 与 Model Call Projection 已能记录：

```text
input_tokens
output_tokens
total_tokens
reasoning_tokens
prompt_cache_hit_tokens
prompt_cache_miss_tokens
latency_ms
retry_count
response_repair_count
profile_id
resolved_model
cost_usd
```

### 2.2 当前模型配置的主要局限

当前模型配置主要由部署环境变量决定：

```text
ZEBRA_MODEL_PROVIDER
ZEBRA_MODEL_BASE_URL
ZEBRA_MODEL_NAME
ZEBRA_MODEL_API_KEY_ENV
ZEBRA_DEEPSEEK_EXECUTOR_PROFILE
ZEBRA_DEEPSEEK_PLANNER_PROFILE
ZEBRA_DEEPSEEK_REVIEWER_PROFILE
ZEBRA_DEEPSEEK_SUMMARIZER_PROFILE
ZEBRA_DEEPSEEK_ANALYST_PROFILE
ZEBRA_DEEPSEEK_CLASSIFIER_PROFILE
```

这会导致以下问题：

1. 一个 Deployment 默认共享同一组模型连接。
2. 不同项目难以使用不同 Provider Account。
3. 不同 Agent Release 难以独立发布模型策略。
4. 模型 Context Window 主要来自代码内静态 Profile。
5. Provider 限流、项目并发、Agent 并发和 Team 并发尚未统一。
6. `cost_usd` 字段存在，但缺少 Pricing Version 和确定性 Cost Calculator。
7. Model Call Record 主要按 Session 查询，缺少 Project、Agent Release、Team、Cost Center 等归因维度。
8. 运行中的模型选择还没有被完整冻结到 Task 级不可变快照。
9. Provider Credential 主要从环境变量解析，尚未形成平台 Connection Profile 与 Credential Ref 管理。
10. 配置变更、灰度、回滚和环境 Diff 没有统一产品入口。

### 2.3 已具备的多 Agent 基础

当前 Zebra 已经具备：

```text
Durable Child Task
ParentChildLink
Orchestration Plan
DAG Validation
DAG Scheduler
Budget Reservation
Budget Usage Receipt
Agent Team
Shared Task List
Write Ownership
Completion Gate
```

当前 Agent Team V1 已限定：

```text
同一 deployment namespace
最多四个 Agent
深度为一
Teammate 不继续创建 Child
写入路径互斥
```

当前 Multi-Agent Budget 已覆盖：

```text
model_tokens
tool_calls
runtime_seconds
```

仍需补充：

```text
money budget
provider request concurrency
TPM
RPM
per-role concurrency
per-model concurrency
pricing version
cost reservation
cost reconciliation
```

### 2.4 当前组件基础

Zebra Desktop 已经使用：

```text
React 19
Vite
pnpm
@lobehub/ui
Ant Design
antd-style
motion
```

这说明 LobeHub UI 在 Zebra 体系内已经经过一次真实集成。

当前 Desktop 对 LobeHub UI 存在深路径导入，例如：

```text
@lobehub/ui/es/ThemeProvider/ThemeProvider
```

后续公共 SDK 应消除这种耦合，统一通过 Zebra Wrapper 和稳定导出访问 LobeHub UI。

---

## 3. 还缺少的产品能力

除项目、记忆、Skill、MCP、Plugin 和模型配置外，中台还需要补齐以下能力。

### 3.1 Prompt 与 Instruction Center

需要管理：

```text
System Prompt
Role Prompt
Planner Prompt
Reviewer Prompt
Tool Instruction
Safety Instruction
Project Instruction
Output Contract
Prompt Variable Schema
Prompt Evaluation
Prompt Version
Prompt Diff
Prompt Canary
Prompt Rollback
```

Prompt 和 Project Context 必须分离：

```text
Project Context
描述项目事实、术语、架构和约束

Prompt
描述 Agent 的角色、行为、步骤和输出要求
```

### 3.2 Knowledge Source Center

知识源与 Memory 需要分开治理：

```text
Knowledge Source
外部文档、数据集、代码库、API、索引和检索源

Memory
Agent 从历史执行中提取并经过治理的长期事实

Project Context
平台人员显式维护的项目基线事实
```

知识源中心需要支持：

```text
Document Collection
Repository
Website
Object Storage
Database View
Vector Index
Graph Index
Data Freshness
Ingestion Job
Chunk Policy
Embedding Profile
Retrieval Policy
Access Policy
Citation Policy
```

### 3.3 Provider Connection Center

模型 Provider 与 Model Catalog 之间应保留连接层：

```text
Provider
描述供应商和协议能力

Connection Profile
描述 endpoint、credential_ref、region、timeout、network policy

Model Catalog Entry
描述某个模型的能力和硬限制

Invocation Profile
描述某类 Agent Role 的调用策略
```

### 3.4 Runtime Profile Center

需要管理：

```text
Sandbox Class
OCI Image Digest
CPU
Memory
PID
Tmpfs
Workspace Quota
Network Policy
Execution Timeout
Output Limit
Region
Availability Zone
Warm Pool
```

### 3.5 Evaluation 与 Experiment Center

需要支持：

```text
Golden Dataset
Offline Evaluation
Provider Smoke
Prompt Comparison
Model Comparison
A/B Experiment
Shadow Traffic
Canary
Quality Gate
Latency Gate
Cost Gate
Regression Detection
Rollback
```

### 3.6 Data Governance Center

需要管理：

```text
PII Classification
Data Residency
Retention
Redaction
Export Policy
Prompt Logging Policy
Model Provider Allowlist
Training Usage Prohibition
Cross-Border Policy
Artifact Retention
Memory Retention
```

### 3.7 Secret 与 Credential Reference Center

只允许管理引用与元数据：

```text
credential_ref
secret_manager_ref
rotation_status
expires_at
last_rotated_at
owner
provider
environment
```

管理界面不得读取明文 Secret。

### 3.8 Notification 与 Incident Center

需要支持：

```text
Budget Alert
Provider Outage
Rate Limit Alert
Model Quality Regression
Connector Failure
MCP Failure
Client Effect Backlog
Memory Review Backlog
Plugin Security Finding
Production Gate Failure
```

### 3.9 Template 与 Automation Center

需要支持：

```text
Project Template
Agent Template
Agent Team Template
Task Template
Scheduled Task
Event Trigger
Webhook Trigger
Release Pipeline Template
Conformance Template
```

### 3.10 Developer Center

需要提供：

```text
SDK
Component Catalog
Hook Playground
API Explorer
Schema Registry
Code Generator
Integration Doctor
Conformance Runner
Examples
Migration Guide
Compatibility Matrix
Release Notes
```

---

## 4. 统一业务对象与边界

### 4.1 核心对象

```text
Project
AgentDefinition
AgentRelease
AgentTeamTemplate
ProjectContextProfile
PromptProfile
KnowledgeSourceProfile
MemoryPolicy
SkillSnapshot
MCPProfile
PluginEnablementSnapshot
ModelPolicy
RuntimePolicy
SecurityPolicy
FrontendCapabilityProfile
HostCapabilityManifest
EffectiveAgentRuntimeSnapshot
TaskBindingSnapshot
ExecutionAuthoritySnapshot
```

### 4.2 概念边界

| 对象 | 负责内容 | 禁止承载 |
|---|---|---|
| Project Context | 项目事实、术语、架构、业务规则 | 模型凭据、临时对话 |
| Prompt Profile | Agent 行为、角色和输出指令 | 项目业务事实、Secret |
| Knowledge Source | 可检索外部知识 | Agent 长期学习状态 |
| Memory | 历史执行沉淀的治理知识 | 未审核的任意外部文档 |
| Skill | 可复用的执行方法和流程 | Provider Credential |
| Tool | 可执行能力 | 项目背景文本 |
| MCP Profile | MCP 连接与工具快照 | 运行中动态扩权 |
| Plugin | Skill、MCP、Hook 的分发安装单位 | Task 权限事实 |
| Model Policy | 模型选择、路由、上下文和限额 | API Key 明文 |
| Provider Connection | Endpoint 与 Credential Ref | Agent 业务行为 |
| Pricing Version | Provider 成本事实 | 客户收费策略 |
| Billing Plan | 内部计费与客户 Chargeback | Provider 原始用量事实 |
| Task Snapshot | 某次运行固定配置 | 动态 latest 引用 |

### 4.3 事实源

```text
Agent Registry
Agent 配置事实源

Project Registry
项目配置事实源

Model Registry
模型与调用策略事实源

Memory Store
记忆事实源

Capability Registries
Skill、MCP、Plugin 和 Tool 配置事实源

Event Store
Task 执行事实源

Usage Ledger
用量事实源

Cost Ledger
平台计算成本事实源

Host Database
业务数据事实源
```

### 4.4 运行冻结规则

每个新 Task 必须冻结：

```text
Project Context Snapshot Digest
Prompt Snapshot Digest
Agent Release Digest
Model Binding Snapshot Digest
Context Policy Digest
Memory Selection Snapshot Digest
Skill Snapshot Digest
MCP Snapshot Digest
Plugin Enablement Snapshot Digest
Host Capability Snapshot Digest
Frontend Capability Snapshot Digest
Runtime Policy Digest
Security Policy Digest
Pricing Version Digest
Budget Policy Digest
```

运行中的 Task 不允许静默切换：

```text
模型
Prompt
Skill
MCP Tool
Plugin
Pricing Version
Context Window
Concurrency Policy
Memory Revision
```

撤权与安全 Revocation 可以进一步收窄或终止运行。

---

## 5. 中台信息架构调整

建议导航调整为：

```text
概览

项目中心
├── 项目列表
├── 项目背景
├── Prompt 绑定
├── 知识源
├── 项目 Agents
├── 项目 Teams
├── 环境配置
└── Effective Configuration

Agent Studio
├── Agent Definitions
├── Drafts
├── Versions
├── Releases
├── Single Agent Config
├── Evaluation
└── Release Pipeline

Multi-Agent Studio
├── Team Templates
├── Agent Matrix
├── DAG Designer
├── Context Sharing
├── Budget
├── Completion Gate
└── Team Releases

Prompt 与上下文
├── Prompt Registry
├── Instruction Profiles
├── Context Policies
├── Context Simulator
├── Compaction Policies
└── Prompt Experiments

知识与记忆
├── Knowledge Sources
├── Ingestion Jobs
├── Retrieval Policies
├── Memory Explorer
├── Review Queue
├── Memory Policies
├── Conflicts
└── Usage Traces

能力资产
├── Skills
├── MCP
├── Plugins
├── Tools
├── Tool Profiles
└── Capability Profiles

模型中心
├── Providers
├── Connections
├── Model Catalog
├── Capability Profiles
├── Invocation Profiles
├── Routing Policies
├── Context Policies
├── Concurrency Policies
├── Pricing
├── Budget Policies
├── Usage
├── Cost
├── Health
└── Evaluation

接入中心
├── Hosts
├── Connectors
├── Backend Manifests
├── Frontend Profiles
└── Namespace Bindings

运行中心
├── Tasks
├── Orchestration
├── Subagents
├── Agent Teams
├── Model Calls
├── Effects
├── Client Effects
├── Artifacts
└── Runtime Fleet

质量与发布
├── Conformance
├── Evaluations
├── Experiments
├── Dry Runs
├── Canary
├── Rollout
└── Rollback

治理与审计
├── Policies
├── Quotas
├── Data Governance
├── Security
├── Audit
├── Incidents
└── Notifications

开发者中心
├── SDK
├── Component Catalog
├── Hook Playground
├── API Explorer
├── Schema Registry
├── Code Generator
├── Integration Doctor
└── Compatibility Matrix
```

---

## 6. Model Control Plane 领域设计

### 6.1 ModelProviderDefinition

描述供应商协议能力：

```python
ModelProviderDefinition(
    provider_id,
    display_name,
    protocol_family,
    supported_auth_modes,
    supported_regions,
    supports_streaming,
    supports_tools,
    supports_strict_tools,
    supports_thinking,
    supports_structured_output,
    supports_images,
    supports_audio,
    supports_prompt_cache,
    lifecycle_status,
    revision,
)
```

Provider Definition 不保存 Endpoint 和 Credential。

### 6.2 ModelConnectionProfileVersion

描述一个可用连接：

```python
ModelConnectionProfileVersion(
    connection_id,
    provider_id,
    profile_revision,
    base_uri,
    credential_ref,
    workload_identity_ref,
    region,
    provider_account_ref,
    network_policy_ref,
    timeout_profile_ref,
    proxy_ref,
    TLS_policy_ref,
    max_inflight_requests,
    rpm_limit,
    tpm_limit,
    burst_limit,
    status,
    connection_digest,
)
```

状态：

```text
draft
validated
published
deprecated
revoked
```

### 6.3 ModelCatalogEntryVersion

描述模型事实：

```python
ModelCatalogEntryVersion(
    model_catalog_id,
    provider_id,
    provider_model_id,
    catalog_revision,
    display_name,
    modalities,
    supported_roles,
    supports_tools,
    supports_strict_tools,
    supports_thinking,
    supports_structured_output,
    context_window_hard_limit,
    max_output_hard_limit,
    reasoning_limit,
    tokenizer_ref,
    provider_document_version,
    availability_regions,
    status,
    catalog_digest,
)
```

模型 Catalog 只保存可验证的模型能力和硬上限。

### 6.4 ModelCapabilityProfileVersion

用于平台归一化模型能力：

```text
fast-classification
long-context-analysis
tool-executor
high-reasoning-planner
high-reasoning-reviewer
multimodal-vision
cost-optimized
latency-optimized
```

这样 AgentDefinition 可以声明能力需求，平台再解析到具体模型。

### 6.5 ModelInvocationProfileVersion

描述一次 Role 的调用参数：

```python
ModelInvocationProfileVersion(
    invocation_profile_id,
    revision,
    connection_profile_ref,
    model_catalog_ref,
    role,
    thinking_mode,
    reasoning_effort,
    tool_choice_policy,
    strict_tools,
    max_output_tokens,
    timeout_seconds,
    max_retries,
    response_repair_limit,
    temperature,
    top_p,
    stop_policy_ref,
    prompt_profile_ref,
    context_policy_ref,
    pricing_ref,
    status,
    digest,
)
```

V1 对 Temperature、Top P 等字段采用 Provider Capability 校验。Provider 不支持时禁止发布。

### 6.6 ModelRoutingPolicyVersion

V1 支持两种模式：

```text
fixed
ordered-fallback
```

示例：

```text
planner
1. deepseek-v4-pro-planner-v3
2. approved-fallback-planner-v2

executor
1. deepseek-v4-flash-executor-v4
2. deepseek-v4-pro-executor-v2
```

V1 禁止自动按实时价格和质量动态切换，以避免重放与成本解释困难。

后续版本可以增加：

```text
cost-aware
latency-aware
quality-aware
capacity-aware
experiment
```

### 6.7 ContextBudgetPolicyVersion

详见第 9 章。

### 6.8 ModelConcurrencyPolicyVersion

详见第 10 章。

### 6.9 ModelPricingVersion

详见第 11 章。

### 6.10 ModelBudgetPolicyVersion

定义：

```text
per_task_token_limit
per_task_cost_limit
per_day_token_limit
per_day_cost_limit
per_month_token_limit
per_month_cost_limit
warning_thresholds
hard_stop_thresholds
currency
cost_center
```

### 6.11 ModelEvaluationProfileVersion

定义：

```text
evaluation_dataset_refs
quality_metrics
latency_threshold
cost_threshold
tool_call_accuracy_threshold
structured_output_pass_rate
safety_threshold
regression_tolerance
promotion_gate
```

### 6.12 EffectiveModelBindingSnapshot

Task Admission 时生成：

```python
EffectiveModelBindingSnapshot(
    task_id,
    agent_release_digest,
    project_id,
    environment,
    role_bindings,
    routing_policy_digest,
    context_policy_digest,
    concurrency_policy_digest,
    budget_policy_digest,
    pricing_digests,
    connection_profile_digests,
    model_catalog_digests,
    resolved_at,
    snapshot_digest,
)
```

每个 Role Binding 固定：

```text
requested role
primary invocation profile
fallback invocation profiles
connection revision
model revision
context hard limit
effective output limit
timeout
retry
pricing version
```

---

## 7. 模型配置继承与覆盖规则

### 7.1 配置层次

```text
Provider Hard Limit
→ Platform Policy
→ Tenant Policy
→ Project Policy
→ AgentDefinition Policy
→ Agent Release Binding
→ Team Policy
→ Role Policy
→ Task Request Narrowing
```

### 7.2 选择型字段

例如具体模型和 Routing Policy：

```text
Role 级显式绑定
优先于 Agent 默认绑定

Agent 显式绑定
优先于 Project 默认绑定

Project 默认绑定
优先于 Tenant 默认绑定

所有绑定必须属于上层允许集合
```

### 7.3 限额型字段

采用最小值：

```text
Effective Limit
=
min(
    Provider Hard Limit,
    Connection Limit,
    Platform Limit,
    Tenant Limit,
    Project Limit,
    Agent Limit,
    Team Limit,
    Role Limit,
    Task Requested Limit
)
```

### 7.4 能力型字段

采用交集：

```text
Effective Model Capabilities
=
Model Catalog Capabilities
∩ Connection Capabilities
∩ Platform Policy
∩ Project Policy
∩ Agent Capability Requirements
∩ Task Authority
```

### 7.5 Credential

Credential 只通过以下链路解析：

```text
Task Binding
→ Pinned Connection Profile
→ Credential Ref
→ Credential Resolver
→ Ephemeral Credential
```

Credential 不进入：

```text
AgentDefinition
Prompt
Task Event
Model Event
Audit Detail
Browser
Frontend SDK
```

---

## 8. 单 Agent 配置设计

### 8.1 Single Agent Studio 页面

建议分为十四个 Tab：

```text
1. Identity
2. Project Binding
3. Prompt
4. Models
5. Context
6. Memory
7. Knowledge
8. Skills
9. MCP
10. Plugins
11. Tools and Capabilities
12. Runtime and Security
13. Limits and Cost
14. Evaluation and Release
```

### 8.2 Models Tab

#### 简单模式

用户选择：

```text
Balanced
Fast
High Quality
Low Cost
Long Context
Tool Heavy
Custom
```

系统将 Preset 解析为版本化 Invocation Profile。

#### 高级模式

展示 Role Matrix：

| Role | Primary Model | Fallback | Thinking | Tools | Max Output | Timeout | Retry | Context Policy | Price |
|---|---|---|---|---|---:|---:|---:|---|---|
| Executor | Profile | Profile | Disabled | Required | Value | Value | Value | Policy | Version |
| Planner | Profile | Profile | Max | None | Value | Value | Value | Policy | Version |
| Reviewer | Profile | Profile | High | None | Value | Value | Value | Policy | Version |
| Analyst | Profile | Profile | High | Optional | Value | Value | Value | Policy | Version |
| Summarizer | Profile | Profile | Disabled | None | Value | Value | Value | Policy | Version |
| Classifier | Profile | Profile | Disabled | None | Value | Value | Value | Policy | Version |

### 8.3 Limits and Cost Tab

字段包括：

```text
Max Model Calls per Task
Max Input Tokens per Call
Max Output Tokens per Call
Max Total Tokens per Task
Max Cost per Task
Max Runtime Seconds
Max Tool Calls
Max Active Tasks
Max Inflight Model Requests
RPM
TPM
Daily Token Budget
Daily Cost Budget
Monthly Token Budget
Monthly Cost Budget
Warning Threshold
Hard Stop Policy
```

### 8.4 Effective Configuration Preview

必须展示：

```text
最终 Model Role Matrix
最终 Context Waterfall
最终 Tool Surface
最终 Memory Policy
最终 Knowledge Sources
最终 Skill Snapshot
最终 MCP Snapshot
最终 Plugin Snapshot
最终 Runtime Profile
最终 Concurrency
最终 Token Budget
最终 Cost Budget
最终 Pricing Version
最终 Security Findings
```

每个字段支持 Source Trace：

```text
Platform
Tenant
Project
AgentDefinition
Agent Release
Environment
Task Request
```

### 8.5 发布流程

```text
Draft
→ Schema Validate
→ Capability Validate
→ Connection Smoke
→ Context Simulation
→ Cost Simulation
→ Evaluation
→ Security Gate
→ Publish Version
→ Canary
→ Promote
```

已发布版本不可编辑。

---

## 9. Context Engineering Center

### 9.1 上下文预算结构

建议将 Context Window 拆分为：

```text
Hard Context Window
├── Max Output Reserve
├── Reasoning Reserve
├── Protocol Reserve
├── Tool Schema Budget
├── System Prompt Budget
├── Project Context Budget
├── Knowledge Evidence Budget
├── Memory Budget
├── Skill Budget
├── Conversation Tail Budget
├── Artifact Budget
└── Compaction Reserve
```

有效输入上限：

```text
Effective Input Limit
=
min(
    Provider Context Hard Limit,
    Model Catalog Limit,
    Project Context Limit,
    Agent Context Limit,
    Role Context Limit,
    Task Context Limit
)
- Output Reserve
- Reasoning Reserve
- Protocol Reserve
- Compaction Reserve
```

### 9.2 Context Policy 字段

```python
ContextBudgetPolicyVersion(
    hard_context_limit,
    max_output_tokens,
    reasoning_reserve_tokens,
    protocol_reserve_tokens,
    compaction_reserve_tokens,
    tool_schema_budget,
    system_prompt_budget,
    project_context_budget,
    knowledge_budget,
    memory_budget,
    skill_budget,
    conversation_tail_budget,
    artifact_budget,
    auto_compact_at,
    exact_tail_min_messages,
    overflow_strategy,
    tokenizer_ref,
    digest,
)
```

### 9.3 Overflow Strategy

V1 支持：

```text
reject
compact_then_retry
drop_low_priority_knowledge
drop_low_priority_memory
shrink_conversation_tail
switch_to_long_context_fallback
```

策略必须确定性执行。

### 9.4 Context Simulator

输入：

```text
Project
Agent Release
Role
User Prompt
Tool Surface
Selected Memories
Knowledge Query
Attachments
```

输出：

```text
Token Waterfall
Estimated Input
Hard Limit
Compaction Trigger
Largest Contributor
Selected Memory
Dropped Memory
Selected Evidence
Dropped Evidence
Tool Schema Cost
Estimated Provider Cost
Potential Fallback
```

### 9.5 验收边界

1. Simulator 与 Worker 使用同一 Context Planner。
2. Tokenizer 不可用时标记 Estimate。
3. Provider 返回实际 Token 后记录 Estimate Error。
4. 超限请求在模型调用前被阻止。
5. 运行重放使用相同 Context Policy Digest。
6. 修改 Policy 不影响已启动 Task。
7. Context Preview 不显示 Secret。
8. Tool Schema 和 Prompt 的 Token 成本可见。

---

## 10. 并发、限流和公平调度

### 10.1 并发层次

需要分别管理：

```text
Tenant Active Tasks
Project Active Tasks
Agent Active Tasks
Agent Release Active Tasks
Team Active Runs
Role Active Nodes
Connection Inflight Requests
Model Inflight Requests
Provider Account Inflight Requests
Tool Inflight Calls
Client Effect Inflight Calls
Orchestration Max Parallelism
```

### 10.2 限流维度

```text
Requests Per Minute
Tokens Per Minute
Input Tokens Per Minute
Output Tokens Per Minute
Concurrent Requests
Burst Requests
Concurrent Tasks
Concurrent Child Tasks
Concurrent Write Effects
```

### 10.3 ModelConcurrencyPolicyVersion

```python
ModelConcurrencyPolicyVersion(
    policy_id,
    revision,
    max_active_tasks,
    max_active_runs,
    max_inflight_model_requests,
    max_inflight_per_role,
    max_inflight_per_model,
    max_inflight_per_connection,
    requests_per_minute,
    tokens_per_minute,
    burst_requests,
    queue_timeout_seconds,
    reservation_ttl_seconds,
    fairness_weight,
    overflow_behavior,
    digest,
)
```

### 10.4 Overflow Behavior

```text
queue
reject
degrade_to_fallback
pause_orchestration
```

V1 默认：

```text
queue
```

### 10.5 分布式实现建议

```text
PostgreSQL
持久化 Concurrency Reservation、Lease、Owner、Expiry 和审计

Redis
执行 RPM、TPM 和 Burst Token Bucket

Scheduler
执行 Tenant、Project 和 Agent 公平排队
```

Redis 故障策略：

```text
生产环境采用 conservative fail-closed
已获得 PostgreSQL Reservation 的运行可以继续
新的高并发 Reservation 暂停或进入保守低配额模式
```

### 10.6 Reservation 状态

```text
queued
reserved
admitted
running
released
expired
rejected
```

### 10.7 多 Agent 并发规则

```text
Team Max Parallelism
≤ Project Policy
≤ Tenant Policy
≤ Platform Policy
```

每个 Child 节点还受：

```text
Role Concurrency
Model Concurrency
Connection Concurrency
Parent Budget Reservation
```

约束。

### 10.8 验收边界

1. 不使用进程内 Semaphore 作为权威并发控制。
2. Worker 崩溃后 Reservation 可以过期回收。
3. 重复 Admission 不重复占用并发槽位。
4. 两个 Scheduler 同时调度不会突破上限。
5. 高权重项目不能完全饿死低权重项目。
6. Provider 429 反馈可以降低动态可用容量，但不能修改配置事实。
7. 并发策略更新只影响新的 Reservation。
8. Team 节点并发不突破父级上限。
9. Client 和 Host Effect 不计入 Model Request 并发。
10. 队列等待时间可观测。

---

## 11. Token、Pricing、Cost 和 Billing

### 11.1 四层数据必须分开

```text
Provider Usage Fact
供应商返回的原始 Token 使用事实

Platform Cost
平台根据固定 Pricing Version 计算的供应商成本

Provider Reported Cost
供应商直接返回的费用，仅作为对账事实

Chargeback
平台对项目、部门或客户的内部结算结果
```

### 11.2 ModelPricingVersion

价格不能直接写在 Model Profile 中。

```python
ModelPricingVersion(
    pricing_id,
    provider_id,
    model_catalog_ref,
    region,
    currency,
    effective_from,
    effective_to,
    input_price_per_million,
    output_price_per_million,
    reasoning_price_per_million,
    cache_hit_price_per_million,
    cache_miss_price_per_million,
    image_input_price,
    image_output_price,
    audio_input_price,
    request_base_price,
    source_ref,
    revision,
    pricing_digest,
)
```

### 11.3 ModelUsageReceipt

```python
ModelUsageReceipt(
    model_call_id,
    task_id,
    agent_definition_id,
    agent_release_id,
    project_id,
    team_id,
    orchestration_run_id,
    role,
    provider_id,
    connection_id,
    model_catalog_id,
    pricing_id,
    input_tokens,
    output_tokens,
    reasoning_tokens,
    cache_hit_tokens,
    cache_miss_tokens,
    image_units,
    audio_units,
    request_count,
    provider_reported_cost,
    observed_at,
    usage_digest,
)
```

### 11.4 ModelCostLedgerEntry

```python
ModelCostLedgerEntry(
    ledger_entry_id,
    usage_receipt_digest,
    pricing_digest,
    provider_cost,
    currency,
    calculation_version,
    cost_center,
    project_id,
    agent_release_id,
    team_id,
    task_id,
    created_at,
)
```

账本采用 append-only。

纠错通过 Adjustment Entry 完成。

### 11.5 成本估算与结算

调用前：

```text
Context Token Estimate
+ Max Output Reservation
+ Pricing Version
= Estimated Maximum Cost
```

调用后：

```text
Provider Usage
+ Pinned Pricing Version
= Actual Platform Cost
```

随后执行：

```text
Release Unused Cost Reservation
Book Actual Cost
Update Task Budget
Update Project Budget
Update Team Budget
```

### 11.6 Budget Policy

支持：

```text
Per Call
Per Task
Per Agent Run
Per Team Run
Per Project Day
Per Project Month
Per Tenant Month
```

### 11.7 Hard Stop 语义

Hard Stop 只能发生在安全边界：

```text
模型调用前
新 Child Task 创建前
新 Effect 调度前
新 Continuation 恢复前
```

已经提交的业务 Effect 不能因为成本上限中断对账。

### 11.8 V1 收费范围

V1 建议只支持：

```text
USD
Provider Cost
Project Chargeback
Cost Center
Budget Alert
Usage Export
```

V1 暂不包含：

```text
客户发票
税务
多币种结算
实时汇率
支付
套餐扣费
信用额度
```

### 11.9 使用与成本页面

支持维度：

```text
Tenant
Project
Agent
Agent Release
Team
Role
Task
Provider
Connection
Model
Region
Environment
Cost Center
Day
Month
```

关键指标：

```text
Input Tokens
Output Tokens
Reasoning Tokens
Cache Hit Tokens
Cache Miss Tokens
Estimated Cost
Actual Cost
Cost Per Successful Task
Cost Per Evaluation Point
Cache Hit Rate
Average Context Utilization
429 Rate
Retry Cost
Failed Call Cost
```

---

## 12. Multi-Agent Studio 设计

### 12.1 适用对象

```text
Orchestrator Agent
Durable Subagent
Agent Team
DAG Workflow
Worktree Coding Team
Research Team
Review Team
```

### 12.2 Team Template

```python
AgentTeamTemplateVersion(
    team_template_id,
    revision,
    lead_agent_release_ref,
    members,
    graph,
    max_agents,
    max_depth,
    max_parallelism,
    context_sharing_policy_ref,
    model_budget_policy_ref,
    completion_gate_ref,
    failure_policy_ref,
    mailbox_policy_ref,
    workspace_policy_ref,
    digest,
)
```

### 12.3 Agent Matrix

页面采用矩阵编辑：

| Node / Role | Agent Release | Model Profile | Context Policy | Memory Policy | Skills | MCP | Max Parallel | Token Budget | Cost Budget |
|---|---|---|---|---|---|---|---:|---:|---:|
| Lead | Release | Profile | Policy | Policy | Snapshot | Snapshot | 1 | Value | Value |
| Planner | Release | Profile | Policy | Policy | Snapshot | Snapshot | 1 | Value | Value |
| Researcher | Release | Profile | Policy | Policy | Snapshot | Snapshot | 2 | Value | Value |
| Reviewer | Release | Profile | Policy | Policy | Snapshot | Snapshot | 1 | Value | Value |
| Presenter | Release | Profile | Policy | Policy | Snapshot | Snapshot | 1 | Value | Value |

### 12.4 Context Sharing

支持：

```text
fresh
capsule
fork_tail
resume
result_bundle
```

每个节点必须明确：

```text
读取哪些 Parent Context
读取哪些 Memory
读取哪些 Knowledge
读取哪些 Artifact
输出什么 Result Contract
```

### 12.5 模型配置

Orchestrator 只能提出：

```text
required role
required capability tier
latency preference
cost preference
context requirement
```

Control Plane 解析为已批准的 Invocation Profile。

Orchestrator 无权填写：

```text
任意 Provider URL
任意 Model ID
任意 Credential
任意 Pricing
任意 Concurrency Override
```

### 12.6 Team Budget

```text
Parent Ceiling
├── Lead Reservation
├── Planner Reservation
├── Researcher Reservations
├── Reviewer Reservation
└── Presenter Reservation
```

Child Actual Usage 完成后：

```text
Book Receipt
Release Unused Reservation
Update Parent Remaining
```

### 12.7 UI 控制

同一个 Run 只允许：

```text
Root Agent
或 Presenter Agent
```

持有前端 UI Control。

Researcher、Reviewer、Tester 等角色只能产出 UI Intent Proposal。

### 12.8 发布流程

```text
Team Draft
→ Agent Release Resolve
→ Graph Validate
→ Capability Validate
→ Model Validate
→ Context Simulation
→ Concurrency Simulation
→ Budget Simulation
→ Owned Path Validate
→ Evaluation
→ Publish
→ Canary
```

### 12.9 验收边界

1. Team 成员全部固定 Agent Release。
2. Team 成员模型全部固定 Invocation Profile。
3. Child 能力不超过 Parent。
4. Child Token 和 Cost 预算不超过 Parent Reservation。
5. Team 并发不超过 Project。
6. DAG 环在发布前拒绝。
7. Fallback Model 必须满足同一 Role Contract。
8. Reviewer 失败不能静默完成。
9. Uncertain Effect 阻止 Completion Gate。
10. Team Release 变更不影响历史 Run。

---

## 13. Effective Agent Runtime Snapshot

### 13.1 目标

建立统一快照，回答：

```text
某个 Agent 在某个 Project、Environment 和 Release 下
知道什么
使用什么 Prompt
能使用什么 Memory
能检索什么 Knowledge
能调用什么 Skill、MCP、Plugin 和 Tool
使用什么模型
上下文上限是多少
并发上限是多少
Token 和 Cost 上限是多少
运行在哪个 Runtime
能控制哪些前端能力
```

### 13.2 快照结构

```python
EffectiveAgentRuntimeSnapshot(
    project_context_digest,
    prompt_digest,
    knowledge_policy_digest,
    memory_policy_digest,
    skill_snapshot_digest,
    mcp_snapshot_digest,
    plugin_snapshot_digest,
    tool_profile_digest,
    host_capability_digest,
    frontend_capability_digest,
    model_binding_digest,
    context_policy_digest,
    concurrency_policy_digest,
    pricing_digests,
    budget_policy_digest,
    runtime_policy_digest,
    security_policy_digest,
    evaluation_profile_digest,
    resolved_sources,
    snapshot_digest,
)
```

### 13.3 Source Trace

每一项配置标记来源：

```text
system
tenant
project
agent-definition
agent-release
team-template
role
environment
task-request
```

### 13.4 页面能力

```text
Resolved Config
Raw JSON
Source Trace
Version Diff
Environment Diff
Capability Diff
Context Waterfall
Cost Simulation
Security Findings
Release Impact
Historical Task Comparison
```

---

## 14. TypeScript SDK 与组件体系

### 14.1 总体原则

组件体系分为三层：

```text
协议层
纯 TypeScript Contract 和 Client Runtime

Headless React 层
Provider、Hooks、状态和行为

Lobe UI 视觉层
对 LobeHub UI 的二次封装和 Zebra 业务组件
```

### 14.2 推荐包结构

```text
sdks/typescript/
├── packages/
│   ├── contracts/
│   ├── client-core/
│   ├── react/
│   ├── ui-lobe/
│   ├── platform-widgets/
│   ├── next/
│   ├── copilotkit-adapter/
│   ├── devtools/
│   └── create-zebra-agent/
├── examples/
│   ├── react-vite/
│   ├── next-app-router/
│   ├── trench-demo/
│   ├── headless-demo/
│   └── platform-console-demo/
├── conformance/
└── docs/
```

### 14.3 包职责

#### `@zebra-agent/contracts`

```text
OpenAPI 生成类型
JSON Schema 类型
AG-UI 扩展事件
Client Effect Contract
Frontend Capability Contract
Model Center DTO
Runtime Query DTO
```

要求：

```text
无 React
无 Lobe UI
无浏览器全局依赖
可用于 Node、Browser 和 BFF
```

#### `@zebra-agent/client-core`

```text
SSE Replay
Command Client
Idempotency
Client Session
Controller Lease
Client Effect Dispatch
Receipt Retry
Usage Query
Effective Config Query
```

#### `@zebra-agent/react`

```text
ZebraAgentProvider
useZebraTask
useZebraAgentState
useZebraReadable
useZebraAction
useZebraApproval
useZebraClarification
useZebraUsage
useZebraClientStatus
```

该包保持 Headless，不依赖 Lobe UI。

#### `@zebra-agent/ui-lobe`

```text
AgentShell
AgentChat
AgentComposer
AgentStatus
TaskTimeline
ToolCallCard
ApprovalCard
ClarificationCard
ArtifactPanel
UsageBadge
CostBadge
SubagentPanel
OrchestrationGraph
ClientEffectPanel
```

#### `@zebra-agent/platform-widgets`

用于中台配置页面：

```text
ProjectContextEditor
PromptProfileEditor
KnowledgeSourceEditor
MemoryExplorer
MemoryReviewPanel
SkillCatalog
SkillEditor
McpServerEditor
PluginLifecyclePanel
ModelProviderForm
ModelConnectionForm
ModelCatalogTable
ModelRoleMatrix
ContextBudgetEditor
ContextWaterfall
RoutingPolicyEditor
ConcurrencyPolicyEditor
PricingEditor
UsageCostDashboard
EffectiveConfigInspector
MultiAgentMatrix
DAGDesigner
ReleaseDiff
AuditTimeline
```

#### `@zebra-agent/next`

```text
BFF Route Handler
Server-side Token Exchange
SSE Proxy
Cookie-safe Session Adapter
App Router Helpers
```

#### `@zebra-agent/copilotkit-adapter`

将 Zebra Hooks 映射到 CopilotKit，不改变 Zebra 事实源。

#### `@zebra-agent/devtools`

```text
Event Inspector
State Inspector
Capability Inspector
Client Effect Inspector
Context Debugger
Token Waterfall
Connection Diagnostics
```

#### `create-zebra-agent`

生成：

```text
Provider
BFF Routes
Example Hooks
Environment Template
Frontend Profile Manifest
Conformance Tests
Integration Doctor Config
```

---

## 15. TSDX 使用决策

### 15.1 可行性

TSDX 2.0 适合用于：

```text
contracts
client-core
react
next
copilotkit-adapter
devtools
create-zebra-agent
```

其当前工具链支持：

```text
TypeScript
ESM/CJS
Declaration
Vitest
Oxlint
Oxfmt
Bunchee
React Template
```

### 15.2 Lobe UI 包的特殊处理

LobeHub UI 当前采用 ESM 包结构，并依赖 React 19、Ant Design 6 和 Motion。

因此：

```text
@zebra-agent/ui-lobe
@zebra-agent/platform-widgets
```

建议采用 ESM-only。

可通过 TSDX 的 Bunchee 底层能力构建，但必须用真实 Consumer App 验证：

```text
Tree Shaking
CSS Side Effects
React Server Components
Next.js Transpilation
Vite
Tauri
Subpath Exports
```

若 TSDX 对 ESM-only 和 CSS 输出控制不足，保留 TSDX 脚手架约定，构建命令改为直接调用 Bunchee 或 tsdown。

### 15.3 包管理器边界

当前 Zebra Desktop 使用 pnpm，TSDX 2.0 的官方工作流偏向 Bun。

建议第一阶段采用：

```text
仓库内隔离的 sdks/typescript Bun Workspace
```

要求：

```text
不加入当前 pnpm workspace
不在仓库根生成第二份冲突 Lockfile
CI 独立执行
Desktop 作为 pnpm Consumer 安装已构建 tarball
```

当 SDK 有独立发布节奏后，可迁移到单独仓库：

```text
zebra-agent-js
```

### 15.4 兼容矩阵

#### Headless 包

```text
React 18
React 19
Vite
Next.js App Router
Tauri WebView
Modern Browser
Node 20+
```

#### Lobe UI 包

```text
React 19
Ant Design 6
Lobe UI 固定兼容范围
Next.js
Vite
Tauri
```

### 15.5 Peer Dependency 规则

`@zebra-agent/react`：

```text
react >=18
react-dom >=18
```

`@zebra-agent/ui-lobe`：

```text
react ^19
react-dom ^19
@lobehub/ui 固定兼容区间
antd ^6
motion ^12
```

### 15.6 禁止泄漏上游类型

公共 Props 中不能暴露：

```text
LobeHub UI 内部 Props
Ant Design 内部 Props
antd-style 内部 Theme 类型
LobeHub 深路径类型
```

Zebra 定义稳定语义 Props，Wrapper 内完成映射。

### 15.7 深路径导入

公共包禁止：

```text
@lobehub/ui/es/*
```

统一使用公开 Export 或 Zebra 内部 Adapter。

### 15.8 Design Token

定义：

```text
ZebraColorToken
ZebraSpacingToken
ZebraRadiusToken
ZebraTypographyToken
ZebraStatusToken
ZebraRiskToken
ZebraCostToken
```

LobeHub UI 与 Ant Design 的 Token 映射只存在于 `ui-lobe` 内部。

---

## 16. 组件产品设计

### 16.1 运行时组件

```text
AgentShell
ChatList
MessageItem
Composer
RunStatus
TaskPlan
ToolTimeline
ApprovalPanel
ClarificationPanel
ArtifactViewer
MemoryUsagePanel
SkillUsagePanel
McpUsagePanel
PluginUsagePanel
ModelCallPanel
TokenUsagePanel
CostPanel
ContextWaterfall
SubagentTree
OrchestrationGraph
AgentTeamPanel
ClientEffectPanel
```

### 16.2 配置组件

```text
ProjectContextEditor
PromptEditor
KnowledgeSourcePicker
MemoryPolicyEditor
SkillSnapshotPicker
McpAllowlistEditor
PluginEnablementEditor
ModelProviderEditor
ModelConnectionEditor
ModelCatalogEditor
ModelInvocationProfileEditor
ModelRoleMatrix
ContextPolicyEditor
RoutingPolicyEditor
ConcurrencyPolicyEditor
PricingEditor
BudgetPolicyEditor
RuntimeProfileEditor
SecurityPolicyEditor
EffectiveConfigPreview
```

### 16.3 组件接入层级

#### 最低接入

```tsx
<ZebraAgentProvider>
  <AgentChat />
</ZebraAgentProvider>
```

#### Hook 接入

```tsx
useZebraReadable(...)
useZebraAction(...)
useZebraApproval(...)
```

#### Headless 接入

业务项目使用状态和 Handler，自行渲染 UI。

#### Platform Widget 接入

中台和私有管理系统直接使用完整配置组件。

### 16.4 组件插槽

所有复杂组件支持：

```text
renderHeader
renderFooter
renderMessage
renderTool
renderArtifact
renderApproval
renderEmpty
renderError
slots
classNames
styles
```

同时禁止通过插槽绕过权限和 Receipt 语义。

---

## 17. 新项目低成本接入流程

### 17.1 初始化

```bash
bunx create-zebra-agent my-agent-integration
```

选择：

```text
React Vite
Next.js App Router
Headless
Lobe UI
CopilotKit Adapter
```

### 17.2 生成内容

```text
ZebraAgentProvider
BFF Proxy
Client Grant Route
SSE Route
Readable 示例
Action 示例
Approval 示例
Frontend Profile Manifest
Conformance Tests
Environment Schema
```

### 17.3 平台注册

```text
创建 Project
注册 Host
发布 Connector
发布 Frontend Profile
发布 Agent Release
绑定 Model Policy
运行 Conformance
```

### 17.4 Integration Doctor

检查：

```text
BFF Connectivity
HostGrant
ClientGrant
Origin
SSE Replay
Idempotency
Frontend Profile Digest
Mounted Hook Digest
MCP
Model Connection
Runtime
Usage
```

### 17.5 生产发布

```text
Dry Run
→ Shadow
→ Canary
→ Promote
```

---

## 18. Management API 设计

### 18.1 Project 与 Context

```text
/platform/v1/projects
/platform/v1/project-contexts
/platform/v1/project-bindings
/platform/v1/effective-configs
/platform/v1/context-simulations
```

### 18.2 Prompt 与 Knowledge

```text
/platform/v1/prompts
/platform/v1/prompt-versions
/platform/v1/knowledge-sources
/platform/v1/ingestion-jobs
/platform/v1/retrieval-policies
```

### 18.3 Memory

```text
/platform/v1/memories
/platform/v1/memory-reviews
/platform/v1/memory-policies
/platform/v1/memory-conflicts
/platform/v1/memory-usage
```

### 18.4 Capability Assets

```text
/platform/v1/skills
/platform/v1/skill-snapshots
/platform/v1/mcp-servers
/platform/v1/mcp-snapshots
/platform/v1/plugins
/platform/v1/plugin-enablement
```

### 18.5 Model Center

```text
/platform/v1/model-providers
/platform/v1/model-connections
/platform/v1/model-catalog
/platform/v1/model-capability-profiles
/platform/v1/model-invocation-profiles
/platform/v1/model-routing-policies
/platform/v1/context-policies
/platform/v1/model-concurrency-policies
/platform/v1/model-pricing
/platform/v1/model-budget-policies
/platform/v1/model-evaluations
```

### 18.6 Multi-Agent

```text
/platform/v1/agent-team-templates
/platform/v1/orchestration-templates
/platform/v1/completion-gates
/platform/v1/team-releases
```

### 18.7 Runtime Query

```text
/v1/tasks/{task_id}/effective-config
/v1/tasks/{task_id}/model-calls
/v1/tasks/{task_id}/usage
/v1/tasks/{task_id}/cost
/v1/tasks/{task_id}/context
/v1/orchestration-runs/{run_id}/usage
/v1/orchestration-runs/{run_id}/cost
/v1/agent-teams/{team_id}/usage
```

---

## 19. 权限模型

新增角色：

```text
Model Administrator
Model Publisher
Cost Administrator
Billing Viewer
Prompt Publisher
Knowledge Administrator
Team Publisher
SDK Maintainer
```

### 19.1 Model Administrator

可以管理：

```text
Provider
Connection
Credential Ref
Model Catalog
Concurrency
Pricing
```

### 19.2 Agent Publisher

可以绑定已发布 Model Profile，但不能创建 Connection 或修改 Pricing。

### 19.3 Cost Administrator

可以管理：

```text
Budget Policy
Cost Center
Chargeback Rule
Adjustment
```

不能读取 Credential。

### 19.4 Project Admin

可以在项目允许集合中绑定：

```text
Agent
Model Policy
Memory Policy
Skill
MCP
Plugin
```

不能扩大 Tenant Ceiling。

### 19.5 高风险操作

以下操作要求 Reason、Expected Revision、Impact Preview、Audit：

```text
Revoke Connection
Revoke Model Profile
修改 Pricing
提高 Cost Budget
提高 Concurrency
启用 Write Plugin
修改 Production Routing
修改 Production Team Template
```

---

## 20. 验证体系

### 20.1 Domain Validation

验证：

```text
Schema
Bounds
Digest
Revision
Lifecycle
Capability Intersection
Limit Narrowing
No Secret
No Moving Alias
```

### 20.2 Provider Connection Validation

```text
DNS
TLS
Auth
Region
Model List
Streaming
Timeout
429
5xx
Token Usage
Cache Usage
```

### 20.3 Model Capability Smoke

```text
Plain Text
Streaming
Tool Call
Strict Tool
Structured Output
Thinking
Reasoning Continuation
Long Context
Cancellation
Retry
Output Truncation
```

### 20.4 Context Validation

```text
Golden Token Count
Fallback Estimator
Budget Waterfall
Compaction
Tool Schema Cost
Memory Selection
Knowledge Selection
Overflow Strategy
Recovery Equality
```

### 20.5 Pricing Validation

```text
Golden Usage
Golden Pricing Version
Golden Calculated Cost
Cache Price
Reasoning Price
Adjustment
Idempotency
Rounding
```

### 20.6 Concurrency Validation

```text
Two Schedulers
Worker Crash
Reservation Expiry
429 Feedback
Redis Failure
PostgreSQL Recovery
Fairness
Queue Timeout
Team Parallelism
```

### 20.7 Budget Validation

```text
Pre-call Reservation
Actual Reconciliation
Unused Release
Child Reservation
Hard Stop
Safe Boundary
Uncertain Effect
```

### 20.8 Evaluation Gate

```text
Quality
Tool Accuracy
Structured Output
Latency
Cost
Safety
Regression
```

### 20.9 SDK Validation

```text
Build
Types
ESM
CJS for Headless
ESM-only for Lobe
Tree Shaking
SSR
React 18
React 19
Next.js
Vite
Tauri
CSS
Strict Mode
SSE Reconnect
Idempotency
```

### 20.10 Consumer Contract

必须建立：

```text
consumer-react18
consumer-react19
consumer-next
consumer-vite
consumer-tauri
consumer-headless
consumer-lobe
```

---

## 21. 当前验证状态矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| Model Role | 已有基础 | 六类 Role 已定义 |
| Invocation Policy | 已有基础 | Thinking、Reasoning、Tool Choice、Max Output |
| Context Window | 已有基础 | Hard Gate 与 Reserve 已有 |
| Token Usage | 已有基础 | Provider Usage 已解析 |
| Cost 字段 | 部分完成 | 可存储，缺 Pricing Calculator |
| DeepSeek Role Routing | 部分完成 | 静态代码 Profile |
| Per-Agent Model Policy | 契约引用已有 | 缺 Registry 与 Runtime 解析闭环 |
| Provider Connection Registry | 缺失 | 当前主要依赖环境变量 |
| Model Catalog Registry | 缺失 | 当前 Profile 硬编码 |
| Distributed Model Concurrency | 缺失 | 仅有 Orchestration Parallelism |
| RPM / TPM | 缺失 | 需独立策略与运行控制 |
| Pricing Version | 缺失 | 无定价版本事实源 |
| Cost Ledger | 缺失 | 无 append-only 成本账本 |
| Chargeback | 缺失 | 无内部计费模型 |
| Multi-Agent Token Budget | 已有基础 | Token、Tool、Runtime |
| Multi-Agent Money Budget | 缺失 | 需新增 Cost Reservation |
| Agent Team | 已有基础 | 最多四 Agent、深度一 |
| Memory | 已有较强基础 | 生命周期与治理模型已有 |
| Skill | 部分完成 | Catalog 与 Snapshot 需平台化 |
| MCP | 部分完成 | Gateway 与 Allowlist 已有 |
| Plugin | 已有领域基础 | 需 Cloud 安装与发布治理 |
| LobeHub UI | 已有试用 | Desktop 已接入 |
| Shared SDK | 缺失 | 需独立 TypeScript 包体系 |
| TSDX | 外部工具可用 | 需处理 Bun 与 pnpm 边界 |

---

## 22. 收口边界

### 22.1 V1 必须完成

```text
Project Context Registry
Prompt Registry
Knowledge Source Registry 基础
Memory Explorer 和 Policy
Skill Catalog 和 Snapshot
MCP Server Registry 和 Snapshot
Plugin Catalog 和 Enablement
Model Provider Registry
Model Connection Registry
Model Catalog
Invocation Profile
Fixed / Ordered Fallback Routing
Context Budget Policy
Distributed Concurrency Reservation
RPM / TPM 基础
Pricing Version
Usage Receipt
Provider Cost Ledger
Task / Agent / Project Cost Query
Single Agent Studio
Multi-Agent Studio 基础
Effective Runtime Snapshot
Headless SDK
React Hooks
Lobe UI Runtime Components
核心 Platform Widgets
Integration Doctor
Conformance
Trench Pilot
```

### 22.2 V1 锁定范围

```text
币种 USD
Team 最多四 Agent
Team 深度一
模型路由 fixed 和 ordered-fallback
React Web 优先
Lobe UI 包 ESM-only
Provider Cost 与内部 Chargeback 基础
Project、Agent、Task 和 Team 归因
```

### 22.3 V1 明确排除

```text
自动质量成本动态路由
Agent 自主修改 Production 配置
开放 Plugin Marketplace
任意远程 Plugin 执行
客户发票
税务
多币种
实时汇率
支付
跨 Tenant Memory
任意 DOM 和 JavaScript
运行中 Task 热切换模型
latest 和 current 移动引用
无限层级 Agent Team
移动端完整 SDK
自动购买 Provider Capacity
```

### 22.4 Definition of Done

V1 完成需要同时满足：

1. 每个 Task 可以反查完整 Effective Runtime Snapshot。
2. 每个 Model Call 可以归因到 Project、Agent Release、Role、Model、Connection 和 Pricing Version。
3. 每个 Token 和 Cost 都可以通过 Event 与 Ledger 对账。
4. 单 Agent 和 Multi-Agent 的预算都能在安全边界执行。
5. 两个 Scheduler 并发时不会突破模型并发上限。
6. Provider Profile 更新不会改变历史 Task。
7. Pricing 更新不会重算历史账单。
8. 新项目通过 SDK 和 Component Package 完成接入，无需复制 Zebra 内部 UI 代码。
9. React 18 Headless Consumer 与 React 19 Lobe Consumer 同时通过。
10. Trench 全链路完成 Model、Memory、Skill、MCP、Plugin、Frontend Hook 和 Cost 验收。
11. 新增 Jazz 时 Zebra Core 和 Worker 不增加业务名称分支。
12. Feature Flag 关闭后现有 Cloud Agent 运行链保持稳定。

---

## 23. 实施阶段

### Phase 0：架构与 Ontology

任务：

```text
PLATFORM-ONTOLOGY-ADR-01
MODEL-CONTROL-PLANE-ADR-01
USAGE-COST-ADR-01
SDK-ARCH-ADR-01
```

退出条件：

```text
概念边界冻结
配置继承规则冻结
事实源冻结
V1 排除项冻结
```

### Phase 1：Model Control Plane Core

任务：

```text
MODEL-PROVIDER-CON-01
MODEL-CONNECTION-CON-01
MODEL-CATALOG-CON-01
MODEL-INVOCATION-CON-01
MODEL-ROUTING-CON-01
MODEL-CONTEXT-CON-01
MODEL-CONCURRENCY-CON-01
MODEL-PRICING-CON-01
MODEL-BUDGET-CON-01
MODEL-EFFECTIVE-BINDING-CON-01
```

退出条件：

```text
所有模型配置可生成稳定 Digest
Secret 不进入模型
Limit 只能收窄
Role 与 Capability 校验通过
```

### Phase 2：PostgreSQL 与 Application Service

任务：

```text
MODEL-REGISTRY-PG-01
MODEL-CONNECTION-PG-01
MODEL-PRICING-PG-01
MODEL-USAGE-PG-01
MODEL-COST-LEDGER-PG-01
MODEL-CONCURRENCY-PG-01
MODEL-CONTROL-PLANE-COMP-01
```

退出条件：

```text
真实 PostgreSQL
版本不可变
CAS
Namespace Isolation
Backup Restore
```

### Phase 3：Runtime Cutover

任务：

```text
MODEL-GATEWAY-RESOLVER-01
MODEL-BINDING-ADMISSION-01
MODEL-CONTEXT-POLICY-01
MODEL-CONCURRENCY-RUNTIME-01
MODEL-USAGE-RECEIPT-01
MODEL-COST-RECONCILIATION-01
```

退出条件：

```text
Worker 不再依赖全局单一 Model Settings
Task 使用 Pinned Model Binding
Usage 和 Cost 闭环
```

### Phase 4：Single Agent Studio

任务：

```text
PLATFORM-MODEL-CENTER-UI-01
PLATFORM-AGENT-MODEL-MATRIX-01
PLATFORM-CONTEXT-EDITOR-01
PLATFORM-CONCURRENCY-EDITOR-01
PLATFORM-PRICING-EDITOR-01
PLATFORM-EFFECTIVE-CONFIG-01
```

退出条件：

```text
单 Agent 完成 Draft、Validate、Evaluate、Publish 和 Canary
```

### Phase 5：Multi-Agent Studio

任务：

```text
PLATFORM-TEAM-TEMPLATE-01
PLATFORM-TEAM-MATRIX-01
PLATFORM-DAG-DESIGNER-01
PLATFORM-TEAM-BUDGET-01
PLATFORM-TEAM-MODEL-BINDING-01
PLATFORM-COMPLETION-GATE-01
```

退出条件：

```text
四 Agent、深度一、预算、并发、模型和 Completion Gate 全闭环
```

### Phase 6：SDK 与组件

任务：

```text
SDK-TSDX-BOOTSTRAP-01
SDK-CONTRACTS-01
SDK-CLIENT-CORE-01
SDK-REACT-01
SDK-LOBE-UI-01
SDK-PLATFORM-WIDGETS-01
SDK-NEXT-01
SDK-DEVTOOLS-01
SDK-CREATE-ZEBRA-01
SDK-CONSUMER-MATRIX-01
```

退出条件：

```text
包发布
类型稳定
Consumer Matrix 通过
Desktop 改为 SDK Consumer
```

### Phase 7：Pilot 与 Production Gate

任务：

```text
MODEL-PROVIDER-CONFORMANCE-01
MODEL-CONTEXT-CONFORMANCE-01
MODEL-COST-CONFORMANCE-01
MODEL-CONCURRENCY-CHAOS-01
SDK-INTEGRATION-DOCTOR-01
TRENCH-PLATFORM-PILOT-01
JAZZ-ZERO-BRANCH-01
PRODUCTION-GATE-01
```

退出条件：

```text
Trench 生产试点
Jazz 零核心分支接入
安全、恢复、成本和回滚证据齐全
```

---

## 24. 推荐实施优先级

第一批：

```text
PLATFORM-ONTOLOGY-ADR-01
MODEL-CONTROL-PLANE-ADR-01
USAGE-COST-ADR-01
SDK-ARCH-ADR-01
```

第二批：

```text
MODEL-PROVIDER-CON-01
MODEL-CONNECTION-CON-01
MODEL-CATALOG-CON-01
MODEL-INVOCATION-CON-01
MODEL-CONTEXT-CON-01
MODEL-PRICING-CON-01
MODEL-CONCURRENCY-CON-01
```

第三批：

```text
MODEL-REGISTRY-PG-01
MODEL-USAGE-PG-01
MODEL-COST-LEDGER-PG-01
MODEL-CONCURRENCY-PG-01
```

在 Model Runtime Cutover 之前，可以并行启动：

```text
SDK-TSDX-BOOTSTRAP-01
SDK-CONTRACTS-01
SDK-CLIENT-CORE-01
```

Lobe UI 包应在 Headless Contract 稳定后开始。

---

## 25. 最终产品判断

完成本次扩展后，Zebra 中台将形成以下完整闭环：

```text
项目建模
→ Agent 配置
→ Prompt 与上下文
→ Knowledge 与 Memory
→ Skill、MCP、Plugin 装配
→ Model Role Routing
→ Context Budget
→ Concurrency
→ Token 与 Cost Budget
→ Single Agent Release
→ Multi-Agent Team Release
→ SDK 与组件接入
→ Task 执行
→ Usage 和 Cost 对账
→ Evaluation
→ Canary
→ Rollback
```

最终用户应当能够在一个页面上看到：

```text
这个 Agent 在当前项目中使用哪个模型
每个角色使用哪个模型
上下文如何分配
并发上限是多少
Token 与 Cost 上限是多少
使用哪些 Memory、Skill、MCP 和 Plugin
能访问哪些 Host 和 Frontend 能力
实际运行消耗了多少
为什么选择了这个模型
配置来自哪一层
发生变更会影响哪些新 Task
```

这将使 Zebra 从 Cloud Agent Runtime 进一步演进为具备开发、装配、发布、治理、观测和成本运营能力的完整 Agent Platform。
