# Zebra Web 能力原生化:Crawl4AI 接入与搜索重建方案 v1.0

## 1. 文档状态

- 规划任务:`WEB-PIPE-PLAN-01`(本文件)
- 关系定位:**修订** `WEB-INT-PLAN-01`(Wigolo 原生化计划 v1.0)的 Provider 策略;
  **收编** `docs/Zebra Agent Web Pipeline V2 完整修复方案.md` 为 Gateway 层实施规格
- 上游基线:
  - Crawl4AI:`github.com/unclecode/crawl4ai`,许可证 **Apache-2.0**,语言 **Python(async)**,
    当前文档版本 **v0.9.x**,核心能力 parallel crawl / chunk-based extraction / LLM 结构化抽取 /
    LLM-ready Markdown 输出;**无原生搜索能力**
  - 现行 Zebra 代码:`main`,审计点见 §3
- 当前决策:本方案进入任务计划;实施任务保持 `Locked`
- 启动条件:维护者显式选择一个 `Locked` 任务,改为 `Ready`,指定 owner、reviewer、
  branch、worktree 和最终 Owned paths
- **实施进度(2026-07-21)**:9 张实现卡(CON/SEC/STORE/PROJ/CRAWL/SEARCH/SEARCH-Q/OPS/E2E)的
  Zebra 自有逻辑已在 `zebra-agent` 仓库全部落地并通过离线测试(`make check` 全绿:mypy 0 issues /
  ruff clean / file-size gate / eval 1.00;`pytest` 1709 passed, 6 skipped)。真实 Crawl4AI 后端
  与浏览器二进制仍需 `WEB-PIPE-OPS-01` 经 Setup Phase 预置(dep-gated smoke 当前 skip)。剩余
  集成步骤见 §14——尚未在 `harness.py` 接线,模型当前仍见 legacy v1 的 `web.fetch`/`web.search`。

本文是把现行 `web.search` / `web.fetch` 工具与 Pipeline V2 重构目标,转化为基于 Crawl4AI
与搜索重建的 Zebra 原生能力的持久化设计依据。本文合入只代表架构、边界、任务和验收已建立,
不代表任何新增 Web 能力已经实现、部署或对模型开放。

## 2. 背景与结论

Zebra 现行 Web 能力分两块,各自有明显缺陷:

