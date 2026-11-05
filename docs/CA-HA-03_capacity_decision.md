# CA-HA-03：有边界的容量决策（冻结 v1）

2026-11-05；人类 Owner lukeding，执行 Codex；branch `codex/ca-ha-03-budgets`。
用户明确选择：**持续 5/s，正常负载不允许容量拒绝**。
本协议取代将 15 秒探索窗口当作容量验收的做法；不放宽原排队目标。

## 固定目标和统计口径

- 同一 `[zebra-ha-e1-short-v1]` 合成任务、签名准入、输出字节计量和固定回复，零工具调用。
  与真实供应商能力/质量、生产 HA、长期 SLO 分开，不冒称真实模型链路验收。
- 30 秒预热（150 个计划请求）＋60 秒稳态（300 个计划请求），持续 5 offers/s。
  预检任务另计。生成器未发出、超时、429、unknown 和任务失败都保留，不能删除分母。
- 分别记录计划提交、实际发出、签名接纳、业务完成、退出 ACK 的数量与吞吐。
  稳态完成率与稳态前后未完成队列变化同时报告；排空后追平不能代替稳态吞吐。
- 正常负载不能出现容量 429；超时、unknown、未发出或其他错误也不能当作成功。
  排队 p95≤2s、p99≤5s；等待授权、HITL、模型、工具和 unknown 单独标识。
- 提交/接纳/完成各按原窗口记录；边界波动若足以改变 5/s 判断，视为证据不足，
  不能据此关闭里程碑。不给有限窗口补造稳定吞吐结论。
- 默认基线：已测试的 Memory 空扫描退避组合（d9ab05a0）；使用
  `.artifacts/cloud-ha-e1/e1-a-memory-backoff-drain-1793865198/overlay/` 的确切文件，
  其余依赖为原已安装版本，**不是整个当前 checkout**。后续读取组合/只读尾部探索
  不自动加入基线。冻结镜像、各 overlay、fixture、批准/签名与配置哈希。
- 同一 v126 保留种子的全新隔离副本；双 Worker 各4槽（总8），每 Worker2CPU、PG2CPU；
  256 SSE，原连接/内存/队列预算逐角色实录。任何调整都需单列前后值，不能暗中放大。

## 一轮诊断的时间账单

每个 Task 按同节点单调时钟对齐；跨 API/数据库时间先记录时钟偏移和测量误差。

| 区段 | 边界 | 所需证据 |
| --- | --- | --- |
| 等槽 | 签名接纳持久化→实际获得执行槽 | 原回执、pending创建时间、信号量/槽日志 |
| 占槽准备 | 获槽→登记/子进程恢复→首模型 | 父/子进程时钟、阶段 wall/CPU/运行队列等待 |
| 占槽业务 | 首模型→会话业务完成 | 模型开始/返回、事件持久化、主线程关键路径 |
| 完成后占槽 | 业务完成→子进程退出证明/ACK→释放槽 | 确认退出记录、父进程时钟、完整 held_ms |

- 分开记录 CPU 服务需求、调度/限额等待、数据库客户端操作、锁/IO与其他剩余时间；
  并行线程耗时不能相加冒充关键路径。未归因余量如实报告，不都归咎网络或数据库。
- 同轮采集 Worker/PG/API 资源用量及 throttle、连接/池等待、服务器活动/锁/IO，
  关联只含 Task/fence/PID 等元数据，不保存 SQL 参数/凭据。
- 查询次数只作解释变量；必须以消耗的时间、资源饱和/等待证据确认瓶颈。
- 给出每段可消除成本与仍须保留的授权、租约、停止、持久化、退出证明条件。
  完成账单后最多选两个主要瓶颈，不能继续无限列优化点。
- 现有历史证据可用于设计采样器，不能拼接不同轮次成一张假想同期账单。

## 只选一个主方案

