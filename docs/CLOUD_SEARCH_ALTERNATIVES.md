# 首次来源召回：免密钥替代路线

2026-10-17；CLOUD-SEARCH-ALTERNATIVES-01。用户取消 Brave，进一步明确优先免密钥。
本轮是路线评估及移除未使用的 Brave 配置，不是新后端上线或性能验收。

## 当前结论

保持 Yahoo 默认。下一项有意义的低成本验证是：现有固定 SearXNG 的 Google
及 DuckDuckGo HTML 原生引擎，在已存在的受控出口上是否具备可用的第二检索通道。
这仍可能失败，不能直接承诺替换 Yahoo，更不能宣称免费上游有可保证的 SLA。
只在原生接口或实际出口与旧失败记录存在可证实差异时做新资格检查；
完全相同的已失败组合不重复跑，不以换名字/重装包当新方案。

此前本机 Google 拒绝、DDG 验证码、Bing 相关性不足，见
CLOUD_SEARCH_PROVIDER_QUALITY_ACCEPTANCE.md；Yahoo 宽查询缺 GA 来源，
不是前五条裁切或已验证的语言配置问题，见 CLOUD_B1_BATCH_BOUNDARY.md。
旧失败不能当作当前全路线永不可用的证明，也不能无视旧失败直接配置生产默认。

## 最小路线及停止条件

1. 比对旧失败请求的实际出口、原生请求目标、解析器版本；当前固定 Google
   已走 /wml/search XML，不能把换到这个已存在路径宣传为新修复。
2. 用已有受控 egress 隔离测试 Google XML / DDG HTML 的正常公开请求。
   只使用既有依赖、验证 TLS，保留 DNS/SSRF 与请求取消；无 CAPTCHA 求解、
   挑战绕过、身份轮换或公共 SearXNG 实例池。
3. 每条具备新差异的候选先执行四条固定真实查询（中英文版本公告、技术语义、
   近期信息），每条最多一次。出现拒绝、验证码、空结果或错误版本均保留。
   若只有阻断而没有有效来源，不扩大重试或增加引擎。没有差异则跳过这一轮。
4. 候选初筛通过后，固定 12 条未加业务来源限制的首次查询，各两次，
   与 Yahoo 交错配对。核对具体来源及版本覆盖，而非 HTTP200 或命中官网域名。
   记录前五条可回答性、冷热耗时、失败率，不调用模型。
5. 只有来源覆盖改善且新增网络等待不抵消少一次补救往返的收益，才准备
   可选显式引擎配置。Yahoo 默认/回退先保留，不自动广播或按关键词路由。
   随后有限高思考/transient_v2 页面配对，agent 自己决定工具和停止。

这条路线无需 API 密钥/搜索调用账单；仍有当前出口和维护成本。
同一上游的原生引擎故障与网络故障分别记录；暂停响应不能计作上游真实成功。
预期收益来自少一次补救搜索/模型往返，不是必然加快单次 HTTP；目前未测新收益。
初筛预计数小时内可以得出继续/停止结论，不能无限调试上游抓取。
全部不合格时明确保留 Yahoo 及其召回限制，不靠提示词或并发多个坏后端掩盖问题。

## 已排除或暂缓

- 本机原生 DDG Web 实现含自动 JS 挑战处理，不直接执行此路径；选 HTML
  正常响应流程，遇到挑战停止。Mojeek 原生 request 会先求解 ALTCHA，
  Startpage 含 Anubis 求解，均不直接作为这轮最小原生候选。
- Jina Reader 的免密钥读取网页不等于免密钥搜索；当前官方表格中 s.jina.ai
  无密钥被禁用，不能将其列为免费匿名搜索替代品。
- Serper：官方称 2500 次免绑卡试用，但仍要注册/密钥；非本轮优先路线。
- Exa：当前官方免费计划免付款方式；镜像自带 exaapi，但原生适配器请求
  highlights，需额外核清检索/摘录行为与计费。仍需密钥，本轮不实施。
- Tavily：每月 1000 免费 credits 免绑卡，但仍需密钥，本轮不实施。

无新模型/回放/提示词、工具合同或 Trench 改动；不改全局代理，
不降低逐次新鲜授权、高思考和 v2。未注册账号、付费或改变运行服务。

官方参考：
- [Google 原生实现](https://docs.searxng.org/dev/engines/online/google.html)
- [DuckDuckGo 原生实现](https://docs.searxng.org/dev/engines/online/duckduckgo.html)
- [Jina 当前访问限制](https://jina.ai/reader/)
- [Serper 试用](https://serper.dev/)
- [Exa 免费计划](https://exa.ai/pricing)
- [Tavily credits](https://docs.tavily.com/documentation/api-credits)
