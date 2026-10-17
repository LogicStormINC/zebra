# Cloud 启动准入连接复用

2026-10-17，CLOUD-START-ADMISSION-REUSE-01。源码9451985c。
结论：完成一个可归因的百毫秒级准入优化，已更新本地正常API。
真实页面中启动平均缩短378ms，但不能全部归因于这个补丁；首正文没有改善。
保留逐次新鲜授权、高思考、transient_v2、自主工具选择和原网络线路。

## 剩余启动时间实际在哪里

此前“2.3–3.1秒”使用页面Send→model_request_started事件；本次用临时Provider
观察器测实际HTTP调用入口，四次之间保持同一口径，不混用历史事件时间计算百分比。
入口仍含极短的HTTP函数内准备，不是抓包证明首字节已经发到Provider。

| 不重叠的启动区间均值 | A原路径 | B复用路径 |
| --- | ---: | ---: |
| Send→首个Cloud请求进入API |745.7ms|633.1ms|
| 初始化6个API请求的执行区间并集 |887.3ms|660.9ms|
| Worker执行开始→模型HTTP，不含上述API重叠 |469.4ms|439.0ms|
| 请求间隔/领取等未覆盖时间 |395.0ms|386.4ms|
| 启动合计 |2497.5ms|2119.4ms|

首个Cloud请求之前的112.6ms差异不是本次API补丁的直接收益。
请求间隔还可能含调用方、网络和调度，不能都算数据库执行。
没有修改Trench/BFF产品流程，也未把这部分时间伪装成已定位的慢SQL。

六个请求仍为extensions安装列表、runtime capabilities、POST/tasks、Client surface、
AG-UI command、Host binding renew。没有新增组合协议或合并授权边界。
Worker四次初始化均为366条非空非DISCARD cursor.execute、49条DISCARD、33次空
检查，共448次显式调用；TaskIO物理建连5次，建连23–28ms，SQL墙钟222–243ms。
输入准备85–123ms，Context准备107–144ms，runtime身份关联18–24ms，模型网关
构造不足1ms。这些内部区间可能嵌套，不直接相加。没有重新创建沙箱或下载组件。

## 根因与最小实现

Client open→mount→bind已合并成一次HTTP，但内部每个adapter继续单独建立
有界PostgreSQL连接。A页面这一请求每次20次TaskIO建连，其中约104ms为A1建连。
这才是本轮可直接去除的重复初始化；不能靠缓存profile/session/Task授权减少读取。

仅修改生产文件apps/api/src/zebra_agent_api/client_surface.py：
在现有task_io_deadline内部，为Cloud的open和authenticated mount两条入口增加
已有postgres_connection_scope(bounded=True)。本地走原nullcontext。
不新增Pool、Port、业务SQL、表、缓存、线程、超时配置或请求重试。

每个adapter的事务依然独立提交/回滚并DISCARD ALL；不是将三步改成一个大事务。
Host目标校验、Client凭据、profile生命周期、挂载能力、Task/Run、控制权/fence等
读取都保留；独立提交的撤销在下一次读取可见。原2秒与Grant剩余寿命取最小值，
unknown-commit/部分成功/响应丢失语义不变，凭据响应不缓存，不自动重开会话。
同一同步线程/请求独占，出口关闭所有socket，不跨请求/用户/租户共享事务或结果。

### API镜像组件落后

正常APIeb4f695b的client_surface.py与仓库基线一致，但存储组件比正常Worker9953a04d
旧：没有bounded参数或TaskIoConnections._open/有界socket复用。
第一次临时观察器启动因此失败；已先回滚正常入口，未产生模型调用。
最初Dockerfile还将裸sha256误当镜像名，构建失败；随后使用已核对本地base tag。
这些是本轮诊断准备失误，保留日志，不作为性能样本或生产故障修复收益。

