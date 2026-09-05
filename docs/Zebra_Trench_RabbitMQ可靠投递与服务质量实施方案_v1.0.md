# Zebra Cloud Agent 与 Trench RabbitMQ 可靠投递与服务质量实施方案 v1.1

- 状态：Reviewed design；实现与上线尚未验收
- 日期：2026-09-04；原文件名保留以兼容既有引用
- 范围：Zebra Cloud Agent、Trench AI Turn、订阅抓取调度
- 本轮修订依据：[缺口核验与验收](RabbitMQ可靠投递缺口核验与验收.md)
- 本方案不表示 RabbitMQ 已接入。各阶段必须提交自己的代码、基线和故障测试证据。

## 1. 目标与非目标

PostgreSQL 是任务、事件、租约、幂等、Outbox/Inbox、结果的唯一权威。
RabbitMQ 只通知 Worker：数据库中已有工作可以检查；它不是任务唯一副本。
Redis Streams/SSE 保留实时输出；SQLite 本地模式不强制加载 RabbitMQ。

解决任务拾取、空转扫描、突发背压、失败隔离和恢复可观察性。
不承诺加速模型推理、工具网络或 RSSHub；不承诺 exactly-once 外部副作用。
不迁移每次 Tool Call，不传正文、文件、Cookie、Host Grant、密钥或签名下载 URL。
不替换 Effect/Handoff/Artifact Outbox，不把 normalize/archive 随调度迁移。

## 2. 已核实的基础与前置修复

Trench 已在 create_turn 同事务写 Turn、消息和执行 Outbox。
执行 Outbox 的 published 表示执行完成，必须与 Broker 发布状态分表。
当前 claim_next 有行锁，但 renew_lease、部分投影/完成写回仅在应用层检查 owner；
接入多消费者前须统一条件写入及 fence，不能把既有租约视作已完成的并发证明。

Zebra 的 SessionCommandConsumer 扫描 recent sessions 的有限窗口；
低频沿用同一窗口不能保证旧任务最终被发现，恢复索引必须独立于 recency。
ADR-023 的 expected_revision 是 admission CAS，不是消费时 current_revision 等值门槛；
命令进入 Event Store 后 revision 必然推进，消费者不得因此拒绝合法命令。
ADR-024 的提交后实时发布保持不变，Rabbit 可靠唤醒与实时发布是两个合同。

Trench managed RSS 当前以 SourceRow 为抓取对象、Redis cursor 限定调度间隔，
抓取结果 push_raw 后才记录成功；不可假设已存在用户级 durable FetchCommand，
也不可承诺 Redis 宕机时来源流水线继续完成。

## 3. 权威与确认边界

| 边界 | 可确认的事实 | 不能推断 |
|---|---|---|
| PostgreSQL commit | 任务与唤醒意图持久化 | 已被 Rabbit 接受 |
| mandatory publish 成功且 confirm ACK、无 return | Broker 接受并至少路由到队列 | 已执行、进入了正确业务队列 |
| Inbox + 执行租约事务提交 | 本次交接可恢复 | 模型或外部写入已成功 |
| Consumer ACK | 传输消息可删除 | 业务已终结 |
| 业务结果事务提交 | 结果、游标和状态持久化 | 浏览器收到实时事件 |

Broker 不可用时，在数据库及准入依赖健康、配额允许的前提下仍可返回 202。
DB 不可用、身份无效、权限撤销或容量拒绝不能伪装成 202。
前端显示 queued/running/retrying/configuration_required/failed 等实际状态；
Broker 故障不得统一伪装成 Zebra Cloud Agent is unavailable。

## 4. 部署与拓扑

单集群两个 vhost：/trench 与 /zebra。它们是权限/策略隔离，不是独立硬件故障域。
生产按至少三个节点、跨故障域部署 quorum 副本；单机 Compose 只验证开发功能，
不能以单机重启宣称生产高可用。固定受支持镜像版本和 digest，记录升级兼容测试。

| vhost | durable topic exchange | durable quorum queue | 唯一业务 binding |
|---|---|---|---|
| /trench | trench.command.x | trench.ai.turn.ready.q | ai.turn.ready.v1 |
| /zebra | zebra.command.x | zebra.session.command.ready.q | session.command.ready.v1 |
| /trench | trench.command.x | trench.source.fetch.rss.q | source.fetch.rss.v1 |
| /trench | trench.command.x | trench.source.fetch.rsshub.q | source.fetch.rsshub.v1 |
| /trench | trench.command.x | trench.source.fetch.web.q | source.fetch.web.v1 |
| /trench | trench.command.x | trench.source.fetch.social.q | source.fetch.social.v1 |

