# CLOUD-PG-MIG-01 — SQLite 快照与 PostgreSQL Cutover

> 状态：`In Progress`
> 分支：`codex/cloud-pg-mig-01`
> Worktree：`/Users/lukeding/Desktop/playground/2026/product/zebra-agent-cloud-pg-mig-01`

## 当前切片

本卡先交付迁移链的两个可复用基础合同：

1. 对 SQLite 文件执行只读一致性快照，按表名、列定义和规范化 JSONL
   记录排序，生成行数、表计数和 SHA-256 manifest。UTF-8 文本按 NFC
   规范化，BLOB 以明确的 base64 标记编码；源数据库不执行写操作。
2. 在 PostgreSQL migration v16 中加入 namespace-scoped
   `control_plane_cutovers`，以 `PREPARED -> VERIFIED -> ACTIVE` 单向状态机和
   `(deployment_namespace)` 唯一 ACTIVE 索引约束切换。`run_guarded` 在同一
   transaction 中先检查 namespace、cutover id、manifest digest 和 ACTIVE
   状态，再调用写操作；检查失败或操作抛错时写入为零。

这些模块只建立迁移证据边界，不改变 API/Worker profile 选择，也不把 SQLite、
Redis 或 Mem0 变成云端事实源。

## 已验证

- 本地快照/完整性单测：`2 passed, 5 skipped`（无外部 PostgreSQL 时 PG 用例跳过）。
- PostgreSQL 17.5 Compose runner：`13 passed`，输出
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS`。
- runner 清理了容器、volume 和 network；迁移目录 v1-v16 的 checksum 与并发
  migration runner 一并复核。
- changed-path Ruff、strict Mypy、`git diff --check` 通过。

## 尚未完成

- 将 canonical snapshot 中的 Event/Projection 及其他权威 Store 数据导入
  PostgreSQL，并在导入前执行 restricted identity、empty-schema、checksum、
  Event ordering 和 projection rebuild 校验。
- 接入真实 cloud runtime 的 ACTIVE 写门禁、SQLite fallback removal、完整
  migration replay 证据；这些完成前不能关闭本卡。
- PostgreSQL backup/PITR、Artifact 对象恢复、Redis/Mem0 rebuild、Outbox
  reconcile、multi-Worker drill 和生产 RPO/RTO 属于其他 `CLOUD-REC-*` 卡。

## 设计边界

- PostgreSQL Event/Projection 与 fenced aggregate 仍是 Zebra 的事实源。
- Mem0 只能从 confirmed governed Memory 重建；Redis 只能从 Event replay
  重建，二者不参与 cutover authority。
- `ACTIVE` 不是生产准入。生产切换仍需 `CLOUD-REC-01` 的 backup/restore/drill
  证据及独立审批。
