# Cloud Delivery Transaction PostgreSQL 计划

## 状态

- 任务：`CLOUD-DELIVERY-TXN-PG-01`
- 状态：`Done`
- 分支：`codex/cloud-delivery-txn-pg-01`
- 决策来源：侧边栏 ChatGPT 已批准 storage-only 激活

## 目标

在 PostgreSQL 中建立 API-neutral 的 delivery transaction receipt/audit 边界：同一
个 action/idempotency key 只能有一个确定的请求事实，重试必须返回同一 receipt，
请求 hash 不一致必须拒绝。该边界只负责持久化和状态转换，不负责 HTTP、API
响应序列化或 Worker 调度。

现有 `CloudControlPlane` 的 `idempotency` 与 `delivery_audit` Port 是组合入口；
本任务只在其上补齐原子事务所需的 Core contract/state model 和 PostgreSQL
实现。现有本地 SQLite `ControlPlaneStores` 保持不变。

## 事务不变量

1. `(deployment_namespace, action, idempotency_key)` 是唯一 receipt identity。
2. 首次请求写入 request hash、状态和 response receipt；同 key 同 hash 重放同一
   receipt；同 key 不同 hash 抛出冲突。
3. receipt 与 delivery audit 要么同一事务提交，要么都不可见；禁止半状态。
4. 外部 effect 不在本任务内执行。崩溃恢复只能重放已持久化 receipt，不得凭空
   再次执行外部动作。
5. namespace、action、key 和状态转换均必须在信任边界处校验；不得从 DSN 推断
   namespace，也不得跨 namespace 查询。

## 允许范围

- `packages/agent-core/`：delivery transaction contract、state model、Ports。
- `packages/agent-storage/`：PostgreSQL adapter、必要 migration、focused tests。
- 本计划及 `AGENT_TASKS.md`、`PROGRESS.md`、`task_plan.md`、`WORKLOG.md`。

## 明确非目标

本任务不修改 `apps/api/`、`apps/worker/`、`packages/agent-runtime/`、Provider
HTTP、Desktop、SQLite、Redis、Mem0、CopilotKit/Trench、application Compose 或
生产切换。API command wiring、Worker ownership、Lease fencing 总门禁和 Runtime
profile selection 必须由后续独立任务完成。

## 验收

- Core contract 与已批准的 `CloudControlPlane`、`WorkerMutationAuthority` 边界
  对齐，且无运行时依赖。
- PostgreSQL migration 可重复执行并保持 checksum/name 不变。
- 并发相同 key、hash mismatch、crash/retry、receipt/audit 原子性均有确定性或
  Compose 测试证据。
- 已完成 Control Plane/PostgreSQL adapter 回归通过，根目录本地 SQLite 行为无
  变化。

## 已实现切片

- Core 新增 `DeliveryTransactionState`、状态转换校验、`DeliveryTransactionRecord`
  和 `DeliveryTransactionPort`；`claim`、`mark_processing`、`mark_unknown`、
  `mark_failed`、`commit`、`replay`、`get_state` 的结果契约保持 API-neutral。
- PostgreSQL v15 新增 `delivery_transactions`，以
  `(deployment_namespace, action, idempotency_key)` 唯一约束提供单 owner；
  `claim_token` 是提交时的 fencing token。v14 receipt/audit 表保持不变。
- `PostgresDeliveryTransactionStore.commit()` 在同一个 PostgreSQL connection
  transaction 内写 receipt、audit 并推进 `COMMITTED`；任意写入失败都会回滚，
  `UNKNOWN`/`FAILED` 不允许自动 replay。
- 未修改 `apps/api/`、`apps/worker/`、本地 SQLite 或任何 Runtime/Provider/Mem0/
  Redis/CopilotKit/Trench 路径；后续 API/Worker wiring 仍是独立任务。

## 验证证据

- `tests/agent_core/test_delivery_transaction.py`：`2 passed`。
- `tests/compose/delivery_transaction/run-postgres-tests.sh`：真实 PostgreSQL
  Compose `12 passed`，覆盖并发单 owner、hash 冲突、原子回滚、replay、UNKNOWN
  与 stale token；结果 `ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=PASS`。
- `tests/compose/control_plane/run-postgres-tests.sh`：Control Plane 回归
  `11 passed`；结果 `ZEBRA_CONTROL_PLANE_POSTGRES_TEST_RESULT=PASS`。
- changed-file Ruff、Core/Storage changed-file Mypy、`git diff --check` 均通过。

## 关闭

侧边栏 ChatGPT 已复核实现与全部证据并批准从 `Review` 关闭为 `Done`。
API/Worker command wiring、Runtime/backend selection 和 production cutover 保留为
后续独立任务。
