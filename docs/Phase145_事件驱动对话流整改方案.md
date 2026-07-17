# Phase 145 事件驱动对话流整改方案

## 1. 背景

当前 Desktop 任务页将持久化 Session Event 归纳为固定的 Planning、Context、
Tools、Result、Verification、Completed、Review 阶段，并将执行轨迹和对话消息
分块放在阶段列表之后。

这种布局适合展示粗粒度进度，但不适合作为工程 Agent 的主对话界面：真实执行会
读取上下文、调用工具、等待批准、失败、重试和再次验证，不是单向流水线；同时，
固定阶段列表占据首屏，导致最终回答、文件变化和交付物需要继续向下寻找。

本阶段以用户选定的 Codex 风格事件流截图为视觉目标，将主区域改造成按持久化事件
顺序呈现的真实工作流，同时保留现有 Desktop 顶部任务栏、右侧检查器、底部
Composer、durable task navigation 和 local-first API 配置。

## 2. 用户目标

用户打开或恢复一个任务后，应能连续看清：

1. 自己提交了什么任务；
2. Agent 当前正在执行什么；
3. 调用了哪些工具以及结果是否成功；
4. 是否需要批准或补充信息；
5. 最终回答是什么；
6. 产生了哪些变更和交付物；
7. 如何继续追问。

## 3. 设计原则

- 真实事件优先：所有过程状态来自有序持久化事件，不伪造阶段或 Git 状态。
- 结果优先：最终回答是视觉主角，工具原始参数和长输出默认折叠。
- 一条时间流：消息、工具、审批、澄清、验证和终态按事件序列连续呈现。
- 渐进披露：主流展示可理解摘要，完整证据留在可展开内容和右侧 Logs。
- 复用优先：复用现有 SessionEvent、task plan、approval、clarification、trace、
  Markdown 和 inspector 组件，不引入新依赖。
- API 最小化：现有 session stream 足够时不增加 API；只有缺少安全、稳定字段时才
  添加向后兼容字段。

## 4. 目标信息架构

页面继续使用三层结构：

1. 顶部任务栏：标题、任务状态、工作区、设置、刷新和会话操作；
2. 中部工作区：左侧事件驱动对话流，右侧 Context / Logs 检查器；
3. 底部 Composer：附件、模式、输入、发送或停止。

主对话流按以下顺序投影：

- 用户消息；
- 可见任务计划；
- 模型或 Harness 运行状态；
- 合并后的工具调用；
- 审批或澄清卡片；
- Assistant 回答；
- 终态和验证摘要。

## 5. 事件投影模型

前端建立一个确定性的 `SessionEvent -> TimelineItem` 投影层：

| 事件 | 可见条目 |
| --- | --- |
| `user_message_received` | 用户消息 |
| `plan_proposed` / `plan_updated` | 任务计划入口或更新状态 |
| `model_request_started` / `harness_attempt_started` | 处理状态 |
| `tool_call_proposed` | 工具调用开始 |
| `policy_decision_made` | 工具策略结果 |
| `tool_execution_started` | 工具运行状态 |
| `tool_execution_completed` | 成功工具结果 |
| `tool_execution_failed` | 失败工具结果 |
| `approval_requested` | 行内审批入口 |
| `clarification_requested` | 行内澄清入口 |
| `model_response_received` | Assistant Markdown 回答 |
| `session_completed` | 完成状态 |
| `session_failed` / `session_cancelled` | 失败或取消状态 |

投影必须：

- 先按 `sequence` 排序；
- 将同一次工具提议、策略决策、开始和结果合并；
- 保留 attempt 边界与失败、重试语义；
- 不重复渲染用户消息或 Assistant 回答；
- 对未知事件安全忽略，并允许在 Logs 中检查原始事件；
- 不显示不可验证的模型内部思维内容。

## 6. 组件整改

### 6.1 SessionThreadWorkspace

- 移除固定阶段列表和阶段占位。
- 保留任务摘要卡，但压缩为标题、真实状态、事件和工具统计。
- 按统一 TimelineItem 顺序渲染事件流。
- 保留右侧 Context / Logs 检查器。
- 草稿状态只展示真实未启动状态，不展示六个等待阶段。

### 6.2 SessionExecutionTrace

