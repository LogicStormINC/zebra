# Cloud 搜索通道质量排查与验收修复

日期：2026-10-15。任务 SEARCH-PROVIDER-QUALITY-01，起点fc3c9c42。

## 当前结论与交付边界

已修复operator验收将无关搜索链接误判为ready的问题，未修复上游Bing检索质量。
当前没有通过本轮中英文官方公告查询验收的替代通道；用户确认暂时没有搜索API凭据，
先完成可落地修复。未引入付费API、账号或依赖，没有继续调用模型重复失败。
真实模型/页面性能配对未执行，不能报告模型轮数、SQL或总耗时的新收益。

正式代码只修改docker/web-search/verify.py；保留现有原生legacy/v2适配器、证据账本
与URL准入检查。另增加一个针对性测试文件，仅更新原诊断测试中的三个operator CLI
调用点以传入新约束，没有修旧schema/网络fixture或扩大测试基础设施。

## 根因证据

Cloud查询完整进入SearXNG；原生Bing适配器正确编码完整q并解析其结果。直接请求
Bing HTML，页面标题/输入仍是完整查询，但结果已经是Redis教程、首页、下载页等，
与SearXNG返回一致。因此本轮可确认的故障层在上游响应质量，并非本地丢词或解析
丢失了相关公告。Bing内部为何生成这些结果，当前无法从客户端确定。

