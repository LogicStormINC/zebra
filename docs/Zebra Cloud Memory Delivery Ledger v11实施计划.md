# Zebra Cloud Memory Delivery Ledger v11 实施计划

状态：方案已审查，父任务保持 `Locked`，等待四个窄任务按顺序解锁。

基线：`zebra-cloud-trench@ac9801c2`。PostgreSQL governed Memory v10 和 Context recovery 已进入云端主线；Mem0 仍只是可丢失、可重建的派生索引，不能成为 Zebra 的事实源。

## 1. 结论与边界

`MEM-GW-DEL-01` 不能按原来的宽任务卡直接实现。原因不是缺少一张普通 outbox 表，而是三个安全合同尚未闭合：

1. v11 投递记录必须和 v10 的 `confirmed`、`deleted`、`superseded`、`expired` 权威变化在同一 PostgreSQL 事务中写入，否则会出现“权威状态已提交、投递永久丢失”。
2. Gateway 结果必须区分 `applied`、`definite_no_effect` 和 `unknown`；消费者不得从错误字符串猜测是否重试。
3. Mem0 的重复 `POST` 可能产生不同 provider UUID。现有 Adapter 没有安全的 scoped namespace reset，因此 `unknown publish` 不能自动重试，也不能声称重建闭环已经可用。

本计划只冻结协议、任务边界和验收门禁。它不启用 Mem0 写入，不改变本地 SQLite composition，不修改 Desktop，也不把任何 Mem0 数据提升为 Zebra 事实源。

## 2. 已核对的依赖状态

| 依赖 | 当前状态 | 对 v11 的结论 |
| --- | --- | --- |
| `CLOUD-MEMORY-CON-01` | 云端主线可见，治理状态 `Review` | 已有 v10 Core 基线，仍需按仓库治理完成合并 |
| `CLOUD-MEMORY-PG-01` | v10 authority 在主线，治理状态 `Review` | 可提供权威 revision、digest、生命周期和批量扫描 |
| `MEM-GW-CON-01` | Gateway Port 已存在，mutation 仍只有 status/detail | 必须先扩展 typed certainty 合同 |
| `MEM-MEM0-SPIKE-01` | OSS REST/Compose 语义已验证，治理状态 `Review` | 可作为 reset Spike 的事实基线，不能把 boot-smoke 当生产证据 |
| `MEM-MEM0-ADP-01` | Adapter 代码在主线可见，治理状态 `Review` | 仅作为 provider transport；mapping/ledger 不归 Adapter 私有持有 |
| Lease/Effect | PostgreSQL claim/CAS/DB-time 已有验证 | 只复用模式；Memory consumer 不复用 Session `LeaseFence` |
| Host namespace authority | 完整 cloud composition 尚未闭合 | 阻断生产启用，不阻断隔离的 Core/Storage 合同工作 |

## 3. v11 最小数据模型

只增加三张职责清晰的表。任何表都不得保存 Memory 正文、原始 scope、provider response body、凭据或已删除内容。

### 3.1 `memory_delivery_scopes`

保存派生 provider namespace 的生命周期：`deployment_namespace`、不可逆 `scope_digest`、单调 `generation`、`active|quarantined|rebuilding` 状态、当前 revision，以及无正文的 quarantine/rebuild reason、operator、时间和 CAS revision。

同一 deployment scope 只允许一个 active generation。`unknown publish` 或 reset 期间必须先将 generation 标记为 `quarantined`，不得继续接受普通写入或搜索结果。

### 3.2 `memory_delivery_operations`

这是 outbox 与审计账本的合并表，至少包含：

- Zebra `MemoryId`、权威 revision、content digest、scope/generation；
- `publish|delete` operation、稳定 idempotency key；
- `pending|claimed|in_flight|completed|uncertain|dead_letter` 状态；
- attempt、next-attempt、随机 claim token、owner、expiry；
- `applied|definite_no_effect|unknown` certainty；
- provider ref（若已确认）、无正文 error code、创建/更新/完成时间。

