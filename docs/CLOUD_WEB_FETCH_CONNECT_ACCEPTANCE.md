# Cloud 网页抓取分段诊断与 gzip 优化验收

日期：2026-10-15。任务 WEB-FETCH-CONNECT-01，基线4ec1c8a6。

## 已证实的范围

已落地一个共享源文件、17行新增：标准Accept-Encoding:gzip协商，以及既有
_read_bounded_body内的双边界解压。没有新增依赖、重试、授权缓存、并发线程或SQL。
主攻抓取传输成本；没有将未重现的偶发超时宣称已经修好。

上一轮87645270的Redis GA博客失败detail明确为native network request deadline
exceeded，约10秒触发父进程总截止。其旧trace没有子进程阶段证据，不能倒推出
DNS/TLS/服务端/正文中的哪一阶段超时。本轮未重放该Run。

初始无模型Redis实测2.633s；追加两次Redis/一次PG固定公开页面均成功。分段结果：

- 导入模块850–901ms，发生在原生网络动作前。
- Redis DNS为公网IPv4；TCP约0.8–3ms，TLS345–474ms。
- Redis响应正文1692922字节，读取730–1167ms。
- PG包含IPv4/IPv6有效答案，实际首地址TCP成功；无地址选择失败证据。
- 没有复现10秒截止，故不做多地址fallback、超时延长或盲目重试。

独立importtime显示运行包初始化累计约1.03s，其中agent_core包入口约610ms，
agent_runtime.harness约390ms；这些是嵌套累计值，不能相加。网络子进程每次重新
导入，不是Worker只付一次的启动成本。本轮不扩大成多个包的导出结构重构。

## 最小改动与安全边界

普通内置fetch请求增加gzip协商。共用读取函数先按原规则读取最大maximum+1个
wire字节，核对压缩传输的Content-Length；再使用stdlib gzip.GzipFile读取最多
maximum+1个解压字节。任一侧超限仍response_too_large；截断、CRC/头/deflate错误
都response_incomplete，不将坏数据当作空正文或成功。原始identity响应保持不变。

解压后仍走相同字符集、可见main正文提取、投影和证据路径。byte_count保持返回的
HTML正文大小语义；本轮性能诊断另计wire字节，未增加生产元数据或持久化事件。

所有_read_bounded_body调用点已检查：fetch、legacy搜索及search_json共用边界。
只对fetch增加请求协商；其它收到gzip时也能正确、有界读取。HTTPS证书/SNI、公网
DNS/SSRF、禁止重定向、10s原生总截止与kill/reap、每50ms新鲜控制检查均未改动。

新增10项回归，先失败再修复：解码内容、wire/decoded双cap、Content-Length、
坏头/截断/尾随垃圾/坏deflate、identity/多成员流及协商后正文投影。连同既有TLS、
SSRF、原生取消、搜索后端、抓取源、两路并行和延迟沙箱，共211项通过。
Ruff排除私有.artifacts、mypy1278源文件、eval30与文件大小门通过；未跑全量pytest，
未把字面make check记成通过。只有本轮小测试文件，无旧fixture或测试系统修改。

## 同源固定输入 ABBA

同一候选镜像下Redis官方GA URL，顺序identity/gzip/gzip/identity；仅请求协商头
不同，不调用模型，不写业务库，每次新的进程/DNS/TLS。所有四次成功且解压后的
完整HTML sha256、最终投影文本sha256均相同。

| 指标（每种2次） | identity | gzip |
| --- | ---: | ---: |
| 正文传输字节 |1692922|418982|
| 解码HTML字节 |1692922|1692922|
| 正文读取中位数（含gzip解码） |658.559ms|398.382ms|
| 整个独立诊断进程中位数 |2272.408ms|2085.718ms|

正文传输减少75.25%，正文读取减少260ms（约39.5%），完整诊断约少187ms（8.2%）。
这里包含导入和阶段探针开销；只是同页小样本，不是站点通用p50/p95或全Agent收益。
单次初筛gzip约457ms，最终表使用ABBA而非挑最快请求。

## 新真实页面回归

只执行一次新真实高思考联网问题，Flash/high、transient_v2、所有6次模型回执为
thinking enabled/high、retry0。Run0db31430-bdc6-4abe-8bc1-bf4d60bc3362：
http://localhost:3000/dashboard/strategy/conv_1792059039150_63ec29

canonical completed，首段公开过程正文5.115s，两家官方链接首次可见43.532s，
Host创建→完成44.413s。7次实际handler全部成功（3search+4fetch），包含PG公告、
Redis发布入口、官方GitHub与Redis GA博客；博客handler约2469ms，本次没有原生
抓取超时。全部任务继续0沙箱/0OCI操作、网络峰值2、启动415SQL/66连接。

首轮另有2次policy侧invalid_tool_arguments失败：模型将limit传成字符串"5"；
它们没有进入网络handler，随后模型去掉该参数重试。该既有输入问题完整保留，没有
在本轮放宽类型校验或混入未提交的输入恢复工作。最终页面列出日期/特性/来源并说明
博客公告与GitHub标签时间不同；不把模型对两者时间差的解释当成独立验证事实。

全Worker显式cursor.execute4412，Task I/O新连接998，模型HTTP并集15.245s，
网络并集11.419s。SQL不含API/Host/其它线程或协议隐式语句。上一轮候选56.396s/
4722SQL与本次不是同工具选择的配对，不将差值归因于gzip。整体稳定延迟/系统SQL80%、
STOP/GC仍未完成验收，原偶发10s超时的具体阶段仍不明。

## 本地集成与下一步

正常Worker7be67b5c8645f0062bb37f7070b113be2447de9bb37f4914eb6023cd8e8e377f，
只在原c7a422d5覆盖web_gateway.py；恢复原六Compose、正常入口/命令并healthy。
APIc0b8e9dc、Yahoo搜索镜像245b675f及原配置/服务级环境不变，33累计源hash核对。
主checkout cloud-agent-trench本地集成并保留原27条无关脏改动；未推送/npm发布/
远端部署。临时trace入口和浏览器观察器撤除，正常页面重新加载原结果，不再调用模型。

私有证据.artifacts/web-fetch-connect-20261015包括旧失败安全摘录、分段探针、
importtime、ABBA字节/hash/时序、真实页面canonical/工具/模型/SQL与截图、正常源/
服务身份核对。未提交原HTML、凭据或临时探针代码。

后续可优先收窄网络子进程的包导入依赖：已测到每次约0.85–0.90秒；应单独限定
入口/依赖与兼容边界再改，不直接把安全校验或取消轮询去掉。原偶发超时若再出现，
仍需有子阶段证据才能确定修复，不能凭本次成功请求认定已经消除。
