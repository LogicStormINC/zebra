# Zebra Agent 阶段性 Session Handoff 与短线程链架构方案 v1.0

## 0. 文档状态

| 字段 | 值 |
|---|---|
| 状态 | Superseded for ordinary user experience by ADR-013；backend safety contracts retained |
| 任务 | `CTX-HO-PLAN-01` |
| 分支 | `codex/ctx-handoff-stage-plan` |
| 基线 | `CTX-LC-01` commit `0486069` |
| 目标读者 | Core、Context、Storage、Worker、API、CLI、UI、QA |
| 决策日期 | 2026-07-17 |

> 2026-07-19 决策更新：本文关于“由普通用户预览 Envelope、确认创建阶段性
> 新线程并导航到 child Session”的产品合同已由
> [`ADR-013_用户任务连续性与内部执行分段.md`](./ADR-013_用户任务连续性与内部执行分段.md)
> 取代。现有 lineage、Envelope、原子性、no-replay、authority narrowing 和恢复
> 合同继续作为后台 Execution Segment rollover 的安全基础。本文其余历史设计与
> 验收证据保留，不再作为普通 Desktop 交互规范。

本文定义 Zebra 在明确阶段边界创建关联新 Session 的长期方案。它补充
[`上下文生命周期与混合压缩架构方案_v1.0.md`](./上下文生命周期与混合压缩架构方案_v1.0.md)，但不改变首要决策：上下文高水位默认在当前 Session 内 Compaction，不能把“新开线程”当作绕过 Context Window Planner 的自动 fallback。

## 1. 决策摘要

1. 默认路径仍是同一 Session 内的 hard gate、Micro-compaction、Projection Folding、
   `ContextCapsule` 和 provider continuation。
2. 历史 v1 将阶段性新线程定义为显式产品操作；ADR-013 已废弃该普通用户合同。
3. Agent 只能给出 typed rollover hint；是否创建内部 Segment 由后端生命周期控制器决定。
4. 新 Session 不是旧历史的复制品，只接收可验证的 `SessionHandoffEnvelope`、必要
   Artifact 引用、工作空间绑定和最近精确证据。
5. 父子 Session 都记录耐久关联事件；Session lineage 可查询、可审计、可重放。
6. 未决工具、审批、澄清、运行中 lease 或不确定副作用禁止跨 Session 搬运。
7. 已完成工具调用只作为证据进入 handoff，不得在新 Session 中静默重放。
8. Handoff 不继承或扩大权限；子 Session 的 Policy、Tool、Network、MCP 和 Credential
   authority 必须与父 Session 相同或更窄。
9. Provider 私有 continuation 不跨 Session；新 Session 从 Zebra 透明状态重建上下文。
10. v1 只支持线性阶段链，不实现自动分支、合并、Agent Teams 或嵌套线程树。

## 2. 当前基线与缺口

### 2.1 已有能力

- `Session` 拥有耐久事件流、状态机、恢复、审批、澄清和消息追加能力；
- `CTX-LC-01` 已提供透明、版本化、可验证的 `ContextCapsule`；
- Context Capsule、完整工具 Artifact、Active Projection 和 provider continuation 已耐久化；
- API/CLI 可 inspect context 并在非运行边界手动 compact；
- `agent.research` 提供有界只读 Subagent，只向主路径返回摘要、来源和 usage；
- Session 创建、列表、详情和流式事件读取已经存在。

### 2.2 仍缺失

- `Session` 没有 `parent_session_id`、`root_session_id`、`handoff_id` 或 `stage_index`；
- 没有从父 Session 原子创建关联子 Session 的 application Port；
- 没有跨两个事件流写入 lineage 的事务合同；
- 没有 Handoff Envelope schema、validator、Artifact 类型或 checksum；
- 没有 `/handoffs` API、CLI 命令、UI 操作或 lineage read model；
- 没有新 Session 的 handoff context 注入和 worker recovery 路径；
- 没有防止跨 Session 重放工具副作用的专门验收矩阵。

### 2.3 与 Research Subagent 的区别