来源四队列在来源阶段才启用。不保留同时匹配的 source.fetch.ready.q，以免复制执行。
分类由数据库中解析后的能力确定；X 经 RSSHub 抓取也应归 social 隔离。
每个 vhost 声明自己的 command.dlx；每个 ready 队列绑定一个显式命名的对应 dlq。
禁止隐式通配绑定；部署验收检查 vhost/exchange/binding/queue 完整映射。

共同配置：

- persistent 消息、manual ACK、publisher confirms、mandatory=true；
- DLX、DLQ durable，源 quorum queue 显式 at-least-once dead-lettering、
  overflow=reject-publish、delivery-limit、max-length-bytes；
- DLQ 同样设置容量与告警，目标不可达须监控源队列滞留，不能静默 drop-head；
- 不依赖 delayed-message 插件；延迟由 PostgreSQL available_at 控制；
- 不设置统一短消息 TTL；若未来开启过期唤醒，必须先证明 DB 能重建；
- TLS、独立 provisioner/relay/consumer 账号、最小权限、连接/channel 限制；
- 开发端口仅绑定 127.0.0.1，管理端口不公网暴露，禁远程 guest；
- vhost 配额不能隔离全节点 disk/memory alarm，需集群容量告警与 fallback。

## 5. Envelope v1 与身份

两仓库各自维护严格类型，使用同一版本 JSON Schema 和相同正反例做 CI 一致性检查。
无新共享仓库；不把 AMQP 类型引入 agent-core。

```json
{
  "message_id": "uuid",
  "message_type": "trench.ai.turn.ready",
  "schema_version": 1,
  "deployment_namespace": "cloud-agent-trench",
  "scope": {"kind": "principal", "tenant_id": "tenant", "workspace_id": "workspace"},
  "aggregate_id": "turn-id",
  "operation_id": "turn-id",
  "wake_generation": 0,
  "idempotency_key": "stable-business-key",
  "correlation_id": "request-id",
  "causation_id": null,
  "occurred_at": "2026-09-04T00:00:00Z",
  "traceparent": null,
  "payload_ref": {"kind": "trench_turn", "id": "turn-id"}
}
```

三个标识不可混用：

- aggregate_id：Turn / Session / Source 对象标识，同一对象可以有多次业务操作。
- operation_id：Turn ID / command_id / fetch_command_id，业务重试始终不变。
- message_id：一次持久化唤醒记录；物理重发不变，新一代恢复唤醒必须改变。
- wake_generation：该 operation 在 DB 原子递增的唤醒代数，从 0 开始；
  transport publish_attempts、业务 attempt_count、execution fence 分别计数。

payload_ref.kind 是固定枚举 trench_turn、zebra_command、source_fetch_command；
id 必须等于 operation_id。数据库表映射仅在代码白名单中，不接受任意表名、SQL、URL。
Zebra aggregate_id=session_id，另携带 accepted_event_id/accepted_sequence，
expected_revision 可作诊断但不可替代 accepted Event。Source 引用真实 FetchCommand，
scheduled_at/reason 保存在 DB，不再用不兼容的自由形状 payload_ref。

限制 UTF-8 JSON 为 16 KiB、字符串长度、嵌套深度；拒绝未知字段、不支持的版本、
重复 JSON key、负 generation、非整数版本和不合法日期；traceparent 可空并限长。
旧消费者未知版本进入有告警的隔离状态，不盲重试；先部署兼容消费者再发新版本。
本文包含 null、UUID 等类型规则，阶段 0 必须产出可执行 Schema，不仅复制示例。

scope 是判别联合，不能用空字符串或缺少 tenant 来自动退化为公共来源：

- principal：Trench user 映射为既有权威 tenant/user/workspace；Zebra 使用已验证 namespace。
- shared_source：仅限数据库明确标记的公共来源，以受控 service scope 执行；
  不代表用户有内容访问权，读取仍经用户订阅/历史权限过滤。
- 私有或凭证相关来源必须分开 fetch_scope/credential_binding；消息只有不透明引用，
  不共享凭证、原文、结果、DLQ 或缓存。未证明身份模型前不得迁移来源队列。

