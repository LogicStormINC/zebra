# CLOUD-REC-PROD-CON-01 生产恢复合同 v1.0

| 项目 | 结论 |
| --- | --- |
| 状态 | `Review`；本文件不构成生产批准 |
| 任务 | `CLOUD-REC-PROD-CON-01` |
| 权威事实源 | PostgreSQL Event Store；Projection 可由 Event 重建 |
| Artifact bytes | 版本化、不可变的 S3-compatible object；PostgreSQL 保存 manifest/ref |
| 可丢弃状态 | Redis live stream、缓存、Mem0 派生索引、Worker 本地目录 |
| RPO/RTO | `TBD`，必须由真实 provider 的隔离恢复演练实测并批准 |

本合同把现有本地 recovery evidence 与生产准入分开。`CLOUD-REC-BACKUP-01`、
`CLOUD-REC-RESTORE-01`、`CLOUD-REC-DRILL-01` 证明本地代码路径和迁移语义，不能
替代 PostgreSQL physical backup/WAL、对象存储备份、PITR 或灾备演练。机器可读
证据的规范是 [CLOUD-REC-PROD-CON-01-evidence.schema.json](./CLOUD-REC-PROD-CON-01-evidence.schema.json)。

## 1. 不可违反的不变量

1. 一个 namespace 只有一套 PostgreSQL control-plane authority。Event append 是
   durable fact；Projection、Redis 和搜索索引都能从它重建。
2. Artifact/Snapshot 的 bytes 不进数据库备份清单；每个 PostgreSQL manifest ref
   必须绑定 object version、checksum、size、namespace 和创建水位。
3. 恢复期间旧实例不加入服务发现，runtime identity 没有写权限。任一校验失败都
   停止恢复，不在故障实例上猜测性修复。
4. restore 必须生成新的 `control_plane_epoch`。旧 epoch、旧 Lease token、旧连接
   和旧 runtime identity 的 fenced mutation 必须影响零行。
5. Redis 可清空；恢复后只从 PostgreSQL cursor replay 重建。已开始但结果不确定的
   Effect 进入人工 reconciliation，禁止把不确定状态自动重试成“成功”。
6. 备份、WAL、manifest 和对象副本不包含密码、KMS 明文密钥或 provider token。

## 2. 故障场景边界

| 场景 | 允许动作 | 明确禁止 |
| --- | --- | --- |
| 切换前失败 | Abort，删除/重建目标，继续使用原 SQLite | 修改活动 SQLite、保留半导入目标 |
| `ACTIVE` 已提交的应用缺陷 | 回滚应用 binary，继续使用兼容 PostgreSQL schema | 切回陈旧 SQLite、执行猜测性 down migration |
| 数据库逻辑故障 | 在新实例按目标恢复点恢复，并完成只读校验、epoch rotation、projection rebuild | 原地修表、让恢复实例接入服务发现 |
| 站点/存储故障 | 走已演练的 failover/restore runbook | 把灾备恢复当普通版本回滚 |

若业务确实要 PostgreSQL → SQLite，必须停写、导出/导入、逐项校验并产生新的
cutover record；这是一轮独立迁移，不是恢复快捷路径。

## 3. Backup 合同

### 3.1 PostgreSQL

- 使用平台批准的加密 physical base backup 与连续 WAL archive；`pg_dump` 只作为
  开发/迁移 portability evidence，不代表 PITR。
- backup identity 只能写入备份目标；restore identity 独立审批、短时使用并在
  epoch rotation 后撤销。备份目标采用不可变/防删除 retention。
- 每个备份记录 provider、base backup ID、WAL archive 上界、timeline、加密状态、
  retention 截止时间、manifest checksum 和创建时间。
- 监控最后成功 base backup、WAL archive lag、可恢复时间窗和最近 drill 结果；任一
  指标缺失时不得宣称满足 RPO。

### 3.2 Object storage

- Artifact backup 是独立的 versioned/immutable copy，不能从 Worker 本地目录重新
  上传来冒充备份。
- 先完成 object upload、checksum read-after-write 和批准耐久级别确认，再提交
  PostgreSQL manifest ref。数据库事务失败留下的无引用 object 只能由带最小保留期
  的 orphan GC 处理；仍被 manifest 引用的 version 禁止回收。
- restore 必须按目标 PostgreSQL recovery point 读取 manifest，校验 object version、
  checksum、size、metadata 和 namespace；缺一个即阻断服务恢复。