| 能力 | Research Subagent | Stage Handoff |
|---|---|---|
| 目的 | 隔离高噪音只读证据采集 | 将主任务推进到新的显式阶段 |
| 生命周期 | 单次调用、进程内 coordinator | 耐久 Session，可暂停、恢复、审计 |
| 输出 | 有界摘要、来源、usage | Handoff Envelope + Artifact refs + lineage |
| 工作空间 | 继承只读 workspace | 继承明确 workspace binding，权限不扩大 |
| 返回路径 | 结果回填父 Session | 子 Session 成为后续主路径 |
| 嵌套 | v1 深度 1 | v1 线性链，不支持树形分叉 |

## 3. 目标与非目标

### 3.1 目标

- 在阶段边界降低 context rot，而不删除或篡改父 Session 的耐久历史；
- 让长期任务形成可导航的线性 Session 链；
- 让新 Session 获得足够的公开、可验证状态继续工作；
- 保留原始目标、验收标准、用户约束、决策、工作空间和验证证据；
- 对崩溃、请求重试、重复点击和 worker takeover 保持幂等；
- 让 operator 能解释“为什么切换、从哪里来、保留了什么、遗漏了什么”。

### 3.2 非目标

- 不根据 token 占用、模型报错或 cache miss 自动创建新 Session；
- 不用 handoff 替代当前 Session 内 Compaction；
- 不持久化或传递隐藏 reasoning、provider 私有 CoT 或 credential；
- 不迁移 pending approval、pending clarification、pending tool call 或运行中副作用；
- 不实现任意 DAG、线程合并、自动 fan-out、Agent Teams 或 nested stage chains；
- 不跨 workspace、tenant、repo identity 或 credential boundary 交接；
- 不自动 commit、push、创建 PR、切换分支或修改权限；
- 不把 Handoff Envelope 当成 Event Store、Artifact 或 Git 状态的替代品。

## 4. 触发模型

### 4.1 v1 允许的触发

| 触发 | 行为 |
|---|---|
| 用户明确要求“进入下一阶段/新线程继续” | 直接进入 handoff preflight |
| Operator 从 API/CLI/UI 触发 | 直接进入 handoff preflight |
| Agent 判断阶段已经完成 | 只能产生建议，等待用户确认 |
| Context quality 指标持续恶化 | 只能产生建议和诊断，不自动执行 |

### 4.2 明确禁止的触发

- `within_budget=false` 时自动新建 Session；此时仍应 compact 或 fail closed；
- 首个公开 delta 之后为规避模型失败而静默 handoff；
- 工具执行状态不确定时通过新 Session 重新生成并执行；
- 当前 Session 等待审批或澄清时把待处理动作搬到新 Session；
- 仅因为会话时间长或消息数量多就自动切换。

### 4.3 安全创建边界

Handoff 只允许在 source Session 没有活动写 lease、没有运行中工具、没有未决审批或
澄清、没有不确定外部副作用的边界执行。v1 使用固定 allowlist：

- `completed` 与 `suspended`：允许进入事务内最终 preflight；
- `created`、`ready`、`running`、`waiting_approval`、`waiting_input`、`failed`、
  `cancelled`：全部拒绝。

`ready` 不代表阶段已经形成稳定事实，失败/取消也不能被 handoff 包装成成功交接；未来
若要扩大 allowlist，必须单独修改状态合同和 Eval。Source Session 原状态保留；
handoff 事件是 lineage 事实，不伪造新的执行终态。

## 5. 领域模型

### 5.1 Session Lineage

```python
class SessionLineage(BaseModel):
    session_id: SessionId
    root_session_id: SessionId
    parent_session_id: SessionId | None
    inbound_handoff_id: HandoffId | None
    stage_index: int
```

约束：

- root Session 的 `root_session_id == session_id`、`stage_index == 0`、parent 和 inbound
  handoff 为空；
- v1 的 child 必须与 parent 共享 root，`stage_index == parent.stage_index + 1`；
- lineage 创建后不可修改；
- child 不得指向自身、后代或其它 tenant/workspace；
- v1 不提供 merge parents；storage 对 `parent_session_id` 设置 committed successor 唯一
  约束，同一 parent 最多有一个 child，禁止用不同 idempotency key 绕过线性链。
- 默认最大 `stage_index` 为 8，Task Profile 只允许降低；超过时返回稳定错误
  `handoff_depth_exceeded`。

### 5.2 Handoff Reason

```text
user_phase_boundary
operator_handoff
long_term_maintenance
context_quality_recommendation_confirmed
```

