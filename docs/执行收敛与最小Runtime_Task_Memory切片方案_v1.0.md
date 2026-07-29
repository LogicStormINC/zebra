# Zebra 执行收敛与最小 Runtime / Task Memory 切片方案 v1.0

| 字段 | 值 |
|---|---|
| 状态 | Phase 1 Runtime guard、Phase 1.5 / Policy Recovery、Terminal Follow-up 内容连续性、确认项推进与 FINAL 合同均已通过本地及真实 A 线验收，等待分支 Review；完整 Phase 2 锁定 |
| 日期 | 2026-07-29 |
| 当前任务 | `CTX-REHYDRATE-02`（Phase 1.5） |
| 依赖 | `CTX-MEM-01` / PR `#198` |
| 上位约束 | Event Store 唯一执行真相；Harness 无默认次数上限；业务语义留在调用方 |
| 关联文档 | `自适应Agent循环与预算治理方案_v1.0.md`、`上下文连续性与治理记忆改进方案_v1.1.md`、`Zebra Agent Runtime Upgrade Proposal v2.0.md` |

## 1. 决策

本次不提前建设完整 Memory 2.0。当前故障按三个可独立审查的边界修复：

1. `HAR-CONV-01`：在 Harness 内补齐进展判断、无进展循环阻断和终态收敛；
2. `CTX-REHYDRATE-02` 最小切片：作为 A 线必需的 Phase 1.5，复用现有
   `ContextCapsule`、`ProtectedInstructionLedger`、`ActiveContextProjection` 和
   `rehydrate_projection()`，让一次有界、禁用工具的终态综合消费恢复后的状态；
3. `HAR-CONV-01-POLICY-RECOVERY`：作为同一 Phase 1.5 的 P1 补完项，仅把 Policy
   明确标记为可纠正的只读工具输入拒绝转换成一次结构化失败 observation；
4. `CTX-SEG-02-FOLLOWUP-REHYDRATE`：修复同一 Task 的 terminal follow-up 长上下文
   回归，使同步 API 与 Worker 复用同一 Capsule/Projection 持久化与恢复合同；
5. `CTX-SEG-02-FOLLOWUP-RESOLVE`：让最新用户 follow-up 在规划或工具探索前优先
   解决恢复上下文中的待确认项，禁止再次询问已经回答的同一问题；
6. 完整 Phase 2：Worker 重启后的广义按需重水合和长期 Memory 路线继续锁定。

`HAR-CONV-01` 的 typed `SUSPENDED` 是安全失败，不是业务成功。A 线只有在固定输入
最终产生符合原始请求的完整结果时才通过；“不再无限循环”不能替代结果验收。

这里所称的 Runtime / Task Memory 只是现有事件投影中的最小工作状态，不是新的
Memory 数据库，也不包含 Agent Memory、Knowledge Memory、学习策略或长期偏好。

## 2. 复现证据与根因

同一类“图片识别 + Web 取数 + Skill 组织结果”的只读任务有如下对照：

