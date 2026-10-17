# Cloud 搜索首正文剩余关键路径

2026-10-17，CLOUD-SEARCH-CRITICAL-PATH-01。结论：当前约12秒不是一个未修复的
12秒启动阻塞。本轮完成诊断与原配置页面复验，没有可据此验收的新性能补丁。
保留已接受的 Cloud egress、Yahoo 线路、逐次新鲜授权/DNS/SSRF/取消、高思考及
transient_v2。未改 Trench、Provider 配置、生产代码或正常运行服务。

## 口径与可复核拆分

首正文采用最终可见答案去空白后的前16字符首次出现在可见 Markdown 的时间。
它不是首 token，也不是过程文字、占位符或 canonical answer_committed。
时间从页面 Send 事件起算；完成取 Trench canonical completed_at_ms。

以下读取上轮两个已启用线路的真实页面记录，未重放任何旧 Run。各行互不重叠，
相加严格等于首正文。模型区间含请求准备/事件回执；工具区间含运行时及事件回执，
不能等同于纯网络。并行工具取区间并集，不把两路时长相加。

| 区间 | B1 | B2 | 本轮 R2 |
| --- | ---: | ---: | ---: |
| Send→首个模型开始事件 |2.492s|2.261s|3.062s|
| 前两轮模型开始→响应事件 |2.500s|2.214s|2.239s|
| 并行搜索区间 |2.767s|2.386s|2.252s|
| 并行抓取区间 |2.013s|1.736s|1.699s|
| 最终模型开始→可见答案前16字符 |2.797s|1.931s|2.786s|
| 阶段衔接余量 |0.714s|0.902s|0.805s|
| 首正文合计 |13.282s|11.430s|12.844s|
| Send→canonical完成 |16.266s|14.311s|16.717s|

前两轮是模型选择搜索，再根据结果选择抓取，最后生成答案。三个样本均3模型轮、
2search+2fetch、0失败、0Provider重试；不将必要取证链删成无工具直接回答。
B1/B2 前两轮 Provider 自报完整耗时分别1032/1242ms、939/1016ms。
最终候选 TTFT1805/1389ms，最终完整 Provider4411/3848ms。
完整候选耗时晚于首正文，不能整段加进首正文。

Provider首SSE事件分别195/209/150ms、178/190/217ms。
最终候选 reasoning_tokens243/184；这些计数不等于推理耗时。
首SSE可能只是role/空delta；无法据此把后续时间严格分解为排队、prefill和思考。
公开正文前还包含生成、共用coalescer、授权流传递、首16字符积累和浏览器呈现。
不把这些合计差值全部叫渲染延迟或纯模型思考。

## 模型连接和上下文核查

Worker main.py 已在进程生命周期中共享 httpx.Client，工具间的模型请求继续复用它。
不是每轮新建模型客户端；本轮不叠加第二个连接池，也不改高思考/模型。
B1/B2 第2轮提示词缓存命中5888token，第3轮7040token，已存在有效续接缓存。
最终新增未命中约5912–5943token，主要伴随必要抓取结果；不能据此认定都是冗余。
工具schema17044bytes。稳定schema、源码中已排序工具及现有缓存不应重复“修复”。

最终抓取正文PG约14887bytes、Redis16036bytes。Redis提供文本/Markdown，PG经
HTML投影。没有引入有损摘要、来源白名单硬编码、固定工具轮数或自动替代取证。

## 本轮无模型实测

在正常已接受 Worker9953a04d 的原生 child 运行两批search→fetch，每批两路并行，
Cloud egress及Yahoo新线路始终启用。仅注入原有分段观察器，不覆盖生产模块。
8工具请求全部成功，父进程取消检查回调108/98次，子进程均关闭回收。
回调在此隔离探针中仅计数，**不能当成真实身份撤销/STOP授权验收**。
生产授权代码完全未改；本轮无新增安全行为变更需发布。

| 项目 | 批次1 | 批次2 |
| --- | ---: | ---: |
| 冷child双搜索合计 |1259ms|1168ms|
| 同child双抓取合计 |1555ms|1291ms|
| child stdlib+runtime导入 |约320–324ms|约320–322ms|
| Search TLS |2.5–3.2ms|3.8–4.3ms|
| Search等待响应头 |813–869ms|743–788ms|
| PG新鲜DNS/DoH |693ms|289ms|
| PG TLS / 等待响应头 |282 /245ms|267 /284ms|
| Redis新鲜DNS/DoH |268ms|308ms|
| Redis TLS / 等待响应头 |48 /83ms|50 /69ms|
| PG正文投影 |4.69ms|4.51ms|
| Redis正文投影 |0.03ms|0.02ms|

DNS/DoH包含本地解析、CA、受控SOCKS连接、DoH TLS及上游回答，不是纯DNS服务器
CPU。阶段观察可能嵌套，不能把表中包含区间相加。不同查询、时刻及授权回调的
native结果与页面不是相同工作量，不能直接相减后把差值全部归因于授权SQL。
当前公开工具链主要时间在外部等待，正文投影只有数毫秒；拒绝为其增加解析框架。
未运行新native A/B，因为尚无得到证据支持的重复操作补丁。

