# ADR-026: Task/Turn/Segment 生命周期与多轮连续性

- 状态：Accepted（2026-08-24）
- 关联：ADR-013（稳定 Task 身份）、ADR-025（Cloud Context 继承）、
  `CTX-INHERIT-CLOUD-01`（物化基础）
- 任务卡：`CTX-TURN-ADR-01`（本文档）及其实现卡 `CTX-TURN-*`

## 1. 背景与问题

当前实现把"一次最终模型回答"直接映射为 `SESSION_COMPLETED`：

- `execution_finalization` 在每个 COMPLETED outcome 后写 `SESSION_COMPLETED`；
- 消费者（AG-UI `RUN_FINISHED`、Memory finalization、标题生成、
  Workspace 终态、Child 唤醒）全部以该事件为触发点；
- 终态后续问只能通过 Handoff rollover 创建新 Segment。

后果：普通对话四五轮就产生新 Segment，Task 身份与上下文连续性被
执行细节绑架；`WAITING_INPUT` 被迫兼任"等待下一轮"；终态语义
（Task 是否结束）与执行纪元（Segment）没有区分。

## 2. 决策：三层生命周期模型

```text
Task：用户和 Host 感知的稳定会话
└── Execution Segment：内部执行/上下文/authority 纪元
    ├── Turn 1：用户消息 → 模型/工具 → 最终回答
    ├── Turn 2
    └── 只有硬边界才 rollover 到下一个 Segment
```

| 对象 | 状态 | 终态含义 |
|---|---|---|
| Task | `open/completed/failed/cancelled`（投影） | 整个用户任务是否结束 |
| Turn | `running/waiting_approval/waiting_input/completed/failed/cancelled` | 一轮交互结果 |
| Segment | 沿用 `SessionStatus`，新增 `awaiting_turn` | 当前执行纪元能否接收下一轮 |
| Attempt | 保留 Harness Attempt | 一次模型/工具执行尝试 |

关键规则：

- 普通最终回答：`TURN_COMPLETED → Segment.awaiting_turn → Task.open`
- 下一条普通消息：继续当前 Segment，创建新 Turn
- `WAITING_INPUT` 只表示当前 Turn 等待澄清，不再兼任"等待下一轮"
- 只有 context hard watermark、崩溃恢复、authority/workspace/provider
  边界、显式 fork 才 rollover 到新 Segment

## 3. 交互模式（interaction_mode）

`TASK_PREPARED` 新增 `interaction_mode` 字段：

- `conversation`：普通 Zebra/AG-UI 对话。Turn 完成不写 `SESSION_COMPLETED`，
  Segment 停在 `awaiting_turn`。
- `one_shot`：内部 Child、批处理、明确的一次性 Host Run。首个 Turn
  完成后写 `TURN_COMPLETED(closes_segment=true)` 并补写
  `SESSION_COMPLETED`（兼容现有终态消费者）。
- 老事件缺失该字段：读侧统一解释为 `legacy_one_shot`，行为与现状
  完全一致（每个最终回答 → `SESSION_COMPLETED`），历史重放不变。

模式由 admission 请求（经 `parse_create_session_payload` 校验）决定，
不根据 prompt 猜测，不允许模型自行修改。Agent Definition 侧的
模式声明是后续增量（`AgentDefinitionSnapshot` 尚无该字段，当前
definition 不能设置 conversation）。默认值在灰度推进中逐层从
`one_shot` 切换为 `conversation`（见 §8）。

## 4. 事件合同

### 4.1 Turn 开启

人类 `USER_MESSAGE_RECEIVED` 开启一个 Turn，payload 新增：

- `turn_id`：确定性 TurnId，由 `uuid5(NAMESPACE_URL,
  "zebra:turn:{session_id}:{turn_index}")` 派生——同一 Segment 内
  每个人类消息对应唯一递增 `turn_index`，重放/重试收敛到同一 id
- `turn_index`：Segment 内从 0 递增
- `origin`：`human`；handoff seed 写 `session_handoff`；老事件缺省

人类消息与自动指令分离：

- 人类消息：`actor=user, origin=human`
- Handoff seed：`actor_kind=automation` + `source=session_handoff`
  （沿用现有 provenance 五元组，读侧兼容）
- Context History 只选择真实人类消息

### 4.2 Turn 终结

新增事件（payload 均带 `turn_id`）：

- `TURN_COMPLETED`：`turn_id, turn_index, summary, closes_segment,
  usage/result metadata`
- `TURN_FAILED`：`turn_id, turn_index, reason, metadata`
- `TURN_CANCELLED`：`turn_id, turn_index, reason`

对 `one_shot`：

```text
TURN_COMPLETED(closes_segment=true)
SESSION_COMPLETED        # 兼容现有终态消费者
```

对 `conversation`：

```text
TURN_COMPLETED(closes_segment=false)
# 不写 SESSION_COMPLETED；Segment → awaiting_turn
```

