# 新免密钥检索通道：真实无模型资格检查

2026-10-17；CLOUD-KEYLESS-PROVIDER-02；基线8dd4aac1。

## 决策

找到有实际召回价值的新渠道：Exa官方匿名托管MCP，区别于需密钥的REST API。
初筛4/4官方目标命中，补回Yahoo缺失的RedisGA公告；但扩展批次出现匿名限流，
没有稳定性验收通过，不能替换默认或启动页面配对。
Seznam、Swisscows和Yandex原生通道未胜出；停止本轮，不继续换参数重测。
正常Yahoo默认/回退及全部运行服务不变，无模型/Run/提示词/Trench改动。

## 网络调研筛选

| 候选 | 一手来源与本地源码核对 | 处置 |
| --- | --- | --- |
| Exa官方托管MCP | 官方明确免APIkey；实际initialize/tools-list匿名200 | 优先真实检索 |
| Seznam | 固定镜像已有原生HTML适配器，首页正常表单/cookie，不解挑战 | 新原生筛选 |
| Swisscows | 固定镜像JSON适配器，正常nonce/signature请求头，非CAPTCHA解算 | 新原生筛选 |
| Yandex | 固定镜像原生web站内搜索接口，search_type=web；不调用验证码求解 | 新原生筛选 |
| Stract | 原搜索仓库已归档，当前官网转为媒体关系/PR产品 | 不按旧搜索教程搭建 |
| Marginalia | 官方API要key；public用于开发且经常限流，免费许可非商业 | 非本项目免密钥生产默认候选 |
| Mwmbl/Yep/Qwant/Google/DDG/Bing | 此前组合已有超时/阻断/召回失败记录 | 不重复这些组合 |

无账号注册、付费、新依赖、公共实例池或绕过挑战。本次未调用Mojeek、
Startpage或DDG Web内置求解逻辑。

