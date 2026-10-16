# SEARCH-BODY-CRITICAL-01：真实搜索首正文拆解与最小优化

2026-10-16，owner Luke Ding，基线48e9d904。结论：移除了一次重复公网DNS/DoH预查询；固定网页抓取有局部收益，但新的四轮页面配对没有证明首正文或整轮净提速。高思考/v2和既有连接优化均保留。

## 21–26秒原始等待在哪里

复用上一组优化版B1/B2的Worker与DOM记录，以发送click为起点，在首正文时刻截断各区间；并行工具取区间并集，禁止相加重复计算。

| 首正文前阶段 | 上一组B1 | 上一组B2 |
|---|---:|---:|
| 模型请求区间，包括最终候选到首正文 |8.079s|8.158s|
| 网络工具区间并集 |12.749s|8.571s|
| 准入/编排/投影/页面同步剩余 |4.856s|4.536s|
| 首正文总计 |25.683s|21.265s|

剩余中包含模型前约2.44s；不是4.5s全在模型后。旧页面没有子进程DNS/TLS分段，不能倒推出历史每次DoH的具体耗时。模型多轮高思考和网络往返仍是主要耗时来源，本文不以减少思考、跳过来源校验或强制工具选择换分数。

## 当前根因与最小方案

六次正常Worker无模型原生HTTPS抓取分段（PG/Redis各三次）均200。当前系统DNS返回Fake-IP，因此public_addresses按现有规则回退到验证TLS的DoH。一次请求先在_proxy_configuration做公网预查询，随后PublicMcpHttpsConnection.connect重新解析、验证全部IP并固定真正连接的IP；前一次结果没有用于建连。实测前一次冗余lookup429–1015ms，第二次DoH393–2436ms，后者仍可能波动。DNS与其嵌套的TLS/响应头时间不能重复相加。

最小改动只涉及三个现有runtime源文件：

- proxy选择不再额外做公网DNS；实际直连仍由既有pinned HTTPS handler每次新鲜解析、验证并使用同一IP。没有跨请求DNS缓存。
- 保留抓取、旧search、新search_json的private_network_blocked错误分类：urllib会把PublicAddressBlocked包成URLError，三个适配器识别其reason并保留原策略含义；DNS故障仍为gateway_unavailable。
- 独立reject_non_public_resolution及MCP/其他显式调用者保持兼容；配置私有检索后端的精确endpoint准入、DNS校验不变。

每个实际连接仍拒绝任何私网/混合/多播/保留地址，证书验证及SNI使用原域名。原新鲜执行控制、50ms取消检查、父进程总截止/kill/reap、内容双cap、gzip、重定向拒绝和代理选择均保留。没有新Port、依赖、池、持久子进程、请求重试或全局网络设置。

## 确定性与固定网页验收

新增scripts/check_web_single_resolution.py，运行uv run python scripts/check_web_single_resolution.py。使用真实urllib handler与connect，仅替换DNS/socket/TLS peer，无网络、无fixture。基线两次请求产生4次DNS/DoH而失败；改后每个请求一次、第二个请求重新解析，三transport均通过，六个私网/混合地址案例在socket创建前拒绝，TLS仍校验主机名/证书。最终正常Worker内同一检查也通过。

已有聚焦回归首次149通过/1失败：原私网报错字符串仍要求non-public。保留该兼容文本后原失败单测通过；没有修改旧fixture或放宽断言。新脚本初始三个lambda触发Ruff，改为普通def；生产逻辑不因此改变。clean tracked-source make check通过Ruff/mypy1285/size3103/eval30及既有progress故障门。未声称全量pytest通过。

两个公开URL分别固定ABBA，共八次、每模式每URL两次；所有200，同URL的正文hash在A/B一致。两镜像均2CPU/512MiB，复用同一个正常Worker网络命名空间；进程新建，未清OS/CDN缓存，控制回调为空，不包括真实控制SQL。

| 原生抓取中位数 | A原逻辑 | B去重查询 |
|---|---:|---:|
| PostgreSQL18官方公告 |2.351s|1.755s|
| Redis8 GA官方博文 |2.493s|1.383s|

每次成功fetch的DoH2→1。Redis A样本3.447/1.539s波动很大；这些局部中位数不能外推为全页或稳定p50收益。

## 新一组真实页面配对

固定A1/B1/B2/A2，A为ce680c30原正常Worker，B为60052f35最小改动；同一API7eb869c9、相同临时聚合观察器和子进程分段观察器。每次重建Worker，API为同一诊断进程；API/搜索/数据库/Provider非全冷启动。模型看到的工具结果移除了诊断profile，未给模型新增性能提示。

同一已登录页面/账号、原PG18与Redis8官方发布日期/两特性问题，Flash、thinking=enabled、reasoning_effort=high、transient_v2逐个canonical核验。只有四个新Run，不重放旧Run、不为好成绩补跑。

