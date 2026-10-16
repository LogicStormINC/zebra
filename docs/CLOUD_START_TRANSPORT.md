# Cloud 启动：复用 transport 与已提交任务索引

CLOUD-START-TRANSPORT-01；2026-10-17；基线 1c77c3d5。

## 根因及最小改动

只读本轮调用图及无模型原生 PostgreSQL 探针确认：POST /tasks 的 94 次 Driver execute 中，
原子准入已在事务内建好 Task/Segment/Event 索引，响应组装的 ensure_for_session 又重建一次。
末尾 22 条重复准备可用原有 get_task 读取一条已提交 header 替代。
只改 create_task 共用入口；云存储优先读，缺失时仍原 ensure；SQLite 原路径保留。
不改变原子写入、幂等回执、租户/Host/Run 校验、事件索引修复本身。

主 ZebraStrategyRuntime 已持有共享 httpx.AsyncClient。客户端准入辅助路径仍重新创建 client，
无模型工厂实测约 43–47ms；继而建立独立 TCP/TLS 连接。通过已有运行链路显式传递 client，
借用方用标准库 nullcontext，既不创建另一个 client 也不关闭借来的 client。
每次 _call 仍独立交换新鲜 Host Grant，headers/credential 不存到共享 client，不缓存授权。
未传 client 的独立入口维持原生命周期。Trench 仅改协议传输接线，不改产品逻辑。

未启用新的 DB 全局连接池/跨请求结果缓存，也不将建任务的多个原子事务合成一个事务。
当前服务与 HEAD 的 task_api.py 在修改前逐字节一致；不附带升级镜像内其他存储代码。

## 验证口径

- 无模型原生探针：仅 execute=false 建任务、不提交 command；实际验签/新鲜主体检查/nonce消费。
  A=94 SQL；B=73 SQL，下降21（22.3%）。单次带 SQL 栈探针耗时472/357ms只作定位，不当稳定收益。
- 确定性检查：现存云 header 复用、缺失回退、SQLite 保留；借用 client 不关闭、不创建替代，
  不同用户各自新鲜 Grant、共享 client 不残留 Authorization。
- 四轮真实页面固定 ABBA，同一公开搜索题、高思考/Flash/v2/自主工具；所有失败保留。
  A=上一轮已验收 API/Host transport，B=本轮最小改动；Worker/Search 不变。
- Host 私有诊断仅记阶段、路径、PID和时间，不记 headers/payload/token；对 A/B 同样启用，
  拆 click→持久 Turn→runtime entry→新鲜主体校验→Grant HTTP→首个 Cloud 请求。
  正常恢复前移除临时 hook，复核三份 Host 源文件字节与最终候选一致。
- SQL=Worker attempt+窗口内 API Driver execute，空探针另列，排除只读取证；
  首正文为最终正文前16个规范化字符首次在DOM出现（含显式临时草稿，排除进度）；
  模型/工具工作量不同，不把整轮 SQL 和耗时原始差值当本次改动因果。

## 结果

四轮均 completed/high/DeepSeek Flash/transient_v2。14 次执行模型响应 retry0；20 次工具全部成功；
每轮一个 candidate、一次质量验收通过，没有质量重写。工具仍由 agent 自行决定。

| 样本 | 启动秒 | 首正文秒 | Host整轮秒 | 模型轮 | 工具数 | Worker＋API非空SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |

| A1 | 2.625 | 21.605 | 24.940 | 4 | 6 | 4311 |
| B1 | 2.198 | 21.647 | 29.145 | 4 | 6 | 4351 |
| B2 | 2.196 | 14.571 | 18.757 | 3 | 4 | 3201 |
| A2 | 2.276 | 16.709 | 20.371 | 3 | 4 | 3289 |

启动均值 2.451 → 2.197 秒（本组约省253ms、10.3%）。回切 A2=2.276 秒，B1/B2=2.198/2.196，
两个 B 样本均低于两个 A；样本仅各两次，含调度、首次握手和数据库波动，不保证稳定省253ms。
首正文均值 19.157 → 18.109 秒，整轮 22.656 → 23.951 秒，非空 SQL 3800 → 3776（约0.6%）。
配对两组的模型/工具数分别同为4/6与3/4，但生成长度和模型/网络等待不同：
B1 整轮反而更慢。没有证据表明整轮普遍提速，不将首正文差值都归因于这十余行改动。

## 局部确定收益与计量边界

