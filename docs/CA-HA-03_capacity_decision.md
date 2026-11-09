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

## 2026-11-06 执行资格修复与1/2/4有界测量完成（未达容量验收）

隔离安装错误已定位：旧baseline pin绑定33410，而新PG为33413。安全异常元数据回归
冷/暖两分支通过；原生新包v2通过兼容校验，旧快照保持拒绝。另对原测试Rabbit应用
备份Mnesia后stop_app/start_app恢复，无reset或凭据轮换；不归为子进程根因。
实际测量使用逐Task native冷启动，不用warm-fork。并发1两窗口0.229/0.226完成/s，
完整占槽3.234/3.339s；并发2为0.397/s、3.673s；并发4为0.626/s、4.414s。
并发4毛CPU/Task Worker2.535s、PG1.793s，Worker叶级17.19%周期节流，父级未见节流。
曲线随并发增长，但短批次不能证明持续容量；guest时钟未同步，未给排队SLO。
19个新Task均签名201、准入unknown0，17个模型/业务各完成一次，19个精确ACK各一次；
全部失败和编排错误保留：两次GET503中止、一轮脚本失败后额外5个新Task、错误Run范围
强停403及ready前502。无旧任务POST重发。Task范围强停完成退出和资源释放，但仅启动阶段；
仍保留pending_live1、active_leases0，未删除或宣称排空。原六角色/绑定/ready恢复，
六临时容器和两再生tmpfs精确回收，PG容器/数据停止保留，生产未操作。
下一条件为专用完整父级预算环境；约32可分配同等CPU/32GiB/32槽仅规划候选，非最低需求
或达标证明。本机10核无法验证此配置，不向共享生产宿主机继续加压。
不追加局部优化，不跑450或完整E1-R。13a8de6c仍本地Review，CA-HA-03/整体HA仍In Progress。
证据.artifacts/cloud-ha-e1/execution-qualification-1793892399/RESULTS.md，
all-task-audit.json、measurement-analysis.json、resource-estimate.json及final-resource-audit.json。

## 2026-11-06 测试工具收尾，容量验收明确暂停

冻结13a8de6c/package-v2/native cold候选，无执行架构/性能改动。新增受检查的单解释器
准备→执行入口及离线回归：旧准备失败继续执行可复现，修复后停止；冻结观察器16并发
查询活动峰值1、503保留且无Task POST，原unknown/no-replay检查通过。本轮新Task0。
只读检查保留PG：强停Task已cancelled/stop done/无租约，但pending未结清、handoff未handled，
确实占同scope32中的1个准入名额，且仍满足pending扫描。物理exitACK不能冒充命令处理边界；
未删行/标done/修改应用候选。冻结安装8模块来源核验，4个command模块与checkout不同，
使用安装源码而非当前代码归因；该派生队列名额缺口后续需最小修复/回归并重新冻结。
OrbStack Kube现可达但单节点10CPU/约15.66GiB，仍与Mac共享；两VM各4CPU父级，
未落实独立32CPU/32GiB可分配资源。32候选需另留宿主余量，非最低/达标配置；
无选定供应商/报价，不承诺成本或发起采购。PG复查后停止保留，生产未访问。
容量E1-A/完整E1-R明确暂停，不用零散优化填时间。证据：
.artifacts/cloud-ha-e1/test-tool-closeout-1793897286/RESULTS.md。

## 2026-11-06 CA-HA-03-Q1 本地修复通过，候选待Review

独立分支codex/ca-ha-03-q1-stop-capacity，唯一应用修改force_stop_recovery.synchronize：
在原Session/lease/stream事务结清canonical终态后，仅在租约明确释放且现有精确退出
证明满足时，将该Session前缀内pending置cancelled；不写handled，不改旧回执/结果。
排队1→请求后1→0；运行中无ACK/错ACK保持1，精确ACK后0。单槽真实接纳检查证明
名额可以再用一次，重复ACK/停止/恢复不多释放。领取并发、事务回滚与清理进程真实
os._exit后的原机制恢复通过；真实本机子进程退出但缺持久ACK仍保持1。
新增8项、相关79项通过，Linux专用1项在macOS跳过；冻结9相关模块组合再验8通过。
ruff和修改模块mypy通过。这里只是存储/API组合及本机进程回归，不是完整Linux部署资格。
原pending/unknown/签名未改，旧PG保持停止；原293+37证据摘要核对一致。新合成数据
快照/日志保留，独立临时PG/卷精确回收。旧done记录不会自动回填；原行仍保留为证据。
源码覆盖包与清单重新冻结，未重新签署/发布运行包，未推送或部署。独立资源仍阻塞
容量验收，E1-A/E1-R继续暂停；整体HA未完成。
证据.artifacts/cloud-ha-e1/force-stop-capacity-1793898506/RESULTS.md，
capacity-and-recovery-results.json、fresh-regression-data/及FROZEN_CANDIDATE.json。

