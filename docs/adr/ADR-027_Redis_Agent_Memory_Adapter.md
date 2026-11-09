# ADR-027: Redis Agent Memory 派生索引与安全切换

- 状态：Accepted（代码接入）；生产外部服务启用仍受真实服务门约束
- 日期：2026-09-20
- 关联：ADR-018、ADR-019、ADR-020、Cloud Remediation R08/R09

## 决策

Redis Agent Memory 只能作为 Zebra Governed Memory 的派生检索索引。
PostgreSQL 继续保存 Memory 正文、作用域、Revision、确认、撤销、过期、
Tombstone、投递账本和 Provider Mapping。Redis 返回的内容不直接进入模型；
运行时只接收外部排序 ID，并在 PostgreSQL 中重新校验映射、当前 Revision、
内容摘要、生命周期和业务可见范围。

旧 `agent-memory-server/V0` 是研究基础，不作为生产接入目标。当前适配器面向
Redis Cloud / Redis Software 共享的数据面 REST 合同；Redis Software 的可用性
仍取决于官方支持状态和客户获得的部署资格。

## 固定 REST 合同

2026-09-20 依据 Redis 官方文档及官方链接的 Python SDK `redis-agent-memory
0.4.1` 固定以下合同：

| 操作 | HTTP |
|---|---|
| 精确读取 | `GET /v1/stores/{storeId}/long-term-memory/{memoryId}` |
| 批量创建 | `POST /v1/stores/{storeId}/long-term-memory` |
| 修订正文 | `PATCH /v1/stores/{storeId}/long-term-memory/{memoryId}` |
| 语义检索 | `POST /v1/stores/{storeId}/long-term-memory/search` |
| 批量删除 | `DELETE /v1/stores/{storeId}/long-term-memory` |

创建请求由客户端提供 `id`，响应逐项返回 `created` / `errors`；删除响应逐项
返回 `deleted` / `errors`。认证使用 `Authorization: Bearer`，请求路径包含 Store
ID。官方资料：

- <https://redis.io/docs/latest/develop/ai/context-engine/agent-memory/developer-guide/>
- <https://redis.io/docs/latest/develop/ai/context-engine/agent-memory/rest-api-quickstart/>
- <https://redis.io/docs/latest/develop/ai/context-engine/agent-memory/api-reference/>
- <https://github.com/redis/agent-memory-server>

SDK 不是运行依赖；Zebra 复用已安装的 HTTPX，避免额外生成代码依赖。若官方
合同变化，先更新契约测试与本文，再切换生产服务版本。

## 身份与隔离

- Provider Memory ID 固定为 Zebra `MemoryId`，支持响应丢失后的精确 GET 对账。
- Provider `ownerId` 是 `z-` 加作用域字符串 SHA-256 的前 62 个十六进制字符；
  不向外部服务暴露原始 Authority、Tenant、Repo 或 User 标识。
- 外部 Namespace 是 `scope_digest:generation` 的不可逆派生值。
- Store、Endpoint、Provider、Deployment Namespace 共同参与投递 Scope Digest。
- 搜索必须带 `ownerId eq`，跨 owner 结果即使由 Provider 返回也会丢弃。
- Durable Mapping 必须同时匹配 Provider Ref、Memory Revision 和内容摘要。

## 写入、修订与不确定结果

`publish` 先按稳定 ID 读取：

1. 同 owner 且正文相同：幂等成功。
2. 同 owner 但正文变化：PATCH 同一 ID，支持 Governed Memory 新 Revision。
3. owner 不同：拒绝写入，报告 definite-no-effect。
4. 不存在：按稳定 ID 创建。

创建、PATCH 或删除遇到响应丢失、超时、5xx、损坏响应时，立即用精确 ID
读取对账。对账能证明目标正文存在或记录已不存在时才报告成功；无法证明时
返回 UNKNOWN，由 R08 账本隔离并 Quarantine Scope，不盲目重试。

删除前先读取并验证 owner，只删除一个确切 Zebra Memory ID。Tombstone 在
PostgreSQL 中先形成；R08 的每 Memory Revision 串行声明阻止旧 publish 越过
delete。外部删除不回滚 PostgreSQL Tombstone。

## Rollout 模式

| Provider | Rollout | 行为 |
|---|---|---|
| `disabled` | `off` | 不构建客户端、不投递、不检索 |
| `mem0` | `off` | 仅保留旧配置识别；ADR-018 禁止 Runtime admission |
| `redis_agent_memory` | `off` | 已选择但不连接外部服务 |
| `redis_agent_memory` | `shadow` | 投递与检索；外部排序绝不改变 Context |
| `redis_agent_memory` | `active` | 外部排序只能重排 PostgreSQL 已授权候选，缺失项由 PostgreSQL 回填 |

主动模式最多在 PostgreSQL 当前查询的 50 条已授权候选内重排，再裁剪回原始
Context limit。外部故障、空命中、Mapping 不完整或校验失败时，立即使用原有
PostgreSQL 排序；Agent 任务仍可执行。

## 配置与启动门

配置必须显式提供：

- `ZEBRA_MEMORY_PROVIDER`
- `ZEBRA_MEMORY_ROLLOUT`
- `ZEBRA_REDIS_AGENT_MEMORY_ENDPOINT`
- `ZEBRA_REDIS_AGENT_MEMORY_STORE_ID`
- `ZEBRA_REDIS_AGENT_MEMORY_API_KEY_ENV`（只保存环境变量名）
- `ZEBRA_MEMORY_GENERATION`
- `ZEBRA_MEMORY_DATA_EXPORT_AUTHORIZED=true`

默认值是 `disabled/off`。Shadow 或 Active 缺少 HTTPS Endpoint、Store ID、
Key 环境变量或明确数据导出授权时启动失败。HTTP 只允许测试环境显式开启。
密钥不进入 Settings repr、事件、日志或文档。

## 验收与发布状态

确定性合同覆盖创建、幂等重放、Revision 更新、响应丢失对账、作用域碰撞、
搜索过滤、删除和损坏响应。真实 PostgreSQL 测试覆盖治理提交、原子投递意图、
后台消费、Provider Mapping 与召回准入。

真实 Redis 服务测试位于
`tests/agent_integrations/redis_agent_memory/test_live_contract.py`，仅在以下测试
变量齐全且 `ZEBRA_TEST_REDIS_AGENT_MEMORY_ALLOW_DATA=true` 时运行。它只写入
随机合成记录并按确切 ID 清理。

当前真实服务门：`NOT_ENABLED`。没有受权 Endpoint、Store ID 和 API Key 时，
不得把跳过测试解释为生产通过，也不得切换线上 `shadow` 或 `active`。

## 回滚

先将 `ZEBRA_MEMORY_ROLLOUT=off` 或 Provider 改为 `disabled` 并重启 Worker。
这会停止外部投递和检索，不撤销已完成的 Tombstone，也不删除 PostgreSQL
治理状态。需要重建索引时提升 Generation；不得复用已 Quarantine 的
Generation 猜测结果。
