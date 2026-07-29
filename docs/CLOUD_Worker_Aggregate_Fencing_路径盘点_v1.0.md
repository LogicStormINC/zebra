# Zebra Cloud Worker Aggregate Fencing 路径盘点 v1.0

## 1. 目的与结论

本文冻结 `CLOUD-AGG-FENCE-01` 的实现边界。目标不是把所有 SQLite 表逐一
翻译成 PostgreSQL，而是保证每个会推进云端执行状态的写事务都验证当前
deployment namespace、Lease epoch、fencing token 与 owner identity。

当前 PostgreSQL 层只覆盖 Event、Session Projection、Lease、Effect Ledger 与
Effect Outbox。其余 `ControlPlaneStores` 仍只有 SQLite 实现，且组合入口只有
`sqlite_control_plane_stores()`。因此当前代码具备显式注入的 Lease/Effect 云端
能力，但尚不是完整的多 Worker 控制平面。

必须保留三类不同语义：

1. Event 是 Session 执行事实源；Model Call、Tool Run、Workspace 与 Task 是可
   重建投影，不能升级成第二事实源。
2. Context capsule、Handoff envelope/dispatch、Provider continuation payload 与
   Artifact payload 包含 Event 外的权威状态，必须闭合各自事务。
3. Session History 与 Artifact list 是只读组合视图，不需要伪造 Lease 写入，
   但必须提供 namespace、授权范围和一致性快照。

API delivery/idempotency 属于 API command lane，不属于 Worker Lease lane。它要用
command claim、durable Effect 与 receipt/audit transaction 解决，不能硬套 Session
LeaseFence。

## 2. 统一 fencing 不变量

所有 Worker-owned PostgreSQL mutation 必须满足：

- mutation 输入携带 deployment namespace 与完整 `LeaseFence`；
- 在持有相关行锁的同一 PostgreSQL transaction 内读取并验证 epoch、token、
  owner 与有效期；
- stale epoch、token 或 owner 任一不匹配时零业务写入；
- expected stream sequence 或 projection revision 参与 CAS，旧投影不得覆盖新投影；
- transaction 内任一步故障时全部回滚；
- 重试同一内容幂等，复用同一 identity 写入不同内容时 fail closed；
- API administrative CAS 与 Worker fenced mutation 使用明确不同的入口；
- real PostgreSQL 测试覆盖 current、stale epoch、stale token、stale owner、并发、
  namespace 与故障注入。

Core contract 使用 `WorkerMutationAuthority` 表示 Worker transaction 输入，字段为
deployment namespace、Session、完整 `LeaseFence` 与 expected stream revision。
`AdministrativeMutationCAS` 使用相同的 namespace/Session/stream CAS，但类型上禁止
LeaseFence。空 Event stream 的 expected revision 是 `-1`；低于 `-1` 非法。聚合专用
revision（如 active capsule id 或 Workspace binding revision）继续留在各聚合 request，
不建立 `str | int | None` 的万能 revision 类型。

## 3. 权威路径清单