## 2026-11-06 资源决策：容量验收受环境阻塞

Q1修复线结束追加开发，应用f20b56a3及原源码/签名证据冻结不变；尚未重签或部署。
资源方案选择AWS us-east-1 Linux ARM64按需：2×c7g.8xlarge（各32CPU/64GiB）
＋独立c7g.xlarge控制/负载节点（4CPU/8GiB），同AZ spread、双PG与明确父子预算。
总68CPU/136GiB含备库/控制/宿主余量，不是5/s最低需求证明。数据盘2×500GiB gp3，
各6000IOPS/250MiB/s；三系统盘各64GiB。48小时含准备/验收/导出，网络和磁盘实测待资源。
下载AWS官方2026-11-04价目核实EC2费率：1.16/h×2＋0.145/h；公开存储/网络费率
估算税前48h129.86美元，含至多7天快照约143.77美元，建议预留180美元税前；
地域EBS正式报价/税费仍未核验，不是已授权支出或保证账单。报价与公式可复算。
本机无云CLI/账户配置/凭据；账户净剩余额度、AZ库存、支付与实际启动均未核验，
已落实独立实例0。未购置/建环境/跑Task/改生产。不在阻塞期间继续局部优化或安装器开发。
资源/签包/单任务执行及强停名额释放→E1-A→完整E1-R的核验命令、旧入口限制与停点
已写入docs/CA-HA-03_resource_decision.md。里程碑3仍In Progress，不能关闭。
证据.artifacts/cloud-ha-e1/resource-decision-1793899843/，cost-and-allocation.json及官方价目JSON。

## 2026-11-06 CA-HA-03-Q1 功能验证完成，容量验收仍阻塞

冻结 amd64 候选在隔离环境通过 Linux 回归（9 项）及一个新合成任务的在线强停复验。
模型请求开始后强停返回 202。独立签发 Task 级读取授权的 GET 返回 200，Run 级授权仍返回
403。在线确认执行停止、租约撤销、沙箱清理和同步完成。精确退出 ACK 一条，scope
待处理数 1 → 0。6.025 秒是本次从发出 POST 起的观测，尚未验收完整停止时延要求。
原 403、离线证据、旧签名及 unknown 保留。冻结清单和校验索引见
`.artifacts/cloud-ha-e1/remote-host-qualification/q1-amd64-build/stop-read-recheck/`。

修复与回归通过草稿 PR #267 送审，目标分支 `cloud-agent`，其隔离 PostgreSQL 回归
34 项通过。修复尚未部署生产。独立容量资源待落实，E1-A 继续暂停，通过后才恢复
完整 E1-R。里程碑 3 仍为 In Progress。

## 2026-11-09 AMD64全链路修复与5/s过载刻画：容量仍受独占资源阻塞

Owner lukeding；codex/fix-e1a-admission-deserialize。192.168.101.7 隔离 zebra-e1a 栈。
生产未动；同族2026-11-02残留TLS容器（占用28445、上游已死）仅 stop 未删除，可恢复。

- 修复七个叠加根因后 AMD64 全链路首次端到端打通：签名201(0.2-0.4s) → worker领取 →
  真实 gVisor runsc 执行器 → TLS模型fixture（marker/证书/计量全过）→ session_completed。
  关键根因：①digest时代的32条 dead pending 永久占满 scope 容量门（已归档后清除）；
  ②原 catalog 以直连PG(:25432)环境生成而 worker/API 走 PgBouncer(:25433)，database_url
  参与 baseline_digest，任何平台摘要修补都不可能匹配——以 worker.env 原样原生重生
  catalog/bundle/publication（definition da587ef8，trust revision 1）；
  ③payload 残留旧 definition id；④worker 的 catalog 路径是宿主路径（容器内不存在）；
  ⑤模型 wire 指向 http:28082/e1test 而发布档钉死 https:28445/synthetic-only+marker；
  ⑥e1_composition 端口守卫拒绝 25433；⑦worker 无 docker.sock。宿主侧 fixture 修改均留
  .orig 备份。执行器引导在真实 runsc 下实测 6.03s（Mac OrbStack runsc 约2s），新数据点。