| 路径 | 观察 |
|---|---|
| 当前 Zebra 集成任务 | 13 次模型调用、20 次工具调用、9 次压缩；同一图片证据被重复读取，仍未形成终答 |
| Zebra `main` 文本等价任务 | 取消前已发生 11 次模型调用、13 次抓取、7 次压缩，仍处于无进展路径 |
| `HAR-CONV-01@efbb8a3` 文本等价任务 | 一次有效澄清后，11 次模型调用、12 次抓取、7 次压缩；安全结束为 `tool_loop_no_progress`，但没有输出交易日志 |
| Phase 1.5 纯 A 线首次真实回放 | 完整 A 线源码、不含 FinOS/MiniMax/MCP；5 次模型调用、6 次工具调用后，模型提交带 fragment 的只读 `web.fetch` URL，Policy 正确拒绝，但 Harness 直接将唯一 Attempt 标为 `FAILED/retry_exhausted`，仍无交易日志 |
| Phase 1.5 + Policy Recovery 纯 A 线回放 | 单 Segment 已 `COMPLETED` 并输出 8,655 字结构化日志，但保留交易澄清；同一 Task 提交确认后正常 rollover，child Segment 仅输出 167 字并重新索要交易详情，未形成确认后的最终日志 |
| Terminal Follow-up 首轮实现验收 | source 已有 14,118 字 active Capsule，但 handoff adapter 把完整 objective 固定压到约 60 字，child 实际 continuity context 仅 427 字，12K 以后的交易事实全部丢失；首段最终仅输出 387 字“已完成”说明，child 则把带解释前缀的 raw DSML 工具请求误报为 `COMPLETED` |
| Continuity budget / FINAL / DSML 修复后回放 | initial Segment 一次 Attempt 输出 7,757 字结构化日志；source active Capsule 与 child compiled context 均保留完整 14,118 字 objective 和 12K 后交易事实。用户明确确认后 child 仍先执行无关 `files.list`，再调用 `agent.clarify` 重复询问同一确认项并进入 `waiting_input`；内容连续性已通过，剩余根因是 follow-up resolution contract 缺失 |
| Route A 最终真实验收 | 同一 14,118 字输入先经结构化澄清续跑生成 8,536 字日志；完成态再次提交同一句确认后，terminal rollover child 在 2 次模型调用内生成 6,686 字 / 261 行自包含日志，包含 12K 后卖出事实、18 只持仓、成本、风险和 `review_ready_data`，无重复 `agent.clarify`、`waiting_input`、DSML 或业务写入。一次只读空 `files.list` 被 Pro 判定为 non-blocking P2 优化，Business / Runtime Gate 均 PASS |
| 普通 Chat 模型对照 | 约 2 分钟内完成一次图片读取、13 个公开来源查询、一次计算和一个最终回答 |

这些证据说明：

- 正常任务的工具调用可以超过 8 次，恢复低次数上限不能解决问题；
- 换模型仍可复现，所以不是单纯的模型智力问题；
- 现有 guard 只识别完全相同的 `tool name + arguments`。模型只要轻微改变参数，
  即使得到同一批证据，也会被当成新动作；
- 压缩可以保持窗口可用，但不会自行判断任务是否已经获得足够证据，也不会强制
  从“继续找资料”切换到“形成最终回答”。
- 当前终态综合路径只追加通用停止指令，没有消费已经存在的 Capsule、protected
  ledger 和 projection recovery；因此恢复基础设施存在，但最后一次综合没有接线。
- 当前 Policy 审计能正确拒绝不合规 URL，但 Harness 把所有 `DENY` 都视为不可恢复
  Attempt 失败；这混淆了“可纠正的只读输入错误”和“不可绕过的授权/安全拒绝”。
- `CTX-SEG-02` 的文本 checkpoint 能覆盖短跟进，但同步 `execute=true` 路径没有像
  Worker 一样推进 active Capsule；terminal handoff 随后又把两条各约 2,000 字的
  checkpoint 合并后整体截为约 2,000 字，长任务的目标、完成条件和结果证据未进入 child。
- 完整 continuity 接通后，child 已同时看到恢复后的原目标、12K 后证据和最新用户确认，
  但仍把确认当作普通新消息，未先关闭恢复上下文中的待确认项，因而重复澄清。

因此根因是执行阶段缺少“新证据、无进展、终态”之间的闭环，而不是缺少更大的
`max_tool_calls`。

## 3. 不变量

1. Session Event Store 继续是唯一耐久执行真相；不得增加第二套状态数据库或双写。
2. 默认 `max_model_calls=None`、`max_tool_calls=None` 保持不变；显式调用方预算仍严格执行。
3. Policy、Approval、取消、协议校验、幂等与副作用防重边界保持不变。Policy 是
   deny 是否可纠正的唯一分类权威；Harness 不得解析 reason 文本自行放宽权限。
4. Zebra 只理解通用的目标、证据、工具结果、状态变化和终态，不引入金融、图片、
   交易日志或某个 Skill 的完成状态。
5. “未找到”“不可用”“权限不足”是可记录的证据状态；是否足以完成任务由用户目标和
   Skill 合约决定，不由 Runtime 猜测业务完整性。
6. FinOS 或其它调用方不复制循环、预算、压缩或终态状态机。
7. `SUSPENDED`、raw tool protocol 文本或“已尝试综合”都不等于业务完成；调用方和
   验收记录必须以实际最终输出为准。
8. 同一 Task 的 terminal follow-up 是正常多轮能力。若 source 有可验证的 Capsule /
   Projection，child 必须优先消费它；文本 checkpoint 只能在投影不存在时作有界兜底。
