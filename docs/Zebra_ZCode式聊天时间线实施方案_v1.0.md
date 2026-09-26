# Zebra ZCode 式聊天时间线实施方案 v1.0

状态：Review（本地实现与 Host 验收完成）
更新日期：2026-09-27

## 1. 目标

将 Zebra React 聊天界面从“消息列表 + 全局活动列表”升级为按 Turn 组织的
Agent Conversation Timeline。AG-UI 表现层按 2026-09-27 的 ZCode `main`
公开实现对齐正文列、Turn、消息、推理/工具摘要与 Composer 的几何和交互；
Zebra 仍使用自己的事件、类型和组件，不引入 ZCode 运行时或包依赖。

Trench 是首个消费者。Zebra 提供可复用 React 时间线，Trench 只提供业务内容
renderer、路由、登录、会话列表、来源、报告和 Artifact 操作。

## 2. 产品原则

- 一个 Turn 同时拥有用户输入、执行过程、最终输出、交互请求和 Artifact。
- 执行过程保持真实顺序；不把所有 Tool 活动堆到整段会话末尾。
- 当前运行 Turn 保持展开；终态后自动折叠，失败和阻塞保持可诊断。
- 历史 Turn 与实时尾部使用同一视觉列，但拥有独立更新边界。
- 空会话与活跃会话复用同一个 Composer DOM，切换时只改变布局。
- 用户上滚后停止自动追随；主动返回底部后恢复追随。
- UI 只展示公开 narration、Tool 状态和安全错误，不展示私有思维链。
- 保持模型、思考强度、权限、PostgreSQL 权威链路和 Durable Event 协议不变。

## 3. 组件边界

```text
AgentChat
├── AgentConversationTimeline
│   ├── AgentTurnGroup
│   │   ├── user message
│   │   ├── AgentWorkSegment
│   │   ├── assistant final output
│   │   └── turn resources/actions slots
│   └── live tail
├── latest-output control
└── sticky composer dock
```

公开 contract 新增：

- `AgentConversationTurn`
- `AgentTurnStatus`
- `AgentWorkSegment`

`AgentChat` 接受新的 `turns` 属性，同时保留 `messages`/`activities` 兼容入口。
宿主可逐步迁移，不发生一次性破坏性升级。

## 4. 实施阶段

### A. Contract 与投影

1. 在 `ui-contracts` 增加 Turn 与 work segment 类型。
2. 提供纯函数，将兼容消息和活动投影为 Turn。
3. 保证相同输入得到稳定顺序和稳定 key。

### B. React 时间线

1. 新增 `AgentConversationTimeline`。
2. 新增 `AgentTurnGroup` 和 `AgentWorkSegment`。
3. 当前执行段自动展开；成功完成后折叠；失败、阻塞保持展开。
4. 最终答案和业务 renderer 保持最高视觉权重。

### C. 布局与滚动

1. Composer dock 进入同一个聊天 shell，使用 sticky bottom 布局。
2. 空态居中与聊天态底部之间只发生 CSS 布局过渡。
3. 保留用户滚动所有权和“查看最新输出”入口。
4. 按 `scrollKey` 保存和恢复会话滚动位置。

### D. Trench Adapter

1. 将 `StrategyMessage[]` 映射为 `AgentConversationTurn[]`。
2. 将 `metadata.agent_steps` 映射为 Turn 内 work segment。
3. 用 Zebra `AgentChat` 替换 Ant Design `Bubble.List` 主骨架。
4. 保留 Trench Markdown、来源、记忆回执、文件交付、报告和反馈 renderer。
5. 删除重复的页面级进度渲染，避免同一活动显示两次。

### E. 验收

- SDK 类型检查、单测、构建、pack、Vite/Next 消费矩阵通过。
- Turn 顺序、终态折叠、失败展开、Composer DOM 保持、滚动跟随有回归测试。
- Trench frontend tests、lint、production build 和浏览器验收通过。
- 现有 IME、附件、暂停、继续、队列、模型/模式/思考强度选择不退化。
- 不改变模型或 reasoning-effort 默认值。

## 5. 非目标

- 不复制 ZCode 的 Lexical 编辑器、Git 面板、Workspace shell 或专用 Tool renderer。
- 不在本轮引入新的 UI 框架或状态管理依赖。
- 不修改 Cloud Worker、Memory、Policy 或 Durable Event Store。
- 不发布 npm，不部署生产。

## 6. 完成标准

只有在 Zebra package gate 与 Trench Host gate 都通过，并且浏览器证明空态到会话态、
实时执行、终态折叠和用户上滚行为正确后，本任务才可进入 Review。

## 7. 实施结果

- Zebra 新增公开 Turn、work segment 与状态 contract，并由
  `AgentConversationTimeline` 按“用户输入 → 工作过程 → 最终答案 → 资源”渲染。
- `AgentChat` 复用同一个受控 Composer 节点完成空态居中与会话态底部吸附，按
  `scrollKey` 保存阅读位置，并在用户离开实时尾部时提供“查看最新输出”。
- 工作过程运行时展开、成功或取消后折叠、失败或阻塞时保持展开；私有思维链和
  原始工具载荷不进入 UI contract。
- Trench 通过纯投影适配器消费该组件，保留 Markdown、来源、Memory 回执、报告、
  反馈、附件、队列、模型和思考强度等 Host 能力，移除了重复进度渲染。
- 验收时发现并修复移动端隐藏时间线轨道后正文误入 10px 网格列的问题。
- 第二轮像素闭环移除 Zebra 自有的大圆点轨道与 `Live` 标签，按 ZCode 的
  容器规则实现 672px 居中空态、896px/1152px 响应式会话列、56px/40px
  Turn 顶距、20px 内容间距、14px 工作摘要、12×16px/8px 用户气泡和
  16px Composer 圆角。
  第二次源码对照又将完成历史修正为整行 1px 底部分隔和展开后 20px 间距，
  并移除历史摘要图标；工具历史不再误用 reasoning 专属的左侧竖线。运行摘要
  保留轻量扫光，完成态折叠为单行，失败态仍展开。
- 完整聊天壳层补齐 ZCode 的长用户输入 120px 折叠/渐隐、圆形展开按钮、
  图标式“回到最新”、150ms 内容列过渡、Composer hover/focus 反馈，以及由
  Host 提供的低对比品牌水印。Trench 的 1510px Dashboard 上限使其嵌入容器
  正确落在 896px 档；SDK 独立矩阵仍直接覆盖 1152px 档。
- ZCode 参考仓库使用 Apache-2.0；本实现仅对齐公开设计尺寸与行为，未导入其
  React、Tailwind、Zustand、Lexical 或 Tool renderer。

验证证据：SDK `verify` 全绿（27 项测试、package audit、React 18/19 的
Vite/Next 消费、Chromium/WebKit 与 Next hydration）；Zebra `make check` 全绿；
Chromium/WebKit 直接断言上述 computed style；Trench `make check`、生产构建与
生产 Chromium Host 几何验收全绿。npm 发布、Git 推送和生产部署不在本任务范围内。
