# CA-HA-03 — 轮询和资源预算收口

2026-11-02；Owner Luke Ding；执行Codex；branch `codex/ca-ha-03-budgets`；基线`56ae352a5`。
03A/03B为本地Review候选；03整体仍In Progress，完整E1容量验收尚未完成。
没有生产部署/迁移、业务Run重放、模型请求或旧环境恢复。

## 已追踪的实际路径

- `main.py`建立普通池后组合`loop.py`；cutover决定旧串行循环或`CommandWorkerProcess`。
- 旧循环只在空队列sleep，有READY但全被跳过可无等待轮询；本地默认行为保留。
- 命令循环的execution/control各有独立DB线程和游标；原固定间隔不能区分持续deferred。
- Consumer的发现/身份解析及`CommandRecoverySweep`复用同两个storage函数。
  这两处原`connect()`没有读取期限；真实表锁可长期占住DB lane。
- 强停、handoff和Task I/O已经有原生有界连接，直接复用；不改身份解析/原意图语义。

## 03A实现

1. Cloud旧循环及命令循环区分progress/idle/blocked/error，每lane独立保留小型退避状态。
   空和阻塞指数退避到1s，错误到5s，80%–100%抖动；最小非进展等待50ms。
   显式较慢操作员间隔保持下界，不能据此承诺所有配置满足SLO；有进展回到原间隔。
2. 控制lane独立退避，执行侧error/blocked不延长其等待；SIGTERM唤醒命令循环Event。
   原Consumer槽、Future drain、cursor公平扫描、canonical control和收据均复用。
   调整的是发现周期，没有新增执行重试或自动补发unknown操作。
3. `discover_command_pickups`与`resolve_command_pickup`统一改用`connect_task_io()`：
   复用原2s总I/O预算和最多50ms锁等待。覆盖正常消费和恢复扫描，不在每个caller打补丁。
   DB错误继续沿原deferred/重排路径传播，不被当成未提交或资源释放证明。
4. 拒绝NaN/Infinity/bool轮询间隔；命令循环原0–30s配置约束保持。
5. 从已500行的command process抽出后台周期与脱敏trace职责；未扩写为第二调度器。

## 03A时点已有上限与03B缺口（历史）

| 路径 | 当前已有约束 | 尚缺证明/实现 |
| --- | --- | --- |
| 普通PG池 | 每进程max8、等待max32、借用2s | 只在pool scope覆盖路径有效，不能作为全副本总额 |
| Task I/O | 每次2s总期限/锁等待上限 | 短连接绕过普通池，无全副本并发总配额 |
| 命令执行 | execution_slots1–32；信号量先占槽再handoff | 按namespace负载测量及跨Worker/执行器聚合预算 |
| 命令DB lane | admission/control各2线程，非阻塞槽拒绝多余提交 | 独立线程不等于数据库连接容量预留 |
| 维护/清理 | 各单独1线程，不与execution排队 | 各维护源实际SQL/CPU总预算与故障恢复实测 |
| API入口 | server.main包普通池；Helm直接uvicorn factory | 统一实际入口，计入API副本/请求线程与探针 |
| 隔离执行器 | 每个child也进入自己的普通池scope | 必须乘执行器并发/父Worker数，不能只算父池 |

`PostgresDatabase`在构造时捕获ContextVar的池；动态在线程中构造的adapter还需复核
context传播，不能把main线程pool scope推断为所有线程/直连都受限。
本批未引入全局连接注册表/第二执行队列/新商业租户模型或第二套执行事实。

## 验证边界

机器记录见`docs/evidence/ca-ha-03/validation.json`。

- 先红后绿：新轮询回归修复前8失败/2通过；真实PG表锁回归修复前2失败。
- 实际新旧run路径、2000次连续无进展边界、零间隔deferred、独立控制信号/真实drain。
- 独立PG的公平游标/活跃scope插入/执行满槽控制/表锁/普通池回归33通过。
  PG限1CPU/512MiB/PID128，数据tmpfs256MiB；测试创建的精确容器ID均已回收。
  首次资源参数WAL增长导致DiskFull，后用PG原生min/max_wal_size32MiB后整组通过；
  未把资源失败改成skip，未启动或删除旧环境来释放空间。
