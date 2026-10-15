# Cloud 免费搜索通道接入验收

日期：2026-10-15。任务 SEARCH-FREE-PROVIDER-01，起点42b16483。

## 交付与范围

已找到并接入不需要新API凭据的可用通道：复用当前固定SearXNG镜像内的Yahoo适配器，
将其作为唯一默认引擎。Bing保持显式可选，原Sogou/360/公共微信选择器保留；不做
多引擎自动扇出或静默fallback，严格源失败仍按原方式报告。Agent自行决定搜索/抓取。

只有两份生产源/配置变更：docker/web-search/settings.yml启用Yahoo、禁用Bing默认；
agent_tools/web_search.py说明!yh并去掉写死的Bing默认提示，未带选择器时使用部署
默认。现有v1/v2共享契约继续复用，未新增依赖、Port、工具、结果评分器或运行时请求。
原参数/SSRF/证据账本/字节限制、fresh scalar、两路网络并行、v2和高思考均保留。

当前本地出口需要搜索容器自己的HTTPS_PROXY，使用已有正常代理；NO_PROXY排除
localhost/127.0.0.1。通过原docker/web-search/secrets/service.env注入标准环境变量，
不将本机地址写进可移植源码或Trench配置，不修改宿主DNS、Clash/TUN或全局代理。
其它部署可直连或设置自己的可用出口，但必须独立通过同一质量检查。

## 固定镜像与无模型资格检查

镜像仍245b675ff61b01a0ddace63abc095420c55393a55761a32b15274e25cfcdd1d5；
没有升级SearXNG。隔离容器不发布端口，使用原资源上限、普通验证TLS和既有出口。

| 新增筛选候选 | 第一条固定Redis8官方公告查询 |
| --- | --- |
| Yep |正常响应，无候选；未通过|
| Qwant |CAPTCHA；未通过、未解验证码|
| Mwmbl |5秒超时；未通过|
| Yahoo |首条命中Redis8 GA具体官方URL；进入完整资格集|

Mojeek与Startpage在源码预审中发现自动验证码求解逻辑，本轮未执行它们。
没有联邦抓取公共SearXNG实例、创建付费账号或利用固定业务URL绕过搜索。

Yahoo原生适配器在服务级代理配置下完成五条正例和一个域名控制：

- PG18英文公告查询 → PostgreSQL18 Released具体官方公告。
- Redis8英文GA查询 → redis.io/blog/redis-8-ga/。
- PG18中文发布日期/官方域限定 → 同一官方公告（另有官方中文Press Kit）。
- Redis8中文发布日期/官方域限定 → 同一GA官方公告，前五条内命中。
- Python3.14.0官方发布控制 → python.org/downloads/release/python-3140/。
- Redis8查询限定site:postgresql.org → 所有候选均在该域或其子域；只验证限定语义，
  不将这些弱相关PG结果称为Redis公告，也不把无结果当成不存在匹配内容的证明。

最初域控制诊断只允许apex/www，将合法ftp/wiki子域误标false；依site包含子域的
语义修正诊断，保留原回执和更正说明，未修改任何候选或生产域名准入规则。