Reason 是审计分类，不授予权限，也不改变 source Session 的完成状态。

### 5.3 SessionHandoffEnvelope

`SessionHandoffEnvelope` 是跨 Session 的透明交接合同，不复用 provider 私有状态，也不
直接把当前 `ContextCapsule` 改造成线程对象。

```python
class SessionHandoffEnvelope(BaseModel):
    handoff_id: HandoffId
    version: str
    source_session_id: SessionId
    target_session_id: SessionId
    root_session_id: SessionId
    source_stage_index: int
    target_stage_index: int
    reason: HandoffReason
    focus: str | None
    objective: str
    acceptance_criteria: tuple[str, ...]
    protected_user_constraints: tuple[str, ...]
    decisions_and_rationale: tuple[str, ...]
    completed_work: tuple[str, ...]
    pending_work: tuple[str, ...]
    immediate_next: str
    touched_files: tuple[str, ...]
    validation_results: tuple[str, ...]
    known_failures: tuple[str, ...]
    open_questions: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    source_context_capsule_id: str | None
    source_event_range: ContextSourceEventRange
    source_event_hash: str
    workspace_revision: WorkspaceBindingRevision
    completed_tool_evidence: tuple[CompletedToolEvidence, ...]
    known_omissions: tuple[str, ...]
    created_at: datetime
    checksum: str
```

```python
class WorkspaceBindingRevision(BaseModel):
    workspace_id: str
    repo_id: str | None
    revision_hash: str
    commit_sha: str | None
    runtime_snapshot_id: str | None

class CompletedToolEvidence(BaseModel):
    tool_call_id: str
    tool_name: str
    terminal_event_sequence: int
    terminal_status: str
    side_effect_class: str
    result_artifact_ref: str | None
    effect_identity: EffectIdentity | None

class EffectIdentity(BaseModel):
    authority_scope_hash: str
    tool_name: str
    operation_kind: str
    target_hash: str
    canonical_effect_hash: str
    external_operation_id_hash: str | None
```

`revision_hash` 始终必填，即使 workspace 没有 Git commit 或 runtime snapshot。它由 durable workspace binding、repo identity、Git 状态和 snapshot identity 的 canonical projection 计算，使 live workspace 也具备可比较版本。

`side_effect_class` 只能是 `read_only`、`idempotent_effect` 或 `non_idempotent_effect`。
所有 effectful terminal evidence 必须带 `EffectIdentity`；Tool Gateway 在原调用执行前根据
authority、tool、operation、target 和去除随机值后的 canonical payload 计算，不能由模型
提供。无法计算稳定 identity 会阻止 handoff；read-only 可无 identity，并允许 child 重读。

### 5.4 Envelope 内容边界

必须保留：

- 原始 objective、验收标准和所有 protected user constraints；
- 影响后续实现的公开决策及理由；
- 已完成/待完成工作、立即下一步、修改文件和测试结果；
- Artifact 引用、来源事件范围/hash、workspace binding 和 Git/Snapshot 身份；
- completed tool 的结构化 terminal evidence 和 side-effect classification；
- 所有已知遗漏、失败和开放问题。

必须排除：

- `reasoning_content`、CoT、provider encrypted continuation；
- credential、token、secret、原始环境变量；
- 完整大型日志、二进制 payload 或可由 Artifact 引用的重复内容；
- pending tool arguments、approval grant 或可直接执行的临时 capability；
- 无来源、无法验证或模型臆测的“已完成”声明。

## 6. Validator 与 Preflight

Validator 从耐久 Event Store、Artifact Store、Workspace Projection、Policy Projection 和
Runtime Snapshot 获取外部事实，至少验证：

1. source/target/root/session stage identity 一致；
2. source event range 连续且 hash 匹配；
3. source 没有 active lease、pending tool、approval、clarification 或 uncertain side effect；
4. 所有 protected constraints 完整；
5. 所有 Artifact refs 存在、可读且属于同一 authority boundary；
6. workspace revision、repo identity、tenant 和 source commit/snapshot 可验证；
7. completed work 有对应事件、Artifact、Git 或测试证据；
8. target authority 等于或窄于 source effective authority；
9. checksum 与 canonical serialization 匹配；
10. reserved target identity 与 operation record 一致，且 target 尚未 committed；
11. source event stream version、lease fencing token、authority revision 和 workspace
    revision 与 operation reservation 一致；
