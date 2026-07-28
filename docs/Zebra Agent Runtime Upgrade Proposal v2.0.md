# Zebra Agent Runtime 升级提案 v2.0

状态：`Direction accepted / ADR pending / Non-executable`

规划记录：`ARCH-RUNTIME-V2-PLAN-01`（仅核对文档，不是 Agent Definition 实现任务）

核对基线：`origin/main@a6b47c3f`；当前主线事实仍以 `PROGRESS.md` 为准。

本文不是新的架构权威，也不直接激活实现。若与仓库文件冲突，优先级为：

1. 当前用户要求；
2. `docs/Codex-like工程Agent平台最终架构设计_v1.0.md`；
3. 已批准 ADR；
4. `docs/AGENT_TASKS.md` 中已激活任务；
5. 本提案。

标题中的 Runtime Upgrade 指在现有 Runtime 上增加控制面，不是重写 Runtime。

## 1. 结论

Zebra 已经是一个具备稳定 Task、可恢复 Session/Segment、Tool Gateway、Policy、
Sandbox、Artifact、Event Store、Memory governance、Skill、Trust metadata、Trace 和 Eval
能力的 Agent Runtime。v2 不应以“这些能力都缺失”为前提重建一次。

真正尚未闭合的产品级抽象是：

- 可复用、可版本化、可发布的 `AgentDefinition`；
- `AgentDefinitionVersion` 与 Task 执行快照之间的稳定绑定；
- 面向 Agent 版本的长期评估与发布门禁；
- 跨现有 Skill、Memory、Security、Model 和 Eval 合同的一致配置面；
- 私有云下 Registry authority、namespace、数据库权限与恢复合同。

因此 v2 的准确目标是：

> 在不破坏现有执行事实源和包边界的前提下，为 Zebra 增加可版本化 Agent Definition
> 控制面，并复用已经存在的 Runtime、Skill、Memory、Trust 和 Eval 能力。

## 2. 当前事实与真实增量

下表的“现有基线”是本次基于 `origin/main@a6b47c3f` 的仓库核对结果；具体的
implemented/tested/merged/deployed 状态继续以 `PROGRESS.md` 和对应任务验收证据为准。

| 领域 | 现有基线 | v2 真实缺口 |
| --- | --- | --- |
| 执行身份 | 稳定 `AgentTask`、内部 `ExecutionSegment`、Session Event Store | 可复用 Agent Definition 及其版本绑定 |
| Runtime | Harness、Worker、恢复、Tool Gateway、Sandbox、Artifact、Streaming | Agent 版本到 Runtime profile 的确定性解析 |
| Skill | Catalog、scope、digest、Task snapshot、enable/disable、provenance、Eval | Agent Definition 对 immutable Skill snapshot 的发布绑定 |
| Memory | Event 事实源、Context Capsule、governed `MemoryStorePort`、生命周期与来源 | Agent-scoped policy、provider mapping、版本兼容和删除传播 |
| Trust/Security | typed trust level、provenance、untrusted output、Policy、Approval、Credential/Egress 边界 | Agent publish/grant authority 与所有 ingress 的统一 trust evidence |
| Eval | Trace、local Eval runner、release gate、replay cases | 按 Agent version 聚合的质量基线、回归门禁和发布证据 |
| Registry | Task/Skill/Extension 状态均有各自 Store | Agent Definition/Version/Release 的权威 Store 尚不存在 |

### 2.1 名称边界

现有 `AgentTask` 是用户可感知的耐久执行身份，不等于“一个可复用 Agent 产品定义”。
v2 使用以下名称，避免引入第二个含糊的 `Agent` 实体：

- `AgentDefinition`：逻辑 Agent 定义；
- `AgentDefinitionVersion`：不可变发布候选；
- `AgentRelease`：一次发布、撤销或弃用记录；
- `AgentTask`：执行身份，继续沿用现有合同；
- `ExecutionSegment`：Task 内部执行分段，继续对普通用户隐藏。

### 2.2 术语

- `authority`：某类数据或决策的唯一权威来源；不等于内容可信度；
- `publisher grant`：外部 authority 在一次发布操作中授予发布者的能力上限，Definition
  只能收窄它；