在发网络请求前先持久化 `in_flight`。`claimed` 过期表示请求尚未越过网络边界，可以 CAS 回 `pending`；`in_flight` 过期无法证明远端未执行，必须转 `uncertain`。

### 3.3 `memory_provider_mappings`

保存当前 generation 下已确认的 `MemoryId -> provider_ref` 映射，作为 delete 和 search admission 的唯一映射来源。publish 完成时写入；delete 完成或明确 404 时删除。映射必须带权威 revision、content digest、scope/generation 和 CAS revision，避免旧 generation 的 provider hit 复活。

### 3.4 最小状态机

```text
pending -> claimed -> in_flight
claimed 过期 -> pending
in_flight -> completed(applied | definite_no_effect)
in_flight -> pending             # 仅 definite_no_effect，预算内退避
in_flight -> uncertain           # timeout/断连/5xx/失真响应
in_flight 过期 -> uncertain
pending 重试耗尽 -> dead_letter
```

`unknown/uncertain` publish 永不自动重试，并将对应 scope generation 置为 `quarantined`。只有 management-only 的 reset/rebuild 流程可以解除隔离；普通 Worker 不得自行 reset namespace。

## 4. 四个窄任务

### `MEM-GW-DEL-CON-01` — Core delivery certainty contract

- 状态：`Locked`，依赖 `MEM-GW-CON-01`、`CLOUD-MEMORY-CON-01` 的治理合并。
- Owned paths：
  `packages/agent-core/src/agent_core/ports/agent_memory_gateway.py`、
  `packages/agent-core/src/agent_core/domain/memory_delivery.py`（新）、
  `packages/agent-core/src/agent_core/ports/memory_delivery.py`（新）、对应 Core exports 和 focused Core tests。
- 只冻结 `MemoryDeliveryScope`、operation/certainty 枚举、状态转移、稳定 idempotency key 和 provider-neutral Port；禁止 SQL、HTTP、Mem0、Worker wiring。
- 验收：非法 status/certainty 组合拒绝；`unknown` 没有 retry 意义；Core 不导入任何 provider、Redis 或 PostgreSQL 类型。

### `MEM-MEM0-RESET-SPIKE-01` — Scoped namespace reset/rebuild probe

- 状态：`Locked`，依赖 `MEM-MEM0-SPIKE-01` 与 Compose/Store/Gateway 前置合并。
- Owned paths：`docker/compose.mem0.test.yml`、`docker/mem0/` 下的测试辅助、`tests/spikes/mem0/`、`docs/Mem0 OSS协议兼容性验证记录.md` 的新增证据。
- 只验证 scoped enumeration/purge、分页/上限、expired/duplicate/unknown 对象、跨 scope 隔离和重启行为；禁止暴露无边界全局 `/reset`。
- 验收：能证明 reset 的范围、上限、失败语义和 operator 门禁；若 provider 无法提供安全 scoped reset，任务必须以 `Blocked` 结束，父卡不得解锁。

### `MEM-GW-DEL-PG-01` — PostgreSQL v11 ledger and atomic enqueue

- 状态：`Locked`，依赖 `MEM-GW-DEL-CON-01`、`CLOUD-MEMORY-PG-01` 和迁移治理合并。
- Owned paths：`packages/agent-storage/src/agent_storage/postgres/memory_delivery.py`（新）、delivery transaction/support 模块（新）、`postgres/migrations.py`、`governed_memory_transactions.py`、`governed_memory_transaction_support.py`、对应 PostgreSQL tests 和宿主 Compose runner。
- 实现 v11 migration、同事务 enqueue、`SKIP LOCKED` claim/CAS、mapping、批量 search revalidation 和无正文审计；不得修改 Worker 默认 composition。
- 验收：v1-v11 fresh/upgrade/checksum、权威变更与 operation 原子回滚、重复 replay 不产生第二条 delivery、陈旧 ACK 零写入、批量 hit 一次性回查 authority。

