# AGUI-LONG-SESSION-20261028：协议与长会话验收

## 结论与范围

2026-10-28 完成 Cloud AG-UI → Trench 观察／持久化 → 历史恢复的集中审计。
确认并修复两个审批续接缺口。核心隔离门禁 387 项通过，无跳过项；
另完成浏览器长历史验收和接近 1 MiB 正文的真实 HTTP 断线恢复。
不代表“所有环境永不失败”，也不代表重新验收了模型输出质量或供应商可用性。

本轮没有调用模型、执行网络搜索、重跑业务 Run、代用户审批或更改原任务终态。
只更新线上 Trench API；Cloud API、Worker、搜索、MCP、出口和数据库 schema 不变。

## 发现与修复

### 1. 审批误用控制权限的 grant

审批 BFF 复用了 client-surface 的 `_call`，该路径只申请 `agent.run`，
没有本轮业务来源／主题权限。上轮 Cloud 增加执行 binding 续期后，
会把这个控制用 grant 当作后续执行权限，导致原本可用的业务工具被收窄。

修复：批准时从已验证归属的原 Turn 请求恢复来源／主题与用户工作区，复用
正常执行 `_grant`，交由 Broker 重新校验当前权限。该 grant 只用于本次审批请求；
Cloud 仍验证原冻结身份、权限上限、取消、租约和唯一 Run。GET／拒绝保留原控制路径。
没有扩大冻结权限，没有保存 JWT，没有自动重试 POST。

确定性回归先失败，再修复通过；覆盖真实 `_call` 对请求 Authorization 的选择，
原来源／主题恢复、失去回执后的 GET 对账、拒绝不唤醒与旧 Turn 回执拒绝。

### 2. 同一 Run 多次审批后，早期暂停没有完整结算记录

原实现只保存最后一条审批回执。断线／进程重启后全量回放仍可能遇到更早的
已批准暂停，观察器把它误认为当前需要再次审批的终态。

修复：同一 Turn 保留有界的已确认审批集合，兼容旧单回执；恢复时只跳过集合
中精确匹配的历史审批暂停。新审批、未知审批、澄清、失败和取消仍正常停止。
集合不生成执行权限、不批准任何新动作；最多 1000 条，匹配集合只构建一次。

回归覆盖同一 Run 连续三次审批、进程重建后的回执恢复、第四次未批准暂停仍阻塞，
以及旧回执不能改动后来新 Turn。

## 核心门禁

一条命令复用现有测试，不引入框架／依赖，不触碰运行中的产品服务：

```bash
TRENCH_REPO=/absolute/path/Trench \
TRENCH_PYTHON=/absolute/path/trench-venv/bin/python \
ZEBRA_NODE_BIN=/absolute/path/node \
tests/conformance/agui_long_session/run.sh
```

需要已有本地 `postgres:17-alpine`、`redis:8.2.1-alpine`、Python／前端依赖。
脚本创建独占的临时 PG／Redis，退出时只删除自己创建的资源和卷。
证据写入 `.artifacts/`。缺少原生端点或 wire 产物不会被核心门禁静默跳过。

| 层 | 通过数 | 主要覆盖 |
|---|---:|---|
| Cloud 原生 PG／Redis | 75 | session/task/AG-UI 三种入口、v2 协商、游标签名／篡改／跨范围、部分帧恢复、Redis 黑洞、PG 故障、期限、取消、租约、审批续期／原 Run 去重、真实编码器 |
| Host／历史／审批 | 116 | 原生 PG 和 SQLite、真实 HTTP 半条记录断线、持久化终态、1000 轮历史、正文分片、预算、授权、反馈／建议保存与恢复、重复审批与旧回执 |
| 前端 | 196 | Turn 恢复、流式解析、历史缓存、版本去重、建议不重复生成、审批按钮、正文恢复、反馈、复制／下载／导出和报告动作的成功／失败处理 |
| 浏览器 | 单独验收 | 1000 轮 fixture、历史分页／窗口化、滚动锚点、媒体持续播放、直播增长、分片、待确认提交上限 |

核心通过数不与扩展回归重复相加。扩展 Host 回归另有 276 通过、20 跳过；
跳过项主要依赖旧的固定端口原生资源 fixture，不纳入核心已通过声明。

## 长会话实测

### 原生数据库

隔离的同一会话：1000 Turn、2000 消息、20000 事件；旧 Turn 保持 partial。
最后一条消息含超出历史页预算的 1.1 MB 工具元数据。

