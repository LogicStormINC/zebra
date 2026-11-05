# Live checkpoint — frozen9b4f9ad3 / Native7

Two local arm64 logical nodes now run2API/2Worker/2cleanup on profile247; both
healthy/restored. Exact two-arch images/index/source proof and Native7 publication
passed. Two fresh full native pwd Tasks and two active-executor freeze STOPs are
verified with real exit pairs/resource absence; primary independent cleanup ran
while Worker frozen. OCI objects were not started tools. Original7 tasks/budgets/
unknown preserved. Shared physical Mac, WAN apps held, production untouched.
Next: E1 deterministic short-task/corpus/load harness, measured stages and fault/
soak gates; keep03 In Progress and04 locked. Do not replay any existing task.

# Current checkpoint — 2026-11-03

CA-HA-03 stays In Progress on the claimed worktree/branch. Monitor capacity2079
and dual-engine routing source regression are verified (native PG46, make check,
independent review). Primary still runs engine637; Broker/Authority9a; Ubuntu WAN
API/Worker held. Fresh OrbStack node2 calibration/source and both local247 static
preflights pass; no node2 app has started. Source must be frozen and rebuilt into
exact arch images/common index, then new native approval/publication and cold
matching-profile apps/cleanup on both local nodes. Preserve original tasks,
unknown receipts and f69 reconciliation. Full E1 load/fault/soak not_run,04locked,
no physical/storage HA or production rollout claimed.

# CA-HA-03 — E1 provisioning and integration

Owner Luke Ding / Codex; same task/branch/worktree. Source parent9e3cef3b.

1. Independent03A/03B review and fixes: done,9e3cef3b local commit.
2. User-authorized fresh bounded two-host staging: provisioned; no production replacement.
3. New DB121, NOSUPERUSER, empty cutover, versioned objects, Rabbit principals: verified.
4. Native model wire fixture, real authority fixture, exact volumes/endpoints/CA/peer guards: verified.
5. Migration and maintenance integration fixes: focused9green, PG12green+1 inherited fixture failure,
   independent AI review complete; commit source then build exact image delta.
6. Promote delta only into exact owned idle staging apps; verify source, budgets, health and one
   synthetic Task without retrying unknown outcomes. Promotion/source/fresh health verified;
   one Task admitted201 and reached gVisor, then failed closed before model transport because
   native CLI has no trusted exact-request counter. Original failed Task retained, no replay.
7. FullE1 baseline/load/fault matrix remains not_run;03notDone and04locked.

Do not change existing production, restore old workloads, use real provider keys or replay business Runs.

8. Next implementation slice: explicitly compose a trusted request counter through existing
   ModelRequestBudgetFactory; prove its wire/output bounds before another NEW synthetic Task.
   Do not replace it with a heuristic or weaken native budget/capability guards.

Receipts: docs/evidence/ca-ha-03-e1/validation.json. Current environment uses restart=no,
Mac-owned SSH forwards and a single VM control/data plane; not storage/host-failure HA.

9. Budget composition source candidate completed: optional Cloud bundle counter propagation,
   cancellable Cloud roots; actual synthetic model byte meter and cap/body checks verified.
   Broad run3054 pass/856 skip/one obsolete lifecycle assertion; test-only fix followed by
   47 pass/2 skip and final make check. No source image promotion or Task replay.
10. Next exact files/actions: add operator composition under tests/compose/cloud_ha_e1/ using
    compose_cloud_worker+dataclasses.replace(model_request_budget_factory=...), retaining TLS
    peer/CA/namespace guards. Select model invocation max_output_tokens through an existing
    frozen RuntimeAssembly/bundle (not a counter-side wire rewrite). Register only synthetic
    test definitions through existing validated operator services. Update exact image delta
    COPY and source pins, cold promote idle owned staging only, then POST a NEW Task once.
    Full E1 and production HA remain unverified; keep03 In Progress and04 Locked.

11. Operator source prepared: main factory is invoked within its live pool; E1 parent and
    isolated child share strict counter selection.41 targeted tests, offline real Bundle
    counter and actual model meter checks pass. Full make check passed.
12. Before new apps: freeze reviewed source; native delta builds; start only registry after
    registry-only preflight; publish/verify a real multi-arch image manifest; generate actual
    private catalog/publication with that digest and source receipts; UID65532 mode0600;
    publication token operator-only; verify both effective baselines. Then full preflight and
    idle owned cold promotion. Never run the original failed Task again.

13. E8 live assembly done: immutable multi-arch manifest abfd6add..., matched runtime
    source2139/3 and both baselines; new owned API/Worker healthy; actual management
    materialize/publish passed. Native strict credential/ref/template fixes now in generator.
