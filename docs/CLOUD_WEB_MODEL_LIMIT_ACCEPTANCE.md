# Cloud 原生搜索模型参数类型修复验收

日期：2026-10-15。任务 WEB-MODEL-LIMIT-01，基线 e9cd0ecc。

## 根因和最小修复

上一轮真实搜索的候选 Run 出现两次 `limit="5"`，原 Policy 正确拒绝字符串，
模型随后用整数重试，造成额外往返。不是本地解析器把整数变成字符串：
web.search 工具契约及实际 Provider HTTP schema 均为 integer/minimum1/maximum5；
SSE 聚合保留模型参数文本，json.loads 保留 JSON 字符串类型。

当前兼容模型通道使用非 strict 工具调用，模型仍可能返回不符合 schema 的参数。
不切换 beta/strict 端点，也不通过降低高思考设置、去掉 schema 或放松领域校验解决。

复用既有 LocalToolGateway.resolve_model_tool_calls：MCP 解析后，仅对原生
web.search、没有既有 provider presentation、limit 为精确 ASCII 字符串
"1".."5" 的调用转换为整数，再经过原 Policy、权限和工具输入验证。
query、调用 ID、Provider 调用 ID、时间戳不变。其他工具、整数输入和默认值不变；
空白、符号、前导零、小数、指数、Unicode 数字、布尔、越界等均不转换。

调用原有 provider_tool_name/provider_arguments 字段保留模型原始参数，后续请求
serialize_message 继续发送原始工具调用，避免改写 Provider 对话历史。
共享 policy_decision_payload 在同一个既有 Policy 事实中记录这两个原始字段；
ToolCallProposed 继续记执行用的规范参数。顺序和并行路径复用该函数，不新增事件、
数据库查询或写入次数。转换增加的原始参数字段会使相应事实的字节数略增。

仅改两个生产文件：agent_runtime/harness.py（479行）与
agent_core/harness/orchestration_events.py。无新依赖、Port、通用强制转换器或缓存。
直接输入 parser/execute/Policy 仍拒绝字符串；这个兼容处理仅在模型调用解析边界。
现有 STOP/截止、新鲜身份、网络权限/SSRF 规则不变。

## 固定输入因果验证

新增35项检查，初始10个合法字符串转换检查为红，生产改动后通过；另有原始审计
断言先失败再通过。覆盖两种 Web pipeline、五种合法拼写、20种非法/歧义输入、
直接调用边界、其他工具、既有 presentation、原始 Provider continuation、Policy
审计及缺失网络权限/空 query/额外字段仍拒绝。

使用真实 WorkerToolGateway、HarnessLoop、原 LocalPolicyEngine 和固定模型回执：

| 同一模型输入 `limit="5"` | 原解析路径 | 修复路径 |
| --- | ---: | ---: |
| 模型交互轮数 |3|2|
| 类型失败 |1|0|
| 实际成功工具执行 |1|1|

没有调用外部模型或网络；这证明只要发生这一精确类型失配，可以省掉一次纠正轮，
不代表任意问题都少一轮。执行参数为整数5，Policy审计和 Provider continuation
仍保留字符串"5"。权限不足或其他非法参数不会因规范化而放行。

最终169项相关检查通过（18.69s），包括工具解析/顺序并行批次、MCP、搜索、原生
取消、两路网络、延迟沙箱、导入边界、OpenAI兼容适配器。Ruff排除私有.artifacts、
mypy1282源文件、eval30及文件大小门通过。没有扩修旧fixture、DNS或无关解析问题；
没有运行全量pytest，不声称字面 make check 全部通过。

## 新真实页面配对

A1后B1，同一公开PG18/Redis8发布日期、各两项新特性及官方链接问题，Flash/high。
两次 canonical completed，全部4个模型回执 enabled/high、retry0，transient_v2。
实际执行各3次search+3次fetch，PG官方公告与RedisGA博客均成功抓取，页面最终
显示日期、特性和这两条官方链接；无订阅读取或业务写入工具。

| 指标 | A1原解析路径 | B1修复路径 |
| --- | ---: | ---: |
| Host创建→完成 |30.325s|27.471s|
| 点击→首段公开过程文字 |4.853s|4.994s|
| 两家官方链接首次可见 |28.851s|27.330s|
| Worker开始→实际模型HTTP |1.218s|1.213s|
| 主模型轮数 / 实际工具 |4 /6|4 /6|
| 工具失败 / 新沙箱实例 |0 /0|0 /0|
| 网络峰值并行 |2|2|
| Worker显式cursor.execute |3141|3120|
| Task I/O新连接 |692|671|
| 启动SQL /连接 |415 /66|415 /66|
| 新鲜scalar状态读取 |235|214|
| 模型HTTP区间并集 |9.948s|9.153s|
| 网络区间并集 |7.934s|5.856s|
| 首工具事件→handler |259ms|250ms|

安全 trace 仅记录实际发出的 limit schema 和返回 limit 类型，不记录提示词、完整
Provider正文或私有思考。两侧 schema 都为 integer1..5、strict=false；两侧本次
三次搜索均返回整数5，未再次触发旧失配。因此本次端到端总耗时减少2.854s（9.4%）
不能归因于类型修复；搜索查询/后续抓取页面与网络/模型耗时也不同。

首段过程文字反而慢141ms；官方链接早1.521s，不冒充完整答案首字或稳定分布。
本次 Worker SQL仅少21（0.67%），不是新增SQL优化，也不能声称整体SQL80%下降。
计数仅同步Worker及传播上下文工具线程的最外层cursor.execute，不含Host/API/
其他Worker或协议隐式语句。50ms新鲜取消检查和连接行为没有降低频率或增加缓存。

A1 Run：2228f44d-64ed-46db-a035-1da5cca56ef5

http://localhost:3000/dashboard/strategy/conv_1792060907340_5f1ccc

B1 Run：b1ebdfb7-634f-446c-8934-1b71dda3097b

http://localhost:3000/dashboard/strategy/conv_1792061147365_5bbb93

只执行这一组新配对，不重复旧Run、不额外请求模型挑选好数据。
本次真实请求证明兼容性与原有边界；类型失配的因果收益由上面的固定输入验证。

## 本地交付与剩余边界

正常 Worker：b373f27d03a8bb0089e66c73be7943b06fec855755b0d4e2c13ea1a2a89f780e，
在原4a1c78ad上仅覆盖这两个生产文件。正常入口、命令、原六Compose恢复且healthy；
42项累计源hash核对。APIc0b8e9dc、Yahoo搜索245b675f及配置/环境指纹不变。
导入/gzip、纯Web零沙箱、两路网络、新鲜scalar读取、启动415SQL/66连接保持。
页面观察器和临时trace撤除，普通页面重新加载同一已完成结果，不调用模型。

代码本地集成至cloud-agent-trench，主checkout原27条无关脏改动保留；不推送、
npm发布或远端部署。私有证据位于.artifacts/web-model-limit-20261015，包含红绿/
静态检查、镜像/源校验、两次新Run的安全schema/类型/模型/工具/SQL/DOM摘要。

本轮修复已知参数纠正损耗，不代表整个性能优化完成。外部检索/模型波动、网络
偶发截止及全研究链路稳定分布仍待独立验证；不在本轮扩大到新Provider、降低思考、
通用参数宽松化、旧测试修复或完整STOP/容量GC验收。