### `MEM-GW-DEL-RUN-01` — Mem0 delivery consumer and management rebuild

- 状态：`Locked`，依赖 `MEM-GW-DEL-PG-01`、`MEM-MEM0-RESET-SPIKE-01`、`MEM-MEM0-ADP-01` 的治理合并。
- Owned paths：`packages/agent-integrations/src/agent_integrations/mem0/gateway.py` 及其 typed response tests、`apps/worker/src/zebra_agent_worker/memory_delivery_consumer.py`（新）、管理型 reconciliation/rebuild coordinator、PostgreSQL+Mem0 integration tests。
- Consumer 使用独立 claim token、数据库时间和 CAS；publish 前按 revision/digest 回查权威；delete 只使用 confirmed mapping；reset/rebuild 是显式 management-only 流程。
- 不修改默认 `apps/*/main.py` 或本地 SQLite composition；完整 cloud Store/Host wiring 另由后续 gate 负责。
- 验收：2xx publish 为 `applied`；delete 2xx/404 收敛；明确拒绝为 `definite_no_effect`；timeout/断连/5xx/失真成功响应为 `unknown`；unknown 永不自动重试；新 generation 完整扫描后用 high-watermark 收敛增量并原子切换。

原 `MEM-GW-DEL-01` 保留为四个子任务完成后的汇总 gate，不再拥有跨层实现路径。`MEM-GW-GATE-01` 仍必须等待汇总 gate，不得提前宣称生产启用。

## 5. 解锁顺序

```text
MEM-GW-DEL-CON-01 ─┐
                    ├─> MEM-GW-DEL-PG-01 ─┐
MEM-MEM0-RESET-SPIKE-01 ───────────────────┼─> MEM-GW-DEL-RUN-01
MEM-MEM0-ADP-01 ────────────────────────────┘
```

1. 先分别激活 Core contract 和 reset Spike；任何一个失败都保持父卡 `Locked`。
2. Core contract 合并后再激活 PG v11，确保 enqueue 与 v10 authority 同事务。
3. 只有 PG 账本和 reset/rebuild 门禁都通过，才激活 Worker/Adapter runtime。
4. 完整 cloud composition、Host namespace authority、统一 Store selector 和生产凭据仍是独立的 `MEM-GW-GATE-01`/cloud composition 门禁。

## 6. 验收矩阵

| 层 | 必须证明 |
| --- | --- |
| Core | 状态机和 certainty 合法性；consumer 不解析 detail；unknown 不自动重试 |
| PostgreSQL | migration、约束、namespace 隔离、同事务 enqueue、claim/CAS、陈旧 ACK、无正文审计 |
| Gateway | publish/delete 结果分类、deadline、404 收敛、schema drift 和 provider outage |
| Search | active mapping、provider ref、scope/generation 与 PostgreSQL confirmed/unexpired 状态一次批量回查 |
| Delete | authority deletion 先行；账本和错误不含正文；unknown publish 不伪造删除成功 |
| Rebuild | management-only reset；新 generation 完整扫描；high-watermark 增量；原子切换；旧 generation 保持隔离直至安全 purge |
| Degraded | Mem0、其 PostgreSQL 或 consumer 停止时，Run 继续，Zebra Memory 数量和生命周期不变 |
| Docker Compose | 独立 PostgreSQL/Mem0 测试项目、健康检查、宿主 runner、失败清理和真实服务证据 |

## 7. 明确不做

- 不把 Mem0、Redis、Graph 或任何 embedding index 作为 Zebra 记忆事实源。
- 不在 unknown publish 后猜测成功、自动重发 POST 或伪造 provider UUID。
- 不在本阶段引入全局 reset、隐式 in-memory mapping、ORM、SQLite 兼容分支或 Desktop 改动。
- 不修改默认本地 profile 来“顺便”启用云端 Memory delivery。
- 不以 CI billing/spending-limit 状态替代宿主 Docker Compose、PostgreSQL 和 provider contract 证据。