- 5/s×120s 过载窗口（洁净库，atomic-task-run/1 密封会计，596/596 offer 全部对账）：
  79 承接(0.66/s)、441 密封容量拒绝、74 POST 503、3 not_observed、0 未对账/0 损坏；
  承接会话 78 完成+1 suspended；排队均值52.5s/p95 129.5s（5倍过载下容量门按设计工作，
  每个offer都有密封回执）。冻结口径（持续5/s、零容量拒绝、排队p95≤2s）在本机仍不可能：
  排空需约40槽（5/s×8.03s占槽），16核共享生产宿主在4 worker 时 load 已达13，与
  2026-11-05 守卫结论一致。不跑缩水复验冒称通过。
- 256 并发 SSE 两次独立通过：256/256 全部 200、0 提前结束、0 流错误（13s 开门爬坡
  受 API read=2 预算约束；随机 binding 被 403 正确拒绝，须重绑任务原 binding）。
  与 2026-11-05 的 keepalive 观察差异（完成任务裸流静默空闲）如实记录，未合并解释。
- 证据：.artifacts/cloud-ha-e1/e1a-1017-amd64-final-20261109/（RESULTS.md、5/s窗口
  summary/jsonl、sse256-*.json、idle-stats.txt）；宿主 /data/zebra-e1a/state/
  dead-commands-archive-20261108.json、execution-prev/、results/。
- CA-HA-03/E1-A 维持 In Progress：AMD64链路阻塞已清除，冻结容量验收仍等独占执行资源
  （用户已否决付费资源；共享宿主无法提供）。里程碑3不关闭。

## 2026-11-09 空闲维护成本修复：fleet 空闲 ~108% → ~40% 单核

同卡同branch（5aa6cf1c）。101.7 实测 4 worker 完全空闲（零任务）画像定位两项产品缺陷：

- StreamHintRelay 失败结算 1s 重试：live fanout（Redis）不可用时变成永久 claim/settle
  打转（84 tx/s，仅因 101.7 无 Redis 而暴露；等价于 Redis 故障域内的持续 DB 放大）。
  修复：发布失败保留 claim，由 30s 租约到期承担有界重试；成功路径不变。
  契约测试同步更新（test_publish_failure_keeps_claim_for_lease_recovery）。
- AgUiProjectionWorkService 10Hz 空转 + 每拍重跑 bootstrap（对 projector 配置行 FOR UPDATE）：
  fleet ~294 空闲事务/s。修复：bootstrap 完成后 60s 复查 + 空闲时区间倍增至 1s 上限、
  有进展即回落。连同 4444af6a 的 _enabled() 30s TTL 一并部署验证。

| 层 | 修复前 | 修复后 |
| --- | --- | --- |
| PG | 35.6%（峰值74%） | 21.3% |
| PgBouncer | 15.8% | 3.9% |
| 每 worker | 12-17% | ~3.9% |

部署验证：perf2-5aa6cf1c-amd64（f327a05d + 三文件 delta；settings 未变故 baseline 链不重建），
密封 201 → runsc 执行器 → session_completed 全链路复验通过；回归测试
36+341+1 全绿。对容量判定的影响：40 worker 的空闲底盘从 ~10.8 核降至 ~4 核，
共享宿主上的 40 槽不再数学上不可行（仍受生产负载与 8s/任务执行成本约束，不据此宣称可达标）。
遗留观察：PG 21% 空闲仍偏高（疑 autovacuum/残余轮询，未定论）。PG 空闲证据：
idle-before.txt / idle-after.txt / idle-after2.txt（本机 .artifacts 同目录随 RESULTS 归档）。

## 2026-11-09 E1-C 公平性 / E1-O 过载分档证据采集（非验收轮）

同卡同branch。perf2 拓扑（空闲成本修复后）按计划完成两项证据采集；冻结口径
的公平性/过载验收仍排在容量缺口之后，本轮不宣称通过。

