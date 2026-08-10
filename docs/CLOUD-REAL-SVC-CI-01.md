# CLOUD-REAL-SVC-CI-01 Canonical real-service CI

本任务把已有的 PostgreSQL、Redis、应用和恢复 Compose runner 纳入 canonical
Quality workflow。每条 runner 是独立 matrix job：单条失败不会被其它 runner
遮蔽，artifact 中同时保留 stdout、结构化结果和 runner 自己产生的恢复证据。

## 覆盖范围

| runner | 实际边界 | 默认超时 |
| --- | --- | ---: |
| `application` | PostgreSQL + MinIO + API/Worker/migration Compose smoke | 600s |
| `live-fanout` | Redis Streams live publisher/trim/barrier contract | 300s |
| `recovery-pitr` | PostgreSQL physical base backup/WAL/PITR/Lease rebuild | 600s |
| `recovery-s3` | MinIO versioned backup copy/delete/restore + guarded PG ref | 600s |
| `recovery-restore` | PostgreSQL/Redis/MinIO fresh-instance restore composition | 600s |

权威清单是 `tests/compose/cloudline/runner_manifest.json`。包装器
`run_real_service.py` 只接受清单中的 runner，设置隔离 evidence 目录，流式复制
日志并写 `result.json`；超时会终止整个进程组，已有 Compose runner 的 `EXIT`
trap 负责清理容器、网络和 volume。

## CI 约束

- workflow 在 Ubuntu 22.04 上使用锁定的 uv/Python 3.12 和仓库现有 pinned Actions；
  每条 matrix job 有显式 timeout，`fail-fast: false` 只用于让其它边界继续产出证据，
  job 本身仍在 runner 失败时失败；
- artifact 使用 runner 名称区分，`if: always()` 保证失败日志保留；没有
  `continue-on-error` 或“可选通过”路径；
- runner 使用固定 Compose project name 和测试凭据，凭据只在 job 环境中存在；
  不使用生产 Secret，也不做 Kubernetes rollout；
- 这些 jobs 证明 local/Compose real-service contract，不等同于 managed service、
  Kubernetes 或 gVisor 生产证据。

## 本地运行

```bash
uv run python tests/compose/cloudline/run_real_service.py --list
uv run python tests/compose/cloudline/run_real_service.py \
  --runner live-fanout --evidence-dir /tmp/zebra-live-evidence
```

需要 Docker daemon、Compose 和已同步的 workspace。所有 runner 结束后都会清理
自己的 project；如果 Docker daemon 不可用，结果应为失败而不是 skipped。

## 本次验证

本 worktree 的静态 manifest/workflow 测试为 `2 passed`，Ruff/Mypy 和 YAML parse
均通过。Docker 29.4.0 / Compose 5.1.2 本地矩阵最终全部通过：

- application Compose：`ZEBRA_APPLICATION_COMPOSE_TEST_RESULT=PASS`；
- live-fanout：`1 passed`；
- PITR：`ZEBRA_PG_RECOVERY_PITR_TEST_RESULT=PASS`，`RPO=0.121072s`、
  `RTO=6.691080s`；
- S3：`ZEBRA_S3_RECOVERY_TEST_RESULT=PASS`；
- fresh restore：`ZEBRA_PG_RECOVERY_RESTORE_TEST_RESULT=PASS`。

第一次 application 尝试因 Docker Hub BuildKit OAuth EOF 失败，预拉取固定的
`docker/dockerfile:1.7` 后重跑通过；这是外部镜像服务瞬时故障，不被记作 runner
的成功。尚未执行远程 GitHub Actions，故不宣称 canonical job 已在 GitHub 上运行。
