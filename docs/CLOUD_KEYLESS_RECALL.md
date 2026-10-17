# 免密钥原生搜索配置资格检查

日期：2026-10-17。任务：CLOUD-KEYLESS-RECALL-01。基线 99247cb8。

## 结论

不晋级任何候选，不改 Yahoo 默认/回退，不做页面配对。
Google XML 在现有受控出口仍 HTTP403；DDG HTML 中文地区可用，但首次
官方来源命中2/4，Yahoo3/4。DDG 全部地区追加对照第一条即 CAPTCHA，停止。
这是有限真实无模型筛选结果，不是所有出口/地区/长期可用性的结论。
未发现足以支持生产配置变更的稳定来源召回收益。

## 为什么不是重复旧失败组合

先检查 zebra-stream-observer-repair/.artifacts/search-provider-quality-20261015
的 alternate_probe.py/proxy_probe.py/doh_probe.py 及此前验收报告。
Google 旧原生失败使用原本地代理；这次使用既有受控 SOCKS 出口。
旧 DDG 诊断是 HTML GET/独立 TLS；本次固定镜像 duckduckgo 原生 HTML POST
（正常首表单、地区及原生请求头），不执行 duckduckgo_web 挑战处理路径。
Google 当前已是 /wml/search XML，本次没有把 XML 当新实现。
改变条件分别是出口、原生请求流程；不是更换 UA/反复重试破解阻断。

## 配置与操作边界

镜像为运行中固定版本：
19f3942fe0f35b873854d86fc1a7fb9e2bcdf18fbdbdfd1035dcba7c9687ee69，
实际报告 SearXNG2026.10.11-ad46ebd7d。没有升级镜像/安装依赖。
独立临时容器 zebra-keyless-recall-01，原搜索网络、1CPU/512MiB/128pids，
不发布端口、不读取现有密钥、不挂现有缓存卷；临时服务密钥只在私有配置中。
候选 Google/DDG disabled=true,inactive=false，默认仍只有 Yahoo。
候选通过显式 engines 参数选择；query 正文、safe_search=1、5秒引擎/6秒总上限
一致。候选 retries=0；outgoing.proxies 使用既有受控 SOCKS，未创建或修改隧道。
离线原生 Network.iter_proxies 检查确认配置选择该出口，无系统代理继承。

Yahoo 对照直接请求正常搜索容器的本机 HTTP 接口，保留它真实出口、缓存及
原生重试配置；未使用临时容器内的 Yahoo。这里只做原生检索资格验证，
不是签名 Cloud 工具准入/浏览器 E2E。正常 Cloud 授权与安全源码完全未改。
既有 Cloud 新鲜授权、DNS/SSRF、请求级取消、高思考和 transient_v2 均保留；
不能用本次直接后端探测声称这些跨服务行为重新验收通过。

## 生成前冻结的初筛

四条查询和期待具体来源写入 private protocol.json，然后开始请求：

| 查询正文 | 目标来源 | Yahoo | DDG zh-CN |
| --- | --- | --- | --- |
| Redis 8 release announcement redis.io | redis.io/blog/redis-8-ga/ | 未命中 | 未命中 |
| PostgreSQL 18 released announcement postgresql.org | 官方18发布公告3142 | 命中 | 命中 |
| SQLite WAL 模式读写是否互相阻塞 官方文档 | SQLite官方wal.html | 命中 | 未命中 |
| Python 3.14 正式发布日期 官方 | 官方python-3140发布页 | 命中 | 命中 |

固定每题顺序 Yahoo→Google→DDG；任何引擎错误即停止该候选，不重试，
不把后续暂停响应当真实请求。Google 首条 access denied 后剩余三题跳过。
总计9次初筛：Yahoo4、DDG4、Google1，均返回JSON HTTP200；Google业务错误。
Google 日志记录真正上游 /wml/search 的 HTTP403，不是网络超时或暂停探测。

DDG 首条把 Redis Software release notes 排首位，GA链接来自 redis.ac.cn
镜像，原始全部10条也没有目标 redis.io 公告。不能把镜像当官方原始来源。
SQLite DDG全部10条均无期待官方文档；Yahoo首条就是官方 sqlite.org/wal.html。

初始自动严格匹配冻结的是 www.sqlite.org，漏计了 Yahoo 返回的官方 apex
sqlite.org。保留原始 found_top5=false 回执；人工核查后只给这个具体官方地址
增加接受别名，不泛化去掉所有来源的 www。官方文档参考
https://www.sqlite.org/wal.html。没有重新搜索或替换该样本。

另用现有 Cloud _normalize_response 离线处理同批结果：过滤不合规HTTP目标、
保留至多5条、失败引擎保持拒绝，所得官方来源命中仍为 Yahoo3/4、DDG2/4。
native_probe/script、原始公开结果、初始严格匹配和更正后离线结果均保留。

## 唯一追加配置对照及停止

首批 DDG 偏向中文转载/镜像，因此在任务卡先记录一个新假设：
仅把 DDG language 从 zh-CN 改为 all（原生kl=wt-wt），其余条件和四条查询
相同，每题一次，遇错停止。不改文本、不新增提示词或其他后端。
第一题1881.506ms返回CAPTCHA，立即结束；未执行另外三题。
不能确定 CAPTCHA 由语言参数、连续请求还是上游动态策略导致，
所以不能宣称 all 更差，也没有稳定性证据支持它。
总原生检索请求10次；无模型、无重试、无有利替换。

## 耗时的证据边界

| 初筛四题 | Yahoo | DDG zh-CN |
| --- | ---: | ---: |
| 耗时中位数ms |1123.547|848.465|
| 最小ms |800.180|720.144|
| 最大ms |1760.174|1148.414|
| 传输/解析成功 |4/4|4/4|
| 官方目标命中 |3/4|2/4|

DDG四题均较快，但顺序固定、容器与缓存状态不同、样本少；
这不是稳定 p50/p95、因果性能提升或首正文收益。更快却遗漏额外关键来源
不满足晋级标准。因此不开展12题两轮扩展、不配置生产候选、不做模型页面配对。
没有 SQL 或模型轮数的新降幅可报告。

## 清理与复核

临时容器已删除。正常 API/Worker/Search 的镜像、环境哈希、启动时间及
重启次数前后完全一致；生产 settings/Compose/Dockerfile 源码不改。
离线 Cloud 规范化检查、原生代理配置检查、文档差异检查通过。
诊断脚本最初命名locale.py误遮蔽标准库，在任何追加搜索前改名；
一个只读配置核查最初用了容器系统Python缺msgspec，随后用镜像venv在
network=none容器通过。均非上游请求重试，不修测试框架或生产逻辑。
私有证据位于 .artifacts/cloud-keyless-recall/；仅公开测试内容与服务哈希。
后续只有发现新的可用上游、相关适配器修复或实际出口条件变化才重开资格检查；
不重复本轮阻断组合，不以无限提示词/模型回放补偿缺失来源。
