# Zebra Cloud Agent 与 Trench RabbitMQ 可靠投递与服务质量实施方案 v1.0

- 状态：Proposed
- 日期：2026-09-03
- 适用范围：Zebra Cloud Agent、Trench API、Trench AI Turn、Trench 订阅抓取
- 非目标：用 RabbitMQ 替换 PostgreSQL Event Store、业务数据库、Redis 实时流或所有现有队列

## 1. 背景

Trench 与 Zebra Cloud Agent 已具备持久化执行基础，但任务唤醒仍存在轮询、队列职责混杂和故障隔离不足的问题：

- Trench 已将 Turn、用户消息和 `trench_ai_turn_outbox` 同事务提交，并通过 PostgreSQL 租约领取任务；同时使用 ARQ 和 Redis Streams 承担抓取、处理和实时事件。
- Zebra Cloud Agent 已使用 PostgreSQL Event Store、Session Lease/Fence、Effect/Handoff Outbox 作为执行权威，但 Cloud Worker 仍会扫描最近 Session 寻找未处理的 `SessionCommand`。
- Redis 同时承担缓存、心跳、ARQ、数据流和实时输出，多类负载互相影响。
- Worker 崩溃、突发流量、毒消息、来源长期失败等场景需要更清晰的背压、隔离、死信和运维入口。

本方案引入 RabbitMQ，但将其限定为可靠任务投递与 Worker 唤醒平面。所有业务事实、执行状态、幂等、租约和最终结果继续由 PostgreSQL 保存。

## 2. 建设目标

### 2.1 服务质量目标

RabbitMQ 应解决：

1. API 提交后 Worker 拾取延迟过高。
2. 空闲 Worker 仍持续扫描数据库。
3. 突发任务缺少显式背压。
4. 某个来源或上游持续失败时拖累其他任务。
5. Worker 崩溃后任务恢复路径和死信观察不足。
6. Trench 和 Cloud Agent 的任务负载缺少基础设施隔离。

### 2.2 建议 SLO

正式数值应在阶段 0 完成基线测量后冻结。首版建议目标如下：

| 指标 | 建议目标 |
|---|---:|
| API 持久化并返回 `202` 的 p95 | 不高于 250ms |
| 数据库提交到 RabbitMQ confirm 的 p95 | 不高于 150ms |
| Worker 拾取延迟 p95 | 不高于 300ms |
| Worker 拾取延迟 p99 | 不高于 1s |
| Broker 故障期间任务丢失 | 0 |
| 重复消息导致重复业务副作用 | 0 |
| Poison message 可进入 DLQ | 100% |
| Broker 恢复后积压可自动收敛 | 100% |
| 跨用户、跨 Workspace 串任务 | 0 |

RabbitMQ 只改善排队、拾取、背压和失败隔离，不直接缩短模型推理、工具网络调用或 RSSHub 响应时间。

## 3. 架构原则

### 3.1 三层职责

```text
PostgreSQL
  业务事实、执行状态、租约、幂等、Outbox、Inbox
        |
        v
RabbitMQ
  任务唤醒、削峰、背压、消费者隔离、死信
        |
        v
Redis Streams / SSE
  浏览器实时事件、流式文本、短期缓存、心跳
```

### 3.2 核心语义

RabbitMQ 消息只表达：

> PostgreSQL 中已经持久化的任务现在可以被 Worker 检查和领取。

RabbitMQ 消息不表达：

> 消息本身是业务任务的唯一副本或最终状态。

因此消费者收到消息后必须重新从 PostgreSQL 加载权威记录，并校验 tenant、workspace、namespace、revision、lease/fence、取消状态和当前业务状态。

### 3.3 投递保证

- 使用 at-least-once，不宣称 exactly-once。
- Producer 使用 Transactional Outbox 消除数据库与 Broker 双写窗口。
- Relay 收到 publisher confirm 后才更新发布状态。
- Consumer 使用 Inbox、业务幂等键、revision 和 Lease/Fence 防止重复副作用。
- RabbitMQ 不可用时 API 仍可持久化任务，任务安全停留在 `queued`。
- 数据库恢复扫描器始终保留，RabbitMQ 不成为新的单点。

## 4. 目标拓扑

