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