| 检查 | SQLite | PostgreSQL |
|---|---:|---:|
| 快照 SQL 数 | 9 | 8 |
| 快照耗时（该次样本） | 23 ms | 47 ms |
| 完整历史页数 | 42 | 42 |
| 正文恢复分片数 | 12 | 12 |
| 翻页消息数／唯一数 | 2000／2000 | 2000／2000 |

耗时是本机隔离样本，不是线上 SLO。确认：新 Turn 不混入旧分页的固定范围；
无重复／遗漏；错误用户／工作区不能读取；反馈和已保存建议刷新后保留；
大工具元数据不阻断正文；原文、工具证据和 partial 状态完整保留。

### 真实编码与 HTTP

使用 Cloud 当前 `canonical_wire`、`StreamV2Reader._signed`、游标 codec 生成帧，
由隔离 loopback HTTP 服务发送；真实 httpx／SSE／v2 解码器／mapper 处理，
再写入真实 PostgreSQL 和 SQLite。此路径没有拦截浏览器或 HTTP 响应。

初次流在半条 SSE 记录处关闭；接收端从最后完整 ACK 的游标 GET 恢复，
正文和工具结果各出现一次，原 Run 身份保持，最终 completed 正常落库。

- 初始组合门禁：154 帧、278528 字节正文、627 字符最长游标。
- 加强样本：428 帧、1020000 字节正文、627 字符最长游标。
- 两路数据库各通过；每例两个 GET、零模型请求。
- 正文 SHA256 与编码前完全一致；大工具结果和终态一并验证。

### 浏览器长历史

复用真实组件与安装的 SDK；API 是本地 fixture，此项不是生产联调或模型验收。

- 21 页读取后缓存 72 Turn、114628 字节；挂载 13 Turn。
- 阅读锚点变化 0.0625px；101 个 live 帧增长时锚点变化 0。
- 四个活动媒体节点保持同一实例并持续播放。
- 300022 字符正文经 74 个分片完整取回。
- 四个明确提交处于等待确认；第五个在 POST 前拒绝；刷新自动 POST 为 0。

## 测试本身的审计

一次集中原生回归发现三个旧 fixture 与当前契约不符，集中修正后 74 项原生验证通过：

1. 测试用 Redis seal 注入误作用于黑洞读客户端；现在只作用于该 fixture 的写端地址。
2. handoff fixture 没有传入当前已要求的冻结容量策略；补齐真实准入参数。
3. Source-head HTTP harness 使用旧的 `StreamSettings` 位置参数；改用命名参数。

没有通过放宽生产配额、授权或超时来制造通过。较广的 SQLite 诊断测试首次在
并行重负载下有两个 30 秒期限失败；原样隔离重跑两例均通过，共 30.87 秒。
原全量批次被停止，没有宣称整个仓库全绿；重型冷恢复基线不并入本轮性能结论。

## 安全边界与未声称项

- 单条 canonical Event 仍受 1 MiB 限制；大结果应按既有 Artifact／分片契约处理。
- 前端单消息缓存仍为 256 KiB、总历史缓存仍为 3 MiB；自动正文恢复最多 64 个
  4096 字符分片。超出范围保留明确的分片读取，不能宣称任意大正文都自动整块显示。
- 正常执行预算、权限撤销、取消和真实上游故障仍可能让任务暂停／失败；
  不能把它们伪装为成功，也不能靠观察恢复重新执行模型或工具。
- 本轮没有重新进行线上真实模型／真实工具执行验收。工具结果在协议测试中是
  保存／合成的事实输入；真实传输与真实数据库不等于再次执行外部工具。
- 证书轮换必须更新常驻 HTTP 客户端连接池，并验证真实签名观察链路；只测新建
  客户端 `/health` 不足以证明常驻客户端已更新。这是运维发布检查，不是自动续证功能。

## 部署

仅 idle Trench API 更新为 `trench-api:agui-long-session-20261028`，
镜像 `sha256:298e24a67aa6b76a8ea75049f75f3cebe60b1a5854a4e851a07554444600d974`。
环境、挂载、安全设置保持一致，schema 仍为 `d3e4f5a6b7c8`。
原审批 Run 仍是 90 事件／4 个旧模型调用／1 次批准，canonical 哈希未变。
Worker、Search、Search TLS、Yahoo 出口保持原进程；没有重启 MCP。

