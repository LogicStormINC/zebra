# Cloud Agent AG-UI 完整修复与优化方案 / Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已于2026-10-28批准开始实施；后续实现逐卡认领，部署、重跑或生产数据修改不在本次默认授权内。

**Goal:** 把现有事件投影、可靠流、SDK 与组件连成可独立接入、可恢复、可验证的通用 Agent 交互层，Trench 是兼容消费者之一。

**Architecture:** 复用唯一 durable Event Store、现有 Worker／审批／Client Effect 原收据和签名游标；补齐标准语义及消费闭环。标准 AG-UI 事件、Zebra 可靠传输扩展、业务展示三层分别负责自己的合同；不新增执行事实源或通用编排平台。

**Tech Stack:** Python 3.12、现有 ag-ui-protocol/Pydantic、TypeScript client-core/ui-contracts/react/react-charts、HTTP SSE、SQLite/PostgreSQL、Redis 临时输出、既有测试与 Chromium/WebKit 门禁。

日期：2026-10-28。源码基线：cloud-agent `d15fe9f6`；配对 Trench 修复 `6a1a8b8`。均为源码审计基线，不等于当前线上版本。

## Chunk 1：现状、目标与架构边界

### 1. 已核实事实与待核实项

| 项目 | 源码事实 | 对方案的影响 |
| --- | --- | --- |
| 标准事件产出 | 实际构造 14 种：Run 3、Text 3、Tool 4、State/Messages 3、Custom 1 | 依赖库中存在的枚举不算已经实现；14 也不等于端到端覆盖率 |
| 依赖版本 | Python 固定 `ag-ui-protocol==0.1.19` | 不能把当前官网所有行为直接套到旧版本模型上 |
| 协议扩展 | 子 Agent、内容、用量、答案提交、草稿等使用 `CUSTOM zebra.*` | 自定义不等于错误；有标准语义的逐步标准化，必要扩展继续有版本地保留 |
| 实际正文传输 | `stream_v2_wire.canonical_wire` 将正文展开为 `zebra.message_replace`；大记录走 canonical_chunk | “标准 projector 存在”不等于“普通标准客户端可直接消费 v2” |
| SDK | `ConversationStreamReducer.apply` 主要消费自定义 draft/replace；SSE transport 把其他观察交给 Host | 当前 reducer 是窄职责实现，并不是完整 AG-UI reducer；不能直接替换它破坏旧调用方 |
| 组件 | 已有 RunStatus、ActivityGroup、ConversationTimeline、Interrupts、媒体与图表组件 | 优先扩展现有 contracts/组件，避免重写组件库 |
| Trench | API mapper 转成自己的 agent_step/meta/delta；前端另做历史与排序 | 两侧语义可能漂移，需要统一归并结果和 Host 薄适配 |
| 可靠性 | 已有 canonical recovery、原收据、长会话和独立 Cloud 门禁 | 保留这些保障，不因采用标准 HTTP 示例退回断线重执行 |
| 文档冲突 | ADR-015 仍写“不建设 React SDK”，实际有五个 TS 包 | 实施前以新 ADR 明确替代范围，不能按旧文档删掉现有 SDK |

源码依据：

- `packages/agent-integrations/src/agent_integrations/ag_ui/{projection,interrupts,subagent_projection,content_parts}.py`
- `apps/api/src/zebra_agent_api/{ag_ui_stream,stream_v2_wire,stream_v2_reader}.py`
- `sdks/typescript/packages/client-core/src/{conversation_stream,sse_stream,runtime_state}.ts`
- `sdks/typescript/packages/ui-contracts/src/index.ts`、`packages/react/src/components/`（均在 TS workspace 内）
- 配对 Trench：`services/api/src/trench_api/trench_ai_zebra_event_map.py`、`toc-frontend/src/hooks/use-strategy-turn.ts`

尚未证明：线上部署使用哪个 SDK 字节版本、完整官方消费者兼容性、全部 1.0 MUST 行为、生产并发容量及延迟 SLO。方案不会把历史门禁当作这些项目的当前验收。

### 2. 完成后的产品行为

1. 多会话同时运行，每个会话独立显示排队、执行、等待确认、暂停、完成／部分完成／失败／取消。
2. 用户看得清正文、进度说明、工具参数／执行／结果、计划步骤、子 Agent 输出和交付文件。
3. 刷新、切换页面、断线、API/Worker 重启后，已提交结果不丢失、不重复、不乱序；恢复观察不触发执行。
4. 工具与子 Agent 并发时按身份归属，不拼成一段文字，不把一个子任务结束当作整个 Run 结束。
5. 审批、澄清、Frontend Tool 有明确动作和原收据；重复点击或丢失响应不会重复业务操作。
6. 新 Host 不复制 Trench mapper／状态机即可获得基础交互；业务权限、数据查询和业务动作仍属于 Host。
7. 标准客户端可读到标准的 canonical 文本与工具；Zebra 客户端额外使用草稿、可靠续读和受管 Artifact。

### 3. 推荐架构与不变量

