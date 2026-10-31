# CA-HA-02 当前实现

- 从e8a4f10b独立分支，摘取UX文档01530810为559422d7；Ready/Owned paths先登记。
- 新精确GET与原lifespan组合、有界epoch观测；保留原健康/鉴权/关闭行为。
- Worker健康只读采样、能力到期约束、默认关闭本机原子文件，不改原任务执行。
- 定向pytest、局部Ruff/mypy/边界与尺寸；不运行完整门禁/Docker/故障负载。
- 02候选Review；真实PG/完整门禁未验，03–10仍Locked，无部署/生产迁移。

# CA-HA-UX-00 用户体验性能文档补充

- 从cloud-agent e8a4f10b建独立分支/worktree，登记Ready后领取。
- 补正式方案、合同revision3和机器可读UX-01–10，明确计时/分母/负载/证明边界。
- 原任务03/04/07/08/09/10补验收；不另建执行队列/业务租户/权威状态机。
- 仅diff/JSON/链接/文档尺寸/任务指标一致性验证；不得启动代码/重型测试/Docker。
- 文档完成后Review，02–10仍Locked；未验证目标不作为生产性能承诺。

# CA-HA-01复核与集成 / CA-HA-02前置

1. Fetch核对cloud-agent d782039c与01输入7e692719，保留原工作树。
2. 单人静态复核9项修正，合同revision2；不冒称独立审查/实现/故障验收。
3. 文档/JSON/路径/尺寸/锁定状态检查后合入cloud-agent并推送。
4.02技术依赖随01合入满足，但当前不授权业务实现，继续Locked。
5.03共享Worker路径须先合02；无Docker/重型测试/生产部署迁移。

# CA-HA-01 当前文档任务

- 00已单独摘取d7aabfaa并修正d782039c，GitHub cloud-agent已推送，本地主线已同步。
- 01从d782039c独立分支/worktree，Ready后领取；不包含强停候选97463d00a。
- 固定9条DDD不变量、SLO口径、E1包络、F1单故障矩阵、开关和逐卡范围。
- 只做JSON/链接/真实路径/尺寸/差异检查，未运行make test/check、Docker或重型环境。
- 01设计Review，独立评审待安排；02–10仍Locked，不能自动实施/恢复暂停任务。

# CA-HA-00 当前文档任务

1. 在97463d00a独立分支/worktree登记任务，保留原树无关修改。
2. 正式方案：DDD、复用/缺口、候选目标、兼容和安全证明边界。
3. 正式任务：CA-HA-01–10依赖/路径/验收，保持Locked；更新索引/阶段入口。
4. 仅检查diff、Markdown本地链接、范围和新文档尺寸；不运行重型测试或Docker。
5. 文档Review不等于实现或生产HA完成；后续须重新授权并领取Ready卡。

## Active: CA-P5-INTEGRATE

- [x] Audit both actual mainlines, dirty trees, refs and verified P5 evidence.
- [x] Preserve unpublished97463d00 and original branch-tip manifests.
- [x] Fast-forward/push Overdoze main908160e and clean only merged refs.
- [x] Resolve Native merge preserving both lines and exact legacy migration identity.
- [x] Real PG compatibility/Bundle/Coverage70 and focused18 pass; first interrupted suite is not acceptance.
- [x] Final Native11618/3155/15; all15 reproduced on clean remote. PG70, mypy1492/Eval30 and Go full gates pass; static inherited errors recorded without bypass.
- [x] Published source integration afb61121; remote/ancestry verified;36 local/10 remote refs removed.
- [x] Final audit passed;39 dirty occupied heads, original receipts/data and local97463d00 preserved; temporary PG resources/producers cleared. Governance-only delivery receipt follows source merge; no deployment/migration.

# CA-P5-08 — P5 工程退出验证通过（Review）

固定生产者9e91d75f，源码与完整门禁哈希不变。消费者V31在同一环境完成实际
SDK/Worker Alpha/Beta/回退、负向门禁/原GET、三处重启和三Task原历史保留。
Native make test11240/3080条件跳过、make check1448/Eval30，隔离PG8+7通过。
无原业务重发/Controller重领；保留mock/数据/原收据/Coverage/unknown。
临时运行资源已清理、数据保留；无主线合并、生产部署/迁移。
[复核](docs/CA-P5-08_exit_verification.md) · [证据](docs/evidence/ca-p5-08/acceptance.json)。

# CA-P5-10 — Admitted STOP uses durable identity