9. A 线的固定输入是已经完成图片识别的 Skill + 14,118 字 OCR 文本。
   Zebra `main` / A 线不负责图片识别，Vision、MiniMax MCP 和 FinOS 附件能力
   不是该验收的前置条件。
10. Runtime 只校验协议与结构安全，不在 Harness 中用金融词表、中英文
    短语或长度比例伪造业务完整性验证；结构化日志是否完整由固定 A 线
    live Eval 判定。

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
4. 终态指令要求输出自包含的最终正文，不得只引用 intermediate response
   或只说明“已完成”；非空且协议合法的文本可进入 `COMPLETED`，业务
   完整性仍由 Eval 硬门判定；
5. 模型仍请求工具、返回任何未 fenced 的 DSML tool-call grammar，或没有
   形成可用终答，则返回带 typed `stop_reason` 的
   `SUSPENDED`，不得伪造成功，也不得继续循环。

新证据出现时必须恢复普通工具循环。该机制按 batch 而不是全局调用次数工作，保证
长任务可以合法超过 8 或 16 次工具调用。

### 4.4 Phase 1 修改边界

Phase 1 只修改 `agent-core` Harness 的共享路径及其回归测试。不得修改 PR `#198`
正在维护的 `model_step.py`、Context、Storage、Worker、MCP/provider 或 FinOS 代码。
如果根因追踪证明必须越界，停止实现并记录具体调用链和最小 owned-path 变更建议。

## 5. Phase 1.5：终态投影恢复与有界综合

`CTX-REHYDRATE-02` 的最小切片提前激活，作为 A 线业务闭环的必要条件。它只补：

1. 使用现有 `ContextCapsule` 字段稳定承载 objective、显式完成条件、后续真实用户
   决策、计划和 Artifact 引用；不新增 `RuntimeTaskState` 或第二状态源；
2. 终态综合前通过现有 Context Port 边界构造恢复投影；`agent-core` 不得反向依赖
   `agent-context`；
3. Active Projection 含有完成所需的折叠证据时，复用 `rehydrate_projection()`，并
   保持 token budget、Policy、checksum 和 provenance 校验；
4. 最多执行一次 `allow_tools=False` 的 recovery-synthesis。成功必须返回可用最终
   文本；再次请求工具或没有可用答案仍 typed suspend，但该 A 线验收记为失败；
5. 不自动创建第二 Attempt，不修改 Worker、Storage 或 Event schema，除非红灯测试
   证明当前 Port 无法完成同一 Attempt 内的恢复。

Phase 1.5 不增加 Agent Memory、Knowledge Memory、Memory Controller、向量库、TTL
平台或跨任务学习。Worker 重启后的完整按需重水合仍属于后续 Phase 2。

### 5.1 Tool Policy Deny Recovery Boundary

真实 A 线回放证明同一 Attempt 还缺一条执行恢复边界。`parse_web_target()` 和现有
Policy 校验保持 fail closed，不静默删除 fragment，也不把 `DENY` 改成 `ALLOW`。

最小状态机为：

1. Policy 仍产生并持久记录 `POLICY_DECISION_MADE: deny`；
2. 只有 Policy 通过结构化字段显式标记为可纠正的只读工具输入错误时，Harness 才把
   它转换为 `ToolCallStatus.FAILED` observation，并向同一 Attempt 再开放一次模型纠正；
3. 该 observation 只说明“工具未执行及原因”，不得伪造外部结果，也不得消耗一次
   已执行工具计数；
4. 同一 Attempt 第二次出现可纠正 Policy deny 时，不继续循环，转入现有的一次
   recovered `allow_tools=False` synthesis；该综合仍不能执行工具；
5. 纠正后的工具产生新 evidence 时恢复普通循环；无进展时继续使用 Phase 1 的既有
   收敛阈值和终态综合；
6. `REQUIRE_APPROVAL`、人工拒绝、写入/副作用授权拒绝、网络权限拒绝、凭据/敏感路径、
   sandbox/工作区越界和任何未显式标为 recoverable 的 deny 仍立即等待或失败。

结构化分类复用现有 `PolicyDecision` 合约，只增加默认 fail-closed 的布尔标记；不新增
Policy 状态机、Event schema 或业务枚举。Web 输入校验可以设置该标记，Harness 和
测试不得依赖英文 reason 字符串、域名、金融业务、模型或 provider 特判。

### 5.2 Terminal Follow-up Recovery Boundary

