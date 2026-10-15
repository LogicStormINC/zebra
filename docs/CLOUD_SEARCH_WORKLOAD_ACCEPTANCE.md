# Cloud Agent：真实网络搜索配对验收

日期：2026-10-15。任务：SEARCH-WORKLOAD-PAIR-01。记录起点：当前已验收源码 c346e07a。

## 结论与边界

复杂搜索场景尚不能判定为性能优化完成。最近 Context 优化确实减少启动固定工作，
但本次真实页面实验没有证明整轮任务提速，也没有证明首段有效答案更快。
优化版两次完成耗时 63.286 / 66.832 秒；基线三次为 62.491 / 46.603 / 41.926 秒。
这些差异同时受模型规划、搜索命中、网络、工具失败及进程/网页缓存影响，
不能将原始差异解释成这两处源码修改造成的退化或提升。

启动 cursor.execute 固定从 531 降至 415（减少 116，21.85%），Task I/O 新连接
从 76 降至 66（减少 10，13.16%）。整轮仍观察到 3,713–5,467 次 Worker 范围的
cursor.execute 调用。此前纯回复测试不足以代表联网任务，此处明确保留该限制。
这次比较的是最近 Context 切片之前/之后，**两侧均为 v2**；不是 v1/v2 总体收益验收。

## 固定问题与执行条件

通过已登录 Chrome 的 Trench 助手正常发送以下相同问题；每次为新会话、新 Run：

> 请联网搜索并核对：PostgreSQL 18 和 Redis 8 的正式发布日期分别是什么？各列两项主要新特性，并附官方来源链接。中文回答，约300字。只查公开网页，不读取订阅，不修改业务数据。

- Host 请求均为 deepseek-v4-flash-executor-v1，reasoning_effort=high；
  全部主模型回执均为 thinking_mode=enabled / high，retry_count=0。
- 五次 Host 完成、canonical turn_completed 和 transient_v2 均核对通过。
- 每次实际创建一个 sandbox；未重放任何历史 Run，未读取业务订阅或改写业务数据。
  artifacts.read 为模型读取本轮网页工具保存的长文本片段。
- A 为旧 Worker e76adcdc54c51b5d8b3692b13f8af52e81dcb3d075d328d23223bb26e671e93a；
  B 为当前 Worker 376b20ddb9598f5f577c59493653b6ace8bfc67e0c64adb11d08ca8c12b37fc7。
  两镜像业务源码仅 context_materialization.py / execution_events.py 不同。
  API 固定 c0b8e9dce87a9cdc2d4a10d202dc012bc72d3e081dcb8494bf1e55175bacf3ab。
- 顺序 A1→B1→B2→A2→A3。A1 计时器初始化失败，保留全部后端/工具/SQL 结果，
  DOM 时间缺失；A3 仅补足第二个可用基线 DOM 样本，未替换或删除 A1。
- 切换版本会重建 Worker；B1/B2 同一进程，A2/A3 同一进程。
  没有清除搜索、网络或模型缓存，因此不构成严格冷/热启动实验。
- 两侧使用相同临时诊断钩子，正常业务源码未修改。诊断同步日志和调用栈会引入开销；
  以下是带诊断的实际请求，不能当作无诊断生产 p50/p95。

## 全部样本

完成耗时为 Host created_at_ms→completed_at_ms；DOM 时间起点为实际点击发送。
“官方链接”仅表示页面正文首次同时包含两家官方来源，不等于完整答案已经校验或提交。

| 样本 | 完成秒 | 首段公开正文秒 | 两家官方链接可见秒 | 主模型轮数 | 工具总数 / 失败 | 观察到的 Worker SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 基线 | 62.491 | 缺失 | 缺失 | 5 | 8 / 0 | 4,728 |
| B1 优化 | 63.286 | 4.938 | 61.074 | 6 | 10 / 1 | 5,339 |
| B2 优化 | 66.832 | 5.360 | 64.170 | 6 | 10 / 1 | 5,467 |
| A2 基线 | 46.603 | 4.878 | 45.249 | 4 | 8 / 1 | 4,229 |
| A3 基线补充 | 41.926 | 4.409 | 37.744 | 4 | 6 / 0 | 3,713 |