1. 重复操作/往返/锁等待主导：合并关键路径操作，保留授权、租约和停止语义。
2. 完成后占槽主导：只把已证明可安全独立的后续工作移出；同时报告原全链路时长，
   不靠改变统计边界制造占槽改善。
3. Worker/数据库饱和：依据每任务 CPU/IO/连接需求，联动调整资源预算，验证可扩展性。
4. 最低必要链路在当前资源上超过1.6s：明确8槽不足，给出带余量的槽位/资源配置。
   40忙槽只是 Little's-law 估算，不能直接修改为40，更不能忽略共享资源和连接库存。

主要方案必须量化：当前瓶颈消耗、可回收时间/资源、预计吞吐与缺口、必要预算与风险。
没有跨过剩余容量差距的明确预期，不进入实现。新资源不足则交付所需 CPU/内存/连接/IO
及当前环境缺口，不能以“继续优化”代替结果。

## 边界和停止条件

- 一轮诊断、一个主要修复/资源方案、一轮按冻结口径的容量复验。
- 预检验证计时闭合、Task/fence关联、签名准入和采样输出；正式诊断不因观察超时
  自动重发。失败样本和不完整采样明确保留，不以补跑覆盖原始证据。
- 诊断计划最长20分钟（包含准备/采样/排空/恢复）；超过预算先安全停止生产者、
  保留运行状态/数据并报告未完成部分，不无限等待或重放。
- 交付“达标配置”或“明确未达标原因＋所需资源”；证据不足也必须指明缺失测量。
- 容量缺口被实际配置/主方案填补后，才进入持续负载、公平性和完整 E1-R。
  完整故障验收通过后再关闭里程碑；整体 HA 目标仍不等于这些局部结果。
- 生产不动；只操作隔离 E1。原业务数据、原 unknown、原签名证据不改写、不重放。
  所有角色切换采用最新固定源码清单，保留旧状态，按 owner 精确回收临时资源。

## 2026-11-05 同期诊断结论（仍未达标）

正式90s、450/450发出，103签名接纳、347容量拒绝、unknown0；接纳任务
103/103模型/完成/精确ACK各一次。稳态完成47/60=0.7833/s，计划窗口内接纳
48/300，队列32→31；全尝试占槽均值8.9243s，queue p95/p99 78.06949/106.57204s。
256SSE没有提前关闭。原unknown与签名数据保留；生产未动。

完整占槽覆盖103Task/104attempt；细段时钟闭合100/103Task，缺失保留。
PG稳态1.981/2CPU、93.22%period触发限额；child平均DB范围6.3309/7.0308s，
主线程CPU0.6874/runnable1.2124s，范围有重叠不相加。完成后占槽0.6087s，
移出不足以跨过缺口。Worker稳态cgroup采样丢失，补采仅排空；不声称Worker
CPU饱和已证实。SSE汇总重复写使runner退出1；首份结果保留，收尾核验退出0。

主方案选择联动PG/Worker资源预算，候选已准备但未安装：PG16CPU、双Worker
各4CPU/16槽、总32槽；独占测试池预留32CPU/64GiB。现有CapacityProfile检查
306连接+7保留<=384；原256明确拒绝此fleet。PG资源由本轮复合CPU/完成率
外推并留20%余量得到，含拒绝/后台/SSE，既不是必要资源下界也不是达标实证。
WAL/IO及Worker稳态需求还未定量。32槽在80%利用率须平均占槽<=5.12s，需实测。

本机10CPU/32GiB由两个OrbStack节点共享；远端16CPU/约31GiB已有生产负载。
未建立上述独占测试池，不占用生产余量，不跑无预计达标条件的缩水版复验。
因此诊断完成，配置候选备好；主要配置未安装，一轮450请求复验尚未执行，
CA-HA-03/E1-A仍In Progress，完整E1-R不启动。下一步是独占资源就绪后按原
冻结口径只跑新合成Task的一次候选复验，而非继续局部业务优化。

