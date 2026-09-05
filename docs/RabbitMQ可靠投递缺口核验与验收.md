# RabbitMQ 可靠投递缺口核验与验收

日期：2026-09-04。范围：隔离分支 codex/rabbitmq-foundation-01 的方案与现有调用边界。
主方案：[v1.1](Zebra_Trench_RabbitMQ可靠投递与服务质量实施方案_v1.0.md)。
这是设计审查，不是 RabbitMQ 运行时交付或生产验收。

## 1. 证据与结论等级

- A：原方案存在可构造的确定性矛盾。
- B：当前代码存在相关前置缺口；未声称线上已发生该竞态。
- C：方案遗漏条件，存在可行安全实现，也存在失败实现；必须补合同与测试。

| ID | 等级 | 已核实问题与反例 | 修订位置 |
|---|---|---|---|
| G01 | A | 原唯一键 message_type+aggregate_id+schema_version：同 Session 第二条 command、同 Source 第二个窗口碰撞；同 Turn 恢复也无法插入第二条 | §5–6 operation/generation/scoped unique |
| G02 | C | 原文只说“幂等 wake-up”“新的 delivery attempt”，未定义是否换 message_id；若复用已处理 ID，会被 Inbox 去重。不能据此断言实际丢任务 | §6/8/11 新 generation，新 ID；物理重发同 ID |
| G03 | C | Inbox 若先单独提交，领取失败后重投会被跳过 | §6 同事务 durable handoff |
| G04 | C | confirm 对无路由消息也可 ACK；只按 confirm 标 published 会漏投 | §3–4/6 mandatory+return+binding 验证 |
| G05 | C | Relay 过期接管后旧 publish 返回，可覆盖新 owner 的状态 | §6 relay fence 条件写回 |
| G06 | B | Trench renew_lease 与投影先读 owner 后修改，缺少原子 fence/到期条件；claim 行锁不自动保护其他事务 | §2/8 所有租约写路径统一 CAS/锁 |
| G07 | C | 提前 ACK 释放 prefetch，长任务仍占资源；持续交接可超过运行上限 | §7 ACK 外的执行槽、配额、公平性 |
| G08 | B | Zebra recent sessions 有限窗口可反复遗漏旧对象；降频不扩大覆盖 | §8–9 pending 索引、全范围恢复与 backfill |
| G09 | A/C | expected_revision 是接受前 revision，接受 Event 后 current 已变；若消费再等值校验会拒合法命令。投影序号也不等于命令完成游标 | §2/9 accepted Event 与处理游标 |
| G10 | B/C | 内部 client-effect receipt 会创建 resume；只接 API admission 不覆盖所有命令。独立 PG 事务与 Broker 双写不可替代共享 seam | §9 枚举生产者/事务测试 |
| G11 | C | Shadow 若消费正式队列，会竞争消息；写正式 Inbox 则污染正式消费 | §12 独立拓扑与角色/观测存储 |
| G12 | C | CANCEL 若与耗时执行共用饱和执行槽，无法及时停止 RUN；FIFO 不解决控制延迟 | §8 控制接收能力、状态机顺序 |
| G13 | C | 伪造 tenant 消息不能修改真实任务为失败；凭证过期、撤权、删除后重放不能复活 | §5/8/11 DB 校验、受控重放 |
| G14 | A/B | Source envelope 示例不符合统一 payload_ref；SourceRow 全局来源与用户订阅不是同一 scope | §5/10 typed ref、公共/私有抓取范围 |
| G15 | A/B | 原总验收说 Redis 停止仍完成；RSS push_raw、调度 cursor 依赖 Redis。且按能力路由没有对应队列表 | §4/10/15 限定承诺、明确队列 |
| G16 | C | 原生 DLX 会带原始消息体，非法输入可能含密钥；默认 dead-letter 不保证可靠转发 | §4/11 脱敏诊断 Outbox 与受限原生隔离 |
| G17 | C | 缺重试预算、积压容量、保留/重放窗口、回滚 drain/迁移协议，会无限增长或失去恢复依据 | §7/11–12 上限、清理不等式、expand/contract |
| G18 | C | vhost 不隔离节点故障；外部副作用成功但 receipt 丢失，Rabbit/DB 不能保证 exactly-once | §4/8 多数副本与 uncertain 对账 |
| G19 | A/C | 实施决策未列阶段 0；pickup 与首模型事件时间混用；无负载前提的 p99 无可验收含义 | §13–14 阶段门槛与分段测量 |
| G20 | B | Trench broker handoff/recovery intentionally skips cancel_requested; running/dispatching cancellation currently relies on dispatcher heartbeat and DB fallback. Disabling normal polling without a cancellation recovery path can strand a dead owner's cancelled work | Stage-2 composition must preserve low-frequency/control recovery; test before permitting fallback-off |

## 2. 本地代码依据

Trench 基线为 84e9946 加用户未提交源码快照，不能把提交哈希单独当全部源码版本。
Zebra 基线为 230caeb1；真实重测时须同时保存 worktree diff 指纹。

- Trench `services/api/src/trench_api/trench_ai_turn_store.py`：
  create_turn 同事务边界；claim_next 行锁；renew_lease、project_cursor_group、
  _owned_turn 的 owner 读后写与无 fence，_finish_turn 的执行 Outbox published 语义。
- Trench `services/api/src/trench_api/trench_ai_turn_dispatcher.py`：
  bounded running tasks、轮询、首事件后 mark_running；这是可复用模式，不另写无限 executor。
