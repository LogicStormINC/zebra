# Cloud 事件进度同步去重验收

日期：2026-10-15。任务 WEB-PROGRESS-CATCHUP-01，基线580a804a。

## 根因与改动边界

前一组真实搜索 Worker 执行约24.9–27.6秒，模型HTTP并集约9.2–9.9秒，
网络并集约5.9–7.9秒；两者之外仍有较多平台处理。这些区间有嵌套与并行，
不能直接把SQL/连接/recorder各项耗时相加，当作完整墙钟分解。

追踪发现 WorkerProgressRecovery.persist_with 每次成功 sink(event) 后调用
self.catch_up()，紧接着的 repair_commentary(self,sink) 第一行再次 catch_up()。
两者之间没有任何工作。前一组两次搜索各有44次这样的重复；每次即便进度已追平，
仍创建一条新Task I/O连接，执行事务设置、最新Run选择及完整有界Run元数据查询。

按最小方案只删除 progress_recovery.py 这个重复调用，并更新邻近说明。
共享 repair_commentary 保留完整逻辑：先新鲜catch_up，再决定是否有待恢复草稿、
是否terminal；需要输出草稿时仍逐块写入并追平。普通persist仍在写入前做新鲜
catch_up/Run身份/Attempt/权限校验，写入后由repair重新读取新鲜Run再处理状态。

不增加“已同步”标志、缓存、批量Port或新依赖。原publication锁、累积两秒I/O预算、
写入原子fence/事件/投影、checkpoint CAS与未知提交恢复不变。提交后checkpoint失败
仍不能授权重放canonical append。50ms取消轮询频率、身份读取和STOP路径不变。
该优化复用所有persist调用者的共享入口，不在各工具或模型调用点加分支。

## 固定状态与安全验证

新增实际SQLite checkpoint回归先观察到写入前后highwater读取为[1,2,2]，
修复后为[1,2]；最终canonical事件条数、checkpoint与前沿一致。
另一新增检查在sink成功提交后立即插入替代Run，仍在post-append恢复前因superseded
拒绝，并且只执行一次原sink，不补发内容、不猜测新Run身份。

既有草稿恢复、失联提交、部分chunk、租约丢失、取消后待发草稿及原生PostgreSQL
checkpoint/fence验证沿用；没有更改fixture、错误边界或断言以迁就实现。

## 无模型PostgreSQL固定序列

专有临时PostgreSQL容器、每样本独立namespace/Task，实际原子Worker append与进度
适配器。原路径使用git580a804a的完整进度模块，新路径使用当前模块；其余相同。
每样本连续24个相同标题事件，ABBA顺序、两次/路径。没有模型、网络或业务库操作。
真实最新Run读取、任务I/O连接与显式客户端SQL均计数，最终进度状态及前沿逐样本验证。

| 指标（24事件） | 原路径 | 去重路径 |
| --- | ---: | ---: |
| 最新Run读取 |72|48|
| 显式SQL |792|720|
| 新PostgreSQL连接 |144|120|
| 墙钟中位数 |3598.540ms|3047.255ms|
| 单样本耗时范围 |3370–3827ms|2970–3124ms|
| 最终task前沿 |27|27|

每事件减少3条SQL、1条新连接；该序列SQL减少9.1%、连接减少16.7%，中位墙钟
少551ms（15.3%）。这是事件持久化子链路的小样本测量，不能外推为全部Agent耗时
或全部数据库SQL下降相同比例。没有清空OS/数据库缓存，不冒充整机冷启动。


## 本轮针对性验证的明确终点

125项相关检查通过，涉及Worker进度、草稿恢复、真实PG进度/fence、SQLite CAS、
事件/输出、暂态流组合、控制状态和上一轮模型参数修复。另启用专有临时PG完成
两个原生定时发布SQL/commit截止检查，均通过，合计127项唯一通过。

保留1项已有组合测试失败：test_real_cloud_loop_wires_mode_factory_and_binding_without_memory
提供的Cloud设置没有Redis publication，配置初始化即抛错，尚未进入本轮persist路径。
在进程内换回580a804a的完整persist_with实现后，该测试仍以同一错误失败；没有修
fixture、修改Cloud要求或扩大实现。1项固定要求web_control_scratch端点的既有原生
TLS控制检查仍skip；上面两个publication检查已用其原fixture允许的专有端点执行。

