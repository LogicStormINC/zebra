# Zebra PostgreSQL 迁移、备份、恢复与回滚评审 v1.0

| 项目 | 结论 |
|---|---|
| 任务 | `CLOUD-PG-PLAN-01` |
| 状态 | `Review`，尚未构成生产批准 |
| 权威源 | 切换前为单一 SQLite；切换后为单一 PostgreSQL |
| 迁移方式 | 首版停写窗口、一次性导入、验证后整体切换 |
| 双写 | 禁止 SQLite/PostgreSQL 双写 |
| 快速回滚 | 回滚应用版本并继续使用 PostgreSQL，不切回陈旧 SQLite |
| RPO/RTO | 不在设计阶段虚构；生产流量前必须填写并实测批准值 |

## 1. 决策范围

本文冻结 PostgreSQL Adapter 开始前必须明确的迁移和恢复合同。它允许后续任务
实现、测试 PostgreSQL Store，但不允许选择生产 backend、迁移真实数据或声明 HA/PITR
就绪。

本文不实现：

- PostgreSQL Adapter、schema migration 或数据迁移程序；
- Lease/Outbox、对象存储、Redis、Kubernetes 或 Mem0 wiring；
- 数据库凭据、云供应商、备份产品或跨区域拓扑；
- 未经测量的 RPO、RTO、容量或性能承诺。

GitHub Actions 当前受账户 billing/spending limit 阻塞。维护者允许继续本地证据，
但该豁免不等于合并、发布或生产批准。

## 2. 不变量

1. Session Event Store 始终是执行事实源；Projection 可由 Event 重建。
2. 一个运行进程的 `ControlPlaneStores` 只能指向一套权威 backend。
3. 不通过 SQLite/PostgreSQL 双写解决迁移。跨 backend 无法提供所需原子性，失败时会
   制造两个事实源。
4. Adapter 可以分卡开发，事实源不能分卡切换。完整 cloud composition 未通过前，
   默认 local profile 继续使用 SQLite。
5. Event append 独立提交事实；Projection 允许延迟并按 applied sequence 重建。只有
   Context/Handoff/Effect-Outbox 等聚合 Port 才协调多表写入并拥有数据库事务；上层
   禁止用多个独立 Store call 或按表补偿模拟事务。
6. 任何校验不一致都 fail closed：保持旧 backend、不启动 Worker、不接受新写入。
7. Redis、Mem0、搜索索引和前端状态均可丢弃重建，不进入权威迁移清单。
8. 生产 schema 只采用 expand/contract；回滚不依赖破坏性 down migration。

## 3. 权威迁移范围

迁移合同以 Port 而非当前 SQLite 表名为稳定边界。

### 3.1 必须纳入同一次权威切换

| `ControlPlaneStores` 边界 | 迁移/恢复要求 |
|---|---|
| Events、Session Projection | 保留单 Session 单调 sequence、Event ID、幂等键；Projection 可重建 |
| Workspace、Task、Segment | 保留当前状态、active Segment、版本和 lineage |
| Context lifecycle | Event、Capsule、active context projection 保持同一事务语义 |
| Handoff、Dispatch | Envelope、lineage、operation 与 dispatch 状态不可拆分 |
| Idempotency、Effect ledger | 保留 operation key 与不确定副作用状态，禁止自动重放 |
| Governed Memory | 保留 candidate/confirmed/superseded/expired/deleted、scope 与 provenance |
| Artifact metadata/index | 保留 checksum、size、lineage、访问引用；payload 按对象存储计划处理 |
| Model call、Tool run | 保留审计、Artifact 关联与恢复证据 |
| Provider continuation | 保留 provider 状态引用；不可用时 fail closed 或重新开始明确的新 Attempt |
| Session history、Delivery audit | 保留查询与交付证据，不保留已删除正文的额外副本 |
| Lease、Outbox/Inbox | 切换前静止；恢复后按新 fencing epoch 重建或对账 |

### 3.2 不进入 PostgreSQL 权威迁移

- `SQLiteSkillsStateStore`：扩展启停的本地 profile 状态，另行定义部署配置来源；
- web resource/chunk cache：派生缓存，可重新抓取或重建；
- Redis live state：切换/恢复时清空，从 PostgreSQL cursor replay；
- Mem0 PostgreSQL 和 history SQLite：派生语义索引，从 confirmed Zebra Memory 重建；
- Sandbox 临时目录、进程内状态和开放 socket；
- Artifact/Snapshot 大 payload：目标是 S3-compatible storage，不把 byte payload 塞入
  PostgreSQL。切换前必须有完整 manifest 与对象存在性证据。

## 4. PostgreSQL schema 与 migration 规则

### 4.1 数据模型

- 标识符使用原生 UUID；时间使用 `timestamptz`；结构化 payload 使用受版本控制的
  `jsonb`，读取端仍执行领域 schema 验证。