首次部署检查被无关 pgAdmin 的既有自动重启打断；Trench API 已正常更新。
后续只读校验精确受保护服务和原 Run，没有重复部署或回滚。
私有发布证据和回滚基线：`/home/ubuntu/releases/20261028-agui-long-session`。
本地证据：`.artifacts/agui-long-session-20261028/`；未推送 GitHub，待维护者集成。

## 后续只读审计：跨进程观察恢复（2026-10-28）

本节补充上一轮未覆盖的窗口，不撤销已通过测试，也不将测试总数解释为全部路径可靠。
产品源码与线上服务本轮未修改；无模型、搜索、审批或原 Run 重跑。

### 已复现问题

1. **P1：提交正文后观察器重建，无法正常同步终态。**
   `trench_ai_zebra_runtime.py:71` 每次创建空 mapper；dispatcher 从持久游标之后
   读取，未恢复 `final_answer_authoritative` 和 delivery assessment。
   完成事件被映射成 `committed_answer_missing`，但 dispatcher 仅对 `transient_`
   问题使用完整恢复，因此反复续读同一后缀。
   保存的真实编码帧／1020000 字节正文经真实 mapper、dispatcher 和隔离 SQLite：
   三次观察均仍 running，正文保留。部分完成样本配合真实契约形状的
   delivery_requirements_unmet 终态，则从 partial assessment 错映射成 blocked。
   对照调用既有 transient 完整事实恢复路径：一次恢复分别为 completed／partial，
   正文字节数均未变化。该对照是在隔离数据中选择已有路径，不是线上修复。

2. **P1：同一 Run 跨观察器的工具汇总会丢失前缀。**
   新 mapper 的 tool_results/content_parts 是空集合；新结果以局部集合输出，
   Turn store 的 agent_step/done 又直接替换已保存汇总。
   使用标准 files.publish 回执和 sources.get_status 回执复现：原汇总 `[file]`
   被 `[status]` 覆盖，最终正文没有旧文件下载链接，原始文件事件仍在数据库中。
   因此数据本体未丢，但最终交付入口可能丢失。此例 partial 状态保持。
   同一共享 mapper 路径还承载工具名、媒体识别、模型用量；这些应纳入修复回归，
   不能只给文件链接单独打补丁。

3. **P2：完整恢复清空分片状态，却保留对应的已见游标。**
   `trench_ai_zebra_stream_v2.py:64` 在 recovery_start 时清空 replacements/chunks，
   `seen` 却继续把重新发送的已接收前缀当成重复帧丢弃。
   同游标前缀重放后，下一片确定触发 stream_replacement_gap。
   当前缺口处理可再创建新 decoder 并 GET 恢复，因此不直接等同于永久丢失；
   但会消耗额外恢复预算，叠加链路故障时容易再次耗尽重连次数。
   普通 provisional reset 与完整 canonical recovery 的状态清理语义也必须区分。

### 通用最小修复范围（未实施）

- 区分同一个观察器的热续读与新观察器的冷恢复。冷恢复优先复用现有按原 Run
  读取完整权威事实的路径来重建 mapper，而不是只放行缺少答案的终态。
  热续读继续复用游标/连接；不重新提交执行命令，不追加模型或工具执行。
- 完整恢复时协调 decoder 与 mapper 的重建，保留 SQL 游标去重、已批准回执、
  原 Run/Turn 身份、取消/租约/权限检查。不要以放宽 committed-answer 判定补洞。
- 恢复过程中的局部工具/媒体集合不得覆盖此前完整交付集合：复用稳定 tool_call_id／
  part id 做合并，或在完整重建结束后再发布完整集合。原始证据不删除。
- 普通临时流 reset 只清理临时草稿；完整 canonical 恢复重建组装和去重状态。
  同一恢复轮次内同游标异内容冲突仍需拒绝，不能无条件清空去重来绕过校验。
- 新回归覆盖：在文件交付、答案提交、审批等待、终态前后分别重建观察器；验证
  同一 Run、无重复事实/计费/下载入口丢失、partial 不升级也不降为 blocked。
  加入多次 reset 与原始1 MiB预算边界，再走既有原生HTTP/PG门禁。

### 当前线上观察与证据边界

只读短超时统计：186 Turn、0 活跃、0 committed_answer_missing 观察问题；
该库 partial Turn 为0，未改写任何原始状态。API/Worker/Search健康且无重启。
近30分钟每服务最多3000行的指定错误计数为0；不能据此保证无所有历史故障。
本次是源码与确定性隔离复现，不声称上述问题已在指定生产 Run 上发生。

