# SEARCH-EVIDENCE-RECOVERY-01：多轮取证、失败恢复与页面验收

2026-10-16，owner Luke Ding，基线 fab4a5eb。已修复共享网页投影丢失正文链接、链接未进入既有引用记录的问题；真实页面没有证明首正文或 SQL 净收益。保留所有不利样本，不把局部正确性修复写成性能验收通过。

## 根因及最小实施

上一组真实 Run 没有完全相同的搜索 query 或抓取 URL 重复执行。主要额外工作来自正式发布日期证据不足、GA 公告日期和 GitHub 包日期差异，以及抓取结果只保留锚文本却丢弃 href：Redis 8 特性页本来直接指向 GA 博文，PostgreSQL 18 公告本来指向正确的 release-18.html；模型仍需重新搜索或猜测发布说明地址，曾触发 302 拒绝。

复用既有 HTMLParser 和 parse_web_target，未引入依赖或新 Port：

- web_gateway 把已校验的实际请求 URL 传给共享投影；相对链接按该 URL 解析，忽略页面 base 元素，移除 fragment。
- web_content 在可见锚文本旁保留 `[link: HTTPS_URL]`；拒绝原准入规则禁止的地址、凭据、非 HTTPS、异常端口和超过 2048 字符的 URL。隐藏/空锚点及 nav 标签内链接不增加 URL；继续使用原 main、日期、非 HTML 和 UTF-8 输出上限逻辑。
- 仅将完整保留在输出内的已解析链接放入原有 evidence_refs，去重、最多 128 项。复用 web.search 的“已收集参考地址”含义，**并不代表链接目标已被抓取、内容已验证或获得执行权限**。未知引用仍拒绝，核心 ledger 和质量门未改动。
- 同一 HTTP transport 的 LocalHttpFetchProvider/CrawlGateway 旁路原来丢弃这项元数据；在既有 FetchResult 加默认空 tuple，并传递仍在返回投影中的引用。其他 provider 默认行为兼容。WEB_PIPELINE_V2 与 transient_v2 是两个不同开关；前者未启用，后者始终启用。

没有自动补抓取、强制去重、自动重试/重定向、工具数量上限、改写模型提示或降思考。工具选择和缺失证据恢复仍由 Agent 决定。原 DNS 每次新鲜校验、IP pin/TLS、取消和截止、受控网络入口均保留。

## 确定性证据及成本

固定公开 HTML 的旧/新投影对照：PG 公告 10664→14885 字符，原模型预览上限仍使结果截到 12041 字符，但正确发布说明地址及日期/AIO/uuidv7 证据保留；Redis 特性页 6971→7224，直达 GA 博文地址保留。链接会增加上下文占用，且 PG 的部分尾部内容会受原预览预算影响；不能声称所有页面均无代价或模型必然减少调用。未改输出预算、添加新的正文抽取算法或启发式域名白名单。

初始方案的 B2 暴露接入缺陷：模型引用新保留的正确 PG 发布说明地址，但它尚未进入结构化引用记录，质量门以 citation_uses_exact_collected_url 拒绝，导致额外 5433ms 候选模型调用。补齐 evidence_refs 后，对同一已捕获 HTML、同一候选的纯确定性质量复核从失败变为通过；伪造未知 URL 仍失败。该检查未重放 Run、调用模型或改写历史 Event。它证明此误拒路径已消除，不能等价为每次页面节省 5.43 秒。

独立脚本 `uv run python scripts/check_web_link_evidence.py` 无框架、无外网，覆盖链接准入、相对路径、隐藏/main/nav、空锚、base 忽略、预览/UTF-8 边界、ToolResult→ledger，以及真实临时 SQLite CrawlGateway 的元数据传递。旁路断言在旧生产源上红、补字段后绿；实际正常 Worker 中也通过。

## 页面协议与完整样本

同一已登录 Chrome/账号、同一原始问题：

> 请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和各两项主要新特性，只采用官方来源并附链接，简明回答。

Flash、探索、thinking=enabled、reasoning_effort=high、transient_v2 逐 Run 核验。Agent 自选工具、未降低思考或注入路线。第一批固定 ABBA4；发现上述引用接入缺陷后，明确记录修复并固定追加 A3/B3 两个 Run，分别报告版本，未补跑同一版本挑好成绩。六轮全部 completed、answer_committed=1、turn_completed=1，无 session_failed/新 runtime_provisioned，26 个模型回执均 retry_count=0；这不代表没有质量重写。

首正文为发送 click 到 DOM 首次出现答案开头 16 个非空白字符，包含待核验候选，排除过程/占位；不是首字符 paint 或最终被接受时刻。整轮使用 Host completed；DOM 最后更新单独保存。模型/工具均在首正文截断、取区间并集，禁止把并行时间相加。

### 第一批方案版本：链接文本，尚未补齐引用元数据

| 样本 | 首正文 | Host 整轮 | 模型 | 工具成功/尝试 | Worker 非空 SQL | API SQL |
|---|---:|---:|---:|---:|---:|---:|
| A1 |19.961s|23.661s|4|5/5|2748|1262|
| B1 |29.222s|32.235s|5|7/7|3516|1556|
| B2 |30.696s|40.519s|5|4/5|3292|1518|
| A2 |22.331s|26.421s|3|4/4|2418|1111|

A/B 首正文均值 21.146→29.959s，整轮 25.041→36.377s。B1 额外读取 GitHub releases 及 8.0.0 版本以核对 GA 与包日期；B2 Yahoo upstream_error 后换查询恢复，并发生上面的候选误拒。两项均保留，未算作优化收益。

### 最终修复版本：补齐引用元数据后