- E1-C（16 scope：control 0.25/s + 15×flood 0.5/s，120s，drain 饱和）：
  control 29/30 接受、14 完成（洪泛中位 13）；洪泛不买吞吐、低速率邻居未被
  饿死、per-scope 32 上限隔离洪泛伤害；全部拒绝密封、零失败。
  证据 e1-co-1017-20261109/E1C-RESULTS.md。
- E1-O（单 scope 0.5/1/2/3 offers/s ×60s 阶梯，档间排空）：
  ≤1/s 100% 接受零拒绝；≥2/s 接受精确钳制 ~64/60s（drain 份额），
  溢出全部密封容量拒绝；接受密封 p95 在过载下不升反降（363/330ms vs 963ms），
  零 unsealed/零失败。证据 E1O-RESULTS.md。
- 驱动失误记录：`VAR=x docker exec` 不向容器传环境导致 3 轮重复 E1-C 洪泛
  （非计划窗口，不纳入统计，原始 jsonl 保留；系统连续承受 4×~930 offers
  零死命令零失败）。两份 RESULTS 连同 idle 修复测量构成今晚证据集。

## 2026-11-09 阶段0争抢斜率实测：专用 101.7 上限 ≈3.3/s，5/s 仍需 24-32 核

用户问"101.7 全部停服是否够里程碑 3 资源"。零风险阶段 0（不停产）两点实测（perf2 镜像，
PG 8CPU/16GiB，队列排空起步）：

| 点 | 配置 | load | 执行段(起→终) | 引导段(起→模型) | 排空率 |
| --- | --- | --- | --- | --- | --- |
| A | 4 worker，~1 并发 | 5.5/16 | **4.52s** | ~3s | — |
| B | 8 worker 全饱和 | ~11/16 | **9.33s**（p95 14.21） | **6.84s** | 0.99/s |

模型：引导成本 ≈2.5-3 core·s/任务（空闲 3s 墙钟 × ~0.9 核），争抢下自增强（并发引导
→拉长→更多在途）。稳态 5/s 需引导 ~14 核 + PG ~5 + API/worker ~2 = **≥21 核下限，
带 p95 余量 24-32 核**——与 2026-11-06 的 32 核 AWS 草案定量吻合。

**专用 101.7（~15 可用核）外推**：引导预算 ~9 核 → 上限 **≈3.3/s**（乐观 3.75/s），
**不能达到冻结 5/s**。但 16 槽 × ~5s 执行 ≈ 3.2/s——**修订目标至 3/s 后本机大概率可过
零拒绝复验**（需正式改冻结文档）。

三点决策不变，第二项新增定量依据：
1. 24-32 核独占机器 → 按原冻结 5/s 复验；
2. **修订口径 5/s→3/s + 101.7 专用窗口（3-4 小时）→ 大概率过，一次窗口可收 E1-A/C/O**；
3. 长期 In Progress 转投 04+（挂账+兜底三件事）。

阶段 0 证据：stage0-pointA/pointB jsonl（宿主 /data/zebra-e1a/state/model-wire/e1a-results/）；
e-h worker 已撤，拓扑复原 4 worker/11 容器。

## 2026-11-09 冻结口径修订（用户决策）：持续目标 5/s → 3/s

Owner lukeding 于 2026-11-09 深夜会话中明确选择"修订口径 + 101.7 专用窗口"路径。
本节为该决策的正式记录，取代 2026-11-05 冻结 v1 中的 5 offers/s 目标；其余条款不变。

**修订依据（全部为本仓实测）**：
- 阶段 0 斜率（PR #271）：专用 101.7（16 核）上限 ≈3.3/s；5/s 需 24-32 独占核
- 原 5/s 目标制定时（2026-11-06）即伴随 32 核 AWS 草案——目标与资源草案配套；
  用户否决付费资源后，5/s 失去配套资源，3/s 是本机物理上限内的诚实目标
- 空闲成本修复后 16-18 worker 底盘 ~2 核，16 槽 × ~5s ≈ 3.2/s > 3/s 有余量

