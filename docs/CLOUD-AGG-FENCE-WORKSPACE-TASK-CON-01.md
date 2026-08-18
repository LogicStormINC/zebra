# CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01

## 状态

- 任务：Workspace / Task Mutation Fencing Conformance Audit
- 状态：`Done`
- Owner：`governance/planning`
- 分支：`codex/cloud-agg-fence-workspace-task-con-01`
- Worktree：`/Users/lukeding/.codex/worktrees/cloud-agg-fence-workspace-task-con-01/zebra-agent`
- 基线：`zebra-cloud-trench@29a79bf7`
- 父门：`CLOUD-AGG-FENCE-01` 继续 `Locked`
- 后续实现：`CLOUD-AGG-FENCE-TASK-01` 已在
  `codex/cloud-agg-fence-task-01` 完成并进入 `Done`
- 后续证据：`CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01` 已激活并进入
  `Done`
- 前置：`CLOUD-AGG-FENCE-CON-01`、`CLOUD-AGG-WORKSPACE-PG-01`、
  `CLOUD-AGG-TASK-PG-01` 均为 `Done`

本卡是只读治理审计。它不改变 Workspace/Task Core Port、PostgreSQL adapter、
migration、Compose runner、API、Worker、Runtime 或本地 SQLite；只登记已存在的
事务边界、证据适用范围和需要独立激活的缺口。

## 审计目标与边界

验证 Workspace projection、Task/Segment index 以及 Handoff 内的 rollover 是否：

- 在持久化边界绑定 canonical `WorkerMutationAuthority`、当前 `LeaseFence`、
  namespace、Session/Task identity 与 expected revision；
- 在同一 PostgreSQL transaction 内完成 Event、Session、Workspace、Task/Segment
  和 Handoff authority 的一致变更；
- 对 stale owner/epoch/token、namespace drift、pointer/stream drift 和事务异常
  保持 zero-write 或可回滚；
- 明确区分 Event-derived replay/management rebuild 与 Worker-owned mutation，避免
  读路径隐式写入。

## WT-01..WT-12 矩阵

| ID | 路径 | 结果 | 证据与边界 |
| --- | --- | --- | --- |
| WT-01 | Workspace Worker commit 接收 authority | PASS | `workspaces.py:56-71` 在同一连接校验完整 `LeaseFence`；`_validate_worker_commit` 校验 namespace/session。 |
| WT-02 | Workspace Event/Session/Workspace 原子提交 | PASS | `workspaces.py:72-104` 先 append canonical Event，再保存两个 projection；异常由连接 transaction 回滚。 |
| WT-03 | Workspace expected stream revision 与 Event-derived content | PASS | `workspaces.py:77-80,160-180` 拒绝 sequence/content drift；现有 Workspace PostgreSQL 矩阵覆盖 stale、replay、tamper。 |
| WT-04 | Workspace replay/save 边界 | PASS（非 Worker） | `save_workspace` 明确是 Event-derived replay；`save_workspace_in_transaction` 只允许不超过 `session_streams.current_version`，不冒充 Worker authority。 |
| WT-05 | Workspace namespace isolation | PASS | 查询和 upsert 均携带 deployment namespace；现有 Workspace 矩阵覆盖同 Session 跨 namespace 隔离。 |
| WT-06 | Workspace rollback/retry | PASS | 既有 projection fault 后 Event、Session、Workspace 全部回滚，合法 retry 可重新收敛。 |
| WT-07 | Task read path | PASS（非写） | `PostgresAgentTaskStore` 的 `get/list/segments/active/read_events` 只读；既有测试证明读取不会隐式 rebuild。 |
| WT-08 | Task rebuild/index maintenance | PASS（management boundary） | `rebuild_task_in_transaction` 使用 namespace 与 advisory Task lock，重建 Event-derived index；该管理写入不应被宣称为 Worker mutation。 |
| WT-09 | Task rollover concurrency/CAS | PASS（局部） | `_attach_segment` 使用 advisory lock、Task row `FOR UPDATE` 和 active-segment CAS；既有 Task 矩阵覆盖并发一胜者、唯一 task sequence、rollback。 |
| WT-10 | Handoff 组合 Workspace/Task transaction | PASS（组合路径） | `session_handoff_transactions.py:77-142` 锁 Lease/stream/workspace/Task lineage 并校验 reservation facts；`:145-169` 在同一事务写 parent/child projection 与 attach。 |
| WT-11 | Direct Task mutation authority | PASS（successor） | `FencedAgentTaskStorePort.attach_segment_for_worker` 与 PostgreSQL transaction helper 现已要求 `WorkerMutationAuthority`，校验 namespace、source Session、当前完整 LeaseFence 和 stream revision；legacy direct `attach_segment` fail closed。实现提交 `6a31929a`。 |
| WT-12 | Reproducible PostgreSQL evidence | PASS（successor） | `tests/compose/workspace_task/run-postgres-tests.sh` 在提交 `49a8c026` 的 PostgreSQL `17.5-alpine3.21` Compose service 上运行 Workspace、Task 和 migration focused matrix，`36 passed`，输出 `ZEBRA_WORKSPACE_TASK_POSTGRES_TEST_RESULT=PASS`，并清理 container、volume、network。 |

## 审计结论

结论为 `PASS`，任务由 `Review` 收口为 `Done`。Task direct mutation 的 authority
缺口已由 `CLOUD-AGG-FENCE-TASK-01` 的实现提交 `6a31929a` 修复，并以真实
PostgreSQL focused 回归验证；Workspace/Task 证据 successor 已在当前 checkout
提供可重放 runner。该结论不授权应用 Compose、Runtime selector 或 SQLite fallback。

## 必须单独登记的后续卡

1. `CLOUD-AGG-FENCE-TASK-01`（`Done`）：已为 Worker-owned Task rollover
   增加明确的 authority/fence 入口，补齐 namespace、owner、epoch、token、stale
   CAS 和 zero-write 回归；保持已有 Handoff helper 的 Owned path 不被重做。该卡
   已通过本地 `REVIEW-OK`，实现提交为 `6a31929a`；Task `23/23` 与
   Handoff/dispatch `24/24` PostgreSQL 回归均通过。
2. `CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01`（`Done`）：恢复仓库内可重放的
   PostgreSQL `17.5-alpine3.21` Workspace/Task focused runner，记录精确命令、计数、
   sentinel 和清理结果；实现提交 `49a8c026`，runner `36 passed` 并完成清理；不新增
   migration，不把历史临时脚本当作当前证据。

上述 successor 已完成并经过本地复核；`CLOUD-AGG-FENCE-01` 仍保持 `Locked`，不得将
Task direct mutation 接入运行态，也不得激活应用 Compose 或 Runtime selector。
