# AG-UI 1.0 标准与 Zebra durable 边界合同

状态：G0 合同冻结；G1/G2V/G2 已审查交付，G3 实施中。不是生产上线或完整兼容认证。
任务：AGUI-G0-CONTRACT-20261028。实施顺序见
[完整方案](superpowers/plans/2026-10-28-agui-full-interaction.md)。

## 1. 固定来源与版本

| 对象 | 冻结值及含义 |
| --- | --- |
| 目标 wire 协议 | AG-UI `1.0`；新输入的 `protocolVersion` 为 `1.0` |
| 官方 schema | [schema.json](https://ag-ui.com/spec/1.0/schema.json)，Draft 2020-12 |
| 官方仓库修订 | `fdbca490dc90fd8fbce2b342df79383bd70559af` |
| 不变来源 | [修订固定的 schema](https://raw.githubusercontent.com/ag-ui-protocol/ag-ui/fdbca490dc90fd8fbce2b342df79383bd70559af/spec/1.0/schema.json) |
| schema SHA-256 | `4b5c93226838a0e72d88e6c5df20633c686c49fcb75d9be2815c6cbf9e48e71a` |
| schema 原始长度 | 94359 bytes；保留官方原始字节，不格式化 |
| G0 基线 Python | `ag-ui-protocol==0.1.19`；G2 后实际依赖为 `1.0.0`，旧 wire golden 保留原 provenance |
| G0 JS 候选 | `@ag-ui/{core,client,encoder,proto}` 各 `1.0.3`；G1 选定 client/core，见第9节 |

冻结资料位于 `tests/conformance/agui_contract/`：`upstream.json` 记录来源；
`schema-1.0.json` 保留原始字节；`event-catalog.json` 沿根 Event 的 `oneOf`
引用读取每个事件的 `type.const`。目录覆盖 31 个实际 union 成员，不能用 SDK
枚举、说明文案或其它对象的 `type` 常量拼成协议目录。

| 事件族 | 官方实际事件标签 |
| --- | --- |
| Text | TEXT_MESSAGE_START、TEXT_MESSAGE_CONTENT、TEXT_MESSAGE_END、TEXT_MESSAGE_CHUNK |
| Tool | TOOL_CALL_START、TOOL_CALL_ARGS、TOOL_CALL_END、TOOL_CALL_CHUNK、TOOL_CALL_RESULT |
| State | STATE_SNAPSHOT、STATE_DELTA、MESSAGES_SNAPSHOT |
| Activity | ACTIVITY_SNAPSHOT、ACTIVITY_DELTA |
| Special | RAW、CUSTOM |
| Run/Step | RUN_STARTED、RUN_FINISHED、RUN_ERROR、STEP_STARTED、STEP_FINISHED |
| Reasoning | REASONING_START、REASONING_MESSAGE_START、REASONING_MESSAGE_CONTENT、REASONING_MESSAGE_END、REASONING_MESSAGE_CHUNK、REASONING_END、REASONING_ENCRYPTED_VALUE |
| Subagent | SUBAGENT_STARTED、SUBAGENT_FINISHED、SUBAGENT_ERROR |

这是完整消费者的目标范围。生产端只从真实公开事实构造需要的事件，不为覆盖
标签而编造 reasoning、RAW 或子任务。后续逐事件登记 schema 接受、实际生产、
归并、展示/降级、恢复及消费者验证，不能用“31 个标签”代表端到端覆盖。

## 2. 三个独立轴与显式配置

协议版本描述事件形状；传输描述交付方式；projection profile 描述从持久事实
到公共事件的版本化语义。这三个轴不得互相替代。

| 配置 | 事件协议 | 传输与语义 |
| --- | --- | --- |
| 无显式新配置的既有行为 | 旧 Python 0.1.19 合同 | 原 v1/v2 选择、旧 reducer、checkpoint、cursor、archive tag 均保持 |
| `agui-standard-1.0` | AG-UI 1.0 canonical | 标准 POST 输入 + SSE 完整事件；正文保留 TEXT_MESSAGE_CONTENT |
| `zebra-reliable-v2-agui-1.0` | AG-UI 1.0 canonical + 版本化 Zebra 扩展 | 既有独立准入与只读 GET 观察模型、签名 cursor、chunk/ACK、draft/reset、完整恢复 |

`legacy-agui-0.1.19` 只作为文档中旧 profile 的描述名称；不得给旧存储键或旧
cursor 回填这个字符串。`ag-ui-v1` 与 `ag-ui-v1-coverage` 仍是现有 checkpoint
版本。现有 v2 不因传输名字含 v2 就自动升级为 AG-UI 1.0。

新配置兼容 header 保留为 `X-Zebra-AGUI-Profile`，其值只能是上表两个新 ID；
它属于 BFF/Zebra 适配边界，不向标准 RunAgentInput 顶层加入私有字段。
标准版本仍由输入 `protocolVersion` 声明。未知或矛盾选择在准入前明确拒绝，
不静默降级；没有 header 且未显式配置新 profile 时严格保留旧行为。

发现合同使用可选字段 `metadata.aguiProfiles`（支持的新 profile ID 数组）。
G2V 已在现有 `GET /capabilities/runtime` 实现承载点及绑定 registry 的可用性选择，
并验证默认旧 DTO 不新增 metadata；隔离实现见第10节。G2 已实现并审查
独立 producer，生产 registry 默认为空，新生产 profile 仍不可用。实际 Trench 业务
bootstrap envelope 的字段转发待 T1 实现；这不是新增 Native 端点。声明仅提示
兼容能力，不授予 namespace、工具、审批或执行权限。

[官方 HTTP SSE 绑定](https://docs.ag-ui.com/spec/1.0/basic/transports/http-sse)
没有 Last-Event-ID 续读；断线本身不能授权本平台重发业务请求。可靠 v2 是
Zebra 扩展交付合同，消费者先重组它，再送入标准语义管线。标准 profile 不得
要求普通客户端理解 `zebra.message_replace` 或 `zebra.canonical_chunk` 才能读到正文。

## 3. 隔离必须先于语义变更

G2V 先实现 profile 的选择、校验和持久绑定，覆盖 projector、checkpoint key、
cursor scope、完整恢复、历史回放及 downgrade。新 profile 必须有独立投影
版本和 checkpoint 命名空间；不能只给新 projector 打标签却读取旧 payload。
旧符号 cursor、frame_index 和已发布包仍解析为原投影，不跨版本猜测边界。

新配置绑定应冻结 namespace/Task、内部 Run、profile/revision、投影版本及
原持久 anchor；新签名 cursor 的 scope 必须覆盖该绑定，跨 profile/revision
拒绝。不能改旧 cursor 的编码/HMAC domain 或 scope 算法。旧 capability profile
摘要、准入 fingerprint、checkpoint key 与历史 hash 均不得重算或就地升级。
绑定缺失应拒绝启用新 profile，不能读取历史正文去推断并回写。

G0 的 golden 刻意保留当前行为：proposal 只输出 TOOL_CALL_START/ARGS，
TOOL_CALL_END 延后到执行结果；TURN_CANCELLED 仍映射旧 interrupt outcome；
旧可靠 v2 将正文转成 `zebra.message_replace`。这些是兼容基线，不是目标标准
语义。新的 END（参数完成）、cancelled outcome、步骤/Activity、用量与子 Agent
语义只能在完成上述隔离后进入新 profile。

## 4. 公共协议 Run 与内部执行权威

namespace + threadId 界定公开会话；Task、Session/Segment、executionRun、
protocol runId、messageId、toolCallId、activityId 与 subagentRunId 各有用途。
现有同一内部 executionRun 的审批续接继续使用原执行身份与 durable decision；
标准 interrupt 结束一个协议 Run，后继协议 Run 使用新公共 runId。

新 profile 必须先建立可重建的映射：由原执行身份、profile/revision 与已存在的
**durable continuation anchor** 确定公共后继 ID，并持久绑定父协议 Run 和 usage
切片。不要在 G0 虚构一个未经审查的拼接算法。映射算法在 G2V/G2 合同审查
及测试后固定；若尚无可用 durable anchor，则拒绝启用而不是用时间戳、随机 ID
或浏览器状态补位。现有 `resume_run_id()` 是旧纯函数，不是新的执行授权合同。

公共 ID 改变不创建 Worker 执行、不新增业务 Run、不替代原 receipt，不授予
恢复或写权限。审批、权限、Controller、撤权、Effect Ledger 与业务收据仍在
原 durable 边界校验；相同内容的合法 delta 不按 payload hash 去重。用量只计
相应协议 Run 的模型调用，回连/重放不得重复累计，未报告保持 unknown。

## 5. 两种双向往返

[标准 frontend tool](https://docs.ag-ui.com/spec/1.0/events/tool-calls) 的结果由
应用产生。新 profile 从真实且已授权的待处理 Client Effect 形成 START/ARGS/END，
结束为 success 并准确声明 pendingToolCallIds；它不是 human interrupt。应用
执行或拒绝后，下一输入 messages 为每个未回答 toolCallId 提供工具结果，失败
或拒绝也形成明确结果。服务端不得替应用伪造 TOOL_CALL_RESULT。

复用原 Effect ID、Client Session、Controller、修订、参数校验和当前权限；浏览器
任意 tool message 不能替代原确认结果/拒绝收据。unknown 只对账原效果，不换
UUID 重发；历史恢复零执行。现有只输出 STATE_DELTA 的 Client Effect 路径不能
被声明为标准完整往返。G5 须由真实标准消费者完成调用、应用结果回传、继续
执行；缺此证据不声明 frontend-tools 能力。

[interrupt/resume](https://docs.ag-ui.com/spec/1.0/basic/patterns/interrupt-resume)
的消费者在发送前必须完整覆盖最近一次 interrupted Run 的每个 interrupt；
status 以冻结 schema 为准：`resolved` 或 `cancelled`。逐项选择可先存在本地，
但不能缺项先发下一 Run；过期项只能明确放弃，不能继续 resolved。遗漏不等于
放弃。重复、旧 Run、伪造、撤权及过期项不得执行未授权动作。

标准消费者负责完整性；Zebra 作为保留 durable 状态的生产端，也校验原审批
事实、schema、expiry、authority 与幂等性，缺项时不执行未批准动作。新标准
resume.payload 可为任意非 null JSON 值，旧 AgUiResumeEntry 的 dict/status 合同
不被就地放宽。旧单项审批 API 不自动变成新的批量 API。

## 6. 可运行证据与明确边界

离线、只用 stdlib 的完整性检查（无需虚拟环境、网络或数据库）：

```sh
python3 tests/conformance/agui_contract/selfcheck.py
```

真实当前 Python 路径的 golden 检查（使用本工作树已同步的开发环境）：

```sh
.venv/bin/python -m unittest discover -s tests/conformance/agui_contract -p 'test_*.py' -v
```

或运行同目录 `run.sh`；`ZEBRA_PYTHON` 可指定解释器，脚本显式将本工作树
workspace 源码放到 PYTHONPATH，避免其它 checkout 的 editable 安装遮蔽。

`fixtures/legacy-0.1.19.json` 固定 UUID/时间戳，来自实际 AgUiProjector、
EventEncoder、canonical_wire、StreamV2CursorCodec，包含 14 种当前输出标签、
四类场景、每个精确 frame cursor 的尾部和签名 v2 token。不调用模型、不读取
真实业务库。测试还覆盖 event-level replay、错误源 ID/Run/scope、Unicode 分片
字节预算、schema 篡改、目录缺项及重复 union；不用手写 SSE 假装生产投影。

红灯证据：首次运行 golden 测试缺少 baseline 文件而失败；冻结真实输出后转绿。
负例始终断言 schema 字节/目录漂移及 cursor 错绑失败。golden 变更必须作为
显式兼容性审查，不能自动“更新预期”消除回归。

**这些检查不是完整官方 schema 验证器，也不是完整 1.0 行为认证。** stdlib
检查仅证明字节、来源登记与目录一致性；旧 Python 模型验证也不能替代官方
Draft 2020-12。G1/G2 需独立官方 schema 正反例及生命周期/chunk/patch/归属/
恢复测试。这里不证明 native HTTP、生产数据库 checkpoint、前端消费者、性能
或部署验收；原 checkpoint/profile 存储 hash 不被修改，也未进行线上逐行认证。

## 7. ADR 适用范围

[ADR-015](ADR-015_Zebra_Embedded与CopilotKit_AGUI边界.md) 的 durable authority、
BFF 授权和外部投影边界继续有效；其中“不得建设 TS SDK / Trench 必须全部使用
CopilotKit”的狭义选型约束由本合同及已批准完整方案取代。现有 TS SDK 继续，
CopilotKit 为可选标准消费者；不得由此扩张为第二份 durable 事实源。


## 8. 分片退出门禁澄清

G0冻结schema/目录/profile/旧行为及映射的安全约束，不宣称已选定JS归并实现、
公共runId算法或性能SLO。依赖实际证据的决策按计划审查修订：G1在最小官方
JS消费试验后固定复用方案；G2V在任何新profile生产语义前固定并测试映射算法、
checkpoint版本及真实discovery承载；G7优化前采集匹配样本并冻结性能门槛。
这些未完成项阻塞各自下游，不得用G0通过替代其验收。


## 9. G1 标准消费入口（尚非生产profile）

G1以实际消费试验选择固定的 `@ag-ui/client/core@1.0.3`，复用官方
enforcement、chunk展开、verify、defaultApplyEvents与source-error drain，
另直接登记已复用的 `rxjs@7.8.1`、`fast-json-patch@3.1.1`。旧14类投影、
SSE/v2、ConversationStreamReducer、业务工具与权限入口不切换。

新增 `standardAgUiEvents` 和 `StandardAgUiConsumer`：每实例明确绑定一个
thread/run，接受录制或live iterable，提供隔离snapshot、pre-apply事件和
post-apply状态通知。消费状态不是任务执行事实，更不是durable commit证明。
`prepareResume`仅准备完整恢复数据，不发送请求、不执行效果、不作审批决定。

官方默认实现会跳过无法应用的patch、在非test模式吞掉subscriber异常，
自定义内存agent还必须自行实现stop；这些边界不能直接冒充可靠ACK。G1以
patch副本预检、显式失败、私有stop/iterator清理请求及前序应用通知栅栏保护
已接收状态。受阻live源和延迟通知的resolve/reject均有回归；terminal在
官方管线成功结束后才公开，不提前接受后续事件。

旧代码的包版本仍是内部0.1.0构建候选，本分片不发布registry、不替换Trench
vendor，也不能覆盖已交付同名包。G6交付前统一版本、tgz、manifest与lock验证。
31类taxonomy/有效例可接受不等于完整1.0行为认证；完整消费者/生产投影/
Artifact/审批/恢复闭环仍分别由G2V–G7/T1的门禁证明。

G1阶段本地reader采用128个待处理canonical事件（另有1个等待前序通知的active项）
上限，溢出显式拒绝消费并停止订阅，不伪造Run失败或重新执行。该限制也可能
拒绝突发同步录制源；它是有限容量拒绝策略，不是producer背压或无限历史承诺。
G3/G7须在启用profile前验证实际冷恢复、节奏控制和字节/内存预算，不能直接
把未节流的大数组当作无限流。不能强制取消调用者自有IO或永不完成的回调
promise；reader会及时失败并请求cleanup，底层资源中止仍由source owner负责。

G1验收：25项新增、完整SDK199项通过且无跳过；type/package、实际dist的
ESM/CJS消费通过。规格与代码质量审查通过。框架消费者/双浏览器检查通过后，
最终容量guard再经过完整SDK199/type/package复验。新增入口尚未接生产profile，
因此不把这些证据等同于完整1.0生产协议、Trench迁移或吞吐/模型验收。

## 10. G2V profile 隔离与可恢复绑定

显式注册入口是 `ZebraAgentApi.agui_profiles`；每个 `AgUiProjectionProfile`
同时绑定 profile ID、revision、实际 projector 与可冷恢复的 state_type。
默认 registry 缺失，不启用任一 1.0 profile；不存在自动将旧 projector 注册为
标准实现的生产配置。已注册的测试 projector 仅证明隔离，不证明 1.0 生产语义。
`X-Zebra-AGUI-Profile` 请求缺失时仍选择旧实现；未知、空值或未绑定值返回
`409 agui_profile_unavailable`，不能静默降级。原始 Task/Session SSE 不接受此 header。

实际发现承载点为已有 `GET /capabilities/runtime`，仅当实际 registry 非空时
添加 `metadata.aguiProfiles`，内容来自其 `available_profiles`。默认不添加 metadata；
其余能力合同保留，schema_version 随增量迁移版本正常更新。业务 BFF 后续把该字段
转发到自己的 bootstrap envelope；不得硬编码另一个“支持列表”。

新 output checkpoint 使用 `<profile>:r<revision>`，严格隐私使用独立
`<profile>:r<revision>:coverage`。namespace、Task、原 command anchor 仍由现有
ProjectionScope 组成；binding ledger 也由完整 output version 分离。consumer、
observer、plan、materializer、snapshot 快路及单事件冷恢复都使用同一显式绑定。
落后于 source 的 SSE 也按当前 snapshot 完整 version 从同 namespace 的组合工厂
构造问题读取器，不能把新 scope 交给旧 work store；隐私切换后重新选择。该构造无
I/O，实际查询仍受原 deadline 和 store scope 校验约束，不 enable/backfill/repair。
每次冷恢复通过 profile.state_type.from_checkpoint 创建独立状态；默认仍为原
ProjectionState。共享 projector 不保存当前 Task/Run 或可变恢复上下文。G2 新状态
字段和对应 cells、usage/continuation 上下文必须在其明确 owned paths 中实现，
不能通过在共享 projector 上写“当前 Run”来传递。G2V 未实现这些新语义。

精确 cursor binding 是 UTF-8 canonical JSON（ensure_ascii=True、紧凑分隔符）的
SHA-256，数组按以下次序：`zebra:agui:binding:1`、namespace、Task UUID 字符串、
内部 executionRun、profile ID、整数 revision、完整 projector_version、原 command
anchor event UUID。新 durable cursor 使用 version=2 并包含此 profile_scope；旧
version=1 不增加字段。跨 namespace/Task/Run/profile/revision/privacy 不能恢复。
可靠传输将该 digest 加入原 stream scope 的身份数组，并用 `agui:` 标识新 scope；
新签名 cursor 的前缀为 `v2p.`，HMAC domain 为
`zebra:stream:v2:agui-profile-cursor\0`。旧 `v2.` 的编码、身份数组及 HMAC domain
逐字保留。新 token 即使带 `recovery=full` 也先核对签名与 scope，不能降回旧路径。
标准 SSE 的 durable event ID 保持其观察坐标性质，不由其授予任何执行权威。

公共协议 runId 的重建算法为 `agui:` 加 canonical JSON 数组的 SHA-256：
`["zebra:agui:protocol-run:1", binding_digest, continuation_anchor_event_uuid]`。
首次使用原 command anchor；后续仅接受原 Run 窗口内、相同内部 run_id、被 scalar
header 明确标记为 internal_continuation 的 SESSION_COMMAND_ACCEPTED。算法入口
逐一核对 source.read_event_header 返回的原 anchor 和 continuation header，拒绝
伪造或错位坐标，不扫描正文、不新增 Worker 执行，也不重写 receipt。后继协议链接
属于独立 binding metadata，不能占用只表示 spawned subagent 关系的 parentRunId。

该 hash 只能在 durable admission anchor 已存在之后计算。G2V 没有实现标准
RunAgentInput.runId 的 POST admission 互操作：G3 必须明确选择由已授权 BFF 先准入
并返回绑定，或在标准准入事务中持久绑定客户端提供的 public runId；不能悄悄回显
另一个 runId，也不能扫描所有 Runs 来反解 hash。内部执行/审批/收据身份不变。

增量 PostgreSQL v115 安装 profile-aware source routing，保留历史迁移 checksum；
SQLite 使用同一 classifier。每个 family 根据真实 source privacy 只唤醒 ordinary
或 coverage queue；晚到隐私事实重新准备对应严格队列，旧 output 行不被改写。
显式配置最多六个 projector versions（旧两个 + 新两个 family 的各两个），第七个
仍拒绝；没有无限 fanout。GET 不注册、不迁移、不 repair、不 materialize。

## 11. G2 标准公开投影（已审查，未激活）

`StandardAgUiProjector` + `StandardProjectionState` 是独立 producer/state。
只有显式 `AgUiProjectionProfile(..., projector=StandardAgUiProjector(),
state_type=StandardProjectionState)` 才使用它；默认 registry 仍为空。
官方 Python `ag-ui-protocol==1.0.0` 复用全部生成模型；独立 dev validator
`jsonschema==4.26.0` 校验 G0 冻结 Draft2020-12 Event union 的正反例。
旧 projector 仅明确 assistant role 和使用官方 JSON Patch 校验入口，以保留
原 wire bytes；旧 schema/fixture/cursor/HMAC 与旧 migration 文件不重写。

- 每个公开协议 Run 首帧 RUN_STARTED，紧接实际派生 STATE_SNAPSHOT 建立 patch
  base：首次为空，续接重建已接受的公开文档，不能盲目置空。G2 文档仅拥有
  `/execution`；后续用 add patch 保留其他状态。既有 Client Effect fallback 未在
  新 profile 冒充完整消费，G5 先完整组合再激活。审批/澄清不发 MESSAGES_SNAPSHOT，
  不删除既有消息/Activity。HARNESS_ATTEMPT_STARTED/SESSION_RESUMED 与真实终态才
  改变 execution phase；protocol success 不能冒充执行/业务完成。
- 已校验的完整 TOOL_CALL_PROPOSED 对象一次产生 START/ARGS/END；END 只结束
  参数。pending result 仍保留，执行 Activity 的 running 仅来自真实 STARTED，
  完成/失败只来自对应 durable terminal；取消不伪造结果。富媒体和工具正文复用
  已有 `tool_result_content` / `project_content_parts`，不外发原 metadata。
- PLAN_UPDATED 复用 SessionPlan 校验与稳定 plan Activity ID，提供真实实时进度。
  标准 Step 仅在已观察 in_progress 后又有显式同 ID/内容 completed/cancelled 时
  回顾式成对交付 START/FINISHED；保留原观察时间/身份，取消状态用 metadata 区分。
  未完成 span 跨等待/合法续接保留，删除/替换使其失效；Run 终态不制造成功。
  观察跨度可含审批暂停，不能宣称实际执行 duration。TESTS_COMPLETED 仅记录结束。
- MODEL_RESPONSE_DELTA、候选/final model response 与 commentary reservation
  都不是发布。正文只来自 PUBLIC_OUTPUT 和 ANSWER_COMMITTED；实际 commentary
  publisher 的 durable chunks 按原 model-call/source digest 在每个协议切片内拼接。
  实际末块结束；若协议先终止，END 明确 publicationComplete=false，不补正文或
  冒充最终提交。只保留 chunk offset，真实续接剩余块开新的切片 message ID；原
  publication ID 不重发，相同正文但不同 publication ID 不按内容 hash 去重。
  strict Coverage 必须首先经过 coverage_projection_event；任意答案/工具正文、
  公共候选文本与私有 metadata 不会借新 profile 绕过原隐私边界。
- 只有真实 APPROVAL_REQUESTED / CLARIFICATION_REQUESTED 才产生可回答 Interrupt；
  question/responseSchema 使用原公开事实，clarification ID 不能冒充 toolCallId。
  delivery/verification pause 公开完整已验证 DeliveryAssessmentPayload（包括 unmet/
  satisfied/evidence/artifact refs），不复制外层 metadata/候选正文，不伪造未知枚举。
  缺失 assessment 就不发该事件，不把 partial/blocked 变成人工问题。
- 非人工 SESSION_SUSPENDED 先公开 paused execution patch，仅 allowlist diagnostic，
  不公开路径/runtime/原 metadata。budget/verification/交付阻塞/用户 snapshot/未知
  非失败停止关闭为 cancelled，绝不冒充 success；storage/authority/plugin 服务故障
  关闭为 RUN_ERROR，但 execution 仍 paused，不冒充 durable business failed。
  workspace drift 为非失败 paused/cancelled。协议 cancelled 不等于 durable
  SessionCancelled；原执行可在合法续接事实后形成普通新公共 Run，不是 AG-UI resume。
  依据 [1.0 lifecycle](https://docs.ag-ui.com/spec/1.0/events/lifecycle) 的 cancelled/
  run closure 规则；此前候选采用 pause-success 的设计已在提交前纠正。
  冻结 budget 没有原生额度修改动作，不宣传虚构问题。waiting_children 有真实后台
  工作，继续同一活动协议 Run；Client Effect 完整往返留在 G5。
- TURN/SESSION_CANCELLED 产生 cancelled outcome，终态最多一次。真实 failure
  产生通用 RUN_ERROR；error、success、cancel 与 input interrupt 都保留本切片
  已知 usage。missing count 保持 absent，bool 非法，cache miss 不是 cache write；
  reasoning/cache 为子集，不重复相加。只使用实际模型 token 事实，子任务调用
  次数不变成 token。每个实际 call 都参与 unknown 传播，不能跳过全缺字段的 call；
  已知 provider/model 的缺失字段使该组对应字段 absent，无法归属的全未知 call
  使 inclusive terminal usage 省略。已代表的 research/delegation 没有 token 事实时，
  整体 totals 同样省略；在途 child 的未知标记跨协议切片保留，真正结算后下一切片
  才重置。已有真实数值仍在 scope=model_call 的 CUSTOM 事件逐调用公开，不能冒充
  inclusive totals。绝不根据 model_calls_used 推断 token。
- durable SUBAGENT_DELEGATED 的 event ID 定义 invocation，绑定原 child/tool/name，
  立即公开 delegated Activity（不是实际 child running 证明）。标准 START/terminal
  仅在匹配终态时回顾式成对交付；parent cancel/interrupt 不伪造子成功/错误。
  完成只信任当前 epoch 的 HARNESS/resume、原 deterministic wakeup key/revision
  及精确无重复 child set；原 worker 同事务从真实 terminal links/events 生成该事实。
  不读取子私有正文，不以 child ID 授予访问。failed/cancelled 产生 SUBAGENT_ERROR。
  research producer 增补原 tool-call/name；历史稀疏事件不猜父归属。该生产者在工具
  返回后才持久化 START/terminal，标准事件不填虚构开始/结束时间，并明确
  `timing=observed_after_execution`；这不是 live spawn 或真实 duration 证明。

公开 Run ID 仍复用第10节 hash：已暂停/等待真实输入的协议切片遇到原 immutable
internal continuation anchor 才开后继；waiting_children 的 resume 不重复开关 Run。
原 TURN/SESSION completed/cancelled/failed（含协议早已暂停后到达的事实）阻止迟到
内部 resume 再开公开 Run；映射可能的 anchor 不等于授予恢复执行权限。
实际内部 header 为 HARNESS/resume 且 `command_run_id is None`，不是新业务 Run；
G2 修正 G2V 曾以模拟非空 run_id 测试的条件，并用 SQLite/PG 实际写入 header 验证。
前序关系只在 versioned `previousProtocolRunId` metadata，不能放入 parentRunId。

新 `standard_v1` cells 固定原 Run anchor 的 root Segment，跨 Segment 共享派生状态。
原 namespace/Task/source/member/CAS 校验仍生效；SQLite/PG 提交另外核对该 root，
旧 profile 不能写新 cells。v116 仅增补派生 schema，所有旧 migration bytes 保留。
恢复严格读取当前 Event 之前的 cells，不窥视之后状态或历史正文。原 anchor 已
处理后必须存在完整 root count/chunks；缺失、版本/类型/私有字段损坏、错误公共
Run 绑定都明确失败，不重新开始或丢失已得用量。储存的 v1 schema/phase/usage/
child/coverage 形状受校验，不能把私有任意 JSON 作为 STATE_SNAPSHOT 输出。
共享 projector
没有当前 Task/Run 可变字段。call ID 在协议切片内、publication ID 在原执行绑定内
使用 hash point cells；只 hash 身份，不 hash 正文。活动状态/已知 usage 聚合使用
有界小 snapshot，不保存工具参数、
私有 conversation 或完整结果。10k-call 回归验证 point reads 与小 snapshot 不随
已结束 call ID 历史增长；32KiB 活动元数据及原 1MiB/1024-key Page 门禁明确失败，
不会部分发布。G7 仍须验证实际长历史性能、并发与完整传输恢复，不以此替代 G6/G7。

标准 profile 的 source Page 仍最多256条，但并不假设整个 Page 的派生状态日志
一定能塞进1MiB。物化在没有任何写入的阶段遇到明确 Page-budget 异常时，按有界
二分前缀重算并返回可提交 prefix；consumer 只按实际 committed.through_sequence
推进，剩余源事实在后续批次处理。单 Event/校验/缺失状态错误不因重试绕过。
旧 profile 保留原 Page/异常行为。256次模型事实的回归验证完整前沿、单次 Run
开始和无遗漏总数；G7 仍须测量真实10k/native/并发的吞吐成本。
strict 新 profile 先调用原 privacy sanitizer，再只保留 allowlist 生命周期分类：
waiting_children 不关闭，infra/authority 保持 RUN_ERROR，workspace drift 保持
paused/cancelled；不复制原 metadata/assessment/body，也不改旧 sanitizer 字节。

## 12. G3 实施边界

G3A 先修复共享 SSE framing 与有界 pull/apply 栅栏，并添加原生 Event-column
幂等键的只读精确坐标查询；G3B 再连接原生准入、标准 HTTP 与可靠桥接。
独立审查及门禁按卡记录；G3A 不代表 HTTP 或 CopilotKit 互操作已验收。
采用第10节允许的原生准入后观察路线：实际已接受的公共 Run ID 由适配器
交给官方 HttpAgent。标准 POST 观察该操作，不再提交执行。不能改写任意调用方
runId、根据 command UUID 猜 Event UUID，或把未处理的续接 anchor 猜成公共后继。
当前不新增公共 ID ledger，不放宽原 Client Session/Host/Controller 权限。

G3A已审查的入口约束：逐记录pull在官方归并应用及通知完成后才继续；内部栅栏
使用对象身份，位于enforce/chunk/verify之后，不进入wire/公开回调/历史。RAW、
CUSTOM、未知事件丢弃及一条chunk展开多个事件均不依赖“必有状态变更”来确认。
明确初始messages/state只用于可信上下文；不授予业务权限。记录/assembly按UTF-8
字节计量，行缓冲按需增长。主动abort丢弃不完整记录并取消自有reader；调用方
自有永不完成IO只能请求清理。legacy消费边界保留有效raw event_type/稀疏值，
只预检自身消费字段；完整新标准事件仍由官方schema管线校验。损坏记录不重试，
真实runtime接住错误、保留已确认cursor/controller lease并显示unavailable。
精确原生幂等键只读查询返回实际Event坐标，不把command UUID当Event UUID。
规格/质量审查和独立检查通过；这些证据不代表实际HttpAgent请求已经背压，
也不替代G3B的真实输入到Worker、HTTP观察及公共Run切片门禁。

## 13. G3B 实际 HTTP 适配（审查候选，未激活）

这里固定第10节的原生准入后观察路线，不声称任意客户端随机runId可直接准入。
现有会话以受控原生MESSAGE接收实际用户文本；仅CONVERSATION的awaiting_turn
状态支持该追加路径，不把one_shot终态或初始开放Turn放宽为可追加。新建Task
使用既有原子Task+Surface+RUN：可选单条纯文本message必须匹配原生校验后的
prompt，作为RUN.input元数据保留；模型仍读取原生Task目标，不能重复追加。
旧state-only输入和command收据字段保持原形。附件、workspace、MCP、任意
初始工具等受限项没有借此放宽；Host既有复杂准入轨道继续按原权限使用。

- `/prepare`提交一次原生意图；`/prepared`只读取原始操作，不重新准入。精确
  Event-column key解析实际Event坐标；不把command UUID当作Event UUID。
  只有物化到实际continuation anchor之后的派生状态才返回公共协议Run ID。
  waiting_children或已忽略的迟到意图不构造假后继。
- 标准POST只观察已准入操作；输入与原始已接受输入语义一致，公共runId来自
  实际绑定。对象键顺序无意义；数组有序，bool与number区分，数值1与1.0等价。
  缺省protocolVersion在捕获前设1.0；显式矛盾版本拒绝，不静默改写。
- 首条输入准入前尚无Native Task UUID，SDK的fresh-only `attachPrepared`显式
  安装同源BFF返回的原始prepared收据，再调用真实HttpAgent；它不产生UUID、
  不发送准入，也不是执行授权。旧的pending/unknown操作不能被此方法覆盖。
- BFF原始operation locator与native accepted Event key分别来自原始受保护收据。
  server helper在新实例中可只读恢复，不要求进程内先调用过admit。Native
  凭据及fence留在server context；浏览器只使用固定同源路径。已校验的Native
  origin和定位参数被捕获，不因外部配置对象后来变更而转发凭据到其他地址。
- 私有prepared输入和input-bearing POST绑定原始ClientSession；MESSAGE采用
  server-auth派生的private preparation marker，初始轨道复用原生client marker。
  不从浏览器state/forwardedProps授予身份。获准查看公开结果的另一个Session
  不因此取得原始Readable/context。只读观察不要求controller/fence或最新UI
  revision；新的输入动作仍要求当前原生权限、Controller和修订。

新profile的可靠GET采用独立的canonical-only读取绑定：同一原生proof验证当前
Host/Task/Run、不可变anchor及完整profile scope，lane固定原Run anchor Segment。
不修改原run.stream_admission，也不借观察准入transient_v2。新profile不读取
未经公开分类的临时候选正文；旧profile的draft/reset及wire字节保持。标准正文
仍为TEXT_MESSAGE_CONTENT，大canonical事件经共享有界chunk桥接后才进入官方
enforce/chunk/verify/apply。transport通知不混入业务CUSTOM。

原生检查点可能保留上一切片terminal；新观察以已验证的公共Run及起始序列
判断结束，忽略旧terminal，在自己的terminal处停止，不跨入同Page后继Run。
RUN_ERROR没有runId，其归属由该已验证切片确定。标准观察失败转为安全
RUN_ERROR及EOF，不把观察错误写成业务失败；原生投递结果读取也必须组合。

实际HttpAgent应用沿用官方归并：所有注册/传入subscriber之前处理私有身份
栅栏，预检patch，等待应用及通知，再确认cursor。clone保留公共订阅和middleware，
私有失败/中止/栅栏状态重新初始化。官方finalize不自动等待的边界由适配器
显式等待；terminal应用和final hooks完成后才确认终态cursor，并清理原始reader。
中止、毒帧、通知失败不确认未应用数据；clean EOF没有terminal不得冒充完成。
正常可靠断线保留有限分片和签名cursor，在同一官方管线只读接续；reset的null
cursor同样等待持久化。整段重播与活动Run冲突时明确失败，不静默重复正文。
从原始收据重建全新只读观察仍不产生准入；G4/G5/G7须继续验证UI恢复及零效果。

`ZEBRA_AGUI_STANDARD_PROFILES_ENABLED`默认false。API和Worker使用同一显式
projector/state工厂；启用配置组合两旧四新共六个有界版本。该候选不启用生产
profile，不发布registry或替换Trench包；完整frontend tool/resume仍属G5。
