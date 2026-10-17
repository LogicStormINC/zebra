# Cloud 原子准入事件写入与后端复用

任务 CLOUD-ADMISSION-WRITE-01；基线bd5107eb。保留高思考/Flash/v2、新鲜身份与授权、自主工具。

## 原因与证据边界

历史A2原子事务非索引部分174.8ms，没有逐条SQL记录，无法事后断言是某一条语句或锁。
本轮先用新鲜Host Grant/execute=false无模型原生探针，SQL参数不记日志；仅对三条Event INSERT
使用PG EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON)，不重复执行同一次写入，不改触发器。
首条INSERT数据库执行37.8/16.9ms，后两条约0.9ms；Session/Workspace投影合计约5ms。
首条追加顺序trigger约2.0–2.4ms、coverage Task摘要约1.3–2.0ms，其余单项不到1ms。
计划未报告JIT，不能把PG全局jit=on当根因；执行器初始化与native函数计划均可能贡献。
源表有36个索引；首次backend的首条INSERT约1494–1507 shared buffer hits，后续约43。
这显示后端初次打开关系/索引与函数计划的工作，但不是磁盘读了1500页，也不精确归因到一个索引。

同连接两组原生对照，每次Task独立commit：首次INSERT14.06/7.86ms，复用backend后1.26/0.75ms；
完整admission90.0/49.6→49.2/31.0ms，backend PID分别保持相同。无模型/无command。
历史174.8ms完整尖峰未复现；不将全部尖峰归因于初始化，不声称已解释当时每一毫秒。

## 最小实现

复用已有postgres_pool_scope（Worker已使用，API标准Docker入口尚未使用）：
新增server模块只在PG模式包住原Uvicorn CLI，默认factory/host/port和参数透传保留；
API Docker ENTRYPOINT改为该模块。现成pool仍min1/max8、等待2s、队列32，退出/失败时关闭。
不改数据库adapter、触发器、SQL、schema、Trench产品逻辑、授权、core Port或依赖。
API factory直接调用和local SQLite保持原行为；默认单进程API容器每进程一池，
本轮不验收Uvicorn reload/multiworker子进程的连接池继承。
每次池借用仍为独立事务，已有reset/rollback/连接故障替换保留。
Host授权及有界TaskIO读取仍走原期限/新鲜校验，不使用普通池替代，不缓存授权或查询结果。

## 验证约定

生命周期独立检查先红（缺少server入口），再绿：真实PG后台PID复用、新创建adapter继承绑定、
独立事务已提交、启动/服务异常向上传播且pool关闭、CLI参数和SQLite路径不变。
使用已有pool的readonly/reset失败/跨线程/租户隔离检查；不修改旧fixture。

固定四轮真实页面ABBA，同一官方搜索题、高思考/Flash/v2、自主工具；无第五次模型Run。
每次服务重建后，先通过实际HTTP做一次同样的新鲜Grant execute=false准入作为就绪检查，
A/B相同工作量、无command/模型，之后测页面；模拟已服务过请求的正常API，不代表冷进程首请求。
A为现有未池化入口，B为仅新增接线，Worker/Search镜像不变。低开销SQL模板/阶段/PID计时
对A/B一致；页面不用EXPLAIN，也不记录参数、凭据、私有模型思考。
原生连接池每借用有空协议探针，Driver execute/empty与非空SQL必须分别列明。

B1的首次事件SQL仍22.8ms，Task249.7ms比A1231.6ms更慢，不能隐去。
PID证明pool已扩为2个backend，readiness与页面Event落在不同backend，
一次就绪准入不足以把两个backend全部变暖。保持原四轮协议；B2和A2各完成后
追加且仅追加两次无模型HTTP准入，测实际服务的稳态复用，均不纳入页面计时窗口。
不把这种pool初始容量扩展叫缓存失效，也不为得到好数字增加模型Run。

## 真实页面四轮结果

四轮全部completed，高思考/Flash/transient_v2，12个执行模型响应retry0，16个自主工具调用成功；
每轮3个模型响应/4个工具，均一个candidate和一次quality通过，无质量重写。

| 样本 | POST/tasks ms | 原子准入ms | 首条Event INSERT ms | 首正文s | Host整轮s | 非空SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | 231.6 | 136.8 | 33.34 | 12.495 | 16.172 | 3152 |
| B1 | 249.8 | 159.3 | 22.84 | 15.648 | 19.272 | 3288 |
| B2 | 210.4 | 149.1 | 19.43 | 13.507 | 16.453 | 3213 |
| A2 | 426.5 | 280.6 | 23.64 | 13.192 | 16.243 | 3196 |

首正文均值A12.844s、B14.578s，整轮A16.208s、B17.863s；本轮没有页面首正文/整轮提速证据，
不能只引用B2或用启动变快来代替该结论。非空SQL均值3174→3250.5（本组反增约2.4%），
模型/工具数相同也不代表输出长度、Provider等待、轮询和所有运行工作相同。
启动2.415→2.121s是原始均值；首个Cloud前750→585ms也同时变化且未改动，不能全归本补丁。
Worker首Provider前仍448execute/33empty/5物理连接；六个Cloud前置请求的非空SQL仍156，
B多13个空协议探针（Driver execute156→169），启动合计非空仍571，前序SQL收益保留。
POST/tasks非空67不变，Driver总execute67→74，其中新增7个empty是现成pool健康检查；
不是7条业务SELECT或业务DML，但确实有协议往返，未将其从Driver总数抹掉。
每个页面Task请求均实测6条Host registry/clock/nonce/audit SQL，新鲜身份/授权没有被缓存。