- `ingress`：外部定义、Skill、Memory、知识或 Eval 数据进入 Zebra 的入口；
- `namespace`：由 `(authority_issuer, namespace_id)` 标识的不透明隔离边界，不表示
  Zebra 拥有 Tenant、Organization 或成员关系；
- `AgentDefinitionSnapshot`：Task 创建时冻结的 Definition 版本和解析配置；
- `ExecutionAuthoritySnapshot`：每个 Attempt 重新验证的外部 authority、limits 与
  Zebra 收紧后的执行权限；
- `release gate`：现有 Run/Eval case gate；v2 候选新增门禁统一称为
  `AgentVersionPublicationGate`。

## 3. 权威边界

### 3.1 定义事实与执行事实分离

未来 Registry 是 Agent Definition 元数据的事实源。Session Event Store 仍是执行事实源。

```text
Agent Registry
  AgentDefinition
  AgentDefinitionVersion
  AgentRelease
          |
          | immutable version reference + digest
          v
AgentTask / ExecutionSegment
          |
          v
Session Event Store
```

规则：

- Event Store 不复制整份 Agent Definition；
- Task 创建时记录不可变 version reference、digest 和解析后的
  `AgentDefinitionSnapshot`；
- 当前 Attempt 单独记录 `ExecutionAuthoritySnapshot`；同一 Attempt 的 resume/failover
  必须重新验证有效性且不得超过已持久化快照；真正创建的新 Attempt 使用重新验证后的
  当前 authority，可与旧 Attempt 不同，但仍受 Definition capability、Zebra Policy、
  Approval 和 Sandbox 收紧；retry 按其是否创建新 Attempt 适用对应规则；
- 运行中的 Task 不因 Registry 中的 mutable draft 变化而漂移；
- 已发布版本不可原地修改，只能发布新版本；
- Registry 不保存 Session checkpoint、Tool result 或恢复状态；
- Registry 和 Event Store 的跨库 dual-write 不在 v2 初始切片中。

`AgentDefinitionSnapshot` 的最小语义包括：Definition version/digest、
`(authority_issuer, namespace_id)`、解析后的 versioned references/digests、Definition
policy versions、degradation policy 和创建时间。`ExecutionAuthoritySnapshot` 继续遵守
ADR-012，包含外部 authority/limits 的 issuer、subject、expiry 与 Zebra 收紧结果。
两者的生成者、摘要范围与恢复校验算法必须在 Gate A ADR 中分别冻结，不能由 Adapter
各自定义或合并成一个长期权限快照。

### 3.2 运行时解析

`AgentDefinitionVersion` 只引用已经存在的稳定合同：

```text
AgentDefinitionVersion
  model_policy_ref
  tool_profile_ref
  skill_snapshot_digest
  memory_policy_ref
  security_policy_ref
  evaluation_profile_ref
  runtime_profile_ref
```

它不得内联：

- API key、OAuth token 或数据库凭据；
- 任意可执行 Python；
- 未经 Tool Gateway 注册的工具；
- 能绕过 Policy/Approval 的提示词；
- 未固定 digest 的 Skill 或 Runtime image。

解析失败、引用不存在、digest 漂移或 authority 不兼容时必须 fail closed。

## 4. Agent Definition 合同

### 4.1 最小模型

示意模型如下，最终字段必须由独立 ADR 和 Core contract task 冻结：

```json
{
  "definition_id": "agentdef_xxx",
  "name": "research-agent",
  "description": "Bounded research and evidence synthesis",
  "authority_issuer": "https://business.example.com",
  "namespace_id": "opaque-business-scope",
  "status": "active",
  "current_published_version": 3
}
```

```json
{
  "definition_id": "agentdef_xxx",
  "version": 3,
  "schema_version": "agent-definition/1",
  "skill_snapshot_digest": "sha256:...",
  "model_policy_ref": "model-policy/research-default@2",
  "tool_profile_ref": "tool-profile/research-readonly@4",
  "memory_policy_ref": "memory-policy/research@1",
  "security_policy_ref": "security-policy/external-research@3",
  "evaluation_profile_ref": "eval-profile/research@2",
  "runtime_profile_ref": "runtime-profile/gvisor@1",
  "definition_digest": "sha256:..."
}
```

### 4.2 生命周期

三类对象职责必须分开：

