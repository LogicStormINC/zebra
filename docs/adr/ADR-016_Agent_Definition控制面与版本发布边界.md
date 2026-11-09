# ADR-016：Agent Definition 控制面与版本发布边界

- 状态：Accepted
- 日期：2026-07-28
- 决策者：Maintainer
- 任务：`AGENT-DEF-ADR-01`
- 方向来源：`Zebra Agent Runtime Upgrade Proposal v2.0.md`
- 扩展：ADR-001、ADR-009、ADR-010、ADR-011、ADR-012、ADR-013、ADR-014

实现状态：本 ADR 只冻结架构合同。它不实现 Python、SQL、API、CLI、Docker 或 UI；
`AGENT-DEF-CON-01` 及后续实现任务在本 ADR 合并到 `main` 前保持 `Locked`。

## 1. 背景

Zebra 已有稳定 `AgentTask`、内部 `ExecutionSegment`、Session Event Store、Harness、
Tool Gateway、Policy/Approval、Runtime、Skill 选择、governed Memory、Trace 和 Eval。
这些能力可以完成一次 Agent 执行，但缺少一个可复用、可版本化、可发布、可撤销的
Agent 配置身份。

本决策增加 Agent Definition 控制面，不创建第二个 Runtime，也不把 Agent Definition
变成用户、服务账号、多 Agent 角色或自治执行实体。

当前代码基线还有两个必须如实记录的缺口：

- `TASK_PREPARED.skill_components` 只冻结规范化 Skill 名称选择器，尚未冻结
  scope/version/digest 或内容；
- 当前 Harness Attempt 只持久化 attempt number，尚无 ADR-012 所要求的外部
  `ExecutionAuthoritySnapshot`。

因此后续任务必须实现这些合同，不能声称直接复用已经完成的能力。

## 2. 决策摘要

| 关注点 | 决策 |
| --- | --- |
| 执行身份 | `AgentTask` 继续是用户可感知的稳定执行身份 |
| 可复用配置 | `AgentDefinition` 是配置身份，不是运行实体或权限主体 |
| 配置版本 | `AgentDefinitionVersion` 创建即不可变，内容变化产生新版本 |
| 发布 | `AgentRelease` 记录 scoped environment 中版本的发布、弃用和撤销 |
| 定义权威 | Agent Registry 是 Definition/Version/Release 元数据唯一 authority |
| 执行权威 | Session Event Store 是 Task/Segment/Attempt 唯一耐久执行事实源 |
| 外部权限 | 外部 authority 每个 Attempt 验证，Zebra 只能保持或收窄 |
| 隔离 | durable key 为 `(authority_issuer, namespace_id)`，不创建 Tenant Domain |
| 本地存储 | SQLite Registry Adapter |
| 私有云存储 | PostgreSQL Registry Adapter；每个环境只能选择一个 authority |
| 执行绑定 | Task 保存不可变 Definition snapshot；Attempt 保存独立 authority snapshot |
| 扩展授权 | Definition 固定声明和 digest；Task binding 才计算 Granted |
| 发布门禁 | 在现有 Eval gate 上增加按 Definition version 聚合的发布门禁 |

## 3. 与既有 ADR 的关系

本 ADR 只扩展，不取代以下不变量：

- ADR-001：Event Store 仍是唯一耐久**执行**事实源；Memory 不是状态源；
- ADR-009：单主 Agent 默认，多 Agent 只复用通用委派原语；
- ADR-010：deterministic tests、Replay 和安全检查仍是发布硬门；
- ADR-011：Registry、Memory、OPA、Temporal 等均通过 Core Port 和 Adapter 接入；
- ADR-012：身份、业务授权和租户业务外置；namespace 是不透明隔离键；
- ADR-013：Task 稳定，Segment 内部隐藏，自动 rollover 不扩权；
- ADR-014：Available、Installed、Enabled、Granted、Approved 五层不能互相推导。