首段通常是“I'll search …”过程说明；B1 首次捕获仅为“I”片段。
因此 4–5 秒的首段过程说明不能当成用户问题已得到回答。
实际带来源答案出现于约 38–64 秒。页面终稿均明显超过“约300字”，本次也未做逐句
语义正确性审核；成功完成和有效网页回执不代表输出质量要求全部通过。

| 样本 | web.search | web.fetch | artifacts.read | 成功官方网页抓取 |
| --- | ---: | ---: | ---: | ---: |
| A1 | 3 | 5 | 0 | 3 |
| B1 | 3 | 6 | 1 | 5 |
| B2 | 5 | 5 | 0 | 3 |
| A2 | 4 | 3 | 1 | 2 |
| A3 | 3 | 2 | 1 | 2 |

工具回执 route=web_gateway，搜索 provider=searxng；此为当前实际生效的 Web 工具路径，
不要与 transient_v2 存储/传输协议混为一谈。官方抓取均有 status_code=200 与原 URL；
包括 PostgreSQL 官方发布新闻或 release-18 文档，以及 Redis 官方 redis-8-ga 博客。
不是用模型“我已搜索”的文字推断发生了工具调用。
B1/B2/A2 各有一次 web.fetch 失败，reason=http_error；工具失败回执未保留具体 HTTP
状态码，故不猜测 404/500，也未将其误算为 Provider 重试。五次均通过后续路径完成。

Run 与可复查页面：

| 样本 | Run | 页面 |
| --- | --- | --- |
| A1 | 23494ad6-ab0c-4b06-9bd0-eba56128026c | http://localhost:3000/dashboard/strategy/conv_1792048767402_f28eb9 |
| B1 | dd3b65f2-6d87-49ad-b042-edce8b2faaa0 | http://localhost:3000/dashboard/strategy/conv_1792049132537_e694f4 |
| B2 | e9b24d30-bd83-4cb4-a526-eb7285aeaa19 | http://localhost:3000/dashboard/strategy/conv_1792049311267_75b58e |
| A2 | f62d4789-9ebe-48da-9e2e-53bc99c5eda8 | http://localhost:3000/dashboard/strategy/conv_1792049689558_bf7b5f |
| A3 | 44ad6a3e-49fe-4a23-999a-1520153555e8 | http://localhost:3000/dashboard/strategy/conv_1792049782409_f3bb6f |

## 时间分解

| 样本 | Worker→实际 Provider HTTP 毫秒 | Context 毫秒 | 启动 SQL / 连接 | 主模型 HTTP 累计秒 | 工具 handler 累计秒 | 控制投影 SELECT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | 1,548 | 576 | 531 / 76 | 19.171 | 23.274 | 445 |
| B1 | 1,581 | 419 | 415 / 66 | 18.400 | 22.159 | 429 |
| B2 | 1,519 | 440 | 415 / 66 | 19.909 | 24.631 | 482 |
| A2 | 1,426 | 575 | 531 / 76 | 10.946 | 16.170 | 309 |
| A3 | 1,326 | 484 | 531 / 76 | 10.354 | 16.479 | 319 |

有 DOM 计时的点击→实际 Provider HTTP 为 B1 4,042、B2 4,135、A2 3,609、A3 3,244ms。
本次也没有证明页面启动时间的稳定改善。主模型轮数只统计 canonical model_request_started；
标题等辅助模型不计入主模型轮数和流式 HTTP 时段，不能称“全部 Provider 请求数”。
工具 handler 包括实际工具传输/处理和期间控制检查，不等于纯网络传输时间。
阶段内部可能嵌套，不把这些数字与 SQL 执行时间直接叠加。

## 暴露出的真实成本与下一步最小切片