12. parent 尚无 committed successor；锁内重算的 current stage、Task Profile revision 和
    effective depth limit 与 reservation 一致，且 target stage 未超限；
13. 所有 effectful completed tools 都有可验证 `EffectIdentity` 和已存在的 terminal
    root-lineage ledger entry；Handoff validator 只校验，不补写 ledger。

Candidate validator 使用 operation reservation 中服务端预分配的 handoff/target id；真正
创建后由 storage invariant 验证 lineage 和事件一致性。任何失败都必须在创建 child 前
结束，不能留下半创建 Session。

## 7. 创建事务与事件

### 7.1 Durable Handoff Operation

Storage 先以 `(source_session_id, idempotency_key_hash)` 保留一个耐久
`HandoffOperation`：

```text
preparing -> committed
          -> aborted
```

Operation 保存 request hash、服务端预分配的 handoff/target id、expected source stream
version、source lease fencing token、authority revision、workspace revision、Task Profile
revision、effective stage-depth limit 和 Artifact id。
`preparing` 可在崩溃后继续；只有确定性 validation/conflict 才进入 `aborted`；临时 storage
或 provider 错误保持可重试。Operation row 不是 Session 事实，committed parent/child 事件
才是 lineage 的权威来源。

### 7.2 准备与提交

```text
resolve source projection
  -> reserve HandoffOperation and target id
  -> verify safe boundary at expected source version
  -> build deterministic envelope candidate
  -> optional model-assisted public summary
  -> validate against durable facts
  -> persist immutable handoff Artifact
  -> begin final storage transaction and lock source
  -> lock 内重算 stage/depth 并 CAS source version/fencing/authority/workspace/profile/limit
  -> atomically append parent event + create child events + lineage index + dispatch outbox
  -> mark operation committed
  -> worker claims outbox after commit
```

模型辅助文本只能改善公开摘要，不能决定 lineage、完成状态、权限、来源范围、checksum
或副作用状态。模型输出验证失败时回退到确定性 builder。

Final transaction 必须再次计算 safe-boundary facts，preflight 结果不能跨事务直接信任。
CAS 或唯一后继约束失败返回 typed conflict，不覆盖新状态。

### 7.3 耐久事件

Parent Session 只追加一个权威 `SessionHandoffCommitted`，记录 handoff/target id、reason、
stage、source range/hash、Artifact id、checksum 和 idempotency key hash。`preparing` 或
`aborted` 属于 operation/audit store，不向 Session Event Store 写入半完成 lineage。

Child Session：

- `SessionCreated`：普通新 Session 创建事实；
- `SessionHandoffReceived`：记录 parent/root/handoff/stage/Artifact/checksum；
- `UserMessageReceived`：作为 child 唯一初始 user message 保存 exact `stage_prompt`；payload
  记录 `source=session_handoff`、handoff id、principal hash 及认证所得的
  `actor_kind/trust`（`direct_user`、`operator` 或 `automation`），不得硬编码来源；
- `TaskPrepared`：使用新阶段 title、显式 focus 和继承后收窄的 authority。

Parent committed event、child created/received events、可重建 lineage index、operation
committed update、`UserMessageReceived` 和 child dispatch outbox 必须处于同一 storage
transaction。Child 在事务中进入 `ready`；outbox claim 不改变状态。Worker 必须先获取带
fencing token 的 workspace lease、验证固定 revision，再原子转为 `running`；漂移则原子
转为 `suspended`。任何模型或工具调用都发生在该转换之后。Handoff Artifact 可先写入
不可变存储，但 committed event 前不具权威性；未引用 Artifact 由 retention sweep 清理。

### 7.4 幂等与 Dispatch

- 客户端必须提交 `idempotency_key`；
- storage 对 `(source_session_id, idempotency_key_hash)` 建唯一约束；
- 相同 key 和相同 request hash 返回原 handoff/child；
- 相同 key、不同 request hash 返回 conflict；
- worker dispatch 失败可以安全重试，不创建第二个 child；
- committed 后的网络超时不得触发第二次 lineage 写入。
- 不同 key 并发请求受 parent successor unique key 和 source-version CAS 约束，最多一个
  committed；失败者返回 `handoff_successor_conflict`。