```text
                  +---------------------+
Browser --------->| Trench API          |
                  +----------+----------+
                             | 单事务
                  +----------v----------+
                  | PostgreSQL          |
                  | Turn/Event/Command  |
                  | Outbox/Inbox/Lease  |
                  +----------+----------+
                             | Relay
                  +----------v----------+
                  | RabbitMQ            |
                  | Command Wake-up     |
                  | Retry/DLQ           |
                  +----------+----------+
                             |
           +-----------------+-----------------+
           v                                   v
+----------------------+           +----------------------+
| Trench Worker        |           | Zebra Cloud Worker   |
| claim Turn/source    |           | claim Session Lease  |
+----------+-----------+           +----------+-----------+
           |                                  |
           +---------------+------------------+
                           v
                  PostgreSQL 持久化结果
                           |
                           v
                   Redis Streams / SSE
                           |
                           v
                        Browser
```

## 5. RabbitMQ 部署与隔离

使用一个 RabbitMQ 集群、两个 vhost，按系统隔离权限、策略、配额和故障域：

### 5.1 `/trench`

- Exchange：`trench.command.x`
- 类型：topic
- durable：true

| Queue | Routing key | 用途 | 阶段 |
|---|---|---|---|
| `trench.ai.turn.ready.q` | `ai.turn.ready.v1` | AI Turn 唤醒 | 第一阶段 |
| `trench.source.fetch.q` | `source.fetch.ready.v1` | 订阅源抓取 | 第二阶段 |
| `trench.ai.turn.dlq` | DLX | 非法或不可恢复的 Turn 消息 | 第一阶段 |
| `trench.source.fetch.dlq` | DLX | 永久失败抓取 | 第二阶段 |
| `trench.document.normalize.q` | `document.normalize.ready.v1` | 文档规范化 | 暂缓 |
| `trench.event.archive.q` | `event.archive.ready.v1` | 事件归档 | 暂缓 |

### 5.2 `/zebra`

- Exchange：`zebra.command.x`
- 类型：topic
- durable：true

| Queue | Routing key | 用途 | 阶段 |
|---|---|---|---|
| `zebra.session.command.ready.q` | `session.command.ready.v1` | SessionCommand 唤醒 | 第一阶段 |
| `zebra.session.command.dlq` | DLX | 非法或不可恢复命令 | 第一阶段 |
| `zebra.effect.wakeup.q` | `effect.ready.v1` | Effect Dispatcher 唤醒 | 后续评估 |

### 5.3 队列策略

- durable exchange。
- durable quorum queue。
- persistent message。
- publisher confirm。
- manual ack。
- 根据 Worker 类型设置 prefetch。
- 每个 vhost 使用独立服务账号和最小权限。
- 禁止远程 `guest`。
- 不依赖 delayed-message 插件；业务重试时间由 PostgreSQL `available_at` 控制。
- 对必须完成的业务命令不设置统一短 TTL；只对明确可过期的瞬时 wake-up 设置过期时间。

## 6. 统一消息协议

Trench 与 Zebra 使用相同 envelope 语义，但各自在本仓库维护类型和校验，第一期不创建新的共享仓库。

```json
{
  "message_id": "uuid",
  "message_type": "trench.ai.turn.ready",
  "schema_version": 1,
  "aggregate_id": "turn_id/session_id/source_id",
  "tenant_id": "tenant-id",
  "workspace_id": "workspace-id",
  "deployment_namespace": "cloud-agent-trench",
  "idempotency_key": "stable-business-key",
  "correlation_id": "request-or-run-id",
  "causation_id": "parent-event-id",
  "occurred_at": "RFC3339 timestamp",
  "traceparent": "W3C trace context",
  "payload_ref": {
    "store": "postgres",
    "table": "trench_ai_turns",
    "id": "turn-id"
  }
}
```

消息中禁止放入：

- 浏览器 Cookie。
- Host Grant。
- X/Twitter `auth_token`。
- API Key 或其他密钥。
- 模型完整上下文。
- 大段正文和文件内容。
- MinIO 临时签名 URL。

## 7. 数据模型

### 7.1 Broker Outbox

Trench 现有 `trench_ai_turn_outbox.status = published` 表示执行生命周期完成，不能复用为 RabbitMQ 发布状态。两个系统都应增加职责单一的 Broker Outbox。