可复跑脚本与输出在配对 Trench 工作树：
`.artifacts/agui-recovery-audit-20261028/{probe.py,result.json,artifacts_probe.py,artifacts-result.txt}`。
`probe.py` 复用上一轮保存的真实 v2 编码帧；第二脚本使用标准工具/恢复记录形状。
使用现有 Trench venv 与 tests/api、services/api/src、packages/core/src 等既有 PYTHONPATH。
所有数据库均为 TemporaryDirectory 中一次性 SQLite；没有外部执行请求。

## 修复与上线：AGUI-COLD-RECOVERY-20261028

本节取代前一节的“未实施”状态；此前隔离审计证据保留。

- 冷观察恢复进入共享 Runtime 时标记 full_recovery；observer 明确忽略旧后缀游标，
  对同一 Run GET 完整权威事实。已有观察器内部热重连仍保留游标、连接和组装状态。
  不重新 POST 执行命令；新鲜授权、绑定续期、取消和租约检查保持。
- recovery_start 同步重建 decoder 与 mapper，避免旧分片去重吞掉重放前缀，以及
  模型用量/工具汇总在同一次完整重放中重复累计。
- 普通 provisional reset 仅清理草稿及其去重记录；保留 canonical 分片、确认正文、
  已接收 canonical 游标冲突检测。完整恢复才清理整套组装状态。
- 共享 SQL 投影按 tool_call_id/part id 合并交付集合，重放中的局部集合不会删除
  先前文件/媒体入口；相同 ID 更新、不重复追加。先保存原始输入事件，再生成合并
  展示投影，原始证据不改写。旧无 ID 回执保留。
- 分片包裹的 RUN_ERROR/RUN_FINISHED 按解码后类型结束观察，避免额外 GET。
- 原 turn_store 已735行：原样迁出投影/终态/序列化至279行的专用模块，store降至
  500行并保留既有导入入口。8个迁移辅助函数 AST 与原实现相同，无新依赖/表结构。

### 验证

修复前新增6个检查全部失败；修复后核心门禁397项通过，零跳过：
Cloud75 + Host126 + frontend196。另补充63项授权绑定/运行时/投影专项通过，
与核心门禁部分重叠，不相加作为独立用例总数；包含分片终态不重连检查。
最后新增的终态检查由原门禁通配符自动纳入以后运行。

冷恢复检查使用保存的真实 Cloud encoder 帧、真实loopback HTTP/httpx、实际
Runtime/mapper/dispatcher和原生PostgreSQL/SQLite。仅执行准入/身份依赖由隔离
fixture替代；原执行不会被触发。1020000字节正文恢复后SHA256一致；完成/partial
各保持准确状态；只增加原终态一条事实，无重复旧事实。SQL原始工具回执未被合并
展示内容改写。完整重放用量7保持7，工具结果只出现一次。

既有1000Turn/20000事件原生历史门禁和浏览器长历史检查继续通过；浏览器API仍为
fixture，不能作为新的线上模型/工具执行验收。正文/分片/历史缓存预算未放宽。
核心证据：Zebra `.artifacts/agui-cold-recovery-20261028/gate/`；补充与红绿证据：
配对Trench `.artifacts/agui-cold-recovery-20261028/`。

### 上线

只替换空闲 Trench API，镜像 `trench-api:agui-cold-recovery-20261028`，
image ID `sha256:53fc3ba0d51629cdd5455b9e84a262c3782a13f0dfdced3b0493dbb71fdc00d6`。
原配置、挂载、安全设置及schema `d3e4f5a6b7c8`保持。断网候选镜像检查和已运行
容器中的纯本地检查均通过；启动后有界日志没有Traceback/ERROR/ImportError。
所有Turn的run/status/answer/request/metadata/cursor/version联合哈希保持一致，
Worker及Search/TLS/egress等受保护服务进程不变，无MCP重启。
没有新增模型/搜索请求，没有批准/拒绝或重跑原Run，没有改写旧失败/partial状态。
发布证据/原镜像回滚基线：`/home/ubuntu/releases/20261028-agui-cold-recovery/`。

边界：冷恢复会额外重读当前Run的权威事实；它不是零SQL成本。热重连成本不变。
本轮不宣称解决所有外部Provider/网络故障，也没有进行新的真实模型Run验收。
