# Zebra Cloud 主线当前状态与后续工作

> 快照日期：2026-08-03
> 分支：`zebra-cloud-trench`
> HEAD：`7c99cb56`

## 结论

Zebra Cloud 已完成大部分 PostgreSQL 云端底层适配器，但尚未完成可部署的
API/Worker 微服务组合。当前状态是“云端事实存储和聚合能力基本齐备，主容器
组装、运行时切换和 Trench 业务接入尚未完成”。

任务注册表是当前状态的权威来源；本文件是面向项目协作的汇总，不替代
[`docs/AGENT_TASKS.md`](./AGENT_TASKS.md) 中的任务卡、Owner、Branch 和依赖。

## 已完成

### Core 与本地基线

- Event Store、Task/Segment、Harness、Tool、Policy、Approval、Context、恢复、
  Sandbox 和本地 Runtime 基线已完成。
- `ControlPlaneStores` 已统一 Event、Projection、Task、Lease、Context、Handoff、
  Effect、Memory、Artifact、Provider Continuation、Session History 和 Delivery
  Audit Port。
- 本地 SQLite profile 仍保持可用，并拒绝 `:memory:` 组合，避免多连接产生伪事实源。

### PostgreSQL 云端基础

- PostgreSQL 迁移目录已覆盖 v1-v12：Event/Projection、Epoch/Lease、Effect
  Outbox、Workspace、Task/Segment、Model/Tool、Context、Handoff、Artifact、
  Governed Memory、Memory Delivery 和 Native Memory Gateway。
- 已完成并有独立测试证据的主要 Adapter 包括：Event/Projection、Lease、Effect
  Outbox/Consumer、Workspace、Task、Context、Handoff、Model/Tool、Artifact、
  Session History 和 Governed Memory。
- Handoff v8、Artifact v9、Governed Memory v10、Memory Delivery v11 和 Native
  Memory v12 均已进入当前分支的实现记录。
- 已记录的宿主 PostgreSQL Compose 矩阵包括 Session History `3/3`、Context
  Materialization `4/4`、Task `32/32`、Workspace `80/80`、Effect Outbox `49/49`
  和 Effect Consumer `58/58`。

### Memory

- Zebra PostgreSQL Governed Memory 是权威事实源，负责候选、确认、过期、删除、
  来源和作用域生命周期。
- PostgreSQL Native Memory Gateway 已完成准入验证。
- Mem0 OSS Spike、Gateway Adapter、Compose 依赖和替代 reset 方案已完成验证，
  但 Mem0 仍只允许作为可降级的派生索引。

### Agent Definition v2

- `AGENT-DEF-ADR-01`、`AGENT-DEF-CON-01` 和 `AGENT-AUTH-SNAPSHOT-01` 已完成。
- 已冻结 Definition/Version/Release 模型、Registry Port、Definition digest、
  Attempt authority snapshot、解析和可恢复重验证事件。
- `AGENT-AUTH-SNAPSHOT-01` 已合并到 `zebra-cloud-trench`，不保存凭证、Token 或
  可重放密钥。

### Docker 与协议边界

- `docker/compose.dependencies.yml` 管理 PostgreSQL、Redis、MinIO 和初始化容器。
- Mem0 使用独立可选 Compose overlay；Mem0 数据明确是派生、可替换的存储。
- Embedded 架构已经确定 CopilotKit/AG-UI 方向，取消自研 Zebra React SDK；AG-UI
  目前只完成协议兼容 Spike，没有生产路由或 Trench 接线。

## 尚未完成

### PostgreSQL 运行时组合

当前 API/Worker 仍会回退到 `sqlite_control_plane_stores(database_path)`。因此
PostgreSQL Adapter 已存在，不代表云端运行时已经选用 PostgreSQL。

仍锁定的关键任务：

1. `CLOUD-PROVIDER-CONT-PG-01`：Provider continuation 的 namespace/fence 适配器。
2. `CLOUD-CONTROL-PLANE-PG-01`：完整 PostgreSQL `ControlPlaneStores` 组合、配置
   选择和 API/Worker 接线。