- POST /tasks 四轮稳定 A=94、B=73 条 SQL（下降22.3%）。原子准入语义未动，
  仅去掉响应组装中的重复索引准备；get_task 耗时 B=7.7/13.5ms，原 ensure A=22.4/26.1ms。
- 该请求总耗时 A=245/251ms，B=197/309ms，均值248/253ms，**没有稳定的请求总耗时改善**。
  B2 原子准入事务187ms，明显高于其余92–120ms，不能隐去这个样本。
- 六个阻塞前置 Cloud 请求保持6个，SQL 183 → 162（下降11.5%）。Worker 首次Provider前
  仍为448 execute、33空探针、5次TaskIo物理打开；启动合计非空SQL598 → 577（下降3.5%）。
- 准入额外 client 创建次数每轮1 → 0；真实A两轮构造约14.8/15.7ms，
  小于单独进程工厂探针43–47ms，应以实际页面值说明收益。
- Task响应结束→client-surface服务端入口间隙 A=171/74ms、B=62/59ms，
  均值123→61ms；包含Host读写/Grant交换/本地连接，不能全部命名为TLS或构造成本。
  socket可复用，每个请求的身份、Grant、目标授权仍重新校验，未共享授权结论。

## 首个 Cloud 请求前：逐段证据

下表 Cloud请求以Host发出为终点；API收到还需约9/58/17/12ms，单列避免混淆。

| 阶段ms | A1 | B1 | B2 | A2 |
| --- | ---: | ---: | ---: | ---: |
| click→持久Turn建立 | 220.0 | 193.0 | 180.0 | 212.0 |
| Turn建立→runtime入口 | 459.2 | 326.1 | 235.3 | 265.3 |
| runtime入口→首次Cloud发出 | 110.6 | 111.9 | 189.6 | 73.3 |
| 其中：新鲜主体校验 | 7.4 | 2.8 | 5.1 | 8.0 |
| 其中：首次Grant HTTP | 88.9 | 96.2 | 152.8 | 42.8 |

新鲜主体校验只有约3–8ms，不能用缓存授权来换性能。首次Grant HTTP约43–153ms，
包含首次TCP/TLS与broker响应，当前计时不能把两者进一步分离。
最大部分是持久化入队180–220ms及调度/准备235–459ms；后者包括claim、轮询等待、
运行前状态检查和调度，不能将全部235–459ms叫纯轮询时间。
这部分在Host已持久Turn至runtime入口之间；没有在本轮改Trench入队/调度产品逻辑。
主runtime的HTTPclient在启动时已建立，不是每个Turn首次Cloud请求前再创建；
本轮借用修复位于Task之后的辅助准入，未声称消除了首个Cloud请求前的等待。

## 验证、交付与剩余边界

API定向22 passed，独立断言检查通过；Host定向54 passed/2 skipped，恢复正常源文件后
单独借用生命周期检查再次通过。干净跟踪源码默认make check（含完整mypy/ruff/边界检查）通过。
单独只检查task_api.py的mypy曾遇到既有import-untyped依赖发现问题，未修类型测试基础设施；
默认项目范围mypy已通过。本轮不涉及上一轮的目录期限断言失败。

正常API镜像：sha256:1fcd97720fadee51845f9a3620f415f05c135b1aee2731bc8ce299b33b20be82。
正常Worker仍为1a2270dfbf0bb4986e526cb309e73fc0a339822d34139a7084f700c4e9abc22d；
Search仍为245b675ff61b01a0ddace63abc095420c55393a55761a32b15274e25cfcdd1d5。
原六Compose/env摘要/entrypoint/command、healthy/0 restart与104项登记源码指纹复核通过。
Host计时hook已移除，三份正常Host源文件与冻结B候选逐字节一致，独立transport测试通过。
接收器关闭、DOM观察器解除，恢复正常服务后B2原结果可见，不产生第五次模型Run。

证据在私有.artifacts/cloud-start-transport-20261017：summary.safe.json、startup.safe.json、
host-breakdown.safe.json、diagnostic-A/B.safe.json、final-source-checks.safe.json及page-B2.jpg。
无模型探针两任务均无session_command_accepted/model_request_started，未消耗额外模型轮。
本地代码集成保留primary27项无关脏状态，不推送/远端部署、不发布npm包。
剩余重点是事务内首次索引构建与Host调度准备；后续必须先测其内部阶段，不能用减授权校验、
降低思考强度、固定工具路由或扩大测试修复来换取看起来更短的数字。