Ruff排除私有.artifacts、mypy1282源文件、eval30、文件大小门通过。
没有运行全量pytest，不声称全部测试或字面make check通过。

## 一组新真实搜索页面

A1后B1，同一公开PG18/Redis8问题，Flash/high，两侧全部3个模型回执enabled/high、
retry0，transient_v2，canonical completed。均实际执行2次search+2次fetch，两个
官方原文HTTP200，页面最终列出日期、新特性及来源。没有重放旧Run或为挑好结果重复
模型请求。除安全trace外，页面计时仅观察渲染，不添加模型调用。

| 指标 | A1原路径 | B1去重 |
| --- | ---: | ---: |
| Host创建→完成 |21.735s|20.711s|
| Worker开始→结束 |18.957s|18.190s|
| 点击→首段公开过程文字 |5.045s|5.129s|
| 两家官方链接首次可见 |20.244s|20.653s|
| Worker→实际模型HTTP |1.349s|1.328s|
| 模型轮数 /工具成功 |3 /4|3 /4|
| 工具失败 /新沙箱 |0 /0|0 /0|
| 网络峰值并行 |2|2|
| canonical recorder append |37|37|
| catch_up次数 |97|66|
| catch_up累积方法耗时 |2855ms|2364ms|
| Worker显式SQL |2324|2204|
| Task I/O新连接 |499|441|
| 启动SQL /连接 |415 /66|412 /65|
| 新鲜scalar状态读取 |159|132|
| 模型HTTP区间并集 |7.207s|7.102s|
| 网络区间并集 |4.322s|3.930s|

SQL按指纹对账，只有四类计数变化：事务设置、latest Run选择、Run header查询
各少31条，scalar状态读取少27条。前93条正好对应31次重复catch_up删除，是本轮
实现直接减少的固定调用；另外27条来自本次网络等待更短、在相同50ms频率下少轮询。
连接差也精确为31+27=58。除此之外全部SQL指纹计数相同。

本轮观察Worker SQL减少120（5.16%），其中直接归因去重的93条约占原Worker SQL的
4.00%；不能把全部5.16%当成固定软件收益，也不是全系统SQL减少。计数仅同步Worker
与传播上下文工具线程的最外层显式cursor.execute，不含Host/API/其他Worker、协议
隐式语句或数据库触发器。启动少3条SQL/1连接是同一去重在首次模型前已生效。

总耗时少1.024s（4.71%），网络和模型本身也有波动；catch_up方法累计少491ms与
固定序列方向一致，不能把总耗时差全部归因于去重。首段文字反而晚84ms、官方链接
晚409ms，因此没有证明首段/最终正文提前，不能宣称稳定3秒或整体性能目标完成。
首段指标是公开过程说明，不是完整答案首字；官方链接指标也不是最终提交时刻。

A1 Run870e8660-7a6a-4512-a0d0-6f0d29177500：

http://localhost:3000/dashboard/strategy/conv_1792061757812_0e60c5

B1 Run98b1e953-350f-4481-85fe-3d695fba3c13：

http://localhost:3000/dashboard/strategy/conv_1792061867298_846695

## 正常本地交付

正常Worker5d0862026041d53dbb4510e518ffdbc01cebad8f2db71528be47815d2d625890，
仅在原b373f27d覆盖progress_recovery.py。原六Compose、正常Worker入口/命令恢复且
healthy；43项累计源hash核对。APIc0b8e9dc、搜索245b675f/配置/环境指纹不变。
高思考/v2、模型limit修复、子进程导入/gzip、两路Web/零沙箱、新鲜控制/截止保持。

普通页面重新加载同一完成结果，观察器/临时trace撤除；专有临时PG容器、其匿名卷
和临时DSN文件清理。私有证据.artifacts/web-progress-catchup-20261015保留红绿、
固定ABBA、基线失败复现、真实Run/工具/SQL/页面摘要及正常服务/源校验。

代码本地集成cloud-agent-trench，主checkout原27条无关脏改动保留，不推送、npm发布
或远端部署。完整首正文分布、外部网络/模型波动及全系统SQL目标仍待后续验证。
下一步应继续观察尚存的首次模型前约3.5秒和事件边界成本；不把本次少量删除扩为
授权缓存、降低思考、重写测试基础设施或无边界批处理。