## 事件/投影逐段与新A2尖峰

| 页面均值ms | A | B |
| --- | ---: | ---: |
| POST/tasks | 329.06 | 230.05 |
| 原子段含checkout/commit | 208.67 | 154.19 |
| 事务体非索引部分 | 53.90 | 51.09 |
| 第0条append含stream CAS | 29.76 | 22.48 |
| 第1条append | 2.83 | 3.99 |
| 第2条append | 3.38 | 4.48 |
| Session投影 | 6.40 | 9.91 |
| Workspace投影 | 1.74 | 3.43 |
| 不可变绑定 | 7.01 | 4.98 |
| Task索引构建 | 140.72 | 92.75 |
| 请求内普通物理connect次数 | 7.00 | 0.00 |
| 普通connect总耗时 | 53.19 | 0.00 |

事务内非索引部分本组约39–63ms，没有重现历史174.8ms。
新A2的索引段221.7ms，其中SELECT GREATEST(两个Task位置倒序LIMIT1子查询)为85.7ms，
首条source坐标UPDATE为53.4ms。其他样本该SELECT约数毫秒以内，不能说固定慢在投影写入。
这条SELECT不执行写入触发器。只读EXPLAIN验证两个Index Only Scan+LIMIT，未全表扫描，
新backend规划3.0ms/执行1.16ms，复用执行0.09ms，现存Task执行0.176ms，未报告JIT。
因此确认的是调用墙钟抖动及可重复的backend首次工作；没有足够证据在锁、网络、调度、
首次catalog/函数计划成本中为历史174.8ms给出唯一比例，也不能宣称已经消灭所有尖峰。
本轮不改trigger/migration、不加透明重试或取消校验来掩盖它。

## 独立稳态HTTP对照（不调用模型）

这4次都在页面完成后，未进入页面SQL/计时窗口。每次新鲜Grant、独立Task/事务，
A每次重建后端，B实际使用同一服务已有两个backend；不是人为固定1条连接的页面试验。

| 样本 | API请求ms | 原子准入ms | 首条INSERT ms |
| --- | ---: | ---: | ---: |
| A1 | 192.7 | 77.7 | 12.13 |
| A2 | 162.4 | 73.5 | 9.35 |
| B1 | 148.6 | 61.3 | 6.65 |
| B2 | 97.3 | 49.8 | 4.53 |

均值API177.6→122.9ms（本组约省54.6ms），原子75.6→55.6ms，首条INSERT10.74→5.59ms。
这是小样本局部收益，不保证p95，也不是页面首正文提升的证据。第一次使用每个后端的成本仍在，
扩池时的新连接也仍需首次初始化；没有启动时循环预热或迁移guard豁免。

## 验证与正常运行

独立生命周期红/绿、实际候选镜像同一检查、实际CLI --help通过；定向56passed/1deselected。
排除项是先前已记录的early_extension_read_inherits_remaining_io_budget期限断言，不修旧fixture。
干净跟踪源码默认make check通过（完整ruff/mypy/边界等），未声称完整make test通过。
正常API使用python -m zebra_agent_api.server，默认CLI参数保留；原六Compose/env摘要/command、
Worker/Search镜像与107项登记源指纹、healthy/0restart复核通过。API入口的变更是本轮声明的改动，
不是声称entrypoint逐字节未变。正常服务连续两次新鲜授权HTTP准入后，两个PG后端PID集合保持相同。
正常API镜像：sha256:13e19eadb56deae9bb939e1262be4ac7da7a776654ce43098b3eff983a210aeb。
Worker仍sha256:1a2270dfbf0bb4986e526cb309e73fc0a339822d34139a7084f700c4e9abc22d；Search仍sha256:245b675ff61b01a0ddace63abc095420c55393a55761a32b15274e25cfcdd1d5。
私有证据在.artifacts/cloud-admission-write-20261017：write-breakdown/steady-breakdown/summary/
startup/read-plan/native-warm.safe.json、EXPLAIN trigger时长、四轮DOM/Driver轨迹、生命周期及正常源指纹。
本轮无推送、npm发布、远端部署或Trench源码修改；四轮模型Run之外只有明确execute=false的诊断。
验收B2会话conv_1792212261165_239ffd；正常恢复后只读核对原结果，不重新执行。

正常B2原结果及高思考设置已在恢复后可见，page-B2.jpg已保存；DOM监听和回环接收器已关闭。
17个原生/就绪诊断Task（含底层DB对照）核实0accepted command/0model request，未增加模型Run。
本地Review仅代表该最小接线及验收切片，历史174.8ms的唯一归因仍未完成，不表示整轮性能目标完成。
