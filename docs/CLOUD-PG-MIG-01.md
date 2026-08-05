# CLOUD-PG-MIG-01 — SQLite 快照与 PostgreSQL Cutover

> 状态：`Done`
> 分支：`codex/cloud-pg-mig-01`
> Worktree：`/Users/lukeding/Desktop/playground/2026/product/zebra-agent-cloud-pg-mig-01`

## 当前切片

本卡先交付迁移链的可复用基础合同。实现按职责拆为
`migration_snapshot.py`（快照格式/校验）、`migration_context.py`
（Context capsule/pointer 回放）、`migration_handoff_rows.py` 与
`migration_handoff.py`（Handoff authority/lineage 回放）、
`migration_idempotency.py`（control-plane receipt 回放）、
`migration_memory.py`（governed Memory authority 回放）、
`migration_delivery_audit.py`（Delivery Audit 顺序回放）、
`migration_cutover.py`（Cutover 门禁）和 `migration_recovery.py`（导入编排），
各源文件均保持在 300 行目标以内：

1. 对 SQLite 文件执行只读一致性快照，按表名、列定义和规范化 JSONL
   记录排序，生成行数、表计数和 SHA-256 manifest。UTF-8 文本按 NFC
   规范化，BLOB 以明确的 base64 标记编码；源数据库不执行写操作。
2. 在 PostgreSQL migration v16 中加入 namespace-scoped
   `control_plane_cutovers`，以 `PREPARED -> VERIFIED -> ACTIVE` 单向状态机和
   `(deployment_namespace)` 唯一 ACTIVE 索引约束切换。`run_guarded` 在同一
   transaction 中先检查 namespace、cutover id、manifest digest 和 ACTIVE
   状态，再调用写操作；检查失败或操作抛错时写入为零。

3. 受限 importer 只接受已校验的 Event/Projection snapshot：先按连续 sequence
   导入 Event，再用 Event 重建 Session、存在 `task_prepared` 事实的 Workspace、
   Task index、Model/Tool projections，以及经过 payload checksum、compaction
   Event 和 active pointer 绑定验证的 Context capsule。Handoff operation、
   immutable envelope 和 pending/完整 claimed dispatch 在 Event 之后回放；
   `session_lineage` 不直接写入 PostgreSQL，而是在 Task/Segment 重建后逐行校验。
   SQLite idempotency receipt 经过 action/key/request/status/JSON object/timestamp
   校验后写入 namespace-scoped control-plane 表。Governed Memory 经过内容、
   creation/provenance digest、scope、supersession 和 source Event range 校验后
   写入 PostgreSQL authority 表。Delivery Audit 只接受 snapshot v2 的显式
   source rowid，按源读取顺序写入 PostgreSQL 自增 `audit_id`。
   SQLite 中没有权威 ACK 时间的 `acked` dispatch、非受支持的权威表、非空目标、
   错误 identity 和不连续 sequence 都 fail closed。

这些模块只建立迁移证据边界，不改变 API/Worker profile 选择，也不把 SQLite、
Redis 或 Mem0 变成云端事实源。

## 已验证