- Definition 是逻辑容器，可处于 `Active` 或 `Archived`；
- mutable draft 只是 Definition 下尚未生成 Version 的可变编辑载荷，不是独立事实源或
  生命周期实体；从未发布时，`current_published_version` 为 `null`；
- Version 创建即不可变；任何内容修改都产生新 version，可处于
  `Validated` 或 `Rejected`；
- Release 是某 `(authority_issuer, namespace_id)`/environment 对某个 Version 的生效
  记录，可处于 `Published`、`Deprecated` 或 `Revoked`。

发布生命周期为：

```text
mutable draft -> immutable Version: Validated | Rejected
Validated Version -> Release: Published -> Deprecated | Revoked
```

`Running` 属于 Task/Session；`Learning` 属于 Memory/Eval workflow。它们不能混进
Definition、Version 或 Release 生命周期，否则 Registry 会与 Runtime 状态机形成双事实源。

### 4.3 发布门禁

发布至少需要：

- schema 和引用完整性通过；
- Skill、Runtime image 和 policy reference 均固定版本/digest；
- capability 不超过 publisher grant；
- Memory scope 和删除策略明确；
- required Eval cases 通过；
- secrets 只以 broker reference 表示；
- `authority_issuer`、`namespace_id`、外部主体引用、审计 actor 和幂等键完整；
- 撤销后新 Task 不得继续使用该版本。

## 5. Skill：复用，不重建

Zebra 已经具备 Skill metadata、scope、digest、Task snapshot、管理状态、`skills.read`
provenance 和 release-eval。v2 不创建平行的 `skill-runtime` 或第二套 Skill Store。

Agent Definition 只新增：

- 发布时解析一个 immutable Skill component snapshot；
- 校验版本、scope、namespace、digest 和 enable/grant 状态；
- 把 snapshot digest 写入 Task 的 `AgentDefinitionSnapshot`；
- Skill 后续禁用或撤销时，对新 Task fail closed；
- 运行中 Task 的处置由 Gate A 在继续、暂停待批、下个 Segment 停止或立即终止中明确
  选择，不能静默热更新。

这里的处置选项只适用于 Definition Release 或 Skill 内容撤销。外部身份、执行 authority、
Credential 或强制安全 Policy 的撤销继续遵守 ADR-012 和现有 Security 合同，新 Attempt
必须重新验证并 fail closed，不能选择“继续”来绕过。

Plugin、Hook 和 Marketplace 继续遵守 ADR-014 的五层状态机，不由 Agent Registry 绕过。

## 6. Memory：事实、上下文、知识分层

原提案的 Runtime/Task/Agent/Knowledge 四层可以保留为产品视角，但不能各自变成新的
数据库事实源。实现边界应为：

### 6.1 Execution facts

Session Event Store 保存 Task/Segment 状态、Tool execution、审批、失败和恢复事实。
这是唯一耐久执行事实源，不称为可检索的“Agent Memory”。

### 6.2 Active context

Conversation projection、Context Capsule、compaction 和 provider continuation 是可重建的
执行上下文。它们同时受 token budget、provenance、Task 级
`AgentDefinitionSnapshot` 和当前 Attempt 的 `ExecutionAuthoritySnapshot` 约束。

### 6.3 Governed durable memory

`MemoryStorePort` 保存由执行事实派生的 candidate/confirmed/superseded/expired/deleted
知识，包含 scope、source event range、confidence、review 和 retention。

Task memory 与 Agent memory 应优先表现为：

- scope 和 namespace；
- write/review/retention policy；
- source provenance；
- Definition version compatibility；
- 删除、失效和 supersede 传播。

它们不是绕开 Event Store 的隐藏执行状态。

### 6.4 External knowledge and semantic providers

文档库、数据库、搜索索引、向量服务和第三方 memory provider 都是可替换 Adapter：

- provider 不成为 Task/Event 事实源；
- provider ID 通过 Zebra mapping 与内部 Memory ID 隔离；
- namespace 由 Zebra 强制，不能信任 provider 自带过滤；
- provider 降级不得令 Run 失败；
- write-after-timeout、重复发布和删除传播必须有幂等/对账合同；
- 原始外部知识始终以 untrusted evidence 进入 Context Compiler。