“Event Store 是平台唯一事实源”的旧表述在本 ADR 中收窄为“唯一执行事实源”。
Registry 可以成为 Definition 元数据 authority，但不得保存或推导执行恢复状态。

## 4. 领域身份与生命周期

### 4.1 AgentDefinition

Definition 是 `(authority_issuer, namespace_id, definition_id)` 下的逻辑配置容器，只
保存稳定身份和描述性元数据。它不表示运行状态、用户身份或发布状态。

Definition 下可以有一个带 revision 的 mutable draft。Draft 是编辑载荷：

- 不可被 Task 引用；
- 不可授予任何权限；
- 不参与恢复；
- 使用 optimistic concurrency/CAS 防止覆盖；
- 校验失败只产生 validation result，不产生不可变 Version。

### 4.2 AgentDefinitionVersion

Draft 通过 schema、引用和 publisher authority 上界等静态校验后，物化为
不可变 Version。Version 级 Eval 以该不可变 identity/digest 为输入，是
Release 的必需门禁，不是 Version 物化的前置条件。
Version identity 至少由 `(authority_issuer, namespace_id, definition_id, version_id,
definition_digest)` 确定。

本 ADR 不冻结 version ID 是整数、语义版本还是其他格式；Core contract 必须给出
确定性排序、唯一性和测试向量。Version 内容创建后不可原地修改，也不使用
`Validated/Rejected` mutable status 暗示内容可变。验证证据作为独立 append-only
记录或 Artifact reference 保存。

### 4.3 AgentRelease

Release 是 `(authority_issuer, namespace_id, definition_id, environment)` 范围内，将
一个 immutable Version 置为可用的 append-only 状态转换和审计记录：

```text
Published -> Deprecated
Published -> Revoked
Deprecated -> Revoked
```

同一 scope/environment 的 publish/deprecate/revoke 使用 revision CAS、idempotency key
和审计 actor。`current_published_version` 只能是从 Release history 重建的 projection/
cache，不是第二事实源。

每个完整 `(authority_issuer, namespace_id, definition_id, environment)` scope 最多一个
effective `Published` Release。发布新 Version 必须在同一 Registry transaction/CAS 中
把旧 current 追加为 `Deprecated(reason=superseded)`，再追加新 `Published`。没有 current
返回 not found；检测到多个 effective Published 属于数据损坏，`resolve_published`
必须 fail closed，不能按 version 字符串或时间猜测。

被 Task/Event 引用的 Version 和 Release history 不物理删除；archive/tombstone 不能
破坏 replay、审计或 digest 验证。

## 5. 三类 authority 必须分离

| Authority | 权威来源 | 生命周期 | 禁止内容 |
| --- | --- | --- | --- |
| Definition metadata | Agent Registry | Definition/Version/Release | Task checkpoint、Tool result、Credential |
| Execution facts | Session Event Store | Task/Segment/Attempt/Event | mutable draft、整份 Registry 状态 |
| External execution grant | 外部签名 authority，经 Zebra 验证后写 Event | 每个 Attempt | token、密码、业务用户对象 |

Registry、Event Store 和外部 authority 不互相替代，也不使用跨库事务或运行时
dual-write 构造伪原子性。

## 6. Task Definition Snapshot

Task 创建时，Registry resolver 在线性化读取点解析当前有效 Release，并产生
`AgentDefinitionSnapshot`。它作为 `TASK_PREPARED` 的可选、schema-validated 嵌套
字段写入 Event Store；`WorkspaceProjection` 只做可重建镜像，`agent_tasks` 表不另存
一份权威快照。

最小语义包括：

```text
snapshot_schema_version
definition_id / version_id / definition_digest
authority_issuer / namespace_id
binding_purpose: production | eval
release_id / release_revision / release_status (required for production; absent for eval)
resolved component references and digests
resolved Definition policy/degradation references and digests
resolved_at / snapshot_digest
```

