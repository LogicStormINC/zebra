# ADR-020：Context Materialization 边界

| 字段 | 值 |
|---|---|
| 状态 | Accepted；`CLOUD-CONTEXT-CON-01` |
| 日期 | 2026-08-03 |
| 范围 | Zebra Cloud 微服务的只读 Context 输入组装 |
| 前置 | `CLOUD-SCOPE-CON-01`、`CLOUD-SESSION-HISTORY-PG-01`、`CLOUD-MEMORY-PG-01`、`CLOUD-AGG-CTX-PG-01` |

## 1. 决策

Context Materialization 是一次可丢弃、可重建的只读组装结果，不是新的
Session、Context 或 Memory 权威。它把三个已经存在的事实源连接到
Context Compiler 的输入边界：

| 来源 | 回答的问题 | 权威边界 |
|---|---|---|
| Session History | 发生了什么 | Event Store 与 Event-derived Session Projection；历史读取不写库 |
| Active Context Capsule | 当前可恢复状态是什么 | Context lifecycle aggregate 的 Capsule 与 active pointer |
| Governed Memory | 哪些跨任务事实允许被召回 | PostgreSQL governed Memory authority；只接受 confirmed 且未过期记录 |

Materialization 只携带上述来源的当前版本，不能覆盖原始 Event、Capsule、
active pointer 或 Memory lifecycle。Mem0、Redis、向量索引和 provider-native
continuation 都不能成为该结果的事实源。

## 2. Core 合同

`agent-core` 暴露以下 provider-neutral 类型与 Port：

- `ContextMaterializationRequest`：携带受信的 `OpaqueAuthorityScope`、目标
  `SessionId`、期望 Session revision、期望 active Capsule ID、读取时刻、模式、
  History 上限和可选的 `MemoryQuery`。
- `ContextMaterialization`：携带实际 Session revision、History 消息、active
  Capsule 和 `GovernedMemoryEntry`；它不携带 DSN、数据库连接或 provider 类型。
- `ContextMaterializationGeneration`：由 Session revision、active Capsule ID
  和 `(MemoryId, revision)` 有序集合组成，是该临时组装结果的比较身份。
- `ContextMaterializationPort.materialize(request)`：只读 Port。当前切片只
  冻结接口和验证规则，PostgreSQL 实现由后继任务单独激活。

### 2.1 必须满足的不变量

1. `OpaqueAuthorityScope` 必须允许目标 Session；deny-all scope 直接失败。
2. 返回的 Session revision 必须精确等于请求的 expected revision；否则视为
   stale，不能返回部分结果。
3. 返回的 active Capsule ID 必须精确等于请求的 expected ID；初始组装使用
   `None`，不能悄悄接受并发产生的新 Capsule。
4. History 按 sequence 严格递增且不超过请求上限；排序或上限错误 fail closed。
5. Memory 必须显式带业务 `MemoryQuery`。query 只允许
   `statuses=(confirmed,)`，结果必须匹配 query 的 visibility/scope，且在
   `as_of` 时未过期；candidate、superseded、deleted 和跨 repo/user/tenant
   的记录不得进入 Context。
6. 一个 Memory ID 在结果中只能出现一次，generation 中的 revision 必须为
   正数且按 Memory ID 稳定排序。
7. 组装和 rebuild 都不产生 Event、Session Projection、Capsule、Memory
   lifecycle 或 Artifact 写入。

业务可见性（`repo_id`、`user_id`、`tenant_id`）与部署隔离（opaque
`namespace_id`）是两套输入。Core 只校验形状；外部 authority 到内部
`deployment_namespace` 的映射由受信 composition 提供，Zebra 不变成业务租户
目录。

## 3. 生命周期

```text
initial/continue/recovery request
        ↓
read Session History + active Capsule + confirmed Memory
        ↓
validate expected revisions and scope
        ↓
ephemeral ContextMaterialization + Generation
        ↓
Context Compiler input
```

- **Create**：以一次请求生成临时 envelope，不新增 durable record。
- **Append/continue**：下一次请求带上最新 Session revision 和 active Capsule
  expectation，重新 materialize；旧 envelope 直接失效。
- **Snapshot**：`generation` 仅用于同一读取结果的比较、日志和缓存键，不是
  新的数据库 revision。
- **Expire**：请求结束、TTL 到期或任一来源 revision 变化时丢弃 envelope。
- **Rebuild**：从三个权威源重新读取；不得从旧 envelope 推断新的事实。

## 4. PostgreSQL 后继实现边界

`CLOUD-CONTEXT-PG-01` 才能实现 Storage adapter。它必须在一个一致的只读
数据库读取中组合现有 Session History、Context lifecycle 和 governed Memory
适配器，并在返回前复核 revision、scope、expiry 和 active pointer。它不得：

- 新建 Context/Memory authority 表或修改已有 migration；
- 把 Session History 变成写 aggregate；
- 修改 `ControlPlaneStores`、Worker/API 启动、Runtime 或 Provider HTTP；
- 引入 Desktop、SQLite、Redis、Mem0、向量数据库或 dual-write。

## 5. 与已有 Context 生命周期的关系

本 ADR 不重复 `CLOUD-AGG-CTX-PG-01` 的 Capsule 创建、active pointer CAS、
`CONTEXT_COMPACTED`/`CONTEXT_CAPSULE_CREATED` Event 或管理员恢复。那些操作
仍由 Context lifecycle aggregate 负责；本合同只消费其当前 active 读结果。

同样，本 ADR 不改变 `CLOUD-SESSION-HISTORY-PG-01` 的 browse/search/read
过滤，也不改变 `CLOUD-MEMORY-PG-01` 的 Memory mutation/review/snapshot
authority。它们通过明确的 Port 组合，而不是互相复制规则。