1. **同轮 Web 工具串行。** 五组 handler 区间并集等于总和，没有观察到重叠。
   ToolContract.parallel_safe 默认为 False；web_search_contract 与 web_fetch_contract
   均未覆盖它。registry.parallel_safe_names 只收集显式允许的工具，Worker 即使配置
   max_parallel_tool_calls=3，ConcurrentToolBatch.can_execute 仍拒绝这些批次。
   下一片先审计共享 transport、sandbox、取消回调及限流的线程安全，再利用现有并发
   框架开放已证明安全的只读工具；保留权限、STOP、身份校验和有界输出。
   不能直接把 22 秒宣称可砍成 11 秒：跨轮依赖和模型规划不会自动并行。
2. **搜索候选与抓取截断造成额外续轮。** 多次初始搜索返回教程/无关页面，随后直接
   抓取官方源；部分长网页日期落在省略段，模型又调用 artifacts.read 或另一网页。
   这由实际回执、模型工具路径和公开过程说明共同支持，但没有证明搜索服务损坏。
   下一片应分别量化查询改写/engine 命中和有界正文的日期/元数据保留，避免固定规则
   替 Agent 决策；用相同可重复工具输入隔离检索效果，再做真实模型配对。
3. **工具等待期间反复读取主投影。** 每轮 309–482 次控制投影 SELECT，另有事务调用；
   不是把 SELECT 与 BEGIN 都算成主投影读取。例：A1 445 次该 SELECT 的 driver 执行
   累计约 658ms，不能据此解释整个一分钟延迟。还需将新连接、取消检查频率与期限
   单独拆开，保持可证明的停止响应上界，而不是直接删除 fresh control/lease 校验。
4. **事实持久化后的 checkpoint/header 推进仍昂贵。** A1 观察到 177 次 run-header
   读取、171 次 progress-head 更新和 128 次 head 读取；它们来自多种 catch-up/advance
   调用，不是同一个 SQL 查询，也不据此宣称死循环。下一片围绕每个已提交事实只做
   必要推进，保留 fenced commit、恢复与正确投影，避免随文本帧重新做重投影。
5. **首次工具到 handler 仍有约 2.1–2.4 秒间隔。** 此间隔从 canonical
   tool_execution_started 到 ToolExecutor handler，混合了首次懒加载、runtime/策略等
   准备，不能全归因于 sandbox 冷启动或 daemon 网络。应先补内部边界再选最小改动。

源码定位：agent-tools/contracts.py、web_search.py、web_gateway.py、registry.py；
agent-core/harness/concurrent_batch.py；worker/execution_context.py、execution_events.py。
本次没有修改这些文件，没有新增缓存、并发或重试策略。

## SQL 观测覆盖与验收未通过项

SQL 是同步 Worker 执行范围与带诊断标签的 ToolExecutor 线程中最外层 psycopg
Cursor/ClientCursor.execute 调用数；没有重复计算内层重载，不记录 SQL 参数/正文。
ThreadPoolExecutor 仅传播诊断 ContextVar，不传播应用权限、deadline 或 work-unit 状态。
计数不包含范围外 heartbeat/background、API/Host/其他 Worker；不等于数据库服务器
pg_stat_statements 总量或完整系统查询数。连接数为 TaskIoConnections._resolve 调用，
代表这一实现的新 Task I/O 连接尝试，不代表整机所有 socket。
真实工具路径不同，因此不能按整轮 raw SQL 求出优化百分比，更不能拿它验证 SQL≥80%
总目标。稳定 p50/p95、并发/冷热分布、STOP 与容量/GC 仍未在本次通过。

## 恢复与证据

已恢复当前正常 Worker376b20dd / APIc0b8e9dc，原六份 Compose、entrypoint、command
逐项比对，两个服务 healthy，26 个已验收源文件的容器 SHA256 一致。
临时 trace launcher 与浏览器计时器已撤除。当前本地服务保留所有已验收优化和高思考设置。
未推送、发布 npm 或远端部署，也没有追加修复旧测试。

私有证据：.artifacts/search-workload-20261015。含所有 page/worker/api/canonical/profile
安全摘录、原始分组指标、失败回执摘要、截图、版本切换与 normal-restored.safe.json。
collect.py / metrics.py 可重新核算已生成新会话的记录，trace 文件按精确 Session 过滤。
文档仅汇总诊断结果，不提交私有日志、浏览器内容、身份或连接配置。