其中 component 至少覆盖 model、tool、Skill、Memory、Security、Eval 和 Runtime。
未实现 resolver 的引用类型不能发布为 required component。

Snapshot 不得包含 publisher grant、subject permission、Credential、token、expiry 或
其他当前执行权限。它跨 Task 的内部 Segment 保持不变，普通恢复只依赖 Event replay，
不得回读 mutable draft、`latest` pointer 或当前 Registry 内容。

发布前 Eval 是唯一例外：具有当前 evaluator authority 的调用者可在隔离的
non-production environment 中按完整 Version identity/digest 精确绑定 candidate。
该路径必须将 `binding_purpose=eval` 写入 snapshot/Event，不创建 Release，
不可成为生产默认，也不降低 Tool、Policy、Approval 或 Sandbox 限制。这条
受限路径用于打破“先发布才能 Eval、先 Eval 才能发布”的依赖环，不是
隐式 publication。

Version digest 使用 SHA-256，覆盖 schema version 和不可变 payload，排除 digest 字段
自身、Draft revision、展示缓存和 Release 状态。Core contract 必须提供唯一 canonical
UTF-8 serialization 和固定测试向量；不得由 SQLite、PostgreSQL 或 API Adapter 各自
计算。

## 7. Attempt Execution Authority Snapshot

`ExecutionAuthoritySnapshot` 是 ADR-012 的后续实现合同，当前代码尚未完成。应使用
独立 schema-validated durable event（建议 `EXECUTION_AUTHORITY_RESOLVED`），在
`HARNESS_ATTEMPT_STARTED` 和任何模型/工具动作之前持久化。

最小语义包括：

```text
snapshot_schema_version / attempt_number
identity_issuer / authority_issuer / subject_ref_or_hash
audience / namespace_id
canonical granted authorities
external limits / effective limits
issued_at / expires_at / validated_at
source authority digest
Zebra policy reference/version/effective digest
AgentDefinitionSnapshot digest (optional for legacy Tasks)
snapshot_digest
```

不得持久化原始 token、Credential 或可重放秘密。

同一 Attempt 的 resume/failover 不能覆盖原 snapshot；重新验证结果必须追加
`EXECUTION_AUTHORITY_REVALIDATED`（或同义 typed event），至少引用原 snapshot digest、
当前 source authority digest、effective narrowed digest、decision、validated_at 和
expires_at。拒绝/收窄也是执行事实，必须先写 Event 再继续，Projection 只缓存最新结果。

同一 Attempt 的 resume/failover 必须重新验证有效期和撤销状态，且 effective authority
不得超过已持久化快照。真正创建的新 Attempt 使用新的、重新验证的 snapshot；它可以
与旧 Attempt 不同，但仍取以下交集：

```text
effective capability = external authority
                     ∩ Definition capability ceiling
                     ∩ current Zebra Policy/Security floor
                     ∩ enabled/grantable components
                     ∩ Runtime/Sandbox hard limits
```

Approval 仍对每个有副作用动作独立生效，不因 Definition 或 Attempt snapshot 自动通过。
retry 按现有生命周期是否创建新 Attempt，适用对应规则。

Release/Skill revocation 在 Task binding、新 Attempt/Segment 和每个有副作用 Tool 的
Policy/Gateway 边界查询 Registry/Catalog revocation state；无法确认时 effectful action
fail closed。Runtime 观察到后发撤销时追加 typed revocation-observed/Policy decision
event，再阻断或 suspend。Credential 继续由 Broker 在每次使用时检查，强制 Security
floor 继续由 PEP 实时执行；这些在线检查不改变 Event Store 的执行事实权威。

## 8. 发布、绑定与扩展授权

Definition 发布阶段只校验：

- component identity、scope、version、digest 和 schema compatibility；
- 引用存在且 publisher authority 允许发布该声明上界；
- secrets、任意代码、未固定引用和 Policy bypass 不存在；
- required Eval evidence 满足 `AgentVersionPublicationGate`。