证据：`.artifacts/cloud-ha-e1/e1-a-bounded-diagnostic-1793873558/RESULTS.md`；原密封回执
`.artifacts/cloud-ha-e1/corpus-rebuilt-approval-sse-256-1793873711/`。
六角色ID/绑定/ready恢复、pending0、clone停止、两个owner workspace卷精确回收。

## CA-HA-03 资源候选只读补核查，2026-11-05

这是前一轮容量诊断的只读补核查，不是第二轮450请求容量试验。

- 从原停止的保留clone，以ha_app角色、READ ONLY、3s statement timeout取得两个
  热点定位谓词的ANALYZE/BUFFERS计划：接纳定位Index Only Scan/已有覆盖索引，
  event identity Index Scan/主键；执行0.336/0.189ms。不能据此证明UPDATE/触发器便宜，
  也不能以它替代负载实测。没有发现这两个谓词缺索引的证据，故未添加新索引。
- session_events实存约111.8万行、37个索引；只记录事实，不能把索引数直接当根因。
- 两台真实Worker里分别运行纯load_settings/CapacityProfile检查：候选16槽、batch16、
  fleet306连接均可解析；旧PG256元数据被拒绝，候选PG384元数据通过。
  未发起DB连接/Task/model，不代表签名准入或部署验收。
- 原Worker运行环境仍各4槽；原六角色ID/running和两API ready再次核验；clone停止。
- 32CPU/64GiB是候选预留估算，不是已证明的最小配置或硬件采购结论。
  当前缺口仍是隔离的扩展实测（包括Worker稳态CPU、WAL/IO、slot与吞吐伸缩性）。
  未安装主要配置、未执行容量复验、不推进完整E1-R，HA目标未完成。

证据：hotspot-read-plan-summary.json、hotspot-read-plans.jsonl、
event-storage-inspection-verified.tsv、native-config-check.json、
config-followup-restoration.json。既有evidence.sha256保留；新增证据见
followup-evidence.sha256，未改写旧容量结果/回执/unknown/签名。

目录：`.artifacts/cloud-ha-e1/e1-a-bounded-diagnostic-1793873558`。

## CA-HA-03 delegated resource candidate, 2026-11-05

User delegated resource choice. The uninstalled32CPU/64GiB draft is not a minimum.
Selected12CPU test cap on192.168.101.7: PG6CPU/4GiB plus two independent private
Docker nodes, each3CPU/4GiB,16slots.32slots total;306+7 connections<=320.
This is logical dual-node evidence on one physical host, not physical multi-host HA.
Avoid cross-WAN DB transactions (measured TCP latency around160ms or more).
Guard tracks existing85 containers, memory>=6GiB, disk>=12GiB and sustained load.
Exact installed source snapshots plus d9 overlay retained. Source v126 copied via
pg_dump/restore across architectures:1114740 events,17742Tasks,pending0 match.
Logical restore/reindex and PG patch changes are explicit comparison limitations.
Old stalled transport terminated only after checking remote progress/process state;
checksum transfer completed, no business replay. OCI/config image IDs reconciled
by identical layers/semantic config. Official DinD initialization enables nested
memory/CPU cgroups with parent3CPU/4GiB limits; no host cgroup change.
Both new nodes pass native counter/TLS and wrong key/client/namespace checks;
zero Tasks executed during qualification. Isolated test bundle materialized and
published:437a587a-a0c7-4c83-b477-9a62afdf7e7c,version0a432a2d-4c4f-4d19-92b5-b39a827116b9.
Next: one fresh signed Task then one450-offer30s+60s window at5/s, zero capacity
rejection. Original six test roles paused only during controlled run and restored
in finally. Production, original Tasks/unknowns/signatures remain unchanged.
Evidence:.artifacts/cloud-ha-e1/e1-a-resource-candidate-1793875018 and remote
/home/ubuntu/.local/state/zebra-e1/e1-a-resource-candidate-1793875018. Task In Progress.