1. **抓取/读取(`web.fetch`)** 是单 URL 同步有界读取,刚把下载上限从 256 KiB 提到 2 MiB
   (PR #190),但仍是 Pipeline V2 §7.1 点名的旧结构:`max_bytes` 同时管下载与正文,无流式、
   无解压限制、无浏览器回退、无资源投影。Google Finance 这类重型 SPA 仍会失败或吐出低质正文。
2. **搜索(`web.search`)** 是单一后端(SearXNG JSON 适配器)上的贫血合同:结果硬上限 5 条、
   无 rerank、无新鲜度/域名过滤、输出纯文本、与 fetch 完全不衔接。且默认关闭,需 operator
   配置 `ZEBRA_WEB_SEARCH_ENDPOINT`。

目标用户诉求同时覆盖两类:解决 Pipeline V2 重型页面问题,**并把现行网络搜索工具全部替换掉**
(结果质量/覆盖率、合同强度、search↔fetch 衔接、结构化输出四项痛点全要解)。

经过对 Crawl4AI、wigolo、托管搜索 API 的横向评估(见 `WEB-INT-PLAN-01` 配套讨论),结论是:

1. **重型页面(fetch/crawl/extract)轴 → Crawl4AI**。它是 Apache-2.0、与 Zebra 同语言(Python)、
   能作真库依赖(`pip install crawl4ai`)直接调 `AsyncWebCrawler`,**没有 wigolo 那套 TS 进程
   边界与 30s/32KiB MCP stdio 限制**。许可证宽松,未来 vendor/部分 clean-room 也合法。
2. **搜索轴 → 不「换掉 SearXNG」,而是「换掉合同 + 加 provider registry」**。Zebra 定位是
   local-first / embeddable,一个零配置、免凭证、免 vendor egress 的本地 meta-search 是真实
   差异化价值。真正的痛在合同与衔接,不在后端本身。质量提升靠本地可做的杠杆(见 §8),
   托管 provider 作为 opt-in 逃生口经 Credential Broker 接入。
3. **两条轴共享一个 Zebra 自有的 Gateway 层**:转移预算、运行期 SSRF、压缩炸弹防护、统一结果
   信封、`resource_id` 投影、prompt-injection 标记。这是 Pipeline V2 的工程价值所在,但只作
   Gateway/投影规格,**不自建 transport/extractor**(那部分交给 Crawl4AI)。
4. **模型侧只发现稳定 `web.*` 合同**,不感知 Crawl4AI、SearXNG 或 Provider 配置;每次执行过
   Zebra Policy、Egress、预算和审计;Provider 可替换且 durable state 不变。

本方案因此同时**修订** Wigolo 计划:抓取/抽取 Provider 从「wigolo 进程」改为「Crawl4AI in-process
库」;`watch`/`research`/`gather` 不在本期范围,继续 `Locked`。

### 2.1 「原生能力」判定(沿用 `WEB-INT-PLAN-01` §2.1)

满足全部条件才可称为 Zebra 原生能力:

- 模型发现的是稳定 `web.*` 合同,不是 `crawl4ai.*` 或 `searxng.*`;
- 工具名、参数、结果、错误和 Artifact 合同由 Zebra 版本化(`capability_version`);
- 每次执行经过 Zebra Policy、Egress、预算和审计;
- Provider(Crawl4AI / 搜索后端)可替换,替换后模型侧合同与 durable state 不变;
- 完整结果进入 Zebra Artifact / 资源存储,模型只看到有界、可验证、标记截断的投影;
- 搜索结果→抓取→排序的综合只经过 Zebra 控制的路径(本地 rerank / 未来 Zebra Model Gateway);
- 抓取 Provider 输出始终视为不可信外部数据。

仅 `pip install crawl4ai` 并在工具里直接调,属于外部库依赖,不满足原生化口径。

## 3. 现状评估(现行代码审计)

审计锚点固定到以下 `main` 代码,激活任务时必须重新核验:

| 关注点 | 现行实现 | 文件 | 问题 |
|---|---|---|---|
| 抓取合同 | `web.fetch`,单 URL,`required=(url,)` | `packages/agent-tools/src/agent_tools/web_gateway.py` | 无 mode/question/extract;下载与正文预算混淆 |
| 抓取执行 | 同步 urllib,`DEFAULT_WEB_MAX_BYTES=2_097_152`(2 MiB) | `packages/agent-runtime/src/agent_runtime/web_gateway.py` | 一次性读入内存;无流式/解压限制/浏览器回退 |
| 抓取投影 | `max_output_bytes=262_144`(projector 模式)/ `65_536` | `packages/agent-runtime/src/agent_runtime/harness.py:216-219` | 大正文直接截断,无 `resource_id` 续读 |
| 搜索合同 | `web.search`,`MAX_WEB_SEARCH_RESULTS=5`,query ≤500 字符,输出纯文本 | `packages/agent-tools/src/agent_tools/web_search.py` | 5 条硬上限;无 rerank/新鲜度/域名;纯文本 |
| 搜索执行 | `LocalWebSearchTransport`,SearXNG JSON,同步 urllib,256 KiB 上限 | `packages/agent-runtime/src/agent_runtime/web_search.py` | 单一后端;`provider` 硬编码 `searxng` |
| 搜索装配 | 仅 `if search_endpoint is not None` 才注册 | `packages/agent-runtime/src/agent_runtime/harness.py:225-232` | **默认关闭**,需 operator 配置 |
| URL 守卫 | `parse_web_target`:HTTPS、无 userinfo/端口/fragment、非 localhost、非 IP literal | `packages/agent-core/src/agent_core/domain/web.py` | **仅解析期**;无运行期 SSRF |
| 安全层 | `policy`/`mcp_proxy_policy`/`external_policy`/`network_profile`/`setup_egress`/`broker`/`credentials`/`secret_store` | `packages/agent-security/src/agent_security/` | 无独立 `ssrf.py`;私网/metadata/rebinding 未覆盖 |
| 合同版本 | `ToolContract(name, required_arguments, description, argument_properties, parallel_safe)` | `packages/agent-tools/src/agent_tools/contracts.py` | **无 `capability_version`** |
| 配置入口 | `ZEBRA_WEB_SEARCH_ENDPOINT` → settings → CLI/API/Worker → harness | `apps/config/.../settings.py:128,203` | 仅一个 endpoint 字符串,无 provider 选择 |
| 本地研究 | `agent.research`(只读,用 files.read/search/git.status) | `packages/agent-runtime/src/agent_runtime/research.py` | 与 web 无关,本期不动 |

关键缺口(本方案必须闭合):

1. **运行期 SSRF 缺失**:`parse_web_target` 只在解析时拦 localhost/IP literal,不拦 DNS 解析后
   落到私网/链路本地/云 metadata(`169.254.169.254` 等)、不防 DNS rebinding、不在重定向后重验。
2. **预算混淆**:`max_bytes` 同时承担下载保护与正文限制(Pipeline V2 §7.1 五条问题原样存在)。
3. **搜索与抓取不衔接**:搜出来的 URL 不会自动抓取,Agent 必须手动串。
4. **无资源投影**:大正文只能截断,无 `resource_id` / `web.read` / `web.find` 续读。
5. **合同无版本**:无法做 Pipeline V2 §5.2 / Wigolo 计划 §5.2 要求的兼容演进。

## 4. 目标架构

```text
Model / Harness
  -> Zebra native web.* Tool contracts (versioned by capability_version)
  -> Policy / HITL / Network Profile / Egress / runtime SSRF
  -> Web Gateway(预算 / 信封 / resource_id 投影 / 取消 / 超时)
       |-- fetch/crawl/extract  -> Crawl4AI in-process provider (agent-integrations)
       |-- search               -> Search Provider Registry
                                     |-- SearXNG (本地默认, 免凭证)
                                     |-- future hosted (Credential Broker, opt-in)
       -> search->fetch->rerank 综合路径(本地 rerank)
  -> Artifact / Resource Store(provenance projection)
  -> Event Store / Tool Run / Context
```

### 4.1 分层职责(沿用 Wigolo 计划 §4.1,标注本期变化)

| 层 | 负责 | 不负责 |
|---|---|---|
| `agent-core` | `WebTarget`、稳定领域类型、`capability_version`、resource 领域类型 | Crawl4AI、Playwright、SearXNG 类型 |
| `agent-tools` | `web.*` 合同、参数验证、结果规范化、Provider-neutral transport Protocol、`ToolContract.capability_version` | 进程/浏览器生命周期、网络实现 |
| `agent-runtime` | transport 装配、预算执行、取消、超时、资源投影编排 | durable Watch(本期不做) |
| `agent-security` | Policy、Egress、**运行期 SSRF**、动作风险、凭证能力、压缩炸弹 | 页面解析、搜索排序 |
| `agent-storage` | web resource、chunk、FTS5 索引、去重、TTL | 把 web cache 变成 Session 权威 |
| `agent-integrations` | **Crawl4AI in-process adapter**、浏览器池、Setup 摘要校验 | Tool 业务合同与 Policy 决策 |
| `apps/*` | 配置(`ZEBRA_WEB_*`)、依赖组合、API/CLI/Worker 入口 | 核心规则与 Provider 专属领域逻辑 |

### 4.2 Crawl4AI Provider 运行方式(in-process,非 sidecar)

首期使用 **in-process Python 库**,而非受控常驻进程(这是相对 wigolo 的关键优势):

- 固定 Crawl4AI 版本,写入 `agent-integrations` 依赖,记录制品来源与 SHA-256;
- Crawl4AI 自带的 Playwright/浏览器二进制**必须进入 Zebra Setup Phase**,固定版本并校验摘要,
  **不允许首次 Tool Call 隐式下载安装**(沿用 Wigolo 计划 §3.2);
- Crawl4AI 的 HTTP/浏览器出站**必须经 Zebra 允许的 Egress 路径**(Network Profile),不能获得
  宿主任意网络;若 Crawl4AI 内置 fetcher 无法注入代理,则在 adapter 层用 Zebra 受控 transport
  预取或后置校验;
- 禁用 Crawl4AI 任何 telemetry、远程模型、自动升级、任意插件;
- Crawl4AI 是 **async**,Zebra 现行 transport 是同步 urllib——adapter 负责 async↔sync 桥接,
  或在 runtime 工具层引入 async 执行通道(任务卡评估);
- Crawl4AI 输出始终视为不可信外部数据,进入统一信封前过 content guard。

> 与 wigolo sidecar 的差异:无需 loopback token、无 30s/32KiB MCP 限制、无跨语言序列化。
> 但隔离性弱于进程边界——因此**预算与 SSRF 必须在 adapter 外层强约束**,不能信任 Crawl4AI
> 自报字节数或自限行为。

## 5. 原生合同设计

### 5.1 合同命名(本期范围)

保留并扩展 `web.fetch`;新增 crawl/extract/read/find;**重建** `web.search`:

- `web.fetch`(扩展):`url`、可选 `question`、`mode`(auto/http/browser)、`max_output_tokens`、
  `extract`(none/markdown/text/html/json-ld);
- `web.crawl`(新):`url`、`strategy`(bfs/dfs/sitemap)、`max_pages`、`max_depth`、`allow_browser`、
  `question`;
- `web.extract`(新):`url` 或 `resource_id`、`schema`(named/custom)、`selector`、`format`;
- `web.read`(新):`resource_id`、`cursor`(不透明)或 `offset`/`limit`、`max_output_tokens`;
- `web.find`(新):`resource_id`、`query`、`top_k`;
- `web.search`(重建):`query`、`limit`、`time_range`、`include_domains`、`exclude_domains`、
  `min_score`、`auto_fetch`(0..N)、`format`。

`watch.*`、`research`、`gather`、`diff`、`find_similar` **不在本期**(沿用 Wigolo 计划,
保持 `Locked`)。`web.cache.*` 由资源存储内化,不单独暴露给模型(见 §7)。

### 5.2 兼容与版本策略

- `web.fetch`/`web.search` 保持工具名、必需参数与当前文本输出兼容;
- 首个原生化版本只**增加可选参数**与 `ToolResult.metadata` 中的结构化 Web 信封;不提供新参数时
  行为不变;
- **新增 `ToolContract.capability_version`**(`contracts.py`),后续改变必需字段、默认值或输出
  语义必须发布新 `capability_version` + 迁移说明 + 双版本合同测试,不能原地改旧调用。

### 5.3 统一结果信封(Pipeline V2 §5 + Wigolo 计划 §5.3)

Web 结果至少包含:`provider`、`provider_version`、`capability_version`;`fetched_at`、规范化
URL、内容哈希、MIME type;`citations`、source span、freshness、证据评分(适用时);`truncated`、
`truncation_scope`、`degraded`、失败 backend、预算使用;`resource_id`、完整输出校验和、模型投影
大小;`untrusted_external_content=true`;稳定 error code、失败 stage、不泄露秘密的 detail。

Crawl4AI / SearXNG 专有字段可存 Provider metadata,但不成为跨 Provider 的必需模型合同。

### 5.4 资源存储边界(Web cache 内化)

资源存储是可删除、可重建的派生证据存储:**不替代** Event Store、Artifact、Task、Session 或
Agent Memory;`clear`/`refresh` 是 operator/生命周期操作,不暴露为模型 `web.cache.*`(本期);
命中必须返回抓取时间、内容哈希、TTL/stale 状态、来源;私有/认证内容不得跨 namespace 共享。

## 6. 安全与权限边界

### 6.1 运行期 SSRF(闭合 §3 缺口 1)

- `parse_web_target` 的解析期守卫保留(HTTPS、无 userinfo/端口/fragment、非 localhost/IP literal);
- **新增运行期校验**:URL 在 DNS 解析、连接、**每次重定向后**重新验证解析得到的 IP;
- 默认拒绝 RFC1918 私网(`10/8`、`172.16/12`、`192.168/16`)、链路本地(`169.254/16`,含云
  metadata `169.254.169.254`)、loopback、IPv6 loopback/link-local、非常规端口;
- 防 DNS rebinding(解析与连接之间校验解析结果一致);
- 最多 5 次重定向,重定向后重做 DNS+IP+SSRF+Policy;
- 禁止 `file://`/`ftp://`/`data://`;
- Crawl4AI 的浏览器出站使用与 HTTP 相同的 Egress/SSRF 策略;
- 建议在 `agent-security` 落地独立 `ssrf.py`(目前散落在 policy/network_profile)。

### 6.2 转移预算(闭合 §3 缺口 2,收编 Pipeline V2 §4)

五层预算彻底分离:`max_in_memory_bytes` / `max_wire_bytes` / `max_decoded_bytes` /
`max_clean_chars` / `max_projection_tokens` / `max_output_bytes` / `max_compression_ratio` /
`max_browser_network_bytes`。`max_wire_bytes` 与 `max_output_bytes` 完全独立——页面可下载数 MB,
提取后压缩到 `max_output_bytes` 以内。Crawl4AI 负责抓/抽/分块,**预算由 Zebra adapter 在其外层
强制**,并对 Crawl4AI 回传内容做 wire/decoded 校验(防压缩炸弹、内存放大穿透)。

### 6.3 浏览器动作风险(对齐 Wigolo 计划 §6.2)

只读动作(读取、scroll、wait、screenshot)按只读评估;`click`、`type`、认证 profile、下载或任何
提交状态的动作进入独立 Browser Action 风险分类,无法证明只读时要求审批。交易/发信/发布/删除等
外部副作用不在本期默认范围。

### 6.4 凭证与 prompt-injection

- 托管搜索/认证抓取只用 Zebra Credential Broker 签发的短时、窄 audience、窄 scope capability;
  原始 secret 不进参数、日志、Event、Artifact、资源目录;
- 所有 web 正文标记 `untrusted_external_content=true`;系统规则明确网页指令属待分析数据,不得据其
  自动执行 shell/文件改动/登录/转账(对齐 Pipeline V2 §23.2)。

## 7. 资源存储与投影(闭合 §3 缺口 3、4)

完整正文写入资源存储,模型只收 `resource_id` + 有界投影(Pipeline V2 §13–17):

- 文件布局:`<cache_root>/web/<resource_id>/{metadata.json,clean.md,chunks.jsonl}`(可选 `raw.html`);
- SQLite 表:`web_resource` + `web_chunk` + `web_chunk_fts`(FTS5);
- 去重优先级:URL+ETag → URL+Last-Modified → canonical URL+内容哈希 → 内容哈希;
- 同 URL 并发请求合并为单个 in-flight task;
- Projector:有 `question` 时 FTS5+BM25(可选 embedding)选 top-K 按原文顺序回排;无 `question`
  时返回标题/目录/开头/主要章节摘要/尾部注记 + `resource_id`;
- `web.read` 用不透明 cursor(比字符 offset 稳定,后续改分块不破接口);`web.find` 返回片段+标题
  路径+块号;cursor/resource_id 伪造必须拒绝;文件读取经 Resource Store 校验,**不向模型暴露磁盘路径**。

## 8. 搜索重建(闭合 §3 缺口 3,解用户四痛点)

### 8.1 合同重建(解「合同太弱」「输出纯文本」)

- 内部抓取上限上调(如 20),模型投影 top-K(默认 5–10,可配);
- 新增 `time_range`/`freshness`、`include_domains`/`exclude_domains`、`min_score`、`auto_fetch`、
  `format`;
- 输出改结构化信封(§5.3):每条结果带 score、canonical url、freshness、`fetch_status`、
  `artifact_uri`(若 auto_fetch);保留 `[UNTRUSTED ...]` 标记。

### 8.2 Provider Registry(解「单一后端」)

- 定义 `SearchProvider` Protocol(`agent-tools` 或 `agent-integrations`);
- **本地默认:SearXNG**(零配置、免凭证、免 vendor egress),保留 `LocalWebSearchTransport` 思路
  但迁出硬编码 `provider="searxng"`;
- **opt-in 托管**(Tavily/Brave/Exa 等)经 Credential Broker 接入,短时窄 audience 凭证;
- 配置扩展:`ZEBRA_WEB_SEARCH_PROVIDER`(默认 `searxng`)、`ZEBRA_WEB_SEARCH_ENDPOINT`、provider 专属
  凭证引用;CLI/API/Worker 透传。

### 8.3 质量杠杆(解「结果质量/覆盖率差」,且坚持本地免凭证)

用户明确选了「质量差」+「本地后端」——这两个靠纯合同重建解不了,需以下本地可做的杠杆:

1. **多 query 扩展 + RRF 融合**:对原 query 做受限改写/扩展,多发 SearXNG 查询,用 Reciprocal Rank
   Fusion 合并(本地、免费,这是 wigolo `search` 多查询的等价做法);
2. **Zebra 侧 rerank**:对 snippet 做 BM25/关键词覆盖评分;后续可选本地 cross-encoder;
3. **search→fetch→extract→rerank 闭环**(关键):`auto_fetch=N` 时用 Crawl4AI 抓 top-N 的真实正文,
   按内容与 query 的实际匹配重排,而非仅靠 snippet 关键词。这一项**同时**解掉「search 与 fetch 不
   衔接」——是同一处改动;
4. **SearXNG 引擎清单调优**:operator 配置更强的引擎组合(免 key 引擎优先),作为默认质量底座。

> 这四条均不改 local-first 定位、不需 vendor egress。托管 provider 仍是质量天花板不够时的 opt-in。

## 9. 任务拆解与依赖

本方案**修订** `WEB-INT-PLAN-01` 的任务卡。映射关系:

| Wigolo 计划卡 | 本方案处理 |
|---|---|
| `WEB-INT-CON-01`(原生合同) | **修订**:加 `capability_version` + 信封 + `resource_id` + 搜索重建合同 |
| `WEB-INT-ADP-01`(wigolo sidecar adapter) | **替换** → Crawl4AI in-process adapter(`WEB-PIPE-CRAWL-01`) |
| `WEB-INT-SEC-01`(Policy/Egress/SSRF) | **修订**:补运行期 SSRF + 独立 `ssrf.py` + 压缩炸弹 |
| `WEB-INT-TOOLS-01`(只读工具) | **拆分** → `WEB-PIPE-CRAWL-01`(fetch/crawl/extract)+ `WEB-PIPE-SEARCH-*` |
| `WEB-INT-CACHE-01` | **内化** → `WEB-PIPE-STORE-01`/`WEB-PIPE-PROJ-01`(资源存储,不暴露 cache.* 给模型) |
| `WEB-INT-OPS-01`(Setup) | **修订**:Crawl4AI + Playwright/浏览器固定版本+摘要校验,无隐式安装 |
| `WEB-INT-BROWSER-01`(受控动作/认证) | **保留 Locked**,本期只读 browser;动作风险分类就绪后再激活 |
| `WEB-INT-ORCH-01`(research/gather) | **保留 Locked**,不在本期 |
| `WEB-WATCH-*` | **保留 Locked**,不在本期 |
| `WEB-INT-E2E-01` | **修订** → `WEB-PIPE-E2E-01`(去 wigolo sidecar,加 Crawl4AI smoke + 离线确定性套件) |

本期任务图:

```text
WEB-PIPE-PLAN-01 (本文)
  -> WEB-PIPE-CON-01   (合同 + capability_version + 信封 + resource_id)
       -> WEB-PIPE-SEC-01   (运行期 SSRF + 预算 + 压缩炸弹 + prompt-injection)
            -> WEB-PIPE-CRAWL-01  (Crawl4AI in-process adapter: fetch/crawl/extract)
            -> WEB-PIPE-STORE-01  (资源存储: SQLite + FTS5 + chunker + 去重)
                 -> WEB-PIPE-PROJ-01  (projector + web.read + web.find + 不透明 cursor)
            -> WEB-PIPE-SEARCH-01  (重建 web.search 合同 + Provider Registry + SearXNG 默认)
                 -> WEB-PIPE-SEARCH-Q-01  (质量杠杆: 多query/RRF + rerank + search->fetch->rerank)
            -> WEB-PIPE-OPS-01  (Setup: Crawl4AI + 浏览器 固定版本/摘要/warmup/无隐式安装)
  -> WEB-PIPE-E2E-01  (合同矩阵 + 离线确定性 + 真实 Crawl4AI smoke + 安全矩阵)
     (等待 CRAWL / STORE / PROJ / SEARCH / SEARCH-Q / OPS 全部合入)
```

阶段交付(初始状态全部 `Locked`,本文为 `Review`):

| 任务 | 交付边界 |
|---|---|
| `WEB-PIPE-PLAN-01` | 本文 + 任务卡 + 进度与 docs 索引 |
| `WEB-PIPE-CON-01` | 原生合同、`capability_version`、结果信封、Provider-neutral Protocol |
| `WEB-PIPE-SEC-01` | 运行期 SSRF、五层预算、压缩炸弹、prompt-injection 标记 |
| `WEB-PIPE-CRAWL-01` | Crawl4AI in-process adapter:fetch/crawl/extract + async 桥接 + 预算外层 |
| `WEB-PIPE-STORE-01` | SQLite 资源/chunk/FTS5 schema、chunker、去重、TTL |
| `WEB-PIPE-PROJ-01` | projector + `web.read` + `web.find` + 不透明 cursor + 路径保护 |
| `WEB-PIPE-SEARCH-01` | 重建 `web.search` 合同 + Provider Registry + SearXNG 默认 |
| `WEB-PIPE-SEARCH-Q-01` | 多 query/RRF + rerank + search→fetch→rerank 闭环 |
| `WEB-PIPE-OPS-01` | Setup:Crawl4AI/Playwright 固定版本+摘要、warmup、无隐式安装 |
| `WEB-PIPE-E2E-01` | 合同矩阵、真实 Crawl4AI smoke、离线确定性、安全回归 |

任务状态、owner、branch、Owned paths 以 `docs/AGENT_TASKS.md` 为唯一执行依据;本文依赖图不等同
允许共享路径并行开发——共享 `agent-tools`/`agent-runtime`/`agent-security` 的 sibling 卡不得同时
`In Progress`。

## 10. 验收标准

### 10.1 合同与功能

- `web.fetch`/`web.crawl`/`web.extract`/`web.search`/`web.read`/`web.find` 全部为 Zebra 原生合同,
  模型侧不出现 `crawl4ai.*`/`searxng.*`;
- 所有输入有大小、数量、格式、互斥字段校验;
- 大输出保留完整资源,模型投影可验证且明确标记 `truncation_scope`;
- Provider failure/degraded/stale/partial 不伪装成成功空结果;
- 换 SearXNG→test double 或换 Crawl4AI→alternate 时原生合同测试仍通过。

### 10.2 安全与恢复

- SSRF fixture 覆盖 redirect、DNS rebinding、IP literal、localhost、private range、云 metadata、
  userinfo、port、Webhook;
- 运行期 SSRF 在 DNS 解析后与每次重定向后生效,不止于解析期;
- 压缩炸弹(小 wire → 大 decoded)被 `max_compression_ratio` 阻断;
- secret scan 证明凭证不进事件、日志、Artifact、SQLite、资源目录;
- timeout、cancel、Crawl4AI 异常、Worker 重启行为确定;
- Provider 不能修改 Policy、tool profile、Session state 或系统指令。

### 10.3 搜索质量(解四痛点)

- 重建合同后:结果数可 >5(投影 top-K 可配)、带 score/freshness/domain、结构化信封;
- `auto_fetch=N` 时 top-N 被 Crawl4AI 抓取并按真实内容重排(search↔fetch 衔接成立);
- 多 query/RRF + rerank 在固定 fixture 上对 recall/top-K 有可度量提升(Eval 记录);
- provider 可切换(SearXNG ↔ test double ↔ 托管 stub),合同不变。

### 10.4 Eval 与发布

- 固定 HTML/PDF/SPA/robots/sitemap/redirect/challenge fixture;
- fetch/crawl/extract/search Eval 记录正确性、引用覆盖、来源质量、耗时、Tool/Model 次数;
- 至少一条真实 Crawl4AI smoke 和一条完全离线确定性套件(mock Crawl4AI);
- API/CLI/Worker 对相同 durable state 一致;
- `make test`、`make check`、file-size gate 通过;SBOM、安装/升级/清理/rollback 说明齐全。

## 11. 与现有文档的关系

- **`Wigolo_Web_Intelligence原生化架构与实施计划_v1.0.md`**:本方案修订其 Provider 策略
  (wigolo sidecar → Crawl4AI in-process,抓取/抽取轴)并收编其合同/信封/安全设计;`watch`/
  `research`/`gather` 不变,继续 `Locked`。
- **`Zebra Agent Web Pipeline V2 完整修复方案.md`**:本方案**收编**其为 Gateway 层实施规格
  (预算模型、SSRF、信封、projector、resource_id),但**不自建** HttpTransport/BrowserTransport/
  extractors/chunker(交给 Crawl4AI)。Pipeline V2 的 `RoutePlanner` 退化为 Web Gateway 的 Provider
  路由。
- **`docs/AGENT_TASKS.md`**:本文为 `Review` 后,需在 AGENT_TASKS.md 落 `WEB-PIPE-*` 卡并标注对
  `WEB-INT-*` 卡的修订/替换关系。
- **`PROGRESS.md`**:在 `WEB-PIPE-E2E-01` 全部验收合入前,只能报告已完成的规划/合同/Provider/单项
  能力,不得声明「web 能力已全面原生化」。

## 12. 非目标

- 本规划任务不修改代码、不安装 Crawl4AI、不下载浏览器;
- 不 vendoring Crawl4AI 源码(Apache-2.0 允许,但首期仍只依赖未修改上游包);
- 不引入 wigolo(AGPL)进抓取/抽取轴;
- 不做 `watch`/`research`/`gather`/`diff`/`find_similar`(保持 Locked);
- 不把 web cache 暴露为模型 `web.cache.*`;
- 不建立第二套 Harness/Session/Credential Store/Memory;
- 认证网站与有副作用的浏览器自动化必须等 `WEB-INT-BROWSER-01` 独立激活;
- 不因本文合入改变 ACP、代码智能或私有云任务状态。

## 13. 激活与完成规则

1. 当前只有 `WEB-PIPE-PLAN-01` 进入 `Review`;所有实现任务保持 `Locked`;
2. 每次只解锁一个满足依赖的任务,补齐 owner、reviewer、worktree、精确 Owned paths;
3. 任务需扩大权限、引入真实凭证、修改上游或突破 Owned paths 时停止评审;
4. 每个任务单独分支、worktree、PR,不把 Crawl/Store/Proj/Search/Sec 合并;
5. 只有 `WEB-PIPE-E2E-01` 全部验收合入后,`PROGRESS.md` 才能声明抓取/搜索原生化完成;
6. 在此之前只能准确报告已完成的规划、合同、Provider 或单项能力,不能报告「现行网络搜索工具已
   全部替换为原生能力」。

## 14. 实施进度与剩余集成(2026-07-21)

### 14.1 已落地并离线验证(zebra-agent 仓库)

| 卡 | 产物 | 测试 |
|---|---|---|
| `WEB-PIPE-CON-01` | `ToolContract.capability_version`;`agent_core.domain.web.TruncationScope`;`agent_core.domain.web_resource`(WebResourceId + 只读 view + StorePort);`agent_tools.web_envelope.WebResultEnvelope` | 21 |
| `WEB-PIPE-SEC-01` | `agent_security.ssrf`(运行期 SSRF / `RedirectBudget` / `CompressionRatioGuard`);`agent_security.content_guard`(注入标注) | 25 |
| `WEB-PIPE-STORE-01` | `agent_storage.web_chunker`;`agent_storage.web_resource`(SQLite `web_resource`/`web_chunk`/`web_chunk_fts` FTS5 + 去重 + TTL + `WebResourceStoreAdapter`) | 8 |
| `WEB-PIPE-PROJ-01` | `agent_tools.web_projection`(`WebProjector` + 不透明 `ReadCursor` + `web.read`/`web.find` 工具) | 8 |
| `WEB-PIPE-CRAWL-01` | `agent_tools.web_crawl`(`web.fetch` v2 / `web.crawl` / `web.extract` 合同 + `FetchProvider`/`CrawlGatewayPort`);`agent_runtime.crawl_gateway`(`CrawlGateway` + import-guarded `Crawl4AIFetchProvider`) | 7 |
| `WEB-PIPE-SEARCH-01` | `agent_tools.search_pipeline`(重建 `web.search` v2 合同 + `SearchProvider`/`Registry`);`agent_runtime.search_providers.SearXNGSearchProvider` | 12 |
| `WEB-PIPE-SEARCH-Q-01` | `expand_query` + `reciprocal_rank_fusion` + `rerank_hits` + search→fetch→rerank 闭环 | (同上 12) |
| `WEB-PIPE-OPS-01` | `agent_runtime.web_setup`(版本固定 + 摘要清单 + 就绪探针 + 无隐式安装) | 4 |
| `WEB-PIPE-E2E-01` | 合同矩阵 + 离线端到端 + 安全 fixture + dep-gated Crawl4AI smoke | 17 |

门禁:`make check` 全绿(ruff clean / mypy 0 issues over 440 files / file-size gate / eval 1.00);
`pytest` 1709 passed, 6 skipped。新增包依赖:`agent-runtime` → `agent-storage`(无环)。

### 14.2 剩余集成步骤(未做,如实标注)

1. ~~**harness 接线**~~ **已完成(灰度)**:v2 工具链(`web.fetch` v2 / `web.crawl` / `web.extract` /
   `web.read` / `web.find` + 重建 `web.search`)已接入 `agent_runtime.harness`,经
   `web_pipeline_v2` 开关 + `ZEBRA_WEB_PIPELINE_V2` 环境变量控制;**CLI 已透传该开关**(灰度 live)。
   v1 仍为默认——因为 worker 的 durable network authority(`tests/worker/test_approved_continuation.py`
   守护)尚未由 v2 复刻,故 **API/Worker 暂不透传开关,保持 v1**。新增 `agent_runtime/fetch_providers.py`
   (无 crawl4ai 也能跑的 `LocalHttpFetchProvider`)与 `agent_runtime/web_tools.py`(v2 装配)。
2. **配置面**:已加 `web_pipeline_v2`(`ZEBRA_WEB_PIPELINE_V2`)。`ZEBRA_WEB_SEARCH_PROVIDER`、
   资源存储路径(`.zebra-agent/web_resources.sqlite` 当前由 workspace 派生)等仍待产品化。
3. **legacy 迁移**:旧 `web_search.py`/`web_gateway.py`(v1)及其测试仍在(v1 默认路径在用);
   v2 全量切换后需移除/迁移。
4. **真实 Crawl4AI 后端**:`Crawl4AIFetchProvider.fetch` 的 `arun()` 映射按 v0.9.x 文档编写但**未经
   真实安装验证**(沙箱无法装包+浏览器)。需经 `WEB-PIPE-OPS-01` 预置后跑 dep-gated smoke。
5. **async 桥**:Crawl4AI 是 async,gateway 当前用 `asyncio.run` 同步桥接;真实负载可能需 async 执行通道。
6. **durable network authority 对齐**:v2 经 `CrawlGateway`+`resolve_and_validate` 自带运行期 SSRF,
   但尚未复刻 v1 经 Policy/durable network profile 的「执行恰好一次 + 审批投影」语义——这是
   把 v2 默认切换到 Worker 的前置条件。

按 §13.6,在 worker durable-authority 对齐 + 真实后端 smoke 完成前,不得声明「现行网络搜索工具已全部
替换为原生能力」。当前状态:**9 卡 Zebra 自有逻辑全部实现并离线验证;v2 已灰度接线(CLI live,
经 `ZEBRA_WEB_PIPELINE_V2`);全量替换的前置是 durable-authority 对齐与真实 Crawl4AI 后端**。
