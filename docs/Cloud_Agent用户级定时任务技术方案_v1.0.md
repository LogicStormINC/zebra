# Cloud Agent 用户级定时任务技术方案 v1.0

> 状态：实施中；Core 与 PostgreSQL Storage 切片已完成，后续切片待实施
> 日期：2026-09-15
> 适用范围：Zebra Cloud Agent、Trench Host、HTTP/SSE MCP、Skill、Subagent
> 明确不包含：RSS 订阅源抓取调度、运维 Cron、DAG 节点选择器

## 1. 目标

Cloud Agent 应允许每个用户在自己的租户、工作区和授权范围内创建、查看、修改、暂停、恢复、立即执行和删除定时任务。例如：

- 每天 09:00 汇总财联社订阅内容并生成报告；
- 每周一检查指定 GitHub 仓库并输出风险清单；
- 在指定时间运行一个带固定 Skill、MCP 和模型配置的研究任务。

每次触发创建一个新的普通 Cloud Agent Task。Task 继续使用现有实时流、Artifact、Skill、MCP、Subagent、Policy、Budget 和 Worker 执行链路。

## 2. 核心结论

实现可行性高。现有系统已经具备 PostgreSQL Event Store、幂等 Task admission、Transactional Outbox、RabbitMQ relay、Consumer Inbox、Worker Lease、TaskBindingSnapshot、Skill/MCP 版本绑定、流式输出、Artifact 和 Subagent。

缺失部分是用户级 Schedule 控制面、到期领取器、Firing 记录、后台授权绑定和管理 UI。首版采用 PostgreSQL DB Scheduler，不引入 Temporal，不使用 RabbitMQ 延迟队列或 TTL 队列保存定时计划。

## 3. 架构边界

```text
用户 / Trench
    │ 创建、修改、暂停计划
    ▼
Schedule API
    ▼
PostgreSQL: task_schedules + task_schedule_firings
    │ DB clock + lease + FOR UPDATE SKIP LOCKED
    ▼
zebra-agent-scheduler
    │ 生成一次确定性的 Task admission
    ▼
现有 Task Admission
    │ Event + Projection + TaskBinding + Outbox 原子提交
    ▼
RabbitMQ（仅唤醒）
    ▼
现有 Cloud Worker
    ▼
Task / Stream / Artifact / Skill / MCP / Subagent
```

### 3.1 PostgreSQL

PostgreSQL 是用户计划、下一次执行时间、Firing、领取租约、Task 关联、暂停、撤销、失败和补偿状态的唯一事实源。

### 3.2 RabbitMQ

RabbitMQ 只负责在 Task admission 成功后低延迟唤醒 Worker，不保存计划定义、不计算下一次执行时间，也不决定计划是否已经触发。Broker 不可用时，计划和 Firing 保留在 PostgreSQL，现有 Outbox relay 恢复后继续投递。

### 3.3 Scheduler

Scheduler 是共享系统进程，但调度对象和授权边界是用户级的。它只负责领取到期计划、创建唯一 Firing、推进 `next_fire_at`、将 Firing 物化为标准 Task admission。它不直接调用模型、工具、Skill、MCP 或外部业务系统。

### 3.4 不得混用的现有能力

- `agent_orchestration` DAG scheduler：仅做无 I/O 的节点就绪选择；
- Trench source scheduler：仅调度订阅源抓取；
- Outbox `available_at`：仅用于消息延迟投递和重试；
- 系统 Cron：仅用于运维任务。

## 4. 领域模型

### 4.1 TaskSchedule

| 字段 | 含义 |
|---|---|
| `schedule_id` | 全局 UUID |
| `deployment_namespace` | 部署命名空间 |
| `tenant_id/workspace_id/principal_id` | 用户所有权边界 |
| `host_app_id` | 创建计划的 Host，如 Trench |
| `title` | 用户可见名称 |
| `trigger_type/trigger_spec` | `once`、`interval`、`calendar` 及结构化规则 |
| `timezone` | IANA 时区，如 `Asia/Shanghai` |
| `task_template` | 冻结的 Task 创建模板 |
| `status` | `active`、`paused`、`completed`、`deleted` |
| `schedule_version` | 乐观并发版本 |
| `next_fire_at/last_fire_at` | UTC 执行时间 |
| `overlap_policy/misfire_policy` | 重叠和错过策略 |
| `created_at/updated_at` | 审计时间 |

