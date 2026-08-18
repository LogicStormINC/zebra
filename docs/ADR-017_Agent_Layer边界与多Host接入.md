# ADR-017：Agent Layer 边界与多 Host 接入

- 状态：`Accepted`
- 日期：2026-08-18
- 决策人：maintainer（lukeding）
- 权威方案：`docs/cloud-agent构建实施方案.md`（审查基线 `main@bb3a1bce`，
  关键代码断言已于批准当日复核属实）

## 背景

Zebra 的产品定位（ADR-012、AGENTS.md Product Positioning）是独立的
多会话 Cloud Agent Runtime，被 Trench 等业务系统通过签名授权消费。
当前代码已具备 Agent Layer 约 70%–75% 的底座（Host 入站信任、Agent
Registry 与 Definition Snapshot、AG-UI 纯投影、Cloud Data Plane），但
多 Host 接入闭环仅完成 35%–45%，存在五个已核实的 P0 级耦合：

1. Worker 硬编码 Trench 工具名与 `trench.*` 资源映射
   （`tool_gateway_runtime.py` 的 `_required_resource()`）；
2. 出站 Host 连接是部署级单例（`host_tool_endpoint` 等全局配置）；
3. Host Manifest 缺少资源绑定、grant scope 与能力声明，Worker 只能猜；
4. HTTP HostGrant 链与 Worker `TenantScopedAuthorityResolver` 合成权限链
   相互分离，未合成一条可审计的执行权限链；
5. Task 绑定信息埋在 `TASK_PREPARED` 事件中，无第一类
   `TaskBindingSnapshot`。

## 决策

1. **Zebra Agent Layer = Agent Control Plane + Host Integration Plane**，
   负责统一 Agent 接入、权限准入、Definition 解析、Host 能力绑定、命令
   接收、查询重放与协议投影；现有 Runtime 继续承担 Worker、Sandbox、
   Effect、Artifact、Memory、Lease 与恢复。
2. **逻辑边界先行**：Agent Layer 以 `agent-control-plane` application
   package 落地于 `apps/api` 进程内；在出现独立扩缩容、网络 trust zone
   或合规边界等真实需求之前，不拆新微服务，不复制 Agent Runtime。
3. **一个 Task 在 v1 只绑定一个 Primary Host**（host_app_id +
   namespace_id + connector profile revision + 不可变
   HostCapabilitySnapshot）；跨 Host 工作流经 Subtask/Handoff 实现，
   `host_bindings[]` 留待真实需求。
4. **Capability 与 Grant Scope 分离**：Zebra 使用稳定语义 Capability
   （`evidence.read` 等），Host 保留自己的授权词汇（`trench:event:read`
   等）；有效能力 = Definition 上限 ∩ Manifest 声明 ∩ Host 授予 ∩
   Zebra Policy。
5. **Admission 固化一切运行能力**：Task 创建时在单个 PostgreSQL 事务中
   原子写入 Task、Session、Events、Projections、TaskBindingSnapshot 与
   Idempotency；Worker 只消费快照，不实时发现 Manifest，恢复使用同一
   Manifest digest。
6. **多 Host 零分支门禁**：新增第二个 Host（fake-host-b / Jazz）时，
   `agent-core` 与 Worker 生产代码不得增加 Host 名称分支；该不变式由
   Host Conformance Kit 在 CI 强制。

## 后果

- 实施以 16 张 `AL-*` 任务卡承载（四个阶段：边界与协议 → Connector 与
  Task Binding → 执行权限与 Host Egress → API/Conformance/迁移），
  以 `AL-PLAN-01` 预留表登记，全部 `Locked`，按依赖顺序逐张激活。
- Trench 现有链路采用渐进切换：先保留 `ZEBRA_HOST_TOOL_*` legacy
  兼容，Connector Registry 就绪后新 Task 走 Binding 模式，存量 Task
  受控 drain，最后删除 legacy 配置与 Worker 特例。
- 迁移编号从 v24 起算（当前头为 v23），正式激活时需复核迁移头。
- 与既有决策的关系：本 ADR 细化而不推翻 ADR-012（外部业务边界）、
  ADR-015 与 ADR-016（Definition 控制面）；`ExecutionAuthoritySnapshot`
  复用其既有求交与收窄语义。
