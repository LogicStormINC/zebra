# Zebra 执行收敛与最小 Runtime / Task Memory 切片方案 v1.0

| 字段 | 值 |
|---|---|
| 状态 | Phase 1 已激活；Phase 2 锁定 |
| 日期 | 2026-07-28 |
| 当前任务 | `HAR-CONV-01` |
| 依赖 | `CTX-MEM-01` / PR `#198` |
| 上位约束 | Event Store 唯一执行真相；Harness 无默认次数上限；业务语义留在调用方 |
| 关联文档 | `自适应Agent循环与预算治理方案_v1.0.md`、`上下文连续性与治理记忆改进方案_v1.1.md`、`Zebra Agent Runtime Upgrade Proposal v2.0.md` |

## 1. 决策

本次不提前建设完整 Memory 2.0。当前故障先按两个可独立审查的阶段修复：

1. `HAR-CONV-01`：在 Harness 内补齐进展判断、无进展循环阻断和终态收敛；
2. `CTX-REHYDRATE-02`：Phase 1 合并后，复用现有 Event、Capsule、Artifact 和
   `rehydrate_projection()`，补齐压缩后的收敛状态恢复与按需重水合。

这里所称的 Runtime / Task Memory 只是现有事件投影中的最小工作状态，不是新的
Memory 数据库，也不包含 Agent Memory、Knowledge Memory、学习策略或长期偏好。

## 2. 复现证据与根因

同一类“图片识别 + Web 取数 + Skill 组织结果”的只读任务有如下对照：

| 路径 | 观察 |
|---|---|
| 当前 Zebra 集成任务 | 13 次模型调用、20 次工具调用、9 次压缩；同一图片证据被重复读取，仍未形成终答 |
| Zebra `main` 文本等价任务 | 取消前已发生 11 次模型调用、13 次抓取、7 次压缩，仍处于无进展路径 |
| 普通 Chat 模型对照 | 约 2 分钟内完成一次图片读取、13 个公开来源查询、一次计算和一个最终回答 |

这些证据说明：

- 正常任务的工具调用可以超过 8 次，恢复低次数上限不能解决问题；
- 换模型仍可复现，所以不是单纯的模型智力问题；
- 现有 guard 只识别完全相同的 `tool name + arguments`。模型只要轻微改变参数，
  即使得到同一批证据，也会被当成新动作；
- 压缩可以保持窗口可用，但不会自行判断任务是否已经获得足够证据，也不会强制
  从“继续找资料”切换到“形成最终回答”。

因此根因是执行阶段缺少“新证据、无进展、终态”之间的闭环，而不是缺少更大的
`max_tool_calls`。

## 3. 不变量

1. Session Event Store 继续是唯一耐久执行真相；不得增加第二套状态数据库或双写。
2. 默认 `max_model_calls=None`、`max_tool_calls=None` 保持不变；显式调用方预算仍严格执行。
3. Policy、Approval、取消、协议校验、幂等与副作用防重边界保持不变。
4. Zebra 只理解通用的目标、证据、工具结果、状态变化和终态，不引入金融、图片、
   交易日志或某个 Skill 的完成状态。
5. “未找到”“不可用”“权限不足”是可记录的证据状态；是否足以完成任务由用户目标和
   Skill 合约决定，不由 Runtime 猜测业务完整性。
6. FinOS 或其它调用方不复制循环、预算、压缩或终态状态机。

## 4. Phase 1：进展感知与终态收敛

### 4.1 最小状态

复用现有 Harness attempt metadata，只增加无法从当前值推导的三项状态：

- 已见过的稳定 observation fingerprints；
- 连续无新证据的 batch 数；
- 是否已进入一次性、禁用工具的终态综合轮。

不新增 `progress_score`、固定业务 phase enum、Memory 表或外部服务。若现有 tool
result、Artifact 引用或事件已经能提供字段，直接复用，不复制。

### 4.2 进展判定

现有精确 action fingerprint 继续用于幂等和副作用安全。另为已执行结果生成稳定的
observation fingerprint，至少覆盖：

- tool result 状态；
- 规范化后的结果内容摘要；
- 已有的 Artifact、来源或资源稳定引用。

provider call id、时间戳、展示顺序等易变字段不得制造“新证据”。一个 batch 只有在
产生此前未见的 observation，或产生已有可审计的 Task / Plan / Approval 状态变化时，
才重置无进展计数。不同参数得到相同证据仍算无进展。

### 4.3 收敛行为

连续无进展达到现有重复停止阈值时：

