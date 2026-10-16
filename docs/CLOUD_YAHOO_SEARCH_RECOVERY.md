# YAHOO-SEARCH-RECOVERY-01：Yahoo 失败与模型恢复成本

2026-10-16，Luke Ding / Codex，基线7df03bce。结论：补齐 Yahoo 无效状态响应的原生恢复，并修复取证链接挤掉实际源地址造成的错误重写。最终页面配对有明显观察差值，但工作量与网络失败不同，不能宣称稳定约50%提速或全系统SQL降幅；Yahoo冷启动跳转超时仍存在。

## 故障定位及最小实施

### 无效 HTTP 状态0

此前实际搜索日志在Yahoo原始请求及_yahoo_html跳转处记录curl_cffi.HTTPError，状态为0、reason为OK。核对固定SearXNG镜像内error_recorder.py：日志第一项来自exception.response.status_code，确实不是curl异常编号。该值不代表一个有效的上游HTTP响应；OK文字也不能证明请求成功。

原Network.call_client在retry_on_http_error=false/retries=0时将状态0视为可返回响应，Yahoo解析器随后拒绝它；SearXNG只向调用方暴露通用HTTP error，Zebra归类upstream_error，Agent再发起模型决策/改写查询。尚未证明究竟是代理、HTTP/2复用、libcurl还是服务端触发0，未据猜测切协议、升级依赖或改全局网络。

仅在既有Yahoo配置加入retries:1、retry_on_http_error:[0]。复用安装版本已有的“无效响应→关闭客户端→再次请求”实现，没有新重试循环、工具fallback、引擎扇出或模型路由。正常200仍一次请求；状态0仅最多一次普通重试，持续0仍由原Yahoo解析器失败，不伪装为空搜索成功。403/429/验证码仍由原策略异常直接拒绝。

边界必须明确：retries也是该库已有RequestException重试开关，因此HTTP5xx/网络异常等可能重试一次；库原有的首次断连重连另有一次，不宣称所有故障绝对最多两次底层请求。未增加引擎5s、搜索6s及Zebra10s配置预算；这些请求级/父层截止不等价于证明所有底层异步操作都在同一时刻取消。本轮没有修改SearXNG的超时取消实现。Yahoo仍是唯一默认引擎，其余由Agent显式选择，正常代理/TLS/权限/取消/v2/高思考保持。