```text
Durable Event Store / Worker / Policy / Receipt
                    ↓ 确定性公开投影、授权与发布门禁
          标准 AG-UI 语义 + 有版本的 Zebra 扩展
                    ↓ HTTP / SSE（按客户端协商传输配置）
        SDK 解码 → 兼容转换 → 校验 → 归并 → selectors
                    ↓
     现有 React 组件 / CopilotKit adapter / 其他 Host UI
                    ↑
           Host BFF：身份、业务数据、业务动作
```

- 保留 canonical Event Store 为执行事实源；UI store 只是可丢弃、可重建的投影。
- 复用现有签名 authority、namespace、Task/Run binding、租约及审批校验，不从浏览器状态恢复执行权限。
- 不新增 WebSocket、消息总线、第二套任务表、通用组件注册平台或独立 UI 服务。
- 默认继续现有 TS SDK 和组件；CopilotKit 作为标准互操作消费者及可选接入方式，不作为替换全部 UI 的前置。
- 停止读流、暂停执行、取消任务、重试观察、重新执行是不同动作；不能复用一个含糊 retry 按钮。
- 旧 v1/v2、旧 cursor、旧 archive tag、历史 Run、旧包消费者保持原有合同。新合同通过显式配置启用。

### 4. 两种传输配置；不要混淆标准与扩展

**标准互操作配置：** 输出完整标准事件对象；TEXT_MESSAGE_CONTENT 保持标准正文。可通过现有准入 use case 接上标准 POST + SSE facade，仍经 Host BFF 授权。标准客户端不必理解 Zebra draft/replace/canonical_chunk 才能阅读 canonical 结果。

**Zebra 可靠配置：** 保留独立准入与只读 GET 观察、签名 cursor、分帧 ACK、draft/reset/full recovery。它是扩展传输，不冒称标准 HTTP 绑定本身具有续读能力。SDK 必须先组装可靠传输帧，再进入同一语义处理管线。