已针对同一公开问题分别检查setlang、mkt、cc、HTML/RSS与普通/现有系统代理出口；
均未取得合格公告结果。没有把某一URL/参数猜测直接写进生产。
上游[问题4964](https://github.com/searxng/searxng/issues/4964)记录了同类首词匹配故障；
[PR6671](https://github.com/searxng/searxng/pull/6671)改用setlang/cc，当前固定镜像源码
已包含该修补，但此次本机仍复现，不能将“已包含上游修补”等同于质量恢复。

| 通道/组合 | 本次实际观察 | 判定 |
| --- | --- | --- |
| 当前Bing | 中英文完整查询返回泛化首页/教程；site限定仍出现范围外链接 | 公告检索不合格 |
| 360，原生显式选择 | 中文普通查询有相关第三方文章；英文限定PG无结果，Redis命中其他版本/主题 | 本轮官方公告集不合格 |
| Sogou | 三条限定查询均302到/antispider/；当前curl响应无next_request，原生适配器读取它时AttributeError | 不可用，未绕过验证码 |
| Google，固定镜像原生适配器与现有代理 | access denied；后续请求被SearXNG按原规则暂停 | 不可用 |
| Brave，同一隔离原生组合 | too many requests；原规则暂停 | 不可用 |
| DuckDuckGo，独立TLS验证解析 | 验证码挑战页 | 不可用，未解验证码 |

另观察到容器系统DNS给Google/DDG返回异常地址。仅在独立诊断请求中使用验证TLS的
DoH区分DNS与搜索通道问题；DNS恢复后仍遇到JS壳、拒绝或验证码，不构成替代通道。
未修改宿主DNS、Clash/TUN、生产搜索设置或Cloud授权边界。Sogou一次无site普通查询
HTTP200且无适配异常，不足以证明其限定公告查询可用；失败限定查询回执完整保留。

## 最小可落地修复：验收不再误报

原脚本仅要求executed、有证据引用、输出链接均来自账本，五个无关首页也能ready。
新脚本将传输成功和已知查询的来源约束分别记录：

- 默认两条固定公告查询分别要求命中已知PG18公告、Redis8 GA官方路径。
- 自定义每个--query必须对应一个--expect-source HTTPS来源约束；参数数量错误在网络
  调用前拒绝，来源语法复用parse_web_target，不接受私有字面地址/非法HTTPS目标。
- 来源匹配以实际收集到的证据引用为依据，比较scheme/origin和路径边界，防止同名前缀
  域名、查询参数内嵌URL、相似路径前缀或HTTP降级误匹配。允许末尾斜线与跟踪query；
  显式约束带query时要求一致。没有通过抓网页、增加模型或修改结果来制造命中。
- --transport-only只验传输，可以退出0，但ready仍为false，quality_checked=false；
  传输通过不再冒充搜索质量合格。打印只含布尔/计数/受控原因，不记录结果正文或凭据。

这是已知公开查询的canary约束检查，不能证明任意查询的语义正确。宽泛域名约束也
只证明命中该域名；官方公告验收应提供具体路径。运行时Agent仍决定查询/抓取策略，
未将这些固定验收问题放入Agent执行流程或增加每次用户请求的查询成本。

## 无模型真实验证与回归

同一正常Worker、同一搜索服务、同样两条公告查询：

| 脚本 | 传输/候选 | ready | 进程结果 |
| --- | --- | --- | --- |
| 原脚本，显式传相同query | 两条各5来源 | 两条true（误判） |0|
| 新默认质量检查 | 两条各5来源，预期路径均未命中 | 两条false，expected_source_missing |1（正确拒绝）|
| 新transport-only | 两条各5来源 | 两条false，quality_checked=false |0（仅传输）|
| 新自定义Redis官网导航查询 |5来源且包含明确期待的官网根路径 |true|0|

13项新增用例最初全失败；最终65项相关检查通过，包含真实legacy/v2组合的原operator
检查、源完整性、原生网络失败诊断与URL边界。首次相关回归有三个CLI调用点仍使用旧
参数，集中审计全部调用点后一次更新并验证，没有扩到无关fixture。
初次旧默认OpenAI探测一条ready真/一条因原URL账本门为假，该样本也保留；正式前后
对照使用完全相同的PG/Redis查询，不用不同query的结果混算修复效果。

Ruff（排除私有.artifacts）、项目mypy1278源文件、eval30与文件门通过。额外直接对
operator脚本做mypy仍有9项原有typing错误，旧版同样9项；未为此扩展修复范围，
也没有将此额外命令称作通过。未执行完整pytest或将字面make check标为全绿。

## 操作方式

从当前checkout将operator脚本经stdin送入正常Worker，无需重建或重启应用：

```sh
docker exec -i zebra-application-zebra-worker-1 /app/.venv/bin/python - \
  < docker/web-search/verify.py

docker exec -i zebra-application-zebra-worker-1 /app/.venv/bin/python - \
  --query 'Redis' --expect-source 'https://redis.io/' \
  < docker/web-search/verify.py

docker exec -i zebra-application-zebra-worker-1 /app/.venv/bin/python - \
  --transport-only --query '!360so Redis 8 发布 日期' \
  < docker/web-search/verify.py
```

第一条在当前环境应失败，表示该公告集质量未通过，不能据此宣布联网不可达。
后两条分别演示带明确来源的导航检查、仅传输检查，不替代第一条的公告质量标准。

## 本地状态与后续

生产搜索settings.yml保持原样，worktree/主checkout/容器内容hash一致。Worker仍为
正常d9d84e3c、API仍c0b8e9dc，原六Compose/entrypoint/command、healthy及31个既有
源hash核对。v2、高思考、两路并行、fresh scalar、启动/正文提取收益均未改动。
私有隔离搜索容器及其自有临时卷、随机secret配置已移除；没有调用模型、重放旧Run、
推送、远端部署或改业务库。operator修复本地集成cloud-agent-trench，保留原27条脏改动。

检索性能主目标保持未完成。继续免费方案需要先找到可用的服务出口/上游通道，并以
同一查询集通过后再启用；随后才做真实高思考页面配对。当前不盲目换默认引擎、不将
无关结果缓存起来、不通过降低思考强度掩盖等待，也不新增自动多引擎重试放大请求。

私有证据.artifacts/search-provider-quality-20261015：原始响应安全摘录、固定镜像原生
隔离通道验收、Sogou错误复现、matched-readiness、正例、red/focused/static日志及
设置一致性hash。原SearXNG镜像固定245b675f，未升级/替换正在运行的搜索服务。