**修订后验收参数（其余统计口径、零容量拒绝、排队 p95≤2s/p99≤5s、256 SSE、
失败样本保留、生产不动原则全部沿用）**：
- 30 秒预热（3 offers/s，90 个计划请求）＋ 60 秒稳态（3 offers/s，180 个计划请求）
- 专用窗口期间 101.7 生产栈暂停（窗口前后完整恢复并核验健康），窗口时长 ≤4 小时
- 阶段闸门：空闲机单任务执行段 >6.5s 即中止并恢复生产（占槽预算不足）
- E1-C 多 scope（1/16/32）与 E1-O 分档随 3/s 基准重定：0.5×/1×/1.5×/2× = 1.5/3/4.5/6 offers/s

修订不回溯既有证据；此前按 5/s 记录的窗口（4.97/s 纯准入、596-offer 过载）保持原样。

## 2026-11-09 专用窗口执行回执：3/s FAIL，本机上限实测 ≈1.6-2.0/s；QA栈事故记录

按修订口径执行专用窗口（停产84容器→闸门3.31s GO→16-20 worker→三轮3/s复验+定标）。
**E1-A 3/s 未通过**：三轮接受率 1.47/1.46/1.30/s，执行段 7.8-9.4s；20 worker 比 16 更差
（自增强确认）；2/s 在 20 worker 下也出现 43 个密封容量拒绝。瓶颈定位为产品级执行器
引导成本（引导段 6.28s，runsc 宿主引导；PgBouncer 池 8→40 无改善）。阶段 0 的 3.3/s
外推被推翻：并发下有效引导成本 ~5-7 core·s（自增强）。256 SSE 两轮 256/256 零掉线。
全部 offer 密封对账零损坏；负载守卫未触发。

**剩余选项**：(a) 引导成本产品优化（RUNTIME_CPUS 0.25→1.0 / deferred provisioning，
需重生成链）；(b) 24-32 核独占；(c) 口径降至 1.5/s。CA-HA-03 维持 In Progress。

**事故（如实记录）**：erp-full-qa-20261028-2 QA栈（10-28一次性验收环境）pg/db/s3
均为 tmpfs 数据，docker stop 清空其内存态。schema 已迁移重放（MIG_OK），api 两容器因缺
部署期种子仍退出待原流程重放；验收结论已在仓库文档（ERP-NATIVE系列），证据未丢。
教训：停产窗口前必须审计 tmpfs 容器。生产恢复 82/84 Up（trench/erpnext/WeKnora/zebra
健康抽查通过）。证据：.artifacts/cloud-ha-e1/dedicated-window-20261109/WINDOW-RESULTS.md
（本仓）与宿主 /data/zebra-e1a/window/。

## 2026-11-09 Phase A/B 引导段定位与零代码杠杆：3/s 需产品级 import 削减

**Phase A（定位，全部实测）**：零工具任务零 OCI（事件流 0 容器创建，defer 生效）；
引导段=session 子进程，**每任务 ~3.0 CPU·s**：import 2.0s（67%，热点
zebra_agent_worker.claims→agent_storage.postgres.leases→agent_storage/__init__ 全量拉载
1.06s）+ 初始化 0.8s + 组装 0.18s；DB 往返 1-10ms/条非瓶颈。并发恶化机理=宿主 CPU
饱和自增强（16 并发 × 3 CPU·s），非调度配额或连接池。

**Phase B（零代码杠杆，实测）**：
- B2 checked-hash pyc 预编译镜像（perf3-bootcache）：import -15~19%（2112→1794ms），
  远低于 11-03 原型的 -48%——残余为 pydantic 模型构建等非编译成本；
- B1 worker --cpus 2.0：共享宿主下**负杠杆**（16×2 配额加剧超卖，带产 3/s 探针
  1.52/s、exec 12.5s，比 1.0 配额更差）；专用机下有限正效应但主约束仍是 CPU 总量。
- 结论：**零代码杠杆无法达到 3/s**。带产基线维持 4 worker @1CPU。

**D1 提案（产品级，待批准后实施）**：`agent_storage/__init__` 改 PEP 562 惰性导出
（子进程不需要的 artifact_objects 等子模块 1.06s 拉载全部延迟），配合
session_process_child 已有惰性导入结构。预期 import 2.0→<0.8s、子进程 3.0→~1.8 CPU·s，
16 worker 专用机理论 5-6/s、现实 3.5-4/s——3/s 可达且全部署形态受益。回归纪律：
现有 import 结构测试 + 全量 make test/check + 链上验证后再复验。

