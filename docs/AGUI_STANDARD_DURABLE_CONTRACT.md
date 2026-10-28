# AG-UI 1.0 标准与 Zebra durable 边界合同

状态：G0 合同冻结；不是 1.0 功能上线或兼容性认证。日期：2026-10-28。
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
| 当前 Python | `ag-ui-protocol==0.1.19`，是旧实现依赖，不能因此声称目标 1.0 已实现 |
| JS 候选 | `@ag-ui/{core,client,encoder,proto}` 各 `1.0.3`，registry 核实候选；G0 不安装、不选型、不修改锁文件 |

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

发现合同保留为现有业务 bootstrap envelope 的新增可选字段
`metadata.aguiProfiles`（支持的新 profile ID 数组）。**当前没有这个字段或新
profile 可用性实现**；这不是一个新端点。G2V/G4 必须在现有 bootstrap/discovery
组合处实现并验证旧 DTO 兼容后，才可对外宣布可用。声明仅提示兼容能力，
不授予 namespace、工具、审批或执行权限。

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

本地reader暂采用128个待处理canonical事件（另有1个等待前序通知的active项）
上限，溢出显式拒绝消费并停止订阅，不伪造Run失败或重新执行。该限制也可能
拒绝突发同步录制源；它是有限容量拒绝策略，不是producer背压或无限历史承诺。
G3/G7须在启用profile前验证实际冷恢复、节奏控制和字节/内存预算，不能直接
把未节流的大数组当作无限流。不能强制取消调用者自有IO或永不完成的回调
promise；reader会及时失败并请求cleanup，底层资源中止仍由source owner负责。

G1验收：25项新增、完整SDK199项通过且无跳过；type/package、实际dist的
ESM/CJS消费通过。规格与代码质量审查通过。框架消费者/双浏览器检查通过后，
最终容量guard再经过完整SDK199/type/package复验。新增入口尚未接生产profile，
因此不把这些证据等同于完整1.0生产协议、Trench迁移或吞吐/模型验收。