## 2026-11-05 隔离资源复验结论：FAIL，停止本轮负载

Owner lukeding；CA-HA-03 / codex/ca-ha-03-budgets。按用户自行决定资源的授权，
实装 PG6CPU/4GiB＋两个逻辑节点各3CPU/4GiB，共12CPU/12GiB硬上限，32执行槽。
同一物理宿主机，不是物理双机HA；跨架构逻辑恢复/重建索引和PG版本差异使其不能
作为仅CPU变化的因果对照。32CPU/64GiB始终不是实测最低需求。

- v2运行包发布成功：version cd8e94a6-e77a-4a92-98d1-f62cb7409e9d，
  bundle sha256:d7a2207696e03cfada19d469fa38fa9dfa708d0b249a437d2003154fbe07922c，
  trust revision2；原版本/签名证据保留。私有配置权限恢复600/UID65532，不放宽安全校验。
- 第一个新预检保留unknown且不重发；新v2合成预检201、模型/完成/精确ACK各一次，
  登记→ACK4.51746s。合成模型fixture，不是实际供应商验收。
- 第一正式窗口错误地把API压到0.25CPU：450计划/347发出/103未发出，347回执
  未解析成功、零已验证201；API节流周期100%。失败原始记录另存failed-api-quarter-run。
  纠正API为2CPU，外层节点仍各3CPU，未修改Task预算，也没有覆盖原窗口。
- 最后窗口450/450发出；AES-GCM及request_hash逐原intent核验得到51个201、5个429、
  394个unknown。保留41个原GET文件；其余可用原POST密封回执核验。unknown不通过DB
  状态冒充成功，不重发。51个已验证会话中37业务完成、41模型开始、44精确退出ACK，
  command done44/pending7；退出ACK不等于业务成功。
- 排队44个可观测样本，p95/p99=94.800879/105.581530s（另7个未启动，不能当零）。
  登记→ACK44个完整单调时钟样本：平均14.009924s，p95/p99=18.658526/18.930204s。
  全部已记录释放57次/51会话：每会话累计占槽均值15.189157s，p95/p99=22.755/23.183s；
  这是保护中止后的有限释放样本，不证明所有命令完整排空。
- 阶段样本均值：登记→子进程1.061s(n44)，子进程→组装0.462s(n43)，
  组装→恢复0.914s(n43)，恢复→模型6.168s(n41)，模型3.053s(n37)，
  返回→完成2.110s(n36)，完成→退出证明1.026s(n36)，证明→ACK0.143s(n44)。
  各阶段覆盖集合不同，不能直接相加。稳态在已验证201集合内观察到接纳31、完成24、
  ACK22；394个unknown尚未收敛，不能据此声称总体稳态完成吞吐。
- 60个稳态资源样本：PG2.704/6CPU，零节流；node1/node2分别2.608/2.787CPU，
  父级节流周期52.1%/66.3%；Worker1.944/2.119CPU。API约0.628/0.619CPU，零自身节流。
  父级包含子进程，不能相加；本轮主要瓶颈为执行节点共享CPU配额/调度压力，
  不能沿用旧PG2CPU饱和解释，也不能以此证明某个更大资源配置必然达标。
- 256 SSE观察期零提前结束、2036 keepalive；保护停止后的连接行为不计入此前观察。
- 宿主机连续10个5秒采样load>20触发保护（触发load25.7954，MemAvailable约15.35GiB，
  diskfree约22.19GiB）；只停止本run节点与PG，未重启/修改生产。load包含配额等待，
  不能单靠它推断生产受损。原回执查询/排空被中止，未知状态及7个pending保留。