```text
broker_outbox
- message_id PK
- message_type
- schema_version
- aggregate_type
- aggregate_id
- tenant_id
- workspace_id
- deployment_namespace
- envelope_json
- status: pending | publishing | published | dead
- available_at
- publish_attempts
- lease_owner
- lease_expires_at
- published_at
- last_error
- created_at
```

约束：

- `(message_type, aggregate_id, schema_version)` 唯一。
- 与 Turn、SessionCommand 或 Source Fetch 状态在同一事务插入。
- Relay 通过 `FOR UPDATE SKIP LOCKED` 领取。
- publisher confirm 后才标记 `published`。
- Relay 在 confirm 后、更新数据库前崩溃时允许重复发布。

### 7.2 Consumer Inbox

```text
broker_inbox
- consumer_name
- message_id
- message_type
- aggregate_id
- tenant_id
- workspace_id
- received_at
- processed_at
- outcome
- last_error

PK (consumer_name, message_id)
```

Inbox 用于传输去重、重复投递审计和 DLQ 重放记录。业务副作用仍需依赖业务幂等键、aggregate revision、Lease/Fence 和 Effect Ledger。

## 8. Trench AI Turn 方案

### 8.1 写入路径

```text
POST /turns
  -> PostgreSQL transaction
       -> INSERT trench_ai_turns
       -> INSERT user message
       -> INSERT trench_ai_turn_outbox
       -> INSERT broker_outbox
  -> COMMIT
  -> 返回 202 + turn_id
```

RabbitMQ 不可用时：

- API 仍返回 `202`。
- Turn 保持 `queued`。
- Broker Outbox 保持 `pending`。
- Relay 恢复后自动补发。
- 前端通过 snapshot 显示“排队中”，不能将 Broker 故障直接显示为 `Zebra Cloud Agent is unavailable`。

### 8.2 Relay

Relay 是独立进程或独立 Worker 角色：

1. 批量 claim `pending` Outbox。
2. 发布 persistent message。
3. 等待 publisher confirm。
4. 标记 `published` 或记录下一次重试时间。
5. 暴露 outbox lag、publish latency 和 publish failure 指标。

Relay 不在每个 API 请求中同步运行，Broker 连接使用长连接和有限 channel pool。

### 8.3 Consumer

```text
收到 turn_id
  -> 校验 envelope
  -> Inbox 去重
  -> claim_turn_by_id(turn_id)
  -> 建立 PostgreSQL 执行租约
  -> 将本地执行任务交给受控 executor
  -> ACK Rabbit 消息
  -> 提交 Zebra 并跟踪 durable events
```

单次 Agent 运行可能持续数分钟，因此 Rabbit 消息不应在整个执行期间保持 unacked。ACK 条件是 PostgreSQL 租约已建立，并且本地执行任务已成功调度。

如果进程在 ACK 后崩溃：

1. PostgreSQL 租约到期。
2. Recovery Sweeper 找到过期 Turn。
3. 生成幂等 Broker Outbox wake-up。
4. 其他 Worker 重新领取并从保存的 Zebra cursor 恢复。

### 8.4 降级路径

- Broker 正常：Rabbit Consumer 是主路径。
- Broker 故障：低频 PostgreSQL fallback sweeper 领取超时任务。
- Broker 恢复：自动回到 Rabbit 主路径。
- 双路径同时触发时，由 PostgreSQL Lease 保证只有一个执行者。

## 9. Zebra SessionCommand 方案

### 9.1 API 事务

Zebra 接受 SessionCommand 时在同一 PostgreSQL 事务中写入：

```text
SESSION_COMMAND_ACCEPTED Event
Session projection
broker_outbox(session.command.ready.v1)
```

禁止先提交 Event 再直接 publish RabbitMQ，否则会留下数据库已有命令、Broker 无消息的双写窗口。

### 9.2 Worker 消费

消息只携带：

- `session_id`
- `command_id`
- `expected_revision`
- `tenant_id`
- `workspace_id`
- `deployment_namespace`

Worker 收到后：

1. 从 Event Store 重新读取对应命令。
2. 校验消息与权威 Event 的 tenant、namespace 和 command identity。
3. 确认命令尚未投影或执行。
4. 获取 Session Lease/Fence。
5. 按 Event sequence 执行命令。
6. 将结果继续写入 PostgreSQL Event Store。
7. 提交后才通过 Redis 实时发布。