发布和 Task binding 阶段的必需引用失败必须 fail closed。运行期间的可选知识/语义
provider 不可用时，只能按 `AgentDefinitionSnapshot` 中已冻结的 degradation policy
降级；被声明为必需的 Memory capability 不可用时仍然失败。

## 7. Trust 与 Security：证据，不是分数授权

禁止用固定 `trust_score = 0.8` 之类的标量直接决定权限。来源可信度、内容风险和执行
authority 是三个不同概念。

最小 trust evidence：

```text
source_kind
source_identity
content_digest
trust_level
risk_markers
retrieved_at
policy_version
```

原则：

- 内容不能通过自称 system/admin 获得权限；
- suspicious marker 是风险信号，不是唯一安全判断；
- untrusted 内容可以被读取和总结，但不能授予工具、网络、文件或 memory write 权限；
- Agent Definition 只能收窄发布操作的 publisher grant，不能扩大；运行时仍以当前
  Attempt 的 `ExecutionAuthoritySnapshot` 为权限上界；
- Tool Gateway、Policy、Approval、Credential Broker、Egress 和 Runtime isolation 继续独立；
- trust evidence 必须进入 trace/audit，但敏感原文和 secrets 不进入控制元数据。

v2 的增量是补齐所有 Agent Definition ingress、Registry publish、Memory provider 和
evaluation dataset 的一致 provenance，不是替换现有 Security package。

## 8. Evaluation：从 Run gate 到 Agent version gate

Zebra 已有 deterministic tests、Trace、Eval cases、replay、LocalEvalRunner 和 Run/Eval
case gate。v2 候选新增的是按 Definition version 聚合的
`AgentVersionPublicationGate`：

- required Eval suite reference；
- correctness/safety/reliability/efficiency 分项结果；
- fixture、dataset 和 evaluator version；
- score 之外的通过条件和失败原因；
- 与前一发布版本的回归比较；
- cost、latency、recovery 和 policy violation evidence；
- release decision 与审计 actor。

LLM-as-judge 只能是附加证据，不能替代 deterministic contract、Policy 和安全测试。
线上经验不得自动修改已发布 Definition；改进必须形成新 draft、新 Eval 和新发布。

## 9. 包与依赖策略

不执行原提案中的全量包重命名。当前规则继续成立：

- `agent-core` 只放 domain、use case 和 Port，不依赖其他 `agent-*` 包；
- `apps/*` 只做 composition；
- Skill 继续在 `agent-tools`/`agent-storage` 现有边界演进；
- Memory 继续由 Core Port、governed Store 和可替换 integration Adapter 组成；
- Trust/Policy 继续在 `agent-context` 与 `agent-security` 的明确责任内；
- Eval 继续在 `agent-observability`。

只有当第一个 Agent Definition contract 获批并证明现有包无法清晰承载时，才考虑新增：

```text
packages/agent-registry
```

即使新增，`agent-registry` 也必须实现 `agent-core` Port，不能让 Core 反向依赖它。
`agent-sdk`、`memory-core`、`context-security` 等包当前均属 YAGNI。

## 10. 候选决策顺序（非执行 Phase）

架构方向已经接受，但只有 Gate A 在 `docs/AGENT_TASKS.md` 中进入 `Ready`；Gate B-G
保持 `Locked`。每项开始前仍必须获得 owner、branch 和 Owned paths。

### Gate A：决策冻结（`AGENT-DEF-ADR-01`）

- 编写 Agent Definition/Version/Release ADR；
- 冻结 Registry authority、不透明 namespace、发布/撤销和 Task binding；
- 冻结 Task 级 `AgentDefinitionSnapshot` 与 Attempt 级
  `ExecutionAuthoritySnapshot` 的生成、摘要、恢复和重新验证边界；
- 冻结 Definition schema evolution 和 immutable digest；
- 明确本地 SQLite 与云 PostgreSQL 的权威选择，不 dual-write。

每个部署环境只能有一个 Registry authority：本地阶段为 SQLite，私有云阶段为
PostgreSQL；迁移采用离线导入、校验和切换，不并行 dual-write。

### Gate B：Core contract（`AGENT-DEF-CON-01`）