官方 1.0 HTTP SSE 绑定不提供 Last-Event-ID 续读；不能按其“断线后新 Run”示例自动重发本平台业务请求。[标准 HTTP SSE](https://docs.ag-ui.com/spec/1.0/basic/transports/http-sse)

新配置的精确名称、发现路径和兼容 header 在 G0 冻结，复用已有 bootstrap/discovery；不在方案中虚构已存在的端点。能力声明用于 UI 提示，不授予权限，不作为拒收合法事件的理由。[Capabilities](https://docs.ag-ui.com/spec/1.0/basic/capabilities)

版本隔离必须先于语义修改：G2V 先让投影选择、checkpoint key、完整恢复和新 cursor 绑定显式 profile；旧 cursor 仍路由旧投影，不套新 frame_index。每个旧事件流/旧游标/旧包组合的 golden 字节与行为保持；不得仅给新 projector 加版本标签却继续复用旧 checkpoint 载荷。

## Chunk 2：协议、状态、组件和可靠性改造

### 5. 完整事件范围与支持口径

官网 SDK enum 与 convenience chunk 章节的展示口径不同。以下列出 31 个候选标准事件名作为核对目录；G0 必须以冻结的官方 schema、版本／commit 和 SHA-256 得出最终集合。不得用目录行数宣布 1.0 全兼容。

| 事件族 | 事件名 | 当前服务端产出 | 目标 |
| --- | --- | --- | --- |
| Run/Step，5 | RUN_STARTED、RUN_FINISHED、RUN_ERROR；STEP_STARTED、STEP_FINISHED | 前 3 种 | 补真实步骤生命周期；规范终态及关闭顺序 |
| Text，4 | TEXT_MESSAGE_START、TEXT_MESSAGE_CONTENT、TEXT_MESSAGE_END、TEXT_MESSAGE_CHUNK | 前 3 种 | 生产端可继续显式三段；消费端展开 chunk |
| Tool，5 | TOOL_CALL_START、TOOL_CALL_ARGS、TOOL_CALL_END、TOOL_CALL_RESULT、TOOL_CALL_CHUNK | 前 4 种 | 修正参数结束与执行结束的区别；消费端支持 chunk |
| State，3 | STATE_SNAPSHOT、STATE_DELTA、MESSAGES_SNAPSHOT | 3 种 | 验证全量替换、原子 patch、完整历史恢复语义 |
| Activity，2 | ACTIVITY_SNAPSHOT、ACTIVITY_DELTA | 无 | 计划／查询／工具执行进度等可恢复的结构化活动 |
| Reasoning，7 | REASONING_START、REASONING_MESSAGE_START、REASONING_MESSAGE_CONTENT、REASONING_MESSAGE_END、REASONING_MESSAGE_CHUNK、REASONING_END、REASONING_ENCRYPTED_VALUE | 无 | 消费与安全降级；只有受支持的公开摘要才允许发出可见事件 |
| Subagent，3 | SUBAGENT_STARTED、SUBAGENT_FINISHED、SUBAGENT_ERROR | 以 zebra.subagent 扩展替代 | 标准生命周期与消息／工具／活动的来源归属 |
| Special，2 | RAW、CUSTOM | CUSTOM | CUSTOM 类型化及版本化；RAW 仅经授权脱敏的来源使用，不透传内部事件 |

每种事件分别记录：schema 接受、生产映射、增量归并、UI 展示／明确降级、快照恢复、实际消费者验证。生产端不为“数量齐全”伪造 reasoning/subagent/RAW；不需要的 shorthand 不必重复发出。[官方事件参考](https://docs.ag-ui.com/sdk/js/core/events)

### 6. 优先修正事件语义

**工具调用：** 当前 ToolCallEnd 与工具执行完成一起投影，Trench 在 START 就显示“正在执行”。应使 END 表达参数传输完毕，执行阶段由已存在的真实执行事实／Activity 表达；结果只来自持久执行结果。先审计所有调用方，避免提议、等待审批、排队都被算作 executing。覆盖参数不完整、失败、超时、取消、并行调用、审批后晚到结果。[Tool calls](https://docs.ag-ui.com/spec/1.0/events/tool-calls)

**步骤与活动：** 从真实计划／工具／验证／交付事件构建稳定 activity/message ID 和 step；没有持久事实的百分比不编造。步骤按模型允许的顺序嵌套；任意并发任务由 Activity/Subagent 表达。计划变更是状态更新，不默认表示旧步骤成功。

**Run 终态：** completed、partial、blocked、cancelled、failed 与观察连接状态分别保存。RUN_FINISHED 的协议成功不直接等价于“业务交付全部完成”；partial/blocked 使用有版本的交付 assessment 与动作解释，只有真实可回答的请求才形成 interrupt。新增 profile 才采用冻结 schema 的 cancelled 等 outcome；不悄悄改变旧生产合同。

**公开输出：** 区分 commentary、最终正文、工具参数、工具结果、公开 reasoning 摘要。隐藏内部工具占位语句，不能把“Tool calls proposed.”当正文；只有真实提交事实可标记 committed。公开 commentary 和 reasoning 摘要也不是同一种内容。

**用量：** 保留现有精确计费事实；标准终态 usage 做投影，区分累计和每个协议 Run 的用量，不跨重连／重放重复累加；未上报保持 unknown，不能写成 0。

### 7. 身份、顺序与跨 Run 连续性

- 明确 Host conversation、Task/thread、内部 execution Run、Segment、协议 runId、messageId、toolCallId、activityId、subagentRunId 各自用途。
- 顶层隔离采用 namespace/授权域 + threadId；每次观察绑定 run/profile/revision，禁止全局单一 activeRun/busy/AbortController。
- 当前内部同一 Run 的审批续接，与标准 profile 的“interrupt 关闭后以新协议 Run 继续”分别建模。若需不同公共 runId，复用 durable continuation anchor 确定性关联，不能创建新 Worker 执行或把新 ID 当业务授权。
- 协议 run 与内部 Run 映射及 usage 切片必须先过合同审查；绑定缺失时拒绝启用新 profile，不猜测或写回历史。
- 子 Agent ID 表示一次调用而非 agent 定义；父子／工具归属和审批等待在恢复后仍成立。跨授权子任务先校验公开可见性，不能把 child Task ID 当作可直接访问的资源。
- 不比较 Task sequence、Session sequence、Host relay sequence 或跨流时间戳大小。持久 cursor 决定原流顺序；归并身份负责去重；UI 接收序仅作展示排序。
- 无合法标准事件 ID 时不要拿 payload hash 去掉内容恰好相同的两个合法 delta。Zebra 回放使用已有持久坐标，普通流遵守标准顺序。
- 重新投影的输出 ID／边界必须确定；旧有符号游标绑定旧 profile。映射算法变更应绑定投影版本，不能让旧 frame_index 指向新的帧。

子 Agent 事件是归属协议，不是新增编排器；State attribution 不创建子 Agent 私有 state document。[Subagents](https://docs.ag-ui.com/concepts/subagents)

### 8. SDK 处理管线

1. 复用现有 SSE 解码、边界预算、UTF-8、abort 和回连；补标准多行 data、半记录、CRLF、EOF 截断测试。
2. 可靠配置先恢复 canonical_chunk／签名 cursor 及 ACK；旧 ConversationStreamReducer 保持旧接口。
3. 兼容边界把旧扩展转换到内部统一表示；依次进行标准化 middleware、输入处理、chunk 展开、生命周期校验、状态归并。
4. 未知事件／未知字段与已知字段格式错误分别处理；前者按冻结规范处理并限量诊断，后者报协议错误，不盲重连同一毒帧。安全授权字段仍严格校验。
5. snapshot 按合同替换其范围；delta 按 RFC 6902 在副本上原子执行，失败不留下半个状态。支持必要 op 和 Pointer 转义，阻止危险原型路径，不做随意对象深合并。
6. 明确缺失基底、缺帧、重复帧冲突和过期 snapshot 的行为：Zebra 请求只读 recovery；普通标准消费不能凭空假定有恢复 API。
7. 输出复用 AgentMessage/AgentWorkSegment/AgentRunState；扩展计划、子树、interrupt／tool 状态所需最少字段，公开 discriminated union，避免 `any` 或通用 `Record` 承包全部合同。
8. selector 按 thread/run/实体订阅；不每个 token 复制全部历史。切换会话清理的只是观察订阅，不修改后台任务状态。

优先复用官方 JS core/client 的类型、chunk 与行为处理，先做最小包体／兼容性试验；仅当现有依赖无法满足且官方包能减少自维护代码时引入固定版本依赖。不手抄另一套完整 AG-UI，也不为避免一个依赖写有缺口的 JSON Patch 实现。

schema 严格测试与运行时前向兼容分开；未知元数据可按规范保留，闭合对象的未知成员不能无条件送进应用。[Processing model](https://docs.ag-ui.com/spec/1.0/basic/processing)

### 9. 客户端状态与动作

| 维度 | 状态／规则 |
| --- | --- |
| 执行事实 | queued、running、waiting_for_user、paused、terminal + outcome；由服务端事实驱动 |
| 观察连接 | connecting、live、recovering、disconnected、permission_denied；不覆盖执行事实 |
| 本地提交 | idle、submitting、unknown、confirmed、rejected；unknown 只对账原操作 |
| 工具 | preparing arguments、proposed、waiting approval、executing、succeeded/failed/cancelled；来自各自事实 |
| 子 Agent | running、waiting、completed、failed、cancelled；父终止不能伪造 child 成功 |
| 交付 | unverified、partial、ready、blocked；不能仅凭正文存在或收到 FINISHED 判 ready |

动作复用现有 Client Session/Controller 和 Receipt 流程；普通前端工具只能提交已授权、版本绑定的待处理效果。历史恢复不执行工具；unknown 不换 UUID 重发，不自动接管 Controller。

审批／澄清：展示服务端 schema、原因、影响、过期、结果；支持拒绝、取消和确定范围内的修改。responseSchema 声明可编辑不代表后端现有合同允许；修改参数须重新校验 policy、绑定及确认原收据，未实现时不展示编辑入口。多 interrupt、三次连续审批、过期／撤权、丢响应和后来新 Turn 都要覆盖。

新 profile 的 resume 形状按冻结 schema，既有审批 API 通过适配层继续使用原 durable decision；浏览器“已批准”不能作为授权凭据。[Interrupt/resume](https://docs.ag-ui.com/spec/1.0/basic/patterns/interrupt-resume)

标准多审批必须完整覆盖最近一次 interrupted 协议 Run 的全部 interrupt：每项明确作答或放弃（wire枚举以G0冻结schema为准）；过期项不得作答，须明确放弃。UI 可逐项收集本地选择，但完整性未满足时不得先发起下一 Run；消费者发送前与服务端 durable 审批边界均检查。缺项、重复项、旧Run项、伪造项、过期项及撤权都不能执行未获批准的动作，既有单条审批API不被悄悄改成新的批量语义。

**标准 Frontend Tool 适配是单独合同：** 当前 Client Effect 只输出 STATE_DELTA，不等于标准工具往返。新 profile 中，真实且授权的前端调用生成标准 TOOL_CALL_START/ARGS/END；协议 Run 以 success 关闭并留下未回答调用，应用执行或拒绝后，下一输入 messages 必须补齐每个 toolCallId 的工具结果。它不是 human interrupt，服务端不得代应用伪造 TOOL_CALL_RESULT。新增调用绑定复用原 Client Effect ID/Session/Controller/修订/权限，只有原确认结果或明确拒绝收据可转成下一输入；任意浏览器 tool message 不能绕过收据。unknown 先对账原效果，不补造结果，不重执行。旧效果路径保持；若当前适配不能满足完整往返，则明确不声明标准 frontend-tools 能力。验收必须包括真实标准消费者从调用到结果回传、继续执行的全过程。

### 10. UI 与生成式展示

- 扩展现有 AgentConversationTimeline/ActivityGroup：正文和执行说明有区别，工具参数可展开，结果带状态与时长，计划步骤清晰可查。
- 现有 RunStatus 区分后台仍在执行、观察断开、等待人、暂停及已结束；每种状态只给实际支持的动作。
- 子 Agent 使用可折叠分组、来源标记和父子关系；单个失败、取消和等待不隐藏其他结果；根级结果汇总保留可追溯引用。
- 保留现有 image/video/external_video/chart/file 五类内容合同，复用 Artifact 预览／下载／权限刷新；不拿文本事件数量代替多模态能力。
- 表格、结构化结果、引用与证据链接先复用既有 renderer，确有缺口再增补类型。任意 HTML/JS、任意远程 iframe 不是本方案默认能力。
- 长输出分页与窗口化保持可访问；实时追加不抢用户阅读位置、不重挂载媒体；键盘、焦点、aria-live 限流、减少动画设置纳入浏览器验收。
- schema 驱动表单限于受支持的表单字段与校验；选择、确认、编辑遵循现有业务动作，不能借“生成 UI”直接执行权限外命令。
- 未知类型显示明确的安全 fallback；受限、不支持、加载失败和空结果区分，不能静默丢掉关键审批或文件交付。

### 10.1 用户输入、页面上下文和双向状态

- 覆盖 RunAgentInput 的 thread/run、messages、state、tools、context 等冻结字段；BFF 验证登录、租户归属和请求大小，浏览器提供的历史或 state 不能覆盖服务端执行事实。
- 附件／多模态输入按已安装客户端及模型真实支持项启用；文件大小、类型、上传失败、取消、权限过期和跨模型不支持分别有反馈。不以支持图像输出推断支持图像／音频输入。
- 复用现有 Readable/Surface/context 命令：页面选择、当前资源版本、空状态清除、组件卸载和迟到响应都校验精确会话及修订；输入快照须在明确提交时捕获，后台 React rerender 不自动生成新业务意图。
- Agent 更新受支持的共享 state，Host 业务写入仍通过已注册工具及审批／收据；JSON Patch 不能直接等同于执行任意业务数据库更新。
- 同一输入的 optimistic user message、服务端确认与历史加载按原请求身份合并，失败保留可操作状态；提交 unknown 只查原收据，不发新 Run。新建会话首条输入和已有会话补充输入分别覆盖。
- 复制／反馈／建议／报告属于 Host 功能，移植 SDK 时保留既有行为；“重新执行”明确创建新意图，“继续”必须符合原暂停合同，两者不由网络超时自动触发。

### 11. Trench 迁移

第一步将同一份真实 Cloud wire 同时喂给旧 mapper 和新 SDK，离线比较正文 hash、顺序、工具与 child 身份、状态、文件、审批及交付 assessment；这个双读只计算展示投影，不执行两遍效果。

第二步以显式配置让新 SDK 接管实时和历史的同一归并语义；Trench 保留业务身份／数据权限、来源／推荐／反馈／报告及 Artifact URL resolver。已有业务历史持久化暂留，不新增一套更复杂的写入；待每条功能等价后按职责删除重复 mapper 分支。

第三步验证多会话列表与详情来自一致的 durable 状态；多标签页只复用现有控制权／收据协议，不能自行新建全局锁。保持原会话链接、旧历史可读和每个 Host 自己的业务 ID。

退出条件：新接入最小 Host 与 Trench 共用同一 runtime-independent SDK；Cloud 默认门禁不导入 Trench 仓库。不能以“Trench UI 显示正常”代替标准消费者验收。

### 12. 性能与可观测性

- 先保留现有首帧、draft 合并和增量归并优化；分别测模型等待、durable commit、投影、网络、SDK、render，不能把模型耗时算成 UI 优化空间。
- 记录分层指标：known-invalid/unknown 事件、恢复次数与原因、cursor conflict、projection lag、队列时延、端到端 frame-to-paint、活动更新延迟、累计内存和挂载节点数。
- trace 关联 Task/协议 Run/内部 Run/工具/子 Agent 的不透明诊断 ID；公共错误不泄露 JWT、提示词、私有工具结果和内部堆栈。
- 测量 1/10/50 并发会话，分别区分可见订阅和后台摘要；前端不能通过每会话短周期全历史轮询获得状态。先复用既有聚合查询，证据表明瓶颈后再设计摘要订阅。
- 背压时可合并可视化临时进度，不能丢 canonical、interrupt、工具结果或终态；超预算返回可解释状态并能恢复。
- 建议初始 UI 门槛：参考机器 10k 事件归并无增长到 O(N²) 的迹象；10/50会话时内存受配置上限约束；100次 live 更新阅读锚点偏移≤2px、媒体不重挂载。具体 p95 帧渲染目标由 G0 建立基线后冻结，暂不宣称生产 SLA。

### 13. 扩展、版本和包交付

按用途登记现有 CUSTOM：可靠传输、canonical 提交／交付 assessment、Artifact 展示、coverage、用量和业务摘要。每个公开扩展要有版本、schema、producer/consumer、丢失影响、重放与降级规则。

有标准对应的 subagent/activity/usage 渐迁；draft/reset/可靠分片、发布门禁、受管 Artifact 不因“标准化”移除。一个逻辑输出不能同时经标准和旧 CUSTOM 路径被插入两次；按协商选择视图或在适配边界按持久身份合一。

- 新 schema profile 与 transport v2 是两条独立版本轴；capabilities 不等于 authority。
- 先固定源码／依赖／schema／包内容 hash，再 pack；改变公开接口或字节内容不能继续覆盖同名 0.1.0 tarball。
- 按五包依赖顺序构建并产出新版本 tarball，受影响包及依赖引用一起对齐。Trench vendor、package.json、lockfile、安装后解析到的包哈希同时验证。
- 跑现有 package-audit、React18/19、Vite/Next SSR/RSC、Chromium/WebKit；公开 exports／types 与 CJS/ESM 一致，不含 workspace 路径、测试或凭据。
- GitHub 交付包括源码、版本、lockfile、消费者实际 tgz、清单和门禁结果。当前用户选择不发布 npm registry，未来发布必须单独获授权。
- 默认开发目标 cloud-agent；cloud-agent-trench 仅接收明确认定的兼容修复。重大新合同不整批灌入旧基线；需同步时说明范围并保留 archive tag。

## Chunk 3：实施任务、验收与发布

### 14. 实施分片与 Owned paths

以下是 proposed 卡片；依赖按所选 integration target 验证并在 docs/AGENT_TASKS.md 认领后才可动代码。每卡一个 owner／分支／工作树，跨文件边界先登记，不把整个 SDK 或整个 API 当临时共享所有权。

| 卡片 | 依赖 | 最小交付与主要文件／测试边界 |
| --- | --- | --- |
| G0 合同冻结 | 无 | 新 ADR 与官方 schema/版本清单；更新 ADR-015 的失效部分、AGUI 设计、PROGRESS/任务表；`tests/conformance/agui_contract/` 目录。区分 schema 合法与行为符合；纯文档/fixture，无执行变更 |
| G1 标准消费核心 | G0 | 复用 client-core，新增 `src/agui_events.ts`（兼容/边界）与 `src/agui_reducer.ts`（官方归并适配或最小纯归并），对应 `tests/agui-events.test.ts`、`tests/agui-reducer.test.ts`；同时拥有 `sdks/typescript/package.json` 的test入口更新。标准 chunk/patch/隔离/毒帧/完整resume，不改旧 reducer 调用行为 |
| G2V 投影版本隔离 | G0 | `ag_ui/{contracts,task_stream,projection_state,checkpoint_keys}.py`及checkpoint选择的准确调用点、API profile选择/cursor绑定；新旧projection golden/cursor/checkpoint tests。认领前列清全部路径，涉及Port/storage改动另拆卡；旧profile字节与旧包兼容后才解锁G2 |
| G2 公开投影语义 | G2V | `ag_ui/projection.py`、`projection_state.py`、新 `activity_projection.py`、现有 `subagent_projection.py`、`interrupts.py` 及对应 integrations tests；只在新profile修正工具 END、活动、步骤、子 Agent、终态；projection.py 已456行，添加前按责任拆分以保持500硬限 |
| G3 标准与可靠传输 | G1/G2 | `apps/api/.../{ag_ui_stream,stream_v2_wire,stream_v2_reader}.py`、`client-core/src/sse_stream.ts`、标准 facade 的现有 route composition；新增 wire/profile/cursor tests。若需要 continuation 映射／ports／storage，先单独登记子卡，不能越权改 core |
| G4 React 交互闭环 | G1/G2 | ui-contracts/index、现有 `agent-conversation-timeline`、`agent-activity-group`、`agent-run-status`、`agent-interrupts` 及对应 React tests；按实体局部订阅，新字段可选兼容；未冻结的表单/Reasoning能力不提前宣称 |
| G5 双向动作与多会话 | G3/G4 | client-core `src/{runtime_state,command_recovery,receipt_transport,sse_stream}.ts`、react `src/hitl/index.ts`/现有effects消费调用点、API `ag_ui_{command,command_receipts,client_state}.py`/`client_effect_receipts.py`及integrations `client_effect_projection.py`；标准Frontend Tool完整往返、全量resume覆盖、多会话、unknown/撤权检查。增补调用点须先登记；不改旧业务授权语义 |
| G6 标准消费者与包 | G3/G4/G5 | `sdks/typescript/scripts/{package-audit,react-browser-matrix,react-consumer-matrix}.mjs`、新增 `agui-consumer-matrix.mjs` 及各包 package.json/lock；真实官方客户端／CopilotKit adapter、Reasoning 安全降级和 optional能力；不新造 frontend runtime |
| T1 Trench 消费迁移 | G6 | 配对仓库新任务：现有 zebra mapper/dispatcher、use-strategy-turn/observation/history、chat-api、workspace/sidebar、vendor/manifests/tests；先离线等价再显式切换，保持业务功能 |
| G7 联合与性能收口 | G6/T1 | `tests/conformance/agui_long_session/` 增量扩展及独立新合同门禁、browser fixtures、`docs/evidence/agui-interaction/`、runbook；同时验旧消费者和新 profile，不改模型/质量预算制造通过 |

每张卡都包含 red → 最小修改 → targeted green → 该分片已就绪的适用 gate → 更新文档／清单 → 独立提交。G1与G2V/G2可概念上独立，但不在同一接口未冻结时并行修改共享 contracts；实现次序默认串行以减少返工。

### 15. 每个实现分片的可执行检查方法

- [ ] 从可重复缺陷写最小失败检查；先运行看到具体失败，不用新增测试框架。
- [ ] 找到所有 caller／sibling；确认在共享边界修复，记录必要 owned-path 扩展。
- [ ] 最小实现，不将 refactor、性能指标平台或新 UI 主题混入合同修复。
- [ ] 原检查变绿，执行下列该分片适用命令，并保存原始输出、commit 和环境版本。
- [ ] 检查当前与旧 profile、原收据/hash、历史 cursor、未提交工作和资源保留。
- [ ] 独立提交；仅在指定 integration target 满足依赖后解锁下卡。

Python 使用仓库既有环境；测试文件名以实际认领落地为准，下面新路径是本计划拟新增的 runnable gate：

```sh
uv run pytest tests/agent_integrations/test_ag_ui_projection.py tests/agent_integrations/test_ag_ui_turn_projection.py -q
uv run pytest tests/api/test_agui_stream_routes.py tests/api/test_agui_command_routes.py -q
pnpm --dir sdks/typescript check
pnpm --dir sdks/typescript exec tsx --test packages/client-core/tests/agui-events.test.ts packages/client-core/tests/agui-reducer.test.ts
pnpm --dir sdks/typescript test
pnpm --dir sdks/typescript verify
ZEBRA_NODE_BIN=/absolute/path/to/supported/node tests/conformance/agui_long_session/run.sh
make test
make check
```

G0–G3 新增 `tests/conformance/agui_contract/run.sh` 后，要求一条命令执行：官方 schema/golden、实际 Python projector→HTTP→真实 SDK→状态快照。官方消费者/CopilotKit差分在G6加入并成为其后发布门禁；不让G3依赖尚未解锁的G6。新测试路径创建前不得写成现有能力；条件跳过不能计入该核心 gate 的通过。SDK现有test命令显式列举文件，G1必须同步接入新增文件并核对实际执行数，不能只依靠文件落盘自动发现。

Trench T1 在其自身环境执行 focused API、完整 toc-frontend test/lint/build 和本仓库既有 make check；新包必须从 tgz 安装，不能用源码软链接假装消费者安装验收。历史测试缺环境时明确记录，不能据此宣称完整产品通过。

### 16. 验收矩阵

| 场景 | 必须证明 |
| --- | --- |
| 标准事件目录 | 冻结集合每个事件有 schema/消费/fallback 测试；按能力声明的生产事件有真实投影事实；不能只测手写 JSON |
| 顺序与身份 | text/tool/chunk 开关、同名工具并行、entity ID 冲突、合法重复delta、重复帧/冲突帧、跨 thread/run/namespace 不污染 |
| 工具交互 | 参数结束不等于执行结束；审批前不显示已执行；成功/错误/取消/结果晚到；工具端与前端结果不被伪造 |
| State/Activity | snapshot替换/缺失字段/role规则、全部必要Patch op/转义/原子失败/越界；活动首次缺基底、并发修改、恢复一致 |
| 多会话 | 1/3/12确定性状态检查；10/50并发场景；切换/刷新/后台标签页/乱序请求/部分结束/权限变化，互不影响 |
| 子 Agent | 并行、嵌套、未宣布但合法归属、单子失败、等待审批后继续、父终止；消息归属与共享state语义正确 |
| Reasoning | 公开摘要独立呈现；无摘要不合成；加密值不解密、不当正文；不支持模型给明确能力降级 |
| 审批与效果 | 批准/拒绝/取消/过期/撤权/重复/未知；多interrupt缺项不得发送、逐项暂存后完整resume、过期放弃、旧Run项拒绝；三次连续审批后进程重建；历史只读零副作用 |
| 标准Frontend Tool | 官方consumer收到未回答调用/协议成功关闭→应用执行或拒绝→原收据确认→下一输入全部tool结果→继续；伪造tool message、历史回放、unknown和丢ACK均不重复执行 |
| 可靠恢复 | SSE半条记录、UTF-8分割、尾部截断、断线、Redis故障、PG不可用、API/Worker重启；恢复不自动POST/不新执行 |
| 冷启动 | 仅suffix cursor不能重建时走完整canonical恢复；最终正文/交付/终态一致；旧scalar序号不与relay比较 |
| 长会话 | 1000 Turn/2000消息及既有1,020,000字节正文路径；分页无漏重、hash一致、内存受限；不以解除预算获得通过 |
| 标准互操作 | 实际官方JS consumer及CopilotKit最小接入读取真实Cloud标准profile；独立Host不引用Trench业务代码 |
| 多模态/界面 | 同一Artifact权限、预览/HEAD/Range/下载、图表降级、来源引用、持续播放、滚动/键盘/焦点/aria-live |
| 包与旧消费者 | React18/19、CJS/ESM、SSR/RSC、Chromium/WebKit；旧v1/v2、旧tgz和Trench兼容，版本/包字节可追踪 |

确定性/录制fixture、真实网络/数据库、真实浏览器、真实模型/业务工具分四类证据；逐类报告。需要真正模型执行的最后验收必须使用专用测试会话，不能重跑用户原 Run；生产工具外部写入单独确认。

### 17. 交付顺序与投入估算

| 阶段 | 交付 | 退出条件 | 初步工程量 |
| --- | --- | --- | --- |
| A：合同与基线 | G0 | 版本/schema/profile及Run映射约束冻结、ADR冲突解决、旧基线可复现；具体映射算法由G2V代码前固定 | 2–3 工程日 |
| B：基础闭环 | G1/G2/G3 | 标准正文/工具/状态/Activity和可靠恢复由统一管线消费；旧门禁不退化 | 7–11 工程日 |
| C：完整交互 | G4/G5/G6 | 子Agent、审批/Frontend Tool、多会话、Reasoning安全处理、标准消费者与新包通过 | 6–10 工程日 |
| D：消费者与收口 | T1/G7 | Trench等价迁移、双浏览器、旧包回归、性能与可回滚交付 | 5–8 工程日 |

约20–32工程日是审计后的初估，不是上线承诺。是否能直接复用官方JS reducer、现有 durable事实是否含足够子Agent归属、标准profile Run映射和真实包差异是主要变量；A完成后重新估算，不为赶日期跳过门禁。

### 18. 发布、回滚与完成定义

1. 只读盘点实际部署版本、schema ledger、镜像、SDK解析路径和消费者；不把当前源码当线上事实。
2. 产出带SHA的源码/协议/schema/五包/consumer锁文件/兼容表及验证证据；固定 profile 默认行为。
3. 离线新旧投影比对及隔离E2E通过后，授权环境中先启服务端兼容实现，再安装新包，最后按Host/用户范围开启新profile。
4. 活跃 Run 默认保持准入时的profile；不在流中切换投影算法／游标解释；后续只读恢复也使用原合同。
5. 回滚首先停新profile准入和UI切换，保留解码旧新数据能力；回到旧UI不覆盖新canonical状态。不做反向数据库迁移或批量重写历史。
6. 明确回滚阈值：跨会话污染、重复副作用、授权错误、正文hash不一致立即停新profile；错误率/恢复循环/延迟阈值由A建立基线后冻结。
7. 首次发布不主动做生产历史回填；有必要时另设可重跑、可审计、授权范围明确的迁移卡。

完成必须同时满足：声明能力逐项有证据；协议与状态语义一致；普通Host接入成功；Trench核心功能不丢；旧包/原Run可恢复；包版本可追踪；观察恢复零执行副作用；完整适用门禁通过；运维回滚可操作。实际部署和真实模型验收另有单独完成记录，不能由源码测试替代。

### 19. 方案评审需要冻结的决定

- 推荐采用现有SDK为主、标准消费者可选互操作的路线；不整体改为CopilotKit，不重建Event Store。
- 推荐标准语义与可靠传输双配置；新profile可与旧v2并存，审批与内部Run同一性不被改变。
- G0冻结官方schema、profile和兼容边界；JS复用在G1最小实际消费试验后选定，公共runId算法/真实discovery承载点在G2V代码前固定，具体性能阈值在G7优化前以匹配基线冻结。各待决项是对应卡的前置门禁，不能当成已完成。
- 支持目录应区分“可以消费”和“真实可生产”；实时语音、任意代码生成UI、全新协作编辑、Protobuf/WebSocket、新计费平台不属于本次默认范围。
- 本方案交付时未实施、未推送、未部署；所有实现卡为建议，当前只认领文档卡。

### 20. 参考与证据边界

- [AG-UI 事件](https://docs.ag-ui.com/sdk/js/core/events)、[schema定义与获取](https://docs.ag-ui.com/spec/1.0/schema-files)：目录/模型约束；官网页面间存在版本展示差异，必须冻结机器schema。
- [生命周期](https://docs.ag-ui.com/spec/1.0/events/lifecycle)、[工具](https://docs.ag-ui.com/spec/1.0/events/tool-calls)：工具END、取消、usage与关闭语义。
- [处理模型](https://docs.ag-ui.com/spec/1.0/basic/processing)、[标准传输](https://docs.ag-ui.com/spec/1.0/basic/transports/http-sse)：未知/已知错误、管线顺序及标准不提供续读。
- [中断](https://docs.ag-ui.com/spec/1.0/basic/patterns/interrupt-resume)、[子Agent](https://docs.ag-ui.com/concepts/subagents)、[能力](https://docs.ag-ui.com/spec/1.0/basic/capabilities)：连续性和声明边界。
- 既有仓库文档：`docs/AGUI_CLOUD_INTEGRATION_2026-10-28.md`、`docs/AGUI_LONG_SESSION_2026-10-28.md`、`docs/CLOUD_STREAM_SDK_PERFORMANCE.md`。历史测试结果未在本轮重跑，不作为新方案已通过的证据。


方案审查：独立 reviewer 首轮指出5项实质问题（旧投影前置隔离、标准Frontend Tool往返、完整resume覆盖、门禁依赖、新测试入口），均已修订；复审通过。该结论仅针对方案，不代表实现、性能或部署验收。


实施进度（2026-10-28）：

- [x] G0：冻结官方schema/31事件目录、真实旧14类wire/cursor golden及ADR边界；7+36+174检查和make check通过；独立审查见任务表。
- [x] G1：官方1.0.3消费核心；25新检查/完整SDK199、check/package及两阶段审查通过。尚未启用新profile；128 pending guard和观察状态不代表生产执行/吞吐验收。
- [x] G2V/G2：版本隔离与公开投影语义；592fc95b 已审查并推送 cloud-agent，默认未启用。
- [x] G3A/G3B：有界入口、实际准入后HTTP/可靠GET、原生端到端与独立审查通过；默认未启用。
- [x] G4：共享展示、局部订阅、完整本地响应草稿；最终SDK273、SPEC29/QUALITY53通过，原生动作仍属G5。
- [ ] G5–G7/T1：双向动作、包、Trench及联合门禁。

G0审查后的顺序澄清：原估算把JS复用、Run映射算法及性能阈值都归到G0。实际需消费试验、版本隔离代码边界及可重复性能样本才能决定，故分别移至G1/G2V/G7的实现前门禁。G0交付为可运行的合同/兼容基线，不解锁依赖这些决定的新生产profile；无新增架构权限。

G3实施分片澄清（2026-10-29）：先交付G3A有界SDK入口及原生精确坐标只读查询，
再交付G3B实际准入／HTTP／可靠桥接。两卡串行、独立审查；G3A不代表标准HTTP
互操作已完成，不解锁新profile启用。原G3整体验收条件保持不变。


G5实施分片澄清（2026-10-29）：G5A先完成显式版本隔离的原生完整响应及
前端工具原收据往返；G5B再完成现有React Provider/HITL/runtime的会话切换、
迟到回调及执行端权威检查。两卡串行独立审查；G5A不代表G5整体完成，亦不启用
生产profile。具体原生合同先写入独立focused文档，再编辑实现；G0的旧合同隔离、
原收据及无额外执行不变量保持。
