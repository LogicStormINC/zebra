# Cloud Agent 首正文延迟优化实施方案

> 执行方式：按任务串行实施；使用 writing-plans 制定方案、executing-plans 推进。每阶段有独立验收，不为小测试修复重复完整评审。

**Goal:** 降低 Cloud Agent 点击发送到真实正文显示的延迟，优先消除平台等待，同时保留执行、权限、恢复和输出隐私语义。

**Architecture:** 先串联已有计时和真实草稿链路，再把云端沙箱创建推迟到首个确实需要沙箱的操作。模型决定回答还是调用工具；平台只按工具和上下文依赖准备资源。预热先使用现有镜像与节点能力，通用运行容器池作为独立、有条件的后续设计。

**Tech Stack:** Python Worker/API、PostgreSQL、Redis transient_v2、Docker/gVisor、TypeScript client-core、React 及五个官方 npm 包。复用现有 Ports、计时、事件、租约和工具网关，不新增依赖。

日期：2026-10-15。源码基线：cloud-agent-trench / 74c703a9。
状态：完整方案；本次仅文档，不代表生产实现、模型验证或启用已经完成。

## 1. 范围与事实边界

产品是独立 Cloud Agent，Trench 只是一个消费端。生产修改必须落在公共 Worker/API/runtime/integrations/SDK；消费端仅进行配置与验收。

已完成：Docker CLI 代理路径、DNS 子进程轻量解析、TLS bridge TCP_NODELAY；SDK 增量 UTF-8 计数、消息列表历史行 memo、v2 去重启动读取。

已有证据：

| 测量 | 结果 | 不能据此推断 |
| --- | --- | --- |
| 真实同类请求模型前等待 | 历史11.138s → 最新平均4.629s | 不是同期A/B，不是模型首token或p95 |
| 最新真实页面首正文 | 9.426s / 12.133s | 极短正式正文，没有证明长答案草稿时延 |
| 隔离沙箱生命周期配对 | provision平均1.668s → 1.292s | 不等于所有业务请求沙箱耗时 |
| SDK512帧回放 | 257.137ms → 10.756ms | 不是首字改善96% |
| built SDK浏览器草稿回放 | firstbody DOM7.50ms | 不含真实网络、Provider与Worker |

一个实际请求分解：发送→Run1.00s；Run→首模型事件4.469s；模型调用2.250s；响应→Host完成1.454s；完成→DOM0.254s；总9.426s。模型事件不是HTTP发出，模型调用时长不是TTFT。

原始证据：.artifacts/startup-exec-20261015/REPORT.md、startup-dns-20261015/REPORT.md、stream-sdk-perf-20261015/REPORT.md。不得把不同测量口径叠加为总收益。

## 2. 验收指标与目标

首正文必须包含模型实际生成的非空正文，排除spinner、状态文案、推理文本、假占位答案。区分临时草稿和正式结果，DOM提交与屏幕绘制分别命名。

统一采样点：

| 点位 | 含义 |
| --- | --- |
| T0 | 浏览器提交请求前，performance.now |
| T1 | 公共API收到命令 |
| T2 | canonical命令接受/Run建立 |
| T3 | Worker领取且恢复执行权限 |
| T4 | 当前模型尝试实际开始HTTP请求 |
| T5 | Provider流首事件 |
| T6 | Provider首非空正文delta回调 |
| T7 | 首允许公开的draft写入Redis成功 |
| T8 | API首次把该draft交给SSE发送层 |
| T9 | SDK解析到该draft |
| T10 | React首次提交对应非空正文DOM |
| T11 | canonical答案提交 |
| T12 | Run/Turn终态及消费端结果同步 |

正文隐私门禁可能使T7–T10缺失；合法缺失必须有原因，不能记成0。HTTP重试分别计数，不能只记录最后一次尝试。T8是发送层交付，不冒称浏览器收到。

浏览器用本进程单调时钟算T0→T9/T10；服务内用本进程单调时钟；跨进程采用已有trace关联与UTC校时误差说明，禁止直接相减不同进程的单调时间。

先建立最新版本基线，然后验证：