- 从独立大卡片改为事件流内的紧凑工具组。
- 成功工具默认折叠；失败和等待状态默认展开。
- 摘要行显示工具名、状态和安全输出摘要。
- 展开区显示参数、输出和 Policy 结果。
- 使用原生 button / details 语义提供键盘操作和展开状态。

### 6.3 AssistantMessageBlock

- 继续复用 XMarkdown 和复制动作。
- 提高正文层级，不让 Trace 卡片压过最终回答。
- 保持代码、列表、引用和链接的现有安全渲染路径。

### 6.4 Approval、Clarification 和 Task Plan

- 保持现有真实交互逻辑。
- 入口放入对话流对应位置；当前状态无法精确定位时，放在最新运行状态之后，
  不复制或伪造历史可操作卡片。

## 7. API 整改边界

第一实现路径直接复用现有 session summary、ordered session stream、approval、
clarification 和 task plan projection。除非实现证明前端无法稳定关联工具事件，否则
不增加 API。若确实缺少关联字段，只能添加安全、向后兼容的 attempt、tool run identity
或耗时字段，不改变既有事件类型、Policy、HITL、存储和恢复语义。

## 8. 可访问性和响应式

- 灰色正文和状态文本保持足够对比度，不把普通信息呈现成禁用状态。
- 折叠控制使用 button 或 details，并暴露展开语义。
- 图标按钮继续提供 `aria-label` 和可见 Tooltip。
- 运行状态使用克制的 `aria-live="polite"`，不朗读原始日志洪流。
- 交互目标保持至少约 44 x 44 px。
- 900px 宽度下右侧检查器下沉或折叠，页面不得水平溢出。
- 动效遵循 `prefers-reduced-motion`。

## 9. 实施顺序

1. 建立 TimelineItem 类型和纯投影函数，并先补确定性检查；
2. 使用投影替换固定阶段列表和分离的消息 / Trace 排列；
3. 收紧视觉层级、折叠交互、响应式和可访问性；
4. 仅在现有事件字段不足时添加 additive API 字段和后端测试；
5. 完成 focused desktop checks、生产构建、仓库检查和浏览器视觉验收。

## 10. 验收标准

- [x] 主区域不再显示固定七阶段占位列表。
- [x] 可见事件按持久化 `sequence` 稳定排序。
- [x] 同一次工具提议、策略决策、执行和结果合并展示。
- [x] 多 attempt、失败和重试不会被折叠成单向成功流程。
- [x] 用户和 Assistant 消息不重复。
- [x] Assistant 回答具有高于工具日志的内容层级。
- [x] 成功工具默认折叠，失败或运行中状态明确可见。
- [x] 审批、澄清、任务计划和右侧检查器的现有功能保持可用。
- [x] 刷新或恢复后，事件流顺序与 durable stream 一致。
- [x] 900px 和桌面视口无水平溢出，键盘可操作折叠和检查器。
- [x] focused frontend checks、`pnpm build` 和 `make check` 通过。
- [x] 设计 QA 使用相同状态和视口对照目标截图，P0-P2 问题清零。

## 11. 明确非目标

- 不公开模型隐藏思维链；
- 不引入新的前端状态管理或 UI 依赖；
- 不重写 Session API、事件存储、Harness、Policy 或 HITL；
- 不在本阶段增加新的文件编辑器、Diff 编辑能力或云端服务；
- 不改变新任务启动配置和 attachment / MCP authority 语义。

## 12. 实施结果

- 前端新增纯 `SessionEvent -> TimelineItem` 投影，按 sequence 排序，并以
  attempt 与 tool-call identity 合并工具生命周期；旧事件使用与后端一致的
  FIFO 关联规则。
- 固定阶段列表已删除，用户消息、运行状态、工具证据、Assistant 回答和终态进入
  同一连续事件流；任务计划只在其最新 durable 位置展示一次。
- 工具证据使用原生 `details`：成功默认折叠，失败、拒绝、等待批准或运行中默认
  展开；参数和输出有界展示。
- 现有 API 的 sequence、attempt number 和 tool-call identity 已满足稳定投影，
  因此遵循 API 最小化原则，没有扩大 API、存储、Policy 或 HITL 合同。
- 16 项桌面检查、Node 22 生产构建、1312 项后端测试、`make check`、1512px
  与 900px 浏览器验收和截图设计 QA 均通过；详细证据见根目录
  `design-qa.md`。