- 首个 cloud profile 是单 external namespace 部署；Adapter 注入不可变
  `deployment_namespace`。多 namespace profile 仍由 `CLOUD-NS-01` 锁定。
- Event 唯一键为 `(namespace, session_id, sequence)`；Event ID 为
  `(namespace, event_id)`；Event 幂等键为 `(namespace, session_id, idempotency_key)`。
- Session Event sequence 是从 `0` 开始、无间隙且严格递增的领域合同；迁移不得改写
  sequence。
- 通用请求幂等键保持 `(namespace, action, idempotency_key)`；Effect 保持
  `(namespace, root_session_id, ledger_key)`。UUID 全局生成仍不替代授权查询中的
  namespace predicate。
- append 使用 expected-version CAS，不用“先查后写”的应用级竞争窗口。
- Projection 写入携带来源 stream version，禁止旧 Projection 覆盖新版本。
- namespace 是所有权威行和索引的必需隔离键；仅有 session ID 不构成授权边界。
- 所有外键、唯一约束和查询索引由 migration 显式创建，不依赖 ORM 隐式建表。

### 4.2 事务所有权

- `EventStorePort.append` 在一个事务内执行 expected-version CAS 与 Event insert；
  Projection 不与它假装同步原子，消费者通过 stream version 幂等追平。
- 已有 `ContextLifecycleStorePort`、`SessionHandoffPort` 继续作为聚合事务 owner；其
  PostgreSQL Adapter 在一个连接/事务内提交各自 Event、Projection、Artifact metadata
  或 Dispatch 状态。
- `CLOUD-LEASE-01` 在写 Outbox 前新增一个聚合 Port；调用者只提交领域输入，Port
  负责 Event/Effect/Outbox 的单事务 commit。禁止暴露通用全局 Unit of Work。
- 事务失败只允许整体 rollback；Projection lag 通过 replay 恢复，不回写或删除 Event。

### 4.3 版本策略

1. migration 有单调版本和 checksum；启动时只允许已知 schema 范围。
2. expand migration 先落库，再发布同时兼容旧/新 schema 的应用。
3. contract migration 只能在旧版本完全退出、备份保留期结束且恢复演练通过后执行。
4. 生产故障优先 forward-fix；不自动执行 down migration。
5. migration job 单实例执行并持有 PostgreSQL advisory lock；API/Worker 无建表权限。
6. schema owner、runtime reader/writer 和 migration identity 分离。
7. 每次发布前，当前版本和 rollback candidate 都必须在目标 schema 上通过启动、读写
   与 schema-range 测试；旧 binary 禁止执行 migration。

## 5. 首次迁移与切换

首版采用维护窗口，流程必须可重复且每一步产生机器可读 manifest。

### 5.1 准备

1. 固定源代码、SQLite schema 版本、目标 migration 版本和 exporter 版本。
2. 拒绝新 Session/消息/审批/工具动作，等待运行中 Attempt 到安全边界后停止 Worker。
3. 确认没有 active lease、未完成数据库事务或仍在写入的 Artifact payload。
4. 对 SQLite 使用原生 backup API 生成一致快照；原文件只读保留，不直接迁移活动文件。
5. manifest 记录源文件 SHA-256、大小、schema 版本、cutoff 时间和 exporter 版本。

### 5.2 导出与导入

1. exporter 从只读快照按 Port/聚合导出版本化 JSONL，不复制 SQLite
   内部 rowid、触发器或实现细节。
2. 导出格式固定为版本化 JSONL，不允许“等价格式”。每行是 RFC 8785 JCS JSON，UTF-8
   无 BOM、LF 换行；领域字符串必须已是 Unicode NFC，exporter 遇到非 NFC 值即失败而
   非静默改写。记录按 schema 声明的 typed business-key tuple 排序：整数按数值、UUID
   按 16-byte 值、字符串按 UTF-8 byte；格式版本与 key schema 写入 manifest。manifest
   记录文件 SHA-256、行数、业务键范围和每 Session 最大 sequence。
3. 目标 PostgreSQL 必须是空的新 schema；importer 使用幂等业务键和显式事务。
4. 导入顺序先 Event/权威主记录，再 Projection/索引，再 Ledger/Audit；Projection 同时
   从 Event 独立重建，用于交叉验证而不是信任源 Projection。
5. Artifact manifest 必须逐条验证 checksum 和 payload 存在性；缺失时整个切换失败。

### 5.3 切换前校验

- 所有数据集 counts、业务键、摘要与 manifest 一致；
- 每个 Session sequence 从 0 连续递增，无重复 Event ID/idempotency key；
- Event replay 得到的 Projection 与迁移 Projection 按版本化字段白名单比较；白名单是
  migration 输入 `projection-comparison-v1.json`，其版本、SHA-256 和维护者审批身份写入
  manifest 与 cutover record。差异写入 JSONL artifact，任何未批准差异阻断切换；
