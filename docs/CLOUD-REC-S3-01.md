# CLOUD-REC-S3-01 Artifact object backup/restore 演练

| 项目 | 结论 |
| --- | --- |
| 证据范围 | `production-like`、`local-only` |
| Provider | MinIO versioned bucket（S3-compatible adapter） |
| 备份来源 | 独立 `zebra-artifacts-backup` bucket 的 provider-side copy |
| 权威 ref | PostgreSQL `artifact_payload_metadata.object_version` |
| 生产含义 | 不构成跨区域复制、生产 retention、DR 或 object restore 批准 |

本 runner 是 `CLOUD-REC-S3-01` 的隔离证据；总体准入由
[`CLOUD-REC-PROD-CON-01`](./CLOUD-REC-PROD-CON-01.md) 控制，PostgreSQL PITR
由 [`CLOUD-REC-PG-PITR-01`](./CLOUD-REC-PG-PITR-01.md) 单独验证。

## 1. 证据流程

`tests/compose/recovery_s3/run-s3-recovery.sh` 启动临时 PostgreSQL 与 MinIO，
初始化两个 versioned bucket：

1. migration、epoch、Session Event、Lease 和 finalized Artifact metadata/ref 写入
   PostgreSQL；source object 通过 `S3ArtifactObjectStore` 写入，并验证 checksum、size
   和 `zebra-*` metadata；
2. 使用 provider-side `CopySource + VersionId` 把 source version 复制到独立 backup
   bucket。备份验证读取 provider object，不读取 Worker 本地目录；
3. 精确删除 source object version，确认 source 当前读取为 `NOT_FOUND`；
4. 用 backup bucket 的 version 读取 bytes 和 metadata，再写回 source bucket，验证
   新 version 的 checksum/size；
5. 在 PostgreSQL 上先确认旧 ref，随后执行带 namespace/artifact/session/status/旧
   version 条件的 guarded recovery repair，把 ref 指向 restored version，并再读回
   验证；
6. 验证 other namespace 的 PG metadata 和 object key 均不可见，最后清理 Compose
   containers/volumes。

Runner 的 recovery repair 是 evidence-only 的受控 SQL 模拟，不是新的 runtime API。
生产实现必须由独立 restore identity、epoch/fence、管理审计和审批流程承载；不能把
脚本中的直接 repair SQL 复制到 API/Worker。

## 2. 执行与输出

```bash
bash tests/compose/recovery_s3/run-s3-recovery.sh
```

成功输出必须包含：

```text
S3_RECOVERY_SEED=PASS ...
S3_RECOVERY_CLEAR=PASS source_version_deleted=True local_payload_used=False
S3_RECOVERY_VERIFY=PASS ...
ZEBRA_S3_RECOVERY_TEST_RESULT=PASS
S3_RECOVERY_CLEANUP=PASS containers=0 volumes=0 temporary_credentials=0
```

保留机器可读报告：

```bash
ZEBRA_S3_RECOVERY_EVIDENCE_DIR=/tmp/zebra-s3-recovery-evidence \
  bash tests/compose/recovery_s3/run-s3-recovery.sh
```

报告 `schema_version` 为 `zebra.recovery.s3.evidence.v1`，记录 source/backup/restored
object version、SHA-256、size、metadata verification、PG ref old/new version、guarded
affected rows、namespace isolation、是否使用本地 payload 和 cleanup 状态。

## 3. 验收与限制

- backup version 与 source version 不同，且 source version 在 restore 前确实被删除；
- restored bytes 与 immutable expectation 完全一致，PG ref 最终指向 restored version；
- Artifact metadata、object key 和 PG query 都带 deployment namespace；other namespace
  读取必须为空/`NOT_FOUND`；
- 临时密码只存在于 Compose 环境变量，失败也执行 `down --volumes --remove-orphans`；
- MinIO 单机、同账户、同 region 的 timing 不能外推到生产对象 retention、跨区复制或 RPO。