- outbox 使用 child session id 作为 delivery id；worker 以 claim/lease/ack 消费，重复投递
  只恢复同一 child，不重新创建 handoff 或重复初始事件。

## 8. Child Context 组装

Child 首次模型调用使用新的稳定前缀和新的动态 conversation，不复制 parent 的完整消息。

```text
system / organization / project rules
+ child task title and explicit stage focus
+ validated SessionHandoffEnvelope
+ referenced source ContextCapsule as bounded evidence
+ selected Artifact previews
+ exact `WorkspaceBindingRevision`
+ current tool schemas and effective Policy
+ caller-provided `stage_prompt` as a new attributed user event
```

规则：

- parent 完整事件仍留在 Event Store，通过 lineage/Artifact 按需读取；
- provider-native continuation 不跨 Session；
- child 重新经过 Context Window Planner；
- child 不把 handoff data 当成系统权限指令；
- final transaction 前的 workspace drift 由 CAS 拒绝且不创建 child；commit 后，worker
  claim dispatch 但保持 `ready`，获取 workspace lease/fence 后再次校验，并原子执行
  `ready -> running`；漂移则追加 `SessionHandoffWorkspaceDriftDetected` 并原子执行
  `ready -> suspended`。v1 只能恢复固定 revision 后 resume，或 cancel child；
- child 对任何新动作重新走 Tool Gateway、Policy 和审批。

## 9. 工具副作用与恢复

### 9.1 已完成工具

Handoff 只保存结果证据，不保存重执行指令。启用本能力前，Tool Gateway 必须对每个
effectful 调用在副作用前，以 `(root_session_id, EffectIdentity)` 唯一键原子 reserve ledger：
`reserved -> executing -> succeeded | failed_no_effect | uncertain`。外部调用返回后，terminal
tool event 与 ledger terminal state 在同一耐久事务提交；进程在外部调用后、提交前崩溃则
保持 `uncertain`，只能 reconciliation，不能静默重放。重复 identity：`succeeded` 返回既有
证据，`reserved/executing/uncertain` 拒绝，只有已证明 `failed_no_effect` 才允许显式新 attempt。
Handoff validator 只接受已有 terminal ledger entry；旧调用无法验证或未入 ledger时拒绝。
新 call id、模型文本或 client key 均不能绕过。Read-only 可用新 call id 重新取证。

### 9.2 未完成或不确定工具

- `ToolExecutionStarted` 无确定 terminal event：拒绝 handoff；
- pending approval/clarification：拒绝 handoff，先在 parent 解决；
- 外部 API 状态未知：拒绝 handoff，先通过原 Session recovery/inspection 收口；
- uncertain side effect 必须先追加明确 reconciliation terminal event；普通 summary 不得
  把 unknown 改写成 success/failure；
- 已安全失败且无副作用：记录 failure，可在 child 中重新规划，但必须产生新 tool call id。

### 9.3 崩溃恢复

| 崩溃点 | 恢复行为 |
|---|---|
| Artifact 写入前 | 无状态变化，重试 builder |
| Artifact 已写、事务未提交 | Artifact 非权威，重试或清理 |
| 跨 Session 事务已提交、worker claim 前 | child 保持 ready；outbox 保留并重新 claim |
| Commit 后发现 workspace drift | child durable suspended；恢复固定 revision 或取消 |
| Child 已开始执行 | 按普通 child Session recovery，不重建 handoff |
| Parent/child projection 或 lineage index 丢失 | 从两个权威事件流重建查询索引 |

## 10. API、CLI 与 UI

### 10.1 API

```text
POST /sessions/{source_id}/handoffs
GET  /sessions/{session_id}/lineage
GET  /handoffs/{handoff_id}
```

创建请求仅接受：`idempotency_key`、`title`、`reason`、必填 `stage_prompt`、可选 `focus`
和显式 authority 收窄项。`stage_prompt` 原样归因到真实认证主体；API、CLI 或 automation
不能伪装成 direct user。客户端不能直接提交 lineage/checksum、完成状态或 Artifact ownership。

创建响应返回：handoff id、child session id、lineage、source/target status、Artifact id、
checksum、known omissions 和是否为幂等重放。

### 10.2 CLI

