# CLOUD-REC-PG-PITR-01 PostgreSQL physical PITR 演练

| 项目 | 结论 |
| --- | --- |
| 证据范围 | `production-like`、`local-only` |
| 实现 | PostgreSQL `17.5-alpine3.21` physical `pg_basebackup` + archived WAL |
| 恢复点 | `pg_create_restore_point('zebra_pitr_target_v1')` 命名恢复点 |
| 权威校验 | Event sequence/count、Projection replay、namespace、Lease epoch |
| 生产含义 | 不构成生产 PITR、RPO/RTO、failover 或 provider readiness 批准 |

本 runner 为 `CLOUD-REC-PG-PITR-01` 的隔离证据。生产恢复准入仍由
[`CLOUD-REC-PROD-CON-01`](./CLOUD-REC-PROD-CON-01.md) 控制；S3 Artifact backup
由 `CLOUD-REC-S3-01` 单独负责。

## 1. Runner 做什么

`tests/compose/recovery_pitr/run-pitr.sh` 创建四个临时 volume：

- `primary-data`：启用 `wal_level=replica`、`archive_mode=on` 和 WAL archive；
- `base-backup`：由 PostgreSQL 用户执行 physical `pg_basebackup -X none`；
- `wal-archive`：`archive_command` 写入的 WAL 文件，restore 只读挂载；
- `restore-data`：从 base backup 复制出的全新数据目录。

流程按顺序执行：

1. migration、control-plane epoch、Session bootstrap、Projection 和带 checkpoint
   的 source Lease 写入 primary；
2. 对 primary 做 physical base backup；
3. 写入目标 Event，创建命名 restore point，再写入一个必须被 PITR 排除的
   post-target Event，并切换 WAL；
4. 将 base backup 复制到全新 restore volume，写入 `restore.signal`、
   `restore_command`、`recovery_target_name` 和 `recovery_target_action=promote`；
5. restore 服务健康后验证：只恢复到目标 Event，Projection 从 Event 重建，
   other namespace 读不到数据；
6. 旋转新 `control_plane_epoch`，旧 Lease heartbeat 必须被拒绝，新 epoch Lease
   获取后释放；
7. Compose `down --volumes --remove-orphans`，再把 cleanup 状态写进报告。

## 2. 执行与输出

在仓库根目录执行：

```bash
bash tests/compose/recovery_pitr/run-pitr.sh
```

成功时必须看到：

```text
PITR_SEED=PASS ...
PITR_TARGET=PASS ...
PITR_VERIFY=PASS events=4 revision=3 ... old_epoch_rejected=True
ZEBRA_PG_RECOVERY_PITR_TEST_RESULT=PASS
PITR_CLEANUP=PASS containers=0 volumes=0 temporary_credentials=0
```

默认报告位于临时目录并在 cleanup 后删除。需要保留机器可读证据时设置：

```bash
ZEBRA_PG_PITR_EVIDENCE_DIR=/tmp/zebra-pitr-evidence \
  bash tests/compose/recovery_pitr/run-pitr.sh
```

最终 JSON 的 `schema_version` 为 `zebra.recovery.pitr.evidence.v1`，并记录
base backup digest、archived WAL 数、命名恢复点/LSN、Event/revision、Projection
重建、旧 epoch 写入拒绝、replacement Lease epoch、模拟 RPO 和实测本地 RTO。
它是 PostgreSQL scope evidence，不填充 S3 字段，也不冒充完整生产 recovery
contract artifact。

## 3. 验收与限制

- post-target Event 不得出现在恢复实例；Event sequence 必须从 `0` 连续到目标 revision；
- `session_streams.current_version`、Projection `current_sequence` 和重建结果必须一致；
- `other-namespace` 的 Event read 必须为空；
- restore 前 epoch 与新 epoch 必须不同，旧 epoch heartbeat 影响零行；
- runner 失败也执行确定性 cleanup，临时 PostgreSQL 密码只存在于 Compose 环境变量；
- Docker image、WAL volume、目标恢复点和 RTO 是本地测试测量，不能外推到生产。

生产实现仍需独立 backup identity、WAL/object immutable retention、KMS、跨可用区/账户
恢复、provider receipt、审批者和真实 RPO/RTO。没有这些证据，不能把本 runner 结果写成
`production` 或 `DR ready`。