结论：该12CPU共享主机配置不能通过持续5/s、零容量拒绝与排队SLO；没有证明达标配置，
也没有证明最低硬件需求。现有环境不能继续加压争取通过。下一次容量验证需要独占且
有明确CPU余量的执行节点，保持近端PG，并先证明父级CPU节流消失；具体CPU下限尚缺
无节流条件下的每任务服务需求测量。完整E1-R/跨scope公平性未执行，里程碑3不关闭。
本轮不再追加微调、负载或故障矩阵。

收尾：停止的节点直接离线提取日志，未重启Worker/daemon；仅PG短暂启动供BEGIN READ ONLY
审计，随后停止。原六个E1角色ID核验恢复，两原入口/health/ready均ready。只删除本run
已停止的本地导出副本容器及卷；原种子、原数据、unknown、签名和远端未完成状态保留。
证据：.artifacts/cloud-ha-e1/e1-a-resource-candidate-1793875018/RESULTS.md，
final-audit.json、final-phases.json、resources-summary.json、offline-recovery/、
original-restored-final.tsv、publication-v2-pool-proof.json、evidence-final.sha256；
原窗口corpus-rebuilt-approval-sse-256-1793886575与failed-api-quarter-run分别保留。
远端保留：/home/ubuntu/.local/state/zebra-e1/e1-a-resource-candidate-1793875018。

## 2026-11-05 停载后原证据追踪：unknown不是提交未到达

本轮只读本地离线日志，未启动节点/数据库、未发HTTP请求或新Task。
最终450个原operation在两API访问日志均有且仅有一次POST：112个HTTP200、338个HTTP503。
HTTP200中只有56个最终可验证密封结果（51接纳＋5拒绝）；另56个仍unknown，
加338个503组成394个unknown。因此生成器/SSH观察中断不能解释全部未知结果，
HTTP200不能等同接纳。
按精确operation匹配199条atomic first Run失败里程碑，全为TimeoutError；其中198个
属于最终unknown，另1个已由原回执恢复为密封结果。其余196个unknown没有该里程碑，
不可用相邻日志代替关联或强行定位。generic unknown日志无operation ID，未逐任务归因。
198个可关联unknown中prepare阶段耗时中位1492ms、fence1550ms；189个进入事务，
transaction_entered中位1558ms；dispatch_return中位1861ms（局部起点晚于外层2s起点）。
多数已在进入原子业务事务前耗尽大部分2s总预算。失败栈涉及idempotency、event、
Task投影和binding等多个SQL位置；这是截止时间到达点，不是各SQL CPU成本排名。
结合PG零配额节流与执行节点父级节流，现有证据不足以把某条查询或锁定为单一根因，
也不足以安全放宽deadline、移除授权复核或自动重发unknown。
停止后原GET收集仅41文件，最后ConnectError与节点被保护停止一致；这是回执收敛缺口，
不改写已存POST结果。需要在下一可承载测试环境证明独立原GET/控制预算，不能把当前
51个signed集合中的完成数当作450个operation的全局完成吞吐。
证据unknown-diagnostic.py/json/output.json，原API日志offline-recovery/；脚本断言
450个不同operation均单次到达及199条唯一失败关联，已运行通过。
总体E1-A仍FAIL，HA目标未完成；不追加本宿主机容量负载，不改生产。

## 2026-11-05 准入准备追踪补证：排他消费锁，不再归为纯CPU问题

只读现有62个数据库采样，49个存在advisory等待，累计321个后端×采样，峰值9个。
这不是等待秒数或CPU比例。采样没有锁键/阻塞PID，不能归因全部到某条锁。
直接检查原api-source.tar（未使用当前checkout替代安装版本）：publication_consumer.py
59–60行依次调用HostManagementStore.authorized和lock_definition；对应安装版
host_management.py242行、publication.py87行均为排他pg_advisory_xact_lock。
前者按管理binding、后者按Definition串行，且消费期间持锁完成Snapshot校验。
因此“CPU不足为唯一/已确定主要根因”的表述收紧为：节点节流已证实，准入锁争用
也有同时期证据与静态串行路径；两者贡献尚未分离。仅加CPU不能保证接纳5/s。

