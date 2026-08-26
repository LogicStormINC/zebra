# ADR-025：Cloud Context 消费与子 Agent 受限继承

| 字段 | 值 |
|---|---|
| 状态 | Accepted；`CTX-INHERIT-CLOUD-01` |
| 日期 | 2026-08-23 |
| 范围 | Cloud Worker 上下文消费、Durable Child 上下文继承、Handoff 连续性 |
| 前置 | ADR-020、`CLOUD-CONTEXT-PG-01`、`CTX-MEM-01`、`CTX-HO-01C`、`SUBAGENT-CLOUD-CUTOVER-01` |

## 1. 结论

Zebra Cloud Agent 不做“全部上下文继承”。父 Session、子 Session、跨 Worker
恢复分别通过显式、受限、可追溯的 Context 合同获得所需事实：

1. Cloud Worker 在一次 PostgreSQL 只读物化中读取最近 Session History、当前
   active Context Capsule 和符合 scope 的 confirmed Memory。
2. Durable Child 必须显式选择 `fresh`、`capsule`、`fork_tail` 或 `resume`；
   继承结果在 Child admission 时固化进 `TASK_PREPARED`，后续重放不再读取父
   Session 的实时状态。
3. Handoff 的目标、验收、约束、决策、文件、验证、失败、待办、问题和
   Artifact 引用必须对模型可见，但仍标记为非指令数据。
4. Context 只传递事实，不传递权限。Child 的 capability、Policy、Network、
   Workspace 和 Host authority 继续由冻结 binding 求交并收窄。
5. Credential、隐藏推理、Provider private continuation、未界定的完整历史和
   raw tool output 永不进入继承快照。

Event Store 与 Projection 仍是 Session 执行事实，active Capsule 是当前恢复
摘要，governed Memory 是 confirmed 的跨任务事实。Materialization 和
Delegated Snapshot 都不是新的事实权威。

## 2. 为什么不全部继承

完整复制父 Prompt、消息、工具输出、Provider 状态和运行权限会同时产生四类
问题：

- **正确性**：Child 看到父 Session 后续追加的状态，重放结果会漂移。
- **安全性**：父 Agent 的 credential、Host grant 或写权限可能被无意扩大到
  只读 Child。
- **成本**：完整历史会快速占满模型窗口，并把无关噪声带入独立研究任务。
- **审计性**：无法回答 Child 使用了父任务的哪一段事实、来自哪个 revision。

因此，Zebra 使用“按来源选择 + admission 固化 + 明确遗漏”的继承模型。

## 3. 四种继承模式

| 模式 | Child 获得的 Context | 典型用途 | 失败条件 |
|---|---|---|---|
| `fresh` | 只有新的 objective | 完全独立的研究或验证 | 无；不要求父 Context 物化 |
| `capsule` | 唯一 active Capsule | 延续目标、约束、决策和当前计划 | 父 Session 没有 active Capsule |
| `fork_tail` | 最近最多 12 条安全 History | 需要最近对话措辞或局部问答 | 没有可继承 History |
| `resume` | active Capsule（若有）+ 最近 12 条 History + 最多 8 条 confirmed Memory | 高连续性的受限续作 | 三类来源都为空 |

这些模式不是权限级别。`resume` 比 `fresh` 携带更多事实，但不会因此获得更多
工具、网络或 Host 资源权限。

## 4. Cloud Worker 的物化边界

Worker 在 Attempt authority 固化后构造一个
`ContextMaterializationRequest`：

- scope 来自本次 Attempt 的有效 authority；
- `expected_session_revision` 必须等于当前 Session Projection；
- `expected_active_capsule_id` 必须等于当前 active pointer；
- History 只取最新 20 条，再按 sequence 升序交给模型；
- Memory 只取 confirmed、未过期且符合 Definition 或 repo scope 的最多 8 条；
- mode 根据当前事件确定为 `initial`、`continue` 或 `recovery`。

PostgreSQL Adapter 在同一个只读 `REPEATABLE READ` 快照中完成所有读取；无
正文的模型工具调用响应不占 History 条数。Session revision、active Capsule
或 scope 任一漂移都 fail closed，Worker 不退回拼接多个不一致读取。
SQLite/local profile 不启用该 Cloud Store，继续保留原本的本地兼容路径。