1. 不再执行该批工具；
2. 向 conversation 写入结构化、可见给模型的无进展 observation；
3. 仅允许一次禁用工具的最终综合调用；
4. 模型返回非空最终文本则正常 `COMPLETED`；
5. 模型仍请求工具或没有形成可用终答，则返回带 typed `stop_reason` 的
   `SUSPENDED`，不得伪造成功，也不得继续循环。

新证据出现时必须恢复普通工具循环。该机制按 batch 而不是全局调用次数工作，保证
长任务可以合法超过 8 或 16 次工具调用。

### 4.4 Phase 1 修改边界

Phase 1 只修改 `agent-core` Harness 的共享路径及其回归测试。不得修改 PR `#198`
正在维护的 `model_step.py`、Context、Storage、Worker、MCP/provider 或 FinOS 代码。
如果根因追踪证明必须越界，停止实现并记录具体调用链和最小 owned-path 变更建议。

## 5. Phase 2：投影恢复与按需重水合

`CTX-REHYDRATE-02` 在 PR `#198` 和 `HAR-CONV-01` 合并前保持 `Locked`。它只补：

1. 压缩前后的目标、验收条件、进展状态和证据引用可从 Event/Capsule 重建；
2. Active Projection 缺少完成判断所需的已引用证据时，调用现有
   `rehydrate_projection()` 按需恢复；
3. 重水合受 token budget、Policy、checksum 和 provenance 校验；
4. Worker 重启或强制压缩后不重复已经完成的只读工具调用。

Phase 2 不增加 Agent Memory、Knowledge Memory、Memory Controller、向量库、TTL
平台或跨任务学习。这些仍属于 v2.0 长期路线，必须另行激活。

## 6. 分支与合并路线

```text
origin/main @ a6b47c3
          + PR #198 / codex/issue-197-context-memory-continuity
                           |
                           v
          codex/runtime-convergence-phase1
          (先提交本文档，再实现 HAR-CONV-01)
                           |
                   人工审查，禁止直接合并
                           |
        PR #198 与 Phase 1 分别合并到 main 后
                           |
                           v
          codex/context-rehydrate-phase2
          (再激活 CTX-REHYDRATE-02)
```

当前 Phase 1 是叠加分支：同时包含 `origin/main` 的 v2.0 提案和 PR `#198` 的上下文
连续性实现。提交 PR 前应在 PR `#198` 合并后重放到更新后的 `main`，不得把代码直接
写到或推送到 `main`。

## 7. 验收基线

### 7.1 Phase 1 确定性门禁

- 先加入能复现“参数变化但证据不变”的红灯测试，再做最小修复；
- sequential 与 concurrent batch 的收敛语义一致；
- 相同证据的语义变体在有限轮次内进入一次终态综合，并完成或 typed suspend；
- 每次出现新证据时计数重置，超过 8 次工具调用的正常长任务仍能完成；
- 显式预算、Policy、Approval、取消、协议和副作用防重回归不变；
- focused tests、`make test`、`make check` 通过；继承阻塞必须单独列证据。

### 7.2 Provider-neutral A/B 验收

HAR-CONV-01 使用同一份 Skill 指令和同一份人工识别文字，对未修改的 `main`
与 Phase 1 做只读 A/B；不加载图片附件、MiniMax MCP 或 FinOS provider：

- 输入、模型、允许的公开数据源和“不得写入真实业务数据”约束一致；
- Zebra 在无默认调用次数上限下形成最终回答或明确 typed suspend；
- 参数或 URL 变化但没有新证据时必须收敛，不能把原始工具协议文本误报为完成；
- 记录模型调用、工具调用、压缩、重复 evidence、终态和总耗时；
- 真实图片只作为人工识别文字的离线来源，不进入 fixture、commit、日志正文或 PR；
- FinOS 项目分支的图片附件、MiniMax MCP 和镜像验收独立进行，不作为 Zebra
  `main` 收敛修复的前置条件。

### 7.3 Phase 2 门禁

- 强制多次压缩后，目标、验收条件和证据引用零丢失；
- Worker 重启后从 Event/Capsule 恢复收敛状态；
- 缺失投影证据可以按引用重水合，checksum 或 Policy 不通过时 fail closed；
- 无第二状态源、无业务语义、无跨任务隐式长期记忆。

## 8. 明确延期

- 完整 Memory 2.0 的 Agent Memory、Knowledge Memory 和 Memory Controller；
- 自动学习、反思、自优化、跨 Agent 共享经验；
- 为某个模型、MCP、图片工具、Web provider 或 FinOS 增加特判；
- FinOS 回测、TradingView 复盘、trench 页面及其它产品模块。