发布不产生 Task grant。Task binding 时才根据当前 external authority、当前 Enabled 状态、
Definition ceiling 和 Zebra Policy 计算精确 Granted 集合，并把 resolved identity/digest
写入 `TASK_PREPARED`。

现有 `skill_components: list[str]` 是名称选择快照，不是 immutable content snapshot。
实现必须升级为固定 `(identity, scope, namespace, version, digest)` 的 resolved entries，
同时保持旧 Task/event 可读取。

### 8.1 Registry 与 Event Store 的线性化边界

Task binding 使用以下顺序：

1. scoped `resolve_published` 读取 Release revision、Version 和 digest；
2. 校验 external publisher/task authority、Enabled 状态和 Policy；
3. 在同一 Registry revision 上 recheck/CAS 一个有界 binding fence；
4. 只向 Event Store 幂等追加 `TASK_PREPARED` snapshot；
5. Event append 成功后，Task 才成为执行事实。

Binding fence 只包含 scoped release revision、snapshot digest、idempotency key 和短期
valid-until，不包含 Task lifecycle/checkpoint；Event Store 保存它作为 observed revision
证据，恢复绝不回读 fence。它解决 bind 与 revoke 的排序，不是第二份 Task 状态。

不使用跨 Registry/Event Store transaction。Event append 失败可以按 idempotency key
重试；没有 Event 的 fence/resolver receipt 不是 Task 执行事实。

## 9. 撤销与紧急收紧

| 变化 | 新 Task | 新 Attempt/Segment | 当前 Attempt |
| --- | --- | --- | --- |
| Release Deprecated | 不再默认选择；显式 pin 由 Policy 决定 | 已绑定 snapshot 可继续 | 继续 |
| Release Revoked | deny | fail closed | 下一个安全边界 suspend |
| Release/Skill 安全撤销 | deny | fail closed | 下一次 Tool/Policy 边界立即阻断或 suspend |
| Skill Disabled | deny 新绑定 | 不重新解析或授予 | 不静默热更新 |
| 外部 authority 过期/撤销 | deny | fail closed | continuation/resume 重新验证并拒绝 |
| Credential 撤销 | deny 相关能力 | fail closed | Broker 下一次使用立即拒绝 |
| 强制 Security Policy | 只收紧 | 只收紧 | PEP 立即执行 |

Definition 固定的 Policy reference 不能阻止紧急 Security floor 收紧。Definition Release
的继续策略也不能绕过 external authority、Credential、Approval 或 Security 撤销。

Release/revocation record 必须包含 typed `reason_class`、`enforcement_mode` 和
`effective_at`。普通 actor 只能选择 safe-boundary enforcement；只有当前外部 authority
和 Zebra Security Policy 都认可的 security-revocation actor 才能选择 immediate
enforcement。Adapter 不得从自由文本 reason 猜测执行模式。

## 10. Registry Store 与迁移

- local-first 使用 SQLite Adapter；私有云使用 PostgreSQL Adapter；
- composition root 每个部署环境只注入一个 Registry Port；
- backend 不可用时 publish/bind fail closed，不回退读取旧 authority；
- Registry mutation 使用事务、CAS、idempotency 和 append-only audit history；
- SQLite 到 PostgreSQL 使用停止写入、export manifest、count/digest/high-water mark
  校验、import、复核、authority cutover；禁止热 dual-write；
- PostgreSQL 的 Docker Compose 只管理基础依赖，Zebra 主应用容器保持独立；
- 本 ADR 不决定 factory、连接池、物理表名、version ID 格式或是否新增 package。

Memory 新写最终必须使用 `(authority_issuer, namespace_id)` 和显式 Definition scope。
现有 `tenant_id/user_id/repo_id` 仅是兼容输入；迁移必须依赖可信显式映射，禁止推断
issuer/业务关系、裸 legacy-key 查询或继续新增 legacy 写入。具体 caller map、schema
和分批迁移由 `AGENT-DEF-MEM-01` 冻结后实施。

