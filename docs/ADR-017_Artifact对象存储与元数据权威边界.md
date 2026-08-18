# ADR-017：Artifact 对象存储与元数据权威边界

| 字段 | 值 |
|---|---|
| 状态 | Accepted for contract; implementation Locked |
| 日期 | 2026-07-29 |
| 决策者 | Maintainer direction + Zebra architecture baseline |
| 任务 | `CLOUD-ART-OBJ-CON-01` |
| 影响范围 | Artifact payload、对象 metadata、Worker fenced lifecycle、management recovery |

## 背景

当前 local profile 的 `SQLiteArtifactPayloadStore` 把 SQLite metadata 与本地文件
bytes 组合为一个 Artifact payload authority。它适合单机，但文件写入与 metadata
提交不能原子化，没有 namespace 或 Lease fence，且其他 Worker 无法读取本机文件。

云端目标要求 S3-compatible storage 保存 bytes，而 PostgreSQL 保存 metadata、
checksum、retention、manifest 和 lineage。对象存储的网络操作无法与 PostgreSQL
提交构成一个物理事务，因此必须先冻结可恢复的 staged/finalize/compensate 合同。

本文只冻结边界与失败语义。它不实现 PostgreSQL schema、对象 adapter、API route、
runtime profile 或 provider SDK。

## 决策

### 1. Artifact payload 的权威边界

一个云端 Artifact payload 的 authority 由两部分共同组成：

- PostgreSQL metadata：namespace、Session/resource binding、artifact identity、
  checksum、size、content type、retention、lifecycle、manifest 和 lineage；
- object bytes：与该 metadata 所声明 digest 和 size 相符的不可变 payload。

Event-derived Model Call、Tool Run、Session Artifact list 和任何 API response 都是
投影或读取视图，不得成为 bytes 或 lifecycle 的第二事实源。Redis、temporary URL 和
object-store provider metadata 也不是 Zebra authority。

### 2. Identity、locator 与访问 URL

`artifact://<artifact_id>` 是稳定的 Zebra identity，可被 Event、projection、trace
和受控 provenance 引用。解析它必须经 namespace-scoped PostgreSQL metadata lookup；
URI 本身不携带访问权，也不得作为 object key。

object bucket/key 或等价 locator 是 adapter 内部细节。它必须受 namespace 隔离，
但不得暴露给 Model、Event、projection、API artifact list 或普通客户端。具体 key
编码留给后续 adapter card，且不得从用户文件名、未清洗输入或 secret 推导可猜测路径。

temporary access URL 是授权后的短期 capability，不是 identity：

- 仅在 namespace、resource binding、policy 和 finalized metadata 均已验证后签发；
- 不写入 Event、projection、Artifact metadata、log、trace、model context 或前端持久化；
- 过期、缺失或删除的 object 不得获得 URL，也不得由旧 URL 推断新对象位置。

local `access_uri` 仅是 local filesystem locator 的兼容字段，不能被提升为云端
durable identity。

### 3. Opaque external references

Model/Tool Event payload 中已有的非 `artifact://` `artifact_uri` 是 opaque external
reference。Model/Tool projection 只能保留该字符串；replay 不得读取、复制、探测、
签名或为它创建 payload metadata。API read composition 仍将它表示为
`external_reference`，而不是 Zebra 可读取 bytes。

### 4. Provider-neutral object capability

后续 object adapter 必须向 Zebra 提供下列能力，不泄露 MinIO、AWS S3 或其他 provider
的对象类型、endpoint、credential 或错误模型：

| 能力 | 合同 |
|---|---|
| conditional put | 同一内部 locator 的不同内容绝不覆盖；返回可供验证的对象版本或等价证据。 |
| head/verification | 区分不存在、权限/transport failure 与已存在但 size/checksum 不匹配。 |
| verified read | 仅按 metadata 产生的内部 locator 读取，并校验预期 digest/size。 |
| conditional delete | 依据已验证的对象版本或等价证据幂等删除，不能删除不同 payload。 |
| temporary read capability | 只为已授权、finalized 的对象签发有限期读取 capability。 |

adapter 可使用任何满足这些语义的 S3-compatible provider。SDK、认证方式、endpoint、
bucket policy、multipart strategy 和具体 key layout 均不在本文选择范围内。

### 5. Fenced staged/finalize/compensate lifecycle

Worker 发起的 metadata mutation 必须在其 PostgreSQL transaction 内验证完整
`WorkerMutationAuthority`。对象 I/O 不伪装成与 PostgreSQL 的单一事务；以下状态机
明确其恢复边界：

```text
ABSENT
  └─ fenced reserve ──> STAGED (metadata durable, bytes not readable)
       ├─ conditional put + verified head + fenced finalize ──> FINALIZED
       ├─ retryable object failure ────────────────────────────> STAGED
       └─ compensation ───────────────────────────────────────> COMPENSATED

FINALIZED
  └─ authorized prune or management retention sweep ──────────> PRUNING
       └─ verified conditional delete ─────────────────────────> PRUNED
```