私有探针初始有导入路径、缺少limit、map括号错误，均在发出完整两批之前修正；
其中缺少limit未发出网络，括号错误阶段已发出两次search。它们不属于性能配对样本，
不计入以上8次成功工具，也未隐瞒为零流量。错误日志保留，临时子进程目录已清理。

## 两次新页面复验与失败样本

相同公开PG18/Redis8问题、原配置、高思考/Flash/transient_v2、自主工具选择。
不是修改前后的A/B。没有候选补丁，因此不能宣称新增性能收益或SQL下降。

- R1 Run cfe6486e-95fb-4c49-9ec7-201cb75fd8d1，canonical completed，4模型、
  3search+2fetch、零工具失败/Provider重试。Run创建→完成19.653s。
  页面 http://localhost:3000/dashboard/strategy/conv_1792229660425_34935a 。
  临时DOM计时脚本字符串转义错误，未安装成功；没有有效Send/首正文时刻。
  此Run保留，不补跑替换，不拿created_at伪造Send时间。
- R2 Run 5db61536-4c71-406e-9b39-23677920102e，canonical completed，3模型、
  2search+2fetch、零工具失败/Provider重试；首正文12.844s，Send→完成16.717s。
  页面 http://localhost:3000/dashboard/strategy/conv_1792229735293_2d918d 。
  观察器安装返回ready后才发送。最终DOM、官方来源、canonical状态及high回执对账。

R1多一次搜索的原因已核对：第一次Redis结果只有release入口、Redis Software
release notes、第三方版本站和GitHub列表，**没有GA博客**；模型随后在PG抓取同时
以blog/May2025细化Redis查询，才得到GA博客并抓取。不能把这一必要缺口修复称为
无效重复搜索，也不能以R2少一轮直接计算“本轮优化收益”。

两次均抓取PG官方发布公告及Redis GA博客，页面显示日期、特性和官方链接。
首正文的R1计时缺失使本轮不构成有效双样本首正文配对；没有第三次/替换模型Run。
没有SQL观察器，SQL数量与下降百分比本轮均**未测量**。

## 最小方案与优先级判断

1. 保留当前网络与模型实现。本轮未发现安全可删的重复模型/工具操作，不将高思考
   降档、不强迫3轮封顶、不减少新鲜检查、不截掉正文来制造性能收益。
2. 从平台可控时间看，下一轮应优先追踪通用Cloud首个模型之前的2.26–3.06s。
   复用现有transport与连接，找真正重复的准入/初始化操作；一次新鲜身份授权不能删。
   本轮只有canonical开始事件，尚不能声称已定位其中某个慢SQL，需独立精确任务。
3. 若继续限定网络方向，最小可测假设是：在已执行的search等待期间准备同child的
   DoH TLS transport，后续fetch仍重新发DNS查询、验证完整答案和连接目标。
   当前DoH TLS约88–100ms，外加连接/CA建立，所以收益上限可能只是百毫秒量级，
   不是再省几秒。需要先证明预连接在真实链路可重用且稳定获益；不能把预热改成
   DNS/授权缓存。线程所有权、取消回收、搜索后无fetch的额外资源必须先验证。
   目前不实现这个有并发成本、收益尚不足证实的预热器。
4. 模型侧若需继续归因，使用现有临时Provider观察器增加首个语义delta数值时刻，
   区分首空SSE与思考/工具/正文；不记录私有思考。先做一次有明确候选的实验，
   不再为了“12秒必须下降”反复运行相同页面。

“下一步最有价值”是转向通用启动准入的可控等待，而不是再写搜索/解析微优化。
约12秒不是不可降低的理论下限；也没有证据支持在当前质量、安全和自主决策条件下，
用另一个小补丁就稳定降到几秒。本轮交付的是这一判断的证据及可运行对账脚本。

## 校验、状态和重现

```sh
python scripts/check_cloud_search_critical_path.py .artifacts/cloud-yahoo-first-request B1 B2
python scripts/check_cloud_search_critical_path.py .artifacts/cloud-search-critical-path R2
ruff check scripts/check_cloud_search_critical_path.py
git diff --check
```

脚本只读取本任务公开测试的本地私有证据；验证高思考/v2/零重试、工具配对、区间
不重叠、总和及canonical完成，不会查询数据库、网络或调用模型。原始正文/私有证据
不提交。无模型阶段观察复用已有探针，只记录阶段与字节数。

正常APIeb4f695b/Worker9953a04d/Search19f3942f保持；无重启、镜像/环境/代理修改。
未集成之前未验收的progress/thread复用代码，未扩修fixture或跑全量测试。
浏览器临时DOM观察器、事件绑定和本地receiver均撤除；R2完成页保留。
源代码本轮仅新增离线对账脚本，无生产性能改动、迁移、推送或远端部署。
私有证据保留在feature worktree的.artifacts/cloud-search-critical-path/。
