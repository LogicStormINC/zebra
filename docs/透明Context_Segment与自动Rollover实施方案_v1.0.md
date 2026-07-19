# Zebra Agent 透明 Context Segment 与自动 Rollover 实施方案 v1.0

## 1. 目标与边界

本方案落实 ADR-013：用户和外部业务系统只感知稳定 Task，Zebra Runtime 可以在
Task 内部自动使用多个 Execution Segment。现有 Handoff Envelope、lineage、
Effect Ledger、authority narrowing 和恢复合同作为内部实现基础，不再作为普通
聊天产品功能。

本方案不把用户、组织、成员、业务 RBAC、订阅或计费引入 Zebra。外部系统提交
Task 和签名 Agent authority；Zebra 只管理 Agent 执行、对话连续性、并发、恢复、
usage evidence 和技术限制。

## 实施状态（2026-07-19）

P0-P4 的本地 SQLite/API/Desktop 合同已由 `CTX-SEG-01` 一次性落地：

- `TaskId`、`AgentTask`、`ExecutionSegment`、Task Port 和可重建 SQLite 投影；
- handoff 创建 child Segment 与 `active_segment_id` CAS 在同一事务提交；
- `/tasks` 创建、读取、列表、消息、停止、挂起、恢复及跨 Segment 单调流；
- 完成后的普通续问和取消/失败后的恢复自动建立内部 Segment，附件保持可用；
- typed lifecycle controller 对上下文压力、恢复、Agent hint、审批、澄清、运行中
  工具、未知副作用和 drift 作确定性决策；rollover mutation 只由 internal 路由承载；
- Desktop 全面使用稳定 Task identity，删除用户可见的 Handoff 表单、Envelope 与
  child navigation；operator 仍可通过 internal Segment read 检查 lineage；
- 既有 root Session/lineage 在读取时回填 Task 投影，普通 child Session detail 被隐藏。

PostgreSQL、分布式调度与独立服务身份网关仍是云部署适配工作，不属于本地
`CTX-SEG-01` 的完成条件；它们不得改变 Task/Segment 领域合同。

## 2. 领域模型

### 2.1 Task

`Task` 是公开、稳定、耐久的用户工作单元：

```python
class AgentTask:
    task_id: TaskId
    namespace: str
    title: str
    status: TaskStatus
    active_segment_id: SessionId
    authority_digest: str
    workspace_binding_revision: str
    current_sequence: int
```

Task 不复制业务用户或租户目录，只保存外部 namespace 和经验证的技术 authority。

### 2.2 Execution Segment

现有 Session 在新模型中承担内部 Segment：

```python
class ExecutionSegment:
    session_id: SessionId
    task_id: TaskId
    predecessor_id: SessionId | None
    visibility: Literal["internal"]
    rollover_reason: RolloverReason | None
    segment_index: int
```

首个 Segment 也不成为额外用户会话。Task Projection 是普通产品读取入口。

### 2.3 Task Event Stream

每个 Segment 保留原有事件流与局部 sequence；新增 Task Stream 分配独立、单调的
task sequence，并引用原始 `(segment_id, segment_sequence, event_id)`。Projection
只呈现用户相关事实，内部 lifecycle 事件保留在审计视图。

## 3. 生命周期控制

`ContextLifecycleController` 每次 provider 调用前、工具边界后、attempt 结束和恢复
时计算以下决定：

```text
continue_current_segment
compact_current_segment
rollover_internal_segment
pause_for_approval_or_clarification
fail_closed
```

建议默认策略：

- soft watermark：优先 Micro-compaction/Projection Folding/Context Capsule；
- hard watermark：若压缩后仍无法满足 outbound hard gate，准备 rollover；
- repeated compaction：压缩收益低于配置阈值或 Capsule 恢复质量下降时 rollover；
- provider boundary：安全 continuation 不可用且透明状态足够时 rollover；
- runtime recovery：必须创建新执行载体时 rollover；
- Agent hint：只作为输入信号，不绕过 Controller 校验。

“阶段完成”本身不强制 rollover。短任务、简单续问和仍有充分上下文的 Task 继续
使用当前 Segment。

## 4. 原子 Rollover

Controller 只在以下条件全部成立时进入事务：

- 当前 Segment 为唯一活动写入者且 fencing token 有效；
- 没有 running tool、pending approval/clarification 或 unknown effect；
- Workspace revision 和 authority digest 与预检一致；
- 当前状态可形成稳定 Checkpoint；
- 目标 authority 与当前相同或更窄。

事务复用现有 HandoffOperation：

1. reserve 唯一目标 Segment 和 idempotency scope；
2. 固化 Context Capsule、Artifact refs、effect terminal facts 和 Checkpoint checksum；
3. 追加 source rollover-committed 事实；
4. 创建 internal target Segment 和初始事件；
5. CAS 更新 `task.active_segment_id`；
6. 写入 dispatch outbox；
7. commit 后由 Worker claim 并恢复执行。

任何步骤失败都不能暴露半个 Segment。重试必须返回同一目标，不能创建并行后继。

## 5. 上下文与副作用

目标 Segment 的首个上下文由以下内容构成：