| 聚合族 | 当前 Port / 实现 | 权威性 | 当前事务与缺口 | 目标边界 |
| --- | --- | --- | --- | --- |
| Context lifecycle | `ContextLifecycleStorePort` / `SQLiteContextLifecycleStore` | capsule artifact、events、active pointer 共同权威 | SQLite 内部原子，但后续 Session/Workspace 投影分事务；写方法无 LeaseFence | capsule、events、active pointer 与必要投影在同一 fenced transaction 或可确定性重放 |
| Workspace | `WorkspaceProjectionStorePort` / `SQLiteWorkspaceProjectionStore` | Event 派生投影 | 无条件 upsert，无 sequence CAS、namespace、fence；Event 与投影分事务 | fenced projection CAS；旧 sequence 不覆盖新值；与 Event 写入原子或提供确定性 replay |
| Agent Task | `AgentTaskPort` / `SQLiteAgentTaskStore` | Event、Projection、Lineage 派生跨 Segment 索引 | 读取可触发 rebuild；序号依赖 SQLite 全局锁；handoff 内部能共用 connection | 只读查询不写；connection-scoped mutation 可加入 Event/Handoff transaction |
| Handoff | `SessionHandoffPort` / `SQLiteSessionHandoffStore` | envelope、lineage、parent/child events 与 rollover 共同权威 | 现有 SQLite transaction 边界完整，PostgreSQL 不存在 | 整体迁移，保留 source facts CAS、child 建立、Task rollover 与 dispatch outbox 原子性 |
| Handoff dispatch | `HandoffDispatchStorePort` / `SQLiteHandoffDispatchStore` | delivery claim/ack 权威 | 只有 worker id 与过期时间，无 epoch/token/claim identity | `SKIP LOCKED` claim；claim identity 或 child LeaseFence 阻止旧实例 ack |
| Model Call | `ModelCallStorePort` / `SQLiteModelCallStore` | `MODEL_RESPONSE_RECEIVED` Event 的派生投影 | 无条件 upsert；Event/index/projections 分事务 | fenced、内容一致的幂等 projection update，可从 Event replay |
| Tool Run | `ToolRunStorePort` / `SQLiteToolRunStore` | tool completion/failure Event 的派生投影 | payload、Event、index、projections 最多分成六个事务 | 与 Event/replay 协议闭合；同 key 不同内容拒绝 |
| Provider continuation | `ProviderContinuationStorePort` / `SQLiteProviderContinuationStore` | opaque bytes 是额外权威 payload，selection Event 是引用 | artifact 先写、Event 后写；无 fence；tenant 固定为 `local` | tenant/namespace 隔离、fenced store、引用完整性、orphan 清理；sweep 使用管理权限 |
| Session history | `SessionHistoryPort` / `SQLiteSessionHistory` | Event + Projection 只读视图 | 无 PostgreSQL adapter；`scoped(None)` 可能覆盖整个 backend | PostgreSQL 一致性只读快照与 allowed session / tenant scope；不新增 Lease mutation |
| Artifact payload | `ArtifactPayloadStorePort` / `SQLiteArtifactPayloadStore` | metadata 与 bytes 是权威 payload | 本地文件与 SQLite metadata 不原子；冲突可能先覆盖文件；无 fence/namespace；跨 Worker 不可见 | PostgreSQL metadata + object storage；put/finalize/compensation；fenced lifecycle |
| Artifact list | `SessionArtifactReadPort` / `SQLiteArtifactStore` | Model/Tool 投影组合视图 | 无独立 PostgreSQL 组合；遗留 `ArtifactStorePort` 无调用者 | 不新建 Artifact 权威表；复用 PostgreSQL Model/Tool 投影并保持 API contract |
| Effect payload linkage | `FencedEffectToolGateway` + PostgreSQL Effect Outbox | intent/outbox 权威，payload 当前在本地 Store | payload 先落本机，schedule 失败遗留 orphan；其他 Worker 可能读不到 | intent/outbox 不引用不可读 payload；失败可补偿；claim Worker 跨进程可读 |
| Delivery audit / idempotency | `DeliveryAuditStorePort`、`IdempotencyStorePort` / SQLite | API command receipt 与 audit | get-then-insert 竞态；外部动作、receipt、audit 分事务；无稳定 audit id | PostgreSQL command claim/complete；外部动作走 durable Effect；receipt 与 audit 原子 |

## 4. 关键调用和事务接缝

### 4.1 Worker Event 记录链

`DurableHarnessEventRecorder` 当前按顺序执行 ownership check、Event append、
Model/Tool index、Session projection、Workspace projection。每一步使用独立 Store
transaction。Lease 可能在检查后失效，任一步崩溃也会留下部分投影。

首个实现合同必须定义 PostgreSQL connection-scoped mutation/replay seam；不能只在
各 Store 方法前再调用一次 `ownership_check()`。

### 4.2 Context

Worker 入口位于 `apps/worker/src/zebra_agent_worker/context_lifecycle.py`，API 管理入口
位于 `apps/api/src/zebra_agent_api/session_context_control.py`。Worker 写入需要
LeaseFence；API compact/recover 只能在 Session 非 running 且 expected stream 未变化
时使用 administrative CAS。

### 4.3 Handoff

API 创建入口位于 `apps/api/src/zebra_agent_api/session_handoff.py`，Worker dispatch
恢复位于 `apps/worker/src/zebra_agent_worker/session_handoff.py`。PostgreSQL 实现必须
整体复刻现有 `SQLiteSessionHandoffStore.commit()` 的原子边界，不得把 Handoff、
Workspace、Task 与 Dispatch 拆成顺序提交。

### 4.4 Payload

Tool output 与 Effect 输入会先写 `ArtifactPayloadStorePort`。云端实现应复用 Docker
依赖栈中的对象存储能力。对象 key 布局、SDK 与 provider 保持未选择；
[`ADR-017_Artifact对象存储与元数据权威边界.md`](./ADR-017_Artifact对象存储与元数据权威边界.md)
先冻结 object-store capability、失败补偿与管理恢复合同。

## 5. 任务 DAG