### 4.2 TaskScheduleFiring

每个应执行时间点产生一个不可变 Firing：

| 字段 | 含义 |
|---|---|
| `fire_id` | 确定性触发 ID |
| `schedule_id/schedule_version` | 所属计划及版本 |
| `scheduled_for` | 原计划执行时间 |
| `status` | `materializing`、`dispatched`、`completed`、`failed`、`skipped` |
| `task_id` | 产生的 Cloud Agent Task |
| `attempt/failure_code` | 基础设施尝试和稳定错误码 |
| `claimed_by/claim_expires_at` | Scheduler 领取租约 |
| 时间字段 | 创建、派发和终态时间 |

数据库唯一约束：

```text
(deployment_namespace, schedule_id, scheduled_for)
```

重启、重复领取、Broker 重投和网络超时必须复用同一个 `fire_id` 与 Task admission 幂等键。

### 4.3 ScheduleAuthorityBinding

后台计划不保存浏览器 Cookie、JWT、MCP 密钥或 Host Grant，只保存 principal、tenant、workspace、namespace、Host capability、Agent Definition、Policy、Skill/MCP 安装范围和版本摘要，以及授权版本、撤销状态和失败原因。

## 5. Task 模板

`task_template` 复用现有 `POST /tasks` 协议，包含：

- `prompt`、`title`、`workspace` 或 `workspace_source`；
- `model_profile`、`reasoning_effort`；
- `policy_profile`、`tool_profile`；
- `network_profile`、`network_allowlist`；
- `skill_components`；
- `mcp_allowlist`、资源、Prompt 及参数；
- `definition_id`、`definition_environment`；
- `max_model_calls`、`max_tool_calls`；
- `interaction_mode` 和输出交付配置。

每次 Firing 创建一个全新 Task，不向永久 Task 追加消息，以便独立呈现每次执行的状态、实时输出、成本、产物、失败和重试证据。

## 6. 触发规则与时间语义

### 6.1 MVP 支持

- `once`：指定本地日期和时间；
- `interval`：每 N 分钟、小时或天；
- `calendar.daily`：每天指定本地时间；
- `calendar.weekly`：指定星期和本地时间。

首版不开放原始 Cron 表达式。时间计算使用 Python 标准库 `zoneinfo`，数据库统一存 UTC。下一次执行时间从上一条 `scheduled_for` 推导，不能从 Task 完成时间推导。

夏令时重复时间只执行一次；不存在的本地时间顺延到下一个有效时间。API 返回下一次执行时间预览。

### 6.2 默认 Misfire 和 Overlap

| 场景 | 行为 |
|---|---|
| 服务停机错过多个周期 | `coalesce_one`，恢复后最多补一次 |
| 上一次 Task 未终态 | `forbid`，记录 `skipped_overlap` |
| 一次性计划错过 | grace window 内补执行，否则标记错过 |
| Firing 物化失败 | 有界基础设施重试，复用同一 `fire_id` |
| Task 业务执行失败 | 记录失败，不自动制造新 Firing |

未来可显式增加 `allow`、`skip`、`catch_up_bounded`，但不作为首版默认值。

## 7. 用户级授权

### 7.1 登录时一次授权

Trench 用户登录时一次性完成 `schedule.read`、`schedule.manage`、`agent.run` 和已有 Skill/MCP 管理与运行权限。创建、编辑和删除计划不在中途重复弹出授权。

### 7.2 后台运行

创建计划时生成范围受限、可撤销的 `ScheduleAuthorityBinding`。到期时重新检查：

- 用户、租户和工作区仍有效；
- 计划仍为 active；
- Agent Definition release 仍可用；
- Skill/MCP 安装、版本和凭证仍可用；
- 当前 Zebra Policy 仍允许所需能力；
- 资源和 namespace 没有漂移。