本地镜像将**已验收Worker**的task_io.py与connection_scope.py原字节补齐到API，
与仓库受跟踪源码hash一致；没有编辑这两个模块。A、B诊断镜像都携带相同组件，
只让client_surface.py有无上述scope不同，避免依赖升级混入A/B差异。
新镜像先通过network-none导入/签名检查才替换服务。正常构建入口docker/Dockerfile
本来就COPY apps/packages，后续正规源码构建会包含这些已经存在的组件。
未从整个脏工作区重建镜像；未带入未验收的progress/thread实现。

## 无模型因果验证

固定4组AB/BA/BA/AB，一组各一个新open→mount→bind，无额外有利替换：

| Pair | A | B | A/B TaskIO建连 |
| --- | ---: | ---: | ---: |
|1|250.4ms|68.3ms|14 /1|
|2|218.9ms|86.0ms|14 /1|
|3|137.0ms|55.2ms|14 /1|
|4|173.9ms|61.3ms|14 /1|
|中位数|196.4ms|64.8ms|14 /1|

中位减少67.0%，4/4更快，8次成功；通过预先定义的>=10%、>=3/4、零失败门。
17条非DISCARD显式SQL两侧相同，B额外14条DISCARD，不宣称减少SQL。
原生Client/profile/controller/Task store使用真实PG；Host目标binding和namespace
lookup仍为测试fixture，不是完整HTTP身份验收，也不能用这张表承诺页面省67%。

新增检查先3红再通过：两条Cloud入口作用域独占/关闭、异常清理；最终新增5项
包括本地原行为及真实PG独立连接提交session过期/profile撤销后同socket读到新状态。
原有profile在open后撤销、跨资源/凭据/权限拒绝、部分失败与fence并发检查一并运行。
集中批次72 passed/10 skipped/1 teardown error；error是旧fixture DROP DATABASE
WITH(FORCE)清理权限不足，断言主体已通过。没有修改fixture或扩大角色权限，
只用本地管理员清理本任务拥有的遗留隔离DB。新增最终5项原生检查全部通过。
跳过的特殊环境检查不算通过；没有运行全量pytest或声称full make check绿。
Ruff、生产文件定向Mypy、diff检查通过；Mypy最初直接跟随依赖遇到69个安装路径/
py.typed等依赖错误，使用完整workspace MYPYPATH和follow-imports=silent检查目标
文件通过，未扩修类型基础设施或声称依赖全库类型检查通过。

正常API实际libpq180000：另外只读验证同scope两次借用同PID、150ms预算拒绝
500ms pg_sleep、随后新scope SELECT1正常。无业务表写入或模型调用。

## 固定4次真实页面ABBA

同一公开PG18/Redis8发布日期、各两项特性及官方链接问题。
每次API均重新创建并健康，Worker保持同一观察器镜像；两侧相同存储依赖、线路、
环境、Provider参数。四次均completed/Flash/high/thinking enabled/transient_v2，
Provider retry0、工具失败0；工具由Agent选择。无第五个校准/替换模型Run。

| 指标 | A1 | B1 | B2 | A2 |
| --- | ---: | ---: | ---: | ---: |
| Client准入请求 |175.7ms|71.5ms|133.6ms|212.1ms|
| Client TaskIO物理建连 |20|4|4|20|
| Client非DISCARD SQL |30|30|30|30|
| Client DISCARD SQL |0|17|17|0|
| Send→模型HTTP入口 |2276.9ms|2183.2ms|2055.6ms|2718.0ms|
| Send→首正文 |12.427s|17.627s|13.331s|13.163s|
| Send→canonical完成 |16.184s|20.805s|16.256s|16.122s|
| 模型轮数 / 成功工具 |3 /4|5 /8|3 /4|3 /4|

Client平均193.9→102.5ms，减少47.1%、91.4ms；两组页面对均更快。
发送→模型平均2497.5→2119.4ms，减少15.1%、378.1ms。该差值同时含其他API、
首Cloud请求前等待、Worker和调度波动，不能全部归因于本次scope。