- 完整Worker首次1325通过/1失败/759条件跳过；唯一失败在干净基线56ae352a5复现：
  原Mock只提供status而已有生产SQL还要求forced列。只补齐Mock的forced=false，
  不把生产读取改成缺列默认放行；最终完整Worker1326通过/759条件跳过，make check全绿；机器记录保留各次边界。
- 本批未进行生产/多节点故障注入、全仓make test或E1-C/E1-O容量验收；不宣称HA达标。

## 03A时点的03B目标（实现进度见下文）

1. 在任务卡冻结精确API/Worker/child/config/storage/Helm路径后，统一现有池入口。
2. 计算API副本、Worker父/子进程、scheduler、cleanup、探针和Task I/O总连接，
   明确部署上限及控制/原GET预留、等待/拒绝策略；不把单池或单角色上限冒充全局预算。
3. 在独立限额环境记录SQL次数、CPU、池等待、线程/队列上限、队列年龄与拒绝率；
   flood scope和低负载scope分别测p95/p99，拒绝/超时纳入分母。
4. 03B完整验收/评审合入后再解锁04；本批不改旧强停证据缺失的人工对账策略。

03A候选已验证；独立AI评审与修复见文末，人工评审未完成。生产镜像/schema组合需在部署前单独冻结；
本批不直接将cloud-agent镜像替换到现有生产，不通过升级自动重跑旧任务。

## 03B — 连接预算与控制容量候选（2026-11-02，Review）

03B主体实现与本地验证完成；03整体仍In Progress。机器记录在
`docs/evidence/ca-ha-03b/validation.json`。默认未启用、未部署生产。

### 装配与生命周期

- `ZEBRA_DATABASE_BUDGET_JSON`为空/缺省保持旧模式；非空时必须给完整配置，拒绝重复键、
  非整数/布尔限额、不完整组件或超预算。普通池、普通直连、只读、控制、探针分别计数。
- 普通池复用原psycopg_pool；直连和Task I/O复用同一进程额度，先拿额度再做DNS/连接。
  原生连接关闭才归还；连接借用、回调结束、await取消不算物理退出。失败关闭继续占额度。
- 额度耗尽立即拒绝，不新增等待队列；普通池原等待队列仍最多32、借用预算2s。
  不据此推断同一请求此前的业务写入未发生；HTTP503不触发本批任何业务重发。
- API普通/只读/控制同步调用各有有界线程池；Future实际完成才归还线程槽。
  请求scope覆盖preflight、Coverage、Artifact、管理回调及PG扩展/插件/MCP异步适配器。
  同步回调中的嵌套async存储仍由原回调持有槽，不重复计费；取消不提前释放。
  列表已有元数据并发上限为min(8,read)，关闭预算时仍为8；不新增等待队列。
  请求准入在响应头后释放，SSE后续I/O仍计实际连接；本批不声明SSE总连接数已全面有界。
- 精确GET健康路径不占业务准入；旧`/health`纯缓存响应不排同步线程。
  探针有独立额度，业务read/control满载不会挤掉真实数据库观测。
- 所有已查明的非迁移直连入口纳入额度，包括能力维护、执行器证据、强停恢复和safety net。
  迁移/操作员连接列入external预留；不修改迁移历史或业务schema。
- Worker后台线程只传PG容量/池/lane，不继承原本不存在的业务授权/事务ContextVar。
  HTTP线程保留原请求上下文。私有执行器factory也在其自身预算scope内组合。
- API/Worker/执行器/独立清理器/Scheduler都显式进入根scope；开启后禁止嵌套根scope
  放大进程预算。API多workers/reload模式拒绝启动；每声明副本只允许一个API进程。

### 总预算的成立条件

`fleet`填**发布峰值**，含surge，不是稳态副本数。要求：

`sum(fleet.values()) * (pool + normal + read + control + probe) + external + server_reserved <= max_connections`

- 包含API、Worker、全部并发私有执行器、清理器和Scheduler；执行器数不得少于
  Worker峰值乘执行槽数。每个实际启动组件必须在配置中有正数份额。
