当前状态补充：HA02候选已在独立分支发布，真实PG通过，完整门禁被基线阻塞；原生整改01
候选242定向+1真实PG通过，ERPNext整改02待领取。见[分批整改](CA_BASELINE_GATE_REMEDIATION.md)。
HA02未主线合入，03仍Locked，不宣称下游就绪。以下保留原规划状态作为历史。

# Cloud Agent 高可用分阶段任务清单 v1

当前实施：02完整门禁被基线失败阻塞、真实PG5项通过；保持Review，[实现/限制/验证](CA-HA-02_readiness_preflight.md#6-ca-ha-02候选实现2026-10-31review)；不代表完整HA/性能达标。

日期2026-10-31；配套[正式方案](CLOUD_HIGH_AVAILABILITY_PLAN_v1.md)。
本文件是执行拆解，不是已实现能力列表；00已合入并推送cloud-agent，UX文档补充已完成；用户后续仅授权CA-HA-02候选实施，其他任务仍未启动。
人类最终负责人Luke Ding；各实现卡领取前确定一位人类Owner和独立Reviewer，
一任务/一分支/一worktree；本文角色是建议分工，不启动并行代理或后台任务。

## 1. 登记、依赖和激活规则

| ID | 阶段/交付 | 状态 | 依赖 | 建议负责角色 |
| --- | --- | --- | --- | --- |
| CA-HA-UX-00 | 用户体验/并发性能验收文档补充 | Review：revision 3目标未验证 | 01已集成e8a4f10b；本轮仅文档授权 | TL/QA |
| CA-HA-00 | 正式方案、任务和文档索引 | Done：已集成推送d782039c | 当前用户授权 | TL/文档 |
| CA-HA-01 | 固定基线、DDD不变量、SLO与故障合同 | Done：revision 2文档已集成1dd88bfd，非实现 | 00评审并集成，且用户另行授权后续工作 | TL/CORE/QA |
| CA-HA-02 | API/Worker真实就绪与健康合同 | Done：完整组合门禁/实际PG5通过，代码已入本地cloud-agent | 01 | APP/RUNTIME |
| CA-HA-03 | 资源预算、空转退避与租户技术隔离 | Ready（未领取/未实施） | 01、02（共享Worker接线须串行） | RUNTIME/CORE |
| CA-HA-04 | 排空、进程隔离、强停与资源回收 | Locked | 02、03；强停候选须独立合入/验收 | RUNTIME/SRE |
| CA-HA-05 | Worker跨副本接管与旧执行者隔离 | Locked | 03、04 | CORE/存储 |
| CA-HA-06 | PostgreSQL/对象/Redis/身份依赖容错 | Locked | 02、05 | SRE/存储/安全 |
| CA-HA-07 | 多API、流重连、调度与原操作恢复 | Locked | 05、06 | APP/CORE |
| CA-HA-08 | 多故障域部署、发布与回退 | Locked | 04、06、07 | SRE/RUNTIME |
| CA-HA-09 | 容量包络、持续负载、告警与操作手册 | Locked | 03、08 | QA/SRE |
| CA-HA-10 | 固定候选完整联合验收与发布判定 | Locked | 01–09 | QA/TL |

登记方式：AGENT_TASKS.md保留本专项入口，本文件维护Locked候选卡。真正实施前在注册表
新增所领取卡并显式转Ready，验证依赖已进入授权目标cloud-agent，再领取In Progress。
主线已前进时重读冲突与依赖，不能把“代码在某个分支存在”当成依赖已满足。
Review不是Done；Done须合并并回写。生产运行及生产故障注入不由任何文档卡自动授权。

以下Owned paths是候选边界，不是当前编辑授权。01的[精确范围和依赖](CA-HA-01_baseline_and_scope.md)及
[DDD/SLO/F1合同](contracts/cloud-ha-v1/README.md)revision 2已复核集成；后续领取须冻结本卡文件子集。
发现超界先修卡/拆卡，不以扩写整个packages/apps作为临时共享所有权。
命名新增文件须职责明确，无utils/helpers倾倒文件，不引入空DDD层或无需求抽象。

## 2. 阶段零：可衡量基线与合同

### CA-HA-01 — HA基线与DDD合同

- 复用：现有Task/Run、lease/epoch/fence、不可变快照、收据、部署门禁及清理合同。
- 补齐：实际组合路径/开关矩阵、调用链、依赖分类、故障模型、负载包络和SLO测量口径。
- 候选Owned paths：本方案与清单、docs/contracts/cloud-ha-v1/、docs/evidence/ca-ha-01/，
  以及注册表/进度；不含业务实现。
- 必须交付：每条路径的权威事实源与失败结果表；候选99.9%/60s/120s目标评审，
  依赖预算、数据库持久性承诺和DR RPO/RTO明确；未知生产参数逐项标“待验证”。
- 验收：新旧Worker/cutover、API/定时调度、BFF、执行器和存储开关均可追踪到源文件；
  现有门禁失败逐项定位，不把“清理ERP违规”混入HA实现。
- 退出：合同、兼容策略、参数和后续精确Owned paths评审完成；不运行重型环境。

## 2A. 用户体验补充的执行约束

CA-HA-UX-00只补合同revision 3和下述验收，状态Review；不改变03–10的Locked状态，02另获后续实施授权。
本补充指标适用参考E1环境，非实测或生产承诺；完整计时/分母/过载/证明见
[合同7节](contracts/cloud-ha-v1/README.md#7-用户卡顿卡死与并发性能合同revision-3补充)。
各卡优先复用已有公平领取、控制lane、I/O预算、事件游标和safety net；先核对实际开关。
禁止为性能引入第二执行队列、业务租户模型或新的Task终态。

## 3. 阶段一：故障不扩散

### CA-HA-02 — 健康与就绪

- 复用：api_status_mixin.py、routes.py、现有Runtime Gate只读观测；不复制领域判定。
- 候选Owned paths：apps/api/src/zebra_agent_api/{http,http_host_auth,api_status_mixin,routes}.py；
  apps/worker/src/zebra_agent_worker/{main,loop,command_process,worker_loop_service}.py；
  tests/api/test_cloud_ha_health.py、tests/worker/test_cloud_ha_health.py；对应合同/证据。
- 补齐：显式存活/启动/就绪语义与Worker能力观测，兼容现有/health消费者。
- [02依赖/鉴权/尺寸/验收前置](CA-HA-02_readiness_preflight.md)；依赖满足不等于本轮授权代码实现。
- 验收：数据库不可达、连接耗尽、版本不兼容、排空分别返回明确非就绪；
  进程存活不因共享依赖故障被判死；恢复后自动恢复就绪且不开新Task。
- 探针短预算、缓存不掩盖超期事实；不加载历史/创建资源；错误响应不泄露DSN和凭据。
- 退出：合同测试、实际组合的有界依赖失败测试和旧客户端回归通过。

### CA-HA-03 — 资源上限与反空转

- 复用：command_process.py有界lane、worker_loop_service.py、TaskIoConnections和连接池。
- 候选Owned paths：对应Worker轮询/有界配置文件、postgres/{connection_pool,task_io}.py、
  tests/worker/test_cloud_ha_polling.py、tests/agent_storage/test_cloud_ha_budgets.py；01冻结后细化。
- 补齐：对blocked/error/空队列分别退避和抖动；技术namespace公平性、恢复/控制预算，
  全副本与每执行器总连接上限、等待队列与过载响应；不引入订阅/商业租户模型。
- 验收：持续过期/拒绝/容量不足候选不会忙轮询；单namespace洪泛不饿死另一合法任务；
  连接不足不无限排队；控制与原GET在负载下仍有独立预算。
- 验收需记录CPU、查询次数、池等待、排队年龄和拒绝率，不只断言一次返回值。
- 增补UX-02、UX-04、UX-05、UX-08：短任务排队p95≤2s/p99≤5s，低负载scope同样满足；
  无进展60s后5s内可观测（不是自动终止），后台线程/连接/队列必须有硬上限。
- 区分排队/模型/工具/HITL/UI等待与unknown；统计每scope，拒绝和超时不能从分母删除。
- 退出：确定性轮询/预算回归和后续隔离实测通过，无改变unknown重试策略。

### CA-HA-04 — 排空与回收

- 复用：CommandWorkerProcess.drain、CLOUD_FORCE_STOP_20261030及精确OCI资源所有权检查。
- 候选Owned paths：apps/worker/src/zebra_agent_worker/{command_process,session_process,runtime_cleanup_service}.py；
  agent-runtime现有force_stop_cleanup/process_supervision适配器；对应既有定向测试，01冻结清单。
- 补齐：退出先拒新领取，预算内完成/持久交接，未退出执行器的可恢复清理义务；
  把Linux隔离显式开关、部署支持与兼容旧本地行为写入启用矩阵。
- 验收：SIGTERM、卡死、逃逸子进程、退出响应丢失、Docker不可用、晚到创建；
  共享Worker及另一Task继续服务，未有kernel/存储/清理证明时不报resources_released。
- 验收环境正常和中断后均按owner清单清理，保留数据卷、旧收据与unknown依据。
- 增补UX-05、UX-06、UX-10：依赖可用且隔离已授权时，S0至原控制收据p99≤2s、
  S1至执行器退出≤10s、完整回收≤30s；线程/HTTP超时不能充当退出证明。
- 另一scope的短任务、原GET/停止通路仍满足目标；原停止unknown只GET。
- 退出：退出/租约撤销/精确清理/权威同步分别有证据，回滚不扩大清理范围。

## 4. 阶段二：安全接管与依赖容错

### CA-HA-05 — 跨副本与旧执行者

- 复用：PostgresLeaseStore、SessionClaimService、现有恢复/强停和原操作收据。
- 候选Owned paths：postgres/leases.py、apps/worker/src/zebra_agent_worker/{claims,recovery}.py；
  tests/worker/test_cloud_ha_takeover.py、tests/agent_storage/test_cloud_ha_fencing.py；01冻结具体改动。
- 补齐：Worker骤停/分区/旧owner恢复、接管期限与当前权限校验的完整链路证据。
- 验收：至少两个独立Worker进程，同Task同Run接管；旧epoch/token/owner写入被拒；
  已提交业务效果只恢复其原结果；不兼容Worker拒执行，历史快照不漂移。
- 恢复时身份过期必须安全阻塞，不延长grant；在途外部请求结果不明保留unknown，
  不把fence拒写当作外部效果绝对未发生。
- 退出：按01目标测量执行接管及安全阻塞两类结果，不以新Task成功代替旧Task恢复。

### CA-HA-06 — 依赖故障切换与DR

- 复用：PostgresDatabase/池、Task I/O预算、已有对象存储/流提示及身份验证适配器。
- 候选Owned paths：对应已查明的存储连接/依赖适配器、deploy/helm参数、
  tests/compose/cloud_ha_dependencies/；01拆分数据库与其他依赖子卡后各自独占路径。
- 补齐：主备切换连接恢复、Redis按角色降级、对象读写不确定、Broker/JWKS故障与撤销一致性；
  主备防双主/写入隔离、备份读取和恢复后epoch处理。
- 验收：提交成功响应丢失、主库失联/升主、陈旧连接、Redis中断、对象上传应答丢失；
  已确认数据/原收据满足声明RPO，未知提交不重发；权限过期/撤销不因故障绕过。
- 独立恢复备份：校验事件/收据/对象摘要及Coverage定位，记录实际DR RPO/RTO；
  恢复副本不能与旧权威同时写同namespace。异步复制不允许声称RPO=0。
- 退出：依赖拓扑与能力真实存在且完成联合证据；未提供服务参数则保持该项未验。

### CA-HA-07 — 流、原操作与调度恢复

- 复用：持久事件、SDK/BFF原GET、Controller/映射CAS、TaskScheduleMaterializer。
- 候选Owned paths：原生AG-UI恢复模块、apps/scheduler既有组合、对应集成测试；
  如涉及Go BFF/SDK，先在其仓库独立登记消费任务，不在Native卡直接越界修改。
- 补齐：负载均衡换副本、SSE中断与游标缺口、Scheduler多实例故障接管。
- 验收：同一Task/Run断流后接续无漏事实/无重复业务派发，旧事件版本保持兼容；
  原审批/效果收据/挂载unknown只GET恢复，重连不自动RUN、不重领Controller。
- 调度验收：到期任务争抢/领取进程死亡/响应丢失仍只消费原触发，旧claim不能二次提交。
- 增补UX-01、UX-03、UX-04、UX-07、UX-09：提交反馈p99≤200ms但不伪报接受，原收据确认反馈≤3s；
  参考短任务首内容p99≤2s、持久帧到呈现≤500ms、等待说明≤1s、授权合法断流补齐≤5s。
- 长历史10k/100k/1m事件分桶，固定分页/显示≤100；状态/原GET p99≤1s、交互p99≤200ms。
  跨进程时钟误差、参考浏览器/RTT和上游TTFT单列，不用keepalive代替业务进展。
- SDK/BFF/Host真实界面必须先独立登记CA-HA-07消费者任务及精确Owned paths；当前无Go/SDK/UI
  修改授权，平台前端mock保留；mock渲染不能替代真实合同/传输/浏览器联合验证。
- 退出：双API/双Worker及实际受影响SDK/BFF合同联合通过，不宣称所有业务产品已接入。

## 5. 阶段三：部署、容量和最终证明

### CA-HA-08 — 部署拓扑与滚动发布

- 复用：现有Helm、PDB、固定镜像和P5门禁/排空/回退原操作。
- 候选Owned paths：deploy/helm/zebra-agent/{values.yaml,values.schema.json,templates/}中
  明确列出的API/Worker/Scheduler/探针/拓扑模板，tests/deploy/test_helm_chart.py及对应新模板测试。
- 补齐：跨节点/故障域、唯一实例观测、显式终止预算、就绪撤流、Scheduler部署、
  如确有需求才启用HPA；配套外部存储/密钥/身份服务故障域清单。
- 验收：渲染检查不能替代真实故障；升级/回退/单节点丢失期间合法准入与原GET可恢复，
  旧任务继续使用冻结配置；PDB不被写成防节点宕机证明。
- 增补UX-08：扩容信号同时观察scope排队年龄、执行槽、连接/线程/存储预算与上游限额；
  缩容必须排空，不以杀共享Worker实现限流；不将扩副本当作修复任务死锁。
- 退出：固定候选拓扑的隔离集群演练通过；真实生产发布仍须另行授权。

### CA-HA-09 — 容量、持续负载与运维

- 复用：现有Trace/metrics、资源限额、技术usage与任务原坐标。
- 候选Owned paths：agent-observability中已存在的指标适配器、tests/compose/cloud_ha_capacity/、
  docs/runbooks/cloud-ha.md；01先确认模块名和路径，避免平行指标系统。
- 补齐：明确稳定负载包络、恢复风暴/噪声namespace隔离、队列年龄与unknown年龄告警；
  故障处理、回滚、数据恢复和证据保留手册。
- 验收：固定候选连续24小时隔离持续负载，记录峰值与稳态、重启/恢复曲线和残留资源；
  短基准不能替代持续测试，不能把24小时测试外推为30日SLO实绩。
- 发布后才有条件开展30日观测；当前阶段不启动，也不新增长期本机后台负载。
- 增补UX-01–10：E1-A短任务、E1-R恢复、E1-C的1/16/32scope及E1-O的0.5x/1x/1.5x/2x
  分别记录offer/issue/complete/拒绝及每scope等待；生成器饱和不能判通过。
- 确定性依赖fixture预算与真实模型/冷沙箱/HITL/UI分桶，不混算首内容p99；
  首响应、排队、模型TTFT、平台传输与浏览器呈现必须有完整原关联时间线。
- 24h RSS末小时均值≤首稳态小时1.1倍且不越限；历史持久存储增长不当泄漏删除。
  无进展、控制通路受挤占、unknown积压和线程/资源泄漏均需告警与授权处置说明。
- 退出：包络内不失控增长，包络外明确背压；告警实际触发/恢复且可定位原任务。

### CA-HA-10 — 联合出口与发布判定

- 候选Owned paths：tests/compose/cloud_ha_acceptance/、docs/evidence/ca-ha-10/、
  本方案/清单/注册表/进度及发布清单适配文件（先冻结精确路径）。
- 固定最终整合树执行：完整make test/check、合同兼容、旧数据/任务恢复、真实PG/多进程、
  必要的SDK/BFF联合、故障矩阵、持续负载与资源回收检查。
- 两仓库有改动时分别完整验证并固定源；本机串行、唯一重型环境，不绕过失败门禁。
- 遗留门禁失败：给出确切基线、文件/用例和单独修复任务；未解决不能写“全绿”。
- 出口状态分别标识：设计完成/实现验证/隔离HA演练通过/生产演练通过/30日SLO达标。
- UX-01–10逐条附证据/未验证状态，缺项阻断相应容量承诺；API可用性不替代用户体验通过。
- 验收不要求制造新的业务或模型工作；重放只恢复已有事实，新增样本用显式隔离测试身份。
- 退出：矩阵每行有可复核证据；缺项明确未验证并阻断相应能力发布，不靠风险文案放行。

## 6. 最小联合故障矩阵

| 场景 | 必须证明 | 主要责任卡 |
| --- | --- | --- |
| API宕机/换副本/响应丢失 | 原Task和收据可查，无自动业务重发，满足API恢复目标 | 02/07/08 |
| Worker骤停、节点丢失、旧Worker恢复 | 有效fence唯一，旧执行者拒写，同Run恢复或有理由阻塞 | 04/05/08 |
| PostgreSQL切换/提交结果未知 | 已确认数据满足约定RPO，池恢复，未知提交保持unknown | 06 |
| Redis/对象/Broker/JWKS故障 | 按关键性降级/拒绝，持久事实不丢，当前授权不绕过 | 02/06 |
| 取消/强停/清理服务失败与晚到资源 | 退出、清理、同步分项证明，资源义务不被误清空 | 04 |
| 过载/单namespace洪泛/恢复风暴 | 内存/连接/队列有界，控制与其他namespace不被饿死 | 03/09 |
| 滚动发布/回退 | 冻结配置/旧协议可恢复，准入/排空不互相冒充 | 08 |
| 多Scheduler/流中断/审批等待 | 原触发/原消息/原收据关联不漂移，Controller不自动重领 | 07 |
| 备份恢复/旧权威重连 | 摘要、对象、收据及Coverage可读，权威隔离后方可放写 | 06 |
| 验收正常/失败/中断退出 | 生产者先停，owner资源精确回收，保留证据/数据并停机 | 04/09/10 |

## 7. 证据包与任务完成条件

每包最少包含：候选源/镜像/合同/配置摘要、环境与owner、负载参数、故障注入和恢复时间线、
原操作和fence坐标、旧数据/收据/Coverage兼容检查、负面事实、测试出口码及跳过原因、
资源前后清单、回退结论。不得存密钥、令牌、DSN或业务原文。

受控实验每项至少三次且全通过，保留最差值；一次未恢复不能按均值掩盖。
真实生产30日SLO另有实际观测，不能把实验次数转换成可用性百分比。
阻塞与unknown要有授权处置入口，不以自动新Task或删除旧状态清积压。
本轮01只验证文档链接、合同JSON/任务一致性、真实源路径、变更范围和新增文档尺寸；所有实现/演练仍未开始。

## 8. 用户体验专项验收索引（均未运行）

| ID | 必测负面场景 | 不可替代的出口 |
| --- | --- | --- |
| UX-01、UX-02 | 准入响应丢失、长队列、授权过期 | 原收据确认/真实排队时间；unknown不自动POST |
| UX-03、UX-07 | 模型首token慢、平台帧延迟、慢消费者、断流/重复帧 | 上游/平台/界面分段与原游标补齐；不得重做业务 |
| UX-04 | 合法长工具/HITL/UI等待、只有心跳、结构性恢复反复失败 | 阶段说明/疑似停滞观测；不误杀、不假进展 |
| UX-05、UX-08 | 一scope洪泛、单任务挂起、线程/连接耗尽 | 安静scope/停止/原GET守预算；有界拒绝与全部失败样本 |
| UX-06 | 停止COMMIT响应丢失、执行器逃逸、Docker失联、晚到创建 | 独立退出/租约/精确清理/同步证明；未知继续对账 |
| UX-09、UX-10 | 长历史、全天负载、取消与中断退出 | 有界读取/渲染/内存和owner资源清单；保留历史及Coverage |

所有UX场景均not_run。强停候选未合入时UX-06相应子场景标blocked_dependency，
未完成消费者登记/真实浏览器环境时端到端UI指标标environment_unverified；不能以替身填PASS。

2026-10-31完整验收：[当前证据](evidence/ca-ha-02/full-validation.json)。02未满足条件合并，
03继续Locked；已核对01完成、02未合入，预算/退避/公平及入口池覆盖范围见
[02第8节](CA-HA-02_readiness_preflight.md#8-完整验收与03依赖复核)，没有提前启动03。

当前集成：2026-11-01 原生01/ERP02/HA02已完成组合门禁，代码2b908448快进本地cloud-agent；[证据](evidence/ca-baseline-gate-02/validation.json)。最终文档/证据随主线推送。CA-HA-03仅Ready；其他Locked/UX not_run不因本次健康验收自动升级，未部署/生产迁移。
