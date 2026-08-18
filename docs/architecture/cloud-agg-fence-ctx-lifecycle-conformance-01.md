# CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01

## 审计状态

- 日期：2026-08-03
- 状态：`Done`
- 父门禁：`CLOUD-AGG-FENCE-01` 继续保持 `Locked`
- 基线：`zebra-cloud-trench@9ec52b16`
- 性质：只读治理/审计；本卡不修改生产代码、测试、Schema 或 Migration

本卡把 Context lifecycle 的每一个写入口与现有 PostgreSQL authority/fence
合同逐项对齐。`agent-core` 的 Context lifecycle / mutation authority 合同、
`agent-storage` 的 PostgreSQL adapter/read composition、已有 focused tests 与
任务提交记录都是只读审计对象；本卡只写治理文档。

## 范围与事实源

Context 的云端权威由以下事实共同组成：

1. `session_events` 中的 compaction 与 capsule Events；
2. `context_capsule_artifacts` 中不可变的 Capsule payload、checksum 和 Event
   外键；
3. `active_context_projections` 中按 `(deployment_namespace, session_id)` 唯一
   的 active pointer；
4. 与同一事务提交的 Session/Workspace projections。

Migration v7 (`fenced_context_lifecycle`) 已提供上述约束；本卡不新增表，也不
改变 v1-v15 migration catalog。Context Materialization 是单事务 read-only
composition，不是 Context mutation authority。

## 逐方法 Conformance Matrix

| mutation / path | authority input | namespace / aggregate identity | fence 或 CAS validation | PostgreSQL predicate / lock | stale-owner / focused evidence | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `PostgresContextLifecycleStore.commit_worker_compaction` | `WorkerMutationAuthority`，包含完整 `LeaseFence` 与 expected stream revision | Store 固定 `deployment_namespace`；`_validate_worker` 同时校验 authority、Event、Session、Workspace 的 Session；Capsule id 与 Context Event 绑定 | `assert_current_lease_fence` 在同一连接验证 epoch/token/owner/expiry；Event 必须是 `CONTEXT_COMPACTED` 且为 expected revision + 1 | active pointer `FOR UPDATE`；Event 通过 `session_streams.current_version = sequence - 1` CAS；pointer 通过 expected capsule CAS；Session/Workspace 使用单连接 monotonic upsert | `test_worker_context_rejects_stale_fence_without_writes`、stale pointer、canonical retry、projection fault rollback、跨 Session FK | `PASS` |
| `commit_administrative_activation` | `AdministrativeMutationCAS`，无 Worker LeaseFence | authority namespace/session 与 Event 一致；Capsule 读取受 Store namespace 约束并校验同 Session | `require_administrative_projections` 锁 Session stream，检查 Session/Workspace 与 expected revision；active pointer `FOR UPDATE`；Event sequence CAS；Store 在写入边界校验 `CONTEXT_COMPACTED`、嵌套 capsule 和 recovery binding | Event、pointer、Session/Workspace 在一个连接事务；pointer 使用 expected capsule CAS，语义或 CAS 失败整体回滚 | `test_administrative_context_rejects_semantically_invalid_event` 三类零写入、namespace/projection drift、API recovery；真实 PostgreSQL focused matrix `18/18` | `PASS` |
| `persist_capsule_and_advance`（云端实现） | 无 authority 参数 | 不适用于云端 fenced aggregate | PostgreSQL 实现显式拒绝 | `NotImplementedError("PostgreSQL Context writes require explicit mutation authority")`，无写入 | Worker 无 authority 的 fallback 在 PostgreSQL fail closed；手工 compact 对 PostgreSQL 返回 503 | `PASS / fail closed` |
| `activate_capsule`（云端实现） | 无 authority 参数 | 不适用于云端 administrative CAS | PostgreSQL 实现显式拒绝 | `NotImplementedError("PostgreSQL Context activation requires administrative CAS")`，无写入 | 只有 SQLite compatibility branch 可调用；云端 recovery 走上面的 CAS 入口 | `PASS / fail closed` |
| `get_capsule` / `get_active_capsule` | 无 mutation authority；read-only | 每次查询带 Store 固定 namespace；active pointer 以 `(namespace, session_id)` 定位 | 不产生状态转换，不获取写锁 | 只读 SELECT；Capsule payload checksum 与 Event 存在性在读取时验证 | Context Materialization 的 read-only 约束与跨 namespace focused evidence | `PASS` |
| `PostgresContextMaterializationStore` | `ContextMaterializationRequest` 只携带 read expectations | namespace、Session、active capsule identity 和 Memory visibility 作为显式读边界 | 单一 `READ ONLY` transaction；stale revision/pointer fail closed | 无 INSERT/UPDATE/DDL；同一连接读取 Session/History/Capsule/Memory | `tests/compose/context_materialization/run-postgres-tests.sh` 已记录 `4 passed` | `PASS / read-only` |

## 缺口关闭记录

`commit_administrative_activation` 现在在同一持久化边界锁定 stream、校验
projection、执行 pointer CAS，并先验证 Event 语义完整性。Store 使用现有严格
`ContextCompactedPayload` 合同拒绝错误 Event type、缺失/错误嵌套 capsule 或
不一致的 `recovered_from_capsule_id`；冲突发生在任何 Event、pointer 或
projection 写入之前。

侧边栏 ChatGPT 对 successor 返回 `CLOSEOUT-OK`，批准其从 `Review` 到 `Done`
并允许本卡的 `BLOCK-GAP` 关闭；这不自动激活 `CLOUD-AGG-FENCE-01`。

`CLOUD-AGG-FENCE-CTX-SEMANTIC-01`（`Done`）

- Owned paths：`packages/agent-storage/src/agent_storage/postgres/context_lifecycle.py`、
  对应 `tests/agent_storage/` 与 `tests/api/` focused tests、
  `tests/compose/context_lifecycle/` 以及该卡治理记录；
- 目标：在 `commit_administrative_activation` 持久化边界拒绝非
  `CONTEXT_COMPACTED` Event，并要求 recovery payload 明确绑定被激活的
  `capsule_id`；不改变 API/Worker/Runtime 选择；
- 验收：错误 Event type、缺失/错误 capsule binding、错误 namespace、旧 stream
  revision、旧 active pointer 均零写入；正确 recovery 保持现有 HTTP contract；
  真实 PostgreSQL focused matrix 已通过 `18/18`，并已获 sidebar closeout。

## 结论与禁止范围

- `commit_worker_compaction` 的 Worker fence、Context identity、pointer CAS、
  Event/Session/Workspace 原子边界通过审计。
- 读取和 Materialization 不构成第二事实源，也不承担 Lease authority。
- `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01` 已 `Done`；审计记录与 semantic
  successor 的实现证据共同闭合了本 Context lifecycle 缺口。
- `CLOUD-AGG-FENCE-01` 仍为 `Locked`。继续禁止修改 `apps/api/`、
  `apps/worker/` 启动与 profile selection、`agent-runtime`、Provider HTTP、
  SQLite、Redis、Mem0、CopilotKit/Trench 或 application Compose，除非后续
  任务卡单独激活这些范围。