## 11. Package 与依赖边界

- domain models 和 Registry Port 位于 `agent-core`，Core 不依赖基础设施包；
- SQLite/PostgreSQL Adapter 位于 `agent-storage` 或 Gate B 证明必要的新 Adapter package；
- apps 只做 config、composition 和 API/CLI entry；
- Trust/Policy 继续属于 `agent-context`/`agent-security`；
- Eval 聚合继续属于 `agent-observability`；
- 不创建 `agent-sdk`、`memory-core`、`context-security` 或第二套 Skill Runtime。

## 12. 被否决方案

### 把 AgentDefinition 当作运行实体

否决。它会与 AgentTask/Segment、Event recovery 和单 Agent 默认形成第二执行身份。

### Definition 直接授予 Tool、Skill 或 Credential

否决。声明、Enabled、Granted 和 Approved 必须分层；内容元数据不能产生 authority。

### 把 Definition 与 Attempt authority 合为长期快照

否决。它会让过期/撤销权限随 Task 永久存活，违反 ADR-012。

### Event Store 保存完整 Definition 或 Registry 保存执行状态

否决。两者都会形成双事实源和恢复漂移。

### 使用 `latest`、未 pin 引用或发布后原地修改

否决。恢复、回放和 Eval 必须绑定 immutable version/digest。

### SQLite/PostgreSQL dual-write 或故障时回退旧库

否决。并行 authority 无法证明顺序、撤销和恢复一致性。

### 自动学习修改已发布版本

否决。改进只能进入新 Draft、Version、Eval 和 Release。

## 13. 实施与解锁顺序

1. 本 ADR 合并到 `main` 后，只有 `AGENT-DEF-CON-01` 可进入 `Ready`；
2. Core contract 合并后，SQLite Registry 与 `AGENT-AUTH-SNAPSHOT-01` 可分别推进；
3. SQLite Registry 合并后可实现 Draft/Version management；待 Draft/Version 与
   Attempt authority 均合并后，Task binding 才可推进，且只允许生产环境
   `resolve_published` 和受限的 non-production Eval exact-pin，不得暴露真实
   publish mutation；
4. Binding、Memory、Trust 完成后，Agent version Eval gate 聚合真实执行证据；
5. 只有 Eval gate 合并后，`AGENT-DEF-PUB-01` 才实现 publish/deprecate/revoke API；
6. PostgreSQL Adapter 可在 SQLite contract 稳定后独立推进，不阻塞 local-first chain；
7. 任一任务开始前必须重新确认 Owned paths，尤其是 Memory 的 API/CLI callers。

## 14. 验收

- 新读者能区分 Definition、Task、Segment、Attempt 和 external actor；
- 新读者能区分 Registry metadata、Event execution facts 和 external authority；
- Task 配置 snapshot 与 Attempt permission snapshot 不互相替代；
- namespace、grant、Extension、Memory、Revocation 和 Storage 均与上游 ADR 一致；
- 最终架构只记录本 ADR 的稳定结论，不复制未冻结实现细节；
- 除 `AGENT-DEF-ADR-01` 外，没有实现任务因本 ADR 分支本身提前解锁。

## 参考

- [`Zebra Agent Runtime Upgrade Proposal v2.0.md`](./Zebra%20Agent%20Runtime%20Upgrade%20Proposal%20v2.0.md)
- [`ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md`](./ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md)
- [`ADR-013_用户任务连续性与内部执行分段.md`](./ADR-013_用户任务连续性与内部执行分段.md)
- [`ADR-014_扩展体系架构.md`](./ADR-014_扩展体系架构.md)
- [`扩展体系状态机与契约_v1.0.md`](./扩展体系状态机与契约_v1.0.md)
- [`Codex-like工程Agent平台最终架构设计_v1.0.md`](./Codex-like工程Agent平台最终架构设计_v1.0.md)