不依赖 RabbitMQ 的消息顺序；Session Event sequence 和 revision 是最终顺序。RUN、MESSAGE、CANCEL 不拆到不同优先级队列，避免同一 Session 命令乱序。

### 9.3 扫描器调整

- 正常路径不再扫描大量 recent sessions。
- 保留低频 Recovery Scanner。
- Scanner 只处理超过阈值仍未执行的命令。
- 本地 SQLite 模式保持现有行为，不强制依赖 RabbitMQ。

## 10. Trench 订阅源抓取方案

第二阶段迁移订阅源抓取，不先迁移 normalize/archive 数据流水线。

### 10.1 Source Fetch 命令

```json
{
  "message_type": "trench.source.fetch.ready",
  "aggregate_id": "source_id",
  "tenant_id": "tenant-id",
  "workspace_id": "workspace-id",
  "idempotency_key": "source_id:schedule_window",
  "payload_ref": {
    "scheduled_at": "RFC3339 timestamp",
    "reason": "periodic|manual|retry"
  }
}
```

### 10.2 Worker 路由

按能力隔离 Worker，不按用户建立队列：

```text
source.fetch.rss.v1
source.fetch.rsshub.v1
source.fetch.web.v1
source.fetch.social.v1
```

X/Twitter 或其他社交平台抓取失败时，不占满普通 RSS Worker。

### 10.3 来源状态机

来源状态继续保存在 PostgreSQL：

- `next_fetch_at`
- `last_success_at`
- `consecutive_failures`
- `backoff_until`
- `active_fetch_lease`
- `configuration_required`
- `last_error_code`

缺少 `RSSHUB_TWITTER_AUTH_TOKEN` 等配置时：

1. 不无限重试。
2. 来源进入 `configuration_required`。
3. 消息 ACK。
4. 生成面向用户的明确配置提示。
5. 配置完成后再重新入队。

## 11. 暂不迁移的内容

第一阶段明确不做：

- 不替换 PostgreSQL Event Store。
- 不替换 Trench Turn Store。
- 不替换 Effect、Handoff、Artifact Outbox。
- 不用 RabbitMQ 保存 Token 流或浏览器 SSE。
- 不用 RabbitMQ 储存订阅文章正文。
- 不一次性迁移全部 Redis Streams 和 ARQ 队列。
- 不把 Agent 每次 tool call 拆成独立 Rabbit 消息。
- 不通过 RabbitMQ 传递用户凭证。
- 不为每个租户创建 vhost 或队列。

Trench 的 raw/events/documents 流水线只有在补齐“原始内容先持久化，再由 Outbox 发布”的边界后才能评估迁移。直接搬到 RabbitMQ 只会把 Redis 双写问题变成 RabbitMQ 双写问题。

## 12. 重试与死信

### 12.1 可重试错误

- Broker 连接中断。
- Zebra 暂时不可用。
- 上游 429、502、503。
- 网络超时。
- Worker 临时失去 Lease。
- 数据库连接短暂失败。

处理方式：数据库记录 `available_at`，采用指数退避和随机抖动，再生成或激活幂等 wake-up Outbox。业务重试不依赖无限 `nack/requeue`。

### 12.2 不可重试错误

- schema version 不支持。
- tenant/workspace/namespace 不匹配。
- 消息格式非法。
- 来源已永久删除。
- 必需配置缺失。
- 请求违反业务约束。

处理方式：记录 Inbox outcome，进入 DLQ 或业务终态，不无限重投。

### 12.3 DLQ 重放

- 保留 `message_id`、错误代码、aggregate 引用和 correlation/causation。
- 不保存用户正文和凭证。
- 重放生成新的 delivery attempt，但保留原始关联关系。
- 运维入口支持 inspect、retry、discard，并记录操作人和时间。

## 13. 多用户与安全

vhost 只隔离 Trench 和 Zebra，不作为用户隔离边界。用户隔离继续由业务主键保证：

- Trench：`user_id + workspace_id + conversation_key`。
- Zebra：`tenant_id + deployment_namespace + workspace/session`。

Consumer 必须从数据库重新加载并比对，不能信任 Rabbit 消息中的 tenant 字段。日志、指标和 DLQ 不得包含 Cookie、Grant、社媒凭证或用户正文。

生产要求：

- TLS。
- 独立服务账号和最小权限。
- Secret Manager 或等价密钥注入。
- 限制连接数、channel 数和最大消息体。
- Broker 管理端口不公开暴露。