```text
zebra-agent session handoff <source-id> --title ... --reason ... --prompt ... [--focus ...]
zebra-agent session lineage <session-id>
zebra-agent handoff inspect <handoff-id>
```

CLI 默认打印预检摘要并要求确认；自动化可使用显式 `--yes` 和 caller-provided
idempotency key。CLI/API 字段必须有 contract matrix。

### 10.3 UI

- 只在 safe boundary 显示“Start next stage”；
- 展示新阶段将保留、引用和遗漏的内容；
- 显示 parent/root/stage breadcrumb；
- 不把 Research Subagent 显示成耐久阶段线程；
- 不在 context usage 卡片中提供“自动新开线程”开关；
- 创建后导航到 child，但 parent 保持可读和可返回。

## 11. 权限与安全

- Handoff 是控制面写操作，要求 session write authority；
- source/target 必须属于同一 tenant、workspace 和 repo identity；
- child effective authority 计算为
  `intersection(current caller authority, source durable ceiling, requested narrowing,
  current policy)`；不存在可比偏序或交集为空时 fail closed；
- 一次性 approval、临时 capability 和 provider token 永不继承；
- credential 只保留可审计 broker binding identity，child 必须重新授权 binding，不复制
  source grant 或 secret；
- Artifact 引用需重新执行 child read authorization；
- Handoff Envelope 作为不可信数据块注入，不可覆盖 system/Policy；
- 所有 Envelope/focus/title/stage prompt 经过长度和编码校验，并以结构化不可信数据通道
  注入；它们不得提升指令优先级，Policy 不读取其授权语义；
- 审计记录 actor、reason、source/target、authority delta、checksum 和结果，不记录 secret。

## 12. 可观测性

至少记录：

- handoff success/rejection count、reason 和 rejection category；
- source/target/root/stage/profile；
- Envelope byte/token estimate、Artifact count、known omission count；
- build/validate/transaction/enqueue latency；
- deterministic 或 model-assisted generator 及 validator 结果；
- child 首次调用 TTFT、首次完成率、恢复次数和 lineage depth；
- handoff 后重复工具调用检测、workspace drift 和 authority narrowing；
- parent/child token、成本和质量对照。

禁止记录 Envelope 正文、reasoning、secret、完整日志或工具原始大输出。

## 13. Eval 与验收矩阵

### 13.1 硬不变量

- Context 高水位永远不自动创建 child Session；
- 同一 idempotency key 最多产生一个 child；
- parent/child lineage 和事件在崩溃后可重建；
- pending 或 uncertain side effect 时 handoff 必须失败；
- child 不获得更宽 authority；
- reasoning、credential、provider continuation 不进入 Envelope；
- effectful completed tool 不因 handoff 被重放；read-only 重读必须是新调用；
- parent 完整历史保持不变、可审计、可读取。

### 13.2 场景

1. Completed parent 创建 stage 1 child，并继续创建 stage 2；
2. 重复网络请求返回同一 child；
3. 相同 key、不同 focus 返回 conflict；
4. waiting approval、waiting input、running、active lease 均拒绝；
5. Tool started 无 terminal event 时拒绝；
6. Artifact 写入后事务失败，重试只产生一个 committed child；
7. 事务提交后 enqueue 失败，worker sweep 恢复 child；
8. Workspace/Git drift 被发现且不静默覆盖；
9. child authority 继承与收窄成功，扩大失败；
10. Capsule/provider continuation 缺失时仍可用透明 Envelope 恢复；
11. 恶意 Artifact/summary 不能修改 Policy；
12. API/CLI/UI lineage 和 handoff readback 一致；
13. 真实 provider 从 handoff 状态继续任务且不重复 parent tool；
14. 长链达到配置上限后 fail closed。
15. 两个不同 idempotency key 并发竞争同一 parent，只有一个 successor committed；
16. source version、lease fencing、authority、workspace、profile/limit 或 stage 在 preflight 后变化时 CAS 拒绝；
17. outbox 重复投递只启动/恢复同一 child；
18. 相同 external operation identity 的工具在 child 中被 Gateway dedupe 或拒绝。
19. stage prompt、caller actor/trust provenance 在崩溃后从 child 事件流完整恢复；
20. direct user、operator、automation 的 stage prompt actor/trust 均准确恢复；
21. commit 后 workspace drift 在任何模型/工具前令 child durable suspended。

