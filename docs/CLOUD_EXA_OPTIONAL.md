# Exa 匿名 MCP 可选补充：准备与验收边界

日期：2026-10-17。任务：CLOUD-EXA-OPTIONAL-01。

## 结论

当前状态（CLOUD-EXA-LIVE-01）：Exa 已作为可选引擎接入正常搜索服务，Worker
工具说明已列出 `!exa`；**Yahoo 仍是唯一默认引擎，Exa 保留 fast**。
不强制切换来源，不修改研究流程提示词、Trench 产品逻辑或全局代理。
首次准备和历史隔离验证的记录保留如下；最新运行验收见末节。

四组无模型真实检索中，Exa 补回 Redis 官方发布页，但整体检索中位耗时
更高。仅验收“可选补充的实现准备”，不验收稳定性能收益，不启用正常环境，
不进行真实页面或模型配对，不声称减少 SQL 或首正文延迟。

## 接入边界

- 官方匿名入口：[Exa MCP](https://exa.ai/mcp)；
  [官方服务源码与匿名限流说明](https://github.com/exa-labs/exa-mcp-server)。
  匿名 MCP 与需密钥的 REST API 不同；匿名额度及恢复时间不保证。
- 固定 HTTPS 入口 `https://mcp.exa.ai/mcp?tools=web_search_advanced_exa`。
  调用 `web_search_advanced_exa`，不接入任意第三方 MCP 地址。
- 沿用 SearXNG online processor、已有 native HTTP 连接池和请求取消机制。
  不增加依赖、独立网络服务或 Cloud 授权缓存。
- 正常 Compose 已注册 `!exa`；引擎仍为 disabled，排除在默认检索中，
  允许显式选择。普通查询仍只走 Yahoo。Worker 工具说明仅宣告可选能力，
  由 agent 决定是否选择，不编写强制路由；尚未进行模型/页面验收。
- 固定 query 原文；fast、最多 5 条、关闭 summary/highlights、正文每条
  最多 1000 字符、livecrawlTimeout=1000ms。不硬编码来源或改写搜索问题。
- 只接受显式的逐结果 URL。现有 Cloud 结果规范化保留 URL/输出边界，
  后续实际抓取继续经过现有 DNS/SSRF 校验。MCP 不负责替代这些校验。
- 新鲜 Cloud 授权及 DNS/SSRF 生产代码未修改。后端隔离检索不等价于
  已认证 Cloud 工具或页面的端到端安全验收。

## 限流、冷却与回退

1. 识别 HTTP 429、RPC 限流错误、MCP isError，以及 HTTP200、没有
   isError 标记但 content.text 为免费额度/限流提示的响应。初始化和通知
   帧的 HTTP429 同样执行冷却。合法结果正文提到 quota/rate limit 不误判。
2. 一次 Exa 阶段最多 2 秒；初始化、通知、检索共享该预算，零 Exa 重试。
   native 总请求预算最多 6 秒。后续 Yahoo 只能使用原始截止时间内的余额，
   不重新计时。已取消或超时直接传播，**不发起迟到的 Yahoo 回退请求**。
3. 明确的限流触发至少 900 秒冷却；较长的 Retry-After（秒数或日期）
   优先。超过 24 小时则关闭自动恢复，保留阻断状态供 operator 处理，
   不把服务器要求缩短成 24 小时后自动探测。
4. 其他明确的协议/结果错误冷却 60 秒，当前请求在剩余预算内回退 Yahoo。
   网络超时/取消不是上述可恢复协议错误，不在同一请求内重试或回退。
5. 冷却或已有在途探测时，直接使用已加载的 Yahoo 引擎及其连接池、
   原有请求/parser，不发 Exa 控制帧或检索帧。回退 snippet 加
   `[Yahoo fallback]` 标记，不能把回退结果当成 Exa 召回收益。
6. 现有持久 TMPDIR 下 `zebra-exa-control.json` 保存截止时间和探测 lease，
   不保存 query、结果、Cloud 授权或密钥。文件权限 0600，拒绝符号链接，
   flock 保护短读写，一次仅允许一个匿名探测。owner 避免旧请求清除新 lease。
   异常/损坏状态禁止新的 Exa 探测；写入失败可显式失败，不伪装成功。
7. 当前只协调**同一共享本地卷**上的进程/容器；不是多主机配额协调器。
   停电导致部分写入后以损坏状态关闭探测；不提供数据库级持久性保证。
   匿名 MCP session 仅进程内复用，不是授权缓存。请求被取消后不重置配额状态。

严禁通过清理状态文件、换 session/出口/身份或反复重启来规避限流。
真实验证继承了前一轮已知限流批次结束时间加 900 秒的截止时间；首次调用前
该时间已过去，没有宣称上游配额确定恢复，也没有删除或重置控制状态。

## 实施文件与准备命令

- `docker/web-search/zebra_exa.py`：原生可选引擎及上述控制。
- `docker/web-search/check_exa.py`：单个可运行、禁网的 assert 检查。
- Dockerfile：保留原有取消、Yahoo 出口与耗时补丁；复制可选引擎，从当前
  base settings 构建 opt-in settings 快照。修改 base settings 后须重建镜像。
- `compose.yml`：正常启动选择可选镜像及其 settings 快照，默认引擎仍仅Yahoo。
  `compose.exa.yml` 保留为兼容 overlay。基础settings修改后须重新构建快照。

在仓库根目录准备镜像：

```sh
docker build -t zebra-searxng:exa-optional-01 docker/web-search
```

运行离线回归（不会调用 Exa/Yahoo/模型）：

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  -e PYTHONPATH=/usr/local/searxng \
  --entrypoint /usr/local/searxng/.venv/bin/python \
  --mount type=bind,source="$PWD/docker/web-search/check_exa.py",target=/checks/check_exa.py,readonly \
  --mount type=bind,source="$PWD/docker/web-search/zebra_exa.py",target=/checks/zebra_exa.py,readonly \
  --mount type=bind,source="$PWD/docker/web-search/settings.yml",target=/checks/settings.yml,readonly \
  zebra-searxng:exa-optional-01 /checks/check_exa.py
```

首次准备阶段未启用；CLOUD-EXA-LIVE-01 已按用户授权启用。正常启动可用下方
兼容组合，也可直接使用 `compose.yml`，二者均保留 Yahoo 默认：

```sh
docker compose -f docker/web-search/compose.yml \
  -f docker/web-search/compose.exa.yml up -d --no-deps searxng
```

复用现有 `SEARXNG_YAHOO_PROXY` 指定的受控出口；独立 Exa 路线可通过
service env 中 `SEARXNG_EXA_PROXY` 配置，不改变全局代理。无上述变量时
沿用 native outgoing 设置；启用前应核对部署出口符合当前安全要求。
必须保留既有 `search-cache` 卷；回退到正常组合也不删除冷却状态。

## 本轮验证

离线 native 检查通过：原生引擎 loader、默认仅 Yahoo、HTTP/RPC/文本限流、
初始化/通知限流与 Retry-After、跨进程冷却、8 路竞争仅一个 lease、旧 owner
隔离、损坏状态关闭探测、零 Exa 帧回退、取消与原始截止时间。
通知429处理的回归先复现失败，再用最小修改修复；没有依赖真实限流取样。

现有无模型 Cloud 搜索 transport、public DNS、搜索/网关工具检查共 37 项通过。
代码 Ruff/格式通过。新增引擎镜像实际 native 启动和 healthz 通过，配置显示
Yahoo enabled=true、Exa enabled=false。只读检查默认配置与原有取消补丁。

固定四题、固定官方 URL allowset、交错 AB/BA/BA/AB，一格一次：

| 问题 | Yahoo 官方目标 | Exa 官方目标 | Yahoo ms | Exa ms |
| --- | --- | --- | ---: | ---: |
| Redis 8 GA | 未命中 | 命中 | 2196.930 | 1979.627 |
| PostgreSQL 18 发布 | 命中 | 命中 | 947.977 | 1258.668 |
| SQLite WAL | 命中 | 命中 | 772.110 | 1966.734 |
| Python 3.14 发布 | 命中 | 命中 | 830.811 | 1205.365 |
| 合计/中位数 | 3/4 | 4/4 | 889.394 | 1612.701 |

Yahoo SQLite 的 sqlite.org 与 www.sqlite.org 已在调用前同时列入 allowset。
原始探针仅按第一个 URL 计分的 false 保留；现有 Cloud normalizer 与预定
完整 allowset 的离线裁定为命中，没有事后扩大来源标准。

Exa 本组 4 次有效结果、0 错误、0 回退；未真实触发429。真实限流后的
生产回退尚未观测，正确性证据来自禁网注入回归，不能混称已完成真实配额验收。
Exa 中位数多 723.307ms（约81%）；四题样本小、Yahoo 正常服务已热，候选
首个请求包含首次 MCP 初始化，不能据此推导总体或页面耗时分布。
因此不扩展模型/页面批次；匿名容量及稳定收益仍未通过。

第一版隔离候选因 `network` 导入名撞上原生保留字段而未启动，零 Exa 请求。
完整失败日志及当时 4 次 Yahoo 控制保留，未用这批错误做性能比较；修正导入
并加入 loader 检查后，才进行上述独立四组检索。首次启动失败不能从记录中删除。
真实检索后对通知429分支做的修复不改变成功调用参数或默认路由；最终源码
重新构建与离线检查，不追加选择性真实请求。

私有原始协议、构建/启动失败记录、原始/规范化检索结果、测试日志及服务
前后摘要位于 `.artifacts/cloud-exa-optional/`，不把本机证据当成可移植测试夹具。
本轮未调用模型、未改 Run、未更新正常服务，未推送或远端部署。

## 下一步门槛

只有在实际低频工作量中，召回提升可复现且失败/耗时成本可接受，才考虑
宣告可选工具能力并进行高思考、v2 的真实页面配对。沿用同题对照、保留
限流失败、不重置状态；若配额再次限制，遵守冷却并保留 Yahoo，不扩大压测。
当前可选实现准备完成不代表此门槛通过。

## 2026-10-17 追加：分段耗时与配对限流

任务 CLOUD-EXA-LATENCY-01。没有改生产引擎或增加依赖。隔离容器内的私有
诊断副本读取底层**已有** curl infos，分别记录 initialize、initialized 通知、
tools/call；不记录 query、响应正文或 MCP session。沿用原持久配额状态与出口。

原来的 1612.701ms 中位数没有逐请求分段日志，不能倒推精确归因。本轮同四题
重新取证，所有官方目标仍命中，基线中位956.032ms；这是不同批次的网络/上游
波动，**不是优化收益**。数字不替换原始较慢结果。

| 请求 | 外层 ms | 初始化+通知 ms | tools/call ms | 请求就绪到首字节 ms | 响应体 ms | 其他 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Redis（冷 MCP） | 1492.944 | 770.293 | 700.593 | 593.497 | 107.001 | 22.058 |
| PostgreSQL（热） | 908.649 | 0 | 895.891 | 814.527 | 81.251 | 12.758 |
| SQLite（热） | 821.671 | 0 | 797.081 | 748.052 | 48.915 | 24.590 |
| Python（热） | 1003.414 | 0 | 989.918 | 919.999 | 69.801 | 13.496 |

冷 initialize=561.938ms，通知=208.355ms。initialize 的 native DNS=0.052ms、
connect=0.691ms、appconnect=291.798ms，pretransfer=292.045ms；随后首字节
561.784ms，合计561.938ms。这里 connect 是到本地 SOCKS 出口的连接，
appconnect 阶段包含代理隧道、远端连接/TLS；不能把0.691ms当成远端TCP耗时，
也不能声称单独测到了代理远端 DNS。无代理服务端分段遥测就无法进一步分离。

通知和全部 tools/call 的 connect/appconnect 都为0，说明已复用连接；只有
冷生命周期执行初始化。热请求约91–94%的 tools/call 时间在首字节之前。
这段包含公网往返、MCP/上游排队与检索/内容处理，**不是纯服务端检索计算**。
官方 MCP 可返回 searchTime，但基线没有采到该字段；没有虚构服务端分解。
响应体49–107ms、本地其他13–25ms，相比等待更小。

因此不再增加连接池、不在 Yahoo 默认路径后台发 Exa 预热、不跳过 MCP 握手。
最值得验证的单变量是 `type: fast → instant`，仅作用于可选 Exa 检索；
模型高思考设置不变。
[官方 Search 文档](https://exa.ai/docs/reference/search)明确 instant 以部分搜索
深度换速度；[官方 MCP 工具实现](https://github.com/exa-labs/exa-mcp-server/blob/main/src/tools/webSearchAdvanced.ts)
接受该参数。不能未经召回验证直接替换。其他候选如关闭内容/改变 freshness
会改变证据供给，本轮没有混入或试探。

调用前冻结四题8格 fast/instant 配对，顺序 AB/BA/BA/AB；query、5条、1000字符、
livecrawlTimeout1000及 moderation 相同，不改写/硬编码来源。主计时用同一
native pool/session 的热 tools/call curl总时长，单列第一格冷初始化，不能把
冷fast对热instant计作收益。门槛：零错误/回退/限流、所有预定官方目标保留、
中位降幅至少15%且至少3/4题更快。

**配对第一格 fast 即遭真实限流，已停止；instant 实际调用0次。**
initialize489.790ms、通知255.860ms、tools/call277.158ms；tools/call HTTP200
触发现有rate-limit分支，持久冷却约900秒，当前请求实际回退Yahoo。
外层2905.476ms含回退及其他等待，不作为Exa成功或提速样本。未重试、未清
冷却、未切换出口/身份，限流后也未重启重测，不推断匿名额度或下次恢复保证。

另做一次**仅验证已冷却路由**的功能请求：返回标记的Yahoo结果，控制文件
前后逐字节相同，全部底层Exa阶段记录数量不变，证明没有新初始化/检索帧。
这不是对Exa重试，也不计性能样本。离线限流/冷却/取消检查再次通过。

本轮共4次基线检索、1次限流检索、4个MCP初始化/通知帧，2次Yahoo回退检索；
没有模型/页面请求。新鲜Cloud授权、DNS/SSRF、v2、Trench与全局代理均未改。
正常API/Worker/Search镜像、环境摘要、启动时间和重启数前后相同。
私有证据 `.artifacts/cloud-exa-latency/`，正常搜索仍保留Yahoo默认。

本轮完成瓶颈定位；**instant配对与性能改动尚未验收、尚未落地**。冷却结束
仅表示本地允许一次探测，不保证上游恢复；后续若继续，应先受控尝试并在任何
限流时再次停止，不能用新一组成功数据替换本次限流失败。稳定收益之前不做页面配对。

## 2026-10-17 追加：冷却后 fast/instant 配对完成，保留 fast

任务 CLOUD-EXA-PAIR-02，用户明确授权冷却后继续；不是自动循环探测配额。
检查原持久 until=`2026-10-17T13:45:17.056886Z`，续跑时已自然过去约198秒，
blocked=false、lease已到期。没有删除/重置状态、换出口或身份；沿用同一镜像、
受控代理与冷却卷。上一批限流失败独立保留，不能以本批成功覆盖。

严格执行预定四题 AB/BA/BA/AB，8次检索，无预热查询、重试、补抽或扩展。
唯一变量为 type=fast/instant；query、数量5、正文1000字符、summary/highlights
关闭、livecrawlTimeout1000、moderation相同。两者使用同一进程的native池及
MCP协议元数据；全部tools/call的connect/appconnect为0。

计时用热 tools/call curl total；官方召回用现有Cloud normalizer，首次检索的
前5条中匹配**调用前固定的官方目标URL allowset**，另外记录首次命中排名。
没有追加搜索或抓取来补足证据。

| 问题 | fast tools ms | instant tools ms | fast 官方排名 | instant 官方排名 |
| --- | ---: | ---: | ---: | ---: |
| Redis 8 GA | 656.312 | 679.557 | 1 | 1 |
| PostgreSQL 18 | 706.150 | 655.287 | 1 | 1 |
| SQLite WAL | 605.612 | 1167.444 | 1 | 1 |
| Python 3.14 | 769.095 | 1297.257 | 1 | 1 |
| 中位数 / 命中数 | 681.231 | 923.501 | 4/4 | 4/4 |

8次均为有效Exa结果、零错误、零限流、零Yahoo回退。两种模式hit@1及hit@5
均4/4。instant仅1/4题更快，中位数比fast慢35.56%，**不通过预定的≥15%降幅
且≥3/4题更快门槛**；不切换模式、不追加配对寻找有利样本、不做页面/模型验收。

本次还取得上游实际返回的searchTime：fast四题341.5/371.8/321.9/336.6ms，
instant为353.0/346.4/881.8/976.8ms；中位339.05/617.40ms。SQLite/Python
的instant慢点主要也出现在该上游字段，不能归咎于本地连接新建。这个字段是
供应商自报处理时长，不表示已经获得服务端内部检索、抓取、队列的逐段跟踪。

首个fast外层1383.564ms另含冷初始化+通知669.113ms及其他58.139ms；
不能直接与同题instant外层700.624ms相减，声称instant快约0.68秒。
上表已经排除这项冷生命周期差异。样本仅四题一轮，结论是**本次没有支持
切换instant的收益证据**，不是证明任何工作量下fast都更快，也不证明匿名容量稳定。

本轮只更新取证与验收文档，生产源及正常配置未改；正常搜索仍为Yahoo默认，
可选Exa仍保留fast和既有限流冷却/Yahoo回退。新鲜授权、DNS/SSRF、取消、
高思考、v2、Trench逻辑均未动。准备阶段离线控制回归通过；正常API/Worker/
Search的image/env摘要/启动时间/重启数前后相同。仅本任务隔离容器已移除，
一次性续跑automation已删除，不再安排配额探测。无模型/页面、推送或部署。
完整协议、8格原始/规范化结果、逐帧计时和前后摘要：
`.artifacts/cloud-exa-pair-02/`。

## 2026-10-17 追加：保留有效 MCP 元数据，减少限流恢复的重复初始化

任务 CLOUD-EXA-COLD-01。保留 fast，不再试其他检索模式。
上一节冷生命周期669.113ms的精确分解如下：

| 阶段 | ms | 解释 |
| --- | ---: | --- |
| initialize 就绪前 | 205.840 | 含本地代理连接、隧道/远端连接、TLS等，不能独立归为远端TCP |
| initialize 就绪后至完整响应 | 258.721 | 往返、MCP服务处理及少量响应体 |
| initialized 通知完整往返 | 204.552 | 复用连接，等待HTTP202以确认接受，兼顾429识别 |
| 合计 | 669.113 | 真正新建MCP生命周期的控制开销 |

两阶段握手不能无条件省略：
[MCP生命周期](https://modelcontextprotocol.io/specification/2025-03-26/basic/lifecycle)
要求先初始化并发送通知。
[2025-06-18变更](https://modelcontextprotocol.io/specification/2025-06-18/changelog)
已经移除batch支持；没有试旧版批处理、并发通知/工具调用、伪装已初始化或后台预热。
这些方案增加兼容性、处理顺序或配额风险，不能当通用最小优化。

实际发现的冗余在 `response` 错误分支：所有provider错误都会将 `_session`
清空，包括已完成握手后发生的429、RPC限流或HTTP200限流文本。下一次本地
冷却自然到期，即使同一有效会话仍能继续，也会多发initialize和initialized。

最小修复仅增加一个条件：**确认是RateLimit时保留进程内协议/session元数据**；
其他协议、结果或会话错误继续清空。MCP会话与HTTP连接不同：
[Streamable HTTP会话规则](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
要求后续请求保留返回的session ID，会话失效可通过404反馈；限流本身不能证明
会话失效。这里也不保证匿名服务在整个冷却期后一定还保留会话。

请求仍先检查取消、原始截止时间及持久lease/cooldown；冷却期间只走Yahoo。
冷却后复用仍然有效的元数据，**不是清配额、换session或绕过授权**。404/非限流
协议错误继续使会话失效并走现有有界错误恢复；不新增同请求重试。真正进程冷启、
初始化失败和initialized通知限流时没有完整元数据，仍执行原来的完整握手。
该缓存不落盘、不跨进程，也不保存Cloud新鲜授权。

禁网回归先稳定复现 `rate limit discarded initialized session`，再修复通过：
已初始化会话遇限流后保留原协议和session header，连续冷却请求零Exa控制帧，
仅在**私有禁网测试的模拟时钟**到期后恢复tools/call，额外初始化/通知从2个
变0个；真实provider控制文件未修改。另验证404清空会话，真正冷启仍有2个控制帧，
既有Retry-After/跨进程冷却/并发lease/取消/截止时间检查通过。原有Cloud搜索/
DNS/工具检查37项通过，Ruff/格式通过，无新依赖。

收益边界：减少的是**限流后同一进程、会话仍有效时的重复控制请求**，不是消除
全部冷启动。按本次历史分段，两个控制往返约463.273ms；若空闲期间连接已断，
后续搜索仍需支付约206ms的建连/TLS，不能声称省下完整669ms。上述是基于既有
实测的潜在量级，**未做真实限流恢复耗时配对，不能称为已验收的延迟降幅**。
正常热查询无变化；新进程的真正冷初始化0.67秒仍然存在。

本轮不发任何新的Exa检索或控制请求，不主动耗尽额度制造限流。新可选镜像
`zebra-searxng:exa-cold-01`（同时更新本地`exa-optional-01`标签）已构建，
最终源码/原有取消补丁、默认仅Yahoo及native启动在禁网容器检查；正常服务不更新。
真实provider状态摘要和正常API/Worker/Search镜像、环境摘要、启动时间、重启数
前后相同。隔离容器清理，无模型/页面、Trench/全局代理修改、推送或部署。
证据 `.artifacts/cloud-exa-cold-01/`。后续真实自然限流恢复若有足够证据再配对，
不为此反复探测额度；收益稳定前不做页面验收。

### 真实恢复配对的样本缺口与保留规则

用户要求继续真实自然限流恢复验证后，再次核对：真实控制状态已过冷却、无在途
lease；旧Exa隔离容器均已移除。协议元数据按设计仅驻留内存，原始结果/日志未
保留可恢复的会话header。因此**目前没有可供恢复的原MCP会话**。正常搜索服务仍未注册Exa引擎（只准备了
可选镜像），当前也没有自然Exa流量可供被动观测。持久cooldown
不是会话快照；不能把重新建容器的冷启动或离线注入称作真实同会话恢复配对。

本次续查零Exa/模型请求，不用搜索循环耗尽额度，不清状态、不换出口或身份，
也不切换正常服务来制造样本。fast/Yahoo默认/冷却/回退不变。实际收益仍未验收，
约463ms仍只是旧分段推导，不能升级成实测结论。

下一次正常业务自然限流时，须保留发生限流的原进程及其内存协议元数据，直到
恢复验收完成再清理。仅记录会话是否保留的布尔值或不可逆摘要，不落盘/输出
原始session header。尊重完整cooldown/Retry-After；到期后以正常业务所需的一次
fast请求观察结果：有效同会话应无initialize/initialized，失效则按真实404等
现有错误路径处理并记录失败，不换身份重测。请求仍需新鲜授权与DNS/SSRF校验。

真实配对必须注明baseline/candidate的自然事件、查询/结果工作量、进程存续、
连接是否重建、控制帧数及tools/call/端到端耗时。没有可比baseline只能报告一次
恢复观测，不能宣称配对提升；不得为了A/B主动清除候选会话、恢复旧限流状态或
触发第二轮额度耗尽。当前不安排配额轮询或页面验收，等待真实业务事件。
只读就绪证据：`.artifacts/cloud-exa-cold-01/real-recovery-readiness.json`。

## 2026-10-17 正常服务接入：Exa 可选，Yahoo 默认

任务 CLOUD-EXA-LIVE-01，用户明确授权启用，不再等待真实恢复验收才注册引擎。
正常 `docker/web-search/compose.yml` 现在选择 `exa-optional-01` 及镜像内设置
快照。`/config` 实测 Yahoo enabled=true、Exa enabled=false/shortcut=exa；
disabled仅排除默认fan-out，显式`!exa`可选。Exa参数仍为fast/5条/1000字符，
无summary/highlights、livecrawlTimeout1000、moderation沿用原值。

`web.search` 参数说明补充“where enabled, !exa”，说明其限流及标记的Yahoo
回退。没有把来源选择写成固定规则，也没有额外研究流程提示。正常Worker实际
导入的工具contract已可见该说明；这是能力发现验证，不是已用模型证明自主选择。

上线前native禁网回归（含日志隐私、限流/冷却/lease/有效会话保留/取消/截止）
及现有37项Cloud搜索/DNS/工具检查通过，Ruff/格式通过。正常Search沿用原
search-cache命名卷，既有真实冷却文件先逐字节迁入该卷，再重建服务，未清零。
**上线后权威实时状态在正常容器 `/var/cache/searxng/zebra-exa-control.json`；
旧host artifact是历史证据，不再是正常服务的实时状态。** 原Yahoo缓存也保留。

Worker更新基于其精确运行镜像（arm64），只增加一个COPY层替换工具说明文件，
避免把累计源码全量部署。更新前检查0活跃Worker lease；现有environment值、
command、挂载、group/security均保留，API镜像与进程不变。环境/挂载列表顺序
可能由Compose重排，按原key顺序重建摘要确认值一致，不能把顺序差异当配置漂移。
正常启动的后续完整构建同样会包含仓库中的新工具说明。

通过正常Worker、现有证书/私有搜索endpoint、native可取消HTTPS transport，
固定一题做两次无模型功能请求（非性能配对）：

| 选择 | 结果 | Exa控制/检索帧 | Worker transport外层ms |
| --- | --- | ---: | ---: |
| 无前缀默认 | Yahoo返回5条，未命中预定Redis GA页 | 0 | 2067.034 |
| `!exa` | Exa返回5条，Redis GA官方页第一 | 3 | 1742.063 |

Exa的3帧为initialize458.693ms、initialized209.272ms、tools/call677.052ms；
session_ready=true，pid=1230。单题功能检查不能证明提速、稳定容量或真实恢复。
本轮无错误、限流或回退；不再追加查询。未发模型/Run/页面请求，不改Trench。
Search与Worker健康，API保持原状；Search原进程现在保留，不做验收后清理。

增加的生产日志仅含RPC阶段、HTTP状态、native curl数值计时、PID、会话是否
已初始化，以及已持久化的冷却原因/until。无query、结果正文、session header
或Cloud授权数据，无额外SQL。协议/配额/取消行为保持原样。

已注册同会话只读heartbeat `exa`（“Exa 自然限流恢复观察”），每5分钟读取
正常容器日志/状态，**没有新自然限流事件时不发任何Exa请求、不通知未变状态**。
只有普通业务产生新的rate_limit、session_ready=true、原PID/容器仍存续，且
完整cooldown已过、无lease/blocked时，才观察恢复。优先采用已经发生的普通
业务恢复，不另发请求；若尚无业务恢复，至多一次已授权固定公开题目的无模型
功能请求，先标记事件防重复。再次限流/错误即停止，不重试、不清状态或换出口。
进程丢失时不能重建冒充；得到一次可报告观测后删除该观察任务。

恢复时记录同PID的初始化/通知帧数及真实tools/call时间；没有可比真实baseline
只能称恢复观测，不宣称配对收益，不自动扩大到页面。当前仍未验收约463ms的
真实恢复节省。私有构建/配置保留/真实功能结果及运行摘要：
`.artifacts/cloud-exa-live-01/`。本地更新及集成，不推送或远端部署。


## 2026-10-18 正常配置与原进程观察终止

后续正常部署以 [CLOUD_SEARXNG_CONFIG.md](CLOUD_SEARXNG_CONFIG.md) 为准：
镜像默认 zebra-searxng:cloud-config-01，SEARXNG_SETTINGS_PATH 直接读取
/etc/searxng/settings.yml；Exa 显式注册进入同一挂载文件，仍disabled/fast/有界冷却与Yahoo回退。
此前历史镜像/构建命令及实验收据保留，不能把它们当作当前运行配置。

用户授权的 Search 配置实装于2026-10-18 01:19:16（上海时间）替换原进程。
原PID1230期间无自然限流，仅一次 initialize/initialized/tools-call，
因此 CLOUD-EXA-LIVE-01 没有得到真实同会话恢复证据。
原内存MCP会话随进程结束，未重建旧身份或清状态；持久控制文件逐字保留，
出口/引擎代码不变，新进程验收无Exa请求。按任务要求已删除exa heartbeat。
这是观察条件终止，不是恢复成功或初始化性能通过。
证据 .artifacts/cloud-searxng-config-01/{old-mcp-observation.json,after.json}。