`CTX-SEG-02-FOLLOWUP-REHYDRATE` 是既有 terminal follow-up 能力的长上下文 P1，仍属
A 线完成门的必要补完，不是 Memory 2.0。最小合同为：

1. 同步 `POST /tasks execute=true` 与 Worker 必须通过同一个 Context Port 语义持久化
   已验证的 compaction / active Capsule；API 不得导入 Worker 私有实现或另写第二份状态；
2. rollover 继续使用现有 Task、Segment、Handoff 和 Event Store 生命周期，不新增
   Task、Attempt、表或 Event schema；
3. source 存在 active Capsule / projection 时，handoff 必须携带其已有引用、校验信息
   和 source event range；child 通过现有 Context/rehydration Port 恢复原目标、完成条件、
   用户可见的最近对话和完成所需证据，再叠加本次 follow-up 用户消息；
4. 当前 follow-up 文本可以成为 child 的 immediate objective，但不得覆盖或替代原始
   Task objective、acceptance、decision 和 evidence；
5. 只有在 source 没有可用投影时，才使用有界 conversation checkpoint。存在投影时
   不得退化为两次固定字符截断，也不得仅靠 prior assistant/head-tail 猜测任务状态；
6. 重水合继续执行 checksum、source range/hash、Policy、provenance 和 token budget
   校验；不得带入 provider-private continuation、reasoning、凭据或 raw tool output；
7. 投影缺失、损坏或超预算时 fail closed，并留下可诊断状态；不得伪造“已恢复”或
   拼接业务 prompt 以绕过同一 Task 多轮合同。
8. `active_projection` continuity 不得由 adapter 用 60/128/85/65 等字符数
   手工裁剪。`HarnessModelStep` 在构建 initial messages 前使用已有的
   provider-neutral `ModelContextWindow.compaction_reserve_tokens`，计算
   `max(task.context_token_budget, compaction_reserve_tokens)` 作为该轮有效 Context
   budget；不新增 token 常量、Task 字段或 provider 分支。
9. handoff adapter 只输出经验证的 objective、acceptance criteria、protected
   constraints、decisions 和 Artifact/evidence references，并交给现有 Context
   Compiler 按 priority 和 token count 选择。`capsule.plan` 不是用户可见对话，
   不得映射成 `visible_conversation`。
10. 最终模型请求继续通过现有 `plan_context_window` 硬门；本轮不新增
    Conversation Message Replay、FinalAnswerValidator 或任何业务/语言启发式。
11. 最新 user follow-up 是恢复上下文之后的当前权威输入。若它已回答或解决已有
    pending clarification，Runtime 必须先推进该状态，再进入规划或工具探索；不得再次
    请求同一澄清，也不得以空工作区等与已有 evidence 无关的探索替代结果生成。
12. terminal follow-up 保留正常工具能力；不得把所有 child 首轮强制为
    `allow_tools=false`。只有新的、完成任务不可绕过的关键缺口仍可请求澄清；该判断不得
    依赖金融、Skill、语言、长度或 provider 特判，也不得新增状态 schema。

真实验收中的一次无副作用 `files.list` 没有造成循环、重复澄清或错误结果，按 Pro
结论不阻塞 Phase 1.5。减少“恢复 evidence 已充分仍探索空 workspace”可作为独立 P2，
不得反向扩大本阶段或改成全局禁用工具。

允许为复用共享 persistence/rehydration Port 扩大 API、Context、Core 和执行入口的
owned paths；不授权新 Worker 架构、Storage schema、FinOS/provider 或业务特判。

## 6. 分支与合并路线

```text
origin/main @ a6b47c3
          + PR #198 / codex/issue-197-context-memory-continuity
                           |
                           v
          codex/runtime-convergence-phase1 @ efbb8a3
          (Runtime guard；A 线业务结果尚未通过)
                           |
                           v
          codex/context-rehydrate-phase1-5
          (最小完成切片 + Policy Recovery + Terminal Follow-up P1)
                           |
                   A 线完整日志人工验收
                           |
                   人工审查，禁止直接合并
```

Phase 1.5 从 `efbb8a3` 及本次文档基线创建独立叠加分支，继续包含 PR `#198` 的
上下文连续性实现。提交 PR 前应在 PR `#198` 合并后重放到更新后的 `main`，不得把
代码直接写到或推送到 `main`。

## 7. 验收基线

### 7.1 Phase 1 确定性门禁