- Memory lifecycle、Handoff lineage、Effect 状态和 Artifact 引用均可解析；
- 目标数据库的 namespace 负向读取测试为零泄漏；
- 在隔离环境启动只读 API smoke，并验证 Worker 因 cutover 尚未 ACTIVE 而拒绝启动；完整
  runtime 写入 smoke 使用独立 disposable PostgreSQL 测试实例与测试 activation record，
  不为迁移目标绕过 ACTIVE 写门，且不能访问源 SQLite 路径。

### 5.4 切换

1. PostgreSQL `control_plane_cutovers` 与只读外部 manifest 共同记录
   `PREPARED -> VERIFIED -> ACTIVE`，绑定 source hash、migration、应用版本和 activation ID。
2. 只有 migration identity 可将 `VERIFIED` 原子提升为 `ACTIVE`。API/Worker runtime
   identity 的所有 PostgreSQL mutation 必须在同一事务确认唯一 ACTIVE record，非 ACTIVE
   一律 fail closed。独立 importer/rebuilder identity 在 `PREPARED/VERIFIED` 期间只能
   写 migration manifest 声明的 staging/目标表，不能获得 runtime role、Effect、Lease、
   Outbox 或 cutover activation 权限；其凭据不得进入 API/Worker，并在激活前撤销。
3. `ACTIVE` 是不可逆的快速回滚边界。提交后源 SQLite 永久转为只读迁移证据，
   不再区分是否已经出现第一条业务写入。
4. 一次性切换完整 cloud `ControlPlaneStores` composition，不按 Store 单独放量。
5. 先启动只读 API 检查，再启动单 Worker，最后恢复写入口；重启只读取 durable
   cutover state，不根据部署内存猜测水位。

## 6. Abort、Rollback 与 Restore 必须分开

| 场景 | 动作 | 禁止事项 |
|---|---|---|
| 切换前失败 | Abort；删除目标实例/重建，继续使用原 SQLite | 修改活动 SQLite 或保留半导入目标 |
| `ACTIVE` 已提交 | 回滚应用版本，但继续使用兼容 PostgreSQL schema | 直接切回陈旧 SQLite |
| 数据库逻辑故障 | forward-fix 或恢复到新 PostgreSQL 实例 | 原地猜测性修表、破坏性 down migration |
| 站点/存储故障 | 执行经过演练的 Restore/Failover | 把 DR 当普通版本回滚 |

若业务强制从 PostgreSQL 返回 SQLite，必须重新停写，并实现反向 exporter/importer、
完整校验和新的 cutover record；它是一次独立迁移，不是快速回滚。

## 7. Backup 与 PITR 合同

### 7.1 开发和迁移证据

- 每次 migration 验证生成一次 `pg_dump --format=custom --no-owner` 逻辑备份；
- 在全新 PostgreSQL 实例执行 `pg_restore`，运行 schema、replay 和 Store contract 测试；
- 逻辑备份只证明可移植性，不构成生产 PITR。

### 7.2 生产准入要求

- 使用平台或已批准工具完成加密 physical base backup 与连续 WAL archive；
- backup identity 只写备份目标，restore identity 独立审批；
- 备份、WAL、manifest 和对象存储使用独立 retention 与不可变/防删除策略；
- Artifact/Snapshot payload 使用 immutable content/version ID；PostgreSQL manifest
  记录 version、checksum 和创建水位。PITR 后保留恢复点引用的所有 object，GC 不得早于
  数据库/备份 retention；删除与法务清除由 tombstone 和单独批准的备份删除策略协调；
- 运行时先上传不可变 object，并完成 checksum read-after-write 与批准耐久级别确认，随后
  才能提交 PostgreSQL manifest 引用；数据库事务失败产生的无引用 object 只能由带最小
  保留期的 orphan GC 回收，任何被 manifest 引用的 object 禁止回收。端到端 RPO 取数据库
  可恢复缺口与 object 达到批准耐久级别的缺口较大者，二者必须在同一次恢复演练中测量；
- 定期在隔离账户/集群恢复，不能只检查“备份任务成功”；
- 监控最后成功 base backup、WAL archive lag、可恢复时间窗和 restore drill 时间；
- 凭据、KMS 明文密钥和外部 provider token 不进入数据库备份。

生产负责人必须在流量准入前填写：

| 指标 | 批准值 | 实测证据 |
|---|---:|---|
| RPO | `TBD` | `TBD` |
| RTO | `TBD` | `TBD` |
| backup retention | `TBD` | `TBD` |
| restore drill frequency | `TBD` | `TBD` |

任一 `TBD` 存在时，只允许开发/测试 profile。

## 8. Restore 与恢复后处理

