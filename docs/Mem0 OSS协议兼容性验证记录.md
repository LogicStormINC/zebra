# Mem0 OSS 协议兼容性验证记录

> 审查收口（2026-08-02）：`MEM-MEM0-SPIKE-01` 已 `Done`。本记录证明
> pinned OSS/Compose 语义和确定性 provider 行为，不证明真实 provider 兼容性，
> 也不改变 Zebra PostgreSQL governed Memory 的事实源边界。Scoped reset Spike
> 仍 `Blocked`，Mem0 Runtime admission 仍 denied/deferred。

| 项目 | 结果 |
|---|---|
| Zebra 任务 | `MEM-MEM0-SPIKE-01` |
| Mem0 Python | `mem0ai==2.0.13` |
| Server source | `ca2abca2b884e038d3e525070e79d3057ef2012c` |
| Image | `zebra/mem0-api:2.0.13-ca2abca2` |
| Vector store | isolated PostgreSQL 17 + pgvector 0.8.0 |
| Provider | local deterministic OpenAI-compatible Embedding stub |
| Real provider | 未验证，仍需一次性 credential gate |
| Authority | Zebra `MemoryStorePort`，Mem0 仅为可重建派生索引 |

## 1. 验证边界

本 Spike 通过真实 Mem0 REST Server、Alembic、PostgreSQL/pgvector 和 history
SQLite volume 验证 OSS 行为。测试 provider 只实现 `POST /v1/embeddings`；
`POST /v1/chat/completions` 固定失败。因此成功的 `infer=false` 写入同时证明该路径
没有调用 LLM。

该结果不证明真实 OpenAI/Gemini/Anthropic 的认证、限流、模型兼容性或生产 SLO。
正式 Adapter 仍需单独的 disposable credential 验证。

隔离测试使用：

- `docker/compose.dependencies.yml`；
- `docker/compose.mem0.yml`；
- `docker/compose.mem0.test.yml`；
- 独立 Compose project、network、PostgreSQL volume 和 history volume；
- 独立 loopback ports `25433` 和 `28088`。

## 2. 已观察 REST 契约

### 2.1 Authentication

- 受保护端点接受 Bearer JWT、用户 `X-API-Key` 或通过 `X-API-Key` 发送的
  `ADMIN_API_KEY`。
- 匿名 `GET /memories?user_id=...` 返回 `401`。
- Mem0 的 entity/filter 不是 Zebra authorization boundary。Zebra 必须先验证 Host
  authority，再生成不透明 scope 映射。

### 2.2 Add with infer=false

`POST /memories` 请求：

```json
{
  "messages": [{"role": "user", "content": "confirmed memory"}],
  "user_id": "zebra:<sha256(namespace)>",
  "metadata": {
    "zebra_memory_id": "<uuid>",
    "zebra_idempotency_key": "<opaque-key>",
    "zebra_schema_version": 1
  },
  "infer": false
}
```

至少需要 `user_id`、`agent_id`、`run_id` 之一。成功响应包含：

```json
{"results": [{"id": "<mem0-id>", "memory": "confirmed memory", "event": "ADD"}]}
```

同一 payload 和 `zebra_idempotency_key` 连续发布两次会生成两个不同 Mem0 UUID。
Mem0 REST 没有外部 ID upsert，也没有可靠的 metadata lookup API。因此 Adapter 不能
依靠 Mem0 实现发布幂等；必须由 Zebra delivery ledger 保存
`MemoryId -> provider_ref`，并在响应丢失时进行可对账恢复。

### 2.3 Search and namespace

`POST /search` 使用 `filters`；顶层 `user_id`、`agent_id`、`run_id` 已 deprecated。
验证通过的过滤组合为：

```json
{
  "query": "query",
  "filters": {
    "user_id": "zebra:<sha256(namespace)>",
    "zebra_memory_id": "<uuid>"
  },
  "top_k": 10,
  "explain": true
}
```

不同 scope hash 返回空结果。返回 hit 包含 Mem0 正文、score 和 metadata，但
Adapter 只能向 Core 返回 Zebra `MemoryId`、provider ref 和 provider score；正文、
visibility、status、expiration 和 confidence 必须重新读取 `MemoryStorePort`。

### 2.4 Expiration

- `expiration_date` 接受 `YYYY-MM-DD`。
- 默认搜索不会返回已过期记录。
- 固定版本中，`POST /search` 即使设置 `show_expired=true` 仍不返回已过期记录。
- `GET /memories?user_id=...&show_expired=true` 可以列出该记录。

因此 Zebra 不能依赖 Mem0 的 expired search 做治理或恢复；过期状态始终以
`MemoryStorePort` 为准。此差异是 Adapter gate，不在 Zebra 内复制另一套过期事实。

### 2.5 Update, history and delete

- `PUT /memories/{memory_id}` 支持显式 `text`、`metadata`、`expiration_date`；正文
  更新会重新生成 embedding。
- `GET /memories/{memory_id}/history` 返回 `ADD`、`UPDATE` 等事件；history 位于
  独立 SQLite volume，仅作 provider 运维证据。