## 14. 可观测性

### 14.1 RabbitMQ 指标

- ready messages。
- unacked messages。
- oldest message age。
- publish confirm latency/failure。
- consumer count。
- redelivery count。
- DLQ depth。
- connection/channel count。
- memory/disk alarm。

### 14.2 业务指标

Trench：

- Turn Outbox lag。
- Turn pickup latency。
- queued/dispatching/running 数量。
- 来源抓取等待时间和失败率。
- `configuration_required` 数量。

Zebra：

- SessionCommand pickup latency。
- 未执行 command age。
- Session Lease conflict。
- Worker execution duration。
- Effect pending/uncertain。
- fallback scanner 命中次数。

统一传播 `traceparent`、`correlation_id`、`causation_id`、`turn_id`、`run_id`、`session_id` 和 `command_id`。用户正文不得作为指标标签。

## 15. Feature Flag、灰度与回滚

### 15.1 Feature Flag

```text
TRENCH_RABBIT_PUBLISH_ENABLED
TRENCH_RABBIT_CONSUME_ENABLED
TRENCH_DB_POLL_FALLBACK_ENABLED

ZEBRA_RABBIT_PUBLISH_ENABLED
ZEBRA_RABBIT_CONSUME_ENABLED
ZEBRA_COMMAND_SCAN_FALLBACK_ENABLED
```

### 15.2 灰度顺序

1. 只部署 RabbitMQ，不接业务流量。
2. 开启 shadow publish，Relay 发布但无业务消费者。
3. 核对 Broker 消息数与数据库 Outbox。
4. 开启 shadow consumer，只校验消息和数据库，不执行。
5. 开启测试 Workspace 正式消费。
6. 扩到内部账号。
7. 全量开启 Rabbit 消费。
8. 降低数据库正常扫描频率。
9. 最后才考虑关闭旧的正常调度路径。

### 15.3 回滚

1. 关闭 consume flag。
2. 保留数据库 Outbox 和 Rabbit 队列。
3. 恢复 DB fallback scanner。
4. 不回滚业务数据，不清空队列。
5. 修复后通过 Inbox、Outbox 和 DLQ 对账，再恢复消费。

## 16. 实施阶段与任务

所有任务控制在单人 2 至 8 小时；估算已预留约 25% 不确定性缓冲。

### 阶段 0：基线与 ADR，2 至 3 天

| 任务 | 工时 | 完成标准 |
|---|---:|---|
| 记录 Trench Turn 拾取 p95/p99 | 4h | 有可复现压测结果 |
| 记录 Zebra command 扫描成本 | 4h | 有查询次数、延迟和会话规模数据 |
| 冻结权威边界和非目标 | 4h | 两个仓库 ADR 完成 |
| 定义 envelope v1 | 4h | JSON Schema 与兼容规则完成 |
| 定义 SLO、告警和回滚门槛 | 4h | 验收文档完成 |

### 阶段 1：RabbitMQ 基础设施，3 至 5 天

| 任务 | 工时 | 完成标准 |
|---|---:|---|
| 本地 Compose RabbitMQ | 4h | 健康检查通过 |
| 创建 vhost、用户和权限 | 4h | 跨 vhost 访问被拒绝 |
| 声明 exchange、queue 和 DLX | 4h | 重启后拓扑保留 |
| Python 长连接和 publisher confirm | 8h | 断线重连测试通过 |
| Consumer manual ack 和 prefetch | 8h | 重投与背压测试通过 |
| Prometheus/Grafana 指标 | 8h | 队列、lag 和 DLQ 可观察 |

### 阶段 2：Trench AI Turn，5 至 8 天

| 任务 | 工时 | 完成标准 |
|---|---:|---|
| Broker Outbox/Inbox migration | 8h | 升降级测试通过 |
| `create_turn` 同事务写 Broker Outbox | 4h | 注入回滚时零残留 |
| Outbox Relay | 8h | confirm 后才标记 published |
| `claim_turn_by_id` | 4h | 重复领取只成功一次 |
| Rabbit Turn Consumer | 8h | 多 Worker 无重复执行 |
| Lease expiry sweeper | 8h | ACK 后崩溃可恢复 |
| Feature Flags | 4h | 可无损切回 DB poll |
| 集成测试与故障注入 | 8h | 断 Broker/Worker 均不丢 Turn |