崩溃恢复：Worker 在两个兼容事件之间崩溃时，恢复逻辑根据
`TURN_COMPLETED(closes_segment=true)` 补写同一幂等 `SESSION_COMPLETED`
（幂等键 `turn-close:{turn_id}`），不得再次调用模型。

### 4.3 Segment 状态

`SessionStatus` 新增 `awaiting_turn`：

- `RUNNING → AWAITING_TURN`（`TURN_COMPLETED(closes_segment=false)`）
- `AWAITING_TURN → RUNNING`（下一 Turn 的执行事件）
- `AWAITING_TURN → READY`（该 Segment 收到新人类消息、待 Worker 领取）
- `AWAITING_TURN → SUSPENDED/COMPLETED/FAILED/CANCELLED`（真终态路径）

Workspace 同步：`TURN_COMPLETED` 将 Workspace 从 `running` 投影回
`prepared`（释放执行态）；`completed/failed/cancelled` 只由
`SESSION_*` 真终态触发。

## 5. 消息并发不变量

`SessionCommandKind.MESSAGE` 是唯一命令入口，不新增平行命令系统：

- 普通 MESSAGE 只允许在 `Segment.awaiting_turn`（或首条消息的
  READY/CREATED）
- 澄清回复只允许在 `WAITING_INPUT`，并继续原 Turn
- RUNNING/WAITING_APPROVAL 下的第二条普通消息拒绝（409
  `turn_in_progress`），不得静默并发进同一 Turn
- 相同 idempotency key + 相同内容返回同一 Turn
- 相同 key + 不同内容返回冲突（409）
- 相同 expected revision 的两个不同消息最多接受一个（命令缝既有
  CAS 语义）

## 6. 终态消费者迁移矩阵

| 当前职责 | 新触发点 |
|---|---|
| AG-UI `RUN_FINISHED` | `TURN_COMPLETED` |
| 每轮 usage/trace | `TURN_COMPLETED` |
| 标题生成 | 第一个成功 `TURN_COMPLETED`，幂等 |
| Memory candidate 抽取 | 每个成功 Turn 一次，以 durable 抽取窗口
  （`memory_extraction_window`，按 Turn close 与最新提取事件锚定）
  防重与补扫 |
| Provider continuation 持久化 | 沿用 `CONTEXT_CONTINUATION_SELECTED`（每模型调用） |
| Provider continuation 删除 | Segment/Task 真终态（TTL 兜底） |
| Workspace 释放执行态 | `TURN_COMPLETED` |
| Workspace 最终关闭/回收 | `SESSION_COMPLETED/FAILED/CANCELLED` |
| Child 完成后唤醒 Parent | one-shot Child 的 Task/Segment 真终态 |
| Handoff/Rollover | Segment 真终态或 suspended |
| Session history/list | 同时理解 Turn 完成和 Task 终态 |
| Task public status | Task/Turn/Segment 三种状态组合投影 |

## 7. 上下文覆盖不变量

同 Segment 跨 Turn 的前提下，模型上下文必须满足：

```text
模型上下文 =
  已验证 Context Capsule 覆盖的前缀
  + Capsule 之后连续的精确消息尾部
  + 当前 Turn 输入
```

- Capsule 与精确 tail 之间不能有 sequence 缺口
- 无 Capsule 时不得静默截掉历史前缀（显式 omission 或 fail closed）
- 超预算先 compaction，再重新物化；compaction 失败 fail closed
- 最近至少三轮真实用户 Turn 与完整 tool group 精确保留
- 自动 Handoff seed 不进入人类对话历史（ADR-025 收口已实现）
- `MAX_INHERITED_HISTORY=12` 只保留给 Child `fork_tail/resume`
- 当前 Task/Segment 走独立的 current-session materializer
- Provider continuation 跨 Turn 复用必须同时匹配 Session/Segment、
  provider/model/capability version、expiry、authority scope 与
  source hash；不匹配即丢弃，绝不跨 Segment 转移

## 8. 灰度与回滚

上线顺序：

1. 只发布 Turn 事件读取能力，旧行为不变（`legacy_one_shot`）
2. 内部测试 Definition 开启 `conversation`
3. Zebra AG-UI 新建 Task 开启
4. Trench staging 分别测试 conversation/one-shot
5. 指标稳定后交互式 Task 默认 `conversation`
6. 最后才考虑旧 Task 显式一次性升级

回滚不删除、不修改历史事件：停止为新 admission 发 `conversation`；
已有 v2 Task 保持可读可恢复；legacy reader 同时理解有无 Turn 事件的
流；保留 `SESSION_COMPLETED` 消费兼容至少一个完整发布周期。

## 9. 监控

`turns_per_segment`、`segments_per_task`、`rollover_total{reason}`、
`turn_completion_duration`、`turn_admission_conflict_total`、
`context_coverage_gap_total`（必须为 0）、
`provider_continuation_reuse_total`、`legacy_task_upgrade_total`、
`duplicate_effect_total`（必须为 0）。