- Trench `services/rss_ingest/src/trench_rss_ingest/worker.py`：
  ingest_managed_rss_sources 读取全局 SourceRow 与 Redis polling cursor；
  ingest_rss_feed 通过 redis_svc.push_raw 交付内容后记录抓取成功。
- Zebra `apps/worker/src/zebra_agent_worker/command_consumer.py`：
  list_recent_sessions(limit=max(1,batch_size*8))；同步执行入口及控制分支。
- Zebra `packages/agent-storage/src/agent_storage/postgres/client_effects.py`：
  accept_receipt 在同一事务生成 resume command，证明 API 不是唯一命令生产者。
- Zebra ADR-023 admission revision/idempotency 合同，ADR-024 durable commit/live replay 合同。

以上只核实关键共享路径，不宣称已枚举所有内部命令生产者；阶段 3 开工前必须穷举。
无需新增 Broker、停服务或使用用户凭证即可验证 G01 的逻辑矛盾。

## 3. 可执行设计反例

运行：`python3 scripts/check_rabbitmq_delivery_contract.py`。
脚本用标准库 SQLite 演示唯一键/事务/CAS 模型，验证：

1. 原键拒绝同一 Session 第二操作。
2. 原键拒绝同一 Source 第二窗口。
3. 新键允许不同 operation；物理重发仍唯一。
4. 同 scope 同业务恢复增加 generation；其他 scope 不冲突。
5. 旧 Inbox ID 会被去重，新恢复 ID 可交接。
6. handoff 回滚不能残留 processed Inbox。
7. 旧 fence、已到期 lease 不能写回或续命。
8. 同 message_id 不同 digest 不能当普通重复。

这是设计模型，不导入或测试实际 Trench Store、PG 锁、AMQP confirm 或服务集成。
即使全部通过也不能将 G06/其他代码风险标记“运行时已修复”。

## 4. 实际实现必须通过的故障矩阵

| 用例 | 注入点 | 必须验证的终态/证据 |
|---|---|---|
| F01 原子 admission | 业务写入后/Outbox 前 rollback | 业务、幂等、消息、Outbox 同有或同无 |
| F02 多命令/多窗口 | 同对象两 operation，各两代，物理重复 | 四个合法唤醒、每代只一记录，无新业务副作用 |
| F03 confirm 不确定 | 发布前断线/确认丢失/确认后 DB 失败 | 不提前 published，同 ID 可补发，任务最终完成 |
| F04 无路由 | 删除 binding/错误 vhost/交换器缺失 | return/NACK/错误可见，Outbox 不误报成功 |
| F05 Relay 接管 | A 卡住到租约过期，B 领取，A 迟到 ACK | 仅 B fence 可更新；允许物理重复 |
| F06 handoff 窗口 | Inbox前/lease后/commit后/调度后/ACK后杀进程 | 无不可恢复 Inbox；新 Worker 接管同业务操作 |
| F07 租约竞态 | A 读后暂停，B 接管，A 续租/投影/完成 | 旧 fence 全部拒绝，B 结果不被覆盖 |
| F08 背压 | 数千唤醒+长模型任务 | active≤配置容量，控制响应及时，DB lag/拒绝率可见 |
| F09 完整恢复 | 老 Session 超出 recency 窗口；published 无消费 | 索引扫描最终发现，不靠近期访问触发 |
| F10 命令语义 | RUN后MESSAGE/CANCEL、重复/乱序、接受后revision变动 | canonical Event 只处理一次，取消不等模型结束 |
| F11 跨服务超时 | Zebra accept后丢响应 | Trench重试同command，只存在一次上游执行 |
| F12 多入口 | API、批准resume、client-effect receipt等 | 每个 canonical command都有原子唤醒，rollback不泄漏 |
| F13 多用户 | 同operation字符串不同scope、伪造身份、撤权、删会话 | 无越权读写，错误消息不损伤受害者任务 |
| F14 Source双调度 | ARQ+managed loop+Rabbit切换、手动与周期并发 | 同fetch_scope/source不重叠，保留业务幂等 |
| F15 来源凭证/内容 | 两用户不同凭证、缺配置、429、Redis写入异常 | 私有内容不串；失败不推进成功状态；配置安全提示 |
| F16 DLQ | 非法消息含测试假密钥；DLX目标停止/队列满 | 普通诊断无原文；可靠隔离/有告警，安全重放不复活终态 |
| F17 Shadow/回滚 | shadow开启、灰度外scope、处理中关闭consumer | 无抢消息/Inbox污染；fallback先就绪，任务继续 |
| F18 清理/恢复 | 保留窗口边界、DB备份恢复+旧队列 | 不清未终态依据，旧消息不产生新业务操作 |
| F19 生产HA | Broker节点失效/多数不可用/disk alarm | 明确可用性边界，DB安全排队和可量化RTO |
| F20 产品回归 | 关浏览器/刷新/切会话/长回复/真实files.publish | 流式、标题、历史、鉴权下载均可用，附DB终态与浏览器证据 |

## 5. 交付状态

- 完成：方案核验、v1.1 一致性修订、Trench 边界记录、标准库反例脚本。
- 未完成：正式 Envelope Schema、运行时代码、迁移、Broker 部署、基线压测与 F01–F20。
- 上述缺口全部已转成实现门槛，不能因为文档修改就从实施清单删除。
- 下一步：阶段 0 先枚举生产者/权威 identity 映射、实现 Schema 共享样例并测基线；
  阶段 2 前修真实 Trench 租约竞态，禁止先开多 Worker Rabbit consumer。

官方依据见主方案 §16。代码审查和设计模型不能替代真 PG/Rabbit 并发故障测试。