检查通过后，为本次 Task 生成正常 `TaskBindingSnapshot`。计划绑定不是永久 Task Grant，也不能绕开 Task 级能力交集。

### 7.3 无人值守安全边界

首版允许只读研究、报告生成和受治理 Artifact 发布。不可逆外部写入仍遵循 Policy/HITL：需要交互审批时 Task 进入 `WAITING_APPROVAL`，不得因为来自 Scheduler 而绕过审批。计划撤销立即阻止未来 Firing；已运行 Task 使用现有 cancel 语义。

## 8. Skill、MCP 和 Subagent

计划模板默认固定 Agent Definition release、Skill 精确版本、MCP catalog/config digest 和 Task template revision。用户修改配置时生成新 `schedule_version`，历史 Firing 保留原版本证据。

首版不默认跟随 Skill 最新版本。未来的“跟随最新版”必须是显式选项，并记录每次实际解析的版本。

定时 Task 进入现有 Worker 后可像普通 Task 一样使用 Skill/MCP、创建 Subagent 并实时输出正文；Scheduler 不感知执行细节。

## 9. PostgreSQL 与并发控制

新增表：`task_schedules`、`task_schedule_firings`、`schedule_authority_bindings`。

关键索引：

```text
task_schedules(deployment_namespace, status, next_fire_at, schedule_id)
task_schedule_firings(deployment_namespace, schedule_id, scheduled_for) UNIQUE
task_schedule_firings(deployment_namespace, status, claim_expires_at)
```

Scheduler 使用数据库时钟和短事务领取：