- 纯回复、不依赖工作区的合格路径：容器create/start/exec、运行实例reserve、RUNTIME_PROVISIONED均为0；主模型1轮、工具0次。
- 普通草稿：T10早于T11；以可控延迟流证明不会等待模型结束，并以真实长正文复核。首delta产生前的等待独立报告。
- 热态简单请求：平台模型前等待p50≤1.5s、p95≤3s；允许公开正文的Provider→DOM链路p95≤500ms。这是工程目标，未达标须定位，不是已承诺SLA。
- 若Provider首正文≤2s，端到端首正文p50争取≤4s；不限制Provider时不承诺统一4s。coverage/private按正式结果口径单列。
- 容器数量、SQL、Redis容量和资源清理不因刷新次数增加；保留原v1/v2整体SQL≥80%配对验收为独立门槛。

每个报告包含样本数、p50/p95/max、错误、重试、模型/配置、上下文长度、队列负载、冷/热状态和版本。少量真实样本只作探索，不作生产p95结论。

## 3. 源码发现与实施约束

Worker execution.py当前顺序：prepare_context → bind_instance_factory → build_prepared_runtime → require_matching_runtime_authority → persist_runtime_authority → build_execution_tool_gateway → Harness。runtime_setup.prepare_runtime对非setup-only无条件provision。

execution_tool_gateway.build_execution_tool_gateway和tool_gateway_runtime.build_worker_tool_gateway目前要求RuntimeHandle；LocalToolGateway在agent_runtime/harness.py中初始化本地workspace、工具及runtime。runtime省略会自动回退LocalRuntime，云端延迟创建绝不能通过传None实现。

文件读、搜索、发布等可能直接操作LocalWorkspace；不能只拦command.run而把其他工作区依赖放行。工程上下文、skills文件、setup-only、snapshot/restore也须逐一追踪。

OciRuntime._create_command在创建时写session/spec/attempt及实例labels，绑定具体workspace。SandboxSpec.digest包含工作区与会话身份；运行容器不能靠换标签/数据库行变成另一Run的沙箱。公共空白运行容器池并非当前架构上的小改动。

Provider deepseek_responses_streaming.py已有first_event与first_public_text计时；优先串联现有字段。agent_observability/execution_metrics.py已有queue/preparation/model等事件指标，先复用而非新建通用监控框架。

## Chunk 1: 测量与草稿链路

### Task LATENCY-TRACE-01：建立可归因基线

候选Owned paths：
- packages/agent-integrations/src/agent_integrations/deepseek_responses.py、deepseek_responses_streaming.py：Provider现有计时与必要窄字段。
- packages/agent-observability/src/agent_observability/execution_metrics.py：复用阶段统计。
- apps/worker/src/zebra_agent_worker/execution.py、transient_output_runtime.py：准备阶段和首公开写入关联。
- apps/api/src/zebra_agent_api/stream_v2_reader.py、stream_v2_http.py：首draft交付计时。
- sdks/typescript/examples/stream-latency/：独立官方SDK真实入口诊断模式，凭据不落盘。
- tests/agent_integrations/test_deepseek_responses.py、tests/agent_observability/test_execution_metrics.py及上述组件现有tests。

实际编码前将Owned paths缩小至必要文件并登记任务。Trace IDs不能成为高基数监控标签；只写结构化诊断日志，不每帧追加PG事件。不记录正文、token、cookie或业务凭据。

- [ ] 对照已有Provider metadata，先从现有日志和浏览器计时获取T0–T12；只补缺失首帧/阶段字段。
- [ ] 跑一次可控流：先reasoning/空frame，再延迟正文，再终态，检查各点位语义及缺失处理。
- [ ] 使用官方SDK公共入口建立最新真实基线：纯回复、无需沙箱的长正文、状态检查、工作区工具任务。
- [ ] 产出各阶段分布与冷/热差异；列最大两项等待，再决定后续改动。

初测每类3次，交替顺序；最终验收普通与沙箱两类各至少20个有效样本，仍标注小样本p95不代表生产。模型成本、重复工具业务副作用受控；有副作用案例使用隔离工作区和只读操作。

### Task LATENCY-DRAFT-01：真实正文即时展示