- `AgentDefinition`、`AgentDefinitionVersion`、`AgentRelease` domain model；
- narrow Registry Port；
- schema validation、digest 和 state transition tests；
- 不实现 UI、云 Store 或自动学习。

### Gate C：Registry Adapter（`AGENT-DEF-STO-01` / `AGENT-DEF-PG-01`）

- local-first SQLite Adapter；
- version/publish/revoke CAS；
- namespace、idempotency、audit 和 migration tests；
- 云 PostgreSQL Adapter 已登记为 `AGENT-DEF-PG-01` 并保持 `Locked`，待本地 Store
  合同合并后再认领；其 Compose 仅管理数据库依赖，不混入 Zebra 主应用容器。

### Gate D：发布与 Task binding（`AGENT-DEF-PUB-01` / `AGENT-DEF-BIND-01`）

- Task 创建时解析 published version；
- 写入 immutable `AgentDefinitionSnapshot`，并复用现有 Attempt 级
  `ExecutionAuthoritySnapshot`；
- recovery/replay 验证 digest 和 policy reference；
- Definition drift/revocation fail closed。

### Gate E：Memory policy binding（`AGENT-DEF-MEM-01`）

- 复用 governed Memory contract；
- 增加 Definition scope/policy/version compatibility；
- 外部 provider mapping、降级、幂等和 deletion propagation；
- 不把 provider 变成执行事实源。

### Gate F：Trust coverage（`AGENT-DEF-TRUST-01`）

- Registry ingress、Skill snapshot、Memory provider、knowledge retrieval 和 Eval dataset
  使用一致 provenance/risk evidence；
- publisher grant、Definition snapshot、Attempt execution authority 和 content trust
  分离；
- threat model 和 negative tests 通过。

### Gate G：Agent version evaluation（`AGENT-DEF-EVAL-01`）

- Definition version 到 Eval suite 的稳定映射；
- regression、cost、latency、recovery 和 safety gate；
- 发布证据、撤销和回滚 runbook。

## 11. 非目标

v2 初始阶段不包含：

- 自动修改已发布 Agent；
- autonomous self-improvement 或无人工发布；
- 第二套 Task、Session、Event 或 Skill runtime；
- public marketplace；
- 任意代码型 Agent Definition；
- secrets 存入 Registry；
- 跨 Store dual-write；
- 因新增 Agent Registry 而削弱 Policy、Approval、Gateway 或 Sandbox；
- React SDK、CopilotKit 或具体业务 UI；
- SaaS 用户、计费、商业化或行业业务逻辑。

## 12. 完成定义

只有同时满足以下条件，Zebra 才能宣称完成本提案中的 Agent Definition v2：

1. focused ADR 获批，最终架构记录并引用其稳定结论，Gate B 任务随后被显式激活；
2. Definition/Version/Release 有唯一事实源和迁移/恢复合同；
3. Task 绑定不可变 Definition version/digest，恢复不会读取 mutable draft；同一
   Attempt 的恢复不得扩权，新 Attempt 则重新验证当前 execution authority；
4. Skill、Memory、Security、Model、Runtime 和 Eval reference 均可验证且 fail closed；
5. namespace、publisher grant、revocation 和 audit negative tests 通过；
6. deterministic tests、Eval、threat model、rollback 和 operator runbook 完整；
7. 本地、云端、merged、deployed 状态分别记录，不用文档计划替代实现证据。

## 13. 相关权威文档

- [最终架构设计](./Codex-like工程Agent平台最终架构设计_v1.0.md)
- [任务注册表](./AGENT_TASKS.md)
- [ADR-012：Runtime 与外部业务边界](./ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md)
- [ADR-013：稳定 Task 与内部 Segment](./ADR-013_用户任务连续性与内部执行分段.md)
- [ADR-014：扩展体系架构](./ADR-014_扩展体系架构.md)
- [扩展体系状态机与契约](./扩展体系状态机与契约_v1.0.md)
- [生产级 Runtime 实施方案](./生产级Runtime实施方案_v1.0.md)
- [上下文生命周期与混合压缩](./上下文生命周期与混合压缩架构方案_v1.0.md)

架构方向已经接受。第一项产物是 Gate A 的 focused ADR，而不是代码；只有该 ADR
获批并把稳定结论写回最终架构后，Gate B 才能从 `Locked` 转为 `Ready`。
