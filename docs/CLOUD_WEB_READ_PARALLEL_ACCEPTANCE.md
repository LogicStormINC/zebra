# Cloud Web 只读工具两路并行验收

日期：2026-10-15。任务：WEB-READ-PARALLEL-01。起点：4c1ce870。

## 结果

第一步的机制实现和本地激活已完成：同一轮独立的内置 web.search / web.fetch
现在复用现有并发执行器执行，两者合计最多两路。固定输入验证确有收益，真实页面
网络请求峰值从1变为2；尚未证明整轮搜索更快或 SQL 更少。
此前启动固定415次 cursor.execute / 66次 Task I/O连接的收益在四组样本中均保留。
第2步控制查询、第3步检索质量、第4步checkpoint均未在此修改。

## 最小源码变更

- agent-runtime/web_tools.py：只对精确类型 LocalWebGatewayTransport 和
  LocalWebSearchTransport 的注册实例声明 parallel_safe，使用一个每 gateway/attempt
  共享的 BoundedSemaphore(2) 限制两种工具合计并发。显式注入的内置实例、自定义 transport/subclass 均不被
  自动标为安全，未修改公共 ToolContract 的默认值。native Web pipeline v2 未改动。
- agent-core/harness/concurrent_batch.py：每次 submit 单独 copy_context().run，
  保留已有请求/Task I/O/数据库deadline；各线程与父线程的 ContextVar 写入相互隔离。
  现有 Postgres work-unit/connection-scope 按线程验证，拒绝跨线程借用父连接。
  不将一个 Context 实例交给多个线程同时进入。
- 不新增执行器、依赖、Port、配置开关或 Trench/SDK 代码。

调用链已查：LocalToolGateway 是 register_web_tools 唯一生产调用方；它先用 sticky
检查保护取消与归属错误。DeferredRuntime 以现有 RLock 只准备一次实例；Web transport
每次调用使用独立 opener/子进程；Cloud 工具输出捕获有原有锁与独立 Artifact ID。
FencedEffectToolGateway 仅允许只读声明的工具并行，副作用仍走 fenced dispatch。
Policy 在提交线程前逐项判定，混入非安全工具仍走原串行路径。
canonical 终态与模型工具消息按原 provider 顺序收集、持久化，不由网络完成顺序决定。

两路上限是本 attempt 的网络 handler 上限，不是整个 Worker/集群的限流器；现有
max_parallel_tool_calls=3 未降低，其他已安全 Host/Client 工具的并发行为保持原配置。
超过两项的 Web 批次排队执行，不因超额直接拒绝整个任务。取消后的排队调用进入
内置 transport 时仍执行 sticky 检查，不能启动新网络操作或返回停止后的结果。
未改变50ms等待轮询、每次新鲜控制/身份校验、SSRF/重定向/TLS或输出字节上限。

## 针对性验证

最初5项检查，基线3失败/2通过，改动后5通过；最终补两项显式注入检查，共7项通过：

- 内置 search/fetch 实际重叠，四个混合请求共用两路，结果与 call ID 对应。
- 自定义 fetch/search subclass 保持非 parallel_safe，写操作没有被开放。
- 同时停止两个请求，保留原取消异常，排队请求不能开始原生网络操作。
- 每个线程继承请求标识和两种deadline，线程内修改相互隔离，父线程连接不可借用。

最终聚焦回归111通过、2跳过、1未选：包括既有并发策略/顺序/限制、原生TLS取消和子进程
回收、停止后输出拒绝、Web transport、工具校验、DeferredRuntime及连接scope。
未选为已有 native_deadline 用例，未借此声称完整原生数据库期限/全局STOP验收。
没有修复旧fixture或扩展到无关测试。

make check 已执行：文件大小门通过；Ruff扫描未跟踪.artifacts诊断文件时报错，
未修改这些文件来消除告警。单独排除.artifacts后仓库Ruff通过；mypy1278源文件通过；
eval30/30通过。完整 make check 命令本身不标为通过。

## 固定输入收益

在旧/新业务镜像分别执行同一生产 gateway/orchestrator，四个固定 web.fetch 输入，
每个网络适配调用以300ms受控等待替代，三次重复；Docker禁用网络，不调用模型。

| 版本 | 三次耗时毫秒 | 中位毫秒 | 实际峰值并发 |
| --- | --- | ---: | ---: |
| 旧版 | 1222.7 /1209.9 /1211.2 |1211.2|1|
| 首次候选 |616.4 /608.1 /608.5|608.5|2|
| 最终注入保护版 |617.2 /610.2 /607.4|610.2|2|

最终固定工作量中位耗时减少49.62%（首次候选49.76%）。该数字只适用于此受控等待，不能作为真实网络、
整体页面或数据库收益。两侧均执行四次工具，结果正常完成。

## 真实页面 ABBA 对照