### 3.3 Retention 与凭据

生产负责人在流量准入前必须填写并批准：

| 指标 | 批准值 | 实测证据 |
| --- | --- | --- |
| RPO | `TBD` | `TBD` |
| RTO | `TBD` | `TBD` |
| PostgreSQL/WAL retention | `TBD` | `TBD` |
| Object retention/version lock | `TBD` | `TBD` |
| Restore drill frequency | `TBD` | `TBD` |

任一栏仍为 `TBD` 时，只允许 development/test profile；不得以本地 Compose timing
或逻辑 dump 推导生产数字。

## 4. Restore 顺序

1. 记录 incident、source namespace、目标 recovery point 和最后可确认的 durable
   commit；停止 ingress、外部 Effect、API 写入口和全部 Worker，撤销旧 runtime 身份。
2. 在新 PostgreSQL 实例恢复 base backup + WAL；目标实例保持隔离且 runtime role
   无写权限。按同一时间点准备 object backup copy 和 manifest。
3. 只读执行 schema compatibility、Event sequence 连续性、namespace negative read、
   Projection replay comparison、Artifact checksum/version 和 lease/claim 状态检查；
   此阶段不持久化 rebuild 结果。
4. 恢复审批者开启唯一受控写窗口：repair identity 只清空/重建 Projection，完成后
   立即撤销；restore identity 原子写入新的随机 `control_plane_epoch`，随后撤销；最后
   签发绑定新 epoch 的 runtime identity。
5. 用新 epoch 重建或对账 Lease、Effect、Outbox。Pending intent 按 idempotency key
   发现；uncertain external effect 进入 reconciliation，不自动重放。
6. 清空 Redis 并由 Event cursor replay 重建 live stream；Mem0 只从 confirmed
   governed Memory 重建，不能反向写回 Zebra 正文或 lifecycle。
7. 按“只读 API → 单 Worker → 逐步恢复入口”顺序开放。任何健康、权限、计数或 checksum
   失败立即停止新实例，不修改故障实例。

## 5. Evidence schema 与验收门

每次 drill 产生一个符合 schema 的 JSON evidence artifact，以及原始 provider 日志、
检查命令输出和清理记录。`invariants` 中标记为 `const: true` 的字段必须为真；
缺失或为假即 drill `FAIL`。最少必须能回溯：

- source snapshot、target recovery point、timeline、provider 和 namespace；
- PostgreSQL base/WAL 与 object backup copy 的身份、checksum、version、retention；
- Event count、每 Session 最大 sequence、连续性、Projection replay revision；
- Artifact ref 完整性、旧 namespace 负向读取、Redis 重建、uncertain Effect 状态；
- old/new epoch、旧写入被拒、临时 identity 撤销和新 runtime identity 签发；
- RPO/RTO 的起止时间、测量工具版本、审批者、失败重试和临时资源清理。

演练 checklist：

- [ ] 目标恢复点在 base backup/WAL 可恢复窗口内，并保存 provider receipt。
- [ ] ingress、Worker、Effect 和旧 runtime credentials 已停用/隔离。
- [ ] 新实例 schema、Event、Projection、namespace、Artifact、Lease invariants 全部通过。
- [ ] epoch rotation 后旧连接/旧 token 的写入影响零行。
- [ ] Redis、派生索引和缓存按重建路径恢复；没有把它们当事实源。
- [ ] RPO/RTO、数据差异、失败步骤、审批和 cleanup 已写入 evidence artifact。
- [ ] 新实例先只读、再单 Worker、再恢复入口；失败时可重复停止。
- [ ] 临时实例、备份测试副本、restore/repair identity、孤儿对象和日志权限已清理。

## 6. 责任与推进顺序

| 责任 | 交付 |
| --- | --- |
| Storage/SRE | provider backup/WAL/object receipts、restore automation、原始日志 |
| Security | backup/restore/runtime identity、KMS、retention 与撤销证明 |
| API/Worker | read-only → single Worker → ingress 灰度顺序和健康证据 |
| Maintainer | 批准 RPO/RTO、保留期、failover topology 和最终生产准入 |

只有本合同 `Review` 后，`CLOUD-REC-PG-PITR-01` 与 `CLOUD-REC-S3-01` 才能分别
实现 provider-specific runner；两者都完成真实隔离恢复后，`CLOUD-REAL-SVC-CI-01`
才可把 evidence 纳入 canonical CI。当前本合同不激活任何 provider、凭据、部署或
runtime 写路径。