- `DELETE /memories/{memory_id}` 返回 `200`，删除后 scoped search 不再返回 hit。
- Zebra Adapter 不暴露全量 `POST /reset` 或无边界批量删除。

### 2.6 Restart and failure mapping

- 重启 `mem0-api` 后 PostgreSQL memory 和 history 仍可读取。
- Embedding provider 返回 `503` 时，Mem0 返回 `502`，code 为
  `provider_unavailable`。
- Embedding 返回错误维度时，Mem0 返回 `502`，但 code 为 `unknown`。
- Embedding provider 持续阻塞时，REST 请求同步阻塞；测试调用方在 `100ms` deadline
  得到 `TimeoutError`，没有稳定的 Mem0 错误 envelope。

`unknown` 说明服务端错误分类不足。Adapter 必须将所有 5xx、连接错误、timeout 和
无法解析的响应收敛为 degraded outcome，同时保留受限审计细节。

## 3. Adapter 必须遵守的映射

1. 只接收 `ConfirmedMemoryPublication`，请求固定 `infer=false`。
2. `user_id = "zebra:" + sha256(namespace)`；不向 Mem0 发送 Host 原始身份。
3. metadata 至少保存 `zebra_memory_id`、`zebra_idempotency_key` 和 schema version。
4. Zebra delivery ledger 保存 `MemoryId -> Mem0 ID`，处理重复发布、响应丢失、删除
   和 rebuild。
5. search 同时限制 scope hash 和 `zebra_memory_id`/允许 metadata；每个 hit 回查
   `MemoryStorePort`。
6. Mem0 score 不改变 Zebra confidence、status、visibility 或 expiration。
7. Mem0 故障、schema drift 或 stale hit 不得使 Agent Run 失败。

## 4. 未通过或未验证项

- `show_expired=true` 的 search 行为不符合字段描述；Adapter 不依赖该能力。
- Mem0 自身不能提供 Zebra 所需的发布幂等。
- 普通用户跨 entity/ID 的 record-level authorization 尚未进行黑盒 credential test；
  代码审计显示 Zebra 必须拥有完整 authorization boundary。
- 真实 provider、rate limit、服务端 provider timeout、TLS、proxy 和供应商模型差异
  未验证；Adapter 必须设置自己的调用 deadline。
- embedding 维度迁移没有在线重建能力；错误维度当前只得到 `502/unknown`。

## 5. 运行命令

```bash
ZEBRA_RUN_MEM0_SPIKE=1 uv run pytest -q \
  tests/spikes/mem0/test_mem0_oss_contract.py
```

测试自动创建并销毁名为 `zebra-mem0-spike` 的独立 Compose project 及其 volumes，
不会操作长期运行的 `zebra-dependencies` volumes。

## 6. Scoped reset/rebuild Spike（`MEM-MEM0-RESET-SPIKE-01`）

2026-08-02 按 sidebar ChatGPT 方案激活了独立的 test-only reset probe。它使用
`zebra-mem0-reset-spike` Compose project、独立 PostgreSQL/API/proxy 端口和同一组
固定 Mem0 镜像；结束时总是执行 `down --volumes --remove-orphans`。测试不会调用
全局 `/reset`，不会直接写 provider 表，也不会把 Mem0 提升为 Zebra 事实源。

测试矩阵固定为：

- A/g1：重复、过期、分页枚举、response-loss unknown publish、重启和精确 scoped purge；
- B/g1：与 A 的跨作用域隔离和保留验证；
- A/g2：重建后再次发生 unknown publish 时保持 quarantined；
- A/g3：只在下一代重建，验证 generation isolation；
- PostgreSQL：仅通过 `SELECT` 读取固定 `zebra_memories.payload`，核对 provider 行数和
  purge 后是否残留。

故障代理先让 Mem0 完成上游 `POST /memories`，再关闭客户端响应，模拟调用方只能得到
`unknown` 的情况；测试禁止重试，必须通过同一代的完整分页枚举发现对象。分页参数必须
先出现在该 pinned server 的 OpenAPI 中；参数缺失、分页重复/截断、对象元数据缺失、跨
scope 泄漏或 PostgreSQL 残留都会明确失败为 `Blocked`。代理的 `/__test__/reset-fault`
只用于第二代测试故障复位，不是 Mem0 API。

运行命令：

```bash
ZEBRA_RUN_MEM0_RESET_SPIKE=1 uv run pytest -q \
  tests/spikes/mem0/test_mem0_namespace_reset.py
```

静态 Ruff、Python 编译、Compose config 和非 Docker 收集/跳过态测试均通过。真实
Compose 运行已到达 API 健康检查，但在预期的 OpenAPI gate 失败：固定版本的
`GET /memories` 只有 `agent_id`、`run_id`、`show_expired`、`top_k`、`user_id`，没有
`page/page_size` 或 `offset/limit`。因此不能证明完整 scoped enumeration，任务按门禁
标记为 `Blocked`；`top_k` 不得被解释为分页，父级 `MEM-GW-DEL-01` 继续保持 `Locked`。