候选Owned paths：
- packages/agent-core/src/agent_core/harness/model_step.py、stream_deltas.py，仅证据证明共享coalescer有问题才改。
- apps/worker/src/zebra_agent_worker/transient_output_runtime.py、transient_output_composition.py。
- apps/api/src/zebra_agent_api/stream_v2_reader.py、stream_v2_http.py。
- sdks/typescript/packages/client-core/src/index.ts、conversation_stream.ts；React仅必要消费者路径。
- tests/worker/test_transient_output_runtime.py、tests/api/test_stream_v2_reader.py及SDK现有测试。

- [ ] 使用真实Provider首正文计时判断是否产生了可展示draft；短回复没有draft不能直接判断链路失败。
- [ ] 若T6早、T7晚，修共享输出门禁/合并根因；若T7早、T9晚，修通知、读取或重连；若T9早、T10晚，修消费端状态依赖。
- [ ] 保持普通候选正文明确Draft标签；coverage/private和reasoning无公开正文，不降低校验与scope要求。
- [ ] 最终答案同ID替换draft，错误、重连、scope变化、STOP后不得恢复旧草稿；不重复模型调用。
- [ ] 可控流确定性测试、真实长正文、Chromium/WebKit消费者验收集中执行一次。

若最新版本已符合目标，任务以证据完成，生产代码不改。禁止把前端占位文案算首字收益。

## Chunk 2: 按需沙箱与平台等待

### Task LATENCY-LAZY-01：首轮模型不必等待沙箱

依赖：TRACE定位与依赖审计完成；DRAFT路径不回归。
候选Owned paths：
- apps/worker/src/zebra_agent_worker/execution.py、runtime_setup.py、runtime_factory.py。
- apps/worker/src/zebra_agent_worker/execution_tool_gateway.py、tool_gateway_runtime.py。
- packages/agent-runtime/src/agent_runtime/harness.py；必要时新建focused cloud runtime preparation模块，避免超文件上限。
- packages/agent-core/src/agent_core/ports/runtime.py仅契约审计证明必须时修改；优先不扩Port。
- tests/worker/test_runtime_setup.py、tests/worker/execution/、tests/agent_runtime/test_oci_instances.py及focused新回归。

职责：Worker组合配置和执行scope；agent-runtime承载延迟准备的运行逻辑；agent-core不导入基础设施。只加入一个明确的执行内ensure_ready边界，不建立新的资源框架。

#### 准备规则

模型继续看到授权后的完整工具schema，不增加分类器、关键词路由或额外路由模型。首轮模型决定直接回答还是调用工具；资源是否需要由工具/上下文的执行依赖决定。

| 路径 | 处理 |
| --- | --- |
| 已授权、仅消息/已物化上下文、无需workspace输入 | 可延迟沙箱 |
| Host/Client或网络工具 | 审计确认不依赖沙箱才能保持延迟；仍独立执行policy/credential/receipt检查 |
| workspace读写、命令、Git、测试、发布 | 初版保守触发准备，防止改变workspace约束 |
| 工程workspace上下文、setup-only、snapshot/restore/fork | 初版保留eager；不能忽略输入以换速度 |
| 未知依赖、恢复缺乏确定证据 | 保留eager；不是问题复杂度分类 |

#### 顺序与生命周期

执行内状态：UNPREPARED → PREPARING → READY → CLOSED；准备失败→FAILED。仅内存管理执行内状态，跨Worker依赖现有PG实例事实恢复，不新增“未准备runtime”假事件。首轮上下文只能声明配置能力与未分配状态，不能声称沙箱已就绪、工作区已检查或实际authority已建立。