| 样本 | 首正文 | Host整轮 | 模型轮数 | 工具成功/尝试 | Worker SQL | API SQL |
|---|---:|---:|---:|---:|---:|---:|
| A1 |15.543s|19.004s|3|4/4|2242|1048|
| B1 |15.960s|19.810s|3|4/4|2175|1041|
| B2 |24.295s|28.454s|5|6/7|3561|1497|
| A2 |21.790s|25.271s|4|6/6|3067|1341|

四轮均completed、answer_committed=1、turn_completed=1、无session_failed/新runtime_provisioned，15个模型回执均enabled/high/retry0；共21次工具尝试、20成功。B2抓取https://www.postgresql.org/docs/release/18/返回302，按原规则redirect_blocked，模型换用已取得的官方新闻稿及其他来源；失败与后续耗时全部保留，不归类为成功工具，也不扩大修复重定向策略。

| 首正文前独占阶段 | A1 | B1 | B2 | A2 |
|---|---:|---:|---:|---:|
| 模型区间并集 |5.167s|7.202s|10.089s|8.777s|
| 工具区间并集 |5.035s|4.650s|8.827s|7.894s|
| 其余（含启动、页面） |5.341s|4.108s|5.379s|5.119s|

实际成功fetch分段：A1/A2每次2个DoH，B1/B2每次1个DoH，页面中根因修复成立。但A1/B1即便都是3模型/4工具，B1模型等待增加约2.03s，首正文反而慢0.417s；其fetch批次也受网络波动影响，不能用总工具时间差倒推本修复独占收益。

两侧样本平均首正文18.666→20.128s（高7.8%），Host22.138→24.132s（高9.0%）。保留此不利结果，不宣称页面加速，也不直接认定为代码导致的回归：B侧多一个模型轮次均值且有302失败，样本不足以隔离。原生固定抓取及DoH次数才是局部收益证据。下一步大收益应继续定位Agent多轮取证/失败恢复的必要性和真实网络尾延迟，而非继续微调SQL并把结果算作整页改善。

Worker非空SQL均值2654.5→2868；含空探测execute2753→2977.5（+8.2%），API1194.5→1269；工作量不同，没有总体SQL下降结论。四轮模型前execute均448/新建有界连接均5，保留上轮连接收益；click到模型3.313/2.401/2.306/2.389s的波动不归因于本次DNS修改。

## 口径、证据与本地恢复

首正文口径同上一验收：发送click到MutationObserver首次看见答案开头16个非空白字符，包含待核验候选，排除过程和占位；不是单字符paint或最终接受时刻。DOM最后更新19.183/20.128/29.120/25.976s另存。每轮直接读取仍保留的DOM观察器计时/首段，保存紧凑记录，非完整mutation导出。B1过程只保留时间，文本位置是显式诊断标签。

SQL仅Worker执行scope及API请求开始落在click到Host completed+1s的scope；包括SET/reset，非空/空探测分开。流请求结束后才结算；不含Host、其他后台、隐式事务或服务器内部语句，不是系统全量SQL。后台时间窗快照不代替Run计数。

私有.artifacts/search-body-critical-20261016保留原生六次分段、固定八次配对、红绿/default门、三源fingerprint和正常服务核验；page-pair含四Run canonical/SQL/native fetch profiles/compact DOM、summarize.py与breakdown.py、page-B2.jpg。页面身份：

- A1 conv_1792161238555_3693cc
- B1 conv_1792161354787_a9e5c2
- B2 conv_1792161474777_71aa33
- A2 conv_1792161594468_8ad39d

准备/采集问题全部发生在证据路径：第一次表单尚在新会话异步导航，发送被disabled阻止，click为空，无模型；等待空白页后才发送A1。复用采集器一度把旧下载A1覆盖进私有文件，立即按当前CDP记录恢复、删除旧下载钩子，并加canonical会话/创建时间交叉校验，未重新调用模型。截图自动下载及waitForEvent失败；未改浏览器下载设置，现有截图经一次临时loopback文件接收器落盘，接收后已关闭，DOM临时链接/监听已移除。

四轮后恢复正常API7eb869c9/Worker60052f35，再仅修正同一源文件的过时注释并重建正常Worker435867aa；行为与配对B完全一致，没有追加模型。正常入口、原六Compose/env/commands/search保持；95源码指纹通过，API/Worker healthy、zero restarts，实际Worker边界检查通过。API确实因诊断/恢复重启；后续Worker注释覆盖未再次重启API。正常服务下B2原结果可读且高思考保留。

本地集成cloud-agent-trench时保护27项无关修改。无schema/event重写、旧Run重放、fixture清理、push/npm或远端部署。首正文10s、全系统SQL80%、STOP/GC/容量/多Worker等独立门继续OPEN；没有宣称整体重构完成。
