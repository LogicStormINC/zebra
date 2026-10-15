# Cloud 网络控制读取精简验收

日期：2026-10-15。任务：WEB-CONTROL-READ-01。起点：22f72dd7。

## 结论与最小改动

已完成第二步：活动状态下，每次Cloud网络取消检查从“SET TRANSACTION READ ONLY +
完整Session读取”变为一次新的标量状态SELECT。检查频率、每次新连接、原归属检查和
两秒累计Task I/O预算不变；没有缓存授权或停止状态，没有调低高思考设置。

只有三份生产文件：

- agent-storage/postgres/projections.py 增加 get_session_status。使用原部署namespace +
  Session ID主键条件，仅返回SessionStatus，不取计划/审批/澄清JSON，不增加索引或迁移。
  精确原生get_session才走快路径；subclass或实例/类级读取覆盖继续调用原get_session，
  避免绕过自定义读取/测试钩子的语义。枚举非法、缺行或数据库失败均不使用缓存兜底。
- worker/worker_projection.py 在已配置Worker mutation authority的原生Postgres组合中
  显式注入类型化status reader，复用现有可选回调组合方式，不新增Port/依赖。
- worker/execution_events.py 的require_active_execution仍返回None，并保持原串行锁与
  累计期限；活动状态后仍调用ownership_check。观察到中止状态后继续原完整主投影
  读取/ExecutionInterrupted(session=...)路径，保留新鲜完整Session的错误与返回处理。
  控制状态若在两次读取间改变，以原完整读取和归属检查最终观察到的状态为准。

Context调用read_active_session仍取完整主投影；Local/无reader组合保持原完整读取。
未修改网络50ms等待循环、两路并行、检索策略、checkpoint、Trench/SDK或业务数据。
新语句是参数绑定的固定SELECT；原get_session的只读事务设置没有全局删除。

## 明确的收益口径

“2→1”指最外层cursor.execute的显式SQL语句调用：少一条SET，SELECT次数仍为一次，
新鲜连接仍为一次。协议隐式BEGIN/COMMIT、连接启动设置和后台/API等语句不在计数中。
因此不能将50%解释为数据库服务器全部语句/SELECT查询/连接数下降50%。
终止分支可能多一次标量读取后进入原完整错误路径；优化目标是正常等待的高频路径。

## 固定100次检查：独立真实PostgreSQL

临时web_control_scratch数据库，随机隔离schema，原生Task I/O连接；每次提交前均为
新的主库读取，没有模型或业务数据库迁移。两轮均按full→scalar→scalar→full执行。

| 单组100次检查 | 显式SQL调用 | SET | SELECT | 新连接 | 完整Session反序列化 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原完整读取 |200|100|100|100|100|
| 新标量读取 |100|0|100|100|0|

最终轮保留100个独立连接对象并验证全部关闭；没有跨线程/跨检查复用socket。
第一次耗时full1164/915ms、scalar799/872ms；补连接计数后的第二次full879/1470ms、
scalar1050/1207ms。中位分别约1039.5→835.7ms与1174.4→1128.5ms。
连接/系统负载有明显波动，不能据此宣称稳定19.6%延迟收益。
固定工作量下可确认的是显式语句200→100，以及不再传输/解析完整Session JSON。

## 针对性检查

最初11个用例基线4失败/6通过/1跳过；随后加入原生factory与双TLS组合证明。
最终97项聚焦回归全部通过，无跳过：包括13项本次检查、原Context快照、recorder
append边界、已有Worker/native网络取消、第一步Web两路并行和线程上下文检查。