消息不构成授权。消费者验证权威记录的 scope、namespace、aggregate、operation、
当前权限/取消/删除状态及同 ID 指纹；取到别人的记录也不得执行或暴露其字段。
发生 scope mismatch 只隔离这条消息，不能把真实受害者任务改成 failed。

## 6. Outbox、Inbox 与事务

Broker Outbox：message_id、scope_key、message_type/schema_version、aggregate_id、
operation_id、wake_generation、envelope_json/digest、status、available_at、
publish_attempts、relay_owner、relay_fence、lease_expires_at、published_at、
last_error_code、created_at。scope_key 由 DB 权威 scope 规范化生成，NOT NULL。

唯一约束：
`(deployment_namespace, scope_key, message_type, operation_id, wake_generation)`。
schema_version 不是业务去重维度；同一代消息不可通过换版本再次发送新意图。
同唯一键不同 digest 拒绝并审计；同键同内容返回原记录。

事务规则：

1. API admission：业务实体、幂等记录、必要 projection、执行 Outbox、Broker Outbox 同事务；
   duplicate 返回原结果，不增加 generation；回滚零残留。
2. 恢复/重试：锁权威 operation，验证非终态、到期、旧 fence 和当前 generation，
   同事务递增 generation、写新 message_id 和 available_at；并发 sweeper 只能生成一次。
3. Relay：短事务 SKIP LOCKED 领取到期 pending 或过期 publishing，增加 relay_fence；
   提交后执行网络 I/O；不得跨网络等待持有 DB 行锁。
4. 发布后只用 owner+relay_fence+status 条件更新；旧 relay 的迟到 ACK 不能覆盖新租约。
   ACK+无 return 才 published；NACK、return、断线、超时均不能标成功。
5. confirm 丢失或确认后 DB 更新失败：同 message_id 重发，禁止重新创建业务操作。

Inbox 唯一键：
`(deployment_namespace, consumer_role, message_id)`，consumer_role 是稳定业务角色，
不是随机 Pod ID。存 scope_key、operation/generation、digest、outcome、processed_at。
同 message_id 不同 digest 作为冲突隔离，不能当成功重复。
Inbox 的 accepted 表示 durable handoff，不表示 completed；真正结果在业务表。

有容量时，Inbox 判重、DB 权威校验、领取租约/增加 fence、handoff 结果同事务。
严禁先独立提交 processed Inbox，再尝试领取任务。
重复 accepted 可 ACK：原租约/恢复记录仍持久存在；不得把重复消息启动为新执行。

## 7. Consumer、执行与背压

消费者先获得有界执行槽，再领取任务；prefetch 限制未 ACK 消息，
不能限制已 ACK 的长任务。执行槽在业务运行期间持有，lease heartbeat 不与执行槽争抢。
本地 executor 不接受无限队列；停机先停止新消费，再 drain，最后条件释放租约。

持久交接后调度执行成功再 ACK；调度失败须事务释放/延后任务并生成后继唤醒后才 ACK。
交接 commit 后至调度/ACK 任一点崩溃，由到期租约恢复，不要求内存调度与 DB 原子。
ACK 丢失允许 redelivery，Inbox+fence 处理；不根据 redelivered 布尔位跳过业务校验。

| 接收情况 | 动作 |
|---|---|
| DB 故障/无容量 | 不先提交 Inbox；暂停/退避消费，允许有限重投，避免 nack 热循环 |
| 合法任务已终结/取消/删除 | 记录 no-op 后 ACK，不进入无限 DLQ |
| 当前租约有效且忙 | 确认已有恢复责任，记录 busy/no-op，ACK；后续由 owner/sweeper 处理 |
| available_at 未到 | 保留 DB due 状态，记录 deferred 后 ACK；到期扫描负责新 generation |
| 合法消息但业务可重试失败 | DB 写 retry_at 和后继唤醒后结束本次交接 |
| 格式/版本/身份冲突 | 安全隔离并告警，不改其他 scope 的业务任务 |

公平性需按租户限制 active/queued 数与全局 executor 容量，来源按平台/凭证配额。
数据库 Outbox 积压也须限额；Broker 宕机不等于允许无限 202。
准入达到配额返回明确 429/503；已接收任务仍须可查询和恢复。
锁顺序统一，所有 retry_at/lease 时间以数据库时间为准，禁止依赖 Worker 本地时钟。

## 8. 租约、恢复、取消与副作用