证据：/data/zebra-e1a/window/phaseA/（events/importtime/cpu.stat/statements）、
it2/it3.log、e1a-b1.log、phaseB-gate jsonl。

## 2026-11-09 D1-v1 落地：惰性存储根，单任务 -10%，3/s 仍需 D1-v2

PR #275。agent_storage 根（142 名/35 模块）与 agent_storage.postgres 根（97 名）改
PEP 562 惰性再导出；TYPE_CHECKING 保持静态视图。实测：根导入 ~2s→14ms；claims 链
1.21s→0.51s；101.7 带产单任务执行段 4.52→4.06s（-10%）；零新增测试失败
（4547 通过；11 个失败全部基线既有，stash 对照验证）；新增子进程隔离回归
test_lazy_package_exports（轻导入保证+导出完整性+AttributeError 契约）。

外推：专用 16 worker 容量 1.94-2.04 → ~2.2-2.4/s，仍未达 3/s。剩余 import 成本
~1.7s 在 worker 自身模块：control 724ms、execution 362ms、recovery 222ms、
agent_integrations 218ms、agent_core.application 200ms（it4.log 热点表）——
D1-v2 范围已圈定。101.7 已部署 perf4-lazyinit 镜像为 4 worker 基线。

## 2026-11-10 D1-v2 落地：worker 包惰性根，子进程 import 链 ~1.74→~0.9s

PR #277。zebra_agent_worker/__init__（24 名/12 模块急切链）改 PEP 562 惰性——
child 只触达其显式导入的模块，control(724ms)/recovery(222ms)/main/resume 链完全
不再加载。101.7 importtime 实测（perf4→perf5 镜像）：包导入 **1.90s→20ms**；
子进程总 import 链 ~1.74s→~0.9s。零新增测试失败（worker 套件同 6 个基线既有，
stash 对照）；新增 worker 轻导入回归。101.7 基线已切 perf5-lazyworker 镜像。

**两轮 D1 合计结构性削减**：子进程 import 2.0s→~0.9s（-55%），预估子进程
~3.0→~1.9 CPU·s，专用 16 worker 现实容量 ~2.6-3.2/s——3/s 进入可达带但无余量。
剩余热点（agent_core.ports.agent_tasks 337ms、execution_finalization→
agent_integrations 237ms）为执行路径真实依赖，继续削减需重构 contracts 导入面，
边际收益递减。

**下一步**：用户授权第二个专用窗口后按冻结口径（3/s，30s 预热+60s 稳态，零容量
拒绝）正式复验；通过则接 E1-C/O 正式档位。窗口执行包（停产/恢复/守卫脚本）已沉淀
于 /tmp/window-*.sh 与宿主 /data/zebra-e1a/window/。

## 2026-11-10 专用窗口 2 回执：3/s 仍 FAIL（1.5/s），真正根因改判为维护回环饱和

深夜窗口（00:19-01:0x，79 容器停产，tmpfs 三容器本轮保留运行规避上轮事故）。
闸门 perf5 空闲单任务 2.89s（perf2 时代 3.31s，D1 兑现 -13%）；16 worker 正式
3/s 窗口 + 256 SSE（连续第三轮 256/256 全过）：接受 135（1.50/s），容量拒绝 134，
密封对账 269/269 零损坏。**~1.5/s 上限第四次复现且与舰队规模/池/CPU/镜像全部无关。**

**根因改判（本轮核心产出）**：事件流细粒度分解锁定 `execution_authority_resolved
→ plan/模型` 段 5.65-6.90s（其余段全部瞬时），而宿主 load 仅 4.8-7.7（CPU 大量空闲）。
pg_stat_statements 抓到三个维护回环在负载下自放大：
1. 流提示 relay 成功路径打转：`WITH picked…session_streams` 认领 **114,510 次/90s
   （~1,900/s）**——D1-v0 的租约有界化只约束了失败路径；publish 成功→settle→
   立即再到期→再认领的环在负载下全速循环；
2. 检查点观察/消费查询三变体各 **23 万次/90s**（~0.2ms/次，聚合吞掉管线）；
3. scope 咨询锁 **30,091 次获取×2ms**（~500/s，单核等效串行）。
结论：3/s 的约束不是执行器引导（D1 已减半，仍必要但非绑定），而是**投影/唤醒
维护面在负载下的回环饱和**，任务启动在等待检查点就绪。附带发现：101.7 此前
缺 Redis 依赖（本轮补上 TLS Redis，6.90→5.65s 小幅改善，非主因）。