3. `CLOUD-DELIVERY-TXN-PG-01`：Delivery Audit/Idempotency 命令事务。
4. `CLOUD-AGG-FENCE-01`：所有 Worker 权威聚合的真实 PostgreSQL fencing 总门禁。

这些卡均保持 `Locked`，不能在没有 maintainer 激活、Owner、Branch、Worktree 和
Owned paths 复核的情况下直接编码。

### Docker 应用层与在线事件

- `docker/compose.application.yml` 目前不存在。
- Zebra migration、API、Worker 三类主容器尚未建立。
- Redis 目前只有依赖容器，没有 replay-plus-tail 的 live fan-out Adapter。
- PostgreSQL/MinIO/Redis 的备份、PITR、恢复、回滚、RPO/RTO 和多 Worker 故障演练
  尚未形成完整 GA 证据。

### Mem0 运行准入

Mem0 当前 Provider admission 为 `DENIED`，原因是 ambiguous-create 恢复和完整
scoped deletion 仍未得到可靠证明。`MEM-GW-DEL-RUN-01`、Memory parent gate 和
Runtime consumer 均保持 `Locked`。Mem0 不得成为 Zebra 的第二事实源，也不能阻塞
Agent Run。

### Agent Definition 后续链

下列任务仍未实施：

- Registry 存储 Adapter（SQLite/私有云 PostgreSQL）
- Draft/Version materialization
- Task-level Definition binding
- Definition-scoped governed Memory
- Trust/Ingress coverage
- Version publication Eval gate
- Gated publication API

当前任务图存在一个需要维护者重新确认的依赖问题：`AGENT-DEF-PG-01` 依赖本地
`AGENT-DEF-STO-01`，而云端主线又明确推迟 SQLite Registry。因此 Definition 云端
存储链不能自行跳过依赖启动。

### CopilotKit / Trench 生产链路

以下仍为 `Locked`：

- HostSessionGrant 和外部 authority verifier
- Zebra 生产 AG-UI endpoint
- Host Tool Gateway
- Trench read Tool API
- Trench CopilotKit Runtime/BFF
- Event Detail 只读 Copilot panel
- 跨服务 read-only E2E
- 后续 frontend collaboration、deterministic analysis、controlled writeback 和 GA

Zebra 继续拥有 Task/Event/Approval/Receipt/Artifact/Policy authority；CopilotKit
Thread、Redis live state 和前端 state 不能成为持久事实源。

## 当前质量状态

当前 HEAD 的 `make test` 结果：

```text
2243 collected
2033 passed
209 skipped
1 failed
```

唯一失败是仓库文件大小门禁，包含两个已知超限文件：

- `UI/desktop/src/components/CodexConversationPane.styles.ts`：561/500
- `tests/agent_storage/test_postgres_governed_memories.py`：765/700

这不是当前 Cloud Adapter 的功能失败，但会使全仓库质量门保持红色。Desktop 文件
属于当前云端主线之外；Governed Memory 测试文件需要后续拆分或由维护者批准明确的
云端质量门策略。

## 后续实施顺序

以下顺序沿用现有任务注册表，不代表自动激活：

1. 维护者确认 Provider Continuation 的 namespace 边界并激活对应卡。
2. 完成完整 PostgreSQL `ControlPlaneStores` 组合和 SQLite/Cloud 双 profile 选择。
3. 完成 Delivery transaction 和所有 aggregate fencing 证据。
4. 接入 Redis live fan-out，创建独立的 Zebra application Compose overlay。
5. 完成迁移、备份、恢复、回滚和多 Worker E2E 门禁。
6. 再激活 Host/AG-UI/Trench read-only vertical slice。
7. 之后才进入 Frontend、Analysis、Writeback 和 GA。

## 当前治理门

当前没有活动实现任务。维护者必须先在 `docs/AGENT_TASKS.md` 中明确激活一张已注册
任务卡，再允许创建对应 Branch/Worktree 和生产代码变更。SQLite Registry、Runtime
backend selection、Provider HTTP、Desktop、Redis live、Mem0 consumer 和应用 Compose
均不得通过临时修改 `Locked` 状态绕过依赖。