Trench claim-by-id 与 claim-next 共用领取实现。续约、游标投影、完成、失败、释放均校验
owner+execution_fence+未过期 lease+预期状态，并以行锁或条件 UPDATE 原子提交。
旧 Worker 不能在接管后补写；到期后禁止原 fence “复活”，需重新领取。
Zebra 复用现有 Session Lease/Fence 和 Effect 权威，不增加第二套执行锁。

恢复查询使用可索引的 due/unhandled/expired 状态，按时间+稳定 ID 分页；
覆盖从未发布、published 但没被接收、ACK 后崩溃、租约过期、due retry。
不能只扫描 recent sessions 或只扫描 pending broker_outbox。
已发布消息超过阈值未交接可以重建下一代；DB 锁合并并发恢复并有退避，避免消息风暴。

BUSINESS cancelled、deleted、permission_revoked 都在执行前及敏感副作用前重新检查。
旧消息/DLQ 重放不能复活任务。控制命令必须及时进入已有控制机制；
RUN 长任务不得占满控制接收能力，CANCEL 不等待目标 RUN 结束才处理。
不靠 Rabbit FIFO 或 priority 代替 Event sequence；明确命令接收/处理游标，
不能仅因 session projection.current_sequence 前进就认定所有命令已处理。

Trench→Zebra 提交时先持久化稳定 command/run 关联。超时重试复用相同业务幂等键；
Zebra 已接受而 Trench 未记录 receipt 时先查询/重试同一意图，不创建第二次运行。
恢复使用保存的 durable cursor，禁止重跑已完成工具来“恢复文本”。

外部副作用已成功但 receipt 丢失属于 uncertain：依赖既有 Effect Ledger 和上游幂等键/
查询对账；不支持幂等或查证的操作进入人工确认，不自动宣称零重复。
数据库事务或 Rabbit 本身不能保证外部调用 exactly-once。

## 9. Zebra 接入位置

在共享 PostgreSQL command admission/event transaction seam 插入唤醒，
覆盖 API、approval resume、client-effect receipt、其他内部命令生产者；
逐一枚举调用点，不能只补某个 HTTP endpoint。
既有 append 幂等返回 canonical Event 时，唤醒使用 canonical command_id，不用新随机值。
构建有范围索引的待处理命令投影/索引时，须可从 canonical Event 重建；
它不是第二业务权威。Backfill 与 live admission 并行通过唯一键/高水位闭合。

Worker 消息只是 session wake-up：重新读取 canonical 命令，
按现有状态机处理未消费意图，消费时不重做 admission revision 等值检查。
SQLite 原有执行路径保持不变；新端口先检查既有 Port 能否扩展，禁止无用抽象。
同步 PG 驱动、AMQP async loop 与长执行分离，不能阻塞 heartbeat/confirm/取消。

## 10. 来源抓取迁移

第一步持久化 FetchCommand、due schedule、fetch_scope 和来源级 fence；
周期幂等键包含 fetch_scope+source_id+schedule_window，
手工触发使用请求幂等键，重试复用 fetch_command_id。
同 source 相邻窗口不能重叠，需声明合并过期窗口策略、单源互斥和速率上限。

旧 ARQ cron、managed fallback loop、Rabbit 调度按相同 source eligibility 切换，
不能双调度后只相信各自队列去重。迁移前 backfill next_fetch_at 并验证实际 DB 模型。
来源全局 enabled 与用户取消订阅不是同一语义；共享来源不能被单用户停订全局禁用。

配置缺失必须由真实诊断确定，不能把任意 403/timeout 都说成缺 X token。
配置缺失/过期授权进入 configuration_required，提示用户通过安全配置入口操作，
不让用户在聊天里贴 Cookie；配置更新后有限预检，再生成新的恢复唤醒。
429 遵守受限 Retry-After；网络错误退避；平台限流按凭证范围隔离。

本阶段只迁移“抓取任务调度”，不宣称 raw/events/documents 已耐久迁移。
Redis 写入失败时 FetchCommand 不得成功终结或更新 last_success/内容游标；
只有现有接收边界成功才推进状态。需测试“写入成功但响应丢失”的重复内容去重。
若要求 Redis 丢数据后仍零内容丢失，必须单独批准 raw 内容 durable spool/outbox；
不以本次调度迁移偷偷扩大范围或给出无法兑现的全链路零丢失承诺。
最终验收需证明新增文章实际进入用户历史和时间线，不只验收 fetch count。

## 11. 重试、隔离与死信