`STAGED`、`COMPENSATED` 和 `PRUNING` 永远不是普通读取状态。`MISSING` 是对
`FINALIZED` metadata 的 inspection outcome：object head/read 缺失、不可验证或内容
不符时 fail closed，不静默重建 bytes。

reserve 写入预期 binding、digest、size、content type 和 retention。只有 verified
object 与这些预期一致，且当前 Worker fence 仍有效时才可 finalize。若 put 成功但
finalize 响应丢失，management reconcile 可以验证同一 object 后完成 finalize；若对象
不匹配或不可验证，则只能补偿，不得把它标记为 finalized。

### 6. Idempotency、conflict、retention 与恢复

同一 `artifact_id` 的 namespace、binding、digest、size、content type 和 retained
lifecycle request 全部一致时，重复 reserve/finalize/prune 返回同一 canonical result。
任何一项不一致必须是 typed conflict，且不得覆盖既有 metadata 或 bytes。

prune 是显式 lifecycle transition，不是直接删除 object。进入 `PRUNING` 后读取
必须拒绝；conditional delete 成功才进入 `PRUNED` tombstone。重复 prune/sweep 幂等。
retention sweep 只处理明确过期且 scope 已验证的 metadata。

对象或 metadata 的单边故障进入 reconcile：

- staged row 与匹配 object：可由 management reconcile finalize；
- staged row 与缺失/不匹配 object：conditional cleanup 后标记 compensated；
- finalized row 与缺失/不匹配 object：报告 missing，保留 audit evidence，不自动生成
  替代 bytes；
- pruning row：仅重试同一 conditional delete，不能恢复为可读状态。

### 7. Worker 与管理权限分离

Worker reserve、finalize 与其执行中触发的 prune 必须使用当前 namespace、Session、
Lease fence 和预期 revision。stale authority 必须在 metadata mutation 前失败；若网络
对象操作已发生，则仅允许受控 compensation/reconcile，不得把结果变为 finalized。

management reconcile 和 retention sweep 使用显式 operator/management authority、
namespace scope 和审计证据，而不是伪造 Worker fence。它们不得运行 Tool、重放 Event、
从 Model/Tool output 合成 payload bytes，或把 external reference 转换为 managed object。

### 8. SQLite compatibility and future composition

local SQLite profile 保持既有 `artifact://` identity、missing/pruned read behavior 与
local file-backed payload semantics。云端 adapter 必须在其完成后提供相同的核心
`ArtifactPayloadStorePort` lifecycle results；它不得让 API/Worker 静默混用 SQLite
metadata、local bytes 或 cloud bytes。

`CLOUD-ART-READ-COMP-01` 只读取 PostgreSQL Model/Tool projections 和 payload
lifecycle，组成 Artifact list/detail 视图；它不新建 Artifact authority table，也不
负责对象写入。完整 backend selection 仍由 `CLOUD-CONTROL-PLANE-PG-01` 完成。

## 后续任务

1. `CLOUD-ART-PAYLOAD-PG-01` 实现 PostgreSQL metadata、provider-neutral object
   adapter、fenced lifecycle、compensation 和真实 PostgreSQL/MinIO matrix。
2. `CLOUD-EFFECT-PAYLOAD-ATOMIC-01` 使 durable Effect intent 只能引用跨 Worker
   可读的 finalized payload。
3. `CLOUD-ART-READ-COMP-01` 实现 PostgreSQL Artifact read composition 与 API
   contract parity；它不写 bytes。

## 明确非目标

- 不选择或引入 object-storage SDK、provider、credential strategy、key encoding、
  endpoint、bucket policy 或 multipart upload；
- 不新增 migration、Port、adapter、Docker Compose service、API route、CLI command、
  Worker profile 或 runtime backend selector；
- 不实现 signed URL delivery surface、ACL sharing、跨区域复制、PITR、object lifecycle
  provider rule、Snapshot implementation 或 production cutover；
- 不读取 remote URL，不把 opaque external reference 当 Zebra Artifact payload，
  不让 Event replay 产生本地或云端 payload bytes；
- 不改变 local SQLite/Desktop 行为，也不宣称 multi-tenant 或 production readiness。

## References

- [`Zebra Embedded 生产级目标架构.md`](./Zebra%20Embedded%20生产级目标架构.md)
- [`CLOUD_Worker_Aggregate_Fencing_路径盘点_v1.0.md`](./CLOUD_Worker_Aggregate_Fencing_路径盘点_v1.0.md)
- [`Zebra Embedded与Trench实施任务拆解_v1.0.md`](./Zebra%20Embedded与Trench实施任务拆解_v1.0.md)
- [`AGENT_TASKS.md`](./AGENT_TASKS.md)