**首正文A平均12.795s、B15.479s，B慢21.0%；整轮A16.153s、B18.531s，B慢14.7%。**
B1自主5轮/8工具，不能隐去，也不能强制减成3轮去改善结果。
B2首正文亦比A2慢167ms。因此本轮没有证明整体首正文/整轮稳定提速，验收范围是
准入阶段的成本下降及兼容性，保持网络/模型/思考/自主决策而非声称用户总等待已解决。

初始化六个API请求非空非DISCARD SQL156、空检查13，两侧相同；TaskIO物理建连
43→27，B新增17条DISCARD，已观测API显式调用总计169→186。
Worker初始化448次保持。不含Host、其他Worker、领取前SQL或协议隐式语句；
**没有SQL查询下降收益**，不能拿更少建连代替更少SQL。
首正文仍以最终答案去空白前16字符首次可见计算，完成采用canonical时间。

Run与页面（全部新建，未重跑旧Run）：

- A1：61a08e2a-7e41-4536-8c59-6c517e5ad42d，http://localhost:3000/dashboard/strategy/conv_1792231544893_3b124d

- B1：b009ee61-6682-4e1a-a983-6cad1acabd5d，http://localhost:3000/dashboard/strategy/conv_1792231623512_33c29d

- B2：b1e1b4b6-47d1-4b17-8078-aea527a84131，http://localhost:3000/dashboard/strategy/conv_1792231716365_7acb99

- A2：35a39dc3-b726-49f8-b5cc-91c0721499c8，http://localhost:3000/dashboard/strategy/conv_1792231834252_9dc8e8

## 本地交付与可复核边界

正常API ca0a85f2f481d3622fbf8081ac460678a426fa2d2a45aa59686dc18d7508aaf7；
Worker9953a04d/Search19f3942f保留，原六Compose、入口、命令和全部服务环境hash
核对不变，均healthy/restart0。三个API源文件hash核对，正常镜像不含新观察器入口。
新鲜Web DNS/SSRF/取消与Yahoo/Cloud egress线路原样保留；web_pipeline_v2未启用，
它与这里的transient_v2不是一个开关。无迁移、推送、npm发布或远端部署。

本轮自有scratch角色、唯一遗留隔离DB、凭据文件已删除；未重置任何原有密码、
改动全局代理或Trench产品源码。诊断Compose覆盖撤除，DOM观察器/本地receiver已关，
普通页面只读重载B2原结果，官方来源和high设置已核对，不另行调用模型。
原生安全/配对、影像与启动阶段白名单metadata保留在feature worktree私有
.artifacts/cloud-start-admission-reuse/，原始凭据/正文/Provider思考不提交。

```sh
# 显式设置仅用于自有隔离PG的ZEBRA_TEST_POSTGRES_DSN，需CREATEDB权限；不要打印凭据。
PYTHONPATH=.:apps/api/src:apps/worker/src:packages/agent-runtime/src \
  uv run pytest -q tests/api/test_client_surface_connections.py
PYTHONPATH=.:apps/api/src:apps/worker/src:packages/agent-runtime/src \
  uv run python scripts/check_cloud_client_surface_io.py .artifacts/NEW-OWNED-COHORT
```

基准拒绝覆盖已完成cohort；创建/清理仅自有fixture数据库。回滚只需将本地API tag
指回原eb4f695b并在无在途请求时按原Compose重建API；保留正常Worker/Search和env，
不重放任何模型请求。

## 后续优先级

本轮不继续扩展准入端点。剩余启动约2.1秒中，首Cloud请求之前均值0.63秒、请求间/
领取约0.39秒，应在调用侧通用transport/SDK与身份exchange边界继续只读归因，
不能凭空叫作Cloud数据库阻塞，或直接改Trench业务规则。
Worker准备约0.44秒、输入/Context检查有新鲜fence/前沿语义，不缓存成旧快照。
后续只有测到同一语义下可省的重复初始化，才立小切片；此次不搭建新批处理API或
为了首正文数字强制改变模型/取证轮数。整体SQL80%、STOP/GC等原有总体验收仍独立。