区分：传输重发（同消息）、业务重试（同操作新 generation）、运维重放（审核后新 generation）。
租约冲突不计模型失败；Broker 故障不消耗业务重试预算。
可重试业务错误采用指数退避+jitter、最大尝试/总时长，超限进入可查询业务终态。
发布暂时失败留 DB retry；永久协议/配置错误进入 dead 并告警；
dead operation 禁止 sweeper 无条件复活。dead、done 和 cancelled 不等价。

Rabbit 原生 DLX 保留原始消息体，不能保证非法输入不含凭证。
本方案应用校验失败时先持久化脱敏 rejection（错误码、受限关联 ID、摘要），
通过独立诊断 Outbox 可靠发送脱敏 DLQ 记录后 ACK 原消息；
不得直接把非法原文 reject 到普通运维可见 DLQ。
原生 DLX 仅作受限紧急隔离（如 broker delivery-limit），按可能含敏感信息治理：
严格 ACL、短期保留、加密备份、受控查看，禁止写普通日志。

运维 inspect/retry/discard 必须鉴权、审计、限流。不能把 DLQ JSON 原样再 publish。
重放从数据库重建协议，重新检查 scope/状态/权限/配置，创建新 message_id/generation，
causation_id 指向旧消息，业务 operation_id/idempotency_key 保持不变。
未知/不存在对象隔离；删除对象保留必要 tombstone，延迟消息不能重新创建它。

## 12. 灰度、回滚与生命周期

默认 publish=false、consume=false、DB fallback=true；启动校验至少一条可恢复执行路径。
publish flag 指 Broker 出站开关；一旦进入迁移期，业务 admission 仍须原子记录唤醒意图。
关闭发布不丢弃 Outbox，不以 flag 跳过协议有效性与安全检查。
必备开关保留：
TRENCH_RABBIT_PUBLISH_ENABLED / TRENCH_RABBIT_CONSUME_ENABLED /
TRENCH_DB_POLL_FALLBACK_ENABLED；
ZEBRA_RABBIT_PUBLISH_ENABLED / ZEBRA_RABBIT_CONSUME_ENABLED /
ZEBRA_COMMAND_SCAN_FALLBACK_ENABLED。
旧正常扫描可停，低频恢复/对账职责不可无人承担。

1. 部署拓扑和观测，不切业务。
2. 创建迁移表与约束，分批 backfill 未终结任务；不锁长事务扫描全库。
3. Shadow 使用独立 exchange/queue、consumer_role 与观测存储；不得竞争正式队列，
   不写正式 processed Inbox、不领取执行 lease、不产生副作用。
   Shadow 也不能将正式 Outbox 标为 published，必须使用独立投递记录/命名空间；
   shadow 流量有容量限制和独立清理窗口，验证数量按 message_id 对账而非比较总条数。
4. 按同一 scope allowlist 灰度 publisher、consumer、DB scanner。共享队列上的
   非灰度任务由中央领取逻辑处理，不能被普通消费者无条件 ACK 吞掉。
5. 对账后内部账号→全量；保留故障阈值触发 fallback，采用滞回避免反复切换。

回滚先启用/验证 fallback，再暂停新 Rabbit claim，drain 已运行任务；
不强抢 lease、不清队列、不删 Outbox，不撤销已提交业务结果。
Schema 采用 expand/contract；回滚应用不能直接降级删除仍有未终结记录的表。
备份恢复后重新对账 PG 与 Broker；旧 Broker 消息须经业务终态与 generation 校验。

Outbox/Inbox/DLQ 保留期必须覆盖最大业务生命周期、重试、重放及备份恢复窗口；
按该不等式配置清理策略，分批清理，仅清终态且已过恢复窗口的传输记录。
若允许无限期重放，就不存在安全的有限去重保留期；上线前须冻结有界重放窗口，
过期消息只隔离/对账，不再执行。备份恢复同样不能绕过该门槛。
业务幂等记录/Effect receipt/tombstone 不能随 Inbox 一起误删。
生命周期内 revocation/delete 的隐私清理必须覆盖隔离记录与备份政策。

## 13. 可观察性、SLO 与证据

先测基线再冻结以下候选目标，不把设计数值写成已达标：

| 指标 | 建议目标/条件 |
|---|---|
| API durable acceptance p95 | ≤250ms，标明 DB/认证依赖、负载和拒绝率 |
| commit→confirm p95 | ≤150ms，含 relay 等待，return 不算成功 |
| commit→首次有效领取 p95/p99 | ≤300ms / ≤1s，在批准并发与容量内 |
| 恢复时间 | lease TTL + scanner 周期 + 排队上限，阶段 0 给出具体门槛 |
| 已接受任务 | 故障演练中零丢失；不以 HTTP 200 或进程退出作为证明 |
| 隔离 | 跨 scope 读写/执行 0；伪造消息不损伤真实任务 |
| 外部副作用 | 受支持幂等工具零重复；uncertain 单独统计，不冒充成功 |