14. Guarded smoke39d0... admitted once and reached gVisor/isolated model boundary with
    output cap1024, but shared recursive guard TypeError on real present schema.type dict;
    no reservations/tools. Preserve failed Task. One-line tuple fix red3/green35+5skip,
    AI review19passed. Next build this exact new source, real new image index, generate
    a NEW approval with --trust-revision4 (current exact trust3), exact scoped native
    CAS3->4, materialize/publish new Definition and NEW Task. No retries of old Tasks.
    Full E1/HA03/production HA still incomplete.

## E1-A capacity handoff, 2026-11-05

The follow-up is authorized for the paired native reads, deterministic regressions
and new synthetic E1-A tasks against an adjacent original baseline.

- [x] Verify the clean ca-ha-03-budgets checkout and the final transaction-map artifact.
- [x] Confirm the single synthetic Task has 222 transactions, 77 lease reads and
  49 deadline checks. These counts describe this sampled Task.
- [x] Trace child require_owned -> LeaseStore.get -> native lease/epoch/STOP read.
- [x] Trace BudgetExecutionCheck -> original callback -> check_deadline.
- [x] Compare installed and checkout budget code. Installed v126 uses two deadline
  queries in one transaction; the checkout combines them into one statement.
- [x] Review all callback routes and identify pure reads that can share an existing
  work unit without extending a transaction across writes, model I/O or effects.
- [x] Reproduce the chosen transaction count reduction with a deterministic check
  and validate lease expiry, STOP, deadline, scope and rollback behavior.
- [x] Compare fresh same-seed candidate and adjacent original baseline at 4+4 slots,
  5 Tasks/s and 256 SSE. Include all receipts, rejections and unknown outcomes.
- [ ] After E1-A passes, run sustained load and cross-scope fairness, then finish
  the remaining E1-R matrix while keeping the prior F-02 state separate.

Evidence is .artifacts/cloud-ha-e1/e1-a-v126-transaction-map-1793856413/transaction-map.json.
Installed sources are session_process_child.py.installed and overlay/worker_budget.py
in that directory. E1-A and the full HA objective remain incomplete.


Paired-read result is local commit ac349add, with 59 focused regressions passing.
Candidate commits per completed Task 173 versus 222 for the adjacent original.
Mean whole-slot 8.261 versus 9.623 seconds; queue p95/p99 32.016/36.200 versus
43.858/43.933 seconds. Candidate receipts 40 completed, 34 scope 429 and one
unknown; control 36 completed, 38 scope 429 and one unknown. Both unknowns remain
after one further original signed GET. All 75 offers are retained per arm.
Evidence is .artifacts/cloud-ha-e1/e1-a-v126-ownership-unit-1793857758/adjacent-comparison.json.
E1-A still fails. Sustained/fairness and full E1-R remain outstanding.


## ac349add follow-up, 2026-11-05

- [x] Re-profile a fresh synthetic Task at the installed ac349add candidate baseline.
  Its 173 commits include 50 work units, 28 unpaired lease reads, 18 progress
  transactions and 13 latest Run header reads; 12 headers follow catch_up checks.
- [x] Share only the configured native ownership/deadline check and latest Run
  header in one read-only transaction, closing it before any page advance.
- [x] Add native same-scope/custom fallback, Run supersession, write refusal and
  independent page-write regressions. 58 focused tests passed, Ruff/mypy clean.
- [x] Run fresh same-seed candidate and adjacent ac349add control, preserving every
  receipt and every occupied attempt, including the control's two suspensions.
- [ ] E1-A capacity and queue targets remain unmet; sustained/fairness and full E1-R
  are still outstanding.

Local implementation eb0721a9. Completed Task commits 173 to 161.
All-admitted complete slot mean 7.8292 to 7.7545 seconds, an observed 0.95% change
in one pair with different failure outcomes. No significant capacity gain claimed.
Evidence .artifacts/cloud-ha-e1/e1-a-ac349add-checked-header-1793859685/adjacent-comparison.json.

## Installed recorder follow-up, 2026-11-05

- [x] Confirm installed execution_events.py differs from checkout only in the
  already-fixed duplicate pre-tail ownership check (b8e0559c).
- [x] Extend native regression for revocation after tail read and before append.
- [x] Apply only the existing module guard in a fresh isolated E1 candidate,
  compare with adjacent ac349add baseline, retain all occupancy/receipt evidence.
- [x] Restore exact original roles, bindings and stopped retained clones.

Existing b8e0559c guard reused; regression bfd04c5d (11 native passes, Ruff
clean; first timing failure retained). Candidate 173->163 commits, complete
slot mean 8.457625->8.288500 seconds, worse p95/p99. Both arms 40 completed,
35 sealed scope 429, zero unknown, 40 exact ACKs and 256 SSE/zero early closes.
E1-A remains FAIL; no material gain or production-readiness claim. Evidence:
.artifacts/cloud-ha-e1/e1-a-ac349add-recorder-dedup-1793861657/RESULTS.md.

