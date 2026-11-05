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