- 先加入能复现“参数变化但证据不变”的红灯测试，再做最小修复；
- sequential 与 concurrent batch 的收敛语义一致；
- 相同证据的语义变体在有限轮次内进入一次终态综合，并完成或 typed suspend；
- 每次出现新证据时计数重置，超过 8 次工具调用的正常长任务仍能完成；
- 显式预算、Policy、Approval、取消、协议和副作用防重回归不变；
- focused tests、`make test`、`make check` 通过；继承阻塞必须单独列证据。

### 7.2 Provider-neutral A/B 验收

HAR-CONV-01 使用同一份 Skill 指令和同一份已识别的 14,118 字 OCR 文本，对未修改的 `main`
与 Phase 1.5 做只读 A/B；不加载图片附件、MiniMax MCP 或 FinOS provider：

- 输入、模型、允许的公开数据源和“不得写入真实业务数据”约束一致；
- Zebra 在无默认调用次数上限下必须形成完整交易日志；typed suspend 只证明安全
  收敛，不计为 A 线业务成功；
- 参数或 URL 变化但没有新证据时必须收敛，不能把原始工具协议文本误报为完成；
- 记录模型调用、工具调用、压缩、重复 evidence、终态和总耗时；
- 真实图片只作为已识别文字的离线来源；A 线本身没有也不验收图片
  识别能力，图片不进入 fixture、commit、日志正文或 PR；
- FinOS 项目分支的图片附件、MiniMax MCP 和镜像验收独立进行，不作为 Zebra
  `main` 收敛修复的前置条件。

### 7.3 Phase 1.5 门禁

- 强制多次压缩后，目标、显式完成条件、用户澄清决定和证据引用零丢失；
- 同一份 14,118 字 Skill + 人工识别文字允许必要澄清，但确认后必须输出完整日志；
- 终态 recovery-synthesis 只有一次且始终 `allow_tools=False`；
- 缺失投影证据仅按现有引用重水合，checksum、Policy、provenance 或 token budget
  不通过时 fail closed；
- 正常产生 evidence/state delta 的长任务不被误杀；
- 带 fragment 的 `web.fetch` 被 Policy 拒绝并保留审计，模型只获得一次结构化纠正
  机会；纠正后可继续或形成最终日志，不能直接 `retry_exhausted`；
- 第二次 recoverable deny 进入一次工具禁用综合，不得形成新的 Policy/tool 循环；
- 写入、副作用、凭据、网络授权、越界和人工拒绝保持 terminal/waiting，不得进入
  recoverable observation；
- 同一 `/tasks/{id}` 先输出待确认日志，再提交确认并发生 terminal rollover；child
  必须恢复 source Capsule/Projection，输出确认后的完整日志，不得重新索要已给数据；
- 14,118 字 fixture 必须把任务必需的交易 sentinel 放在 12K 以后，并直接
  断言 child compiled messages 包含该尾部事实；仅校验前 60 字或
  `handoff_source=active_projection` 元数据不算通过；
- active projection 使用现有 model compaction reserve 动态扩展 continuity budget，
  不使用字符级截断、新常量或 `capsule.plan` 伪造对话；
- 同步 API 与 Worker 对同一 compaction 产生等价的 active Capsule；handoff 在有
  Capsule 时不得只使用固定 2,000 字 checkpoint；
- child 只恢复用户可见对话、Capsule 状态和经验证的 evidence；provider-private、
  reasoning、凭据及 raw tool output 仍不可跨 Segment；
- terminal synthesis 指令必须要求自包含的 FINAL 日志正文；“以上已完成”等
  非自包含说明不通过 A 线 live Eval，但 Harness 不新增金融/语言词表
  validator；
- `allow_tools=False` 终态输出中，任何带普通解释前缀的未 fenced DSML
  `tool_calls` + `invoke` grammar 也必须 typed `SUSPENDED`，不得 `COMPLETED`；
- FinOS 核心业务表前后全行哈希一致；
- 无第二状态源、无业务语义、无跨任务隐式长期记忆。

## 8. 明确延期

- 完整 Memory 2.0 的 Agent Memory、Knowledge Memory 和 Memory Controller；
- 自动学习、反思、自优化、跨 Agent 共享经验；
- 为某个模型、MCP、图片工具、Web provider 或 FinOS 增加特判；
- FinOS 回测、TradingView 复盘、trench 页面及其它产品模块。