## SQL wait attribution, 2026-11-05

- [x] Capture per-SQL client wall/CPU/runnable wait and native server execution
  deltas at low load and full E1-A load, retaining exact signed cohort outcomes.
- [x] Separate slow SQL/server saturation from reset/acquire/transport waits and
  choose the next change from the largest measured whole-slot contributor.
- [x] Restore roles and approvals (two Worker IDs explicitly replaced with pinned baselines), keep stopped cloned data/evidence.

SQL attribution identified repeated empty Memory discovery (6,786 historical
closed Sessions per empty scan), not a stable query-rewrite win. Next slice:
- [x] Reuse PollingDelay for capped cloud Memory idle/error discovery, reset on
  progress; leave local/command cadence and durable receipts intact.
- [x] Deterministic backoff/cap/reset/error checks, then adjacent fixed E1-A.

Memory backoff local implementation d9ab05a0: 18 deterministic tests, Ruff/mypy
pass. SQL attribution isolated 601 Memory scans/38.536s; no SQL rewrite retained.
Adjacent control / first candidate / natural-drain candidate full-slot means
9.001900 / 7.148550 / 7.926775s; queue p95/p99 latest 30.675555/34.162657s.
All 40 attempts counted per arm. All arms 40 sealed 201, 35 scope 429, zero
unknown, 40 model starts/exact ACKs. Control has one retained storage-contention
suspension; both candidates complete 40/40. Latest candidate naturally settles
40/40 Memory receipts in 21.932s after main drain. Earlier candidate has 16
unsettled Memory receipts retained in stopped data, not replayed or relabeled.

Two original E1 Workers failed restore due mutable source/old helper skew; fixed
by pinning 17 modules per node to immutable baseline bytes and recreating only
the two stateless Workers. Old containers stopped/restart=no, configs retained;
four other IDs unchanged, all approvals unchanged. Latest current role list is
.artifacts/cloud-ha-e1/e1-a-memory-backoff-drain-1793865198/expected-roles.tsv.
Both active pinned Worker hashes verified, six roles running, original APIs ready.
Four new DB copies stopped/data retained, eight owned workspace tmpfs volumes
precisely removed. Production untouched. E1-A still fails 1.6s/2s/5s gates; do
not advance to sustained/fairness or expanded E1-R as a substitute for capacity.
Evidence .artifacts/cloud-ha-e1/e1-a-memory-backoff-drain-1793865198/RESULTS.md.

## Preparation/transport attribution, 2026-11-05

- [x] Read all40 retained preparation marks: inputs812.9ms, context authority
  append227.1ms + refresh235.8ms, selection append170.4ms + refresh219.6ms.
- [ ] Compare read-only SQL/short-transaction client latency from both Worker
  nodes through the configured test path and retained Mac-clone path.
- [ ] Select the next whole-slot change from this evidence, preserving existing
  source pinning, data, receipts and production boundary.

Transport result: direct clone IP and Mac-proxy short Task-I/O transactions
were comparable on both nodes; no topology rewrite selected. A constant-read
probe initially failed closed without process capacity composition, then used
standard executor postgres_pool_scope. No Task data/model/intent mutation.

Next coherent E1 composition reuses six existing bounded-read modules rather
than new caching/transactions: input frontier+membership, native deadline query
and helper, checked latest Run header + Worker recovery wiring. Existing native
regressions precede adjacent fixed E1-A. No schema or production changes.

## 用户冻结的新推进边界，2026-11-05

持续5/s、正常负载零容量拒绝；30s预热+60s稳态，queue p95<=2/p99<=5。
所有429/超时/unknown/未发出均保留。见docs/CA-HA-03_capacity_decision.md。
停止无量化跨缺口预期的局部优化；旧在途只读尾部对照已收尾，控制失败/
缺失SSE和采样如实留档，六角色恢复、clone停止，未重放。

下一步只执行一轮同期诊断，产出接纳→槽→业务→ACK→释放时间账单，
最多两个主瓶颈；再选择一个有量化预期的主方案、一次容量复验。
必须交付达标配置或具体原因/资源缺口，不以继续微调作为结果。
正式诊断前先验证时钟闭合、采样完整性和纯观察开销；不追加业务优化。

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

资源候选补核查完成：两原Worker纯配置入口接受16槽/batch16/306连接，256旧PG拒绝，
384元数据通过；未连接DB/Task/模型。热点定位走已有索引，不新增索引。
六原角色/两ready/原4+4槽/clone停止再次核验。32CPU/64GiB只是候选预留，
不得当作最低需求或采购结论。仍缺隔离扩展实测，不宣称容量或HA完成。

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