started_at 当前在 Trench 收到首批运行事件后才写，不可充当纯 pickup 时间。
分别记录 admission、commit、claim、模型首 token、前端首文本、完成与总耗时。
同进程耗时用 monotonic clock，跨进程时间需时钟同步并标误差。
Rabbit 只能优化前半段，必须比较模型、工具、SSE 和持久化各自耗时。

监测：Outbox oldest due age/publishing lease expiry、confirm/return/nack、
ready/unacked/DLQ、handoff 与 active 数、command backlog、lease takeover、
retry/configuration_required/uncertain、source 可见内容年龄、fallback 命中、
DB 扫描行数/查询次数、broker disk/memory alarm。
tenant/session/run/command/traceparent 用受控日志或 traces，
不作为 Prometheus 高基数标签；日志不得输出原文、凭证或完整 envelope。
Broker oldest message age 需注明由何种指标/采样推导，不假设内建精确业务延迟。

## 14. 实施阶段与硬门槛

| 阶段 | 交付 | 未满足不可进入下一阶段 |
|---|---|---|
| 0 基线/合同 | 两仓库边界记录、Schema/共享样例、拾取与扫描压测、可执行状态模型 | gap 核验、实测 SLO/资源预算、代码调用点清单 |
| 1 基础设施 | Compose、固定镜像、vhost/拓扑、长连接/confirm/return、DLQ、指标 | 真 Broker 断线、无路由、限流、权限及重启测试 |
| 2 Trench Turn | fence 改造、原子 Outbox/Inbox、claim-by-id、relay、consumer、sweeper | 真 PG 双 Worker、续租竞态、ACK 崩溃、回滚测试 |
| 3 Zebra command | 共享 admission seam、pending 索引、command consumer/control 接入 | 多入口原子性、旧 Session、乱序/取消、跨服务幂等 |
| 4 来源 | durable schedule/fetch command、scope/凭证隔离、能力队列、配置状态 | 双调度防重、Redis 接收失败、真实抓取→历史→时间线 |
| 5 上线硬化 | 配额、公平性、重放、清理、迁移/备份恢复、HA 演练 | 完整矩阵和回滚演练、真实流式回复与文件下载回归 |

阶段 0 是前置，不允许“先搭基础设施”跳过它。阶段估算需按本轮新增门槛重估；
v1.0 的 5–7 周只是初估，不是承诺。以有证据的小任务拆分，每项约 2–8 小时，
超过则拆分；不得为了满足工时删掉恢复、安全或并发测试。

## 15. 最终验收与边界

完整矩阵见缺口核验文档，每项须记录版本、配置、命令、终态 DB 和实测结果。
最低要求：提交后关浏览器仍完成、刷新可回放、两用户不串、文件可鉴权下载、
新内容进入历史/时间线、Broker/Worker 故障恢复、同请求幂等、控制命令及时处理、
无无限重试/抢租/恢复风暴、回滚后任务仍可执行。

“Redis 停止时任务仍完成”只适用于已经消除 Redis 硬依赖并验证的 Agent 路径；
来源 raw 流水线当前是单独阻塞/重试状态。上线前分别验证，不以总体口号掩盖差异。
服务启动、mock 单测、状态模型、真 PG/Rabbit 故障测试、跨服务 E2E、
生产多节点验收分别报告，任何较低级证据不得替代较高级证据。

## 16. 官方语义依据

- [Publisher confirms 与 consumer ACK](https://www.rabbitmq.com/docs/confirms)：
  confirm 与消费确认独立；mandatory 的 return 必须处理。
- [Publishers](https://www.rabbitmq.com/docs/publishers)：
  无匹配路由需显式检测，不能把 confirm 当业务已处理。
- [Quorum queues](https://www.rabbitmq.com/docs/quorum-queues)：
  高可用依赖副本多数；默认 DLX 不是 at-least-once，需显式策略。
- [Reliability guide](https://www.rabbitmq.com/docs/reliability)：
  连接中断和确认丢失可能重复，消费者须幂等。

以上依据于 2026-09-04 核验。部署仍须固定实际版本并复测，不以滚动文档替代版本验收。