```text
CLOUD-AGG-FENCE-CON-01
├── CLOUD-AGG-WORKSPACE-PG-01
├── CLOUD-AGG-TASK-PG-01
├── CLOUD-AGG-CTX-PG-01
├── CLOUD-ART-OBJ-CON-01 ──> CLOUD-ART-PAYLOAD-PG-01
└── CLOUD-PROVIDER-CONT-PG-01

WORKSPACE + TASK + CON ──> CLOUD-AGG-HANDOFF-PG-01
WORKSPACE + MODEL/TOOL prerequisites ──> CLOUD-MODEL-TOOL-PG-01
ART-PAYLOAD + EFFECT-OUTBOX ──> CLOUD-EFFECT-PAYLOAD-ATOMIC-01
MODEL/TOOL ──> CLOUD-SESSION-HISTORY-PG-01 and CLOUD-ART-READ-COMP-01
Effect dispatch + PostgreSQL composition ──> CLOUD-DELIVERY-TXN-PG-01
all adapters ──> CLOUD-CONTROL-PLANE-PG-01 ──> CLOUD-AGG-FENCE-01
```

`postgres/migrations.py` 与 `composition.py` 是顺序执行的协调热点。即使两个领域卡的
业务模块互不重叠，也不得同时声明对这些文件的写所有权；后一张卡必须基于前一张已
集成的迁移序列。

## 6. 拆卡验收摘要

### CLOUD-AGG-FENCE-CON-01

冻结 Worker mutation authority 与 administrative CAS。类型测试必须使缺少
namespace/fence 的 Worker write 不可表达。此卡不实现通用 Unit of Work、修改现有
Store Ports 或实现 PostgreSQL adapter；每个后续 coarse-grained aggregate Port 在其
Adapter transaction 内消费该 authority。

### CLOUD-AGG-WORKSPACE-PG-01

实现 Workspace PostgreSQL 投影 CAS。真实数据库验证 stale fence 零写入、旧
sequence 不覆盖、Event/Session/Workspace 全提交或可重放、namespace 隔离。

### CLOUD-AGG-TASK-PG-01

实现只读无副作用的 Task 查询与 connection-scoped rollover。验证并发 successor
仅一个成功、task event sequence 唯一、rebuild 幂等。

### CLOUD-AGG-CTX-PG-01

实现 capsule、events 与 active pointer 的 PostgreSQL 聚合。验证 duplicate
sequence 回滚、active pointer CAS、内容幂等/冲突、stale fence 与 API CAS。

### CLOUD-AGG-HANDOFF-PG-01

实现 Handoff 整体聚合与 fenced dispatch。验证 source 任一 revision/fence 改变时
零落盘、并发 successor 唯一、完整 crash rollback、`SKIP LOCKED` 与旧 claim 拒绝。

### CLOUD-MODEL-TOOL-PG-01

实现 Event 派生索引与 replay。验证同 Event 幂等、同 key 异内容拒绝、stale Worker
不能覆盖新 owner、Event 已提交而索引失败可安全修复。

### CLOUD-PROVIDER-CONT-PG-01

实现 continuation payload 的 tenant/fence/TTL/SHA/soft-delete parity。验证引用不
指向缺失 payload、跨 Worker 恢复、跨 tenant 拒绝及 sweep 管理语义。

### CLOUD-ART-OBJ-CON-01 / CLOUD-ART-PAYLOAD-PG-01 / CLOUD-EFFECT-PAYLOAD-ATOMIC-01

ADR-017 先冻结 stable identity、metadata/bytes authority、staged/finalize/
compensate 与管理恢复。随后实现共享对象 payload，再闭合 Effect intent 引用。验证
同 ID 内容冲突不覆盖、metadata/object 故障补偿、跨 Worker 读取、stale fence 无
payload/intent，以及 schedule 失败无永久 orphan。

### CLOUD-SESSION-HISTORY-PG-01 / CLOUD-ART-READ-COMP-01

只实现 PostgreSQL read composition，不增加事实源。验证 SQLite/PG 合同一致、稳定
排序、分页上限、redaction、namespace 与 allowed-session 隔离。

### CLOUD-DELIVERY-TXN-PG-01

实现 API command claim/receipt/audit transaction，并把 SCM 等外部动作接到 durable
Effect。验证并发同 key 单 owner、不同 request 冲突、crash 恢复不重复外部动作、
receipt/audit 无半状态。

### CLOUD-CONTROL-PLANE-PG-01

最后组装完整 PostgreSQL `ControlPlaneStores` 与显式 backend selection。默认本地
profile 保持 SQLite；云端 profile 缺少任一 adapter 时启动失败，不允许静默混用。

## 7. 解锁条件

`CLOUD-AGG-FENCE-01` 只有在上述实现卡分别提供真实 PostgreSQL 证据、完整云端
composition 通过故障/恢复矩阵，并由维护者批准 runtime selection 后才能从 Locked
转为 In Progress。本文完成不代表生产 cutover、exactly-once 外部执行或 tenant
模型已经完成。