- [ ] 审计所有prepare/provision/destroy/snapshot/restore调用，以及所有workspace工具和上下文读取；输出完整依赖表。
- [ ] 在首轮前完成command intent、task binding、lease/fence、policy、输出scope及现有恢复。已persisted spec与当前配置不匹配不能因延迟而漏检；能预检的digest先核对，实际engine identity在准备时每次新鲜校验。
- [ ] 云端始终注入明确runtime对象；不得触发LocalRuntime默认fallback，不伪造EffectiveRuntimeAuthority或RuntimeHandle。
- [ ] 首个需要runtime的合法工具执行前调用唯一ensure_ready；policy/HITL完成后再实际分配，拒绝的工具不消耗沙箱。
- [ ] ensure_ready内部复用build_prepared_runtime、matching authority、PG instance生命周期、persist_runtime_authority与workspace写权限探测；同步刷新当前执行上下文，不保留旧authority快照。
- [ ] 同一attempt重复或并发调用最多一次准备；现有gateway包含parallel_safe_tools，必须确认实际并发调度，使用执行内锁或既有串行准备机制，不使用全局锁。初始化期间定时/阶段检查STOP、lease loss及原deadline。
- [ ] 未准备便结束的纯回复清理noop；已准备资源由唯一owner释放。准备部分失败、STOP竞争和Worker崩溃继续交给现有实例清理/恢复。
- [ ] 旧恢复有真实实例/快照时保留原路；无实例的lease接管重新按需准备。不得把模型曾说要调用工具作为执行完成事实。
- [ ] 默认仅Cloud显式配置启用；本地SQLite/CLI原行为保持。回滚设置只影响新attempt，不改变在途绑定语义。

最小回归：纯回复0实例；首工具只prepare一次；拒绝工具0实例；Host只读依赖按表运行；准备中STOP；失租约；并发ensure；失败清理；接管；authority不匹配；setup与snapshot保持原行为。

收益评估：简单请求省去实际沙箱准备耗时，当前配对约1.29s仅供量级参考。复杂任务将该耗时移到首工具执行前，不保证整任务变快；也可能增加首工具等待，因此工具TTFT必须单列。

### Task LATENCY-ADMISSION-01：入口与接单等待

依赖TRACE；仅修改最慢的已证明步骤。候选范围为公共API命令adapter、apps/worker/src/zebra_agent_worker/worker_polling.py、loop.py及确实被证明的storage adapter；编码前补精确Owned paths。

- [ ] 将T0→T2拆为浏览器提交、网络、API验证、accepted-command/commit；T2→T3拆通知、接单和恢复。
- [ ] 复用现有通知和有界恢复；查重复串行读取、每请求重建client、冷DNS与连接握手。不擅自放宽有效期、替换PG事实或新增无界缓存。
- [ ] 能删除重复工作就删除；仅独立、无副作用读取可并行。持久化、授权、lease和workspace建立顺序保持。
- [ ] 若慢在网络部署位置，单列同区域部署/链路方案；不能用改SDK解决服务间RTT。
- [ ] 一组交替无模型配对与真实入口复核；禁止通过更高频SQL轮询换低延迟。

## Chunk 3: 冷启动与Provider

### Task LATENCY-WARM-01：低成本预热

依赖TRACE证明冷/热差异。初版只做现有运维能力：digest镜像提前pull到目标节点、Worker常驻ready、连接client适当复用。不会用后台模型请求制造“热态”。

- [ ] 分别测进程刚启动、镜像未就绪、首次连接、新Run新容器与连续请求；冷态只在隔离节点测，不清理正常服务镜像/缓存。
- [ ] 将镜像拉取移到节点准入；配置image digest、runsc版本及资源校验。
- [ ] 核对Worker已共享httpx client，复用现有生命周期而非叠加连接池。
- [ ] 若冷态不是主因，不新增预热代码；运行时共享路径仍保留每次新鲜daemon identity与fence。

### 条件后续：运行沙箱池/快照

不是本轮最小实施必选项。进入条件：按需沙箱完成后，必须创建沙箱的任务仍被启动成本主导，且收益抵得上常驻成本。

当前Docker mount、label与spec digest在创建时确定，因此禁止直接把任意空白容器领给新Run。可先评估同一已授权会话下一attempt的提前准备，但仍需解决attempt/fence变化；不得默认安全。

通用池若要落地，须先独立ADR：工作区注入机制、不可变实例身份与可变执行绑定的边界、新authority契约、PG原子领取、多Worker竞争、污损检测、孤儿回收、TTL、配额及池空fallback。状态可设计为AVAILABLE→CLAIMED→BOUND→DESTROYED，接触业务数据的实例不回池。