## 14. 分阶段实施建议

### CTX-HO-01A：Core 合同与 Lineage

- `SessionLineage`、`HandoffReason`、`SessionHandoffEnvelope`、validator；
- parent/child 事件 payload 和 application Port；
- 状态/authority/preflight 决策；
- 纯领域与事件合同测试。

### CTX-HO-01B：Storage 原子性

- immutable Handoff Artifact；
- lineage table 和 idempotency unique key；
- 跨 parent/child event stream transaction；
- projection rebuild、orphan cleanup 和并发测试。

### CTX-HO-01C：Context、Worker 与 Recovery

- deterministic Envelope builder；
- child 首轮 context injection；
- transactional outbox、ready/running/suspended recovery、workspace drift 和 root-lineage
  effect dedupe guard；
- crash matrix 与真实 provider smoke。

### CTX-HO-01D：API、CLI 与 Operator Surface

- create/inspect/lineage API；
- CLI handoff/lineage/inspect；
- contract matrix、认证、幂等与错误规范化；
- safe-boundary UI 和 lineage breadcrumb。

### CTX-HO-01E：Eval、灰度与发布

- quality/cost/context-rot 对照 Eval；
- disabled-by-default feature flag；
- local opt-in 灰度，确认收益后再开放普通 UI；
- 回滚只关闭新 handoff 创建，既有 lineage 保持可读和可恢复。

实际编码前必须把 A-E 拆成 path-bounded task cards，按依赖顺序合并，不能让多个
contributor 同时修改 Session 事件和 storage transaction 热点。

## 15. 发布与回滚

1. v1 默认关闭，只允许测试和显式 operator opt-in；
2. 首轮只支持同 workspace、线性链、无 pending state 的 completed/suspended source；
3. 指标证明连续性优于同 Session Compaction 后，才扩大到普通阶段操作；
4. 不根据 token/时间自动触发；
5. 关闭 feature flag 后禁止创建新 handoff，但已有 child 和 lineage 仍正常读取、恢复；
6. Schema 版本升级保留旧 reader，不重写历史 Envelope。

## 16. 已固定的 v1 决策与后续问题

- v1 source allowlist 固定为 `completed/suspended`；
- 默认最大 stage depth 固定为 8，Task Profile 只能降低；
- 同一 parent 固定最多一个 committed successor；
- Event Store 中的 committed parent/child events 是 lineage 事实源，lineage row 只是可重建
  查询索引；Handoff Artifact 被任一后代 lineage 引用时必须 retention pin；
- live workspace 必须提供可比较 `WorkspaceBindingRevision`；commit 前 drift 令 operation
  abort/rebuild，commit 后 drift 令 child suspended，operator 只能恢复固定 revision 或
  cancel，不能确认后沿用旧 revision；
- caller 必须提供并承担 `stage_prompt` 的 user actor/trust provenance。

后续可独立评估：

- model-assisted public summary 是否推迟到 deterministic v1 之后；
- UI 是否需要阶段链总览，或首期仅提供 breadcrumb。

后续问题不改变 v1 的安全和一致性合同；必须在相应 UI/summary 子任务激活前写入任务卡。

## 16.1 实施状态（2026-07-18）

CTX-HO-01A 至 01E 已按依赖顺序实现。创建面由 `ZEBRA_SESSION_HANDOFF_ENABLED`
控制且默认关闭；关闭后 inspect/lineage 和既有 child recovery 继续可用。发布前必须运行
handoff Eval、全量测试、Desktop 检查和 `evals/providers/session_handoff_smoke.py`。
回滚只把开关恢复为 `false`，不得删除事件、Envelope、lineage 或 effect ledger。

## 17. Definition of Done

只有同时满足以下条件，阶段性新线程能力才可标记 Done：

- A-E 任务全部合并到 `main`；
- 领域、storage、API/CLI、worker/recovery 和 UI 契约完整；
- 幂等、并发、崩溃、no-replay、authority 和注入攻击测试通过；
- 全量测试、文件门禁、Ruff、Mypy 和 release eval 通过；
- 真实 provider 完成至少一次 parent -> child 连续任务且没有重复副作用；
- operator 文档、灰度开关、监控和回滚路径可用；
- `docs/AGENT_TASKS.md`、`PROGRESS.md` 和架构文档状态一致。