Claimed before code; original optional expiry STOP fails on published ce6 baseline, not caused by09. Reuse canonical admitted fingerprint and latest durable binding/exact workspace for trusted direct cancellation; current Host API/expiry and execution permissions unchanged. Canonical admitted-event proof retains identity/context validation. Final47 focused, full make test11240 passed/3080 conditional skips, make check1448 sources/Eval30 passed; explicit owned PG legacy8/resource7 passed. Fixed-source image consumer S1 pending. Preserve data/history/Coverage and no unknown HTTP/RUN replay or Controller reclaim. [Boundary](docs/CA-P5-10_admitted_stop_identity.md).

# CA-P5-09 — Legacy READY original frontier

Claimed before implementation. V21 real image/PG incompatibility refusal exposed original RUN hidden after recovery projected its accepted event. Shared scoped read-only last-READY-frontier predicate fixes discovery and next-command read; no new events/HTTP/RUN/Controller, no projection rewind or schema/public contract change. Real PG red4/green6 plus rejection/Worker/close-healing/consumer suite33 passed; full gates and new fixed-image S1 pending. Preserve originals/data/Coverage and single-environment cleanup. [Contract and limits](docs/CA-P5-09_legacy_ready_recovery.md).

# CA-P5-07

1. [x] Trace actual original stop/Worker PID1 fallback and register ownership.
2. [x] Real CLI red signal regression, minimal scoped stdlib stop request and pickup boundaries.
3. [x] Full Native make test11231/3080 skips and make check passed; complete event/resource reconciliation; producer source delivery.
4. [x] Handoff source prerequisite to OD-P5-07C-R; image rebuild/actual S1 is consumer-owned, not a producer completion claim.

# CA-OPS-02 current task

- Claimed Ready from published CA-P5-06 6dee587a; exact six teardown flags only.
- Reuse previous cleanup regression: red6 failures; live21 pass.
- Native full make test11225/3080 conditional skips and make check passed; final resource identities match baseline.
- Retain old23 uncertain volumes; no global prune or business data mutation.
- Publish verified fixture source, then unlock OD-P5-07C-R actual single-environment S1.

# CA-P5-06 current task

- Review: authorized approval binding renewal; original GET stays read-only.
- Native full make test11216/3068 conditional skips and make check passed.
- Overdoze30 race packages/selfcheck and make check passed, serial and bounded.
- Container/network inventory unchanged;23 new anonymous volumes require ownership proof before cleanup. No owned test services running.
- Commit/push scoped Native source, then pin for actual single-environment S1.
- P5/S1 not closed; preserve BFF credentials, unknown/no replay, history/receipts/Coverage.
- No production operations or main merge.

# CA-P5-04 current task

- Claimed Ready before code from publishede2462c66 on codex/ca-p5-04-cloud-script-eval.
- Fix cloud Eval missing instance lifecycle and shared quota-backed script workspace; reuse
  existing Eval original/current approval and OCI protocol. Separate retained resources,
  closed admission and unresolved hold make unsafe lifecycle source unavailable.
-34 focused checks and full make test11209/3067 skips plus make check passed.
- Evidence/tasks updated; commit/push next, then rebuild actual S1 images
  from the published source and continue Overdoze07C. Do not end at this prerequisite.
- Preserve history/data/originals/Coverage; no production migration/deployment/main merge.

CA-P5-09 optional real-PG legacy suite:7 passed/1 expired admitted STOP failed; exact published ce6 reader reproduces same failure. Diagnostic reason Host Grant expired. Separate CA-P5-10 dependency must repair durable cancellation identity path before combined final gates; no known failure is waived. Disposable PG removed.

CA-P5-10 final design revision: initial full5 identity/context propagation failures were not waived. Retain original delegation and full context; store revalidates exact canonical admitted STOP/CANCEL event and operation, uses immutable admission time only, current default expiry remains strict.47 focused including old five and real-PG forged-event/operation negatives pass. Full source frozen for renewed gates; no publish or new S1 yet.

CA-P5-09/10 combined final producer gates: make test11240 passed/3080 conditional skips, make check0 file-size violations/ruff/mypy1448/Eval30 passed; source hashes unchanged. Legacy real PG8 and original resource binding7 passed in exact-owned temporary PG (historical fixture replaced for isolation only; assertions unchanged). All owned temporary PG/anonymous volumes removed, no new volumes/networks;4 foreign-owner containers preserved. Source publication required before fresh consumer images; P5 not yet closed.

CA-P5-08 verification resumed on9e91d75f after both producer gates passed and GitHub HTTPS remote verified. No code changes; consumer V22 uses new exact-source images in one environment. After cleanup compare frozen blobs and reuse current-turn full result if unchanged. Prior unknowns/data preserved; final S1 still pending.