A3 原正常 Worker 435867aa，B3 含元数据修复的正常 Worker 3e3b1eab；两侧装相同临时 SQL/分段观察器，同 API、同 Compose 配额。每侧重建 Worker，但搜索/Provider/数据库/OS/CDN 并非全冷。运行后加入的三个旁路兼容源文件不改变本组实际使用的 legacy 工具路径；最终 normal Worker 中两个 active 源文件指纹与 B3 一致。

| 指标 | A3 对照 | B3 修复 |
|---|---:|---:|
| 首正文 |21.584s|25.890s|
| Host 整轮 |25.770s|29.719s|
| DOM 最后更新 |26.276s|30.094s|
| click→首模型请求 |2.248s|2.224s|
| Worker 开始→首模型请求 |0.411s|0.384s|
| 模型轮数（工具循环+候选） |3+1|4+1|
| 工具成功/尝试 |4/5|6/7|
| 搜索/抓取尝试 |3/2|4/3|
| Worker 非空 SQL |2875|3505|
| Worker 全 execute，含空健康探测 |3022|3629|
| API 观察 scope SQL |1291|1528|
| Worker 实际新建有界连接 |158|204|

首正文增加 4.306s（20.0%），整轮增加 3.949s（15.3%），Worker 非空 SQL 增加 630（21.9%）。工作量不同、单对样本且网络波动，不能据此证明代码因果回归；同样，**没有页面提速或 SQL 降低的验收证据**。启动阶段两侧均 448 execute（其中 33 空探测）、5 个新建有界连接，原启动连接收益保留。

| 首正文前区间 | A3 | B3 |
|---|---:|---:|
| Provider 请求等待并集 |8.617s|12.726s|
| 工具执行并集 |8.710s|7.727s|
| 准入/编排/投影/页面余量 |4.258s|5.437s|

A3 模型回执 1251/1688/1677/7209ms，B3 2924/2340/3003/1757/5370ms。前表 Provider 包含最终候选到首正文的部分区间，故不是这些整轮回执的总和。

两侧都出现一次 search_incomplete: yahoo=upstream_error。A3 首次 PG 搜索失败 3.836s，Agent 改写 query 与 Redis GA 抓取并行，再抓 PG 公告；B3 首次 Redis 搜索失败 2.133s，Agent 改写 query 与 PG 公告抓取并行。B3 随后并行抓 Redis 特性页 1.762s、搜索 GA 公告 1.870s，最后抓 GA 博文 1.766s。后两请求同批发出时，特性页直达链接尚未返回；链接修复不能倒流取消已经发起的检索。因此既不能把同主题不同 query 一概当重复，也不能宣称本组省掉了 Redis 搜索。

B3 实际 tool receipt 已含正确 PG release-18.html、Redis GA href，证明生产字段贯通；最终候选只生成一次、无质量误拒。最终 PG 其他引用也来自实际搜索结果；未证明模型必须选用新增 href。下一步较有价值的目标是免费搜索上游失败率、失败后可用来源的结构化表达，以及按已获证据自主收敛的策略评估。应另开有边界切片，先固定故障输入验证，不能直接增加透明重试、强制串行或削减高思考。

## SQL 口径、验证和本地状态

SQL 仅 Worker 执行 scope，以及请求开始落在 click→Host completed+1s 的 API scope；含 SET/reset 和失败执行，空健康探测单列。不是 Host、其他后台、隐式事务、数据库内部语句的系统全量。B3 API 含初始短流准入和后续正式流两个 scope；同样保留。更长运行导致更多轮询/进度，不把它归因为新增逐 token 持久化，也不混成全系统 SQL 降幅。

已有聚焦检查首轮 211pass/1fail：本机真实 TLS 测试一次未进入监听端；未修改 fixture 或生产错误处理。该原案例单独重验通过，再次固定整组 212pass。前期 226 个网络/取消等聚焦检查、33 个 ledger/quality 检查记录保留。最终 clean tracked-source `make check` 通过 Ruff、mypy1285、文件边界、30 个 eval 和既有 progress 故障门；未宣称完整 pytest 套件通过。独立脚本首个旁路红检查一度缺少 required max_output_tokens，修正调用后得到真实元数据丢失断言红，再修生产字段变绿。无旧 fixture 扩修。

私有证据保留在 `.artifacts/search-evidence-recovery-20261016`：固定 HTML/模型预览、同候选质量复核、红绿/default 门；page-pair 和 final-pair 含 canonical/SQL/native profiles/完整 DOM mutation/截图、可重跑 summarize.py 和 breakdown.py（只读已有证据，不调用模型）。六个会话：

- A1 conv_1792162822827_ea690a
- B1 conv_1792162939371_301688
- B2 conv_1792163063435_c4634c
- A2 conv_1792163209752_1cb28d
- A3 conv_1792163746483_64ae09
- B3 conv_1792163867818_69a1df

正常 API 7eb869c9 / Worker a65cfdfe 已在零活动 intent 后恢复/更新，healthy、零 restarts；98 个源文件指纹、原六 Compose/env/入口/命令/search 配置通过核验。诊断/恢复曾重启 API；最后 Worker-only 覆盖没有再次重启 API。临时观察启动器退出，DOM 监听已拆除，两个 loopback 接收器均关闭，B3 原结果仍可读且高思考保留。最后旁路兼容修复未追加模型调用。

仅本地集成 cloud-agent-trench，保留原 27 项无关修改；无 schema/Event 重写、历史 Run 重放、push/npm/远端部署。首正文 10s、全系统 SQL80%、STOP/容量/GC/多 Worker 等独立门仍 OPEN。