池必须按image digest/runtime/资源隔离配置分组；不得挂全租户workspace大目录来绕过动态挂载问题。池空可以回到既有冷创建；身份错误或不确定绑定失败必须拒绝执行而非复用其他容器。

快照恢复另作native PoC，检查gVisor文件系统、版本和恢复限制。不得将现有workspace文件快照误称运行进程快照。

### Task LATENCY-PROVIDER-01：首正文产生时间

以真实T4→T6为依据。复用DeepSeek已有first_public_text字段，检查是否流式调用、是否先发reasoning、输入token/推理强度、连接建立和Provider排队。

先减少重复上下文与不必要串行模型轮数；缓存只缓存可稳定复用且已授权的输入，不缓存失效业务事实。推理强度/模型更换作为显式策略实验，报告答案质量，不静默降低用户选择。

目标是降低Provider TTFT；没有Provider能力和质量证据不承诺固定秒数。官方参考：https://developers.openai.com/api/docs/guides/latency-optimization 。gVisor参考：https://gvisor.dev/docs/user_guide/checkpoint_restore/ 。

## 4. 配对验收与止损规则

A/B固定model、effort、prompt、上下文版本、镜像digest、网络、负载；交替顺序，记录错误/重试，不只挑最快成功请求。纯回复、长正文、Host检查、workspace只读四类分开统计。

按需沙箱验证必须有native PG+真实gVisor测试，不以mock代替实际authority。真实模型只验证确实需要的端到端行为，不重跑用户原Run。所有工具数据用隔离/只读范围。

最小命令：

- uv run pytest tests/worker/test_runtime_setup.py tests/worker/test_transient_output_runtime.py tests/api/test_stream_v2_reader.py
- uv run pytest tests/agent_runtime/test_oci_instances.py tests/agent_integrations/test_deepseek_responses.py tests/agent_observability/test_execution_metrics.py
- cd sdks/typescript && pnpm verify
- make check（在明确源码、已分类基线下执行一次完整门槛；native新测试必须真正执行、不得skip充当通过）

每任务先一个证明根因的失败检查，最小实现，集中回归。已有缺陷、过时fixture、本次回归分别列明；只有本次回归、安全或数据丢失阻止切片交付，不能以忽略生产风险收尾。

最终报告必须分别写：代码完成、focused gates、全量门槛、真实Provider、浏览器、版本启用与SQL验收。原STOP/SQL80%未验收不能被首字优化替代。

## 5. 任务顺序、回滚与交付

执行顺序：TRACE → DRAFT确认/最小修复 → LAZY → ADMISSION最慢点 → WARM必要项 → PROVIDER必要项 → 集中端到端验收。通用运行池和快照在独立ADR后决定。

每次只claim一个Ready任务；后续依赖任务Locked。人类owner Luke Ding，执行Codex。每任务一个codex分支/worktree，Owned paths先登记。沿用已授权cloud-agent-trench本地逐阶段集成解锁；不推送、不远端部署、不发布npm。其他人的UI工作不stage/reset。

SDK五包消费端校验保持contracts/ui-contracts/client-core/react/react-charts；接口兼容修改不必全包升版本，有公开契约变更才按依赖升级。交付本地tarball/manifest及真实入口版本来源；没有安装到入口不能宣称验收了该版本。

回滚：关闭新attempt按需配置恢复eager；在途实例依旧沿原owner/fence清理。诊断采样可以关，不影响业务；恢复旧镜像前确认新旧配置兼容。在途模型不为回滚重新调用。

交付物：阶段trace分布、依赖审计表、最小代码提交、focused/full gate记录、真实配对结果、SDK消费端来源、资源清理与回滚记录。暂不把方案目标写成客户SLA。

预计：TRACE+DRAFT约0.5–1天；LAZY与恢复回归约1–2天；ADMISSION/WARM必要项及集中真实验收约1–2天。核心方案约2.5–5个工作日，按源码审计调整；不含通用池/快照新设计、外部Provider等待和既有STOP/SQL完整验收。运行池若必要须另估，不能塞进最小切片。

方案集中只读审查：GO。核对当前eager顺序、runtime fallback、workspace工具依赖、并发准备和OCI不可变绑定边界；完整依赖表及STOP/接管native证明仍属于实施任务，未冒称已验证。