问题沿用 [前次网络搜索验收](CLOUD_SEARCH_WORKLOAD_ACCEPTANCE.md)，要求联网核对
PostgreSQL18/Redis8正式发布日期与特性，附官方来源。四个新会话，顺序A1→B1→B2→A2，
没有重放历史Run。Host选择均 Flash executor / high，主模型回执均enabled/high、retry0；
均canonical completed、transient_v2、一个sandbox。A为当前优化前376b20dd，B为本次
两文件候选；不是v1/v2对比。各次缓存/模型规划/网络未固定，不构成稳定p50/p95实验。

| 样本 | Host完成秒 | 首段正文秒 | 两家官方链接秒 | 主模型轮数 | 工具启动 / 失败终态事件 | 网络峰值 | Worker SQL调用 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 |55.102|5.223|53.846|6|8 /3|1|5127|
| B1 |64.294|4.806|62.576|5|12 /0|2|6052|
| B2 |62.453|5.199|59.953|8|10 /4|2|6449|
| A2 |64.937|4.461|63.366|6|11 /1|1|5667|

首段多为过程说明；官方链接可见也不是完整答案最终提交。真实请求保留全部失败：
A1有2次invalid_tool_arguments与1次http_error；B2有同类参数错误2次、http_error1次、
另1个repeated_tool_call观察事件；重复拒绝事件不代表再次实际执行同一工具。
工具数量按canonical启动事件，实际ToolExecutor handler数量也核对一致；失败终态
计数包含该重复拒绝，不能直接解释为4个网络失败。所有样本都有成功官方网页抓取
回执和页面来源链接，不仅是模型自述。答案字数/逐句语义未做完整质量验收。

| 样本 | 网络调用区间并集秒 | 主模型HTTP累计秒 | 控制投影SELECT | 启动SQL / Task I/O连接 |
| --- | ---: | ---: | ---: | ---: |
| A1 |18.689|15.022|370|415 /66|
| B1 |21.353|18.667|675|415 /66|
| B2 |15.605|19.541|472|415 /66|
| A2 |23.518|19.458|470|415 /66|

网络区间围绕真实_native_network_call，位于两路信号量内；按开始/结束扫描计算并集
与峰值，不把包含排队的ToolExecutor handler重叠误当成实际网络并行。
同一信号量内的取消/控制检查也包含在该区间，因此不是纯远端处理或传输时间。
四组主模型HTTP均为主要流式调用，标题等辅助请求不计其中。

整轮没有稳定改善，SQL也没有减少。模型/工具路径不同，不能用原始差值认定源码
造成了整体退化或改善；也不能将并行区间之和减并集直接宣称为可兑现的页面节省。
控制SQL仍随每个网络等待累积，并行会同时触发检查，下一片须专门量化和精简。
本片只接受并行机制、受控输入收益及启动固定成本保留，未接受整轮性能目标。

Run：A1 b45a78d8-31eb-4ae2-b114-d8a5405cf8fe；
B1 b216d252-3183-4943-92ce-de48a0bf02e9；
B2 30e8ad4d-ded7-440c-ac25-da219dce00cf；
A2 8259ac8e-8108-41c4-8a0c-3b965cfb05e4。
SQL为带相同诊断的Worker执行范围及标记工具线程中最外层cursor.execute调用，
不含范围外heartbeat、API/Host等查询，不代表数据库服务器总量。日志解析按完整
JSON对象恢复并行print拼接，最终记录invalid=0；所有样本保留，未重跑来筛掉异常。

## 本地激活与证据

真实配对使用a18c3fd8候选。最终仅收紧显式注入适配器的并行声明，默认Cloud路径等价；
未重跑真实模型配对，使用新增注入检查与固定输入验证该保护。
正常Worker为b9f1e73289a9f05b80c4c67834c4b7efdbec104c8ab8da8da574612debf5b012，
API仍为c0b8e9dc。恢复原六份Compose、entrypoint与command，两个服务healthy，28个
源文件hash逐项核对；临时trace入口与浏览器观察器已移除。镜像只在旧376b20dd上覆盖
上述两份生产源码，既有v2、高思考、懒加载及身份校验配置保留。回滚源镜像376b20dd
的完整ID与原启动配置保存在私有normal-services.safe.json。

私有证据：.artifacts/web-read-parallel-20261015，含red/focused/static日志、固定输入
结果、四组DOM/canonical/Worker安全摘录、profile、28源hash、镜像与正常入口核对。
verify.py可复核四组终态、高思考、实际网络峰值、启动固定成本和正常服务源码。
未推送、发布npm或远端部署；完整STOP、系统SQL80%、容量/GC与稳定分布仍为独立未过项。


## 后续：WEB-CONTROL-READ-01

第二步已本地实施，详见[控制读取验收](CLOUD_WEB_CONTROL_READ_ACCEPTANCE.md)。
活动轮询从SET+完整Session变为一次标量SELECT，保持50ms轮询/新连接/原归属检查。
固定100检查显式SQL200→100，SELECT/连接仍100；97聚焦通过，真实PG取消能回收
两路TLS子进程。新页面46.166→34.971s、SQL5173→3231，但模型/工具次数不同，
不能归因全部收益。两路峰值及415启动SQL/66连接保留，正常76937731镜像已核对。
