# Cloud 默认网页工具按需沙箱验收

日期：2026-10-15。任务 WEB-RUNTIME-DEFER-01，起点391f69a3。

## 结果与根因

已消除默认内置 web.search / web.fetch 触发的不必要沙箱启动；只改共享 Cloud Runtime
组成使用的两个源文件，不改 Trench、模型参数或搜索供应商。正常本地 Worker 已启用。

上一轮保存的首工具事件→handler 为2449–2567ms。本轮增加有界 OCI 操作计时，
真实基线3110ms中包括 info12ms、create796ms、inspect43ms、start707ms、可写性
exec960ms。共享 LocalToolGateway.execute 对所有本地调用无条件 ensure_ready，
让通过独立可取消原生网络子进程执行的搜索/抓取也创建了 OCI。工具执行本身不使用
RuntimePort；output projector 使用已有 Artifact store，而不是该沙箱。

最小修复：register_web_tools 返回本次实际注册且已审计的默认原生 Web 名称，
LocalToolGateway 对这两个名称跳过 DeferredRuntime.ensure_ready。与现有两路并行
资格复用同一默认/精确类型判断：显式注入 transport、子类、自定义工厂替代类型均不
在集合。另一套 web_pipeline_v2 返回空集合，保留原行为。这里的 Web pipeline
开关与 transient_v2 流协议不同，真实页面仍为 transient_v2。

文件/命令、MCP、研究子任务与其它本地工具仍走原保守准备规则。之后需要工作空间
时仍按原锁准备一次并持久化真实 authority；纯 Web 不伪造 handle/authority。Workspace
物化和 Context 准入不变，fresh control/ownership/deadline、SSRF、子进程kill/reap、
输出持久化/投影、证据账本与最终答案校验均保留。没有缓存授权或关闭网络隔离。

## 验证

新增7项小回归，先红1/绿6，修复后全部绿；连同原 Web 并发、原生网络取消、transport、
DeferredRuntime、Worker混合执行和线程上下文，共90项通过。覆盖同时search/fetch
不准备、随后两次files.list仅准备一次、四种显式注入/子类仍准备、另一套pipeline仍
准备、停止前不进入handler。无旧fixture或测试基础设施修改。

Ruff（排除私有.artifacts）、项目mypy1278文件、eval30与文件大小门均通过。未跑
全量pytest，也不将字面make check称为通过；私有临时诊断脚本不属于提交代码。

## 新真实页面配对与证据边界

同一公开PG18/Redis8发布日期及两项特性问题，A1后B1，两次新会话。Flash/high、
每次模型回执enabled/high、retry0，网络峰值2、transient_v2均保持。

| 指标 | A1原入口 | B1按需沙箱 |
| --- | ---: | ---: |
| 首工具canonical创建时间→handler |3110ms|249ms|
| 共享工具入口→handler |2841ms|6ms|
| 首工具上述事件区间显式SQL |143|73|
| 沙箱实例 / OCI操作数（含清理） |1 /7|0 /0|
| 启动SQL / Task I/O连接 |415 /66|415 /66|
| 点击→首段公开正文 |5.838s|4.383s|
| 首次两家官方链接可见 |42.739s|54.995s|
| Host创建→完成 |44.545s|56.396s|
| 模型轮数 / 工具数 |5 /7|6 /9|
| 失败工具数 |1|1|
| 同步Worker显式SQL / Task I/O连接 |3989 /1013|4722 /1235|

直接边界少2862ms（约92%），区间SQL少70（约49%）；canonical时间为事件创建，
包含该事实提交与同批次准备，不能解释为纯排队时间。共享入口计时进一步将实际准备
隔离：2841→6ms。不是降低工具权限，也没有移走需要访问文件工具的沙箱准备。

整轮性能本次没有通过：B1耗时/SQL反而增加。A1一次Redis搜索上游search_incomplete；
B1首次搜索均成功，随后Redis官方GA博客抓取等待约10秒后gateway_unavailable，
Agent额外核对其它官方页面。失败样本完整保留，没有重复模型测试来挑好数据。
B1完成且展示来源/证据不足说明，但精确Redis发布日期仍存在未消除的口径冲突，
因此不把canonical completed或两条链接出现视作完整答案质量验收。

可确认的是网页工具不再承受沙箱固定成本；不能把首段正文1.455s差值或整轮表现
严格归因于这项修复，首段说明本来发生在工具前。SQL范围为同一Worker执行及传播
上下文的工具线程最外层cursor.execute，不含API/Host/其它线程或协议隐式语句。
本轮没有系统SQL80%、稳定p50/p95、完整STOP/GC或“全部优化完成”主张。

A1 Run04a88316-e698-477f-8fa7-79d8eb302fa3：
http://localhost:3000/dashboard/strategy/conv_1792058135140_b86ef8

B1 Run87645270-9516-49fb-b295-215f0fc9bf92：
http://localhost:3000/dashboard/strategy/conv_1792058253440_d1c360

## 本地交付

正常Worker为c7a422d51df3a916b621bf032d7970f6c91c7dd0c81e695f2c298307e8ca7643，
在原d6b72027只覆盖harness.py与web_tools.py；APIc0b8e9dc与Yahoo搜索服务245b675f
保持原镜像/配置。恢复原六Compose/正常Worker入口和命令，healthy；32个累计验收
源hash核对，保留v2、高思考、两路并行、fresh scalar、启动415SQL/66连接及其它性能
修复。临时trace入口与浏览器观察器撤除，正常页面重新加载原结果，不重新调用模型。

本地提交并串行集成cloud-agent-trench，保留原27条无关脏改动。无推送、npm发布、
远端部署、旧Run重放或业务库修复。原未提交DNS/参数恢复/SDK工作未混入本切片。
私有证据.artifacts/web-runtime-defer-20261015，包含两次原始安全trace、模型/工具/
SQL/OCI/DOM计时、正常源与镜像复核以及结果截图。

下一步重点仍是外部检索/抓取稳定性与真实完整答案的耗时；本次仅收敛已测得的沙箱
固定成本，不扩修抓取错误分类、旧测试系统或免费供应商策略。