```sql
SELECT ...
FROM task_schedules
WHERE status = 'active' AND next_fire_at <= clock_timestamp()
ORDER BY next_fire_at, schedule_id
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

领取事务只创建 Firing、推进下一次时间并提交，不在持锁事务中创建 workspace、访问 Broker 或执行模型。

## 10. Firing 物化与 Task Admission

Firing materializer 必须复用现有 Task admission 应用服务，不通过 HTTP 回调本机 API，也不复制 `create_session` 逻辑：

1. 领取 `materializing` Firing；
2. 重新验证 Schedule Authority；
3. 将冻结模板转换为现有 Create Task payload；
4. 使用 `schedule-fire:{schedule_id}:{scheduled_for}` 稳定幂等键；
5. 调用共享 Task admission 服务；
6. 记录 `task_id` 和 `dispatched`；
7. 由现有 Transactional Outbox/RabbitMQ 唤醒 Worker。

如果 Firing 与 Task admission 暂时无法位于同一数据库事务，必须增加 materialization outbox/receipt 收口，禁止无证据双写。

## 11. API

```text
POST   /schedules
GET    /schedules
GET    /schedules/{schedule_id}
PATCH  /schedules/{schedule_id}
DELETE /schedules/{schedule_id}
POST   /schedules/{schedule_id}/pause
POST   /schedules/{schedule_id}/resume
POST   /schedules/{schedule_id}/run-now
GET    /schedules/{schedule_id}/runs
GET    /schedules/{schedule_id}/runs/{fire_id}
```

所有读写按 tenant/workspace/principal/namespace 过滤；更新携带 `schedule_version` 或 `If-Match`；删除为可审计软删除；`run-now` 也创建 Firing。运行详情只返回对应 Task 深链，不复制 Task 流和 Artifact 内容。

## 12. 进程与配置

新增独立 composition root：

```text
apps/scheduler/
zebra-agent-scheduler
```

完整云端进程包含 API、Scheduler、Worker 和现有 RabbitMQ relay/recovery。Scheduler poll interval 建议 1～5 秒，并配置 bounded batch size、claim TTL、misfire grace window、最大补跑 1 次、namespace allowlist 和 readiness 检查。Scheduler 可水平扩展，正确性不能依赖单实例。

## 13. 前端与 Trench 体验

Cloud Agent 控制台增加“定时任务”页面；Trench 启用“自动化”入口。

列表显示名称、状态、规则、时区、下次运行、上次结果、运行图标、最近错误、运行历史和 Task 深链；支持立即运行、暂停、恢复、编辑和删除。

编辑面板复用公共 Sender/TaskLaunchControls，配置 Prompt、模型、思考深度、Budget、Tool/Network Profile、Skill、MCP、时间规则、时区、下一次执行预览和输出方式。

每次运行显示“定时任务”来源徽标；正文沿用实时流式渲染，思考过程沿用任务结束后的折叠策略，产物沿用 Artifact 下载链路。

## 14. 可观测性与故障语义

日志、Trace 和指标必须包含 `schedule_id`、`fire_id`、`task_id`、deployment namespace，但不得记录 Prompt 全文、MCP 密钥、JWT、Cookie 或 Host Grant。

关键指标包括 active/paused 数、due lag、claim latency、materialization duration、dispatch latency、first-token、completion latency、misfire、overlap skip、authority reject、Outbox backlog 和 Broker publish latency。

| 故障点 | 必须保证 |
|---|---|
| Scheduler 提交前崩溃 | Lease 到期后可重新领取 |
| Firing 提交后崩溃 | 唯一约束阻止重复 Firing |
| Task admission 响应丢失 | 幂等键恢复同一 Task |
| RabbitMQ 不可用 | Outbox 保留，恢复后继续发布 |
| RabbitMQ 重复投递 | Consumer Inbox/command idempotency 去重 |
| Worker 崩溃 | 现有 Worker Lease 和 Event Store 恢复 |
| Skill/MCP 被停用 | 执行前 fail closed，保留明确错误码 |
| 用户或工作区停用 | 不创建新 Task，计划进入 actionable error |
| 计划修改 | 旧 Firing 保留旧版本，新 Firing 使用新版本 |

系统承诺至少一次领取和幂等物化，不承诺模型与任意外部系统的全局 exactly-once。

## 15. 实施阶段

1. **合同与治理**：新建实施卡并确认授权、时区、misfire、overlap 语义。
2. **Core**：Schedule、Trigger、Firing、Authority Binding 和 next-fire 纯函数测试。
3. **Storage**：前向 migration、Store、并发 claim、实际 PostgreSQL 双 Scheduler 测试。
4. **Admission/Scheduler**：共享 Task admission、materializer、`apps/scheduler`、崩溃恢复。
5. **API/权限**：CRUD、控制、历史、Host scope、tenant guard、运行前复核。
6. **前端**：Cloud Agent 页面、Trench 自动化入口、运行历史和 Task 深链。
7. **系统验收**：PostgreSQL/RabbitMQ 故障注入、真实 Trench 到期执行、流式输出和 Artifact。

## 16. 首版验收标准

1. 两个 Scheduler 不会重复创建同一执行；
2. Scheduler 在提交前后崩溃均可恢复；
3. RabbitMQ 不可用不会丢计划或 Task；
4. 停机跨过多个周期默认最多补一次；
5. 重叠任务默认不并发；
6. 暂停、撤销后不产生新 Task；
7. Skill/MCP/Definition/用户权限变化 fail closed；
8. 每次执行有独立 Task、实时正文、终态和产物；
9. 用户只能管理自己授权范围内的计划；
10. Trench 登录后不出现中途重复授权；
11. API、Scheduler、RabbitMQ、Worker、浏览器链路都有真实验收；
12. 部署证据与本地测试证据分开记录。

## 17. 非目标与升级条件

首版不做任意原始 Cron、Temporal、多区域时钟、无限补跑、以 Broker 代替数据库、永久 Task 聚合所有执行，或绕过 Policy/HITL 的外部写入。

只有出现大量跨天审批、复杂补偿、工作流版本迁移，或数万级高频计划对 DB Scheduler 形成已测量瓶颈后，再评估 Temporal Adapter。

## 18. 工作量估算

| 范围 | 估算 |
|---|---:|
| Core、Storage、Scheduler、API | 10～15 人日 |
| Cloud Agent 与 Trench 前端 | 4～6 人日 |
| 故障注入、部署、观测和系统验收 | 3～5 人日 |
| 合计 | 17～26 人日 |

估算不包含 Temporal、多区域和任意 Cron/RRULE。