### 阶段 3：Zebra SessionCommand，5 至 8 天

| 任务 | 工时 | 完成标准 |
|---|---:|---|
| Zebra Broker Port | 4h | `agent-core` 不依赖 RabbitMQ |
| PostgreSQL Broker Outbox/Inbox | 8h | tenant/namespace 约束完成 |
| Command accept 同事务写 Outbox | 8h | Event 与 Outbox 原子 |
| Zebra Relay | 8h | confirm 和重复发布测试通过 |
| Rabbit Command Consumer | 8h | 从 Event Store 重新加载命令 |
| 调整 recent-session 正常扫描 | 4h | 正常流量不再依赖全量扫描 |
| 保留 Recovery Scanner | 4h | Broker 故障仍可恢复 |
| Cloud Agent 跨服务 E2E | 8h | Trench 到 Zebra 到工具到回复闭环 |

### 阶段 4：Trench 来源抓取，5 至 8 天

| 任务 | 工时 | 完成标准 |
|---|---:|---|
| Source Fetch command | 4h | 幂等窗口明确 |
| 调度器同事务写 Outbox | 8h | 无 DB/Broker 双写窗口 |
| RSS/RSSHub/Web/Social 路由 | 8h | Worker 隔离有效 |
| 来源级 Lease 和限流 | 8h | 同一来源不并发抓取 |
| 配置缺失状态机 | 4h | 缺 Token 时停止无限重试 |
| DLQ 和人工重放 | 8h | 可 inspect/replay/discard |
| 抓取 E2E | 8h | 新内容进入历史和时间线 |

### 阶段 5：生产硬化，3 至 5 天

- Broker 宕机。
- Relay 在 confirm 前后崩溃。
- Consumer 在 ACK 前后崩溃。
- 重复消息和乱序消息。
- Poison message。
- PostgreSQL 或 Redis 短暂不可用。
- 单个社媒来源持续超时。
- 双 Worker 抢同一 Turn。
- 跨用户伪造 envelope。
- DLQ 重放和大规模积压收敛。

## 17. 依赖与工期

```text
基线与 ADR
    |
RabbitMQ 基础设施
    |
Envelope + Outbox/Inbox
    +-------------------+
    |                   |
Trench AI Turn     Zebra SessionCommand
    |                   |
    +---------+---------+
              |
         跨服务 E2E
              |
       Trench 来源抓取
              |
         故障演练上线
```

- 单人完成全部阶段：约 5 至 7 周。
- 两名工程师在基础设施完成后并行：约 3 至 4 周。
- 只完成 Trench Turn 和 Zebra SessionCommand：约 2 至 3 周。

## 18. 最终验收清单

1. 用户提交消息后立即关闭浏览器，任务继续执行。
2. API 提交时 RabbitMQ 已停止，Turn 仍进入 queued；恢复后自动执行。
3. Relay 发布成功但更新 Outbox 前崩溃，重复消息不导致重复 Turn。
4. Consumer ACK 后立即崩溃，租约到期后其他 Worker 接管。
5. 同一会话重复提交相同 request ID，只产生一个 Turn。
6. 两个用户同时操作时，消息、文件、订阅源和 Session 不串。
7. Zebra Worker 重启后从 PostgreSQL Event Store 恢复。
8. Redis 停止时任务仍能完成；恢复后浏览器通过 durable replay 收敛。
9. X 来源缺认证配置时显示明确配置提示，不进入无限重试。
10. DLQ 消息可以安全检查和重放。
11. 前端实时事件仍通过 Redis/SSE，RabbitMQ 不介入 Token 推送。
12. 关闭 Rabbit Feature Flag 后可退回数据库恢复扫描。

## 19. 实施决策

实施顺序冻结为：

1. 建立基础设施、Envelope、Broker Outbox 和 Inbox。
2. 先接入 Trench AI Turn，直接改善回复任务拾取延迟。
3. 再接入 Zebra SessionCommand，消除 Cloud Worker 正常路径的会话扫描。
4. 完成真实 Trench 到 Zebra 跨服务验收。
5. 再迁移 Trench 订阅源抓取。
6. normalize/archive 等主数据流水线必须单独评审，不随本方案自动迁移。

在任何阶段，PostgreSQL 都是唯一业务事实源，RabbitMQ 都只是可恢复的投递与唤醒平面。