- 启动核对实际PG最大连接数、两类服务端预留总额及应用账户非superuser；配置不一致拒绝。
  参数语义见[PostgreSQL官方连接设置](https://www.postgresql.org/docs/17/runtime-config-connection.html)。
- `maxSurge:1`不能约束仍存活的terminating Pod；普通单次变更也可能同时保留旧、新各一整组。
  依据[Kubernetes官方Deployment说明](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment)。
  Helm示例为这类重叠按API/Worker各2*replicas预留，执行器随Worker峰值相乘；
  这是声明算术，不是已实施的存活进程准入。开启时使用API包装入口和独立live/ready探针。
- 示例为每进程17连接、26个声明峰值进程，总442；另预留3+4，合计449<=512。
  这是算术示例，不是当前生产参数或调大生产数据库的建议；没有执行服务端参数修改。
- **当前只允许全新隔离staging安装**：预算开启时Helm upgrade直接拒绝，关闭时升级行为保持。
  在HA08验证生命周期前，预算模式不支持Helm rollback（旧清单可绕过模板guard）、
  kubectl apply/rolling restart、连续发布、节点失联等过渡；不能把2*replicas当作这些路径的上限。
  staging重建前必须证明旧进程/连接已退出，或另行冻结并证明实际重叠预算；本批不执行重建。
- **这不是分布式进程准入服务**：手工扩容、额外客户端、数据库切换或参数漂移超出声明时，
  该证明失效。实际部署必须冻结并约束这些上限，后续08/09负责拓扑/漂移告警与验收。
  当前生产未启用，不能把配置算术称为已在线验证的全副本容量。

### 已验与未验

- 广覆盖API/Worker/Scheduler/部署3102通过、951条件跳过；此后新增探针隔离、私有factory
  scope和嵌套根拒绝，另做定向及真实PG复验，逐次结果分别保留。
- 真实PG最终113通过、12条件跳过：普通池/直连满载时原生强停接受及原GET可用，
  两个独立spawn进程预算、原生失败关闭、借用保留、callback复用、专属健康探针、
  私有child `--check` factory作用域；未调用模型或重跑业务Run。
- 微型压力样本：1次强停POST、20次原GET；普通池和普通直连全占满。
  记录控制/只读SQL次数、延迟、父进程CPU及峰值/拒绝数；采样时normal active=2是
  刻意持有的压力，测试退出后断言归零。不是生产p99或E1容量认证。
- PG限1CPU/768MiB/PID128，数据tmpfs512MiB，min/max WAL32MiB；精确测试容器已回收。
  不恢复旧环境、不操作生产服务/数据库/数据卷；不因错误而自动重发未知操作。
- Helm实际渲染四类：关闭/开启通过，漏surge和总额不足均拒绝；`make check`通过。
- 没有专用E1两API/两Worker跨节点环境，没有1m事件基线和30min各档稳态，
  没有真实IdP/Broker/完整浏览器联合验收、生产切换或人工评审；独立AI评审见下，04不自动解锁。

### 评审与下一步

03B改动跨连接适配、所有实际入口和部署参数，启用时必须共同匹配，防止半接线漏计。
实现与验证保留在同一任务；较多行数来自跨入口回归/机器记录，未增加依赖、UI或业务状态机。
03A父提交保留，可分别审查两个增量；不自动合并或切生产镜像。

下一步：收口独立AI复审；在专用隔离环境冻结E1清单并测每scope排队/拒绝率、
CPU/SQL/线程/连接/队列及p95/p99，明确运行时fleet漂移处置；完成后才作03整体发布判定。
旧任务退出证据缺口的自动核对/告警仍属后续04/09，本批未以放宽退出证明代替它。


## 独立AI评审修复与E1环境核查（2026-11-02）

评审56ae352a..1d5207b4发现两项Important：部分读回调绕过线程额度、发布预算漏掉
terminating进程。共享dispatcher修复后，复审又发现列表并发8与小read额度冲突；
沿用原Semaphore按read额度收紧，保留默认关闭行为。先红后绿回归覆盖取消后的真实回调、
PG异步适配器、嵌套同步回调、三条记录元数据读取及Cloud缓存健康路径；原生授权/期限保留。
本次机器证据见`docs/evidence/ca-ha-03-review/validation.json`，不覆盖或改写03B原记录。

只读环境核查：本地colima-zebra-gvisor与orbstack上下文均不可达；仓库
LogicStormINC/zebra的runner API返回0个self-hosted runner，environment列表为空。
工作流声明的kubernetes/gvisor与trench-staging标签不证明环境已配置。
192.168.101.7仅确认是既有单台生产主机，未找到kubectl/k3s/microk8s命令；
这不证明无任何集群，也不足以证明E1的独立节点/故障域。未启动旧环境或调度工作流。
因此E1仍标记`environment_unverified`，不能用本机微测或该主机替代多节点验收。


## E1新环境集成增量（2026-11-03）

用户明确授权服务器/OrbStack创建新测试环境；现有运行中的runsc基础设施只复用引擎，
不恢复旧工作负载。实际两主机Compose替代不必要的新Kubernetes控制面；各1API+1Worker，
每角色2CPU/2GiB，slot4。VM独立24GiB数据文件系统、各节点512MiB工作卷；新实例/端口/
凭据/命名空间均有独立所有权，既有生产未替换。操作步骤见tests/compose/cloud_ha_e1/README.md。

实际校准发现normal直连2不足以容纳空闲维护并发；E1采用pool4/normal8/read2/control2/
probe1，峰值fleet14，总238+external4+server_reserved3=245<=256。Helm算术示例同步为
normal8及512声明上限，以覆盖其不同的26进程重叠预算；依旧默认关闭且不是生产参数建议。

另修复两个真实组合问题：独立迁移校验profile后使用已预留external份额；ClientEffectRecovery
保留原DSN并复用Task I/O，不再用options改写DSN而触发跨身份拒绝。原预算身份比较不放宽。
定向/真实PG及基线失败边界写入E1证据；现有原生HTTP测试的ScriptedModel缺预算hook，
用原恢复模块同样复现，不能将其冒充本轮完整原生HTTP验收通过。

能力代表可执行组合，非供应商健康或单Task授权。E1保留原生模型适配器/评审配置，
仅在自有容器用不可写hosts+只含测试CA的certifi挂载固定到本地TLS替身；无真实模型密钥。
启动前实查分辨率/对端/证书/标记及反例，所有能力/模型/Coverage结果标记synthetic。
模型质量、真实Provider、IdP/浏览器及E1完整容量/故障矩阵尚未验收。


### E1实际镜像与单次Task回执（2026-11-03）

新两端API/Worker已用0fd9f0c1镜像，2139运行文件及3符号链接在四容器匹配；
API TLS live/ready与Worker控制新鲜度分别验证。旧测试进程退出及ha_app连接归零
后才冷切换，非滚动发布/重启证明。实际记录见evidence/ca-ha-03-e1/validation.json。

新合成Task仅POST一次201，到授权/gVisor后WorkerBudgetError关闭；原生CLI根组合
没有可信exact-request counter。model_request_started是意图事件，不代表Provider发送；
模型预留0、工具0、1尝试、11事件保留。正确修复入口为既有ModelRequestBudgetFactory，
需另外冻结实施边界并证明计数/输出上界；本片未绕过guard或重跑失败Task。

新环境已建立，但端到端模型执行及完整E1容量/故障矩阵未通过。SSH转发依赖Mac在线，
控制/数据面单VM，各节点tmpfs工作卷不跨节点持久，不能声称存储或物理主机HA。


### 预算组合源修复（2026-11-03，未切镜像）

旧入口还注入普通同步HTTP客户端，先于缺counter被WorkerBudgetError拒绝；原历史回执
保留，补充原因不表示模型已发送。CloudWorkerComposition新增可选既有factory，默认None，
显式库调用参数保持优先；普通/委派根继承。CLI及隔离子进程使用原生可取消HTTP，本地不变。
E1合成模型与proof共用JSON UTF8字节计量，不冒充DeepSeek tokenizer；HTTP解析后重新
编码计量，guarded调用者另行证明exact wire等于该编码。不是任意HTTP原字节计量承诺。
输出超过实际max_tokens及超限请求拒绝。自检覆盖实际函数/HTTP与反例，源码评审通过。
回归范围及已修旧测试分别记录，不能拼成全仓重跑通过。显式fixture组合、模型冻结output cap、
新镜像与新Task未验；完整E1/生产HA未验。见evidence/ca-ha-03-e1/budget-composition/。


### Executor monitor preserves emergency control capacity (2026-11-03)

The monitor retains a query connection through the isolated process scope. It
must use the existing normal lane; holding control prevents its own exit ACK
under the legal control=1 configuration. Register, STOP and ACK keep control.
No new role or capacity is added. Execution slots bound monitor concurrency;
normal exhaustion still rejects monitoring, so arbitrary saturation RTO remains
unqualified. Real Linux PG30, worker/API19, make check and independent source
review passed. The candidate is not yet promoted to workers.

The separately promoted existing Broker Task-control protocol now allows the
signed e08 stop to reach stopped with execution/lease/sandbox/synchronization
confirmed. f69 lacks its original exact exit witness and remains in
requires_reconciliation. Neither old Task was replayed; historical ACKs are not
fabricated. Full E1 capacity/fault qualification remains open.


### Dual-engine cleanup candidate (2026-11-03)

The current local pair needs cleanup2. Pool3/normal8/read2/control2/probe1 and
fleet2+2+8+2+1 total247 including external4/reserved3, below PG256. Both node
preflights and unchanged baseline HMAC passed; do not overlap old/new roles.
Ordinary cleanup routes by the recorded revoked fence, prioritizes its engine,
and retains all-engine remaining checks. Foreign-only work cannot spend another
owner's retry/delay budget. Force-stop routing retains shared revocation/sync,
frontier and absolute10min control even without an engine. Deadline quarantine
still remains available on any cleaner. Real Linux PG46 and make check passed;
independent source review found no important issues. The10 new cases fake engine
removal and inject unit ACK facts; real two-node deletion is still unverified.
See evidence/ca-ha-03-e1/engine-affinity/validation.json. New images/publication,
E1 capacity/fault gates, physical/storage HA and production activation are pending.


### Frozen9b runtime acceptance on two local nodes (2026-11-03)

Both logical nodes now run9b4f9ad3, Native approval7 and the matching247 profile.
Native full-flow Tasks completed18.99s/18.73s with one pwd, two settled synthetic
model calls, matching budget renewal and two real kernel exit ACK pairs each.
Active-executor freeze probes returned accepted STOP, retained unconfirmed exit
until the original process resumed, then exact ACK/resource absence/cancellation.
Primary cleanup removed the registered OCI object while its Worker was still
frozen. The object existed but had not started; running-tool kill is not claimed.
Both Workers are restored, old7 event/budget/unknown hashes unchanged. Full E1
corpus/load/fault/soak, physical/storage HA and production remain unqualified.
See evidence/ca-ha-03-e1/native-9b4f9ad3/validation.json for every case and boundary.


### Deferred E1 baseline and checked-bytecode candidate (2026-11-03)

Native8 separately freezes existing deferred provision; cold switch preserved all
13 prior sessions' fact hashes. Fresh no-tool completed6.347s without any OCI
instance; approved pwd completed17.7s with provisioning after approval, exact
cleanup and real exit ACKs. Eight fresh concurrent offers each returned201 once
and completed8.307–20.549s (median11.781), without tools/OCI. This is a diagnostic
burst, not the E1 historical/SSE/load qualification. A malformed operator marker
selected normal pwd and was stopped once without approval/replay; retained.

Cold import consumed~1.63–1.66 CPU seconds versus~0.81–0.88 with standard
checked-hash bytecode in an isolated prototype. Build-time compileall is the
minimal candidate; source hash/magic validation and same-size/mtime mutation
checks pass with read-only non-root runtime. No warm process pool or runtime
isolation change. Source review, runnable and make check passed; exact candidate
builds and whole-Task measurements remain pending. See deferred-config and
checked-bytecode evidence; no production or full capacity acceptance.


### Native9 improvement and static validation root cause (2026-11-03)

Native9 on the two logical nodes preserved old24 event/budget/model/receipt
hashes. New short5.56s, approved pwd16.95s and one eight-offer burst median
9.7305/max13.401s passed real exit/cleanup checks. The burst did not include
the fixed historical corpus or 256 streams. The separate Native10 diagnostic
profiled one fresh short Task per node and preserved old34 facts. Both profiles
showed53 Definition parses and2160 static descriptor builds per Task; profile
cumulative times overlap and are excluded from SLO measurement.

PG row conversion no longer parses a snapshot before the same typed field
validator. Native catalog memoization stores only one digest and 20 immutable
component identities; each public catalog and pin remains fresh. No dynamic
lease, grant, Definition, or authorization decision is cached. Same persisted
v2 row, 23 decodes in readonly native probes: CPU~0.49s to~0.086s, identical
projection bytes. Focused217 and real PG14 passed; the first PG teardown FK
failure is retained with the fixture correction. Native11 with profiling off
and whole-Task measurements are next; full E1 remains unqualified.


### Native12 bounded hint claim and remaining E1 failure (2026-11-03)

A real PG 32-row test reproduced the old hint claim holding stream rows across
per-row round trips and blocking a durable append at its unchanged timeout.
Set-based ordered claim and nonblocking busy settlement retain exact fence,
frontier and DB-clock expiry; no migration or deadline changes. Real PG/Redis15,
unit29 (2 conditional skips), independent review and make check passed.

Native12 ARM-only isolated pair is live and healthy; old78 facts unchanged.
Fresh 5Hz diagnostic stopped at16 inflight:29 admitted once,27 completed, two
safe pre-model executor suspensions, all29 exact exit ACKs.22 admissions above
2s, max6.0893s. Observed PG lock timeouts14→2 across different bounded cohorts;
remaining stream append timeouts align with the failure window but the exact
child cause is unproven. No new unknown model calls, no old replay. Original
Native11 stale-running Task confirmed stopped in1.199s via one signed control
operation; original answer/receipts preserved, separate unknown case stays
suspended. Full E1 corpus/SSE/steady/fault/soak and physical HA remain open.

### F-04 receipt durability gate design

The PostgreSQL 17.5 two-host probes showed that cancelling a SyncRep
wait can return a successful command tag and a warning while only the
primary exposes the receipt. A receipt proof must compare the exact
record on the designated synchronous replay target. Compare the
namespace, action, scoped key, request hash, status, and immutable
response body. Keep the current grant and binding checks ahead of
any client-visible result.

Apply the same gate at three boundaries. The submit response must
withhold the sealed result until the replica confirms it. Original
observation must withhold the result and its recorded flag under the
same conditions. Termination must apply the equivalent check to its
durable stop proof before exposing non-commit proof. An unavailable,
lagged, mismatched or promoted verification endpoint leaves the
operation unresolved. A failed check grants no authority to replay.

The proof connection needs its own declared finite standby budget and
the remaining request deadline. Compose an explicitly configured
verification endpoint with TLS identity, database system identity and
expected recovery role. Promotion requires fencing and a trusted
topology change that rebinds the proof target. Keep admission closed
until that change and synchronous membership are verified. A database
system identifier is shared by physical replicas, so it only proves
cluster membership. The endpoint identity and leader timeline must
come from the fenced topology.

For E1, set `ZEBRA_HA_E1_RECEIPT_PROOF_SYSTEM_ID` and
`ZEBRA_HA_E1_RECEIPT_PROOF_TIMELINE` alongside the single TLS proof DSN.
Take the timeline from the fenced writer topology. The dedicated standby
function requires an active WAL receiver on that timeline before comparing
the exact row. It withholds the proof while the receiver is disconnected or
switching timelines. The login role retains only function execution access.
Provision the updated eight-argument fixture on the isolated writer before
enabling its API configuration, then check the designated standby has replayed it.

Acceptance requires the signed HTTP POST, original GET and
termination cases during paused replay, then exact readback after
replay. Repeat after a fenced promotion, with the previous proof
endpoint still reachable, and measure connection counts and request
deadlines under mixed load. Current one-shot probes support the
primitive only. Runtime composition and production activation remain
pending.

The optional `databaseBudget.executor_limits` mapping declares all five
private-executor limits (`pool`, `normal`, `read`, `control`, `probe`).
Omitting it charges and enforces the shared limits for executors as before.
Helm and runtime charge the override for every peak executor, including rollout
overlap, and still reserve server and external connections separately.