**下一步（D2 提案）**：维护回环负载整形——relay 成功路径加最小重认领间隔/批量
水位、checkpoint 消费者在 pending 高水位下按事件通知而非固定节拍、咨询锁获取
合并。量化目标：负载下 auth→model ≤2.5s、容量 ≥3/s。生产已全量恢复（79/79+3
保留，健康抽查通过）。证据：window2/（停产清单）、e1a-w2/redis/lock 日志与
pg_stat_statements 快照（宿主 /tmp 与 /data/zebra-e1a/window2/）。

## 2026-11-10 D2-v1 落地：v127 列级覆盖源比较，+28% 接受吞吐

窗口 2 归因结论修正后的第一个修复。v96 UPDATE 触发器以
`coverage_model_event_source(to_jsonb(OLD/NEW))` 为门（每更新行两次整行 JSONB
序列化）；位置分配/投影块等派生态更新使其在 1 任务/s 下达 466 次评估/s 且操作数
恒相等。v127 改列级 `IS DISTINCT ROW` 比较（语义等价、免序列化）。101.7 带产探针
（3/s×60s，语句统计重置）：接受 1.03→**1.32/s（+28%）**，body-ARRAY 语句
466→**174/s（-63%**，余量为 INSERT/DELETE 触发器合法记账），事务率 632→460/s。
顺带修复迁移目录测试的过期期望（基线既有失败）并收紧 schema 门（缺最新必需迁移
即拒绝启动）。基线镜像 perf6-coverage-compare，DB v127。3/s 专用复验待下一个
授权窗口；剩余放大项：事件页多次遍历（~30×/任务）与 INSERT 触发器记账。

## 2026-11-10 D2 考古终局：剩余成本为设计内验证路径，3/s 需写入路径批量化

v127 之后对残余放大的逐层归因（语句指纹全文本比对）：
- 最大读者 = `WHERE ... idempotency_key = $3` 单事件查证 **83/s ≈ 每次事件追加 ~4 次
  幂等查证**（append 前存在性检查 + 写后验证 + 唤醒中继复查）——写入路径
  exactly-once 语义的设计内成本；
- 次级 = 覆盖模型 INSERT/DELETE 触发器记账 174/s（合法逐事件簿记）；
- 其余 = 检查点增量页读、回放类型分类尾页读——各自有增量/缓存设计，重复率已收敛。
结论：**没有更多"白捡"的层**。1.32/s（带产）≈ 专用机 ~2.0-2.2/s，距 3/s 的 ~40%
差距需要结构性改动：事件追加批量化（合并幂等查证为批量预检、单事务多事件）、
或 24-32 核（11-06 AWS 草案数学在降低后的每任务成本下依然成立）、或口径 2/s。
三个选项的量化依据均已落档；里程碑 3 维持 In Progress。

## 2026-11-10 D3 落地回执：关闭突发批量化已并入，合成任务无可测增益（如实）

PR #283（设计）+ 本 PR（实现）。append_events_in_transaction（跨度 CAS + ANY 预检 +
多行 INSERT）、commit_worker_events（单事务突发+终态投影，新增批量前投解析——开发期
native-script 套件抓到单事件解析器的 projection-gap 缺陷并修复）、recorder
append_close_batch（内存序列分配，鸭子类型回退）。回归：worker 1357 过（仅 6 基线
既有）、storage 1300 过（4 基线既有）、新增关闭批契约测试。

**101.7 同环境 A/B（带产 load 10-13）**：perf6=64 接受，perf7=64 接受——E1-A 合成
任务无可测增益。原因如实记录：设计稿预估基于"收尾簇 4-5 事件"，实测簇仅 2 事件
（TURN+SESSION terminal；answer/模型增量在各自时点，memory 云上延迟），批收益
~1 事务/任务，在饱和中被读侧放大（auth→model 5.66s@load7.6）淹没。批基础设施
对真实工作负载（多增量流式回合）仍有价值，保留为 perf7 基线（严格更优）。
**3/s 的剩余差距在会话启动读侧等待**——下一靶点：auth→model 段的检查点/绑定
等待路径考古。