一手参考：
- [Exa托管MCP免密钥入口](https://exa.ai/mcp)
- [Exa仓库：匿名限流、工具与认证](https://github.com/exa-labs/exa-mcp-server)
- [Exa高级检索原生源码](https://raw.githubusercontent.com/exa-labs/exa-mcp-server/main/src/tools/webSearchAdvanced.ts)
- [Seznam原生实现](https://github.com/searxng/searxng/blob/master/searx/engines/seznam.py)
- [Stract现官网](https://stract.com/)与[已归档搜索仓库](https://github.com/StractOrg/stract)
- [Marginalia官方API限制](https://about.marginalia-search.com/article/api/)

## Exa真实匿名访问

固定官方 https://mcp.exa.ai/mcp，未提供Authorization/x-api-key/OAuth或账号。
通过现有受控SOCKS，验证TLS、不跟随重定向，curl_cffi为现有依赖。
默认web_search_exa的在线schema另要求objective；为保持相同query及避免
新增指令，选择官方支持的可选web_search_advanced_exa，先读取实际tools/list。
实际调用参数在检索前冻结：fast、numResults=5、enableSummary=false、
enableHighlights=false、textMaxCharacters=1000、livecrawlTimeout=2000。
不设置域过滤、additionalQueries、subpages、摘要或agent_run，不改query正文。
fast是请求参数，服务响应resolvedSearchType为空，内部执行类型不可据此确认。
响应包含逐条明确URL/title/text的JSON，离线复用Cloud规范化至最多5个来源，
不从正文任意提取URL当来源，不把官方镜像站当原始官网。

这里只直接验证提供方检索，不是Cloud授权/浏览器E2E。未调用Agent模型，
也未请求Exa Agent/summary；无法观测提供方内部算法或基础设施。

### 初筛四题

使用前轮四条原始宽查询（Redis8、PG18、SQLiteWAL中文、Python3.14中文），
期待具体官方URL集合在请求前冻结，SQLite含apex/www两种官方地址。
Yahoo/Exa按AB/BA/BA/AB交错，双方同query，每题一次，不重试。

| 指标 | Yahoo | Exa匿名MCP |
| --- | ---: | ---: |
| 官方目标命中 |3/4|4/4|
| 错误 |0|0|
| 请求中位数ms |1004.150|639.878|
| 最慢ms |1831.270|686.495|

Exa首题第一条就是redis.io/blog/redis-8-ga/，没有新提示词或自动补搜。
连接初始化/工具发现单独记录，不计入检索请求耗时；与Yahoo容器内直连
本机HTTP入口的对照不等于完整Cloud端到端成本或严格同transport比较。

### 固定12题两轮扩展（未通过，含协议偏差）

原四题加Node22首次LTS、SQLiteRETURNING限制、PGMVCC、PythonTaskGroup、
Rust所有权、Go1.25、TS5.9、React19；官方页面先核查，输入/参数/期望集合
在请求前写入expanded-protocol.json。每题两次，每轮反转请求顺序，共48次。
预定门槛：无错误、目标命中提升>=15pp、无逐题退化、耗时不变差，才评估接入。

**探针协议偏差：** 服务3次返回HTTP200、未标isError的普通文本，内容是免费
MCP限流。探针只检查HTTP/RPC/isError，没在首条文本限流后停止，48个固定
请求已全部发出。没有重试同一个样本、替换失败、换身份/出口或重新测限额。
完整扩展批次不作为稳定性验收；后续成功不能消除前面的限流。
限流发生在TaskGroup-r1、Go-r1、Go-r2，不推断固定分钟/月配额或重置时间。
离线分析将非预期结构文本拒绝为错误，未扩大修复测试框架或生产SDK。

| 全部请求口径 | Yahoo | Exa |
| --- | ---: | ---: |
| 检索请求 |24|24|
| 限流/错误 |0|3|
| 预冻结精确目标命中 |16/24|19/24|
| 官方多语言页面人工核查后 |16/24|21/24|

Node两次返回nodejs.org/zh-cn/blog/release/v22.11.0，预冻结只含英文路径。
核查确认是同一官方发布说明；原19/24评分保留，21/24是另存的事后人工校正，
不修改协议、不据此补判晋级。参考[官方中文版](https://nodejs.org/zh-cn/blog/release/v22.11.0)。
Yahoo的Node查询均无候选，不是被归一化丢失。
成功请求中位数Yahoo853.275ms、Exa624.645ms，Exa只剩21次成功请求，
不能排除3次限流后声称稳定加速。Go两次Exa限流而Yahoo命中，本身已违背无退化。
因此即使存在召回潜力，稳定性门槛仍失败；不启动模型/页面实验。

## 三个新原生通道

同一固定SearXNG镜像19f3942f、受控SOCKS、5秒引擎/6秒上限、重试0，
独立临时容器、不发布端口、不读取现有密钥/缓存。默认仍只有Yahoo；
候选disabled=true/inactive=false，逐次显式选择。Yahoo对照仍取正常容器。
相同四条查询，每题每通道一次；首个错误或空响应即停止该候选。

| 通道 | 请求/结果 | Cloud最多五条中的预定官方目标 |
| --- | --- | --- |
| Yahoo对照 |4成功|3/4|
| Seznam |首题约3044ms超时，停止|0/1|
| Swisscows zh-CN |4成功|1/4|
| Yandex web |4成功|0/4|

Seznam源码首页引导get有独立3秒timeout，不能把配置5秒误认为每个前置请求
都拥有5秒；本次未扩大预算或修改适配器。
Swisscows包含有用的Redis官方版本说明，但不是目标GA公告；不能把1/4解释成
只有一个官方域名。Yandex的首页/新闻档案等不满足期待事件/语义来源。
这些是本批具体目标覆盖，不是对所有查询或搜索引擎的泛化质量排名。

Swisscows的中文结果含大量区域镜像，源码明确all映射en-US；追加前在任务卡
冻结唯一地区配置对照：相同四题、language=all，不改query。4次均成功，
目标仍1/4，Redis仍缺GA；SQLite目标在完整结果中出现但未进入规范化前五条。
不继续调排序/扩条数或反复换地区。Yandex中文本来就不附语言参数，未做无效重复。

## 总请求、保留收益及下一实施边界

总计73次检索请求：Exa28、Yahoo32、Seznam1、Swisscows8、Yandex4，
另8次MCP初始化/通知/发现；官方资料浏览不计入检索性能样本。
正常API/Worker/Search镜像、环境哈希、启动时间/重启次数前后相同，
临时原生容器已删除；源码settings/Compose/Dockerfile及packages/apps均未修改。
新鲜授权、DNS/SSRF、取消、高思考、transient_v2和Trench保持原路径。
没有新的SQL/模型轮数/页面首正文改善可报告。
私有公开测试证据、原始/规范化/人工校正分开保留于.artifacts/cloud-keyless-provider-02/。

值得保留的工程候选只有Exa匿名MCP低频补充：首先正确拒绝HTTP200文本限流、
设置有界冷却及明确Yahoo回退，不能借换身份/无界重试维持可用，也不保证匿名容量。
若以后接入，优先复用现有CloudMcpTransport的精确目录绑定和逐帧新鲜授权；
还要验证受控出口、DNS/SSRF、请求级取消和输出边界，不能直接用本次curl探针
取代生产安全链路。匿名限流未解决前不改默认，不进入页面配对。