1. 停止 ingress、外部 Effect、API 写入和全部 Worker，撤销旧 runtime 数据库身份，
   隔离故障实例并记录目标恢复点。
2. 在新 PostgreSQL 实例恢复 base backup + WAL；恢复实例不加入服务发现，runtime role
   保持无写权限，数据库只允许后续受控 repair/restore identity 写入。
3. 按目标 WAL 恢复点读取 versioned object manifest，恢复/保留其引用对象并校验
   version、checksum、size 和 namespace。
4. 只读执行 schema compatibility、Event 连续性、Projection replay comparison 和负向
   隔离检查，不在此步骤持久化 rebuild 结果。
5. 验证完成后由恢复审批者进入唯一受控写窗口：服务实例仍不在服务发现中；临时 repair
   identity 只能清空/重建 Projection 表，完成后立即撤销。随后 restore identity 只能原子
   写入新的随机 `control_plane_epoch`，完成后同样立即撤销；最后才签发绑定新 epoch 的
   runtime identity。Lease token 固定为 `(epoch, token)`；
   Lease/Effect/Outbox 和所有受 fencing 保护的 mutation 在同一 SQL 事务中比较当前
   epoch、token 与 ownership。旧连接、旧 epoch 或旧 token 的写入影响行数必须为零。
6. Redis 清空重建；Mem0 从 confirmed governed Memory 重建，不从其 history 反写 Zebra。
7. Pending Outbox 依据 idempotency key 重放；已开始但结果不确定的外部 Effect 进入
   reconciliation，禁止自动重试。
8. 先只读 API，再单 Worker，再逐步恢复入口；任一检查失败即停止新实例且不改故障
   实例。连接池/DNS 切换、审批者和 evidence checklist 在 `CLOUD-REC-01` runbook 固化；
   记录实际 RPO/RTO 和数据差异。

`control_plane_epoch`、fencing 和 Outbox 的实现属于 `CLOUD-LEASE-01`，但
`CLOUD-PG-01` 的 schema 必须为它保留事务和唯一约束边界。

## 9. `CLOUD-PG-01` 实施门

### 9.1 允许实现的首个切片

- PostgreSQL migration runner 与最小 schema；
- `EventStorePort` 和 `ProjectionStorePort` Adapter；
- expected-version CAS、idempotent append、read-since 和 projection rebuild；
- isolated Compose PostgreSQL contract tests；
- cloud composition 保持不可选择，直到其余权威 Ports 完成。

SQLite exporter/importer、cutover state machine 与全量 manifest 校验拆为后续
`CLOUD-PG-MIG-01`，依赖 `CLOUD-PG-01`，并在完整 cloud cutover 前强制完成。

### 9.2 分阶段测试门

`CLOUD-PG-01` 必须通过：

1. 两个并发 writer 对同一 expected version 只能有一个成功。
2. 同一 Event/idempotency key 重试不生成第二个 Event。
3. 多 Session 并发仍保持各自严格 sequence。
4. 删除 Projection 后可从 Event 全量重建，并与原语义一致。
5. Event append 事务失败不留 Event；Projection 落后后可按 applied sequence 追平。
6. logical backup 恢复到新实例后，上述 contract tests 再次通过。

后续各权威 Port Adapter 卡必须在各自 owned paths 内通过聚合事务 conformance；其中
Context/Handoff 不得留下半状态，Effect/Outbox 必须通过原子提交与 fencing 测试。

`CLOUD-PG-MIG-01` 必须通过：canonical export/import 重放、受限 importer/rebuilder
identity、非 ACTIVE runtime 写入 fail closed、唯一 ACTIVE 激活和激活后不回退 SQLite。

### 9.3 仍然禁止

- 在 `CLOUD-LEASE-01` 前宣称 multi-Worker safe；
- 在 `CLOUD-ART-01` 前迁移大型 Artifact/Snapshot payload；
- 在 `CLOUD-REC-01` 前选择生产 backend 或声明 PITR/DR 完成；
- 因 GitHub Actions 暂不可用而降低真实 PostgreSQL、恢复或并发测试要求。

## 10. 评审结论

本模型选择“停写迁移 + 单一事实源 + expand/contract + 新实例恢复”。它有意拒绝
双写和切回陈旧 SQLite，因为二者会把一次基础设施迁移变成领域一致性协议。

进入 `CLOUD-PG-01` 前仍需维护者确认：

- [ ] 同意首版使用维护窗口而非在线双写；
- [ ] 同意 cutover 进入 `ACTIVE` 后不把旧 SQLite 当快速回滚目标；
- [ ] 同意生产 RPO/RTO 保持 `TBD` 即禁止生产流量；
- [ ] 同意 `control_plane_epoch` 是后续 Lease/Restore 的必需合同；
- [ ] 同意首个 Adapter 切片只实现 Event/Projection，不激活 cloud composition。