不能直接删除锁或缓存当前权限/Release：撤权、审批轮换、发布切换、过期校验必须保留。
下一可验证切片应先用原生PG的小型并发事务验证共享消费/排他发布合同：双消费者并行，
审批或Release写者被读事务阻挡；写者完成后新读拒绝旧审批/取得新Release；到期拒绝；
锁有相同deadline且无死锁/非预期锁序变化。只能在这些不变量成立且持锁成本可测后，
决定是否扩大应用Owned paths做共享读取修复。当前不扩路径、不实现、不追加容量负载。
该假设尚未证明能跨过完整占槽缺口，不能启动新的无边界优化轮次。

lock-evidence.py已运行，断言62采样/321后端样本并核验三个冻结源码文件及精确锁调用。
证据.artifacts/cloud-ha-e1/e1-a-resource-candidate-1793875018/lock-evidence.json；
其源文件摘要与行号固定。原RESULTS.md及evidence-final.sha256保持不变。
生产/服务状态未改，CA-HA-03及整体HA仍In Progress。

## 2026-11-05 准入锁切片已完成本地验证，Review未部署

四个应用文件最小修改：消费K1/K2共享锁，原生append_release补齐K2排他锁；其他写者
排他默认值、授权/expiry复核和deadline不变。冻结源码逐字节匹配相邻基线acb7a85f。
正式schema新8项并发/撤权/轮换/发布/超时/取消/到期检查通过；相关49通过，旧Registry
另补5通过2基线同样失败；workspace mypy原版/候选同3项既有错误，ruff改动文件通过。
一次新合成Task低负载前后对照：每侧24/24密封201、unknown0；准入p95/p99
238.607/245.529→232.664/243.506ms；锁获取p95 26.573→0.951ms；持锁均值
26.259→41.287ms；原GET各24个200，重叠STOP均202 requested（非清理完成）。
准入p95仅改善2.49%，不足填平E1-A缺口；结束此优化方向，不追加零散优化/容量试跑。
原数据、unknown、签名和失败探针保留，生产未动；临时PG精确回收。
证据.artifacts/cloud-ha-e1/e1-a-resource-candidate-1793875018/lock-contract/RESULTS.md，
comparison.json、locks.json、source-pins.json及正式回归日志。尚无达标配置证明，
下一容量验证需独占CPU余量/近端PG/无父级节流/固定签名候选；E1-A/E1-R未跑，HA未完成。

## 2026-11-05 完整执行资源测量：预检失败，未进入阶梯

只操作本机隔离环境。候选13a8de6c＋原d9安装overlay；PG3CPU/3GiB在Docker VM，
Worker3CPU/3GiB＋cleanup0.5CPU在根4CPU/8GiB的VM1，API1CPU/1GiB在另一根4CPU
VM2；GET/控制lane仍共享API CPU，不宣称独占物理资源或CPU预留。
新副本签名包版本d0da96c7-8c34-4b76-8f28-e58567d38935；只发1个新预检，
201及原GET核验通过，但model_started0/completed0/suspended1（executor_process_interrupted）。
登记/精确退出ACK各1，失败登记→ACK0.750468s、持槽1.527743s，不能作为成功占槽。
按停止条件不发剩余15任务，不跑1/2/4阶梯或强停探针。warm-fork夹具吞掉原异常，
另有RabbitMQError但未证明根因；下一步先补异常元数据及原生依赖资格，无业务重放。
原六角色/绑定哈希/两ready恢复；新候选容器和tmpfs卷精确回收，失败DB停止保留。
容量边界/5/s配置仍未测得，不申请猜测CPU数量；生产/旧unknown/签名均未改。
证据.artifacts/cloud-ha-e1/execution-resource-measurement-1793890154/RESULTS.md；offline-audit已运行通过。03及整体HA仍In Progress。