- system/developer/policy 当前版本；
- Task objective 与未完成计划；
- 经过校验的 Context Capsule；
- 最近高价值用户/Assistant delta；
- Artifact-backed 工具结果投影；
- Workspace/Snapshot revision；
- root Task Effect Ledger terminal facts。

禁止携带 provider-private reasoning、未验证 continuation、原始 Secret、完整大输出、
运行中工具指令或未知外部副作用。已完成 effectful tool 只能作为证据，不能作为
待执行指令。

## 6. API 与 UI

### 6.1 普通公开 API

目标接口以 Task 为中心：

```text
POST /tasks
GET  /tasks/{task_id}
GET  /tasks/{task_id}/stream
POST /tasks/{task_id}/messages
POST /tasks/{task_id}/cancel
POST /tasks/{task_id}/resume
```

兼容期 Session API 通过 root Task resolver 路由到 active Segment。普通列表过滤
internal Segment，响应不包含 handoff/segment lineage。

### 6.2 Internal/Operator API

```text
POST /internal/tasks/{task_id}/segments/rollover
GET  /internal/tasks/{task_id}/segments
GET  /internal/tasks/{task_id}/lineage
```

只允许服务身份或 operator audit authority，不能由普通 Desktop token 调用。

### 6.3 Desktop

Desktop 永远绑定 Task：

- 不显示阶段表单、Envelope、child Session、stage index 或 breadcrumb；
- 不因 rollover 新建侧边栏项、改变 URL 或替换当前 conversation key；
- SSE 自动跨 Segment 继续；
- 可选显示短暂的非交互“正在整理上下文并继续执行”；
- 审批、澄清、失败和权限变化仍如实呈现。

## 7. 分阶段任务

### P0：纠正普通用户界面

- 接受 ADR-013，标记旧显式 handoff 产品决策为 Superseded；
- 删除 Desktop handoff 表单、preview/create action 和 child navigation；
- 保留后端合同且继续默认关闭；
- 添加不可见性回归。

退出标准：completed/suspended Session 不出现任何 handoff 创建控件，现有聊天、
审批、澄清、停止、恢复和续问检查全部通过。

### P1：Task 与 Segment 合同

- 新增 TaskId、Task status、Task/Segment mapping Port；
- 扩展现有 Session lineage 为 internal Segment metadata；
- 建立 Task Projection 和 rebuild 测试；
- 保持现有 Session API 兼容。

退出标准：多个 Segment 可重建为一个 Task，普通列表不泄漏 internal Segment。

### P2：Task Stream 与控制路由

- 新增 task-level monotonic sequence 和 replay-plus-tail SSE；
- message/cancel/resume/approval/clarification 路由到 active Segment；
- Desktop 使用稳定 task_id；
- rollover 不改变 URL、侧边栏项和 stream cursor。

退出标准：真实浏览器跨 Segment 完成长流、停止、恢复和续问。

### P3：自动 Lifecycle Controller

- 引入 typed decision 与可配置阈值；
- 连接 Context Window Planner、Capsule、Provider 和 Runtime recovery；
- 将 create/preview handoff mutation 移到 internal service；
- Agent 只可提交 typed hint。

退出标准：压力、恢复和 hint 路径自动 rollover，简单任务不产生多余 Segment。

### P4：迁移、收口与云端准备

- 回填既有 lineage 的 task_id 和 visibility；
- 废弃普通 handoff API/CLI；
- 完成 SQLite/PostgreSQL 双实现前的迁移合同；
- 加入并发、崩溃、SSE、no-replay、authority、drift 和 retention Eval。

退出标准：普通产品面只存在 Task；内部 lineage 可审计、可恢复、可迁移。

## 8. 测试矩阵

### 产品回归

- 简单 completed Session 不显示 handoff 控件；
- suspended Session 不显示 handoff 控件；
- Task 内 rollover 后侧边栏数量不变；
- rollover 前后消息顺序、URL、task_id 和 SSE cursor 连续；
- stop/resume/follow-up/approval/clarification 路由到 active Segment。

### 安全与恢复

- running tool、pending approval/clarification、unknown effect 阻止 rollover；
- 相同请求幂等，不同请求冲突，并发只产生一个后继；
- transaction/outbox/Worker 任意崩溃点恢复同一目标；
- Workspace/Snapshot/authority drift fail closed；
- effectful tool 不跨 Segment 重放；
- internal Segment 不通过普通 list/detail/stream 泄漏。

### 质量门禁

- `make test`、`make check`；
- Desktop deterministic checks、TypeScript、Vite build；
- real Chromium 长流、reload、cancel、resume、follow-up；
- packaged Tauri Runtime E2E；
- Linux gVisor 与真实 Workspace quota 门禁保持通过。

## 9. Rollout 与回滚

- P0 可独立发布，不改变后端数据；
- P1/P2 先双写 Task Projection，并以 Session API 为回退读取；
- P3 默认关闭自动 rollover，只在 Eval/内部 profile 灰度；
- 回滚只停止新 rollover，既有 Segment 与 lineage 必须继续可读和恢复；
- 指标至少覆盖 rollover 原因、延迟、拒绝类别、重复 effect、cursor continuity、
  compaction 收益和用户可见中断次数。