- 本地快照/完整性单测：`2 passed, 21 skipped`（无外部 PostgreSQL 时 PG 用例跳过）。
- PostgreSQL 17.5 Compose runner：`29 passed`，输出
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS`。
- runner 清理了容器、volume 和 network；迁移目录 v1-v16 的 checksum 与并发
  migration runner 一并复核。
- changed-path Ruff、strict Mypy、`git diff --check` 通过；迁移模块已按职责拆分，
  避免继续堆叠在单一文件中。
- 新增三项 legacy authority 零写入回归：快照包含 `artifact_payloads`、
  `effect_ledger` 或 `provider_continuation_artifacts` 时，在 Event 写入前拒绝，
  PostgreSQL 目标保持为空；回归同时重新加载被拒绝的快照，确认记录和
  manifest 未改变，保留它作为 quarantine/rebuild 输入。

## 后续门禁

- 真实 cloud runtime 的 ACTIVE 写门禁、SQLite fallback removal 和生产切换仍是
  独立运行态门禁；本卡不授权这些动作。
- PostgreSQL logical backup/restore、physical PITR、Artifact 对象恢复、Redis/Mem0
  rebuild、Outbox reconcile、multi-Worker drill 和生产 RPO/RTO 属于
  `CLOUD-REC-*` 子卡；`CLOUD-REC-BACKUP-01` 与 `CLOUD-REC-RESTORE-01` 已完成
  开发环境备份/恢复证据，`CLOUD-REC-DRILL-01` 正在推进。

### 剩余映射审计

以下三类旧表不会被合成字段后写入云端 authority；每一项都需要独立的导出合同
或历史事实补齐后才能激活下一子任务：

| SQLite source | PostgreSQL target | 当前阻塞证据 |
| --- | --- | --- |
| `artifact_payloads` | `artifact_payload_metadata` | 缺少 expected stream revision、Worker lease、幂等/request hash、Event/object version；本地 `active` 也不能无损映射到云端 lifecycle。 |
| `effect_ledger` | `effect_outbox` | 缺少 execution/dispatch identity、request hash、payload Artifact、intent/terminal Event 和 claim/evidence；状态值相似不等于事实绑定。 |
| `provider_continuation_artifacts` | `provider_continuation_artifacts` | 缺少 deployment/authority scope、selection Event、幂等/request hash 和 accepted LeaseFence；事件 payload 不能补出历史租约。 |

字段级结论如下；“可由 Session/Event 推导”只有在 legacy export 同时提供明确
绑定且能通过 CAS 校验时才可接受，当前快照没有该证据：

| Source | 直接存在且可复用 | 不可从旧行证明的 target authority |
| --- | --- | --- |
| `artifact_payloads` | artifact/session identity、kind/mime、sha256、size、retention/prune 时间 | `intended_event_sequence`、`expected_stream_revision`、idempotency/request hash、reservation Lease、Event/object version、云 lifecycle transition evidence |
| `effect_ledger` | root session、ledger key、attempt、legacy status/result、timestamps | execution/dispatch identity、request hash、payload Artifact、intent/terminal Event、claim Lease/evidence、retry identity |
| `provider_continuation_artifacts` | session/reference/provider/model/capability、payload/source digest、expiry/delete 时间 | trusted deployment/authority scope、continuation selection Event、idempotency/request hash、accepted LeaseFence；`tenant_id` 不能直接提升为 namespace authority |

Delivery Audit 是本卡中已解决的例外：snapshot v2 显式导出
`__zebra_source_rowid`，按源顺序插入并验证 PostgreSQL `audit_id`；rowid 仅作
迁移顺序证据，不作业务身份。

三类阻塞表现在由 focused PostgreSQL 回归锁定为同一 fail-closed 边界：它们不是
“先导入再补字段”的暂存 authority，任何一类出现都会阻止整个快照导入，并在
Event 写入前保持目标零写入。原始记录仍保留在带 manifest 的 SQLite snapshot 中，
可供后续版本化 export 或人工 quarantine/rebuild 使用。

允许的后续路径是先扩展版本化 snapshot/export 合同并生成可审计的历史证据，
或建立明确的 legacy quarantine/rebuild 流程；在此之前 importer 对这些表继续
返回 unsupported-authority error 并保持目标事务零写入。

后续治理父卡 `CLOUD-PG-MIG-LEGACY-CON-01` 已 `Done`：Artifact、Effect/Delivery
和 Provider continuation 子卡均已按独立 Owned paths 完成并合并。当前卡不授权运行态
切换或把任一 quarantine 直接写入 cloud authority。

## 设计边界

- PostgreSQL Event/Projection 与 fenced aggregate 仍是 Zebra 的事实源。
- Mem0 只能从 confirmed governed Memory 重建；Redis 只能从 Event replay
  重建，二者不参与 cutover authority。
- `ACTIVE` 不是生产准入。生产切换仍需 `CLOUD-REC-01` 的 backup/restore/drill
  证据及独立审批。