- 一次控制查询、正确namespace/Session参数、每次新状态、缺行与非法枚举拒绝。
- 覆盖get_session的实例不会被新标量方法绕过。
- 活动控制读取不访问完整投影，且每次执行ownership检查；LeaseLostError原样传播。
- cancelled/suspended/failed/completed继续原新鲜完整Session异常路径。
- Local与Context完整读取保持；继承deadline不延长，Cloud factory确实注入并保持≤2s预算。
- 独立PG提交状态后下次连接立刻读到；不同namespace不可见。
- ACCESS EXCLUSIVE阻塞下0.2s预算及时退出，接受原生QueryCanceled/LockNotAvailable或
  客户端TimeoutError；不以超时后的结果作为成功。释放锁后正常读取恢复。
- 同时启动两条真实TLS滴流请求，PG提交cancelled后，两路均在2s内携带完整新鲜
  cancelled Session退出；原生子进程均已回收、管道关闭，peer观察到断开。

未借此宣称完整Task STOP、PG epoch/lease takeover或容量/GC门通过；这些仍有独立验收。
没有修复旧fixture。make check已跑，文件门通过，但Ruff扫描未跟踪.artifacts诊断代码
失败；排除该目录后的仓库Ruff、mypy1278源文件、eval30项通过，不将原make命令标绿。

## 真实页面前后对照

两个全新会话，沿用前次公开发布信息核对问题，正常登录的Trench入口；均选择Flash
executor、高思考，回执enabled/high、主模型retry0，canonical completed、transient_v2、
各一个sandbox。两侧都已包含第一步两路并行。样本少且模型工具路径不固定。

| 指标 | 优化前 A1 | 优化后 B1 |
| --- | ---: | ---: |
| Host创建→完成 |46.166s|34.971s|
| 点击→首段公开正文 |4.826s|4.654s|
| 两家官方链接首次可见 |45.345s|33.771s|
| 主模型轮数 / 工具启动 |6 /9|4 /6|
| 失败终态事件 |2|0|
| Worker显式SQL调用 |5173|3231|
| 控制相关完整/标量SELECT |327 /0|2 /272|
| 控制相关SET |327|2|
| 启动显式SQL / Task I/O连接 |415 /66|415 /66|
| 真实网络峰值并发 |2|2|

新版272次活动轮询各省一条SET；剩余两次完整读取属于Context，符合保留完整快照
的边界。不能把整轮少1942次调用或快11.2s全部算作此改动收益：模型少2轮、工具少3次，
网络/搜索结果和失败路径也不同。首段正文是过程说明，官方链接可见也不是完整语义
验收。两侧有成功官方网页抓取回执，所有失败样本保留，未筛选重跑或重放旧Run。

A1 Run286cdb94-39f9-4d6c-a2a4-7d2b68a247a5：
http://localhost:3000/dashboard/strategy/conv_1792053680531_53756d

B1 Run864c9432-3903-47f7-9c96-f24f0ce62f56：
http://localhost:3000/dashboard/strategy/conv_1792053805129_0dcd19

SQL观测限于同步Worker范围及标记工具线程的最外层cursor.execute，不含范围外心跳、
API/Host/其他Worker，不等于服务器SQL总量；临时诊断会增加开销。完整系统SQL80%与
稳定p50/p95未在本片验收。后续重点仍是搜索命中/正文截断和重复checkpoint工作。

## 本地状态与复核

正常Worker镜像76937731e94ebf88f145cf3eb0e54a4010af8340e6d28173bb96ee5652b0d51e，
基于原b9f1e732仅覆盖上述三份生产文件；APIc0b8e9dc不变。原六份Compose、entrypoint、
command与两个healthy状态核对通过，30个既有/本次源文件容器hash一致。
临时trace入口和浏览器观察器撤除；原v2、高思考、两路并行、懒加载与启动收益保留。
未推送、npm发布或远端部署。独立测试容器与其临时卷在验收后移除，不涉及业务库。

私有证据：.artifacts/web-control-read-20261015，含red/focused/native/static日志、
两轮固定控制检查、DOM/canonical/Worker安全摘录、profile、镜像和30源hash。
fixed_control.py可重测等量检查；verify.py复核两次新Run与正常服务状态，原始失败
日志保留。连接配置不写入本文或提交。
