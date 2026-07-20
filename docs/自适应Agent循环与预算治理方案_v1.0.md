# 自适应 Agent 循环与预算治理方案 v1.0

## 1. 问题与根因

Zebra 当前在 API 和 harness 内部同时存在很低的默认模型/工具调用上限。
这会把“安全边界”与“正常推理深度”混为一谈：模型仍在获取新证据，
却因为达到固定次数而被禁止调用工具，最后向用户暴露“任务失败”。

根本问题不是某一个工具预算太小，而是缺少两类边界的分层：

- 默认执行策略：应由模型根据任务复杂度决定是否继续调用工具。
- 显式资源合约：调用方确实可以设置硬上限，但耗尽应是可恢复暂停，
  不是模型或任务失败。

## 2. 参考实现结论

- Codex 以持续的工具结果回传驱动循环，并通过上下文压缩管理长任务；
  不把很小的固定工具次数作为普通任务的默认边界。
- Claude 的 tool runner 持续循环到模型不再返回 `tool_use`；显式
  `max_iterations` 是可选的调用方合约。服务端工具达到内部迭代边界时使用
  `pause_turn`，由客户端回传并继续，而不是立即宣告任务失败。
- Hermes 使用较高的循环上限作为最后熔断，配合上下文压缩与最后收尾轮；
  它删除了过早的预算告警，因为这会诱导模型提前放弃。

参考：

- <https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs>
- <https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json>
- <https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner>
- <https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works>
- <https://github.com/nousresearch/hermes-agent/blob/main/website/docs/developer-guide/agent-loop.md>
- <https://github.com/nousresearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md>

## 3. Zebra 最终设计

### 3.1 默认无次数上限

- `max_model_calls` 和 `max_tool_calls` 省略时保持 `None`。
- API、session bootstrap 和 harness 不再注入 `4/3` 或 `8/6` 之类的隐式上限。
- 简单任务由模型直接回答；复杂任务可持续调用工具。

### 3.2 并发与总预算分离

- `max_parallel_tool_calls` 只限制同时执行数，不限制任务总工具次数。
- provider 一次返回的完整 tool batch 必须整批预检；不能静默丢弃成员。

### 3.3 显式硬额度是可恢复暂停

- 调用方显式设置的 `max_model_calls` / `max_tool_calls` 仍严格执行。
- 额度无法容纳下一个完整 batch 时，不启动部分工具，不伪造最终答案，
  而是返回 `SUSPENDED` 并持久化 `session_suspended`。
- 完整 batch 恰好用完工具额度且仍有模型轮次时，允许一次禁用工具的
  收尾轮；模型如果仍要求工具，则进入 `SUSPENDED`。
- 暂停元数据包含边界类型、已用/上限、未执行 batch 大小，便于运营层
  调整合约后恢复。

### 3.4 进展感知的循环收敛

默认无次数上限不等于无限死循环：

- 相同工具+参数的重复 action 继续由现有 fingerprint 机制阻断。
- 被拒绝、失败、空读取结果必须作为结构化 tool result 回传模型，
  让模型更换工具、参数或直接回答。
- 同一无进展路径再次重复时才作为硬停止；已产生新证据或副作用的调用
  不应受低次数阈值影响。
- 长会话依靠现有 context compaction 保持 provider 上下文可用。

### 3.5 用户界面

- 用户只看到任务进度、真实工具结果、可恢复暂停或终态。
- NoopVerifier 的 `verifier hook skipped` 不进入任务时间线或日志。
- 内部 Segment 和 handoff 继续对用户不可见，终态续问自动带入最近的
  user/assistant 检查点。

## 4. 本次实施范围

1. API 和 bootstrap 的模型/工具额度默认值改为 `None`。
2. harness 移除内建 `8/6` 次数上限，全链路支持可选额度。
3. 显式额度耗尽返回 `SUSPENDED` 并记录可恢复事件。
4. 保留重复 action、Policy、Approval、取消与协议完整性边界。
5. 保留终态续问检查点与 Desktop NoopVerifier 降噪。

## 5. 验收标准

- 未显式设置额度的 API 任务可执行超过 6 个工具调用并正常完成。
- 显式设置硬额度时，超限 batch 一个也不启动，Session 进入
  `suspended`，且不记录 `session_failed`。
- 明确失败/拒绝的工具结果回传模型，模型可选择替代工具后完成。
- 重复 action 仍可确定性停止，不会因取消默认次数上限而无界循环。
- 终态续问保留最近 user/assistant 检查点，Desktop 不展示 NoopVerifier 噪声。
- 目标回归、全量测试、Desktop checks/build 和 `make check` 通过。

## 6. 非目标

- 不取消 Policy、Approval、运行时隔离、出站网络或取消边界。
- 不在本次引入计费、租户配额或订阅系统。
- 不通过业务意图关键词或特定领域路由决定工具数量。