独立冷实例直连两次5秒超时，随后原SearXNG暂停该通道；未将暂停响应算作真实请求。
同配置冷实例仅通过标准HTTPS_PROXY环境变量接入现有出口后，六项全部通过：首条
含原生YBV初始化2.643s，其余约0.764–1.291s。原生匿名YBV cookie缓存属于上游
HTTP会话，不缓存Cloud授权、停止状态或查询答案。相关行为见
[SearXNG官方Yahoo文档](https://docs.searxng.org/dev/engines/online/yahoo.html)。

生产原TLS搜索入口也经正常Worker执行新operator检查：两条均ready=true且确实
命中期待来源，不只是返回五个链接。真实页面B1前该检查已完成，因此B1属于已完成
上游初始化的样本；不将B1耗时冒充冷搜索首请求的表现。

## 真实页面配对

同一公开核对问题：PG18/Redis8正式发布日期、各两项特性及官方来源。两个新会话，
A1后B1，各Flash/high、主模型enabled/high、retry0、transient_v2、一个sandbox，
canonical completed；无失败工具事件。未重放旧Run、读取订阅或修改业务数据。

| 指标 | A1 原Bing默认 | B1 Yahoo默认 |
| --- | ---: | ---: |
| Host创建→完成 |33.898s|28.451s|
| 点击→首段公开正文 |5.540s|4.939s|
| 两家官方链接首次可见 |32.684s|26.660s|
| 主模型轮数 |4|3|
| 工具启动 |6|5|
| 成功搜索调用 |4|2|
| Worker显式SQL调用 |3246|2738|
| Task I/O新连接 |726|637|
| 网络等待区间并集 |8.389s|7.748s|
| 主模型HTTP区间并集 |9.421s|7.437s|
| 网络峰值并发 |2|2|
| 启动SQL / 连接 |415 /66|415 /66|

本次观察总耗时减少5.447s（16.1%）、Worker显式SQL少508次（15.7%）。不是稳定
p50/p95或系统SQL80%验收；模型与抓取选择不同，工具提示也更新，不将所有差值严格
归因于一个网络环节。首段正文是过程说明；链接可见不是完整语义终态。临时诊断有
开销，SQL范围仅同步Worker及标记工具线程的最外层cursor.execute，不含API/Host、
其它Worker和协议隐式语句，不是服务器全部查询数或v1/v2总收益。

直接路径证据：A1首轮两组搜索返回首页/教程，随后补搜再抓官方页面；B1首轮结果
分别以两家的具体公告为首条，不再补搜。A1实际4search+2fetch，B1实际2search+
3fetch（额外核对Redis官方GitHub文档），均有原生抓取成功回执；两侧均无artifact
补读。B1最终页面包含发布日期、特性与实际收集到的官方链接。

A1 Run2088b769-6e37-443f-a93a-68f38a97f3d6：
http://localhost:3000/dashboard/strategy/conv_1792057218922_4f0f96

B1 Run8113a1f9-374f-47c8-9ede-d4c211bf7a40：
http://localhost:3000/dashboard/strategy/conv_1792057364014_2355c6

## 针对性验证与正常本地运行

原配置/契约检查最初3失败/1通过；最小改动后72项相关检查通过，涵盖唯一默认引擎、
旧显式选择器、共享契约、operator质量边界、源完整性/失败、两路并行及线程上下文。
没有修改旧fixture、测试框架或SQL观测器。Ruff排除私有.artifacts、项目mypy1278
源文件、eval30及文件大小门通过；未执行完整pytest或把字面make check标为全绿。

正常Workerd6b720277ef48977df4cad1d162e946cfc49b0da279a1bafb2144c97f72f3cea，
仅在原d9d84e3c上覆盖工具契约文件；APIc0b8e9dc不变。Worker原六Compose、正常
entrypoint/command、healthy及32个已验收源hash复核；搜索服务保持原固定镜像、
正常入口和原一份Compose，挂载主checkout的Yahoo配置，代理经原env_file持久注入。
正常服务再次通过operator检查，页面正常入口重新加载已完成结果，没有再调用模型。

代码本地集成cloud-agent-trench，保留原27条无关脏改动。临时trace入口、浏览器
观察器、自有两个隔离容器/临时卷/随机secret配置及env变更临时副本已移除。
没有推送、npm发布、远端部署、改业务库或改动既有未提交DNS/参数恢复/SDK工作。

## 操作方式与限制

在需要代理的部署中，通过原服务env_file配置批准的HTTPS_PROXY出口及NO_PROXY，
然后使用原Compose更新searxng。无需把macOS地址引入Cloud源码。只有在没有活动
任务且配置质量检查完成后进行服务替换；上游不可用时不自动扩大查询或降级授权。

```sh
docker exec -i zebra-application-zebra-worker-1 /app/.venv/bin/python - \
  < docker/web-search/verify.py
```

当前本地默认两条质量检查应均ready=true。网页端可继续用原Trench入口人工测试。
免费通道没有可据本次测试承诺的SLA，上游拒绝/限流/索引和出口变化仍可能导致失败；
切换节点或部署后要重新做来源检查，不能只看/health。普通首正文仍约4.9s，本轮没有
实现稳定3s或完成STOP/GC/完整系统SQL门。

私有证据.artifacts/search-free-provider-20261015：四候选筛选、代理/直连/环境变量
冷实例资格集、operator回执、两次新Run的DOM/canonical/Worker与来源摘录、源码/
镜像/配置一致性记录及验收截图。未提交凭据、原HTML或临时诊断代码。