参考：[SearXNG原生重试配置](https://docs.searxng.org/admin/settings/settings_outgoing.html)、[curl_cffi响应状态与HTTPError说明](https://github.com/lexiforest/curl_cffi/blob/main/docs/quick_start.rst)。具体行为以当前固定镜像源码和原生检查为准，而非仅凭最新版文档。

### 取证恢复后的引用库存溢出

真实B1有两个Yahoo超时，Agent自主改用!bing并抓取PG/Redis官方页面，随后两次候选均被citation_uses_exact_collected_url拒绝。不是工具未执行或地址凭空生成：同一成功receipt序列显示，record_tool_evidence把所有参考地址按字典序截到128项；长发布说明提供的大量href挤掉了实际已抓取的PG源地址。第一次候选失败后，Agent多走一次工具决策、两次PG补抓取、一次5227ms候选重写，最后仍因新源地址再次被挤掉而blocked。

最小共享修复仅12行增量：在既有harness metadata中保留最多128个显式source/url字段，优先放入原有128项引用预算；剩余空间再放发现的参考链接。来源只来自成功ToolResult的既有显式地址字段；辅助source清单与已收集refs求交，不能凭空注入新引用。失败工具不增加引用，质量门、未知URL拒绝及总引用上限均不变。没有新Port、外部依赖、数据库schema或放大引用上限。

新增辅助源清单有额外有界metadata成本，最多128项。超过128个不同显式源仍受原库存上限约束，不保证无限历史引用；发现链接可被驱逐，也不意味着目标内容已被抓取验证。该修复优先保证普通多次取证中实际源地址不被正文链接挤掉，不把地址库存当作语义真实性证书。

对B1同一原始receipt及同一候选纯确定性复核：首次7166ms候选、后续5227ms候选，原逻辑均失败，修复后均通过；伪造未知URL仍拒绝。没有重放旧Run、调用模型或改写历史Event。因此能证明误拒造成的补取证/重写路径被移除，不能把这些时间直接折算成每次页面收益。

## 验证与固定原生观察

首次正常服务两条固定查询并发三组、隔离同镜像/出口/配置再三组，共12次均成功；间歇状态0本轮原生请求没有复现。保留全部记录，不用连续成功证明上游已稳定。

独立scripts/check_yahoo_zero_status.py须在已固定SearXNG解释器内运行，无外网、无框架；直接测试安装版Network及Yahoo解析器，覆盖0→200关闭/恢复、200一次请求、持续0明确失败、403/429/CAPTCHA不重试。原配置对0→200仅返回0，形成断言红；候选配置变绿。最初私有检查尝试改写slots对象实例方法报错，改用最小子类后得到真实断言红。最后正常服务内同一检查也通过。

scripts/check_web_link_evidence.py补充四次128链接洪泛，原逻辑丢失实际源地址而红；修后每轮保留实际来源且总引用不超过128。辅助字段伪造新URL的边界也红→绿。75项ledger/quality/工具恢复/搜索诊断回归通过，另39项配置/搜索完整性检查通过，两组有重叠，不合算成114个独立测试。clean tracked-source make check通过Ruff/mypy1285、文件边界、30eval及既有progress故障门；未跑全量pytest。一次聚焦命令使用不存在文件路径、一次新断言行超长均已纠正，未修改旧fixture/测试框架。

## 实际页面四次运行及版本边界

同一已登录Chrome/账号、Flash、探索、高思考、transient_v2；逐canonical核验20个模型回执全部thinking=enabled/reasoning_effort=high/retry0。原问题保持：

> 请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和各两项主要新特性，只采用官方来源并附链接，简明回答。

顺序固定A1/B1/B2/A2，共四个新Run。A使用原正常API7eb869c9/Workera65cfdfe及旧Yahoo配置；B1只含Yahoo配置，B2增加必要库存修复。因B1发现真实接入缺陷，最终版本比较仅B2/A2，**不能混合四轮版本计算ABBA均值**。两侧API/Worker/搜索都装相同聚合观察器；每轮Worker和搜索进程重建，API沿用同诊断进程。OS/CDN/Provider/数据库未全冷，Yahoo进程内YBV初始化会发生。子进程profile从模型结果中移除，未给模型性能提示。

| 样本及版本 | 状态 | 首正文 | Host整轮 | 模型/候选 | 工具成功/尝试 | Worker非空SQL | API scope SQL |
|---|---|---:|---:|---:|---:|---:|---:|
| A1 原逻辑 |completed|16.906s|28.240s|4/2|4/4|2422|1186|
| B1 Yahoo配置 |failed/blocked|无验收完成正文|48.445s|5/2|5/7|3710|1662|
| B2 最终修复 |completed|29.446s|32.542s|4/1|4/6|3228|1377|
| A2 原逻辑 |completed|59.663s|64.597s|7/1|7/10|5284|2242|

B1保留可见候选、完整DOM及失败，不算成功答案；answer_committed的delivery状态为blocked，session_suspended为delivery_requirements_unmet。其余三个Run为complete且turn_completed=1。四轮没有新runtime_provisioned，没有旧Run恢复/重新执行。首正文按click→DOM出现答案前16个非空白字符，包含待核验候选、排除过程/占位；不是首次paint或最终接受时刻。A1第二候选与整轮成本也保留。

最终B2相对A2：首正文少30.217s（观察值-50.6%）、整轮少32.055s（-49.6%）；Worker非空SQL5284→3228（-38.9%），含空探测execute5505→3307（-39.9%），API2242→1377（-38.6%）。**不是固定同工作量的因果收益或稳定p50/p95**：A2多三轮模型、四次工具，出现10.361s抓取截止、4.269s错误路径404、2.197s无尾斜线308，并额外读取GitHub版本/多个Redis文档核对日期；B2仍有两次Yahoo超时、Agent改写搜索两次。不得将所有差值归因于Yahoo状态0恢复，也不能据此宣称全系统SQL下降38.9%。

| 首正文前区间并集 | B2最终修复 | A2对照 |
|---|---:|---:|
| Provider |9.638s|25.133s|
| 工具 |14.651s|27.544s|
| 准入/编排/投影/页面其余 |5.157s|6.986s|

每轮启动仍448 execute（含33空探测）、5个实际有界连接，click→首模型2.260/2.436/2.457/2.565s，保留既有启动/连接收益。SQL只计Worker执行scope及API请求开始落在click→Host完成+1s的scope，含SET/reset/失败执行；不含Host、其他后台、隐式事务或服务器内部语句，不是系统全量SQL。

### 页面看到的Yahoo额外成本

四页没有出现状态0。B1两次真实Yahoo查询超时，各工具5.800/5.926s；B2两次搜索失败5.734/6.582s。搜索内部记录显示原生307→跟踪跳转→搜索200过程，冷启动有多次网络往返：B1首跳2.70/3.37s，后续还需0.49/1.02s及2.69/3.88s，200已到达时调用方可能已超过原截止，因此不能事后把迟到200标成成功。这才是本轮真实搜索未稳定的主要证据。

SearXNG会在引擎暂停时返回“Suspended: timeout”之类反馈；当前search_health仍统一按timeout给retry_after_seconds=5。B2第二个查询没有观察到对应Yahoo HTTP请求，但仅凭缺失span不足以证明具体暂停/排队机制，不能归因成一次新的Yahoo网络读取。下一切片应固定该类原始反馈和时间线，区分未执行的暂停状态、真实超时与输入错误，向Agent准确表达可用恢复条件；不直接强制选引擎、放大预算、加无限重试或改低思考。本轮未扩入这一尚待原始响应复现的修复。

## 最终代码、服务和证据

生产改动仅docker/web-search/settings.yml与core evidence_ledger；两个独立脚本及治理/本文同步。B2后补了一项辅助清单必须属于已收集refs的交集校验：固定故障红→绿，75回归通过；从B2实际镜像取出原函数，逐个重算全部六个真实receipt，输出metadata与交集校验后的最终函数完全一致，未为此新增模型调用。

正常API7eb869c9、Worker38c42ab1及原固定SearXNG镜像245b675f，在零活动intent后按正常入口更新；99个Cloud源指纹、实际Yahoo配置、原Compose/env/命令/入口/健康状态核验。API为诊断/恢复重启，搜索服务配置更新也重启；不是零重启声明。临时观察器/sitecustomize挂载、DOM监听、自有隔离容器及其匿名卷、loopback接收器清理。无业务库改写、schema迁移、历史Event重写、push/npm/远端部署；本地集成cloud-agent-trench保护原27项无关修改。

私有.artifacts/yahoo-search-recovery-20261016含原生12次结果、固定状态故障红绿、安装版来源/日志、同B1候选质量复核、四Run canonical/完整DOM/工具参数/聚合SQL/搜索状态分段、summarize.py与breakdown.py、page-A2.jpg。summarize只计算最终B2/A2比较，B1失败单列。会话：

- A1 conv_1792165301186_a92211
- B1 conv_1792165405750_89ce1c
- B2 conv_1792165842478_7dcd41
- A2 conv_1792165968075_a81921

状态0底层触发原因及稳定故障率、Yahoo冷启动5s内可靠性、暂停反馈、首正文10s、全系统SQL80%、STOP/容量/GC/多Worker仍是独立OPEN项。本轮交付的是有确定性证明的局部恢复和误拒修复，不是整体性能验收完成。