Cloud 辅助 Context 的显式预算为 2048 tokens。单个继承项最多 8192 字符，
快照总量最多 32768 字符、24 项；Capsule 投影最多 6000 字符，单条 Memory
最多 1600 字符。快照与 Compiler 截断都会写出明确 omission，不能静默发生。

## 5. Durable Child 快照

非 `fresh` 模式从父任务当前的受信 `ContextMaterialization` 派生
`DelegatedContextSnapshot`。快照携带：

- 父 `SessionId` 和精确 revision；
- 所选 active Capsule ID；
- 所选 Memory 的 `(MemoryId, revision)`；
- 每项的类型、稳定 locator、正文和 History sequence；
- 强制遗漏清单与额外截断说明；
- 创建时间和 canonical SHA-256 checksum。

快照在 Child 原子 admission 时进入 `TASK_PREPARED.delegated_context`。Child
恢复时重新验证 schema 和 checksum，然后作为 `delegated_context` evidence
交给 Context Compiler。父 Session 之后继续运行，不会改变已经 admission 的
Child 输入；相同 durable delegation 重放继续指向原 Child 和原快照。

## 6. Handoff 与模型可见性

Handoff 不再只向模型暴露一句摘要。安全 envelope 中以下字段均进入高优先级
连续性 evidence：

- reason、focus、acceptance criteria；
- constraints、decisions；
- completed、pending、immediate next；
- touched files、validation、known failures；
- open questions、Artifact refs；
- 已压缩且不含 raw output 的 completed tool summaries；
- known omissions。

这些内容在 Prompt 中明确标记为 source-attributed data、non-authority 和
untrusted instruction。它们可以帮助模型恢复任务，但不能覆盖 System、Policy
或冻结 binding。

## 7. 权限与安全不变量

1. Context snapshot 不包含或派生 credential。
2. Child binding 的 capability 是父上限、Child Definition 上限和 Zebra
   Child Policy 的交集；Context mode 不参与扩大权限。
3. Durable research Child 固定为 read-only、research tool profile、network
   `none`，且深度为 1，不能再次创建 Durable Child。
4. raw tool output 只通过受控 Artifact 引用或安全摘要传递。
5. hidden reasoning 和 Provider private continuation 不持久化、不继承。
6. Context 中的文本只能作为数据；任何内嵌指令都不能获得执行 authority。
7. 非法 mode、缺失父物化、checksum 不一致、revision/Capsule 漂移均拒绝，
   不能自动降级到“尽量继承”。

## 8. 调用合同

Cloud durable `agent.research` 的参数示例：

```json
{
  "objective": "只读检查部署手册中的回滚步骤，并返回证据位置",
  "delegation_reason": "该证据搜索独立且可并行",
  "context_mode": "fork_tail"
}
```

本地同步 research 合同不开放非 `fresh` 模式。Cloud 调用成功后返回 Child Task
identity、所选 mode、Context checksum（`fresh` 为 null）和 durable wakeup
语义；父任务进入 `waiting_children`，由可信 Child terminal wakeup 恢复。

## 9. 运维与验证

排查 Context 问题时按以下顺序查看：

1. 父 Worker 的 `EXECUTION_AUTHORITY_RESOLVED` 与物化 scope；
2. 请求固定的 Session revision 和 active Capsule ID；
3. Child `TASK_PREPARED.delegated_context` 的 mode、source revision、locators、
   omissions 和 checksum；
4. Child binding 是否仍为收窄 capability/network/workspace；
5. Handoff/Materialization evidence 是否进入 Context Compiler，并受 2048-token
   辅助预算约束。

真实存储验收必须至少覆盖：最新 History tail、scope 外 Memory 拒绝、单 Child
继承、两 Child join、伪造 USER wakeup 拒绝、Child terminal 后父恢复，以及
容器/volume/network 清理。

## 10. 非目标

- 不提供任意父 Session 的全文复制 API；
- 不把 Context snapshot 变成新的数据库 aggregate；
- 不给 Child 继承父 credential、write authority 或网络权限；
- 不传递 chain-of-thought 或 Provider 私有状态；
- 不修改 Trench 业务模型、写路径或前端交互；
- 不改变本地 profile 的默认执行语义。
