# CA-P3-02L — 认证回调与 Runtime 生命周期（Review）

[正式方案与交互](docs/CA-P3-02L_auth_lifecycle.md)。复用K，增加本地epoch/取消围栏与显式启停，凭据留在BFF，unknown不自动重试。
make test10971通过/3022条件跳过（1201.65s）、make check、SDK151及实际平台/独立业务PG/原生HTTP双浏览器通过；Go24个race包通过，4610旧文件保持。 [证据](docs/evidence/ca-p3-02l/validation.json)。生产IdP/签名云准入仍独立。
无Python/schema/旧合同/历史/Coverage变更，不部署/生产迁移/npm发布。

# CA-P3-02K — 同源业务认证 SDK（Review）

依赖J与G-A/G-B，新增无凭据认证状态/显式刷新退出/原操作marker及只读恢复。
过期Access保留业务授权CAS元数据但阻止bootstrap。Python/schema/历史/Coverage保持。
[正式合同和交互](docs/CA-P3-02K_bff_auth.md)。make test 10971通过/3022条件跳过（1244.42s），make check/SDK145及实际平台HTTP+独立业务PG双浏览器通过，4601旧文件保持。 [证据](docs/evidence/ca-p3-02k/validation.json)。不部署/生产迁移/npm发布/主线整合。

# CA-P3-02J — 跨设备待对账与人工处置（Review）

复用H收据/I原映射，新增可选资源收件箱SDK；unknown无自动重发/清除，人工处置独立CAS审计。原生生产Python/schema/历史/Coverage不变。
[方案与交互](docs/CA-P3-02J_request_discovery.md)；make test 10971通过/3022条件跳过（1220.28s），make check通过（1393类型文件/30eval）；SDK139、React18/19与双浏览器矩阵、新跨设备及旧恢复联合验收通过；3768保护文件未变。 [证据](docs/evidence/ca-p3-02j/validation.json)。无部署/生产迁移/npm发布/主线整合。

# CA-P3-02I（Review）

已核对 H 公开收据和 G SDK；显式恢复1、原请求标识持久化和只读对账已实现；业务BFF事实在自有DB，不接mock。补可选原Segment前置条件，保留原Runtime/原生key，未知不重发。

最终make test 10971通过/3022条件跳过（1230.21s），make check通过（1393类型文件、30eval）；SDK verify136及双浏览器/双Go进程/重启/原生收据联合验收通过，3757保护文件不变。[正式方案](docs/CA-P3-02I_command_recovery.md) · [证据](docs/evidence/ca-p3-02i/validation.json)。原生schema/历史/Worker/Coverage不变；生产IdP/完整模型/HA、跨设备发现及非提交证明仍后续。不部署/生产迁移/npm发布/主线整合。按授权限定提交推送，实际SHA另核验。

# CA-P3-02H — 命令接纳收据只读对账前置（Review）

G之后先补P3 unknown的原生可授权、定点只读观察；使用原Segment/幂等键与现有索引，不创建状态表或放开重发。SDK/BFF持久恢复后续独立消费。

最终 make test 10970通过/3022条件跳过（1171.24s），make check通过（1393类型文件、30eval）；定向22通过/1可选PG跳过，独享PG17另跑5通过。3838个既有代码/SDK/合同/证据/Coverage保护文件未变。[正式方案](docs/CA-P3-02H_command_receipts.md) · [证据](docs/evidence/ca-p3-02h/validation.json)。整次PG读取共享两秒预算；首次全量轮次因补齐该预算而中止，最终完整重跑单独计入。按授权限定提交推送，远端SHA由交付回执核验；无部署、生产迁移或主线整合。

# CA-P3-02G — SDK/BFF Readable值提交（Review）

基于已发布fb72ef6f的原生准入合同，复用挂载调度和持久命令，显式协商值提交；不新增Go执行代理、原生表或自动重试，旧模式/历史/Coverage保留。

最终make test10949通过/3021条件跳过（1244.07s），make check通过；SDK verify131、双浏览器各3值命令及原有2动作/收据/恢复链通过。2318生产/旧合同/Coverage保护文件与94 SDK/验收输入保持。见[正式方案](docs/CA-P3-02G_readable_submit.md)和[证据](docs/evidence/ca-p3-02g/validation.json)。环境中断运行排除，最终完整门禁重跑；按授权限定提交推送，实际远端SHA以交付回执核验。

# CA-P3-02F — Readable原生准入（Review）

已核对E后AG-UI现有state/持久命令/Context路径，先补当前Session/挂载绑定与脱敏恢复，不创建新上传接口或Go执行代理。SDK值提交另片；保留旧模式/历史/Coverage，不部署迁移。

最终 make test10949通过/3021条件跳过（1199.57s），make check通过；定向60通过/1条件跳过，独享PG另跑4通过/零跳过。936个保护文件未变。见[正式方案](docs/CA-P3-02F_readable_admission.md)与[证据](docs/evidence/ca-p3-02f/validation.json)。按授权限定提交推送，远端SHA由交付回执核验。

# CA-P3-02E — SDK挂载同步（Review）

2026-10-22；先核对D公开metadata，认领SDK实际应用与原生浏览器联调。
显式协商、旧动作/收据排空、严格公共事实应用；真实本地HTTP/PG与Worker客户端通道，生产IdP/HA另验。
前端mock/历史/Coverage保持；无部署/迁移/主线整合。

最终make test10914passed/3020条件跳过（1309.26s），make check通过；SDK verify125项、包审计、React18/19消费和双浏览器/Next hydration通过。
实际HTTP/PG/Worker gateway双浏览器各2动作/2回执/2恢复命令，回执replay/新binding/秘密隔离/撤销拒绝通过。
3,042既有Python/合同/证据/Coverage文件未变。见[正式方案](docs/CA-P3-02E_sdk_surface_sync.md)与[证据](docs/evidence/ca-p3-02e/validation.json)。
按授权限定提交推送；生产Go Broker/IdP/共享CAS和完整Worker harness仍独立验收。

# CA-P3-02D — 原生挂载摘要与绑定同步（Review）

2026-10-22；基于已发布a1635a9c，先补公开action摘要与实际重挂载绑定前置。
同名action的UI revision变化应同步新的mounted snapshot，持久层须在短Session锁内复核收窄。
最终make test10914passed/3020条件跳过（1135.58秒），make check通过（mypy1388/eval30）。
API56passed/1条件、独享PG62passed/零跳过；3669源码和414旧SDK/合同/Coverage文件无漂移，其中280Coverage保持。
[正式方案](docs/CA-P3-02D_surface_metadata.md) · [证据](docs/evidence/ca-p3-02d/validation.json)。
前轮漏更新旧能力列表严格断言已修正，最终完整复验另记，不把失败/中断轮次计为通过。
按授权准备限定提交推送，远端SHA由交付回执核验；管理前端mock/历史/Coverage保持。
实际SDK/BFF应用同步结果及成对浏览器联调仍后续；无部署/迁移/主线整合。

# CA-P3-02C — 显式BFF浏览器SDK（Review）

2026-10-22；基于已发布0aa6e558；管理前端mock保持，未整合主线/部署/迁移。
SDK新增mode=bff，浏览器只有公共绑定事实，原生HostGrant/Session credential/fence由业务BFF持有；
同源相对路径/方法/头/JSON大小/5秒期限限制、真实connecting/ready/unavailable/stopped订阅，
旧DI必填secret类型和legacy配置/SSE保持；修复Provider配置更换后旧runtime继续轮询。
Observer只续Session不误申领Controller；当前控制权/Task/Effect/Receipt权威仍在原生，Go无执行代理。
[方案与边界](docs/CA-P3-02C_bff_browser.md) · [制品](docs/contracts/bff-browser-sdk/contract.json)。
最终SDK verify117passed/零跳过，包/React18-19消费/Chromium-WebKit/Next hydration通过；
根make test10906passed/3014条件跳过（1181.02秒），make check通过（mypy1388/eval30）。
2941Python/合同输入、76已验证SDK源码和280Coverage文件无漂移；[证据](docs/evidence/ca-p3-02c/validation.json)。
实际Hook/DOM/wire BFF对验与真实IdP/Runtime/Worker联调分别记录，限定提交推送，远端SHA由回执核验。
下一步需原生公开action摘要、mount/绑定/围栏生命周期和真实BFF持久映射，Readable值仍独立合同。

# CA-P3-02B — UI Effect当前资源授权（Review）

2026-10-22；从已发布8715d225独立继续，先核对实际SDK/BFF/Effect依赖。
Effect列表/详情/回执统一复用当前Task/Run、线程、主体、issuer/namespace/scope检查；
本地兼容、原生Controller fence/expiry/revision/收据幂等与原子恢复命令保持，无迁移。
[正式方案](docs/CA-P3-02B_effect_authority.md) · [语义制品](docs/contracts/client-effect-authority/contract.json)。
原生专项32项和真实独享PG18项通过/零跳过；最终make test10906passed/3014条件跳过，make check通过。
3435输入和280Coverage源码/测试零漂移；[证据](docs/evidence/ca-p3-02b/validation.json)区分条件跳过与实际PG。
按授权提交推送独立分支，实际远端SHA由交付回执核验。
下一SDK片必须先明确BFF浏览器传输和Readable值合同及错误ready，管理前端mock保持；
不把本前置称为浏览器UI/Worker已消费收据或完整P3/生产HA验收。无部署、生产迁移或主线整合。

# CA-P3-02A — 产品范围Profile与可信BFF准入

2026-10-22；Owner Luke Ding；基于已发布f154f5d1继续，未整合cloud-agent/main。
新增frontend-profile-management/1：复用原有批准/CAS和Profile服务，产品/环境/Host/App精确版本授权、
原生不可变归属、发布/绑定/撤销及当前查询，v112加法收据/审计事务；不下发万能operator Token。
修复实际公开装配发现的显式Postgres stores命名空间读取；cloud ClientSession要求已验签sub匹配user_ref，
原始bind检查Task/Run/当前Profile，Controller续期/释放检查当前资源；本地/历史/deprecated已有Run兼容保留。
最终make test10874passed/3008既有依赖跳过（1090.05秒）和make check通过（mypy1388/eval30）。
专项77passed/2条件跳过，独享PG45passed/零跳过补齐持久化/围栏；3074输入和280Coverage文件保持。
[evidence](docs/evidence/ca-p3-02a/validation.json)保留中断/旧夹具失败及最终通过记录。
修复显式stores factory和旧夹具，补历史共享App保护：旧operator绑定与产品撤销共享App锁，
存在其它Host/namespace引用则拒绝新的范围写入；不删除旧绑定/能力，历史收据仍可只读对账。
[正式方案与合同](docs/CA-P3-02A_frontend_admission.md)明确一次性credential丢失/部分提交、当前观察和后续UI/HA边界。
Overdoze使用公开HTTPS与generic Broker串联真实Task/Session/mount/Controller；Go不访问原生数据库。
前端mock、历史数据/Coverage均保持；无部署、生产迁移或主线整合。

## Historical progress (preserved)

# CA-P3-01C — 原生公开脚本包校验前置（Review）

2026-10-21；基于已发布B60893da8独立分支继续，先核对下一OD-P3-02A的消费依赖。
新增script-validation/1独立scope/凭据合同，只调用既有ABI解析/摘要/源码语法；不执行/批准/发布代码。
旧A/B/P2制品、基线HMAC和历史/Coverage权威保持；共享有界transport保留旧Bundle接口语义。
专项50项通过（零跳过），实际独立socket和批准轮换/最终复核/取消/超时/背压已覆盖。
新增PG专项暴露4处旧夹具失败并在B原样复现；只修正实际Verified reader观察点及独享schema损坏注入，生产保护不改。
首次全量为此主动中断，旧日志保持。2026-10-22最终make test10856passed/3008既有环境依赖跳过（1109.12秒）和make check通过（mypy1385/eval30）。
独享PG保持专项106项全过/零跳过；3613受检输入零漂移。[最终证据](docs/evidence/ca-p3-01c/validation.json)区分失败/中断和最终通过轮次。
完成正式文档与任务，按授权准备提交推送；远端SHA由交付回执核对。
[正式合同](docs/SCRIPT_VALIDATION.md)说明下一平台资产业务和仍缺的脚本Bundle scoped发布扩展。
前端继续mock；无main/cloud-agent整合、部署或生产迁移。

## Historical progress (preserved)

# 2026-10-21 — CA-P3-01B Worker 原生脚本绑定与恢复

状态 Review：实现、专项64passed/零跳过与独享临时PG保持74passed/零跳过已完成。
[正式设计与配置/恢复边界](docs/NATIVE_SCRIPT_WORKER.md)；[机器合同](docs/contracts/native-script-worker-v1/README.md)。
显式 ScriptBundle/Assembly 与 Definition3/Snapshot3，保留 A/P2 旧制品与 v1/v2 摘要。
Worker Tool/Context/Verifier 接入既有模型/Policy/Context 路径；Verifier 在 ANSWER_COMMITTED 前约束，
不改写已提交结果，不生成 Coverage/verification freshness。受租约保护的原事件流保存 started/completed，
终态恢复先重新授权并重放，纯读未决仅新 fence 有界重算；私有 stdin、执行中 STOP/Host/lease 取消。
实际 Host 当前授权与最后答案/收据在短事务串行化；脚本执行不持 DB 锁。
最终 make check 通过（mypy1381、eval30/30）；make test10822passed/3008既有依赖跳过，1100.23秒、exit0。
冻结2899项源码/合同，全量期间零漂移；旧入口回归124pass，策略构造替换入口修正后13pass。
验证记录 docs/evidence/ca-p3-01b/validation.json；按授权提交/推送，远端SHA由最终回执核对。
前端 mock、历史数据和 Coverage 机制保持；此分支不整合主线、不部署或执行生产迁移。
可信资产管理/Go 公共脚本合同与生产 gVisor/HA 验收仍为后续任务。

以下为历史记录。

# 2026-10-21 — CA-P3-01A 原生脚本执行前置

P2D公开发布/消费与成对OD-P2C已交付；按当前继续指令开始P3第一片。
生产者固定只读script ABI、严格输入输出/摘要、基于既有RuntimePort的受限一次执行，
并修复POSIX共享输出管道deadline。DDD领域值与Runtime I/O分离，不引入新存储/依赖。
当前实现和未接入范围见[正式合同](docs/NATIVE_SCRIPT_ABI.md)。
Bundle脚本准入/Worker Tool/Context/Verifier与持久收据/取消/恢复仍由CA-P3-01B承接；
可信资产最小链/前端接入在后续OD-P3。无历史/Coverage改写、部署、生产迁移或主线整合。
全量make test10756passed/3008既有外部依赖跳过，1098.60秒，exit0；make check通过（mypy1368、eval30/30）。
专项141passed/零跳过，独享临时PG保持专项74passed/零跳过；CLI纯校验与实际Seatbelt通过。
冻结2853项源码/合同，期间零漂移；证据见docs/evidence/ca-p3-01a/validation.json。
源码交付为Review，按授权提交推送；实际远端SHA在交付回执核对，旧证据保留。

以下为历史记录。

# 2026-10-21 — CA-P2-01D 公开发布与消费链路

状态：Review；最终原生make test10710passed/3008skipped，1128.38秒，exit0；make check通过，mypy1364源文件、eval30/30。
专用rtpub私有配置和当前共享审批；复用原生Draft/Version/Release服务，原生评估证据门禁，
原子CAS/收据/回滚；HTTP工厂装配Registry，独立消费Host授权与完整Bundle scope/精确引用。
普通及计划Task使用同一绑定边界；既有默认发布者允许集仍为空，不自动补权。
临时PG专项74项通过；冻结2833个Python源文件，全量门禁期间零漂移。专项21项、临时PG保持专项74项零跳过；最终证据见docs/evidence/ca-p2-01d/。
无历史改写、Coverage算法/Worker语义改变、部署、生产迁移或主线整合。

以下为历史记录。

# 2026-10-21 — CA-P2-01C scoped native Bundle validation

Dependency audit identified the missing native pure validation prerequisite for
Overdoze OD-P2-01A. This explicit stacked continuation starts at published P2B
92f494cb on codex/ca-p2-01c-bundle-validation, preserving prior worktree pins and
the original dirty cloud-agent checkout. No main/cloud-agent integration.

Added separate bundle-validation/1 contract discovery and raw Bundle validation
with explicit scoped private approvals, distinct rtbv credentials/actions and
full approval reauthorization before return. Exact native parser/asset/assembly
semantics remain authority. Receipts bind contract/input/assembly/public approval
snapshot and full scope/trust; they do not publish or prove Worker readiness.
One shared8-slot body/thread limit retains timed-out/cancelled work until the
actual thread finishes; bounded private regular file reads run off the event loop.

Published native OpenAPI/schema/catalog document and positive/negative vectors;
actual loopback subprocess HTTP checks permissions/rotation/no data writes.
Existing Bundle v1 artifacts, v1/v2 historical formats and Coverage proof rules
are unchanged. The API-only setting preserves the exact P2B baseline HMAC.
Execution catalogs now enforce documented private0400/0600 regular file mode;
operator mounts must meet that requirement before future activation.

Design/plan and implementation spec approved; focused58passed/zero skip.
Independent quality review approved; make test10705passed/3007skipped in1059.97s,
exit0; make check pass30/30eval, mypy1357sources,3308sizechecks/zero violations.
All11frozen Python files and producer artifacts unchanged through full gates. Formal contract/flow/limitations are in
docs/BUNDLE_MANAGEMENT.md; evidence under docs/evidence/ca-p2-01c/.
Next separate task is Go OD-P2-01A consuming the pinned native contract, then
paired OD-P2-01B acceptance. No native scripts, deployment or production migration.

# 2026-10-21 — CA-P2-01B Bundle binding and Worker assembly

Owner Luke Ding/Codex; branch codex/ca-p2-01b-bundle-assembly from e56f8272,
isolated managed worktree preserving original cloud-agent dirty work and P1/P2A pins.
Explicit v2 Definition/Task snapshots freeze validated Bundle + public provider
configuration. Scoped publisher grants, fresh draft validation and exact Version
Release gates remain. PostgreSQL v110 is additive sidecar storage, base+payload
atomic; v1 reads and published Bundle/v1 Definition golden bytes unchanged.

Private operator execution catalog approves scope/image/baseline/provider/text
output/evidence; HMAC pins full nonmodel Worker settings without exposing secrets.
Task-local Chat/auto/text model parameters and instructions actually reach the
provider. Incompatible workers retain READY via existing retryable setup refusal;
committed/pending-close healing precedes compatibility and capability rejection.
Workspace materialization and optional completion-title recovery now respect the
same frozen boundary. V1 Coverage/proof and all existing providers remain intact;
unsupported v2 Coverage/DeepSeek routing/Responses/structured output fail closed.
No latest Release/provider lookup on recovery; no shared settings mutation.

Focused deterministic/actual Worker mock-provider/concurrent checks and real owned
PostgreSQL migration/rollback/retry tests implemented. Independent core spec/quality
approved after fixing creation-time retry idempotency; integration review caught and
fixed preflight Coverage/workspace/title sibling paths. Final independent spec/quality review approved; focused65passed including11real
disposable PG tests, affected legacy entry regression9passed. Final r2 make test
10685passed/3007skipped in1043.90s,exit0; make check pass with30/30eval and1353
typed sources. No frozen production source drift; only an old test substitute
needed its existing nullable definition_snapshot field made explicit. V2 refuses
unversioned local Skill roots/MCP because paths do not freeze content.
See docs/evidence/ca-p2-01b/README.md for evidence and skipped/live gate boundaries.
No deployment, production migration or main/cloud-agent integration.

# 2026-10-21 — CA-P2-01A native Runtime Bundle validation

Owner Luke Ding/Codex; branch codex/ca-p2-01a-bundle-contract from published6dbb2a8d,
new isolated worktree, preserving the P1pinned worktree and original cloud-agent dirty work.
Implemented independent cloud-agent.bundle-envelope/1 + runtime-bundle/1 immutable
contract, all20explicit domain bindings, exact validation-only native catalog/asset
closure, bounded strict JSON/canonical bytes/SHA256 and trusted-reader compatibility.
Model/instruction candidate parameters have strict schemas; other18domains stay
pinned/empty with reasons. Published native schema/catalog/example/canonical/digest
artifacts and offline --input/--schema/--catalog CLI. No new dependency/framework.

The descriptor stays bundleManagement/nativeScriptAbi=unsupported. No HTTP/credential
expansion, storage/migration, effective Release/Task binding or Worker assembly.
Asset/image/baseline config pins are declared closure, not verified assets or proof
of executable configuration. Component hashes identify descriptors, not loaded code.
Old Definition/Snapshot v1 bytes/digests, recovery and Coverage source unchanged;
deterministic baseline v1goldens cover eval/production snapshots without reading
any existing database or rewriting history.

Design/plan/spec and independent quality/security reviews approved. Baseline21passed;
new focused163passed/zero skip; preserved Definition/binding/Coverage82passed/1PGskip.
make check passed (30/30eval); final r2 make test10620passed/3007skipped,exit0.
Superseded SIGINT partial run is recorded separately; sourcefreeze matches final gates.
Final counts, source/golden/log hashes and delivery boundary are recorded in
[validation](docs/evidence/ca-p2-01a/validation.json). [Public contract](docs/RUNTIME_BUNDLE.md).
No deployment/production migration or main/cloud-agent integration; native feature
commit/push after completed final gates, remoteSHA confirmed in separate delivery receipt.
Prior sections below retain historical meaning.

# 2026-10-21 — CA-P1-01B2 scoped outbound connector management

Implemented GET/PUT /management/v1/host-connector with fixed operator-approved immutable
Profile and actual Binding CAS/disable/reactivation. B1 current approval, private scoped
credential and bounded transport are reused; connector actions are explicit and existing
B1-only fingerprints/permissions stay unchanged. Shared approval rotation fences B1/B2
replicas together. Profile/Binding, separate receipt and audit commit atomically; unknown
COMMIT requires exact currently-authorized replay or current GET, never blind new writes.

Shared native publication now locks manifest revision and preserves frozen legacy ownership;
legacy bind enforces actual expected-current revision. No historical bytes/digests rewritten.
Additive v109 adds B2 evidence only. Upgrade all writers/API/Worker consistently; rollback
closes B2 on a v109-compatible binary, not an automatic schema/binary downgrade.
No external I/O under locks; existing request/DB/expiry deadlines and bounded capacity apply.

Final focused HTTP/storage/independent-process checks:102passed/zero skip. make check passed
(mypy1339, eval30/30, zero file-size violations). Final make test exit0:
10457passed/3007skipped in1025.55s, frozen sources unchanged after both gates. Wider native PG regressions
90passed/2existing S3-dependent skips; delegated output lacks a retained log/source snapshot,
separate from the frozen-source final gates. Owned scratch v108->v109 preservation probe
kept nine seeded table snapshots unchanged and consumed Grant replay rejected.

Independent design/spec/quality/contract reviews approved. Evidence and proof limits:
docs/evidence/ca-p1-01b2/validation.json; operator/API guide docs/CONNECTOR_MANAGEMENT.md.
Binding disable is not global Profile revocation or running Task cancellation. Go authorized
intent/unknown reconciliation remains pending; frontend remains mock. No production migration,
deploy, business network/model/Task/IdP proof, main/cloud-agent merge or original checkout change.
Earlier records are historical snapshots.

# 2026-10-21 — CA-P1-01B1 native scoped Host registry management

Implemented optional GET/PUT /management/v1/host-registry with independent rthm_ service
credential, exact deployment/product/environment/Host binding, approved immutable template
and shared current PostgreSQL approval/fingerprint fencing. Additive v108 preserves registry
rows and all replay/Coverage/history evidence; legacy privileged upsert advances revision.
CAS, successful audit and operation receipt commit atomically. Unknown acknowledgment is
503 and identical currently-authenticated replay recovers the original single mutation.

Request/body/config/DB work is bounded, no network under locks. Credential expiry bounds
lock waits and transaction exit; late results cannot bypass current trust. Optional disabled
composition stays lazy; configured cloud uses actual CloudCompositionSettings DSN when
provided, never a second settings database. API has no automatic migrations/approval.
Upgrade all registry writers before enabling B1; old writers do not advance revision.

48 focused real PG/HTTP/independent-process and existing descriptor checks passed; final
make test10403passed/3007skipped and make check passed. Full gates and source hashes are recorded in docs/evidence/ca-p1-01b1/validation.json.
Independent spec/quality reviews approved after nested-JSON/uncertain-COMMIT coverage and
CORS preflight contract clarification. This is inbound Host trust, not outbound connector,
Go orchestration, Task/model/business IdP/browser, storageHA or production deployment proof.
Original checkout dirty paths/services/data remain unchanged; no cloud-agent/main merge,
deployment or production migration. Source/remote SHA is confirmed in the delivery receipt.
[Native operator/contract guide](docs/HOST_REGISTRY_MANAGEMENT.md).

# 2026-10-21 — CA-P1-01A read-only scoped management

Implemented native runtime-management/1 GET /management/v1/target with separate opaque
credential digest, exact deployment/namespace/audience/product/environment/action and
expiry binding. Private bounded configuration is reread for rotation/revocation; malformed
configuration fails closed, timed-out reads retain their capacity slot until finished.
The native contract and scope/compatibility rules are in docs/RUNTIME_MANAGEMENT.md.

No Host/connector writes, migrations, execution/Coverage changes or readiness claims.
Code migration number remains explicitly distinct from actual database/Worker readiness.
Unconfigured management preserves existing local and injected-cloud lazy startup; initial
full suite exposed six eager-store regressions, fixed at the optional composition seam,
with70new/existing composition checks passing. Final make test passed10366/3007skipped
and make check passed (Ruff/mypy1329/eval30/30 and repository gates).
Independent review found no additional Runtime blocker. Real paired Go/Python/TLS/temporary
platform-PG acceptance passed separately; native storage there is local SQLite, not a cloud
readiness or production HA proof. Final gate/source evidence is docs/evidence/ca-p1-01a/.
Original checkout's unrelated dirty work/data/services remain untouched in their checkout.
Feature source delivery is independent from main/cloud-agent integration or production.
Earlier sections are historical snapshots.

# 2026-10-20 — Four-batch decoupling audit locally verified

CLOUD-DECOUPLE-AUDIT-01 on cloud-agent, Luke Ding owner/Codex executor. Preserved
previous145dirtyfiles and32container identities. Two readonly audits found7classes
of actionable gaps: filtered/stale conformance PASS and auxiliary evidence collision;
neutral/non-overwriting key bootstrap; missing Runtime gates in joint candidate;
configured connector paths and report sibling; shared-digest revision freeze and
cross-generation writer divergence. Fixed with existing helpers/stdlib and no new
dependencies. Profile routing shared across API admission/Worker/report; historical
nullable profiles retain previous URLs. Explicit profiles use frozen static paths.

v107 adds Host-scoped revision freezes without rewriting old table/JSON/digests.
Both updated write APIs share transaction locks and reject conflicting/ambiguous
writes. Apply v107 BEFORE new API/Worker startup, coordinate consumers before new
admission; old binaries cannot read new-only freezes. No existing DB was migrated.

Final make test exit0:10376passed/2987skipped in1162.17s. Make check exit0 including
boundary/Ruff/mypy1328/eval30/30. Final contract161pass/0skip even with old filter env;
real scratch PostgreSQL conformance87pass/0skip, mixed-writer13pass, report routes8pass.
Spec/security GO, quality APPROVE; shared path focused38pass and independent45/59pass.
Earlier partial full runs, old test assertion failure and duplicate kwargs failure
retained; only final completed gates count as full acceptance. No proof weakening.

Current API/worker-engine/migrate images match frozen production/config source;
isolated cloud/gVisor no-fallback boot/preflight/401 and API restart retained object/
Host registry pass. No business Task or actual model used. Original32containers,
user files and129finalsource hashes unchanged; own scratch cleaned. Defaults no
longer require Trench services; explicit legacy/history/mock examples remain.
Product/Broker/browser/model/remoteCI acceptance and production retirement not claimed.
Formal docs/checklist/README updated, local Review; no commit/push/deploy/live changes.
Evidence: .artifacts/cloud-decouple-audit/validation-summary.json. Historical logs follow.

# 2026-10-20 — CLOUD-DECOUPLE-04 locally verified

Branch cloud-agent, user-directed existing checkout, Luke Ding owner/Codex executor.
Core/default transport now own Runtime command hints only. Trench Turn/source
wire and joint/source/shadow topology are explicit integration compatibility;
old schema/examples bytes unchanged,94 mocked topology/ACL requests identical
HEAD. Default provisioner uses only Runtime credentials, no deletion/rotation.
Historical contracts/Task/Event/Coverage proof/Effect identities remain unchanged.

Offline retirement checks bind namespace/compatibility/time/digest/task set and
require drain or immutable Runtime pin and rollback; output states materials
consistency only, never live authorization or authenticated inventory provenance.
Historical decoder retained; no production retirement. New default ownership gate
and product conformance Make/CI distinguish contract vs scratch-storage evidence,
refuse skipped/empty runs, and retain manual Trench joint acceptance separately.

Final make test exit0:10342passed/2974skipped in1139.10s; make check exit0,
including boundary/mypy1326/eval30/30. Contract conformance145pass/0skip; actual
scratch PostgreSQL87pass/0skip. Spec GO/quality APPROVE; quality focused161pass.
Current-source API/worker-engine/migrate built; isolated cloud/gVisor no-fallback
boot/preflight,401 and restart retained object/Host registry pass. No business
Task or model calls; Host/S3/model fixtures in storage conformance. Actual Broker,
production data source/model/browser/remote CI and live retirement not accepted.

Original32container IDs, user files and123source/config/test hashes unchanged;
own scratch removed. No migration/DB rewrite/existing service restart, commit,
push or deployment. Formal plan/docs/README/registry updated, status Review.
Evidence: .artifacts/cloud-decouple-04/validation-summary.json; formal design:
docs/CLOUD_AGENT_DECOUPLING_BATCH4.md. Earlier records follow.

# 2026-10-20 — CLOUD-DECOUPLE-03 Coverage locally verified

Branch cloud-agent; Luke Ding owner/Codex executor, existing checkout as requested.
Versioned v2 frozen dataset revision/source permissions/opaque selector, fixed
coverage-source/2 dataset.snapshot ABI, Worker/Effect/bootstrap/recovery/storage
and API report wiring. v1 JSON/digest/Manifest/create CallID remain literal-golden
compatible; no historical data rewrite or new migration. Proof membership/parts/
bytes/result sets, budgets, expiry/revocation, fencing, unknown-write recovery,
certified publication and every-output fail-closed guards retained. Report GET/HEAD
checks exact current owner before source metadata and frozen read permissions after;
actual before_consume verified without agent.run or source write permissions.

Final make test exit0:10222passed/2974skipped in1118.77s; make check exit0,
mypy1324/eval30/30. First complete run had2 stale deadline-test patch points;
updated tests retain shared outer/preflight/read deadline, no-read/no-delivery
exhaustion and CPU-overrun checks, independently approved, full gates rerun.
Real scratch PostgreSQL proof/Effect/recovery217pass, report/preconsume51pass,
no skips; Core/source1320pass. Host/S3/model are fixtures, not production source
or actual-model E2E. Default suite skips remain explicitly unverified there.
Independent design/spec/quality approved. Evidence: .artifacts/cloud-decouple-03/.

Original32container IDs/user files and98source/test/config hashes unchanged
through final gates; own scratch cleaned. Existing services/DB/data untouched.
Docs: CLOUD_AGENT_DECOUPLING_BATCH3.md and formal plan/registry updated.
Local Review, uncommitted/unpushed/undeployed. Batch04 remains separate; full
Trench compatibility retirement and real-product acceptance are not claimed.
Historical records follow.

# 2026-10-20 — CLOUD-DECOUPLE-02 local implementation verified

Branch cloud-agent, existing checkout; Luke Ding owner/Codex executor. Eval
repair and both full gates completed BEFORE batch02 runtime edits. Final full
make test10162passed/2934skipped exit0 (1127.97s); make check exit0 including
mypy1323/eval30/30. First batch02 full run had only a stale migration catalog
expectation (106 omitted); minimal expectation fix independently reviewed,
then BOTH commands rerun to completion. Failed and passing logs preserved.

Implemented generic HTTPS current-authority adapter with opaque principal,
explicit Trench legacy mode, signed opaque-resource schedule renewal and
strict firing/identity narrowing; declared resource bindings and frozen marker,
nullable immutable profile policy and additive v106 persistence. Old profile
JSON/digests and historical manifest golden remain unchanged. New generic
CLI/compatibility settings documented. No token-pair issuer or Go backend.

Evidence: .artifacts/cloud-decouple-02/validation-summary.json. Focused realPG
88pass/2S3skip plus client-effect recovery12pass; authority/renewal/frontend94pass;
compatibility50pass. Independent spec GO/quality APPROVE. Five images rebuilt;
corrected worker-engine independent boot, gVisor preflight,401 and API restart
retention pass. Initial wrong worker target failure retained; no gate weakening.
Final59 source/test/config hashes match freeze; original32container IDs and user
files unchanged; own scratch removed. v106 applied ONLY on scratch databases.

Design/task checklist: docs/CLOUD_AGENT_DECOUPLING_BATCH2.md, AGENT_TASKS.md.
Local status Review: no commit/push/deploy or existing DB migration. Production
business/browser E2E remains unverified; simulated Host/browser and real storage/
process startup evidence are distinct. Coverage and messages remain batches03/04.
Historical records follow.

# 2026-10-20 — Eval baseline restored; batch02 unlocked

CLOUD-EVAL-BASELINE-01 corrects replay mutation/read ordering without changing
production policy or thresholds. Independent review approved;62focused checks
and eval30/30 pass. Full make check exit0; full make test exit0 with
10075passed/2931skipped (1144.74s). Evidence: .artifacts/cloud-decouple-02/.
CLOUD-DECOUPLE-02 claimed only after both results; design and exact paths in
AGENT_TASKS and CLOUD_AGENT_DECOUPLING_BATCH2.md. Same cloud-agent checkout,
no data rewrite, running-service restart, commit or push. Historical records follow.

## 2026-10-20 - CLOUD-DECOUPLE-01

First-batch source implementation on user-selected cloud-agent. Product-neutral
base Compose no longer mounts Trench CAs, starts its legacy API or requires
Scheduler authority to render. Explicit compatibility overlay retains historical
legacy namespace/image, Scheduler identity and CA mounts after local-gVisor.
Standalone rollout v2 and versioned rehearsal retain mandatory Runtime evidence;
strict joint v1 now requires its passing product gate. SDK usage copy is neutral.
No auth/coverage business-protocol refactor, data migration or production cutover.

Real linux/amd64 API/Worker/migrate builds and isolated PG/Redis/S3 boot pass:
migrations, API/Worker health, real gVisor readiness with no local fallback,
anonymous401, API restart and S3/Host-registry preservation. All32 existing
running container IDs retained; scratch resources cleaned. Existing engine mTLS
credentials were copied into a private temporary directory; no business CA,
Cookie, Trench endpoint or database configured. No Task/model/sandbox execution
in this boot check.

Final focused independence suite105passes; SDK pnpm check passes.
Candidate/rehearsal CLI contract fixtures pass, while
missing real release evidence fails closed. Fixtures are not production release
proof. make check passes file sizes/Ruff/mypy1319 then fails deterministic eval
at0.80/30cases; pristine HEAD archive and its baseline unit test reproduce the
failure. Separate remaining progress checks pass. Full-suite snapshot returns
10067pass/2931skip/1same inherited failure; final105 cover the last v2 guard
added after full-suite start. Exact evidence/boundaries are recorded in the plan.
Spec and quality reviews approve after joint/independent gate-bypass fixes.

See docs/CLOUD_AGENT_DECOUPLING.md and
docs/superpowers/plans/2026-10-20-cloud-agent-decoupling.md. No commit, push,
registry publication or existing-service restart performed. Later tasks02-04 are
Locked pending acceptance; first batch does not claim complete business decoupling.

## 2026-10-20 - CLOUD-VERSION-SYNC-20261020

Production was missing committed Plugin/runtime/frontend updates despite the
latest incident overlays. All application roles now align with Zebra6bca5053 /
Trench8feacbf, with existing HTTP checksum compatibility separately retained.
Full live fingerprints:1322Zebra files per role,537Trench files per role,222front
files; zero differences from the explicit deployment manifest. Schema104->105,
image-only cutover after live business drained; v105-compatible rollback prepared.
270targeted checks pass/1skip; login/assets/readiness200 and six ARQ heartbeats.
No model/search/Run acceptance; Plugin production switch remains false. Search,
Exa/Yahoo/MCP, global proxy, protected original events/high/v2/data retained.
RSS upstream ingestion errors remain an explicit operational observation, so this
is version/deployment acceptance, not a full-business-health claim. See
docs/CLOUD_VERSION_SYNC_2026-10-20.md for source provenance and rollback.

## 2026-10-20 - CLOUD-YAHOO-EGRESS-20261020

Yahoo retrieval is restored through the existing per-engine proxy seam, without
product source/dependency changes. Root cause: global DIRECT route accepted
CONNECT but failed target TCP after abnormal DNS answers; no Yahoo HTTP exchange.
A dedicated non-root, loopback Yahoo-only outlet reuses the tested existing node,
static binary and installed image. Exactly one user-authorized Search recreation;
image/settings/cache/Exa cooldown retained. One NBOPC native tool acceptance:
3261.81ms,5results,official rank2. Four existing offline native checks pass.
No models/new Runs/original replay/global proxy or Trench logic changes;
other service identities, original event hashes/high/stream-v2 retained.
This closes retrieval recovery, not a statistical/page/model performance claim.
See docs/CLOUD_YAHOO_EGRESS_2026-10-20.md for active override and rollback boundary.

## 2026-10-20 - CLOUD-RUNTIME-REPAIR-20261020

Five minimal runtime/protocol fixes are deployed to production192.168.110.30:
fixed operator search-port admission/registration, provider-safe clarification
resume, correctable blank read paths, verified-source body link evidence and
truthful blocked/partial suspension.326Zebra/30Trench no-model checks pass;
Ruff/mypy1319/file sizes/progress checks pass. Full eval remains24/30, exactly
reproduced on the unmodified baseline. No unrelated fixture repair was added.
Original Session event hashes/model counts, high/stream-v2, permissions, runtime
configuration, Search/TLS/Broker identities and Exa state are retained. No models
or original Run replay. One NBOPC native search reached Yahoo but failed after
6049.68ms with search_incomplete/upstream five-second timeout; no automatic
repeat. Search E2E/recall acceptance remains open, not complete. See
docs/CLOUD_RUNTIME_REPAIR_2026-10-20.md for proof boundaries and rollback.

## 2026-10-20 - Trench baseline archived; generic Cloud branch inherited

Frozen compatibility tag cloud-agent-trench-archive-2026-10-20 is verified on
both GitHub repositories: Zebra a4d0e90f (accepted source06578c09), paired Trench
f25ea8b. cloud-agent inherits the entire baseline and this docs-only receipt;
Zebra main remains unchanged.45historical Zebra topic refs removed,9clean
worktrees detached at identical SHAs;11unique/14dirty occupied refs and all41
worktree directories preserved. Both redundant remote settings/media refs removed.
20dirty tracked diffs/4protected files and5normal service identities unchanged.
No source/configuration/migration/restart/deployment, model/search or MCP calls.
Runtime readiness remains bounded by existing evidence; the next generic Cloud/
management task must be separately claimed. See
docs/CLOUD_TRENCH_ARCHIVE_2026-10-20.md for frozen identities and remaining gates.

## 2026-10-18 - CLOUD-RECOVERY-VERIFICATION-03

Recovery retains per-resource verification scope/evidence and prompt dedupe;
legacy mutations missing scope pause before model/tool dispatch. Capsule/handoff
views exclude skipped without historical rewrites. Researcher paused summaries
retain their reason, unmet items and bounded existing result, with exact guarded
legacy-wakeup compatibility.1846 no-model checks pass/3environment skips,
Mypy8files/Ruff/image/runtime checks pass. Local Worker3eb51845/APIacf4978d are
healthy; both retained Run pages remain partial/no executing/high. Protected
original partial hashes, high/v2/dedupe, Search/Exa and event counts preserved;
no model/search, Trench/Desktop change, push or remote deploy. See
docs/CLOUD_RECOVERY_VERIFICATION_REPAIR.md.

## 2026-10-18 - CLOUD-SKIPPED-WAITING-02

Shared skipped classification now covers retry, context compaction and final
verifier fallback without suppressing independent evidence. SDK ordinary waiting
has explicit waiting presentation and retains real activity outcomes. No Desktop
or historical Event changes. Offline core/context1782pass/1skip,SDK24pass,
installed Trench47pass,build/types/lint and network-disabled Worker checks pass.
Local Worker b8175274 and paired Trench70ce702 are active; both retained Run
pages reload as partial/no executing/high. Durable model/tool and Session counts,
protected original partial hashes/config/dedupe match exactly. API/Search/Exa
preserved, no model/search/new Run or Desktop change. Frontend-only restart
removed cached SDK; served waiting branch verified. See
docs/CLOUD_PAUSED_VERIFIER_REPAIR.md.

## 2026-10-18 - CLOUD-PAUSED-VERIFIER-01

Authoritative partial/blocked delivery now stops waiting-input execution badges;
the two retained real Run pages show 部分完成, not 执行中. Noop verifier results
are false/skipped and ignored as retry success/failure; real configured checks
retain their result. Core1712pass/1skip plus5focused checks,frontend45pass and
actual-Worker offline checks pass. Normal Worker d814124b healthy, no new
model/search/tool/Run; protected original partial hashes/high/v2/dedupe preserved.
Paired Trench local integration80f3896; no historical Event rewrite or push.
See docs/CLOUD_PAUSED_VERIFIER_REPAIR.md.

## 2026-10-18 - Real mutation safety acceptance completed

Fresh user-authorized change/operate page pair now reaches successful isolated
writes without verification. Both correctly pause as awaiting_input with partial
delivery;2real model rounds/1write/0retries each. No-read operate stops despite
remaining3tool+1model budget. High/v2/de-duplication and protected original Runs
preserved; prior failed sample not replayed. Normal Worker87505c5e restored.
Remaining trace-badge and skipped-hook metadata inconsistencies are recorded,
not repaired in this acceptance-only slice. See
docs/CLOUD_VERIFICATION_DEFAULTS_REPAIR.md.

## 2026-10-18 - Mutation page acceptance remains open

Real change sample failed before business dispatch at Effect payload admission;
no false completed status, but target successful-write/missing-proof checkpoint
was not reached. Operate not run; no retries/replacement. Normal Worker restored,
original partial Runs unchanged. Test-only initialization/type issues corrected
and checked offline; new pair awaits authorization. No production source fix or
new acceptance success claimed. See docs/CLOUD_VERIFICATION_DEFAULTS_REPAIR.md.

## 2026-10-18 - Verification defaults page acceptance

One real explanatory high/v2 Turn completed as answer, one main model round,
zero tools/retries and 9.781s Turn interval. Suggestions generated/saved once;
refresh snapshot identical with zero POSTs. Both original partial Turns exact.
Actual Worker33 scripted change/operate safety cases pass; no live mutation
page scenario or fault injection. See docs/CLOUD_VERIFICATION_DEFAULTS_REPAIR.md.

## 2026-10-18 - CLOUD-VERIFICATION-DEFAULTS-01

Explicit change/operate defaults now require verification and matching outcomes;
missing read capability cannot count as proof or trigger an impossible extra
verification round. Complete agent-core: 1,710 passed / 1 skipped; existing intent
and date checks plus Ruff pass. Local Worker-only activation now accepted: 47 fresh source checks and 33 offline
cases in both disconnected image and actual Worker pass. Healthy/restart0/exact
configuration; API/Search and two protected partial Turns unchanged. No external
model/search requests; high/v2/dedupe retained. See
docs/CLOUD_VERIFICATION_DEFAULTS_REPAIR.md.

## 2026-10-18 - CLOUD-EXPLAIN-CONTRACT-01

Shared task-contract inference now recognizes 说明 as an information request,
without removing explicit mutation/operation or post-mutation verification.
59 focused offline tests and existing standalone intent/date checks pass.
Worker-only local activation and original-question high/v2 page acceptance
passed: completed answer contract, one suggestion request auto-saved, exact
reload restoration with zero repeated POSTs. Original partial Runs unchanged;
see docs/CLOUD_EXPLANATORY_CONTRACT_REPAIR.md.

## 2026-10-18 - TRN-ASSET-RECOVERY-01 (validated delivery)

Historical assets use bounded owned references, read-only artifact authority and
canonical legacy ownership checks. Local page: 14 files / 3 reports; all 14
browser downloads and native payload-length checks pass. Six retained Tasks had
only missing read metadata prepared; canonical Event content hashes are unchanged.
Historical API now uses a schema-compatible image; Worker/Search unchanged.
Trench full gates and Zebra make check pass. Full Zebra run: 9,718 pass / 2,923
skip / one old issuer fixture failed. Test-only scope fix: issuer suite 16 pass,
last-failed rerun 1 pass. Production code unchanged since full-run start. Delivery
to existing cloud-agent-trench (paired Trench main); see docs/TRN_ASSET_RECOVERY.md.

## 2026-10-18 - Trench settings and media repair (validated Review)

TRN-SETTINGS-MEDIA-01 restores user-management grants without fabricated Task
bindings, accepts both usage periods over HTTP, permits canonical successful
files.publish media under workspace policy, and converts bounded numeric chart
conditions to declarative predicates. Local API activation was user-approved;
original settings, four SVG charts and external-video playback were verified.
All 18 first-run failures are repaired. Zebra complete test: 9,633 passed /
2,921 environment skips; make check passes. Trench make check passes (233 API /
80 cleaning / 472 frontend passed); SDK full verify passes (104 tests and
package/consumer/browser matrices). User-authorized delivery is on the paired
codex/trench-settings-media-01 branches (pushed). User-requested integration
targets existing Zebra cloud-agent-trench and Trench main. Combined Zebra
verification passes: 9,646 tests / 2,921 environment skips, zero failures;
make check and 35 focused regressions pass. No new branches are retained.
Details: docs/TRN_SETTINGS_MEDIA_REPAIR.md.

Local repair closeout (2026-10-14): deployed API source hashes match both repaired
formatters, API/Worker healthy. Both original history answers verified790/2210
characters; original model counts4/7 unchanged. Normal dotenv dispatcher admitted
transient_v2 with all capabilities; probe cancelled before execution, model calls0.
No push, remote deployment or database backup; user dirty files preserved.

## 2026-10-14 - v2 initial source preparation follows bounded recovery

An actual admission-only probe exposed the same temporary-source error in v2:
CheckpointNotReady became permanent stream_source_unavailable before Worker startup.
Only that typed branch now emits retryable409 projection_not_ready; invalid cursors
and unexpected/broken sources remainfailclosed. Focusedv2/preparation24 passed,
one inherited environment-dependent case skipped. Two original Runs synchronized
790/2210 characters with unchanged model-call counts4/7; actual new admission was
transient_v2 and cancelled canonically before execution, with0 model calls.
The original no-retry startup probe failure remains in private operator evidence.

## 2026-10-14 - Temporary AG-UI preparation remains retryable

CLOUD-STREAM-OBSERVER-REPAIR-01 fixes the existing shared stream problem formatter:
409 projection_not_ready includes retryabletrue; conflicts remain failclosed.
Focused preparation/command/stream routes25 passed. Initial regression caught the
separate command formatter alias; production fix is only in stream_problem.
Trench normal Settings/dotenv v2 negotiation checks38 passed. Local API update
and exact original-Run GET recovery are authorized; no new model execution.

Cloud stream validation follow-up (2026-10-14): clean exact-source make check
passed. Full make test interrupted only after confirming inherited unbounded
terminal-race test patches obsolete Session read_since; f91906dc already uses
bounded pages. Partial JUnit retains 96 failures/1 error/228 skips
among10255 cases; failure classification remains OPEN. Test-only path claimed
before fix; preserve scheduling assertions and add bounded collection. Production
runtime a4b2 and18 actual600s cells unchanged. No local integration yet.


## 2026-10-13 - Canonical observation failure: bounded graceful-close fix

Reviewed289e freeze SPEC70/no-skips54.259s and QUALITY110/no-skips232.532s plus
47adapter probes passed. Matrix03 on35e2 then completed nine quiet600 cells;
pausedSession1 recovered before client RemoteProtocolError around291s. Observed
TaskIOconnect TimeoutError after successful resolver was nearby, but original
native server linkage/infrastructure cause remains unproven. Immutable failure
capture dc17dfda49c6f2f1f76d95da1c49107ca865b4316e7d2f9d719994dca485c097 retains
nine results/start/end maps and raw hash references;289e remains unchanged.

Harness-only capture records ASGI exception/leaf CLASS, phase and monotonic times
before original re-raise; cancellation remains separate. Failed windows now retain
scheduledend versus actualexit, completedLeasecount and incomplete/SLOFalse.
Capture gates01/02 each4pass/1unexecuted async-test registration failure retained;
repository asyncio.run convention fixed this; gate03 passed5/0skips .986s.
Controlled launcher01 failed missing tests import BEFORE native startup, retained.
Controlled02 on11af injected once only in native connect after real recovery at
fresh canonical Sessionhead: server ASGI TimeoutError during streaming followed
by client RemoteProtocolError. Partial30.1753s/requested45, Lease0/SLOFalse.
This proves controlled mechanism, not the original infrastructure cause.

One natural pausedSession1 diagnostic on11af completed actual steady600.000979s
(ended-started); observe return600.089277s includes cleanup; connected600.098204s.
Startup41/steady69/post0/inclusive110SQL, rate.11499981235,3Lease heartbeats,
1actualpeer/full recovery,0ASGI exceptions. No repeat or18-cell acceptance.

Minimal optionA changes only V2 pending.result typed TimeoutError/OperationalError:
check frozenGrant deadline/disconnect, emit existing draft reset then retryable
observation_unavailable notice with another boundary check, then graceful close.
Original finally cleanup remains; no automatic retry, sourcecache, provisional
continuation or Task failure. Unknown/custom/integrity errors and CancelledError
retain original behavior; outer deadline_frames unchanged. Existing HTTP consumer
already rejects premature StopAsyncIteration: earlier possible falsePASS concern
was unconfirmed and corrected, no redundant harness guard added.

Focused A gate01:6pass/7RuntimeError cleanup failures53.657s, retained. Direct
reader test closed Redis asyncclient in a second loop; test-only same-loop fix.
Gate02:13pass/0fail/error/skip52.224s. Six typedfault cases cover Session/Task/AGUI;
unknown/cancel identity and between-notice deadline/disconnect checks pass.
ActualHTTP controlled fresh-head connectfault requested600 emits complete SSE
reset then observationnotice, closes without ASGIexception, and triggers existing
healthy-window EOF assertion at30.189602s/Lease0/incomplete/SLOFalse. No weakened
subscription check, second natural600, fullmatrix rerun or infrastructure repair.

Current runtime1269 SHA a4b2e24b39abcfe32c4fd4d81b8f2a0be31c58db9e8e676249f5213161e2f743.
New focused test SHA a25706248158748594c8b377dfe337f7fed904447af57c75fdf3dff654290431.
Current-source Ruff/fullmypy/filelimits/eval/diff pass; literal make check exits2
on277Ruff findings, every location historical .artifacts copies/diagnostic scripts.
No archive/config modification. NEW private freeze requires fresh SPEC then QUALITY;
prior reviews are historical. Full make test,18healthy600, matched-v1 inclusive80%,
reliability/fullruntime/product acceptance remain OPEN; no commit/integration/push.


## 2026-10-13 - Slice2 compatibility follow-up ready for independent review

Accepted ed796 frozen SPEC GO followed by QUALITY NO-GO is preserved: nominal
131 native checks did not cover custom namespace/highwater public hooks. Original
method identity guards now honor publisher and underlying EventStore hooks.
Raw/AGUI shared proof eligibility also honors native Task map/latest/header/Run/
checkpoint/Event/frame/segment/cell/page hooks, authority bind/bind_snapshot, and
old-signature prepare callbacks. Optional-head and restore consumers choose their
existing fallback before shortcuts; SQLite and explicit nonnative Ports unchanged.

AGUI one fresh request RR closes before tail/backpressure. Initial identity-only
Taskheader is allowed only after original native V2 binding qualified the same
Task in that snapshot; full checkpoint SOURCE remains mandatory. No auth/cache,
expiry/deadline/ramp/pool/executor/write change. Matrices06/07 real startup failures
remain: observed TimeoutError, respectively subscriber83 and73. Matrix06 measured
Hostqueue.563s/post-JTIqueue.903s and headentry parentremaining.126s. Matrix07 measured
Hostqueue.425s/post-JTIqueue.919s, parentremaining.316s and headexecute.1695s;
1socket alone did not establish capacity. Original unobserved failure92 remains
unclassified; no PG error inferred. Both prior partial600 matrices stay incomplete.

Native AGUI snapshot103/198.631s (011b), scoped dedup103/198.124s (222f), shared
compatibility2/12.113s plus affected104/217.825s (0562), callback25/15.141s (35e2)
passed without skips. Fixture failures and original f919 stale-hook proof remain.
Diagnostic08/matrix08 on222f are historical five-second evidence. Final matrix09
on35e2 completed six100-subscriber cells, each100 admissions/recoveries/distinct
TCP peers and actual post-JTI1socket; all1269 start/end/live hashes match. Lease0,
SLOFalse throughout: no600 steady, stable capacity or matched-v1 inclusive80% claim.

Current runtime SHA35e2ccb1daa5dcaa4ac2ea5fa6320ff42a75f35d5657457c482157b44c761c04.
New private source/safe-proof freeze precedes fresh serial SPEC then QUALITY.
Full make test,18healthy600 matrix, reliability/fullruntime/product gates OPEN;
no commit/integration/push/deployment. Historical literal make check artifact-only
Ruff failures remain distinct from passing equivalent current-source gates.

2026-10-13 root: slice1f91906dc locally integrated into cloud-agent-trench;
primary native10/no skips18.702s. Fresh17dirty-file manifest hash-exact after
FF plus original41non-UI dirty hashes unchanged; current combinedUI hash exact.
No SDK changes/retest, push or deployment. Slice2 exact readonly source/core/API/
integration and two native-test paths claimed before code on same PERF card,
owner Luke Ding/executor Codex/branch codex/cloud-stream-proof-perf-01. Preserve
optional-port SQLite compatibility, fresh integrity/privacy checks, parent
Session coordinates and AG-UI full membership; inclusive quiet target remains
OPEN including paused-generation authority refresh.

## 2026-10-13 - Proof PERF slice1 accepted locally

Independent SPEC and QUALITY GO at frozen f9f777f344f6f2a12e4646b7e11743d2f7047c19281cad9ec4208fe6fd4df116.
Four fresh Worker snapshots reduce measured activation to72SQL/4connections;
factory16SQL/3connections separate; API bind18/qualify32SQL, each1connection.
FrameSQL0. Historical81/18 baseline uses a different fixture, no paired latency
claim. QUALITY native45/runtime15/shared48 plus4 lifetime scenarios passed;
SPEC native45/runtime15/shared30 passed. All22source/18proof live/archive hashes
verified independently. Six unrelated resource-binding fixture failures match
accepted249f4e6d. Scoped slice1 only; whole PERF and inclusive quiet target OPEN.
Post-review root changes only acceptance/governance docs before explicit owned
commit/local integration; no push/deploy. New admission remains OFF.

## Cloud stream proof performance claimed — 2026-10-13

CLOUD-STREAM-PROOF-PERF-01 claimed Ready before coding on clean managed
codex/cloud-stream-proof-perf-01 base249f4e6d. Luke Ding owns; Codex executes.
Slice1 explicit readonly fresh snapshot batching, retaining issue/resolve
independence and full source/privacy/fence/Host/Turn/count/bytes/2s bounds.
Readonly COV paths explicitly transferred in task card; no mutation/recorder.
No authority cache or extended polling. Slice2 exact ownership amendment before
qualified quiet-head changes; goals still unmeasured. Admission OFF, no push/deploy.

## Cloud stream CLIENT locally integrated — 2026-10-13

c0e073fe fast-forwarded into cloud-agent-trench after independent SPEC/QUALITY.
Primary native40/no-skips65.92s; combined dirty SDK99/no-skips7.07s and build/type
check GO. Initial combined98/99 retained one timeline collapse assertion failure;
isolated21 and full99 rerun pass. No unrelated UI modifications:41 originaldirty
file hashes unchanged, original UI-contract hunks byte-exact after feature reverse.
CLOUD-STREAM-PROOF-PERF-01 unlocked Ready, not claimed/coded yet; reduce fixed
fresh-proof/quiet-read costs next. Admission OFF, no push/deploy; product gates OPEN.

## Cloud stream CLIENT bounded component accepted — 2026-10-13

Independent SPEC and QUALITY GO on freeze17dd8f7d after historical-memory,
ACK retry/legacy expansion, parent-Session and reset/disconnect repairs.
Renewed QUALITY native39/no-skips68.69s and SDK80/no-skips; original failure
reproductions now converge without duplicates. All41source/current5proof hashes
and archived source/proof copies verified. Root preparing explicit-path local
commit/integration; no push/deploy, admission OFF. Full total SQL/TTFT, aggregate
quotas/relay/STOP/100subscribers and joint runtime/browser acceptance remain OPEN.

## Cloud stream fixed-cost performance follow-up — 2026-10-13

Readonly native audit measured one activation at81SQL/18 fresh connections/
297.5ms (68SELECT+13SET); quiet Session/Task/AG-UI cycles13/12/13 SQL. At30s,
inferred rates0.433/0.400/0.433 exceed0.2 target before additional HTTP costs.
CLOUD-STREAM-PROOF-PERF-01 added Locked after CLIENT acceptance: explicit fresh
proof batches, then complete source-qualified head reads. No mutable authority
cache or polling-delay substitution. See docs/CLOUD_STREAM_PROOF_PERF_PLAN.md;
full SQL/TTFT/ten-minute/capacity acceptance remains unverified.

## Cloud stream CLIENT component ready for independent review — 2026-10-13

Three actual v2 HTTP routes, signed scoped cursors, trusted generation discovery,
canonical recovery and labelled SDK drafts implemented on clean CLIENT base.
Durable AG-UI checkpoint semantics unchanged. Native reader/cursor30pass; clean SDK80pass,
Chromium synthetic fixture pass, static gates pass. Final configured cohort and
freeze manifest recorded in docs/CLOUD_STREAM_CLIENT_EVIDENCE.md. Independent
SPEC first review found unbounded historical call tracking; current-descriptor
closure fix and 5,000-history regression passed. QUALITY then found ACK retry
staging and legacy ASCII expansion; corrected with SDK73 and configured196/no
skips/182.28s proof; static sizes3008/Ruff/mypy1264/eval30 GO.
Parent canonical Session handoff now preserves history and excludes child drafts.
Renewed SPEC found reset/disconnect partial-cursor retention; fixed cursor discard
and cold retry boundary without pausing same-connection live effects. Native39
and SDK80/build/browser/static GO; renewed SPEC/QUALITY and local integration pending; admission OFF.
Full SQL/TTFT/relay/quota/STOP/capacity and joint Worker/browser gates remain OPEN
in the three focused follow-up plans. No push/deploy or business operations.

## Cloud admission bounded component accepted — 2026-10-13

Independent native review found fresh binding digest validation, superseded main
callback renewal and ancillary PublicExpression interleaving gaps. Shared repairs
validate both fresh and pinned Host authority, recognize only trusted ancillary
requests and reject new ordinary/unknown/forged/reused requests. Legacy omission
also survives generic Event normalization, retaining old Worker compatibility.
Configured261/no-skips76.92s including16native; make check GO2999/mypy1257/eval30.
Activation remains81SQL/call,0.3766/0.4024s;10/100frameSQL0, sample total530SQL.
Independent SPEC GO39/no-skips35.4s; QUALITY GO39/no-skips34.81s plus Writer26/no-skips6.48s.
Accepted bounded component for local commit/integration; no push/deploy or full GO.

## Cloud stream admission bounded component in review — 2026-10-12

CLOUD-STREAM-ADMISSION-01 freezes optional negotiated Run metadata in accepted
Events while requested capabilities remain fingerprinted intent. Actual cloud
Worker composition binds source open Turn, current Run/callback, full lease and
fresh persisted API-verified Host binding; mode is honored when new admission is
disabled or Redis is unavailable. Defaults off; no push/deploy or rollout GO.
Configured229/no-skips61.14s, final native9/no-skips19.67s, legacy core19pass;
static GO2999files/mypy1257/eval30. Independent spec then quality pending.
Native provider10/100frames0SQL; activation remains81SQL/call and0.3343/0.2890s.
These component samples do not establish total paired SQL or invocation TTFT SLO.
See docs/CLOUD_STREAM_ADMISSION_EVIDENCE.md; CLIENT/reliability/acceptance OPEN.

## Cloud stream admission prerequisite — 2026-10-12

WRITER bounded component0d49f0b0 integrated locally after renewed spec/quality GO;
primary29checks pass and42unrelated file hashes unchanged. Full product gates open.
CLOUD-STREAM-ADMISSION-01 claimed before coding in its isolated worktree: reuse
accepted-command Event plus indexed bounded source read; freeze negotiated mode,
compose actual Turn/Host-bound Worker. Default admission off; no push/deployment.

# Cloud stream writer component accepted — 2026-10-12

Bounded Redis temporary drafts and optional Worker callback composition implemented
on codex/cloud-stream-writer-01. Actual public-call hook follows durable model
request; source-qualified ordinary v2 deltas bypass PG while in-memory progress
and full response/publication gates remain. Legacy/coverage stay unchanged.
Native callback measures0SQL for10/100frames after activation. Configured179pass/no skips17.91s; static GO2991files/mypy1254/eval30. Synthetic
admission/Grant loaders prove the native seam, not signed Host negotiation.
Production factory stays None; actual admission/Turn/SDK/HTTP wiring and paired
performance/Host/browser acceptance remain open. Quality P1 delayed activation
is repaired with atomic lane revision CAS after the fresh resolver. Renewed
SPEC42/no skips6.75s and QUALITY54/no skips11.26s GO; bounded component
accepted for local integration, full activation/paired/aggregate GC remain open;
no push or deployment. Evidence: docs/CLOUD_STREAM_WRITER_EVIDENCE.md.

# Cloud stream bounded replay component review — 2026-10-12

READ-BOUNDS implements native count/UTF8 byte Session pages, metadata-only HTTP
stream admission, source-qualified Task/Segment/index/privacy preflight, scalar
namespace/status reads, and qualification before AG-UI page delivery. Local
default behavior remains unchanged; privacy is UNKNOWN until source-qualified.
Focused85pass11header-env-skips58.70s, configured native header/role12pass9.09s;
make check GO2988files/mypy1250/eval30. Independent quality P1 exposed unknown
prefix SSE admission; exact raw route-shape fix and signed unrelated Grant
regressions pass initial repair target50cases12.82s; complete configured
native/API/Host/header rerun107pass/no skips65.90s. Renewed reviews pending.
O(history) metadata SQL per page can mean O(history*pages) legacy replay; 2s
deadline and256Segment cap fail closed. Handoff scalar SQL requires payload
SELECT; historical bodies never hydrate in Python startup. Oversized raw pages
can fail after HTTP200 before frames. Full READ100subscriber/paired SQL/Host/browser
gates remain OPEN; v2 dormant, no integration/performance/push/deployment claim.
Evidence: docs/CLOUD_STREAM_READ_EVIDENCE.md.

# Cloud stream bounded-read followup — 2026-10-12

READ slice4a79a270 integrated locally after spec/quality review; postmerge42pass,
combined rebase64pass/staticGO. Full READ remains open. READ-BOUNDS Ready card
created and claimed before implementation; exact readonly COV source forwarding
and header/page handoff recorded. v2 remains dormant; no push or deployment.

# Cloud stream READ slice review — 2026-10-12

Session/Task readers drain again after observing terminal status, closing the
native empty-read/terminal-commit race. Redis canonical payloads only wake durable
replay; Task pages reuse existing count/byte bounds. AG-UI waits for a distinct
body-free checkpoint-ready notification published after the derived own commit.
Healthy empty blocking waits do not repeat SQL; reconciliation30s, degraded
exponential1–30s+jitter, grant/frame gates, local polling/conversation lifetime retained.
Native terminal2pass; focused39pass10environment-skips and35pass; latest live/Worker
17pass; subsequent native SQLite+PG consumer/ready46pass72.36s/no skips;
Qualityreview heartbeat/backoff P2 repaired:4deterministic cases, final target
38pass1native-env-skip10.04s; make check GO2981files/mypy1246/eval30.
Future-Task-cursor P2 repaired with grant-bound body-free highwater preflight400;
HTTPgrant/reader36pass8.39s and staticGO. Source frozen again for independent review.
Full READ remains OPEN: Session replay and privacy startup still hydrate unbounded
history, sync Redis readers share an executor capped at up to32threads, Redis pools
128 each. No100subscriber/nativeSQL reduction/Host/browser gate claim. Followup
must own bounded Session and source-proof privacy reads before full acceptance.
User integration target remains cloud-agent-trench; validated local integration
only, no push/deployment. Frozen baseline measurement checkout untouched.

# Cloud stream local integration — 2026-10-12

User selected cloud-agent-trench as dependency integration target and authorized
validated stages to integrate locally and unlock; no push or deployment.
Reviewed baseline instrumentation f16d8324 integrated with unrelated dirty files
preserved. Native runtime conformance remains failing due to terminal races;
frozen60s/3repeat measurement continues. CLOUD-STREAM-READ-01 claimed before
coding to fix shared reader correctness and polling costs.

Cloud stream typed contract (2026-10-12, CLOUD-STREAM-CONTRACT-01): locally accepted (d8e85614).
Dedicated core transient schema/Port and immutable Run mode/capability negotiation;
16KiB UTF-8 frame, 256KiB batch, scope/Grant/full LeaseFence/generation boundaries; ADR-024
supplement preserves canonical commit-before-publish and strict coverage privacy.
Deterministic contracts37pass for authorized draft policy; make check GO1249/eval30.
Independent spec/quality reviews GO; primary postmerge37pass.
No composition activates v2. Current delta precedes candidate/tool_loop classification;
User permits ordinary labelled candidate drafts; public-call wiring remains OPEN.
Native fencing/revocation, SDK replacement, SQL/RPO fault gates remain successor work.
User permits validated stage local cloud-agent-trench integration/unlock only;
no push/deploy. Long-window baseline and READ runtime terminal repair remain separate.

# Zebra Agent Project Status

Cloud stream/storage execution started (2026-10-12, CLOUD-STREAM-BASELINE-01):
Ready task claimed before coding on codex/cloud-stream-baseline-01, source5dfa824d.
Disposable labeled PG17.5/Redis8.2.1 provide isolated native measurement;
existing business containers/SDK dirty work unchanged. Baseline reader/publication/
progress compatibility72pass42.08s and native checkpoint31pass309.47s.
Frozen baseline45cells/4terminal gaps and scale18cells/6terminal gaps retained;
content/tool positions complete. Final-harness smoke3cells retains1Task terminal
gap; content complete, honest exit1. Profiler counter/report/cancellation/CLI
7checks pass3.59s; make check GO1246/eval30.
Independent spec and quality reviews GO for measurement code only. 60s/3repeat,
HTTPGrant/fullWorker/browser/v2 remain OPEN. No runtime correctness, SQL reduction,
successor completion, mainline integration or activation claim.

Cloud stream/storage roadmap (2026-10-12, CLOUD-STREAM-SPEC-01): user-requested
planning adoption and §20 SQL estimate recorded in docs/CLOUD_STREAM_STORAGE_REFACTOR_SPEC.md.
CLOUD-STREAM-BASELINE-01 Ready/not started; six dependent cards Locked.
Ordinary stream-heavy model expects80%–95% statement reduction; not measured.
Coverage6,411/15,653 and strict<=1000 remain separate open proof/authority work.
Three reader paths, v2 SDK/AG-UI, privacy/fencing, crash/GC and release gates retained.
Documentation only; no runtime implementation, migration or service activation.


Operator handoff (2026-10-12): user declined Baidu/API integration. Removed Baidu
from retained engines and shared v1/v2 query guidance; prepare-only, no service
restart, paid provider or credentials. Current config retains Bing/Sogou/360/WeChat.
V2 mixed-HTTP candidate compatibility remains OPEN independently of this handoff.

Domestic search follow-up (2026-10-12, WEB-SEARCH-CHINA-01): domestic native
engines and public WeChat selectors prepared, operator replacement pending.
Bing-cn remains default with zh-CN; Baidu/Sogou/360/WeChat remain independently
selectable, not default fan-out. Real native Sogou/360/WeChat returned7/4/9results;
Baidu CAPTCHA is not certified ready. Tool v1/v2 now explain native selection.
Affected1270pass12environment-skips69.57s and static gates GO. Legacy all four
usable routes pass HTTPS-to-evidence; v2 360/WeChat pass, but mixed HTTP URLs in
some Bing-Chinese/Sogou responses still trigger v2 invalid_search_response: OPEN.
No new dependency, CAPTCHA bypass, authority/SQL/final-gate weakening or restart.
See docs/CLOUD_WEB_SEARCH_REPAIR.md for scope, probes and manual replacement.

Search readiness follow-up (2026-10-12, WEB-SEARCH-READINESS-01): source/image
and temporary tool-chain acceptance GO; operator replacement/new conversation
pending. Affected1617pass12environment-skips87.88s; make check GO
(Ruff/mypy1246/eval30). Both real temporary v1/v2 HTTPS search-to-evidence
probes return ready=true/source_count5 for both queries. Operator live retest
confirmed current searchHTTP200/zero/CAPTCHA;
kept Bing inherited disabled=true. Corrected explicit Bing-cn configuration
returned real10/8candidates for both failing queries in an isolated same-image
instance. Sanitized failure metadata/native receipts and an actual Worker
search-to-evidence qualification probe are implemented. No running service
restart, original Task submission, SQL threshold or certification change.
New operator restart/probe instructions supersede the older handoff below.

Web search/delivery incident (2026-10-12, WEB-EGRESS-DELIVERY-01): source/image
repair GO; operator startup and real search/conversation replay pending.
Source96a817bc integrated locally into cloud-agent-trench; primary critical
46pass0skip2.20s; dirty/stash digests unchanged; no remote push or restart.
Affected cross-package1602pass12environment-skips92.09s; make check GO
(Ruff, mypy1245, eval30). Three arm64 images built and runtime module hashes
verified; new-image public HTTPS200/text probe GO. Live recovery301ee0ef is
blocked by a Markdown backtick URL
scanner false positive, not Worker startup. Search was unregistered because
endpoint configuration was missing/unforwarded; public DNS also returned
Fake-IP198.18/15. Source repair preserves exact citations and public-address
pinning and canonical search refs-to-ledger; independent TLS SearXNG
configuration/operator-only startup is prepared.
No service restart or original paid Task replay. See CLOUD_WEB_SEARCH_REPAIR.md.

Worker startup incident (2026-10-12, COV-POOL-STARTUP-01): source/image repair GO;
code21825082 fast-forwarded locally into cloud-agent-trench; operator live
replacement/replay pending. Primary postmerge critical12pass0skip6.53s and
make check GO2958/Ruff/mypy1243/eval30; original dirty-file/stash digests unchanged.
The operator restarted Pro API/Worker and applied schema99; session6721d0b0
failed before MODEL at runtime binding. A pooled readonly REPEATABLE READ
binding reader leaked client defaults into later Task INSERTs, including failure
finalization, causing one Worker restart. Shared pool reset now clears those
defaults with zero SQL, preserving the reader transaction and existing guards.
Separately, a cold connection/read took0.4587s versus a0.1s repair I/O budget;
maintenance now uses the existing bounded2s budget/128-row header batch and a
one-second discovery cooldown after failure. RED regressions reproduced both.
Native pooled Worker durably finalizes two sequential setup failures without a
restart. Full9041pass2685infra-skips0fail1113.41s; scratch native145pass10skip,
explicit projector68pass0skip; final critical/concurrency/tenant12pass0skip.
Sizes/Ruff/mypy1243/eval30 GO. Three arm64 images built; offline imports/catalog99
and both modified runtime module SHA256 values match. See
docs/CLOUD_WORKER_STARTUP_POOL_REPAIR.md for operator-only replacement commands.
No operator env/rollout/receipt changes, service restart or task resubmission.
This incident repair does not qualify the still-failing strict SQL gate below.

SQL operation-boundary repair (2026-10-12, COV-SQL-PHASE-01): **In Progress**.
User-authorized local integration into cloud-agent-trench completed at code
commit b40a38be as a manual-test candidate; no running-service activation.
Fresh pre-merge69 and hermetic primary post-merge40 pass; primary make check GO.
Arm64 migrate/API/Worker images built; offline imports/36-file source hashes GO.
Existing Flash runtime is not qualified strict-Pro coverage. User-selected
inactive compose.coverage-pro-test.yml aligns API/Worker Pro model descriptors;
base/operator env, gVisor, authority and rollouts stay unchanged. Migration,
replacement, native capability/admission and manual acceptance remain open.
Application image preparation and operator commands are documented in
docs/COV_SQL_MANUAL_TEST_20261012.md. Strict SQL gate remains FAIL.
Native authority observation no longer performs projection writes; bounded Task
repair/projection batches and additive99 preserve canonical source immutability.
Pure proof retention and complete-record payload reuse are scoped; both prepared
and locked physical reads retain fresh entry/exit guards. Unit reservation
counters no longer conflict with Harness attempt replay on normal short wakes.
Latest reviewed readonly/executor long6848 SQL38.5006s/short16292 SQL72.1584s,
both independently certify with zero exceptional full recoveries. **<=1000 FAIL**.
Pure native preparation qualified72/72 and dispatches no SQL/Host I/O; actual
I/O retains fresh entry/exit guards. Receipt and publication finalization now
share one owned transaction, with crash/revocation rollback and exact retry.
Private outer semantic formatting delegates to the same qualified native owner;
native90/90 qualify; final checkpoint-publication/preparation9 pass47.29s.
Independent final proofs own fresh bounded bytes, never incremental cache bytes;
exact native MODEL publication consumes its verified original acknowledgement.
Fresh single-SQL readonly authority observation and exact native executor pure
preparation follow-up pass authority/executor30 and final enhanced11 regressions.
Unknown/altered Host, transport, artifact, definition and authority delegates
retain guarded fallback; hostile properties are rejected before access.
Final critical publication/physical-I/O/proof80 pass81.57s after serial tests.
Unified evidence owner is now wired to native Worker checkpoint usage and unit
acceptance, with bounded full-metadata preparation, staged durable reservations,
outside-transaction object I/O and one atomic postupload settlement. Final
certification retains its independent originals. Post-review6411/15653SQL still
FAIL (1/2 and7/8 callbacks/batches; recovery0). Real Worker staged crash recovery
and missing/corrupt/STOP4 pass, without second MODEL; Host I/O no longer borrows
native settlement TX. Bounded pre-I/O legacy fallback retains full public proof.
Full checkpoint9036pass2680prerequisite-skips0fail; final tiny timeout and PG
trigger expectation changes have separate19/12 focused and independent1 GO.
This is not strict-SQL, live runtime, semantic or multi-tenant load acceptance.
Outer/kernel authority fanout remains; resets alone cannot meet the budget.
Borrowed write checks remain locked; final `_live` remains fully guarded.
The new non-mutating profiler
changes timing overhead; no direct end-to-end latency improvement is claimed.
Nested operation authorization and MODEL publication fanout remain the root;
do not describe these bounded improvements as a complete performance cure.
Native private publication now reads fresh stream authority without aggregate
replay; continuation/finalization still catch up the committed tail. Host I/O
exit now rechecks local revocation; lower6599/11067 interim counts precede this
necessary repair and cannot be presented as current acceptance.
Current static2920/1243/eval30 GO; full checkpoint9036pass2680skip0fail and
late-fix focused evidence are recorded separately. Borrowed native writes
suppress premature live hints; durable replay owns visibility. See
docs/COVERAGE_SQL_PHASE_EVIDENCE.md for current evidence and open gates.

Local branch reconciliation (2026-10-12, LOCAL-BRANCH-INTEGRATION-20261012):
the original 65 coverage fixture regressions are repaired; coverage full suite
6998 passed / 2033 infrastructure skips. Combined-source repairs preserve
bounded progressive delivery, checkpoint privacy, native Task61 authority locks,
deadline/connection ownership and immutable MODEL source proofs. Additive
migrations 95/96/97/98 retain historical checksums; no business migration ran.
Native authority80/storage65/privacy13 and Worker dispatch17 pass. Combined
full-source validation passes9011/2511-prerequisite-skips; checkpoint compatibility, exclusive
source-owned work routing and scalar-header query cost focused gates pass.
Staged static gate passes2920-size/1231-typed/eval30; Zebra target integration
is locally merged into cloud-agent-trench at0c78c9b2. Independent primary SDK/
AGENTS edits remain uncommitted and byte-identical; old checkouts stay detached.
Trench is locally integrated into main with full check/build and native70 GO.
The existing strict nine SQL<=1000 gate remains FAIL at10497 client calls;
receipts OFF, runtime/fleet/semantic acceptance OPEN. No push or service restart.
See docs/LOCAL_BRANCH_INTEGRATION_20261012.md for the current evidence boundary.

MODEL settlement boundary continuation (2026-10-11, isolated COV-EXEC-01):
optional atomic original acknowledgement, own-TX result escape guard, existing
override compatibility and uncached complete lifecycle/Event exit comparison
implemented. Review rejected skipping the post-callback original reread; retained
it and independent final originals. Native first/replay/fault10 and pure155 pass,
static1115/eval30 GO. Serial nine certifies16.1541s10497client15637server237GET/
4callbacks/5batches; **SQL<=1000 STILL FAIL**, no SQL/p95 benefit claim. Previous
10485/225GET baseline retained; current counts increased12. Normal execution has
zero exceptional recovery, but guard/adapter-entry fanout still dominates.
Full root cure/immutable-retention/fleet/live remain OPEN, receipts OFF; services
untouched, no integration/commit/push. See docs/COVERAGE_MODEL_SETTLEMENT_EVIDENCE.md.

Shared consumer read-phase continuation (2026-10-11, isolated COV-EXEC-01):
common snapshot/MODEL/publication readback loader reuses bounded readonly scope;
exact entry/exit metadata/authority and missing-ID checks before result escape.
Already-owned/custom proof retains guarded fallback/locks; bulk metadata matches
configured deployment before SQL. Only exact native clocks use single incremental
boundary guard; injected clock callbacks keep post-callback validation.
Focused160 passed before final namespace/fallback review fixes; final48 scoped/
guarded fault, owned compatibility, tenant isolation and callback regressions pass.
Final critical native85 pass172.48s; local compatibility199 pass3.30s; static1114/
eval30/actual2612-size/diff GO. Full serial nine independently certifies17.5762s
10485client15619server225GET/4callbacks/5batches. **SQL<=1000 STILL FAIL**;
1127lease pins/877lineage reads/1419resets remain. No latency/SLO claim.
Whole root cure, immutable-retention final unlock, history/fleet/live acceptance
remain OPEN. Runtime receipts OFF; no business activation/integration/push.

Exact-owner native operation continuation (2026-10-11, isolated COV-EXEC-01):
existing work-unit supports exact transaction/deadline borrower reentry, refuses
independent same-DSN owners, poisons caught nested failures and retains cleanup.
MODEL budget, batch acceptance/final certification and Worker local authority
compose their native transactions; all fresh post-lock/Host/STOP/lease checks and
independent final originals remain. No permission caching or reset suppression.
Native smoke51 and boundary60+corrected operation2 pass; expanded56 passed before
deadline correction. Review found older nested wrappers could widen SQL timeout;
shared minimum-deadline propagation fixed, native/recovery/report/API51 pass.
Final source strict nine independently certifies23.4505s12180client18052server
248GET/5callbacks/6batches,
one initialization replay/zero exceptional recovery. **SQL<=1000 STILL FAIL**.
Prior10922/five-batch and10806/four-batch runs retained, no fixed-batch speed claim.
Guarded adapter-entry
fanout still dominates; transaction sharing is not the full root cure. Existing
final external proof under locks, immutable retention, history/fleet load/fairness
and live acceptance remain OPEN. Runtime receipts OFF; primary/business services
untouched. Exact results and failed-meter boundaries in batch evidence document.

Execution-context/canonical finalization continuation (2026-10-11, isolated
COV-EXEC-01 source): native set-based canonical Event/lifecycle/audit commits,
bounded readonly execution metadata entry/exit and same-transaction exact proof
pages are implemented. Publication1/9 objects has reserve6/receipt8/finalize8
queries; readonly scope6/6, locked lifecycle+Event proof2/2 queries. Object I/O
outside execution read transactions, exact post-read metadata, fresh authority,
scope invalidation, per-object Event hashes and independent final proof retained.
Migration94 adds URI/Event proof index path; 5000-row actual EXPLAIN uses URI and
Event-ID indexes with no Seq Scan. Fleet qualification updated. Native execution/
batch/bootstrap/MODEL76 pass, proof/fault74 pass, index/fleet37 pass; static1114/
eval30/actual2610-size/diff GO. Final-source strict nine completes certification
in16.0781s with10806client/16273server/218GET/4callbacks/4qualified batches,
one initialization replay and zero exceptional recovery. **SQL<=1000 STILL FAIL**.
Compared with prior same-nine/four-callback/four-batch sealed run18.2650s12916,
observed fewer calls2110 and2.187s; single controlled runs are not p95/SLO proof.
Authority991/lease1234/reset1605/timeout514 calls expose remaining Worker-wide
authority/transaction fanout. Full plan In Progress: current phase authority,
immutable-retention short final proof, history/fleet quota/fairness/load/live
remain OPEN. Runtime receipts OFF; primary/running business services untouched.
Exact evidence: docs/COVERAGE_BATCH_TRANSACTION_EVIDENCE.md.

Governed Artifact batch follow-up (2026-10-11, isolated COV-EXEC-01 source):
optional immutable batch Port/executor, <=1000 objects/32MiB; bounded buffered
observations/results, immediate MODEL checkpoint/usage. Native set reservation
and receipt settlement, physical I/O outside transactions, atomic finalization
with post-callback whole-batch/Event revalidation. Ordered insert races roll back
the delta and require fresh-fence exact retry; replacement/crash replay preserves
one HTTP and exact charges. Fleet qualification updated; locked readers refuse
batch writes. Native124+MODEL23+buffer replay2 pass; pure88 pass8 native skips;
current Ruff/Mypy1110/eval30/actual2604-size/diff GO. Strict nine source repeat
19.6260s11772client17472server225GET/4callbacks/5qualified batches: SQL<=1000
STILL FAIL, latency not improved. Earlier batch measurements retained; do not
confuse callback/batch count changes with fixed-workload speed gains. Per-object
Event/finalization SQL, metadata/read authority fanout, final proof under locks,
history/fleet quotas/load/live closure remain open. Full plan In Progress,
receipts OFF; no runtime restart/activation/migration/integration/commit/push.
See docs/COVERAGE_BATCH_TRANSACTION_EVIDENCE.md for complete evidence boundaries.

Exact membership/record seal follow-up (2026-10-11, isolated COV-EXEC-01 source):
migration93 seals ordered exact unit keys and record/part metadata at validated
first bind. Native unique Event-backed MODEL part settlement advances the root;
unsupported mutations invalidate, legacy/rebuild cannot self-requalify. Qualified
normal final_certification commits read only <=1000 selected records, never parse
the full original manifest or upload all expected keys. Independent final original
verification still refuses corruption, including after incremental retry. Fleet
qualification rejects indexed-only consumers. Native current44+expanded19 passed;
pure65 pass20 native-gated skips; static1108/eval30/actual2600 size/diff GO.
Full SQL goal STILL FAIL: serial nine18.2650s12916client19132server218GET,
four callbacks/four qualified batches/root4/4/one init/zero recovery. First current
21.3039s14371calls242GET/five callbacks retained. Prior same-four-callback12912:
selected records add4 queries, not overall saving. No p95 improvement claimed.
Exclusive counts identify Artifact read/publication5019 and outer
handoff/authority3545, versus434 batch-commit calls. Next root work is governed
lifecycle batch transactions, not more membership indexes or permission caches.
Executor/history growth, immutable-retention-backed short final proof, shared
tenant capacity/fairness and live/load closure remain OPEN. Task In Progress;
runtime receipts OFF; no primary edits/business migration/restart/merge/push.
See docs/COVERAGE_BATCH_TRANSACTION_EVIDENCE.md for exact scope and failed gate.
Expanded native94 pass11 fixture failures retained; corrected membership19 and
recovery/query/current consumer46 pass cover all eleven without relaxed guards.

Batch transaction root follow-up (2026-10-11, isolated COV-EXEC-01 source):
bounded exact unit acceptance, pure operation authority/lifecycle pins, owner-TX
borrowing and verified-reader reuse implemented. Native volume91 and lookup92
migrations added; new fleet identity rejects older partial consumers. Independent
final original proof, public fresh authority and charge/crash rules retained.
Full client and nested server SQL measured without changing the execution boundary.
Latest nine certified18.0889s/12912client/18823server/218GET/four batches,
one initialization replay/zero exceptional recovery. Strict <=1000 SQL gate FAIL;
full root cure NOT complete. Native MODEL30/readiness55/growth-final-boundaries10
and pure143 pass; static1106-source/eval30/actual2597 size GO.
Still OPEN: sealed exact membership (normal all-key predicate remains), governed
Artifact lifecycle batches, external final proof outside native locks with immutable
retention guarantee, shared tenant quotas/backpressure/fairness and live p95/Trench.
Task In Progress; runtime receipts OFF; no primary/business migration/restart/
activation/commit/merge/push. Exact evidence and strict command:
docs/COVERAGE_BATCH_TRANSACTION_EVIDENCE.md. Historical observations follow.

Versioned execution authority (2026-10-11, isolated COV-EXEC-01 source):
migration90 maintains native monotonic Session/root lineage versions. One cold
independent proof qualifies a wake; subsequent guards freshly check indexed
current authority rather than traverse full Task history. Lease pin then new
post-lock SQL snapshot remains two statements (race regression); read-only
continuation shares only exact current wake context and cannot grant mutations.
Exceptional recovery/final certification remain independent. Shared write
authority consolidates reads; explicit short read work units and bounded256/
32MiB incremental verified bytes reduce duplicate connection/object work.
Strict missing-consumer preflight refuses before proof I/O; final atomic admission
is unchanged. Fleet digest binds authority/90; no production activation.
Serial nine: certified30.5219s20403execute/287GET/7wakes/18qualified/zero
exceptional recovery/two MODEL initialization replays. Service reads7, total
native validations20 (service7/dispatch7/handoff6), not just service-loader reads.
Earlier serial27.9448s19303execute/6wakes also passes; not a fixed-wake latency
comparison. Prior v89:56.0948s49137execute/518GET/10wakes. Native expanded51
and latest read-unit3 pass; pure readers55 pass, static/actual2586-size/diff GO.
Observed savings are controlled component evidence, not p95/fleet/live SLO.
Per-Artifact fresh authority/lifecycle fanout, final locked external I/O, MODEL
volume/membership and tenant/fleet/live acceptance remain OPEN. Task In Progress;
receipts OFF; no primary edit, business migration/restart/commit/merge/push.
Exact scope, counter correction and remaining work:
docs/COVERAGE_EXECUTION_CONTEXT_EVIDENCE.md.

Native Task admission proof (2026-10-11, isolated source): migration89 maintains
exact Session continuity and strict Task origin inside native Event writes.
Normal final_certification policy uses one indexed origin proof plus freshly
read latest binding; changed history/legacy falls back, final/recovery remains
full. Same-phase policy is forwarded to preflight; no authority cache. Capability
digest binds Task-summary/89. Native MODEL54/Worker-fleet82/root8/renewal1 and
pure66 pass; serial nine certified56.0948s/49137execute/2413bindings/518GET passed.
Same-callback v88 had52.1281s/49237execute:100 fewer executes, no latency gain.
Static1098-source/eval30, actual2578
size/diff GO. Remaining per-Artifact authority fanout,
MODEL volume/membership, short transactions and tenant/fleet/live SLO OPEN.
Production receipts OFF, no activation/restart/merge/push. Exact acceptance:
docs/COVERAGE_TASK_ADMISSION_EVIDENCE.md.

Exact incremental MODEL facts (2026-10-11, isolated source): migration88
maintains scoped budget/source/witness facts in the native write transaction.
Actual final_certification normal budget reads use one indexed summary proof;
eager/legacy/invalidated roots retain independent scans, and final publication
certification still replays originals. Unsupported mutations invalidate roots;
projection repair cannot requalify them. Fleet digest now binds summary/88.
Native MODEL48 pass228.11s and Worker/fleet82 pass225.65s, zero skips;
new summary5 pass10.74s, pure105 pass with4 environment-gated native skips.
make check1096-source/eval30 GO; actual2575 size and diff checks GO.
Serial nine1 pass58.12s: certified52.1281s/49237execute/2413bindings/518GET,
10callbacks/18qualified/zero full recovery/independent final certification.
Prior same-callback50.4048s/49375execute:138 fewer executes, no latency gain.
This is not whole-invocation constant work; trigger-internal SQL is not counted.
Task/Host authority fanout, legacy requalification, short transactions and
tenant/fleet/live SLO acceptance remain OPEN. Production receipts OFF;
no primary edit, business migration, restart, activation, commit/merge/push.

Revision-bound receipt mint (2026-10-11, isolated source): exact native commit
verification remains; v87-bound mint/read no longer computes historical MODEL
fingerprints. Legacy fallback and root-missing refusal retained. Fleet qualification
digest binds the revision contract, separating older fingerprint-only consumers.
Native receipt/root matrix15 pass121.08s; serial nine1 pass55.64s, completion
50.4048s/49375execute/518GET/10callbacks/18qualified/zero recovery/finalcert.
Previous53.5462s/49393execute has equal callbacks/GET:18 mint scans removed,
not a stable latency/SLO claim. Budget/index/policy historical scans, authority
fanout, short transactions and tenant/fleet/live acceptance remain OPEN.
Final readiness/continuation/native fleet races69 pass122.37s/zero skips;
make check1094-source GO, actual2572 file-size and diff checks GO.
Production receipts OFF; no primary edits/migration/restart/merge/push.

MODEL revision root (2026-10-11, isolated source): migration87 adds guarded
transactional mutation generation/revision for all MODEL Events/witnesses/calls/
ledger. Normal new receipt reads bind that version instead of scanning history;
legacy receipts retain exact fingerprint fallback, full native mint proof and
independent certification unchanged. Mutation rollback/isolation, prepared-read
invalidation and new/legacy receipt paths: native14 passed113.40s; initialization4
passed earlier. Pure161 passed; static1094 sources GO. Nine workload1 passed:
53.5462s/49393execute/518GET/10callbacks/18qualified/zero recovery/finalcert.
Prior49.2905s used9callbacks; no new latency/query-count gain claimed. The gain
is bounded native receipt-read history complexity, with trigger write overhead.
This is a bounded receipt-read root, NOT complete incremental budget/authority:
full mint/index/policy scans, authority fanout, short transactions and tenant/fleet
gates remain OPEN. No production migration/activation/restart/merge/push.

Delta MODEL transcript and admitted boundaries (2026-10-11, isolated source):
normal incremental commits replay only current records with verified native
global budget/index integrity; exact manifest keys determine remaining work.
Short MODEL/index pages avoid redundant empty reads. Only matching actual native
final_certification admission defers historical boundary physical rereads after
initial manifest/policy verification; fresh authority/original expiry retained.
Eager/full recovery/independent final certification remain full proof.
Native4 pass73.54s (including unrelated corrupt-object final refusal); pure148
pass2.88s. Latest native nine workload passed:49.2905s/47599execute/508GET,
2331bindings,18qualified/zero exceptional recovery/independent final cert.
Prior control60.2254s/56639execute/745GET; callbacks10->9, not fixed-callback
causal timing, p95/SLO or live acceptance. Structural roots NOT COMPLETE:
sealed MODEL state/CAS, authority versions, history scans, short transactions,
Worker fleet cutover and tenant/concurrency gates. Production receipts OFF;
no primary edits, activation/restart/migration/commit/merge/push.
See docs/COVERAGE_BINDING_READ_EVIDENCE.md for exact evidence and remaining plan.

Same-read MODEL metadata (2026-10-11, isolated source): shared Artifact loader
returns verified metadata with bytes; MODEL uses that retention and known frozen
digests avoid a redundant preliminary getter. No body/permission cache; fresh
pre/post authority, full metadata/bytes and original deadlines retained.
Integration223/native26 pass, scoped source GO, make check/actual2565 size GO.
Native2s nine pair:65039->56607execute,3394->2867bindings,745GET unchanged,
70.7937->59.9912s observed. Native60s pair:47699->40307execute,2571->2109bindings,
645GET unchanged,49.4899->41.0434s observed. Both pairs preserve18qualified,
zero exceptional recovery and independent final cert. Single pairs not p95/SLO.
Still OPEN: commit MODEL replay, authority fanout, bounded historical fingerprint
cost and real tenant/fleet/live acceptance. Production receipts OFF unchanged;
no activation/restart/commit/merge/push. See COVERAGE_BINDING_READ_EVIDENCE.md.

Receipt-backed MODEL initialization (2026-10-11, isolated source): qualified
unchanged atomic roots reuse budget policy, preserving fresh native source,
Task/fence/STOP, pre/post authority and original expiry. Legacy/new MODEL tails
use full replay; corrupt eligible roots refuse. Independent final cert unchanged.
Native14 pass137.72s, pure13 pass, scoped review GO, make check GO/actual2565 size
GO. Actual2s nine serial2 pass149.83s: full replays20->2, execute67979->65039,
GET835->745, observed73.4938->67.1875s; both10callbacks18qualified0recovery/finalcert.
Single pair not SLO. Diagnostic60s single callback avoids no replay, adds30 SQL;
no speedup claim. Remaining authority fanout/commit replay/native fingerprint,
large tenant/fleet/live acceptance OPEN. Production receipts remain OFF; no
activation/restart/migration/commit/merge/push. See COVERAGE_BINDING_READ_EVIDENCE.md.
Hardened qualified2s rerun1 pass74.13s: same65039SQL/745GET/two full replays,
68.6504s measured completion; final focused47 and make check GO.

Incremental accepted-batch routing (2026-10-11, isolated source): validated
commits atomically emit optional bounded record membership; final_certification
merges replay related batches only. Legacy/oversized hints use full scan; selected
canonical membership and independent full certification remain mandatory.
Native initial13 pass, final guards4/hardened5 pass (zero skips), deterministic27
and oversized1 pass; fixed stale short-page count assertions. Scoped review GO,
make check GO, actual tracked+untracked2563 size GO. Same native diagnostic nine
serial2 pass99.73s:49829->47669execute,717->645GET,46.3997->45.1373s observed,
18qualified/zero recovery/finalcert retained. SQL4.3% reduction; not p95/SLO.
Fresh authority fanout and full MODEL transcript replay remain OPEN, plus native
2s scoped timing, large tenant load/fleet/live acceptance. No runtime activation,
restart, migration, merge or push. See COVERAGE_BINDING_READ_EVIDENCE.md.

Shared verified Artifact load (2026-10-11, isolated source): reused existing
VerifiedArtifactPayloadReaderPort in integrations loader; full metadata + byte
checks and fresh pre/post-I/O authority preserved, legacy fallback unchanged.
Integration46 + snapshot3 and native15 passed; source review GO, make check GO.
Native-binding diagnostic60s nine serial2 pass100.12s: legacy50.1475s54181execute
versus verified41.3743s49829execute; binding reads2985->2713, GET717 unchanged,
18qualified receipts/zero recovery/independent final cert retained. Single pair,
not p95/SLO; static checks briefly concurrent. SQL/time goals still unmet; native
MODEL replay and authority fanout remain open. No activation/restart/merge/push.
Native2s hardened1 pass68.45s: completion63.7075s/70139execute/3680binding reads/
907GET/10callbacks; 18qualified/zero exceptional recovery/finalcert retained.
Native versus older fixture2s metrics are not a before/after pair.

Fresh native binding consolidation (2026-10-11): root identity + latest binding
share one fresh RR query; full native lineage and all Worker guards retained.
Root business SQL3->2, no authority cache. Initial storage/Worker10 and hardened
storage12 passed, zero skips; make check sizes2382/Ruff/Mypy1092/eval30 GO.
Nine diagnostic60s serial2 pass96.06s: fixed callback35.4825s/45226execute versus
native loader51.4186s/54181execute/2985binding reads. Different compositions, not
a before/after speedup; original frozen9 fixed callback excluded this cost.
18 qualified receipts/zero recovery/final cert retained. Fanout and commit replay
remain open; no activation/restart/merge/push. See COVERAGE_BINDING_READ_EVIDENCE.md.

Atomic continuation frozen workload comparison (2026-10-11): native controlled9
records/117bytes/18 units, serial4 cases passed205.97s, zero skips. Default2s
off66.6344s/75984execute/1997GET/27full-recovery versus qualified fixture50.5764s/
63584execute/907GET/0full-recovery (both10callbacks). Diagnostic60s remains
34.7905s/45226execute/717GET despite zero recovery. SQL/time SLO not met;
shared Artifact/authority fanout and commit MODEL history replay remain root work.
Hardened qualified rerun1 passed67.92s:18qualifiedreceipts/zero recovery,
62.3807s/65682execute/929GET/11callbacks; retain slower observation. Production OFF;
no live activation, migration/restart, merge/push or p95 claim.

Continuation duplicate pickup repair (2026-10-11, isolated source): reproduced
same-generation redelivery incorrectly returning REQUIRES_RECONCILIATION because
predecessor proof validation ran before native receipt idempotency. Shared locked
handoff now checks duplicate identity first and returns no lease; pickup preparation
reuses its approval query joined to the native receipt to avoid duplicate proof
reconstruction. Approval creation and exceptional recovery remain unchanged.
Added marked STOP/approval mutation refusal and post-write crash rollback/retry,
duplicate/no-new-MODEL and independent full certification assertions. Source review
GO; native suite37 passed/1 test import failure128.85s, corrected crash/certification
case passed12.44s (zero skips); sibling multipart/crash/tamper10 passed155.32s,
zero skips. make check passed.
Production minting OFF;
no runtime migration/restart, merge/push or workload latency acceptance.

Continuation qualification concurrency acceptance (2026-10-11, isolated source):
native PG blocking-pid tests assert pin serializes with revocation/epoch changes;
post-pin/write expiry must roll back, never pass by failing early. Actual marked
normal preparation-to-pickup transitions require the injection to run and return
protocol1 proof; refused pickup preserves lease/pending/receipt/Inbox/outbox/Event
snapshots and adds zero historical object reads. Source reviewer GO. Final hardened
17 plus84-to85 upgrade2 passed111.63s, zero skips. make check
sizes2382/Ruff/Mypy1092/eval30 passed. Fixed historical upgrade
fixture catalog bounds for specific84-to85 evidence after86 introduction.
Remaining: complete concurrent crash/STOP/source-race matrix, coordinated fleet
rollover, historical SQL scan cost and nine-record/mixed-tenant load acceptance.
Production minting OFF; no runtime migration/restart, merge/push or latency claim.

Native continuation fleet qualification (2026-10-11, isolated source only):
migration86 adds optional qualified continuation digest to existing v3 process
registration. Actual native Worker/preparer/deriver publishes it on registration
and heartbeat; upgrades/downgrades of a live or expired replacement registration
refuse. Marked normal pickup reuses the requirement query to read current native
approval and pins the extension on the actual attested process. Unmarked legacy
tasks and STOP retain existing routing. Coordinated schema/binary upgrade is
required: old85 binaries reject86, despite unchanged v3 task contract. Source
review GO; make check sizes2382/Ruff/Mypy1092/eval30 pass. Corrected native final
regression92 passed108.63s, zero skips; earlier91/1 stale assertion is superseded.
Production minting OFF. Rollover/concurrent fault acceptance, native history-scan
cost and nine-record/mixed-tenant load remain OPEN. No runtime migration/restart,
primary edit, merge/push, live semantic accuracy or latency/SLO acceptance claim.

Native continuation producer qualification (2026-10-11, isolated source only):
successful commit verification now carries the exact native facade/deriver
qualification into minting. A configured marker alone, arbitrary wrapper or
subclass cannot mint a qualified root; mismatch returns before receipt SQL.
Separate pure continuation digest requires native preparer/method and actual
dispatch deriver, while deployed v3 registration/admission remains unchanged.
Native continuation/readiness42 passed86.77s, zero skips, including arbitrary
callback legacy fallback, exceptional full recovery, current Host revocation
and repeated normal pickup through final certification. Host/model/S3 are
explicit synthetic transports; PG/Worker path is actual. Scoped source review GO;
make check sizes2382/Ruff/Mypy1091/eval30 passed. Debugger tracing hardened the
shared verifier boundary rather than per-caller checks. Production minting OFF.
Still OPEN: versioned fleet admission/registration/pickup wiring and rollover,
concurrent fault/race acceptance, native history scan cost and nine-record real
load acceptance. No restart, activation, primary edit, merge/push or SLO claim.

Native normal continuation preparation/pickup (2026-10-11, source only): shared
authority/STOP/fenced-tail gates retained; eligible receipt avoids historical
object reconstruction and full MODEL recovery. Native protocol approval is
persisted atomically and selected before pickup preparation; unsupported marked
consumers refuse. Commit-verifier remaining-part predicate preserves full-C
budget gates; missing/insufficient proof retains exact recovery. Native normal/
preparation38 pass44.80s, zero skips, including repeated pickup through independent
final certification; each pickup adds zero object reads. Budget/routing focused
8 pass1.63s; native Host revocation1 pass10.55s refuses pickup without a new lease
or object reads. Receipt regression39 passed in an earlier combined run with one
test-loop bound failure, subsequently corrected in the final38 run. Scoped
source review GO; Ruff/Mypy1091/size2382/eval30 pass. Debugger tracing drove shared
boundary changes. Production minting remains OFF: executable verifier/capability
qualification, fault/race expansion and nine-record real load acceptance OPEN.
No restart, primary checkout change, merge/push or latency/SLO claim.

Atomic continuation reader/preparation intent (2026-10-11, source only): bounded
native receipt/source/predecessor validation, original deadline checked after
MODEL fingerprint, source-seal version/checksum and settled budget enforced.
Restricted SELECT-only snapshot supported; no historical object reads. Normal
approval can select an explicitly composed continuation preparer; corrupt marked
preparation refuses without downgrade. Native receipt/preparation38 pass108.30s;
Hardened predecessor/expiry2 pass23.30s, zero skips. Ruff/Mypy1090/size2382/eval30
pass. Source-only scoped review GO. Worker remains
off: qualified normal preparer, atomic protocol approval and pickup are OPEN.
No performance, activation, merge/push or live acceptance claim.

Atomic continuation source-retention follow-up (2026-10-10, source only):
migration85 seals exact native accepted Events referenced by execution receipts.
Same-TX no-op row-version writes serialize stale RR/concurrent mutation without
changing Event JSON or rebuilding independent MODEL witnesses. Referenced source
UPDATE/DELETE/TRUNCATE refuses; rollback remains atomic. Revised source review GO.
Native source/receipt19 passed146.53s; routing/capability still OPEN.
Ruff/Mypy1089/size/eval30 pass; default6915 pass/1598 prerequisites125.90s.
Current Worker remains default-off; no normal-recovery or performance claim.

Atomic continuation (2026-10-10, isolated source only, IN PROGRESS): migration84
and commit-transaction execution witnesses implemented. Native accepted Event,
predecessor, full binding/command/fence, verified budget and scoped MODEL-source
fingerprint are pinned; retries never add counts. Append-only UPDATE/DELETE/
TRUNCATE guard; capacity skips minting without rejecting legal acceptance.
Legacy prefixes are not backfilled. Source review scoped GO.
Receipt minting is opt-in at trusted store composition; current Worker keeps it
off, with no extra receipt/fingerprint queries on its production path. Normal
approval/pickup still run full recovery: verifier/capability qualification,
fast-path routing and race/load acceptance remain OPEN. No latency or
query improvement claim, no deployment/merge/push. See docs/COVERAGE_ATOMIC_CONTINUATION.md.
Hardened native9 pass89.86s, prior receipt/acceptance45 pass659.38s; final default
6915 pass/1588 prerequisites117.34s. Ruff/Mypy1088/size/eval30 pass. Last
receipt-only policy/deadline-inheritance guards: native9 pass95.19s, source GO.

Recovery bounded-query follow-up (2026-10-10, isolated source only): coalesced
native history and unit volume/row pairs from4 SELECTs to2; scoped full count/byte
bounds, oversized body suppression and canonical digest retained. SELECT-only RR
adapter unchanged; actual native revalidation detects same-count/same-byte tamper.
Native selection57 pass16.72s, crash/no-progress/approval tamper7 pass75.66s,
hardened exact-bounds10 pass1.94s. Frozen nine default70.68s/75772SQL/1987GET/
10callbacks; diagnostic33.17s/45010SQL/717GET/onecallback. Single observations,
not SLO; normal continuation still29 proof preparations and6600 public getters.
Full default6915 pass/1579 prerequisites130.14s; Ruff/Mypy1086/size2382/eval30 GO.
No activation, merge/push, capacity/semantic acceptance or whole-plan completion.

Final lifecycle scoped-read follow-up (2026-10-10, isolated source only): reused
existing locked proof reader only for exact pure semantic deriver, within each
complete lifecycle. Budget/source/aggregate proof remain full, byte caches remain
independent, post-append/retry/cross-TX scopes fresh. Unknown derivers retain public
reads. Entry/exit/physical pre/post authority, native pins, fresh expiry and capacity
fallback preserved. Source review GO; focused68 pass0.29s. Initial native54 pass/
zero skips136.65s; stronger post-append injection assertions added after test review,
native hardened3 pass54.47s. Frozen load2 pass119.14s: default72.87s/76349SQL/2017GET/10callbacks;
diagnostic37.46s/45010SQL/717GET/onecallback, down from54282SQL/49.27s with equal
GET/callback counts. Single controlled samples, not p95 or live acceptance. Full
default6913 pass/1571 prerequisite skips126.87s; Ruff/Mypy1086/size2382/eval30 pass.
Authority/recovery fanout, connection capacity/fairness still OPEN.
No primary checkout/runtime replacement, merge/push or whole-plan completion.

Generation-audit follow-up (2026-10-10, isolated source only): bounded history
count/bytes and rows in one native query; all historical accepted-prefix counts
in one ordered scan. Shared approval/handoff audit now uses1 query with no prefixes,
2 otherwise;0/1/6/64/1000-generation regressions, exact native scope/inclusive/fresh
prefix tests. Focused44 pass/8 prerequisites; native52 pass/zero skips71.78s.
Source reviewer GO. Frozen load2 pass136.33s: default78.70s/85170SQL/1987GET/
10callbacks; one-callback diagnostic49.27s/54282SQL/717GET. Single observations,
not p95; continuation audit improvement does not solve principal authority/recovery
fanout. Ruff/Mypy1086/size2382/eval30 pass; full default6903 pass/1568 prerequisite
skips125.58s, `/tmp/cov-generation-audit-default-20261010.xml`. No migration,
authority weakening, activation, merge/push or whole-plan completion.

Native BEGIN / short-page follow-up (2026-10-10, isolated source only): binding
reads configure existing psycopg RR/read-only BEGIN methods before first query,
including deadline/borrow wrappers; no separate SET TRANSACTION. Short canonical
batch pages finish without another empty query; exact full pages still probe next.
Focused17 pass/6 prerequisites; real PG binding/reset13 pass7.92s. Native load2
pass139.20s: default81.35s/85643SQL/2007GET/10callbacks; diagnostic49.19s/54282SQL/
717GET/onecallback. Single observations, no latency gain. This workload uses a
fixed binding loader and does not measure native binding-BEGIN savings; that path
has independent native transaction/reset tests. Ruff/Mypy1086/size2382/eval30 pass.
Default6890 pass/1567 skips with one unrelated SIGKILL PermissionError; isolated
runtime14 pass1.24s. Full rerun6891 pass/1567 prerequisites119.62s; first failed
gate evidence is preserved. Supplemental verifier/reader35 pass0.21s.
Normal continuation and authority fanout remain the principal unresolved work;
no SLO, multi-tenant/live acceptance, merge or activation claim.

Proof-read/final-phase follow-up (2026-10-10, isolated source only): private
locked commit reader keeps entry/exit and physical pre/post authority; the known
pure semantic deriver reuses full records pinned FOR UPDATE, with fresh expiry
and guarded capacity fallback. Other derivers keep native rereads. All verified
proof bodies share an invocation-local 32 MiB cache, never across final phases.
Final lifecycle proof now reuses one complete verifier for source and aggregate
checks; post-append/retry/cross-transaction checks still create fresh proof.
Focused reader/verifier checks pass; final default6886 pass/1565 prerequisites
123.42s and native publication54 pass/zero skips182.76s. Ruff/Mypy1086/size2382/
eval30 pass. Frozen-source native load2 pass134.86s: default81.08s/85685SQL/
2007GET/10callbacks; diagnostic43.73s/54293SQL/717GET/onecallback. Single samples,
not p95. All test processes ended. One residual scratch fixture schema is retained
because its ownership is not established; no database cleanup was performed.
The intermediate body-cache diagnostic was56.13s/60593SQL/855GET (single sample,
concurrent default tests, not latency acceptance). Whole plan still OPEN:
normal continuation, indexed incremental membership, authority fanout, bounded
connection/fairness capacity and mixed-tenant/live/UI gates are not completed.
No merge, push, primary checkout edit or runtime replacement.

Locked-policy SQL follow-up (2026-10-10, isolated source only): one native policy
per constructor/replay/scoped-preflight chain, rather than repeated Task/history
reads; standalone calls and each new phase remain fresh. Combined stream/history
witness in one statement, conflicting commit retries reject before MODEL proof.
Work-load counters now freeze at the same certified-completion boundary.
Focused55 and wider109 passed/55 prerequisite skips; scoped Ruff/Mypy4 passed.
Native nine incremental default89.98s/98485SQL/11callbacks; diagnostic56.55s/
63005SQL/onecallback (single samples, not p95). Getter authority fanout dominates;
default SQL counts worsened as callbacks increased. Overall performance remains
OPEN; no full-plan, SLO, mixed-tenant, live/UI, merge or runtime activation GO.
Final default6864 passed/1565 prerequisites129.15s; native selected safety6
passed116.12s. Ruff/Mypy1085/size2382/eval30 pass. See work-slice evidence.

Demand-driven SQL follow-up (2026-10-10, isolated source only): original/model
pages stop at their proven upper sequence, removing one terminal empty query per
completed bounded scan. Unbounded index and equal-sequence multi-Session scans
retain their existing completeness checks. Conflicting original Task descriptors
reject before stream/history/binding SQL. Lazy page fetch and recovery read
witnesses remain. Focused regression106 passed0.71s; scoped Ruff/diff checks pass.
No new full-load timing or SQL SLO claim; authority fanout, normal continuation,
connection reset and independent final certification optimization remain OPEN.
No commit, merge, runtime replacement or activation.

Checkpoint query coalescing follow-up (2026-10-10, source only): shared verified
Artifact read returns metadata and bytes; checkpoint verification reuses it after
native canonical/lifecycle pin instead of issuing a redundant lifecycle getter.
Same RR root-session binding lookup avoids the identical second root query.
Current authority remains uncached; physical read pre/post guards and final proof
remain. Missing/exact sets now reject before full proof, never authorize publication.
Final default6853 passed/1565 prerequisites146.54s; mypy1085/Ruff/size/eval30 GO.
Native initial72pass/1failure retained; repaired checkpoint42 and publication52
passed. Controlled nine default112.95s/95165SQL, diagnostic81.62s/63329SQL:
queries reduced but observed latency worsened; no speedup/SLO claim. Benchmark
imported before denial-only publication reorder; not frozen-final-source timing.
Prior incremental/rebuild native matrix37 passed873.88s (before this follow-up).
Normal fast continuation and bounded authority batching still OPEN; no activation.

Incremental acceptance implementation (2026-10-10, isolated/source only): user
approved current-unit commit with independent final certification. Explicit
admission/policy validation_mode preserves legacy eager canonical JSON; newmode
scopes historical checkpoint/lifecycle reads, not final certification or current
record dependencies. Global volume/budget/native Event integrity remains.
Verified read coalescing, streaming Task policy and same-recovery replay reuse
implemented. Raw record_ids batch hint was rejected/removed for hidden duplicate
dependency risk; full batch proof and normal continuation recovery remain.
Worker protocol v3 requires old v2 pending work to drain before rollout.
Native repaired rebuild/historical-damage8 passed137.27s. Final default suite:
6848 passed/1565 prerequisite skips129.42s; Ruff/mypy1085/size/eval30 passed.
Incremental nine-record default100.77s/99495SQL; diagnostic67.31s/66101SQL.
Single controlled samples, not p95; diagnostic slower than intermediate64.25s.
Not entire-plan Done: authority batching, normal fast continuation and live/UI
admission remain open. No SLO/live/activation GO.

Coverage performance design refresh (2026-10-10, PLAN ONLY): latest one-callback
controlled run still99.53s/98296SQL with prepare0.021s. Prioritize fresh batched
authority/object access and incremental acceptance before fast continuation.
docs/COVERAGE_PERFORMANCE_PLAN.md now specifies trust/transaction boundaries,
fault matrix, independent certification, protocol migration/rollback, measurement
and UI/live acceptance. Existing source optimizations remain as recorded below;
new contracts are unimplemented. No source changes, restart or performance GO.

Active-lease recovery preflight (2026-10-10): fresh hint + original lock order
inside a savepoint; scoped due live command deferral before expensive preparation.
Miss rolls back locks before proof; no authority/outbox/proof shortcut and fenced
continuation unchanged. Native preflight/original races58 passed49.24s/zero schemas;
scoped source review GO. Proof selection66 passed117.70s, zero scratch schemas.
Controlled nine144.69s/152882SQL/11callbacks; diagnostic99.53s with unchanged
98296 SQL is worse. No isolated speedup claim; SLO OPEN. Final default source
6736 passed/1557 prerequisite skips126.14s; Ruff/Mypy1083/size/eval30 clean.
No merge, service restart or activation.

Coverage guard fanout follow-up (2026-10-10): recovery first-object read shares
its immediately fresh pre-check with the facade read; two pre/post guards instead
of four, cached hits still two and final physical rereads unchanged. Controlled
nine/default154.12s/162309 SQL/12callbacks versus180.50s/178760/14; diagnostic
75.30s/98296 unchanged SQL (previous69.96s), no one-callback improvement claim.
Single observations, not p95/live E2E. Full recovery/commit hotspots still OPEN;
scoped source review GO, final regressions recorded in work-slice evidence.
Repaired fault selection58 passed/zero skips231.01s/zero schemas; native tests
and pure regressions mixed. Retain earlier expired-test-capability failed XMLs.
Final frozen default6736/1544 prerequisites122.39s; Ruff/Mypy1083/size/eval30 clean.
No continuation protocol change, integration, service restart or activation.

Coverage performance plan follow-up (2026-10-10, implementation in progress):
configured durable work slices, private RR SELECT reuse and one deadline wrapper.
Production binding authority reads no longer rebuild Task indexes; native root/
handoff/latest-binding validation stays read-only and fresh. Isolated source only.
Controlled nine117bytes default2s:180.50s/178760 SQL/14 callbacks; diagnostic60s:
69.96s/98296 SQL/one callback. These are single observations, not p95/live E2E.
Normal continuation still performs full recovery; incremental commit and batched
authority remain necessary. SLO/real-provider/browser/semantic labels open.
Detailed measurements/gates: docs/COVERAGE_WORK_SLICE_EVIDENCE.md. No activation.
Final default6736/1542prerequisites (126.55s), safety73 +binding5 +load2;
source review GO, Mypy1083/Ruff/size/eval30. Overall performance still OPEN.

Proof-read scaling follow-up (2026-10-10, bounded native component verified): one
invocation-local model verifier per recovery, not one per accepted batch. RR-only
original byte reuse is bounded to32MiB with uncached fallback, full native/fresh
version/lifecycle checks on every use and independent final physical reread.
No cross-callback authority cache or budget change. Final native1/6/9 certified
17.69/140.89/261.70s, GET157/1802/3521; nine baseline459.46s/10304GET. Native
load cases passed; subsequent safety27 passed (193.46s), zero fixture schemas.
Default6712 passed/1535 prerequisite skips (165.25s), Mypy1082/Ruff/size/eval30.
Retain load XML's test-expectation error: final damaged-object check correctly
raised the existing physical-proof exception; corrected guards pass separately.
Nine remains about262s, not UX/performance SLO GO; final independent proof and
fresh authority/lease queries remain costly. Real provider/broker/browser, labels
and integration/activation remain open. Isolated branch only; services unchanged.

Callback connection performance follow-up (2026-10-10, bounded native matrix verified):
reuse physical sockets inside explicit execution/recovery/check/final-authority
callbacks, not across threads or requests. Independent transactions and session
reset preserve fresh metadata, lease/Host/STOP checks and native final revalidation.
Reset failure now discards sockets without changing committed business outcomes;
transaction failure still propagates. No new dependency or product-limit increase.
Executor-only controlled Worker six-record run certified in 300.95s; adding recovery
scope measured 145.32s, latest rerun 172.42s. Both improved the prior 600s refusal,
but these single-machine controlled-transport runs are not production SLOs.
Native token eligibility is at most nine 1,048,576-context parts under the existing
10,000,000-token ceiling. Twelve is a typed pre-model refusal, not performance GO.
Final admitted 1/6/9 plus refusal/expiry/socket matrix: 14 passed/zero skips
(689.86s), zero new scratch schemas. Final certification17.23/172.42/459.46s,
physical opens53/343/517 (after fixture setup, includes handoff/execution).
Proof-query scaling remains slow at nine records, not user-experience GO. Frozen default
6,699 passed/1,533 prerequisites skipped (129.36s), Mypy 1,082/Ruff/size/eval30.
Independent source review GO; extra recovery tamper/crash checks 8 passed (135.39s), zero new schemas. Actual broker/process/browser/model acceptance,
independent business labels and integration/activation remain open. Services unchanged.

Worker/UI acceptance follow-up (2026-10-10, component verified; scale RED):
actual Worker load gate found 4,610 PostgreSQL connection opens in a profiled
one-record/2-unit run (52.77s). Six records FAILED at final callback, test-case
604.29s against frozen 600s budget; exact refusal not retained, 12 not run.
Keep failed JUnit evidence. No performance GO, cached authority or budget increase.
Typed safe refusal metadata and expired-Host entry validation now settle failure;
one admission timestamp avoids expiry races, fresh IO checks remain enforced.
Paired Trench repairs actual Workspace coverage, active status projection and
silent SSE recovery, preserving cursor/text and waiting for durable terminal state.
Frontend 100/backend 95/build passed. Zebra focused 31; default 6,695 passed/
1,528 prerequisite skips (130.02s), Ruff/Mypy 1,081/size clean. Native smoke
3/zero skips (165.44s) precedes final entry guard; final runtime/grant/expiry-race
3/zero skips (17.04s), zero new schemas. Default suite preceded timestamp fix.
Remaining: connection/proof fanout optimization and full native scale rerun,
real signed Host/JWT/browser/broker acceptance, independent business labels,
integration and activation. Work remains isolated; services unchanged.

Proof-read/history/load/semantic follow-up (2026-10-10, component verified):
phase-local original-byte reuse, paged exact source replay and acceptance tools.
Retain fresh metadata/receipt/sequence/retention checks and logical byte budgets;
independent certificate proof is never reused. Exact historical comparison may
spill to an automatically deleted temporary file, not a weaker aggregate hash.
Necessary identity indexes still have bounded O(N) memory. Real load and labeled
model accuracy require separate evidence; no activation or integration authorized.
Focused 33 passed; default 6,688/1,523 prerequisite skips (128.53s), Mypy 1,081,
Ruff and size passed. Independent review found/fixed incomplete original paging
and a cursor-adapter bypass; final recorded/deadline-aware keyset paging has no
remaining review blocker. Real scratch component load with synthetic 10,003 rows
and 128 objects passed; full Worker load and independently labeled semantics are
not proven. Latest native 10/zero skips (373.00s), zero fixture leaks. Refreshed
load: 21,234,714 -> 545,222-byte history allocation peak; original pages 434,182;
384 -> 128 MinIO GETs. Timings are variable, no measured latency/SLO improvement
claim. Eval30 passed; exact result/evidence boundaries recorded in coverage docs.

Rebuild proof follow-up (2026-10-10, scoped SPEC/QUALITY GO): reuse the private
transcript inside one locked replay transaction; keep rollback, source sequence,
original checkpoint retention and independent certificate checks. No activation.
Author native: two new cases/zero skips (74.01s), nine recovery cases/zero skips
(214.73s), zero fixture leaks. Batch reconstruction replays the ledger once;
original part proofs, independent certificate proofs and history memory remain.
Frozen default regression: 6,663 passed/1,523 prerequisite skips (122.55s).
Mypy 1,080/Ruff/Python size 2,028 zero violations/eval30 passed.
Independent native: 11 passed/zero skips (305.22s), zero fixture leaks; frozen
hashes unchanged. Historical sequence inspected; expired-snapshot rebuild has
no dedicated native evidence in this selection. No live latency/MinIO GO.

Verification-local transcript follow-up (2026-10-10, component SPEC/QUALITY GO): removes repeated
whole-ledger proof and record-merge batch rescans inside publication source
verification. Each proof phase builds its own evidence index; no cross-phase
trusted cache. Original checkpoints, canonical observations, strict historical
ordering, byte ceilings and final lifecycle/retention gates remain mandatory.
Default regression: 6,663 passed/1,521 prerequisite skips (122.20s); Mypy 1,080,
Ruff, Python size 2,027/zero and eval 30/30. Author native: two real multipart
fixtures passed/zero skips, zero scratch leaks. Independent native 53/zero skips
(1127.53s), zero scratch leaks; pure object/HTTP/transcript 15/11/8 passed.
Ordinary commit and independent certificate callers remain independently verified;
locked rebuild now reuses its own transcript. No native scale/semantic/live GO.

Report cooperative deadline follow-up (2026-10-10): one 20-second remaining
budget covers tenant preflight, nested PostgreSQL connections/query/locks,
original object/Host reads and final certificate gate. Request scopes reset;
ordinary callers unchanged. Late results refuse delivery; synchronous DNS,
CPU, thread queueing and cleanup are not a hard 20-second response guarantee.
Final default regression: 6,655 passed / 1,519 prerequisite skips (116.12s);
Mypy 1,079, Ruff, tracked/untracked Python size 2,024/zero and eval 30/30 passed.
Author native-enabled checks: 30/zero skips; independent selection 32/zero skips,
including bounded contended-lock cancellation and zero scratch leaks. Paired
Trench fixes report-owned timeout overrides and Unicode bounds, distinguishes
503/504/422; 37 backend/225 frontend checks and production build passed.
Read-only operation probe corrected earlier O(n) descriptions: proof work has
batch-times-ledger rescans and final locked repeats. Publication source transcript
is now component verified; rebuild optimization and live/native-scale acceptance remain.
No activation, restart, migration, integration or push.

Certified report HTTP delivery follow-up (2026-10-10, component verified): isolated
COV-EXEC-01 composes GET/HEAD with fresh signed read authority and paired Trench
preview/download. No renewal/discovery or ordinary Artifact fallback. Shared
certificate gate now checks source actor, historical fence and original issuance.
Native certificate-read regression: 16 passed / zero skips, zero fixture leaks.
Reader independent SPEC/QUALITY GO: 41 native / zero skips and 42 pure checks,
including actual certified GET/HEAD and mid-proof revocation; scratch cleanup zero.
Final default regression: 6,648 passed / 1,518 prerequisite skips (116.49s);
Mypy 1,079, Ruff, tracked/untracked Python size 2,022/zero and eval 30/30 passed.
Paired Trench: 32 focused backend checks, 216 frontend checks and production build.
Broker principal binding verified in source and 14 broker checks; live JWT/Host/
browser acceptance and deployment configuration remain unverified. Original proof
reads remain O(n); Host's 20-second budget is not a total DB/object-read deadline.
No activation, service restart, integration or push.

Active atomic admission/routing and recovery-lock follow-up (2026-10-09):
default Python regression passed 6,613 tests / 1,514 prerequisite skips (124.72s),
Mypy 1,076 sources and deterministic eval 30/30. Source Ruff and an additional
tracked/untracked scan of 2,017 package/app/test Python files passed. Final native
PostgreSQL selection passed 106 / zero skips (168.33s), including actual native
recovery preparation, compatible handoff and resumed report certification; zero
new fixture schemas remain. These are development gates, not activation or live
performance acceptance. Lock-split has separate SPEC/QUALITY GO, including exact
database/schema/read-set binding, post-lease age/expiry checks and deadline-bounded
HTTP/S3 body reads. Atomic routing re-SPEC passed 104 pure controls; independent
QUALITY passed 98 pure controls and its post-wait/lock-order probes. Both scoped
reviews are GO. Repaired skipped polls, Task runtime deadline, actual S3 endpoint
identity and post-Session Task authority pinning. Multipart7's prior native QUALITY completed
ten real-PG controls / zero skips; its old seven-file freeze is superseded by
this follow-up. No business migration, service restart or primary-checkout
integration has been performed.

Current verified checkpoint (2026-10-09): after the SSE private-prefix performance
slice, full Python passed 6,549 tests with 1,487 environment-prerequisite skips
(127.29s); Ruff passed and Mypy passed 1,070 source files. Current API/AG-UI gate:
925 passed/29 prerequisite skips. Descriptor repaired2 now has independent
SPEC and QUALITY GO on unchanged source/test hashes; QUALITY ran 199 descriptor
regressions and six final-boundary controls, including three guard-removal
mutants. Readiness repaired7 has separate SPEC/QUALITY GO, not atomic admission.
SSE performance3 QUALITY found missing returning-Segment starts/cursors across
A/excluded-B/A slices. That freeze is BLOCKED; repaired slices4 compares contiguous
slice identity and passes 42 main checks including the independent counterexample.
Independent re-review is running. Reportdeadline3 now has separate native
QUALITY GO: 13 passed/zero skips (nine actual-PG cases), plus a killed final-expiry
mutant. Multipart7 native QUALITY passed eight negative controls/zero skips
(212.63s), with seven frozen hashes unchanged and fixture teardown verified.
Normal many-record completion and pre-budget crash recovery are still running;
no final native QUALITY verdict is inferred yet. Earlier pending/review statements
below are historical; these are the current boundaries. HTTP admission/routing,
verified report GET/HEAD, paired frontend/live acceptance, proof-lock performance
and integration remain unfinished. No primary checkout, service or business
database was changed; tests/builds are not deployment acceptance.
Current repaired slices4 full default suite passed 6,551/1,487 prerequisite skips
(135.84s), Mypy 1,070 sources, file-size gate 2,382/zero violations and deterministic
eval 30/30. Ruff clean. Independent slices4 QUALITY passed 98 tests and 786 exact
differential comparisons; independent SPEC passed 98/zero skips plus 2,730 exact
comparisons over 363 permutations. Slices4 has separate SPEC/QUALITY GO. The old
performance3 QUALITY blocker is superseded only for repaired bytes, not erased.
Current repaired API/AG-UI selection passed 911/29 prerequisite skips (39.04s);
the earlier 925 selection included additional paths and is not a like-for-like
count. These gates still do not include real provider/browser acceptance.
The stock file-size gate covers tracked files only; the additional final
tracked+untracked check passed 2,497 source/test files with zero violations.

Current follow-up (2026-10-09): public18-origin's sparse-index high-watermark
bypass was repaired by reading original Events instead of trusting an indexed
prefix. Post-repair API/AG-UI: 908 passed/29 prerequisite skips. QUALITY then
found late strict-marker identity lost in per-Event SSE prefixes; full canonical
Task strict presence is now pinned across prefixes/reconnects. Main shared gate:
50 passed; final Public20 source/pure reviews below are approved. Previous
public18 freezes remain superseded/BLOCKED, not retrospectively approved.
Descriptor-only QUALITY found authority/budget expiry during parsing; final
publication_time now revalidates both (65 main regressions passed), independent
SPEC GO; separate QUALITY pending. Report read now accepts a verified caller's
authority deadline and checks the final database clock; independent SPEC passed
13/zero skips, including nine actual-PG cases. QUALITY pending. This does not
itself verify a grant or enable HTTP report access.
Multipart writer: 20 native passed/zero skips; readiness writer: three native
passed/zero skips on the superseded freeze. Independent readiness SPEC found
mandatory dispatch wiring missing from capability registration; repair now has
63 independent source/pure and six actual-PG passes, separate QUALITY pending.
Public20 repair has
independent source/pure SPEC GO (109) and QUALITY GO (118), not native-scale GO.
Expanded API/AG-UI/source gate: 1,115 passed/29 prerequisite skips; Ruff clean,
Mypy 1,069 sources and deterministic eval 30/30 pass. Strict
HTTP admission/report UI, scale, joint live acceptance and branch integration
remain open. No running service, primary dirty checkout or business data changed.
Full Python regression: 6,540 passed/1,487 environment-prerequisite skips
(118.88s), plus final descriptor refusal-reason assertions four passed. Multipart
independent SPEC passed 11 actual-PG controls/zero skips and 66 pure controls;
QUALITY remains pending. It observed a long proof transaction blocking lease
heartbeat (~145s), so this is bounded correctness approval, not latency/scale
acceptance. Descriptor repair independent SPEC passed 229/zero skips, including
three guard-removal controls; QUALITY pending. Worker/report native re-review
continues in a serialized scratch-DB slot; no business migration was run.
Worker readiness repair now has separate QUALITY GO: 81 pure controls and six
actual-PG cases/zero skips on unchanged frozen7. Observational readiness is not
an atomic API/routing gate. A later three-file SSE performance slice extracted
the frame helper to preserve file limits; complete strict validation precedes
skipping private same-Segment prefixes. Main 46 regressions passed. In the exact
501-event test, projector invocations fall from 501 to two (prefix entries
125,751 to 502) with identical frames/cursors. This is not measured response
latency or general linear complexity; source/pure reviews are pending and the
previous full-suite result predates this subsequent optimization.

Latest public-output repair: independent QUALITY reproduced a partial-root index
bypass in public14; independent public18 SPEC then reproduced a child relabelled
as its own root plus an uncaught Task stream error. Both superseded freezes are
BLOCKED. Shared canonical identity now validates contiguous native membership
against durable handoff root/parent/stage, and both raw adapters return 409 on
incomplete identity. Session/Task summaries whitelist lifecycle fields and never
expose candidate context or attachments. Main current focused gate: 17 passed;
expanded API/AG-UI and independent re-SPEC are running. Public-all/HTTP activation
is not approved. Reader/adapter scoped approvals below remain unchanged.

Earlier follow-up: public14 final independent SPEC passed six actual PostgreSQL
cases, zero skips (5.46s), all fourteen hashes unchanged; QUALITY is pending.
Bounded Cloud reader2 has independent SPEC/QUALITY GO (33 pure cases plus
physical-bound and mutation controls). Read-only Cloud certificate Artifact
adapter2 passed SPEC (four originals plus twelve adversarial controls), QUALITY
pending. Main shared reader/adapter gate: 22 passed, Ruff/Mypy clean. Descriptor-
only Host revalidation passed 60 main tests; independent SPEC pending. Public
summary isolation is being wired after public14 review. Multipart7 source is
frozen with 36 pure passed; native verification is active. Process-level Worker
readiness implementation is active; HTTP/report activation, native scale and
coupled live acceptance are not completed. No running service was replaced.

Previous strict-output isolation follow-up: after repairing a SPEC-reproduced
child-Segment bypass, main expanded API/AG-UI/SQLite Task gate passed 893 with
29 prerequisite skips. A second missing-index fallback finding now refuses
unproven received-handoff identity; current new pure/SQLite gate 27 passed.
Parent lookup passed one native PostgreSQL smoke; final public14 freeze is in
re-SPEC, not approved. The superseded public10 freeze remains BLOCKED.
Candidate4: main native 27 passed/zero skips; independent SPEC 13 passed/zero
skips. Report3: main native 59 passed/zero skips; independent SPEC 13 plus a
historical-deadline control passed. Independent QUALITY passed 27 native controls,
260 pure cases and three mutation controls with both hashes unchanged; both
bounded slices now have SPEC/QUALITY GO. Multipart implementation is active;
process-level compatible-Worker proof, strict HTTP/report activation, native
scale and coupled live acceptance remain open. No running service was replaced.

Current follow-up: API strict preflight independently SPEC/QUALITY approved,
including the repaired idempotency bypass. Absolute AG-UI coverage progress and
paired Trench persistence/UI passed SPEC and QUALITY after cancellation replay
and uncertified terminal-label repairs. Current native storage: 362 passed plus
two separate real PostgreSQL/versioned-MinIO publication cases passed. Worker
empty/single-part same-Session recovery passed independent SPEC and QUALITY;
main native Worker gate 45 passed/zero skips, independent preparing-crash two
passed and QUALITY native twelve passed. Multipart is still being implemented.
Restored ordinary concurrency seam independently
passes six cases and expanded API/AG-UI passes 873 with 29 prerequisite skips.
Strict HTTP admission still refuses until the native execution boundary is ready;
no running service activation or large-run/live-model completion is claimed.
Frontend: 196 tests, TypeScript, ESLint and current production build pass. Paired
Trench broad API gate has seven failures also reproduced at clean HEAD, not a
new progress regression. Mypy 1,061 sources, Ruff and tracked/untracked 2,473-file
size check pass; cumulative candidate-volume admission and full runtime acceptance
remain open. These component approvals do not authorize strict HTTP activation.

Strict MODEL per-unit transaction gate passed scoped SPEC and QUALITY. The QUALITY
projection-rebuild/report-retention fixes passed independent re-SPEC's 14
actual-PostgreSQL representative tests (zero skips; 538.75 seconds), but re-SPEC
found certification reading an oversized original set before the shared preflight.
The shared replay-entry repair passed fresh independent re-SPEC: six real-PG cap
branches refuse before original reads with no state drift, plus projection/prune/
ledger representatives pass. QUALITY independently passed 23 native/raw cases
and two recovery controls on unchanged ten-file hashes. Legacy-five migration
also passed separate SPEC/QUALITY (40/41 focused cases); full native standalone/
combined regressions still remain. Worker composition/recovery implementation
is now active; no strict-task runtime activation follows the component GO.
Main protocol regressions: 284 passed;
Mypy: 1,056 source files clean. No runtime activation follows these checks.
Results require v2 original derivation, exact canonical observations and merges
on commit/retry/rebuild/certificate issue/read. The 32 MiB original-set ceiling
does not bound repeated physical I/O; native large-run optimization, Worker/API/
UI activation and live semantic accuracy still require separate acceptance.

Callback-to-Cloud component passed independent re-SPEC and re-QUALITY after
adding public-projection absence and isolated native PostgreSQL deadline checks.
Final full 17 passed / zero skips (244.32 seconds); independent deadline mutant
now fails when the native guard is removed. Main also passed two actual PG +
versioned MinIO process/crash publication cases (4.02 seconds), cleaning only its
owned temporary bucket. Provider/S3/Host in the callback suite remain fixtures;
the separate publication test does not prove live model execution. Per-unit
transaction derivation gates are now the active slice. Worker/API/UI activation,
native large-run performance and live semantic accuracy remain outstanding.

MODEL invoke-or-replay composition passed independent re-SPEC and separate
QUALITY after closing dispatcher/weakref hidden-transport paths and repairing
official metadata format compatibility. Main full Python 6,369 passed / 1,345
skipped (120.96 seconds), Ruff/Mypy 1,055 and 2,457-file gate pass. Original
v2 checkpoint readback precedes settlement; unknown attempts retain their charge
and cannot retry, settled replay uses exact original evidence. Main separately
passed 34 real PostgreSQL retention/deadline cases with zero skips. Next is
actual callback-to-Cloud acceptance, then per-unit transaction derivation gates
and Worker/API/UI composition. Repeated manifest reads (26 fresh / 15 replay in
QUALITY's fixture) and cumulative settled-proof reads still need scale work.
No running service has been replaced or full product closure claimed.

Semantic request/source/response derivation passed independent re-SPEC and
separate QUALITY after repairing a reproduced foreign-provider/model identity
bypass. It binds v2 original bytes, exact unit, frozen instructions and manifest
part digest/length to the decoded original semantic result. Main full Python
6,176 passed / 1,345 skipped (120.52 seconds), Ruff/Mypy 1,053 and 2,452-file
size gate pass. Pure derivation does not authorize storage acceptance: actual
invoke-or-replay composition, per-unit transaction gates and Worker/API/UI
activation remain outstanding, as does live semantic precision/recall acceptance.

Exact prepared-request checkpoint v2 passed independent SPEC and separate
QUALITY; legacy v1 bytes and Artifact identity remain unchanged. Main full
Python 6,050 passed / 1,345 skipped (114.76 seconds), Ruff/Mypy 1,052 and
2,450-file size gate pass. This is internal byte evidence, not unit derivation
or Worker activation. The next claimed slice binds original request and full
response to frozen semantic rules and manifest part digest/length. Repeated
serialization and production peak memory remain performance acceptance debt.

MODEL checkpoint/receipt lifecycle is in progress. Original completion bytes,
canonical Artifact Events and frozen request/run identities now gate settlement,
replay, rebuild and new calls; readerless settled replay is refused. Main tests
after that repair: 199 real scratch PostgreSQL passed / zero skipped and full
Python 5,985 passed / 1,311 skipped (138.22 seconds); Mypy 1,052 sources passed.
Retention repair now passes independent re-SPEC and main 30 real PostgreSQL
regressions; latest broad rerun 199 passed / zero skipped and full Python
5,985 passed / 1,341 skipped. First-issuance deadline repair now passes independent
re-SPEC and separate re-QUALITY GO: a late final callback cannot certify; lawful
previous historical replay remains valid. Main final 34 real PostgreSQL time
boundary cases passed / zero skipped; full Python 5,985 passed / 1,345 skipped
(122.14 seconds), Ruff/Mypy 1,052 and 2,449-file size gate pass. This is component
approval, not Worker/API/UI activation. Exact prepared-request evidence and
per-unit semantic derivation are next. New-call settled
proof reads still cost O(n) each / O(n²) cumulative; scale acceptance remains due.

Full MODEL completion codec now preserves all supported typed response fields,
including private reasoning, and refuses raw shape/internal-state mutations
before lossy normalization. Independent re-SPEC GO after timezone/UUID/Enum
repairs; subsequent fixed-offset/UTF-8 repairs pass re-SPEC/re-QUALITY GO.
Latest main full Python: 5,956 passed / 1,201 skipped,
zero failures; Ruff/Mypy (1,050 sources) pass. Codec support is fixed stdlib
timezones and canonical cached ZoneInfo, not arbitrary timezone object identity.
This remains internal recovery evidence: no Worker/budget/checkpoint settlement
or public product activation has been completed by this slice.

Exact Effect claim prerequisite: independent SPEC re-review GO after strict
recursive typed-input and succeeded-result replay repairs. Main independently
verified 29 gateway and 52 real scratch PostgreSQL tests (zero PG skips), full
Python 5,672 passed / 1,165 skipped, Ruff/Mypy (1,046 sources), and the 2,436-file
size gate. QUALITY identified lossy raw persisted request/result decoding before
exact validation; shared raw readers now validate strictly before normalization.
SPEC/QUALITY re-reviews GO; main independently verified 59 real scratch PG tests
(zero skips), 44 gateway/Cloud-reader tests and all four original counterexamples.
Latest full Python: 5,684 passed / 1,172 skipped; Ruff/Mypy (1,046 sources) pass.
Snapshot-create callback passed independent SPEC review after persisted Session
namespace validation. Main independently verified 28 real scratch PostgreSQL
callback tests (zero skips). Finalized-output integrity repair passed independent
SPEC/QUALITY re-reviews; main and QUALITY each reran all 30 callback real scratch
PostgreSQL cases with zero skips. Main Worker dispatch and paired
API/UI activation are not yet complete.
Worker business-vocabulary violations were repaired by sharing the integration
adapter contract without changing wire values or weakening architecture gates.
Independent SPEC/QUALITY GO. Latest full Python: 5,685 passed / 1,201 skipped,
zero failures; Ruff/Mypy (1,048 sources) pass. Prepared MODEL request prerequisite
is now in progress; no production activation or full-chain completion claim.
Prepared-request SPEC review reproduced Client auth/hooks/query drift and raw
policy fallback defects despite 61 passing focused tests. Local strict input and
transport-capability repairs are required before QUALITY; ordinary Chat stays
unchanged. Budget/checkpoint callbacks, Worker and paired product loop remain open.
Those repairs and the later URL-userinfo/Basic-Auth repair now pass independent
SPEC/QUALITY re-reviews. Main final full Python: 5,813 passed / 1,201 skipped,
zero failures; Ruff/Mypy (1,049 sources), diff check and file-size gate pass.
The prepared request capability is not yet connected to durable MODEL budgets or
completion checkpoints. Existing HTTPTransport-pool reuse is explicitly unsupported
on this strict opt-in path; MockTransport remains a trusted fixture, not live proof.

2026-10-08 follow-up: user selected semantic checks and delegated the initial
rule. The fixed evidence-grounded annotation rule and separate quality thresholds
are recorded in docs/superpowers/plans/2026-10-08-coverage-closure.md. Implementation
continues in the existing isolated task; this resolves the business-rule choice,
not Worker/API/UI activation or live semantic-quality acceptance.

Semantic follow-up: fixed rule validator and configured gateway adapter passed
independent SPEC/QUALITY review. Shared provider parsing rejects invalid wire
roles before normalization. Integrations regression: 455 passed / 6 skipped;
Ruff and Mypy (1,037 source files) pass. Typed Task identity/recovery passed
SPEC/QUALITY, including a repaired backdated-event expiry defect. Admission now
checks actual UTC time, independently of event timestamps. Core/Worker selection:
1,513 passed / 29 skipped; post-repair focused selection: 97 passed. Strict tasks
temporarily fail with coverage_unsupported before workspace/model/runtime setup;
this is safe refusal, not configured dispatch. Durable callback budgets, actual
Worker dispatch and cross-session strict identity preservation remain pending.
Verified manifest preparation before publication now passes SPEC/QUALITY,
allowing full Cloud run binding without a fake or unbound Artifact facade.
Preparation is source intent only, not readable or published evidence. Final
full Python suite for this source: 5,472 passed / 1,018 skipped; preparation
58 tests and snapshot 159 tests pass. Cloud bootstrap now passes SPEC/QUALITY,
including raw descriptor identity, persisted tool-manifest binding and final-bind
transactional revision/Task-binding guards. Main scratch PostgreSQL bootstrap
selection: 79 passed, zero skipped; full Ruff/Mypy (1,039 sources) pass. This is
component approval, not Worker dispatch or real object-store/Host acceptance.
Snapshot Effect replay identity is the next active prerequisite. Full suite after
the bootstrap repair: 5,535 passed / 1,034 skipped, before the next replay slice.
The earlier untouched macOS process-group cleanup failure did not reproduce;
no unrelated runtime workaround was applied.
Snapshot-create replay now hashes and forwards the exact same opaque key with
the complete signed request identity; SPEC/QUALITY approved, 187 tests passed.
Strict handoff commit/replay guards pass SPEC/QUALITY and 41 SQLite/real scratch PG tests.
These are recovery prerequisites, not configured
model-budget callbacks, Worker dispatch/wakeup or Trench API/UI delivery.
Durable MODEL budget storage and frozen snapshot history provenance passed SPEC/QUALITY.
Main independently ran 163 budget/publication/bootstrap tests
and 73 shared binding regressions against scratch PostgreSQL, zero skips.
Review exposed raw nested typed-copy forgery at projection equality; repaired
the shared lock/write/projection boundaries and bind before any I/O. Legitimate
UUID identities remain intact. SPEC independently ran 66 public API probes.
Main independently reran the repaired full suite: 5,643 passed / 1,133 skipped.
Full Ruff/Mypy (1,045 sources) pass. File-size gate: 2,433 files, zero violations.
Native integrity scans still have O(n) per-mutation/O(n²) cumulative cost;
10k-scale performance acceptance and configured callback execution are pending.
The next active slice composes snapshot-create through existing Cloud Effect
dispatch with exact opaque key preservation and original result replay. This
callback slice is not main Worker dispatch or runtime activation.

2026-10-08: COV-EXEC-01 is claimed on codex/cov-exec-01 from locally integrated
cloud-agent-trench@b97a5b1a. Follow-up source implements resumable validated unit
execution, atomic coverage Artifact/Event publication, physically bounded reads,
prepared manifest indexing, durable budgets (migration 79), exact report building
and fenced certification/replay. See docs/COVERAGE_EXECUTION.md for limits.
This is not runtime activation: strict admission, actual Worker dispatch/wakeup,
Host write Effect composition, production model/check configuration, all-surface
publication gates, API/UI and coupled live acceptance remain unfinished. The
Worker Artifact facade is tested separately, not connected to the main loop.
Dirty primary trees/services remain preserved; no push, live migration or restart.

2026-10-07: COV-STO-01 implements Event-backed coverage persistence on
codex/cov-sto-01, based on locally integrated COV-CON-01@2c49881b. Immutable
Artifact manifests seed exact expected-unit indexes. Batch Events, accepted
units, idempotent receipts and dormant continuation intent share one fenced
PostgreSQL transaction. Cancel/rebuild retain source authority and historical
lease evidence; source coverage events pin the persisted Task binding. See
docs/COVERAGE_STORAGE.md for explicit scale and authority boundaries. No runtime
admission, executor/claim activation, certificate, publication or live migration
is included; snapshot/executor/gates/UI/coupled acceptance remain unfinished.

2026-10-07: COV-CON-01 establishes exhaustive coverage v1 metadata, bounded
snapshot/batch Ports and a deterministic exact-set reference validator on
codex/cov-con-01. Contract/scope/check/content versions, frozen body parts,
record merges, current-authority bindings, expiry, unresolved work and aggregate
input digests are checked without replacing the existing exploratory runtime.
See docs/COVERAGE_CONTRACTS.md for trust boundaries and remaining dependent
snapshot/storage/executor/publication/API/UI/E2E tasks. This is a contract slice,
not production exhaustive processing. Locally merged into cloud-agent-trench
at 2c49881b by user selection. No migration, activation or push.

2026-10-07 exhaustive data coverage proposal (CLOUD-DATA-COVERAGE-DESIGN-01):
docs/CLOUD_DATA_COVERAGE_DESIGN.md specifies Host-owned immutable datasets,
snapshot-bound enumeration, durable per-unit results, exact coverage validation
and publication gates across final answers, streams, artifacts and dependent
business actions. Reuses Task/Event/Effect/Artifact authority; semantic accuracy
is explicitly separate from processing completeness. Planning/docs only;
successors are proposed/Locked, with no code, migration or runtime activation.

2026-10-07 local sandbox integration (CLOUD-LOCAL-GVISOR-01): reused the existing
zebra-gvisor OrbStack Ubuntu VM, rather than weakening isolation or adding a VM.
Its runsc handler is exposed through a client-certificate-required socat TLS
bridge; private keys remain ignored/root-only and the Worker mounts only client
credentials. The local Compose overlay removes the outer Docker socket and keeps
control-plane data in place. Existing quota-volume bytes are shared through the
VM mapping. Real ephemeral Worker preflight and OciRuntime command/shared-file/
quota smoke passed; the test sandbox was destroyed. Five Compose boundary tests
and make check pass. Manual recreate script checks readiness before replacement.
The VM bridge was installed/started without restarting Docker or user application
services. API/Worker still run their old images pending user activation; historical
Turn recovery and live Host/model/browser acceptance remain unproven. See the
runtime-startup runbook for activation, 30-day certificate rotation and rollback.

2026-10-07 runtime startup closure (CLOUD-RUNTIME-STARTUP-01): missing mandatory
OCI isolation now closes the prepared command with durable TurnFailed and
SessionFailed, projected to AG-UI RUN_ERROR and Trench's error terminal. Only
read-only capability checks receive bounded transient retries; container effects
and missing-handler failures are not retried or downgraded. Worker health probes
the configured isolation instead of only Docker version. Runtime preflight is an
operator CLI; see docs/runbooks/runtime-startup-failure.md. Focused runtime/Worker/
AG-UI regression passes; paired Trench protocol tests: 49 passed, and RUN_ERROR
terminal mapping smoke passes. make check passes. Native API/Worker images rebuilt
without restarting services. Real ephemeral Worker preflight correctly exits 1:
local Docker does not advertise runsc. Actual task execution remains blocked on a
compatible configured sandbox host; historical stranded commands were not replayed
or mutated. These checks do not constitute live browser/model acceptance.

2026-10-07 conversation critical-path follow-up (CLOUD-CONVERSATION-PERF-01):
Trench native-v9 explicitly marks only independent authorized read tools as
parallel-safe; existing Worker concurrency and failure isolation remain intact.
Overview/research acceptance guidance targets named evidence gaps, not exhaustive
keyword loops or arbitrary forced short answers. Model-only exact repeated
historical records become references within one user turn; durable observations,
changed facts, query receipts and evidence URLs remain intact. Selected retained
conversation observations replay: 210451 -> 123185 bytes (41.47 percent smaller),
not a provider-token or live latency measurement.
Cloud Worker composition explicitly scopes one PostgreSQL pool (maximum eight
connections, two-second acquisition, bounded queue); adapters capture the pool
for thread use. Deadline-bound Task I/O intentionally retains isolated fresh
connections and its cancellation/unknown-COMMIT protections. Real PostgreSQL
rollback/reuse smoke passes; 20 SELECT microbenchmark: fresh 136.02 ms vs pooled
25.18 ms. Latency summaries now pair parallel calls by session/call identity and
include attempt preparation. Slow serialized mutations log admission/operation
time without payloads. No authority event or transactional projection is deferred.
Paired Trench loads only bounded historical summary columns, combines source and
total counts, and memoizes Markdown configuration/document rendering while
preserving media nodes during streaming. Frontend 407 tests and production build
pass. Local acceptance DOCKER_HOST now uses the proven mounted Unix socket.
Source gates and build evidence are separate from runtime activation: user services
have not been restarted; 120.25-second baseline improvement, browser first useful
output and P95/concurrent-load targets still require fresh calibrated acceptance.
Search guidance is not a deterministic semantic novelty gate; exact compaction
does not merge differing facts. No blanket lower-reasoning policy is introduced.
Final core/Worker regression: 1683 passed / 82 environment-gated skips. Real
PostgreSQL pooled reuse/rollback suite: four passed. Zebra API/Worker Docker
images rebuilt successfully with the pooled driver dependency; not activated.
Local architecture check found single-architecture AMD64 mirror bases on an
ARM64 host. Application Compose now explicitly selects a configurable platform
(AMD64 deployment default); ignored local acceptance config uses ARM64 and
official multi-architecture Python/Docker CLI bases. Native API/Worker builds
pass. This removes the local emulation requirement after recreation, not proof
that emulation explained all historical latency. Compose platform matrix passes.

2026-10-07 progressive follow-up: reproduced the chart prompt's double publication
wording as an OPERATE misclassification. Explicit files.publish plus bounded,
extension-qualified Artifact file objects now infer CREATE; external destinations
and mixed deploy/release requests retain operational verification. A full Harness
regression completes only with a tool-returned Artifact and suspends without one.
The existing embedded Cloud identity now asks for assistant content alongside
tool calls, without a separate acknowledgement model call or duplicate prompt.
Core/stream/progressive Worker regression: 1295 passed, 3 environment skips;
make check and diff check pass. The exact previous chart QA prompt now requires
answer/evidence/artifact, not operational verification. No new live chart pass.
Read-only native header timing localizes an accepted-command-to-model-request
interval of 4.76/4.99 seconds; request-to-first-text Event is 1.51/0.86 seconds.
These Event creation timestamps are not calibrated commit-to-visible timings or
isolated provider timings. Preparation/persistence needs further attribution.
Current checkout differs from activated v8; no build/restart, publication or
new calibrated healthy samples are claimed.

2026-10-07 P1 continuation: explicit empty provider reasoning survives stream
assembly without inventing absent fields or treating empty text as semantic
output. Main independently reran 174 parser/stream/Worker regressions; all pass.
Fresh `make check` passes sizes (2360 files), Ruff, mypy (1110 sources), and
30 deterministic evals. This adapter defect is not yet proven to explain the
historical v5 image failure. QA async operator-hook fixtures have three
reproduced failures and are being aligned with actual joined child cleanup.
Fresh full regression passed: 6800 pass / 1338 environment-gated skips
(881.22 s); explicit native commentary/recovery/publication/visibility matrix
passes 65 with zero skips. Frontend full regression passes 397 and TypeScript
passes. QA async/operator matrix passes 92 Python and 57 Node cases; its
unbounded cleanup wait is removed with actual close/failure regressions.
V7 isolated activation and trust renewal are complete. Actual image replay is
still failing: the browser receives Host 502 from native preview 503. Object
bytes, immutable version and lifecycle are intact. Read-only reproduction
identified separate cold DNS resolvers consuming the shared 2-second deadline.
Artifact index, payload metadata and delivery audit now reuse the existing cloud
TaskIoConnections; deadlines, fresh SQL connections and integrity checks remain
unchanged. Focused regressions: 66 pass / 6 skips; make check passes. V8 isolated
build/activation is complete; actual image slice passes good-image decode,
fault abort/sibling isolation and preterminal visibility. Turn
`57b08037-6dbb-4009-8fde-4550aeb120ca`; no calibrated healthy sample is claimed.
Inline video also passes actual playback/frame advancement/preterminal visibility
with zero file-download requests. Chart/Markdown/LaTeX replay failed at answer
render: chart parts were delivered, but the operate contract reports partial
verification and Host awaits input. Exact Run cleanup confirms lease released
and all five Worker execution counters zero. No chart UI pass is claimed.
Full P1/timing acceptance remains incomplete.
User application services and data remain untouched.

2026-10-04 all-P1 continuation is in progress on the same user-selected branches.
Disjoint context, delivery, background and isolated-QA lanes are claimed under
`CLOUD-PROGRESS-OUTPUT-01`; main owns shared wiring and integration. Required
evidence and timing boundaries are in `docs/P1_PROGRESS_CLOSURE.md`. Existing
user application containers are not restarted or migrated. No P1 completion,
publication or application activation is claimed before fresh verification.
Latest v4 scratch replay passes 3/14 functional cases: simple, multi-source and
tool-only. Strict Host public-facts preservation and object-separated prohibited
action inference repair the actual result/verification chain. Quality gates and
three QA builds pass; fresh full regression is running. Meaningful timing and
feedback SLOs are not met. One calibrated functional sample is incomplete due to
legacy tool-loop public-update events and therefore counts as 0/100 complete
timing samples. Exact evidence and remaining acceptance are in the P1 document.
Frozen v4 full regression subsequently passed: 6715 pass / 1334 environment
skips (793.98 s). Media image live case remains failed, and the paired Host
Redis-timeout double-wait root fix is underway. Functional/full-gate results
do not close latency, remaining live cases or user-operated activation.

Canonical commentary producer/recovery and paired Host composition now pass
focused checks, including 49 native PG checks with no skips, exact Unicode and
whitespace chunks, fenced crash-gap repair, and replay-stable message identities.
Frontend full tests pass 396; TypeScript and production build pass. Latest
`make check` passes 1110 source files and 30 deterministic eval cases. V5 full
regression and isolated rebuild are underway; live matrix/timing remain open.
QA bucket versioning is corrected without changing existing objects; real Redis
wakeup/cancellation/fallback checks pass. Application activation remains separate.
V5 full regression subsequently passed: 6750 pass / 1338 environment skips,
819.64 s. Final frontend/hook integration passes 397 tests and production build;
SDK check/build passes with supported Node 24. These are not a completed live
matrix, 100 calibrated timing samples, or user-application activation.
V5 isolated activation is byte-verified, but the fresh image case fails before
tools: 88 streamed characters then `invalid_response_shape`, zero repairs.
The retained size/hash cannot identify the invalid field; safe diagnostic
metadata is being added without relaxing validation or retry safety. Later media
cases remain paused. Synchronous QA guards also distort browser measurement;
fresh async native checks and exact guard windows are under implementation.
Neither this failure nor 0/100 complete calibrated samples is marked closed.

2026-10-04 P0 implementation and isolated acceptance are complete on the
user-selected `cloud-agent-trench`, paired with Trench `main`. Fenced canonical
Session/index recovery and exact execution-input preparation use bounded,
resumable pages. Persisted usage, attachment and canonical Turn summaries remove
cloud Task GET historical hydration; GET never repairs data. Native lease I/O
and shared workspace reads have deadlines. Duplicate-ID Turn lookup aliases are
preserved; obsolete derived state rebuilds only through the bounded writer.
Final frozen gates: 6346 passed, 1273 environment-gated skips (858.70s);
46 explicit isolated PostgreSQL checks passed with no skips; file-size/Ruff,
Mypy 1093 source files and all 30 deterministic eval cases passed. Trench backend
47 and frontend 373 tests passed; frontend typecheck passed.
Latest API/Worker/migrate images are built. Real isolated Host/browser/SSE short
answer passed with matching 1093 Zebra and 518 Host source files, migrations
72–74, same-Run checkpoint/frozen policy and exactly one final commit.
Evidence: `/tmp/zebra-p0-closure-20261004-uVMAj2`, especially `qa-frozen-v2/`.
This is not full-plan closure: thirteen live/fault scenarios, 100 healthy timing
samples/P95, long-input semantic capsules beyond 2048 events/1 MiB, remaining
background whole-history paths and post-answer Worker cleanup proof remain.
One simple-answer first-text sample is 17.36s, not a closed latency target.
Application migrations/restarts and publication were not performed; current
user application containers still require user-operated activation.

2026-10-04 continuation: fresh `make check` passes file sizes (2360 files),
Ruff, Mypy (1074 source files), and all 30 deterministic eval cases. Native
network cancellation passes 49 tests. Real isolated PostgreSQL lease expiry
and takeover passes both legacy/v2 network paths: native reads stop, sockets
and children close, old-Worker publication is rejected, and the successor can
publish. Related media/Worker regressions pass 53 tests; native HTTP/unknown
commit probes pass six. Explicit optional constructor arguments repair the
native web-tool typing failure without breaking zero-argument legacy factories.
The fresh full suite finished with 6173 passed, 1232 skipped and one failure:
an offline v2 authority test patched synchronous DNS, but native cancellation
now resolves in a child. Actual DNS returned a proxy fake-IP and SSRF correctly
rejected it. Injecting the existing CrawlGateway resolver fixes the fixture;
both authority tests pass with stronger successful-tool-receipt assertions.
Production DNS cancellation/SSRF is unchanged. A fresh full rerun is logged at
`/tmp/zebra-progress-validation-20261004-eyv7fq/full-tests-after-dns-regression.log`;
its terminal result is pending. Whole-history Worker input recovery,
exact activated images, fourteen actual joint cases and 100 healthy timing
samples remain open. No application restart/migration, commit or push.
Independent review reproduced and repaired an unbounded native child cleanup
wait when termination itself raises secondary cancellation. Independent group
kill fallback, process kill, pipe closure and at most 0.5-second reap preserve
the primary exception. Six real RED-to-GREEN probes include descendant socket
closure; the latest network/Worker/real-PG matrix passes 65 with zero skips.
The post-DNS full run passed 6174 with 1232 environment-gated skips, but preceded
this cleanup edit. The subsequent full validation completed (6188 passed, 1232 skipped) in
`/tmp/zebra-progress-validation-20261004-eyv7fq/full-tests-after-native-cleanup.log`.
Application images were rebuilt after the cleanup edit; isolated image code
hash matches local source, without activation. Latest complete `make check`
again passes sizes/Ruff/1074 typed files/30 evals. Isolated runner protocol
matrix passes 42 with one environment-gated skip; new runner strict typing and
browser-script syntax pass. Real scratch topology/cases/timing are not complete.

Previous 2026-10-03 full-suite evidence (not the current running gate):
full Zebra validation was RED (5524 passed, 29 failed, 4 setup errors,
1129 skipped). Four native authorization probes require the explicit isolated
scratch DSN; the remaining failures are being reproduced by independent SQLite
storage and API compatibility lanes. Fresh SDK `pnpm verify` passed package,
consumer and Chromium/WebKit/Next checks. Six late UTC authorization probes
reproduced incorrect success/409 exits; the shared preflight fix passed 35 related
checks. Per-frame expiry and target-resource authorization are not yet jointly
closed. Whole pre-Grant I/O, legacy migration gate, current full gates/builds,
user-operated activation, fourteen live cases and timing distributions remain
open. Application services/data, commits and publication are unchanged.

2026-10-03 full progressive-delivery implementation is in progress on
`cloud-agent-trench`, paired with Trench `main`. Public status/commentary/results
now have a bounded durable contract and ordered Host/React projections. A real
flush timer emits buffered text during provider silence; truthful receipt-based
milestones cover tool-only model responses. Optional expression is off by
default, separately metered, tools/thinking disabled and bounded to two short
calls. Its receipts are excluded from conversation context/title/trace.
Per-task policy is frozen in the event stream. Timer appends share recorder
serialization with tool receipt prepare/commit/accept; long provider calls stay
outside that boundary. SDK split-text, announcement replay and per-chart failure
isolation findings are fixed and quality approved. Latest completed full Zebra
gate: 5042 passed, 915 environment-gated skips; paired Trench API: 794 passed,
frontend: 272 passed before the latest rejection-guard regressions; TypeScript
passes. Isolated real PG Effect/consumer: 16 passed; Task/lease/control/handoff
checks: 54 passed, two RabbitMQ-gated skips. Same-key return, late admission,
newer-message preservation and revoked observers now have focused regressions;
fresh quality review still checks the obsolete snapshot rejection branch.
Effect cleanup independently passes 46 focused checks and 41 probes. Full gates
and builds must be rerun after follow-up edits. SDK verification and exact five
packed artifact/lock/installed-byte checks passed before these follow-ups.
Intra-Event SSE positions now prevent partial-frame disconnect loss; replay
projects each event once instead of repeatedly projecting prefixes. Backend/Host
review loops, running-image activation, mandatory bounded historical paging and
checkpoint recovery, timing evidence and 14 live/fault scenarios remain open.
Actual SSE now uses the metadata-only checkpoint observer and bounded pages;
indexed binding passes 22 focused checks, and migration65/66 facade composition
passes seven real scratch-PG checks. Pending source-header regressions, migration67/68,
background composition and the latest API matrix still require closure. No live
or whole-goal completion follows from this evidence.
No restart, commit, push or 100% claim.
Requirement ledger: `docs/CLOUD_PROGRESSIVE_DELIVERY_PLAN.md`. Immutable source
Task-position and bounded legacy-backfill design:
`docs/CLOUD_TASK_REPLAY_POSITIONS.md` (implementation/activation still open).

2026-10-02 closure follow-up: live media acceptance exposed completed private
model output incorrectly disabling bounded parse repair, artifact publication
misclassified as an external operation, stale progress IDs colliding with error
answers, and chart fetch failures with no recovery control. These are fixed with
regressions; remote-image/chart tool guidance is explicit. Agent core/tools/
integrations: 1559 passed, 2 skipped; paired frontend: 36 passed; chart SDK: 5
passed; make check and frontend production build pass. API/Worker images and
vendored chart package rebuilt. Bilibili actually played inline without video
download; a generated Vega-Lite chart rendered after refresh. Fresh runtime
activation/replay and new chart retry UI acceptance require user-operated service
restarts. No claim of 100% live closure, merge or push. See CLOUD_PROGRESS_OUTPUT.

2026-10-02 progressive-output follow-up: paired Trench preserves AG-UI message
identity through streaming, progress promotion, candidate verification and
final rendering; XMarkdown now renders during streaming, with explicit
reconnect/verification states. Grant exchange recovers bounded transport faults
without retrying run commands or relaxing authorization. API 90/frontend 35
focused tests, lint/types and frontend build pass. Authenticated live acceptance
verified Markdown, real remote image loading and mid-run refresh with no
duplicate progress. Provider tool selection still attempted unnecessary image
downloads; full video/chart live acceptance is not claimed. See
`docs/CLOUD_PROGRESS_OUTPUT.md`. No restart, commit or push was performed.

2026-10-02 follow-up: user-restarted replay exposed two remaining contract
defects. Trench's duplicate keyword classifier overrode negation-aware runtime
inference; partial Host constraints then revealed inference from appended
conversation history instead of the explicit current goal. Trench now supplies
only goal and positive product evidence constraints; Zebra infers omitted fields
from the bounded explicit goal. Positive writes retain verification and create
tasks retain artifact gates. Focused tests and `make check` pass. New images are
built; user-operated activation and exact live replay subsequently passed:
Turn `fa3ba686-0768-49eb-9957-e9d3399eaa36` completed with four progress
updates and no unmet delivery outcomes (55,319ms).

2026-10-02: `CLIENT-RELEASE-CLOSURE-01` pins Trench frontend release v3,
checks admission before task execution, isolates optional client capability
failures from backend queries and preserves authority/fence failures. Publication
uses immutable versions, CAS binding and readback; the live namespace binding
passed read-only verification. Joint browser testing completed a query with four
durable progress updates, and exposed negated-action task inference causing a
false verification pause. That shared core defect and misleading interrupt copy
are fixed with regressions. API/worker images and frontend are rebuilt; activation
and exact negated-query replay remain user-operated. See
`docs/CLIENT_RELEASE_CLOSURE.md` for evidence and the acceptance boundary.

2026-10-02: `CLOUD-PROGRESS-OUTPUT-01` reuses Zebra's already durable
`MODEL_RESPONSE_*` events and AG-UI `zebra.model_response` stage marker.
Trench now projects user-facing tool-loop text as bounded `public_update`
events, persists/deduplicates them in Turn metadata, replays them across SSE
and snapshots, and renders them separately from candidate/final answers.
Legacy progress strings still render. Focused paired validation and the
service-restart/live acceptance boundary are in `docs/CLOUD_PROGRESS_OUTPUT.md`.

2026-10-02: `CLIENT-RESUME-LIVENESS-01` fixes canonical browser/child resume
commands, adds bounded receipt/expiry reconciliation and visible rejected-resume
outcomes, and prevents stale receipts unlocking a new wait. Trench separates
business progress from SSE heartbeats; SDK summaries preserve live Turn status.
The affected live session and Trench Turn reached completed after one additive
repair, without restarting services. Validation and user-operated restart boundary:
`docs/CLIENT_RESUME_LIVENESS.md`.

2026-10-02: `CLOUD-RECOVERY-CLOSURE-01` implements bounded tool/provider recovery,
durable legacy Cloud STOP handling and truthful partial delivery on
`codex/cloud-recovery-closure`. Expected tool exceptions become observations;
uncertain writes and emitted model streams are not transparently replayed.
Invalid command receipts prevent starvation, and admitted STOP survives delayed
processing without renewing execution authority. SDK feedback preserves outputs.
Acceptance and explicit live-deployment boundaries are recorded in
`docs/CLOUD_RECOVERY_CLOSURE.md`; pre-existing changes remain preserved.

2026-10-01: AGENT-QUALITY-02 follow-up fixed a delivery-gate false positive for
tool-returned media URLs. The Evidence Ledger now records bounded `images` /
`media` / thumbnail references separately from source citations, the citation
gate accepts only collected source or media URLs, and revision feedback names
the exact unsupported URL. Delivery assessments expose `media_refs`; focused
Harness coverage is green. Rebuilding the Worker and replaying the affected
Trench conversation remain separate runtime/browser acceptance gates.
2026-10-01 REACT-EXTERNAL-VIDEO-01: a Host-authorized `external_video` part
now has a reusable player in `@zebra-agent/react`. The paired Trench Host
tool resolves only entitled event video URLs; Turn metadata persists the
part for stream/replay without a video Artifact. The player constructs trusted
Bilibili/YouTube/Vimeo embeds, supports direct browser-playable files and
falls back to a source link for other sites. SDK 46 tests, type check and
package audit, plus paired Trench API 83 tests, frontend 162 tests and build
pass. The paired worktrees have not been merged or deployed; a live video
conversation and provider playback remain separate acceptance gates.

2026-10-01: `HAR-EGRESS-TOOL-ALIGN-01` is in Review on
`codex/egress-tool-alignment`. Cloud Worker no longer advertises networked
Web tools for `none`, `setup-only`, `mcp-proxy-only` or `git-proxy-only`;
Tool Gateway and Policy remain fail-closed if a tool call is fabricated.
Opt-in Web v2 `crawl`/`extract` now classify by URL and durable network
profile, while `read`/`find` remain cached local reads. Cloud v2 search
rejects `auto_fetch` to avoid unapproved secondary fetches; the optional
browser fetch provider is reserved for trusted-local, and Cloud uses the
existing no-redirect HTTP provider. Focused tests 113/113, full suite
excluding the inherited `test_host_egress.py` import blocker 4723 passed /
903 skipped, and `make check` pass. These commits are locally merged into
`cloud-agent-trench`; push and deployment remain separate gates.

2026-10-01: Blocked external read egress now returns a failed, non-executed
observation to the model without weakening the policy decision. Sequential and
concurrent regression tests plus agent-core and agent-security suites pass;
`make check` passes in the isolated verification worktree. Full `make test` is
blocked at collection by `test_host_egress.py` importing missing
`_resolve_pinned_gateway`. The fix is copied into the active
`cloud-agent-trench` checkout; runtime deployment and conversation replay are
not yet claimed. See `docs/HAR_POLICY_DENIAL_RECOVERY.md`.

2026-09-30 MEM-QUALITY-01 (in progress, paired Zebra/Trench): automatic
`command.run`/`tests.run` procedure extraction, refresh and promotion are
disabled; independent project rules, architecture facts, preferences and
procedures no longer supersede one another by type alone. A source-event and
old-generator exact-match check marks legacy command memories in scoped
inventory, and PostgreSQL Context materialization excludes these records from
Cloud recall before ranking. Trench Memory settings displays provenance and
offers confirmed, sequential, audited cleanup for the exact-match set; manual
memories and Session Events remain intact. Focused Zebra tests and paired
Trench `make check` pass (API/model `163`, pipeline `79`, frontend builds,
temporary migrations). Full Zebra pytest excluding
the inherited `test_host_egress.py` collection error passes `4724` with `899`
skipped; `make check` passes including release eval 30/30. A dedicated,
ephemeral PostgreSQL 17 instance ran Context materialization integration
tests `11/11` and was then stopped. The currently running Zebra containers
use a different image/version; this uncommitted change was not redeployed,
so live historical cleanup and cross-session browser acceptance are still
unverified. No commit, push or deployment is claimed.

2026-09-29 HOST-MEDIA-IMPORT-01: authority-scoped historical Host media can now
cross into Zebra's current-Session Artifact domain without accepting arbitrary
model-supplied URLs. The Trench adapter selects an entitled event attachment;
the Worker validates and bounded-downloads image/video content, publishes it
through the existing Artifact coordinator, and returns an `artifact://` URI for
the existing `content.present` and AG-UI path. A real browser Turn rendered the
imported JPEG inline with preview/download actions. Zebra focused tests and
`make check` pass; paired Trench focused and full checks pass. The task is in
Review; no commit, push, merge or deployment is claimed.

2026-09-28 TRN-SETTINGS-PRODUCT-01 (Trench product settings): the settings
center now uses a grouped user-facing information architecture instead of a
flat developer inventory. Personalization is separate from Agent capabilities;
startup/navigation replaces the roadmap-like Plan surface; internal API,
pipeline and unavailable-provider copy is removed. Existing profile, Memory,
personalization and local-preference authorities remain unchanged. Skill and
MCP management are preserved as first-class tabs under Tools & Connections,
including search/enable/reload behavior and MCP add/configure/list behavior.
Trench's frontend suite passes `151/151`, the production build passes, focused
ESLint is clean, and browser acceptance covers the core pages plus both
extension managers. No model/reasoning change, backend authority, merge, push
or deployment is claimed.

2026-09-28 TRN-SETTINGS-PRODUCT-01 appearance follow-up: Trench now offers six
persisted palettes (Ink, Graphite, Forest, Ocean, Amber and Clay) that compose
with system/light/dark mode and propagate through shared theme variables into
the dashboard shell, conversation rail, active navigation and settings
surfaces. Four user-supplied local WOFF2 subsets (DongFang DaKai, DaoLi,
ShuHei and LingDong) join the existing FangYuan fallback as selectable bundled
fonts; no CDN or runtime download is required. Invalid and legacy values safely
normalize to Ink/FangYuan. The frontend suite passes `154/154`, production build
and focused lint pass, and browser acceptance proves immediate palette/font
switching followed by restoration to the previous defaults. The supplied font
archives contain no bundled license text, so license provenance remains a
release-documentation follow-up rather than an implementation claim.

2026-09-27 CTX-OBS-02 (six-category context observability): every model call now
retains a typed V2 breakdown for messages, system tools, Skills, system prompts,
MCP tools and unattributed remainder while dual-writing the replay-compatible
three-category field. Tool origin and system-message provenance are classified
before invocation; category estimates are deterministically reconciled to the
provider input-token total without exposing prompt, Skill, credential or tool
payload text. The bounded Task summary and AG-UI custom event validate the exact
six-key schema and reject malformed totals. The host-neutral React Composer
renders dynamic categories, host colors, accounting basis, estimate method,
historical fallback and a responsive scrollable tooltip. Zebra focused tests
pass `77`; `make check` passes file-size, Ruff, strict Mypy over `984` sources
and eval `30/30`; the full suite passes `4700` with `901` environment-gated
skips. Under the required Node 24 runtime, the SDK passes `42` tests, package
audit, React 18/19 Vite/Next consumers and Chromium/WebKit browser matrices.
Paired Trench passes `127` tests, production build and production-browser
acceptance for all six labels and measurement metadata. The task is in Review;
merge, publication, deployment and a real-provider production Turn remain
separate evidence.

2026-09-27 CLOUD-MEMORY-AUTONOMY-01 (natural cross-Session Memory): natural
Chinese user self-statements now enter the existing governed Memory chain
without requiring “请记住”. Stable, non-sensitive response preferences reuse the
deterministic auto-promotion policy; background, goals, interests and portfolio
positions remain review-only. Portfolio records carry their asset subject in a
canonical form, preserve existing source/timestamp provenance and supersede only
an older confirmed position for the same asset. Confirmed interests and holdings
are exposed through the profile API, while relevance synonyms support later
Chinese or English recall. Trench's Memory page exposes the new categories,
warns that holdings are dated and not broker-synced, and preserves canonical
identity during edits. Focused Zebra coverage passes `49`; the broader
Memory/API/Worker/AG-UI group passes `180`; `make check` passes file-size, Ruff,
strict Mypy over `983` sources and eval `30/30`; the full suite passes `4694`
with `901` environment-gated skips. Trench's continuous `make check` passes
API/model `142`, pipeline `74`, ToC `121`, both production builds, migration
heads and offline upgrade, with three pre-existing image warnings. The task is
in Review. Commit, push, deployment, live PostgreSQL and production acceptance
remain separate evidence.

2026-09-27 CLIENT-TRENCH-PILOT-01 (first real Host Client integration): Trench
now captures six bounded Client State readables, creates and persists the
browser Surface before Agent command admission, and exposes the complete
eight-action profile through the authenticated BFF. The Host consumes packaged
`@zebra-agent/client-core`; the previous custom polling/receipt loop and its
unsafe three-failure Surface reset are removed. The SDK resumes the exact
server-mounted UI revision, adds durable HTTP polling when no SSE effect
stream is available, and separates transient `disconnect()` from final
controller release so navigation cannot invalidate the reconnect fence. AG-UI
admission resolves the profile version pinned by
the Client Session rather than the latest release, so profile growth cannot
break an old Run. Production Chromium proves `trench.ui.timeline.open`, five
injected Receipt failures, page reconnect, same-Receipt replay and exactly-once
handler execution without releasing the controller lease. Client State now
whitelists route query keys and strips
nested token/secret/password/cookie/authorization fields at both browser and
API trust boundaries. The operator release script reads the current Binding,
uses its CAS revision for upgrades and is a no-write replay for an identical
release. Zebra passes SDK 32/32, full 4675/897, check/eval gates
and the real PostgreSQL/API/Redis/Chromium/Worker recovery drill; Trench passes
141 API/model, 74 pipeline, 115 ToC, migration/build and browser gates. The
slice is in Review. A live real-model Trench Turn and production infrastructure
gate remain separate evidence, so no deployment or 100% production claim is
made.

2026-09-27 CLIENT-CONFORMANCE-01 (real-process Client recovery closure): the
multi-frontend suite now freezes old Run capabilities across Profile growth and
proves child Tasks do not inherit a parent browser-control channel. A repeatable
fault drill uses real PostgreSQL plus separate API, Chromium and Worker
processes: the browser executes one Client Effect, five Receipt attempts fail,
the API restarts, Redis is cleared, and the same browser profile reconnects.
The UI handler executes zero additional times, the retained Receipt commits and
replays idempotently, and a fresh Worker reconstructs the continuation solely
from PostgreSQL. The drill found and fixed an unbound `window.fetch` receiver
that raised `Illegal invocation` only in Chromium. Focused Client tests pass
16/16; SDK verify passes 30/30, package/React 18/19/Vite/Next/Chromium/WebKit;
`make check` passes over 982 typed sources and eval 30/30; the complete
repository passes 4671 with 897 environment-gated skips. The task is in Review;
Trench Pilot and production release remain separate gates.

2026-09-27 CLIENT-CONTEXT-01 (durable Client State recovery closure): the AG-UI
admitted, redacted Client State snapshot is confirmed on the durable accepted
command and is recovered by the Worker composition after reopening the Event
Store. Recovery now treats an explicit empty snapshot as the latest authority;
it no longer skips that snapshot and revives stale state from an older page.
The focused recovery/context/projection matrix passes 11/11. Repository
`make check` passes the file-size gate, Ruff, Mypy over 982 sources and eval
30/30. The task is in Review; no commit, push or deployment is claimed.

2026-09-27 CLIENT-REACT-HITL-01 (durable React interrupt projection): the public
React package now accepts a `ZebraHitlSource` external-store projection in
addition to its existing controlled props. A remounted page synchronously reads
the durable open Approval/Clarification, while live projection changes notify
the same hooks. Observer replies and callbacks captured under an older
controller fence fail before Host submission; duplicate decisions remain
coalesced, idempotency keys stay deterministic, and choice-free clarification
supports typed text. HITL tests pass 3/3, the SDK suite passes 30/30, the full
package/React 18/19/Vite/Next/Chromium/WebKit gate passes, and existing
API/Worker approval/clarification recovery tests pass 31/31. The task is in
Review; no npm publication, push or deployment is claimed.

2026-09-27 REACT-CONVERSATION-02 (ZCode-style conversation organization): the
public React surface now groups every durable request as one Turn containing the
user prompt, public work segments, final answer and artifacts. Live work remains
expanded; successful/cancelled work folds; failed/blocked work remains
diagnosable. `AgentChat` keeps one controlled Composer DOM across the centered
landing and sticky active dock, remembers scroll position per conversation and
preserves explicit live-tail ownership. Trench consumes the packaged contract
through a pure Strategy projection while retaining its business renderers and
all model/reasoning settings. SDK `verify` passes `27/27`, package audit,
React 18/19 Vite/Next, Chromium/WebKit and hydration checks; Zebra `make check`
passes over `978` sources and eval `30/30`; Trench `make check` and production
Chromium Host acceptance pass. A browser gate exposed and closed a real narrow
viewport 10px-grid regression. No npm publication, commit, push or deployment
is claimed. The follow-up AG-UI pixel pass now matches the public ZCode
conversation shell: a 672px centered draft, responsive 896px/1152px active
columns, 56px desktop/40px mobile Turn rhythm, long-input folding, icon-only
live-tail control, 20px flow gaps and a 16px Composer shell with focus feedback.
The large Zebra rail and `Live` badge were removed. Chromium/WebKit and the
Trench production browser assert computed geometry and empty/active transitions;
Trench's 1510px Dashboard cap correctly selects the 896px embedded tier. The unrelated
base-branch Python quality-gate collection mismatch is recorded separately and
was not folded into this UI task.

The SendBar follow-up closed the remaining vertical-layout defect. `AgentChat`
previously reserved two grid rows even when no header was rendered, so the
viewport shrink-wrapped content in the first row while an empty second row
consumed the remaining height. Headerless chats now select one `minmax(0,1fr)`
row, and the stage fills that scroll viewport. Chromium/WebKit assert zero
composer-to-viewport and viewport-to-chat bottom offsets; Trench additionally
asserts chat/workspace/shell/window alignment after cold reload. SDK `verify`,
Zebra `make check`, Trench `make check`, production build and browser acceptance
all pass; no commit, push, publication or deployment is claimed.

The reusable React surface now also exposes a typed Host theme boundary rather
than freezing Trench's current colors into the package contract. `AgentChat`
and standalone `AgentComposer` accept partial `AgentThemeTokens` covering ten
colors, five geometry values and the font family; equivalent CSS custom
properties remain available for stylesheet themes. Unspecified values preserve
the reviewed defaults. Unit/package-entry tests and packaged Chromium/WebKit
consumers verify both direct application and nested Composer inheritance;
Trench's production build and Strategy browser acceptance pass with the
refreshed local artifact. No npm publication, commit, push or deployment is
claimed.

The Composer backdrop follow-up removes the package-owned sticky-dock gradient
that became a black rectangular band when a Host used a darker `surface` token
than its page background. The dock is now transparent; the actual Composer
retains its Host-controlled input surface, border and focus treatment. The
packaged Chromium/WebKit matrix and Trench production browser acceptance guard
both `background-color: transparent` and `background-image: none`.

The conversation-width follow-up closes the remaining intrinsic-sizing leak:
the package now applies `min-width: 0`/`max-width: 100%` through the complete
chat-to-message chain, while the Trench Host constrains Markdown tables and
long text to the conversation column. Packaged Chromium/WebKit checks and the
Trench production browser fixture reject any message node that escapes the
content boundary, including long prose, URLs and multi-column tables.

2026-09-26 CLOUD-PLAN-ACCEPTANCE-02 (current-version strict closure): the fixed
live-eval catalog now materializes isolated fixtures and records independently
verified real Zebra runs. The selected current-version matrix is complete at
`180/180`: first-attempt success `95%`, final success `100%`, false completion
`0%`, citation support `100%`, recovery success `100%`, human intervention `0%`,
average first public feedback `428ms` and total duration `9.512s`. Shared fixes
expose bounded failed-command diagnostics to the model, normalize standard Git
patch paths, reject mismatched hunk counts before partial writes, allow only
workspace-contained absolute command cwd values, isolate fixture Git roots and
classify scheduled jobs as operations. SDK/React, Trench browser/build, real
PostgreSQL/MinIO and repository gates pass; final Zebra is `4668 passed, 897
skipped`, with file-size, Ruff, strict Mypy over `982` sources and eval `30/30`.
Local implementation is complete; strict evidence is `86/100`. Production is
still `0%`: no local `runsc`, no accepted remote SSH authority, and therefore no
same-digest gVisor, immutable candidate, canary or rollback proof. Model and
reasoning settings are unchanged; PostgreSQL remains authoritative.

2026-09-26 CLOUD-PLAN-CLOSURE-01 (local implementation closure): Trench now
imports `AgentComposer` from reproducible vendored `@zebra-agent/react` tarballs
and the duplicate Host component is deleted. Exact package tarballs pass React
18/19 with Vite and Next 15.5.18 SSR/RSC; SDK tests pass `24/24`. The live-eval
contract now fixes 60 cases (10 per category), 36 development / 24 holdout and
three independent repetitions, producing an exact 180-attempt plan. It rejects
self-reported tiers, reused execution identities, tampered capture/verifier
payloads and incomplete metrics; no attempt was fabricated, so the real-model
campaign remains `0/180`. Real PostgreSQL gates pass `39`, `8` and `27` cases;
application Compose passes; the Effect composition tier passes and preserves a
retryable READY Session when gVisor is unavailable. Deterministic attachment,
MCP and other configuration defects still terminate fail-closed. Zebra `make
check` passes file size, Ruff, strict Mypy over `982` sources and eval `30/30`;
the final full suite passes `4655` with `897` skips. Trench passes `107/107`,
production build and offline frozen install. Local implementation is `100/100`.
Production remains `0%`: no local `runsc`, remote SSH/HTTP time out, and no
immutable candidate, canary, rollback, commit, push or deployment is claimed.

2026-09-26 CLOUD-RELIABILITY-02 (local reliability/release closure): canonical
Task projection now rejects missing sequences in addition to duplicate and
out-of-order events. An invalid persisted browser cursor no longer causes an
infinite loop or unsafe full replay: the API returns the exact authoritative
Task-tail cursor, the HTTP route now actually forwards the standard
`Last-Event-ID` header, client-core persists the replacement, re-reads
authoritative pending effects to close the race, and resumes from that point. Expired login or Client
Session responses (`401/403/410`) stop reconnecting. The immutable candidate
now freezes all four React SDK package versions and rejects versions that do not
match source package metadata; rehearsal evidence explicitly covers stream
integrity, cursor/login expiry, multi-session concurrency and failures before a
Tool call, after an external write and before terminal completion. Focused
Python reliability coverage passes `95` with `27` PostgreSQL-dependent skips;
TypeScript/React passes `24/24`. `make check` passes file-size, Ruff, strict
Mypy over `980` sources and eval `30/30`; the complete suite passes `4643`, with
`897` environment-dependent skips. Docker and a local PostgreSQL test DSN were
unavailable, and no immutable clean-SHA image set or production host rehearsal
was supplied, so real dependency and production gates remain unexecuted. Under
the frozen delivery weights, S6 local implementation is `100%` and total local
implementation advances from `71%` to `91%`; production release remains `0%`.
No model/reasoning setting, commit, push or deployment changed.

2026-09-22 MEMORY-CONTEXT-02 (local memory/context/cache closure): durable
Context Capsule and Handoff v1.1 now keep completed actions, pending actions,
rejected approaches and permission boundaries as separate typed facts through
manual/Worker compaction, materialization, recovery and cross-session handoff.
Permission omissions fail closed. Governed recall now bridges bounded common
Chinese/English paraphrases while removing single-character CJK noise; the
existing authority lifecycle still owns preference correction, temporary
context rejection, deletion suppression and scope isolation. Observability now
reports cold start, warm loop, recovery, compaction and child wakeup cache
metrics separately using raw hit/miss tokens, rate and latency. Focused closure
passes `156/156`; `make check` passes over `980` typed sources and eval `30/30`;
the complete suite passes `4640`, with `897` environment-dependent skips. Real
PostgreSQL execution was unavailable locally and is not claimed. Under the
frozen delivery weights, local implementation advances from `61%` to `71%`;
production release remains separate. Model/reasoning settings are unchanged,
PostgreSQL remains authoritative, and no commit, push or deployment occurred.

2026-09-22 AGENT-LIVE-EVAL-01 (local evaluation contract): Zebra now has 12
fixed representative tasks across answer, research, code, file, operation and
memory/recovery, split `8/4` between development and holdout and fixed at three
repetitions. The report keeps real-dependency and real-model evidence separate,
rejects duplicate/out-of-range attempts, and emits no success, latency,
intervention, citation, recovery or cost metrics until all 36 attempts exist.
Provider cost may remain unavailable without being treated as zero. The first
real DeepSeek smoke proved the distinction between runtime and product success:
the read-only Harness completed in 34.27 seconds with 9 model calls and 20 tools,
but the externally checked answer was 703 characters against a 180-character
limit and therefore failed the task postcondition. The complete 36-run campaign
has not been executed, so no product success rate is claimed. Model and
reasoning settings were unchanged; no commit, push, publication or deployment
is included. The repository passes `make check` and `4621 passed, 897 skipped`.

2026-09-22 REACT-UX-01 (local lifecycle boundary): `@zebra-agent/react` now
exports a typed `AgentRunStatus` integrated with `AgentChat`. Local submission,
server acceptance, queueing, execution, user wait, pause, reconciliation,
disconnection and terminal state are no longer collapsed into one loading or
error state. `completed`, `partial`, `blocked`, `failed` and `cancelled` remain
distinct. Reconnect, continue-current-task and retry-original-request are
separate Host callbacks; reconciliation suppresses blind replay. The public
contract accepts only a Host-approved safe message and opaque diagnostic ID,
not raw errors or private reasoning. Empty-to-active rerenders retain the same
controlled Composer DOM node, value, attachment and focus, while durable
terminal state collapses stale running activity. SDK tests pass `22/22`; exact
tarballs pass Vite 6.4.3 and Next.js 15.5.18 production builds without Node
built-ins, and browser acceptance confirms the lifecycle card and collapsed
work log. Full Zebra remains `4614 passed, 897 skipped`; file-size, Ruff,
strict Mypy over 978 sources and deterministic eval `30/30` pass. Trench
mapping, npm publication and production deployment are not claimed.

2026-09-22 REACT-UI-01 (local React component boundary): the existing
`@zebra-agent/react` package now exports a host-neutral controlled `AgentChat`,
Composer, message list, public activity group, approval, clarification,
Artifact and Memory-setting surface with explicit scoped styles. The Host
retains routing, state, credentials and execution side effects; the package
owns only interaction and presentation. Attachments, suggestions, queue state,
submit/pause/continue, capability/model/reasoning controls and truthful
context/cache metrics are covered without Ant Design, Tailwind, Trench imports
or another runtime.
Deterministic interaction coverage includes Enter, IME suppression and action
state transitions. Final tarballs passed Vite 6.4.3 and Next.js 15.5.18 React
19 production builds with no source aliases or Node built-ins; real-browser
narrow-layout, keyboard, activity-collapse and no-overlap acceptance passed.
SDK tests are `19/19`; full Zebra
remains `4614 passed, 897 skipped`, with file-size, Ruff, strict Mypy over 978
sources and deterministic eval `30/30` green. The API is ready for a separate
Trench Host-adapter migration; no npm publication, commit, push or deployment is
claimed.

2026-09-21 REACT-PKG-01 (local package boundary): the full Cloud Agent + React
optimization plan is now durable under `docs/`. The existing four TypeScript
packages use explicit package dependencies rather than sibling `src` imports,
and TSDX 2.0.0 now builds ESM, CJS and declaration artifacts for each package.
The build pins bunchee 6.4.0 because the TSDX release invokes its dev-only CLI
without shipping it as a runtime dependency. Package tarballs contain only
`dist` plus metadata and have no repository path leakage. An isolated TypeScript
consumer passed ESM, CJS and server-render checks; Vite 6.4.3 and Next.js 15.5.18
React 19 production builds consumed the same tarballs without source aliases.
SDK strict type-check and `17/17` tests pass. The packages remain private and no
npm publication, Trench component migration or production deployment is claimed.
The complete Zebra suite also passes `4614 passed, 897 skipped`; `make check`
passes file-size, Ruff, strict Mypy over 978 sources and deterministic eval 30/30.

2026-09-21 CLOUD-CAPABILITY-UI-01 (adaptive budget regression closure): the
capability-mode adapter no longer reintroduces fixed `10/16`, `16/32` or `24/64`
model/tool ceilings into interactive Tasks. Exploration, research and expert
conversations now omit both fields and continue until normal completion,
cancellation, approval, policy, repeated-action, context, runtime or provider
limits stop them. Explicit administrative, scheduled and evaluation budgets
remain deterministic, but Task admission now accepts any positive integer rather
than enforcing a magic maximum. `trench-native-v15` forces existing conversations
onto the corrected admission snapshot. Focused Zebra API tests pass `22/22`;
Trench runtime tests pass `35/35`; both complete repository gates pass. A
follow-up in browser conversation `conv_1789911230325_53c036` completed after
migration from v14 to v15. Its successor Task
`00c328d5-fa91-4306-bb44-6eef45867b67` records `null` for both call budgets while
retaining `coding` and `full_access`. Model and reasoning settings are unchanged.
No commit, push or remote deployment is claimed.

2026-09-20 CLOUD-AGENT-PARITY-01 (local closure): Zebra now receives a typed
task acceptance contract (`answer`, `research`, `change`, `create`, `operate`)
from each Host and applies task-specific evidence, citation, artifact and
postcondition gates. Trench's AG-UI context is materialized into Worker/model
context instead of being silently discarded, and generic modes no longer force
subscription-report identity or a fixed report length. Completion records
durable delivery assessment, distinguishes completed/pending/blocked outcomes,
and suspends mutations that lack verification instead of claiming success.
Replay/eval contracts now grade terminal outcome, delivery, evidence, artifacts
and failure truth across 30 deterministic cases in 10 categories. Reusable
frontend types moved into dependency-free `@zebra-agent/ui-contracts`, leaving
the React package extraction until a second Host proves the component API.
Trench now selects enabled Skills conservatively or explicitly rather than
binding every installation to every Task, and clears rejected candidate text
before retry so only a committed answer remains user-visible. Zebra passes
`make check`, eval `30/30`, and `4577 passed, 892 skipped`; SDK type-check and
`15/15` tests pass. Trench passes its complete gate (`136`, `74`, and `91`
tests plus lint, builds, migrations and diff check). Browser conversation
`conv_1789910351988_0397a0` completed with one answer/model call, no tools,
failure, or unrelated Skill; rebuilt local API/Worker containers are healthy.
Model and reasoning effort were unchanged. No commit, push or remote deployment
is claimed.

2026-09-20 AGENT-QUALITY-03 (local acceptance closure): Cloud replies now retain
a continuation-safe evidence ledger, exact source references, truthful failed
tool status and one typed committed answer. Host tools are filtered by the
active Grant, broad Trench retrieval is bounded, and the final permitted model
call synthesizes collected evidence instead of suspending before an answer.
The final-quality gate rejects invented or extended URLs and no longer mistakes
words such as `CONCURRENT` for freshness claims. Real browser conversation
`conv_1789903152657_6847d3` reached first public activity in 1.29 seconds and
completed with 6 model calls, 14 successful tools, 7 findings and 21 exact
source links; a cold reload restored the terminal timeline and committed answer.
Zebra passes `4573 passed, 892 skipped` plus file-size, Ruff, strict Mypy over
968 source files and Harness eval 10/10. Trench passes its complete `make check`
including 129 Python tests, 74 cleaning tests, 89 ToC tests, lint, builds,
migrations and diff checks. This is local acceptance only; no commit, push or
deployment is claimed, and DeepSeek Flash with high reasoning was unchanged.

2026-09-20 AGENT-QUALITY-02 (audit closure): the reply-quality remediation now
preserves structured tool status and recoverable Artifact references, reports
attachment/context coverage explicitly, carries continuation state across
approval/clarification/child wakeup, and separates candidate model text from a
typed authoritative `ANSWER_COMMITTED` event. Finalization receives the actual
draft plus exact unmet acceptance requirements, permits one bounded revision,
and suspends rather than reporting completion when delivery requirements still
fail. The eval gate now executes the deterministic Harness and stores its trace
artifact instead of constructing replay values from thresholds. `make check`
passes file-size, Ruff, strict Mypy over 964 sources and Harness eval 10/10; the
full repository passes `4565 passed, 892 skipped`; the Trench committed-answer
consumer regression passes 10/10. This was local-only: model reasoning effort
was unchanged, and live-model A/B, deployment and production acceptance were
not run.

2026-09-20 CLOUD-REMEDIATION-R14 (implementation): immutable rollout candidates
now bind Zebra/Trench commits, digest-pinned images, database/protocol/config
coordinates and the exact R13 release manifest. A second fail-closed validator
requires internal/canary/full phase evidence plus all G2 dependency, browser,
fault and G3 rollback scenarios; capability-disabled checks remain explicitly
`NOT_ENABLED`. The runbook fixes deployment and rollback order and forbids
automatic database down-migration. Local tests pass; real G2/G3 remain open
because `192.168.110.30` currently accepts TCP/22 but times out or closes before
SSH authentication, while port 18080 times out or returns an empty response.

2026-09-20 CLOUD-REMEDIATION-R13: cloud release checks now have explicit L1-L6
Make/CI entry points, JUnit and credential-free gate envelopes, clean candidate
binding and capability-aware `PASS`/`FAIL`/`NOT_ENABLED` aggregation. Fixed-label
event summaries expose queue/model/tool/client/turn latency without identity
labels. L1 `54`, L2 `35`, real PostgreSQL L4 `39`, and all five L3 service
runners pass. The named 10/100/1000-session local scan stayed at 9 queries per
scan with p95 `35.691-37.647ms`; it is a regression baseline, not a capacity
claim. The R00 Ruff blocker is closed. Trench browser and target gVisor evidence
remain required inputs to G2/G3 rather than being marked successful.

2026-09-20 CLOUD-REMEDIATION-R12: sandbox stdout/stderr capture is now bounded
while both pipes continue draining, with UTF-8-safe output and truthful
truncation flags on completion and timeout. OCI defaults and pinned engine calls
use process-tree termination. Compose no longer exposes Docker Socket or
`DOCKER_HOST` to API; engine authority remains Worker-only. Runtime, security,
Worker and Compose regressions pass with `751 passed, 11 skipped`. The current
local engine advertises no `runsc`, so target gVisor execution/cleanup remains an
explicit G2/G3 release gate rather than an inferred success.

2026-09-20 CLOUD-REMEDIATION-R07 (implementation): Client Effects now preserve
their Task/Run, Surface, capability digest, expected UI revision, deadline,
request digest and idempotency key through PostgreSQL, Worker metadata, REST and
AG-UI. Sparse historical events remain readable but cannot execute. The
TypeScript runtime persists its SSE cursor, replays receipts, rejects stale
bindings and never restarts an interrupted handler after refresh. Explicitly
mounted Client State is profile/schema bounded, redacted before persistence,
recovered after Worker restart and projected under a field-owned `/client`
namespace; ordinary server-owned AG-UI state remains backward compatible.
Trench commits `63c9ba9` and `5650b19` add a same-origin BFF and fenced dashboard
bridge without exposing HostGrant or business-write actions. Focused Zebra
Python `20`, SDK `15`, Trench BFF `1` and frontend `2` tests pass with focused
Ruff/Mypy/ESLint. Full Zebra regression passes with `4513 passed, 891 skipped`;
real PostgreSQL/profile/browser acceptance remains open before R07 leaves In
Progress.

2026-09-19 CLOUD-REMEDIATION-R05: Host Effect delivery and recovery now retain
three distinct truths: transport outcome, business outcome, and a bounded
durable Host receipt. A write is successful only with an applied/succeeded
receipt, provider operation ID, and business revision; a proven no-effect
rejection is terminal, while timeout, response loss, 5xx, invalid payloads,
and missing commit evidence remain uncertain. The PostgreSQL outbox exposes a
fence-checked bounded uncertain scan, Worker startup reconciles those receipts
through the pinned signed Host path, and settlement updates the existing
dispatch atomically without replaying the write. Focused regressions pass `42`
with `23` PostgreSQL-dependent skips; the full suite passes `4474` with `887`
skips; file-size, targeted Ruff, strict Mypy over `949` sources, and diff checks
pass. `make check` reaches only the unchanged R00 Ruff import-order baseline in
`apps/api/src/zebra_agent_api/host_auth.py:3`.

2026-09-19 CLOUD-REMEDIATION-R10: finalization now treats unresolved mutation
evidence as a hard truth gate. A mutation that cannot be closed by a fresh read
returns a user-visible unverified partial result, suspends with the dedicated
`verification_required` reason, and cannot emit `SESSION_COMPLETED`; AG-UI
projects the suspension as a recoverable interrupt. Frozen cloud Skills carry
their exact skill ID, version ID, and digest into the Harness and completion
accepts only a matching `skills.read` result. Missing Skill tools fail closed.
The prose gate remains a single bounded soft revision and the generic Chinese
word “分析” no longer imposes a 320-character threshold by itself. The full
suite passes `4468` with `887` skips; the affected regression set passes `827`,
file-size/Ruff/strict Mypy over `947` sources/diff checks pass. Repository
`make check` reaches only the pre-existing R00 Ruff import-order baseline in
`apps/api/src/zebra_agent_api/host_auth.py:3` after the file-size gate passes.

2026-09-19 CLOUD-REMEDIATION-R06 (closeout): resource-scoped mutations now
retain bounded mutation evidence and fresh reads append structured
`VerificationEvidence` with effect/receipt refs, commit/read versions,
observed epoch, postcondition, and verified/unverified/stale/failed status.
When a Host supplies a commit version, a missing or different read version
cannot close the mutation. Global local-tool fallback remains compatible, while
Host verification requires the trusted authority-qualified resource ref.
Focused quality/loop/Host tests pass `17`; targeted Ruff, Mypy, and diff checks
pass. R10 can now consume the frozen evidence contract without re-inferring
resource identity.

2026-09-19 CLOUD-REMEDIATION-R06 (part 1): resource verification is now
epoch-safe and authority-qualified. A read from the same concurrent batch can
advance only to its captured `observed_epoch`, never to a mutation completed in
that batch. Host results carry an explicit resource identity derived from the
frozen Task binding issuer plus namespace, Host, resource type, and resource
ID; Host freshness no longer falls back to arbitrary `_id/name/path` fields
when that trusted identity is absent. The `VerificationResourceRef` and
`VerificationEvidence` contracts are added for the remaining evidence and
R10 consumption work. Focused Core/Worker tests pass `27`; targeted Ruff,
Mypy, and diff checks pass.

2026-09-19 CLOUD-REMEDIATION-R04: pinned Host egress no longer manufactures
`compat:{credential_ref}` tokens. API manifest freeze and Worker execution now
adapt the configured `ZEBRA_HOST_TOOL_SHARED_SECRET` through the existing
`HostWorkloadCredentialResolverPort`; the bounded HMAC adapter keeps the secret
out of repr/logs, validates HTTPS audience and TTL, and returns only an
in-memory credential. A pinned connector without a configured credential fails
closed. The unused production compat issuer was removed. Focused API,
integration, Worker, and freeze tests pass `21` with `4` PostgreSQL skips;
targeted Ruff, Mypy, and diff checks pass. OAuth/mTLS remains a replaceable
adapter choice rather than a prerequisite for the configured HMAC deployment.

2026-09-18 CLOUD-REMEDIATION-R03: Worker gateway composition now retains the
  configured ClientToolGateway in pinned Host, local-only, and no-legacy-egress
  branches; previously only the legacy Host path preserved it, silently
  removing front-end capabilities in the other modes. Host/client/extension
  composition checks pass `17`; targeted Ruff and diff checks pass. No
  credential, schema, deployment, or Trench worktree change was made.

2026-09-18 CLOUD-REMEDIATION-R02: cloud workspace snapshots now use the
  `workspace-snapshot:<artifact_id>/<sha256>/<size>/<object_version>` URI
  contract. The reader validates and reuses the original artifact identity
  instead of generating a new UUID, and the writer emits the same parseable
  prefix it expects. URI round-trip and legacy-shape rejection tests pass;
  focused workspace tests pass `18`, targeted Ruff and diff checks pass. No
  schema, object deletion, deployment, or Trench worktree change was made.

2026-09-18 CLOUD-REMEDIATION-R01: Manifest resource-binding rules now belong
to the canonical Host manifest payload and digest when explicitly declared.
`HostToolManifest.to_payload()` preserves those rules through PostgreSQL
freeze/recovery, while legacy manifests without declared rules retain their
existing digest and legacy inference behavior. Focused integration,
conformance, and storage-boundary validation passes `29 passed, 4 skipped`;
targeted Ruff and diff checks pass. This slice has no credential, Worker,
schema, deployment, or Trench worktree change.

2026-09-18 CLOUD-REMEDIATION-R00: the Zebra/Trench remediation plan baseline
was re-collected and registered. Zebra is at `026f59ef` (the plan baseline
`07dca873` plus the prior GPL license commit) with a clean worktree; Trench is
at `05c6bc1` with pre-existing dirty work intentionally preserved. The runtime
fingerprint records the production compose files, container image digests,
PostgreSQL 16.11, and Alembic `3c4d5e6f7081` without recording secrets. Zebra
file-size and test collection checks pass; the baseline `make check` gate stops
at one pre-existing Ruff import-order error in `apps/api/.../host_auth.py`, so
Mypy and eval were not run in that sequence. No production code, deployment,
schema migration, or Trench worktree mutation was performed. R01/R02 remain
separate implementation slices after the G0 evidence package is committed.

2026-09-16 AGENT-QUALITY-02: the Cloud Agent quality-loop repair is implemented
in-place on `cloud-agent-trench`. Finalization now enforces selected Skill reads,
revises shallow substantive deliverables once, and records a bounded warning if
the second answer remains weak. Mutation freshness is resource-scoped when a
tool exposes an id/url/path and keeps a global fallback for opaque mutations;
Host business errors retain bounded detail/code metadata. Research children
inherit the selected Skill components. Trench native source mutations now
reject ambiguous `sources.add` arguments and schedule an immediate RSS refresh
after add/resume, with periodic fallback truthfully reported. Zebra `make check`
passes (file-size, Ruff, strict Mypy over 945 sources, Eval 10/10); focused
quality/runtime tests pass 49, and the full suite reached 4446 passed, 887
skipped; the two timing-sensitive baseline failures passed in isolation. Trench
targeted tests pass 25/25; the stale custom-website fixture now uses a true
website URL while X URL normalization remains covered by native-history tests.
Acceptance images were rebuilt
from the current source; API, Worker, Scheduler, and Trench live/readiness
health checks are green.

2026-09-16 AGENT-QUALITY-01: the in-place Cloud Agent quality repair is ready
for review on `cloud-agent-trench`. Frozen selected Skills are now available to
the Trench coordinator and must be resolved/read before substantial output.
Declared business mutations enter an unverified state, allow a fresh repeated
read, and receive one bounded verification turn; tests and generic commands are
not misclassified as business writes. Cloud conversation history grows from
8192 to 32768 bounded tokens. Trench source reads project current user
subscription truth, while AG-UI marks `tool_loop/final` responses so live
progress remains visible but only the final response becomes the durable body.
Zebra affected suites passed 800 plus a 40-test classification regression;
the deterministic full suite excluding the live-provider smoke passed 4441
with 887 skips. Ruff, strict Mypy over 943 sources, file-size, Eval 10/10 and
diff gates pass. The live DeepSeek smoke's tool call returned reasoning_tokens=0
and fails only its external reasoning-presence assertion. Trench's affected
group passed 42 with target Ruff/diff green. Existing dirty work is preserved;
no commit, push, deployment, restart, or browser acceptance is claimed.

2026-09-16 CTX-SEG-03: budget-governance repair is ready for review on
`cloud-agent-trench`. Trench interactive tasks no longer inject implicit `6/16`
model/tool limits. The harness no longer reserves the final permitted model call
as a tool-disabled synthesis turn: that call retains tools, and only a required
subsequent model request causes structured `model_call_budget_exhausted`
suspension. AG-UI now closes explicit budget suspensions with a recoverable
interrupt while leaving internal `waiting_children` suspension untouched.
Core/AG-UI suites pass `948` with `1` skip; the focused regression passes `24`.
File-size, Ruff, strict Mypy over `942` source files and Eval `10/10` pass. The
full suite passed `4439` with `887` skips; its only failure was a pre-existing
module-level 30-second clock-window test that passed alone. Trench's affected
group passes `35`; its Python gate remains at the recorded baseline of `121`
passes plus 5 unrelated `_IncludedRouter` failures. No commit, push, deployment,
or browser acceptance is claimed.

2026-09-15 CLOUD-USER-SCHEDULE-DEPLOY-01: The independent Scheduler is now
composed beside the API and Worker in the real Trench acceptance stack. Trench
ToC provides logged-in user schedule CRUD, controls and durable run history;
the BFF binds opaque host workspaces and enabled Skills with separate one-use
Host grants. Scheduled execution now submits the standard RUN command, so its
Turn freezes normal Skill/MCP admission and uses the RabbitMQ wakeup path.
Terminal Task state is reconciled into durable Firing state. The logged-in
browser shows the latest manual run as `9/15 16:02 已完成`; its PostgreSQL Turn
snapshot contains Skill `1` and MCP `1`. Runtime/broker `24`, actual PostgreSQL
`13`, Trench API `6`, and ToC `78` tests pass, together with Zebra file-size,
Ruff, strict Mypy over `942` sources, Eval `10/10`, frontend ESLint and build.
This local slice is in Review; remote deployment remains separate.

2026-09-15 CLOUD-USER-SCHEDULE-API-01: The user schedule management surface is
implemented on `codex/cloud-user-schedule-api`. Verified Host grants now expose
owner-scoped create/list/get/update/delete, pause/resume, idempotent run-now and
run history with Task deep links. Schedule template changes pass through the
normal Task/Skill/MCP/Definition admission rules and atomically rotate the
immutable authority binding; optimistic versions protect every lifecycle write.
The focused API/Core/Storage group passes `824` with `37` dependency skips,
actual PostgreSQL schedule tests pass `9`, and file-size, Ruff, strict Mypy over
`941` sources plus Eval `10/10` are green. The full repository suite passes
`4429` with `887` dependency skips. Frontend, Trench UI, deployment and browser
E2E remain future slices.

2026-09-15 CLOUD-USER-SCHEDULE-STORAGE-01: User-level Task schedules now have
forward-only PostgreSQL v58 authority. Schedule and authority reads require all
owner coordinates; lifecycle and revocation writes use optimistic concurrency;
due pickup uses database time plus `FOR UPDATE SKIP LOCKED`; deterministic
Firings survive duplicate pickup and expired claims; misfire and overlap skips
remain durable evidence. Actual PostgreSQL tests pass 7, full Storage passes 361
with 799 externally gated skips, and full Core passes 763. API, Scheduler process,
Task materialization, RabbitMQ wakeup, UI and deployment remain future slices.

2026-09-15 CLOUD-USER-SCHEDULE-CORE-01: The first user-level scheduling slice
is implemented on `codex/cloud-user-schedule-core`. Core now owns immutable
Schedule, Trigger, Firing, secret-free authority and storage Port contracts,
plus deterministic IANA-timezone next-fire calculation. Once/interval/daily/
weekly rules, DST gap/fold behavior, monotonic lifecycle evidence and stable
Firing identity are pinned by 19 focused tests; the complete agent-core suite
passes 763, with Ruff, strict Mypy and diff checks green. PostgreSQL, API,
Scheduler process, RabbitMQ materialization, UI and deployment remain separate
unstarted slices.

2026-09-14 TRN-DEEPSEEK-V41-MM-01: DeepSeek V4.1 Flash replaces the historical
dual-channel Vision design. The stable Zebra Flash profile now calls the official
`deepseek-flash` alias and accepts validated JPEG/PNG/GIF/WebP attachments through
the existing durable Artifact path. Worker recovery verifies session ownership,
size and digest before attaching transient image content to the current USER
message; Chat Completions and Responses serializers emit their native image
parts. Trench exposes image selection on the existing plus button and switches
image requests from Pro to V4.1 Flash. A real Responses API request with an inline
PNG reached `deepseek-flash` successfully; V4.1 tool calls that omit an optional
reasoning item are also accepted without exposing or fabricating reasoning.
Focused tests, `make check`, and the full suite (`4401 passed`, `875 skipped`)
pass. No deployment or logged-in Trench browser image submission is claimed.
Follow-up browser acceptance exposed a stale PostgreSQL check constraint that
admitted `research` but not the current `research_coordinator` ToolProfile.
Forward migration v57 now accepts all domain ToolProfile values without
rewriting migration v29; a focused regression pins that enum/schema parity.
The existing acceptance database upgraded to v57, Extensions remained enabled
with the original read-only key mount, and a real logged-in Trench conversation
completed through API/Worker with `POST /tasks` 201. Focused checks passed 11;
`make check` passed file-size, Ruff, strict Mypy over 924 sources and Eval 10/10.

2026-09-14 DESKTOP-COMPOSER-UX-01: Desktop Cloud Agent composer is now a
compact command bar with attachment, truthful current permission, task config,
actual model/reasoning labels, and an SVG context-capacity ring. The popover is
derived exclusively from durable model request/response usage and reports the
latest input-window utilization plus weighted session prompt-cache hit rate; it
does not estimate tokens or expose private reasoning. One primary action now
switches between send, pause, and continue. While a Turn is running, typed
supplements remain visible in a bounded eight-item browser queue and are
submitted sequentially at safe Turn boundaries; the local optimistic message is
reconciled by the durable event stream without a blank-frame flicker. Existing
session control and authority contracts are unchanged. Build, all Desktop checks,
diff check, and browser layout/popover inspection passed; local API connectivity
was not available for a live execution/pause acceptance. No commit or push.

2026-09-14 TRN-SUBAGENT-UX-02: Trench Tasks now use a least-privilege
`research_coordinator` profile: the existing research read/publish surface plus
durable `agent.research`, without command, patch, Git or test tools. The
capability generation advances to v13 so the next Turn replaces existing
admission-frozen research Tasks instead of silently retaining the old profile.
Zebra projects safe child lifecycle metadata over AG-UI and exposes an
authoritative read-only parent-child Task query; child summaries and reasoning
remain private. Trench persists lifecycle events in the durable Turn stream and
renders one merged row per child in an opt-in detail panel that stays collapsed
after completion. Focused Zebra 17 tests, Ruff, file-size gate and Mypy over 915
sources passed; Trench 44 backend and 14 frontend tests plus focused ESLint
passed. The local acceptance Zebra API/Worker were rebuilt and are healthy; the
running images import the new profile/query and Worker tool set. A direct live
Task probe without a valid Host grant was correctly rejected with 401 and created
no Task, so logged-in Trench browser/model delegation remains unclaimed. No
commit or push.

2026-09-09 EXT-SKILL-UX-01: installed Skill reads enrich exact scoped/versioned
ready publication names, descriptions and version labels; no migration or object
downloads. Trench settings now provides a searchable readable list, details and
Radix enable switches, missing-metadata/empty/error feedback. Actual user's
better-writing name/description, purpose search and details verified in Chrome.
56 backend tests, 7 frontend tests, make check and focused ESLint pass. Full
frontend tsc remains blocked by three pre-existing dashboard-data-settings test
fixture type errors. API rebuilt with preserved environment; no Git operations.

2026-09-09 GitHub import follow-up: real user retry resumed a pre-deployment
clarification with 5/6 model calls consumed, so only tool-less final synthesis
ran. Trench capability generation now advances v11 -> v12, reusing existing
scoped CAS successor binding and bounded history without resetting Turn budgets.
37 focused tests passed. Real pending-clarification upgrade/import/reference
read passed (8.19 / 6.11 seconds) in an isolated account. User's existing
conversation is not edited; its next message selects the current generation.

2026-09-09 EXT-GITHUB-SKILL-01: Agent now accepts public GitHub Skill links via
extensions.import_skill: bounded HTTPS download, immutable commit verification,
package validation, scoped publication, idempotent install/enable and next-Turn
automatic binding. No script execution, arbitrary fetch or secret model inputs.
Real forjd/better-writing import and subsequent reference read passed through
Trench/Broker/Cloud Worker/model; reimport retained one installation. Worker
rebuilt locally with credentials/environment preserved. 83 initial focused tests
passed plus a subsequent concurrent-version regression; broad suite 4371 passed,
875 skipped with DeepSeek live smoke module explicitly excluded (known network
issue). No full-live-suite/browser/merge/push claim. See management doc and log.

2026-09-09 EXT-SKILL-AUTO-01: scoped enabled Skill IDs now bind automatically
on each new Trench Turn. Changed ID sets create a CAS-protected successor Task
under the same frontend conversation; upgrades select the new version next
Turn without unnecessary Task replacement. Replay/cancel keep their original
binding. Research exposes only the scoped Cloud Skill read tools. Canonical
publication UUIDs, bounded four-page selection and successor context seeding
are covered. Trench separates five-second control requests from a configurable
60-second stream idle budget (1–300 seconds), preventing premature interruption
between Skill tool calls. No schema migration or new consent UI.

Live HTTP-to-Worker/model acceptance passed in
conv_skill_acceptance_d5b35f4efb8e4a9d: initial reply, new Skill read using a
marker present only inside SKILL.md, Agent-native version upgrade, next-Turn
v2 read, disable/successor and other-user installation/Turn 404; all five Turns
completed in 4–8 seconds. API/Worker/Broker source deployed locally. Worker
currently has an acceptance-only api.deepseek.com public-IP mapping because
the host proxy fake-IP path fails TLS; see management doc before recreating it.
Latest Zebra make check passed; full make test: 4335 passed, 875 skipped, three
DeepSeek live transport failures (not passed). Trench focused 35 passed; prior
broader API baseline retains four unrelated failures. No new browser acceptance,
commit, merge or push claim. Other Skill upload/credential UI and full cross-Task
history authorization are separate work, not delivered by this slice.

2026-09-09 EXT-NATIVE-MANAGE-01 Host delegation source: confirmed login-once
policy now shares Trench viewer/chat scopes, including extensions.read/manage.
Broker checks explicit viewer/signed-workload ceilings and operator allowlist;
legacy Hosts cannot gain extension scopes implicitly. Trench rechecks workload
account/workspace before signing and advances Task/idempotency generations.
No perpetual grant, extra consent database or per-Turn consent UI. Accepted
durable work retains existing logout-independent semantics; not immediate global
revocation of issued grants. Zebra make test 4321 passed / 875 skipped; make check
passed. Trench targeted 37 passed; API suite 582 passed / 4 failed in untouched
startup/capsule/harness expectations. Deployment, real management E2E and new
Skill successor ceilings remain open. No commit/push or container recreation.

2026-09-09 EXT-NATIVE-MANAGE-01: seven typed extension management tools now
reuse scoped create/update/installation/catalog services. Cloud Worker registers
them only for explicit frozen Host management/read scopes and revalidates live
Task/Turn identity and lease, including before writes after intermediate reads.
No secret-bearing tool arguments, no synthetic HTTP grants, no active snapshot
rewrite; network-disabled Tasks cannot refresh MCP. Focused tests 119 passed;
full suite 4295 passed / 875 skipped; make check passed. This is runtime source
delivery, not Trench activation: signed Host delegation, new-Skill Task ceilings,
credential UI and real management E2E remain open. See
docs/cloud-extension-agent-management.md. No deployment or Git push this slice.

2026-09-09 EXT-AGUI-01: real Trench MCP fetch execution now verified. Fixed
AG-UI admission forwarding, existing-Turn RUN/RESUME selection/recovery,
PostgreSQL MESSAGE-only atomic admission, and the live publisher decorator
dropping the atomic method. Cloud aliases now fit the provider's 64-character
limit. Trench requests mcp-proxy-only (not unrestricted egress) and advances
its task generation/idempotency namespace to avoid old frozen none profiles.
Browser conv_1788883798514_259bde fetched public example.com via configured SSE:
policy allow, tool_execution_completed=executed with actual remote text,
model deltas, turn_completed and semantic title persisted; about 19 seconds.
API/Worker rebuilt and healthy. Focused Zebra 64 + 12 + 21 passed (one optional
live transport test skipped); Trench runtime 23 passed. Mypy 907 sources passes.
No full-suite, merge or commit claim. Skill upload/credential/deletion UI and
full multi-user live/revocation acceptance remain outstanding. Historical
rollout failures below are retained as evidence, not current MCP status.

2026-09-08 live rollout: schema v56 applied; 250 existing session streams retained.
API/Worker extension overlay active and healthy; Broker extension scopes enabled
with existing credentials retained. Trench API restored; real browser MCP list,
create and enable pass. Fixed production authorizer's unconditional agent.run
requirement (8 real PostgreSQL signed-authority tests pass), BFF history refs,
and refresh body contract (4 UI tests pass). Catalog refresh succeeded after a
transient 503; one catalog persisted. Real AG-UI Turn did not receive MCP:
no snapshot created. AG-UI RUN/RESUME bypasses MESSAGE-only admission. Worker
MCP E2E failed; normal reply/title persisted. See
docs/cloud-extensions-rollout.md for env preservation and remaining UI gaps.

Historical source-delivery entry below predates this activation:

2026-09-08: EXT-TRENCH-BFF-01 implemented in Trench's existing current branch.
Authenticated extension BFF reuses grant exchange with operation-only
extensions.read/manage; no management workload fallback or upstream Cookie.
Explicit bounded collection/create/enable/catalog/refresh paths only. Trench
settings now have Skill/MCP sections: public MCP create, toggle, refresh and
installed Skill toggle. Upload/credentials/deletion are not yet delivered.
Backend focused regression 30 passed. Runtime broker scopes, migration and
API/Worker activation remain pending; no browser/live Worker closure claim.
Extension UI tests 3 passed; focused ESLint and backend Ruff passed.
Frontend tsc is blocked by three pre-existing incomplete source fixtures in
dashboard-data-settings.test.tsx, not the added extension component.

2026-09-08: EXT-ROLLOUT-01 opt-in deployment overlay prepared in
docker/compose.extensions.yml. Actual Compose rendering tests: 3 passed;
paired API/Worker switches, private read-only required key mounts and unchanged
base defaults verified. Running stack NOT changed. Broker scope/Host ceiling,
Trench management BFF/UI, operator key and migrations remain activation gates.
See docs/cloud-extensions-rollout.md for exact sequencing and rollback boundary.

2026-09-08: EXT-MCP-SSE-01 remote legacy SSE compatibility implemented after
user approval. Cloud connections accept explicit sse alongside default
streamable_http; cloud stdio remains rejected. Discovery and execution reuse
bounded framing, schema checks and per-frame live authority/credentials.
Same-origin derived endpoints and public-IP-pinned sockets remain mandatory.
SSE focused 13 passed; make check passed (907 sources, Eval 10/10).
Full regression: 4238 passed / 866 skipped in 133.40s; two subsequently added
SSE checks passed with the complete focused suite (13 passed).
Repository live probe unblocked: a single-host Mihomo fake-IP exclusion restored
public DNS (39.96.127.68). Default discovery completed in 1.71s; CloudMcpTransport
fetch returned real example.com content, isError=false, total 7.47s. One initial
five-second discovery timeout was observed; no timeout/security bypass applied.
Probe used fixture scope/authority, not durable Worker or Trench authentication.
No runtime rollout or Trench E2E claim.

2026-09-08 live acceptance preflight: running zebra-trench-acceptance API/Worker
containers are healthy, but neither contains extension/MCP enable flags or an
MCP master-key mount. Verified runtime PostgreSQL database zebra remains v50;
extension_configurations and mcp_catalog_versions are absent. Active frontend is
Trench/toc-frontend on port 3000; settings sources contain no Skill/MCP management
entry. Live extension acceptance has NOT started. Requires runtime migration/
image/config rollout, Trench management delivery and a configured HTTP MCP target.
No database migration, container restart or operator secret changes were made.

2026-09-08: EXT-MCP-WORKER-01 lifecycle wiring implemented behind
ZEBRA_CLOUD_MCP_WORKER_ENABLED (default off). API composes stored catalog selection;
Worker composes catalog/credential stores from its existing cloud bundle and
replays current-Turn durable authority before HTTP frames. Execution gateway
receives the transport; empty cloud selection cannot fall back to process MCP.
Shared mounted-key startup validation preserves API behavior. Focused 102 passed /
1 skipped, isolated PostgreSQL-related subset 56 passed; make check passed
(906 sources, Eval 10/10). Runtime activation and real remote/Trench E2E pending.
Full regression: 4226 passed / 866 skipped in 151.01s; the subsequently added
empty-selection case passed in the focused gateway suite (3 passed).

2026-09-08: EXT-MCP-WORKER-01 authority adapter implemented. MCP accepts existing
bound Worker execution evidence without an HTTP Grant callback; release compares
it with current Task identity/digests/capability/expiry. Shared scope derivation
preserves user/workspace isolation. Focused 49 passed / 4 DB skipped; make check
passed (905 sources, Eval 10/10). Default lifecycle wiring and real MCP/Trench
acceptance remain pending; this is not a production activation. Expanded focused
regression: 70 passed / 4 skipped; isolated PostgreSQL subset: 33 passed.
Full regression: 4213 passed / 866 skipped in 139.67s; diff check passed.

2026-09-08: EXT-MCP-WORKER-01 remains In Progress. Explicit catalog/transport
composition passes 3 captured-network checks; full 4202 passed / 866 skipped
in 142.81s; make check passed (904 sources, Eval 10/10). Found startup mismatch:
Worker uses bound execution-authority snapshots/revalidation, not fresh verified
HTTP grants. MCP release must adapt to that existing authority boundary before
default lifecycle wiring. No fabricated Grant, activation, commit or deployment.

2026-09-08: EXT-MCP-AUTH-02 is in Review. Anonymous MCP now has a shared
snapshot/grant authorization hook with exact live config and lease/fence checks;
no credential access on that path. Existing Bearer release remains unchanged.
Focused 35 passed / 4 DB skipped; real isolated PG/runtime 39 passed; full
4199 passed / 866 skipped in 144.35s; make check passed (903 sources, Eval 10/10).
Worker transport callback and startup/recovery composition remain incomplete;
no live remote MCP/Trench E2E, production activation, commit or deployment.

2026-09-08: EXT-MCP-ADMISSION-01 is in Review. Optional catalog-store composition
automatically selects current-user enabled usable MCP catalogs for new Turns;
no remote discovery or client allowlist required. Unrefreshed connections are
skipped; exact scope/revision and bounded paging/tool counts enforced. Focused
28 passed; actual isolated PostgreSQL/admission 29 passed; full 4192 passed /
866 skipped in 139.92s; make check passed (903 sources, Eval 10/10).
Default startup remains unchanged pending production Worker recovery/live
authority composition. No deployment, activation or real Agent/browser E2E.

2026-09-08: EXT-MCP-EXEC-01 is in Review. Added pinned cloud HTTP transport
and explicit existing Harness injection, without per-turn remote discovery.
Exact catalog/digest and alias mapping, argument checks, per-frame authority,
none/Bearer auth, protocol drift rejection and bounded untrusted results reuse
existing runtime components. Focused 32 passed; full 4184 passed / 865 skipped
in 143.89s; fixture enum warning subsequently corrected with focused 5 passing.
make check passed (902 sources, Eval 10/10). Automatic scoped admission and
production Worker authorization/startup wiring are still incomplete; captured
HTTP is not real remote MCP or Trench E2E. No activation, commit or deployment.

2026-09-08: EXT-MCP-NAMES-01 is in Review. Fixed cloud discovery incorrectly
rejecting remote names through local alias restrictions. Preserve exact bounded
remote names, use collision-checked internal aliases with shared schema parsing,
keep local HTTP/stdio behavior unchanged. Focused 35 passed / 2 DB skipped;
full 4179 passed / 865 skipped in 141.91s; make check passed (901 sources,
Eval 10/10). Cloud Worker execution and Settings E2E remain incomplete; no
service activation, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01E is in Review. Scoped catalog GET now exposes
current-revision tool metadata without discovery or credential release. Product
decision clarified: configure/enable once, AI chooses tools; Task/Turn bookkeeping
is internal, never a new manual binding workflow. Focused 16 passed / 5 DB
skipped; real isolated PG/captured HTTP 21 passed; full rerun 4165 passed /
865 skipped in 132.16s. Initial unrelated process kill PermissionError passed
isolated retry and full rerun. make check passed (901 sources, Eval 10/10).
Cloud admission/Worker still need persisted user catalogs instead of process
MCP settings; execution and Settings/browser acceptance remain incomplete.

2026-09-08: EXT-MCP-CATALOG-01D is in Review. Separately opt-in automatic
management refresh startup shares credential storage/protector and resolved
cloud database/namespace. Defaults remain disabled; invalid prerequisites fail
startup and boot performs no discovery. Focused 50 passed / 3 DB skipped;
actual isolated PostgreSQL and captured HTTP matrix 14 passed; full 4159 passed /
864 skipped in 134.53s; make check passed (901 sources, Eval 10/10).
Distributed refresh coordination/limits, Task MCP ceiling/Turn admission,
Worker dispatch and Trench Settings E2E remain pending. No live schema changes,
service activation, remote MCP acceptance, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01C is in Review. Explicitly injected management
refresh service and protected POST route now connect scoped configuration,
per-frame grant expiry/configuration checks, Bearer ciphertext release, discovery
and revision-checked catalog publication. Input cannot supply URL, scope or token.
Focused 38 passed / 3 DB skipped; captured-network plus real PostgreSQL matrix
21 passed; full 4154 passed / 862 skipped in 132.64s; make check passed
(900 sources, Eval 10/10). Startup activation, distributed refresh scheduling,
Task MCP ceiling/Turn selection, Worker execution and Trench E2E remain pending.
No live schema change, activation, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01B is in Review. HTTP-only discovery now returns
complete connection-bound immutable catalogs through existing pagination/schema
and HTTPS framing. Per-frame Bearer resolver required; missing/unsupported auth
fails before send. Shared HTTP discovery rejects duplicate remote names early.
Focused 45 passed / 1 DB skipped; captured-network plus real PostgreSQL matrix
23 passed; full 4139 passed / 860 skipped in 130.33s; make check passed
(897 sources, Eval 10/10). Public authorized refresh route, Task MCP ceiling,
Worker dispatch and Trench Settings E2E remain pending. No live network/server
acceptance, schema changes, service activation, commit or deployment.

2026-09-08: EXT-MCP-CATALOG-01A is in Review. Bounded immutable tool catalog
contracts and PostgreSQL v56 persistence bind exact scoped connection/revision.
Parent-lock publication rejects configuration drift; validated digest readback
rejects corruption. Identical A-after-B refresh advances latest publication
without changing historical definition payloads. Deterministic 11 passed;
isolated PostgreSQL catalog/credential matrix 37 passed; full 4124 passed /
859 skipped in 133.57s; make check passed (896 sources, Eval 10/10).
Migration was tested only in disposable schemas. Remote discovery, Task MCP
ceiling/Turn admission, Worker execution and Trench Settings E2E remain pending.
No live service migration, activation, commit or deployment.

2026-09-08: EXT-AUTH-01I is in Review. Opt-in API credential startup now reuses
the admitted cloud DSN/namespace and existing SecretStore/AES-GCM components.
Operator supplies read-only mounted master key with exact handle/version;
missing, malformed or insecure key files stop startup. No user plaintext token
store or default permissions expansion. Focused 98 passed / 2 DB skipped;
real PostgreSQL startup/HTTP/management matrix 54 passed; full 4113 passed /
852 skipped in 122.86s; make check passed (892 sources, Eval 10/10).
Worker dispatch/catalog admission, OAuth and Trench Settings/deployed E2E remain
pending. No service activation, live schema migration, commit or deployment.

2026-09-08: EXT-AUTH-01H is in Review. Protected opt-in HTTP credential
provision/revoke routes reuse verified management grants and atomic revision CAS.
No credential readback, client identity override or default permission expansion.
Focused 23 passed / 1 DB skipped; isolated real PostgreSQL HTTP/service matrix
36 passed; full 4096 passed / 851 skipped in 131.21s. make check passed
(890 sources, Eval 10/10). Service injection is explicit: automatic SecretStore
composition, Worker dispatch and Trench settings/deployed E2E remain pending.
No live schema changes, commit or deployment.

2026-09-08: EXT-AUTH-01G is in Review. Internal MCP execution resolver binds
fresh grant, current lease fence, recovered snapshot and exact operation/params.
Lease is rechecked after credential I/O; shared release now explicitly verifies
target endpoint. Shared fenced Effect gateway rechecks ownership after payload
read and before tool invocation, preserving existing uncertain/recovery handling.
Focused 52 passed / 4 DB skipped; isolated real-DB matrix 44 passed including
existing terminal-result replay. Final full 4073 passed / 850 skipped in 128.59s;
make check passed (889 sources, Eval 10/10). Broker routes, trusted Worker
composition, MCP catalog admission and deployed E2E remain pending. No live
schema changes, Worker activation, commit or deployment.

2026-09-08: EXT-AUTH-01F is in Review. Existing MCP HTTP sessions support
per-frame endpoint-bound Bearer resolution without environment mutation or shared
credential caching. Mixed environment/scoped auth fails closed; initialize,
notification and tool frames reauthorize independently. Failure sends no denied
frame and adds no retry. Secret-bearing exception chains are suppressed.
Validation: 52 transport tests passed (15 new), full 4059 passed / 850 skipped
in 129.37s; make check passed (888 sources, Eval 10/10). Test composition connects
internal release to a captured HTTP opener, not a deployed remote MCP server.
Worker lease/digest/dispatch-ledger composition, API-key templates, OAuth, routes
and Settings E2E remain pending. No service activation, commit or deployment.

2026-09-08: EXT-AUTH-01E is in Review. Internal MCP credential release validates
live Task grant, frozen snapshot scope/coordinates/digest and operation permission,
then reads ciphertext under current-connection lock. Revoked/rotated/disabled or
changed connections reject old snapshots; secret material stays Broker-internal.
Expanded real-DB/crypto matrix 122 passed; final full 4044 passed / 850 skipped
in 125.73s; make check passed (887 sources, Eval 10/10). Initial real DeepSeek
smoke failed for missing reasoning output; isolated and full retries passed
without parser changes (see WORKLOG.md). No Worker/API/transport activation;
trusted lease/digest composition, OAuth and Settings/browser E2E still pending.

2026-09-08: EXT-AUTH-01D is in Review. Verified extensions.manage authority now
provisions bearer/API-key ciphertext and publishes its connection reference/state
atomically with configuration CAS; revoke disables and revisions the connection.
Fixed stale joined-lock reads by locking the parent before reading current payload.
Real PostgreSQL matrix 73 passed; crypto 30 passed; default full suite 4029 passed /
846 skipped in 129.50s; make check passed (886 sources, Eval 10/10). Five new DB
cases passed separately. Management slice complete; runtime credential release and
revocation enforcement, OAuth, public API and Trench Settings remain pending.
No live schema migration, runtime enablement, commit or deployment.

2026-09-08: EXT-AUTH-01C is in Review. Core encrypted credential DTO/Port and
PostgreSQL v55 ciphertext history implemented. Parent locking validates exact
connection/scope/endpoint and serializes append-only revision CAS. Storage never
decrypts or changes authentication state. Real PostgreSQL matrix 61 passed;
crypto 30 passed; full default suite 4022 passed / 841 skipped in 130.38s;
make check passed. Eleven new DB cases were exercised in the dedicated real
run. No service schema migrated; Broker authorization/revocation, OAuth, Worker
and Trench UI remain pending. See docs/cloud-mcp-credential-storage.md.

2026-09-08: EXT-AUTH-01B is in Review. Broker-internal MCP token protection
uses existing SecretStore and installed AES-GCM implementation with exact
deployment/scope/connection/endpoint/credential identity binding. Ciphertext
substitution, tamper and key-version mismatch fail closed; rotation retains
old readback only while old key handles remain available. Validation: 30 focused,
263 security tests; full 4021 passed / 830 skipped in 126.26s; make check passed.
This is cryptographic protection only, not persistence, authority, expiry,
revocation, OAuth, cloud Worker or Trench browser delivery.

2026-09-08: EXT-AUTH-01A is in Review. MCP HTTPS sockets now revalidate DNS
and connect directly to a validated numeric IP, retain original-host TLS checks,
disable environment proxies and reject tunnels. Failed sockets close; no request
replay is added. Validation: 16 egress / 135 MCP tests; full 3991 passed / 830
skipped in 134.86s; make check passed. User credential Broker/OAuth, cloud MCP
Worker activation and Settings/browser acceptance remain outstanding.

2026-09-08: EXT-MCP-HTTP-01B is in Review. HTTP resource and explicit prompt
discovery/read now reuse existing bounded content validation rather than being
silently skipped. Empty resource selection has zero I/O; duplicate server names
fail before network access. Validation: 15 focused / 119 MCP tests; full suite
3975 passed / 830 skipped in 132.12s; make check passed. This is shared transport
support, not user credential Broker, cloud MCP Worker activation or Settings E2E.

2026-09-08: EXT-MCP-HTTP-01A is in Review. HTTP SSE response framing now
returns the correlated result before EOF and carries negotiated protocol and
per-instance session headers. Failed initialization delivery stops the handshake.
Validation: 104 MCP tests; full suite 3960 passed / 830 skipped; make check
passed. Cloud MCP credential/egress composition, Worker activation, GET replay
and Trench settings/browser acceptance remain outstanding.

> This is the current project snapshot, not an append-only session log. Detailed
> history lives in task cards, acceptance records, merge commits, and Git history.

## Active Review

- `EXT-STORE-01B`: immutable exact-scope per-turn ExtensionSnapshot storage
  and migration v54 implemented. Trusted expected digest, full seven-coordinate
  lookup, typed payload/identity checks, idempotent replay, concurrent conflict,
  tamper and tenant isolation covered. Real PG/MinIO and related matrix:
  94 passed in 63.19 seconds, including persisted two-user private Skill
  readback after adapter restart and live disable rejection. make check passed
  (873 typed files, eval 10/10); independent spec/quality PASS.
  Final full regression: 3851 passed / 805 skipped in 145.98 seconds; final
  lint, type, eval, diff and size gates passed. This is persistence only: no
  admission, API, Worker activation, business migration, deployment or commit.

- `EXT-API-03B`: normal cloud HTTP startup now supports default-off Skill
  publication composition using one resolved control-plane bundle (DSN,
  deployment namespace and the same artifact object store). Mixed explicit
  store injection is rejected for automatic publication; explicit publication
  services and local/default-off paths retain their prior behavior.
  Real PostgreSQL/MinIO and related matrix: 77 passed in 55.41 seconds,
  including normal environment and explicit-bundle startup, upload, restart
  read/replay, installation and foreign-user denial. make check passed.
  Independent spec/quality PASS; 129 focused checks passed. First full run:
  3836 passed / 785 skipped / one live DeepSeek Responses payload rejection;
  isolated retry passed (3.22s). Final full rerun: 3837 passed / 785 skipped
  in 128.23s. No actual flags,
  business schema, running services, Worker or Trench Settings were changed.

- `EXT-API-03A`: explicitly composed raw ZIP upload and scoped publication
  metadata GET implemented. Migration 53 atomically binds hashed request keys
  and immutable publication reservations; interrupted uploads resume without
  creating another version. 125 focused tests, real PostgreSQL/MinIO and
  related matrix 75 passed, independent spec/quality PASS; make check passed
  (870 typed files). Real HTTP recovery/install/enable/tool-read path verified.
  Final full suite: 3809 passed / 783 skipped in 137.50 seconds.
  Default service injection remains absent; production object-store wiring,
  Worker authorization/admission and Trench Settings are still pending.
  No business migration, deployment, commit or branch change.

- `EXT-SKILL-02A`: private cloud Skill read adapter now consumes an explicitly
  bound frozen snapshot and verifies current installations, ready publication,
  archive bytes and complete package manifest. Existing skills.list/read reused
  with cloud provenance; no host extraction or script execution. 135 focused
  tests and real PG/MinIO matrix 67 passed, including two users' actual private
  bytes through shared tools. make check passed (868 typed files).
  Independent spec/quality PASS; full suite 3787 passed / 775 skipped.
  Not activated: admitted snapshot persistence, per-call live authorization,
  Worker composition, public upload, MCP execution and Trench Settings remain.
  Preloads bounded selected packages; first-text latency must be verified at
  Worker integration rather than inferred from this off-thread adapter.

- `EXT-API-02C`: Skill installation POST pins an own ready published version
  server-side at disabled revision 1. Scoped idempotency replays current state
  without overriding later toggles; existing store composition and migration
  reused. 114 focused tests, independent spec/quality PASS, real PostgreSQL/
  MinIO and related regressions 66 passed; make check passed (867 typed files).
  Final full suite: 3752 passed / 774 skipped in 137.93 seconds.
  Public upload, Worker consumption and Trench Settings remain unconnected;
  no business migration, environment activation, commit or deployment.

- `EXT-SKILL-01B`: internal durable package publication implemented and
  independently reviewed. Existing ZIP validation and ArtifactObjectStore are
  reused; migration 52 records exact-scope immutable named versions before
  object upload. Verified expectation and object version gate readiness;
  interrupted publication is resumable, with no false Session or raw bytes in PG.
  Final PostgreSQL/MinIO and related regression matrix: 59 passed, including
  recovery/readback and private user objects; make check passed (866 typed files).
  Full suite: 3695 passed / 767 skipped in 144.08 seconds.
  No public upload/install/Worker/Settings
  activation, business migration, commit or deployment.

- `EXT-API-02B`: MCP configuration creation is implemented behind the existing
  default-off management flag. Immutable revision 1 binds a scoped idempotency
  key; replay returns the current revision without overwriting later edits.
  New connections stay disabled and have no credentials or runtime admission.
  Real PostgreSQL matrix: 47 passed (including HTTP create/read/toggle/replay
  and concurrent duplicates); make check passed (861 typed files). Independent
  spec/quality re-reviews passed; 83 focused tests and final full suite
  3671 passed / 756 skipped (135.73 seconds). Storage validation failures now
  return sanitized 503 instead of blaming valid request input with 422.
  No deployment, business schema change or Trench Settings activation.

- `EXT-API-02A`: enabled-only PATCH with separate default-off management flag,
  strong If-Match/ETag, scoped CAS and bounded strict JSON implemented/reviewed.
  114 focused tests and 40 actual PostgreSQL tests passed; full suite 3614 passed
  / 749 skipped in 132.25 seconds, make check passed (858 typed files).
  No deployment or live Worker revocation. Creation/upload/delete/credentials,
  Worker composition and Trench Settings remain pending.

- `EXT-API-01B`: default-off PostgreSQL read composition implemented and
  independently reviewed. `ZEBRA_CLOUD_EXTENSIONS_READ_ENABLED` defaults false;
  cloud-only, matching namespace, read-only schema admission before construction.
  Local lazy SQLite startup preserved by factory-level regression tests;
  119 focused tests passed; final full suite 3574 passed / 747 skipped in
  129.58 seconds, make check passed (856 typed files). No actual environment
  change or migration applied.

- `EXT-API-01A`: opt-in read-only HTTP installation/MCP configuration adapter
  implemented and independently reviewed. Strict verified identity, bounded
  query/IDs, no-store, sanitized responses and cross-scope rejection. 53 focused
  tests after final method correction; preceding full suite 3544 passed / 747
  skipped. Write APIs, Broker scopes, Worker and
  Trench Settings remain pending; no running service activation.

- `EXT-CON-01` and configuration-only `EXT-STORE-01A`: implemented on the
  current branch by explicit user request. Immutable HTTP-only Skill/MCP
  configuration contracts and scoped PostgreSQL CAS/pagination/revision history
  pass independent spec and quality reviews. Evidence: 33 contract tests, 670
  core tests, 38 actual PostgreSQL tests in temporary schemas; make check passes.
  No live schema or Worker activation. Package/catalog/Outbox/Turn snapshot
  persistence, credential authorization, write management API, Trench Settings Skills
  and MCP sections, and actual Agent/browser acceptance remain unimplemented.
  Full-suite baseline repaired in EXT-BASELINE-01; Skill/identity checkpoint:
  changes: 3500 passed / 747 skipped (132.46 seconds).
  Unit tests now isolate their synthetic checkout and schema validation;
  production schema and original-worktree safeguards remain unchanged.
  EXT-SKILL-01A ZIP validation passed 57 tests and independent spec/quality
  reviews, including forged sizes and bounded deflate draining. No extraction,
  upload or script execution enabled. EXT-AUTH-01A passed 41 focused tests and
  independent reviews: verified issuer/subject retained, management permissions
  explicit. Read HTTP routes use this identity; Broker scopes are not enabled.

- `CLOUD-EXT-HTTP-DESIGN-01`: Skill and HTTP-only MCP cloud design drafted in
  `docs/cloud-skills-http-mcp-design.md`. User confirmed no cloud stdio support.
  The design is approved; initial contracts/configuration storage are in review,
  not implemented cloud extension management. Existing
  local compatibility remains unchanged; implementation requires separate task claims.

- `TRN-NATIVE-WORKER-01`: local Apple Silicon latency investigation identified
  amd64 CLI emulation overhead (150 ms versus 18 ms median native info query).
  Worker-only opt-in native image inputs preserve deployment defaults and all
  runtime checks; see `docs/native-worker-local.md`. Local native Worker is
  healthy: continuation first text 2.021s, preparation 0.860s, real sources.list
  executed. This is local cross-service acceptance, not browser paint or p95.

- `RABBIT-SOURCE-CREDENTIAL-REF-01` passes isolated acceptance and is in
  Review. Source bindings now validate an existing credential identity's enabled
  state and source platform without loading its payload. Missing, inactive,
  mismatched and post-bind drifted references fail closed; principal user,
  workspace and active-subscription association remains mandatory. Even a valid
  reference stays `credential_execution_unavailable`, so this closes identity
  integrity without enabling secret resolution or X fetching. Final source
  regression is 100 passed/21 explicit-integration skipped; focused actual
  PostgreSQL is 5/5 including a controlled credential-writer lock race;
  independent SPEC/QUALITY pass. Stage 4 is **7/7 = 100%** at the isolated
  acceptance boundary. No credential payload, live source/schema or production
  process was activated.

- `RABBIT-SOURCE-COMPOSE-01` passes isolated acceptance and is in Review. An
  opt-in minimal-credential process composes the accepted source relay,
  consumer, recovery and quarantine with one shared fail-closed cutover
  selector and a 45-second drain window. Separate real Python processes passed
  broker execution, database fallback, broker restore and default-off rollback;
  fallback generations remain auditable as `superseded` and are not published
  on restore. Actual subprocess E2E is 2/2, cleanup leaves Redis DB 14 empty,
  and independent SPEC/QUALITY pass. Stage 4 group 7 is accepted and Stage 4 is
  **6/7 = 85.7%**. Credential-reference scope closure remains open; no live
  business schema/feed, credentialed source or production process was activated.

- `RABBIT-SOURCE-E2E-01` passes isolated acceptance and is in Review. A real
  fixture HTTP feed traverses durable PostgreSQL admission/Outbox, RabbitMQ,
  fenced execution, Redis raw handoff, normalize and archive into the
  authenticated product timeline and signed Host history Tool. Duplicate
  delivery proves two ACKs, zero requeues and one canonical raw item. A
  deterministic Redis-rejection fault injection leaves source success, raw
  length and normalize cursor unchanged, while two users see only entitled
  source content. Combined source acceptance is 106/106 on actual
  PostgreSQL/Redis/RabbitMQ where applicable; SPEC/QUALITY pass. Stage 4 group 6
  is accepted and Stage 4 is **5/7 = 71.4%**. No credentialed source, live
  business schema/feed or production process was activated.

- `RABBIT-SOURCE-RESULT-01` passes isolated acceptance and is in Review. Six
  sanitized result classes now finalize only the exact command/fence and reuse
  durable FetchAttempt/parse evidence plus a callback-minted Redis checkpoint.
  Retry-After/exponential delay, generation and age are bounded; fallback uses
  the latest due Outbox and completes claim/Inbox/receipt in one transaction,
  while prior generations become auditable `superseded` rows. Migrated URL and
  exception logs are safe, malformed scraper shapes are typed, and downgrade is
  conservative. Combined result/delivery/schedule/cutover/adapter acceptance is
  63/63 including actual generated-schema PostgreSQL; SPEC/QUALITY pass. Stage 4
  group 5 is accepted and Stage 4 is **4/7 = 57.1%**. No live schema/feed,
  credential or production process was activated.

- `RABBIT-SOURCE-CUTOVER-01` passes isolated acceptance and is in Review.
  Managed/default RSS, scraper ARQ and legacy fallback entry points now share a
  default-off selector; broker and DB fallback modes are exclusive and migrated
  mode has one admission trigger. Exact locked validation freezes a non-secret
  execution snapshot before IO; config races fail closed and legacy result state
  is suppressed. Focused 75 passed/12 explicit-PG skipped; parent combined 21/21
  including actual PostgreSQL 9; SPEC/QUALITY pass. Stage 4 group 4 is accepted
  and Stage 4 is **3/7 = 42.9%**. No live process/schema/feed activation.

- `RABBIT-SOURCE-DELIVERY-01` passes isolated acceptance and is in Review.
  Dedicated source Outbox/Inbox/receipt, bounded relay/consumer/recovery,
  exact Redis-checkpoint ACK and opt-in least-privilege RabbitMQ topology are
  implemented independently from the Turn lane. Trench local 15 passed/5
  explicit-PG skipped; parent actual PostgreSQL delivery+schedule 9/9; Zebra
  topology 9/9; isolated live Rabbit source route/ACL 1/1; post-fix SPEC/QUALITY
  pass. Stage 4 group 3 is accepted and Stage 4 is **2/7 = 28.6%**. No old fetch
  entry point, live business schema, feed or production process was activated.

- `RABBIT-SOURCE-SCHEDULE-01` passes isolated acceptance and is in Review.
  Source-wide immutable schedule ownership, atomic FetchCommand plus dedicated
  source Outbox, DB-clock due coalescing, stable manual idempotency and exact
  lease/fence/Redis-handoff finalization are implemented without network or
  process activation. Local 116 passed/4 explicit-PG skipped; parent random-schema
  PostgreSQL 4/4 passed; SPEC/QUALITY pass. Slice **6/6 = 100%**; Stage 4 group 2
  is accepted. Private, credential-reference and
  ambient-auth execution remain blocked; original services are unchanged.

- `RABBIT-ZEBRA-COMPOSE-01` now passes isolated acceptance and is in Review.
  Stage 3 **6/6 = 100%**: broker-only real model, stream replay/user isolation,
  semantic titles/stable routes/draft-only creation, actual answer and asset-page
  file downloads; real broker restart, duplicate drain, fallback/restore and
  canonical cancellation/cleanup. Process fault harness uses real subprocess/PG
  with explicitly injected transport/executor/OCI: final 15 passed. Parent local
  regression 3223 passed/692 skipped, PG 279, live relay/quarantine 7, check 842;
  independent SPEC/QUALITY pass. See `docs/rabbitmq_stage3_composition.md` for
  exact versions, terminal counts, timings and evidence boundaries. Stages 4/5
  remain open; original services and checkouts are unchanged. No commit/merge or
  production-HA acceptance is implied.

- `RABBIT-ZEBRA-RECEIPTS-01` passes SPEC/QUALITY: precise full-fence and canonical
  execution-floor attribution, atomic start/handled receipt with primary worker
  Event/projection commit; no arbitrary model-output completion heuristic.
  Slice 5/5; 61 actual PG cases and 54 shared callers pass; make check (803).
  `RABBIT-ZEBRA-CLAIMED-EXECUTION-01` passes 42 PG/worker cases plus both reviews:
  existing handed-off leases enter the real worker with a scripted model, and
  the completed-tool continuation raw-start gap closes when recorder is supplied.
  `RABBIT-ZEBRA-RECOVERY-01` now handles bounded, proven-unstarted recovery and
  uncertainty isolation; it will not blindly replay prior model/tool execution.
  Recovery accepted 5/5: 129 combined PG/Rabbit cases, final 44 recovery cases,
  make check (806) and SPEC/QUALITY. Poison rows cannot starve healthy candidates.
  Stage 3 is 5/6 (83.3%). MESSAGE atomic input/handoff is accepted: 12 actual PG
  cases, expanded 145 cases, make check (808), SPEC/QUALITY. Canonical CANCEL/STOP
  storage is accepted: 18 actual PG cases, combined 121 cases, make check (810),
  SPEC/QUALITY. Historical cutover accepted after stream-head guard fix: final
  81 PG cases, make check (812), SPEC/QUALITY. Shared fenced Task attach lock-order
  correction passed 7 PG/24 shared tests and both reviews. Consumer accepted:
  final 40 PG/runtime/migration cases, make check (815), SPEC/QUALITY, durable
  reconciliation ACK and bounded requeue fixes included. Quarantine, instance-safe
  cleanup and client-visible outcomes still require composition. Quarantine now
  passes 60 actual PG/Rabbit/runtime cases, check (819), SPEC/QUALITY; slice 5/5.
  Runtime instance identity is accepted 5/5: final 20 actual PG cases, check
  (827), SPEC/QUALITY, including row-lock waits across lease/authority expiry.
  Exact post-commit cleanup accepted 5/5: 92 PG/runtime + 5 live Docker cases,
  check (831), SPEC/QUALITY; plaintext Docker routing fixed from live evidence.
  Public cancel compatibility accepted 5/5: 91 actual PG + 6 live Docker cases,
  check (834), SPEC/QUALITY. Cross-rollover Task-target/CAS and canonical child
  Host identity are now accepted 5/5: 65 + 18 actual PG cases, check (835),
  SPEC/QUALITY. Client-visible outcomes accepted 5/5: actual PG 101 cases,
  final API/projection 52 cases, check (838), SPEC/QUALITY. Shared frame gating
  fixes expiry during DB waits or consumer pauses. Process composition is now
  claimed; Stage 3 group 6 remains open until actual fault/client acceptance.
  Original runtime unchanged.

- `RABBIT-ZEBRA-HANDOFF-01` storage slice passes SPEC/QUALITY: atomic Inbox plus the existing
  Session Lease/Fence and explicit canonical command association. Read-only audit
  confirms old RUN/RESUME execution has no generic command completion receipt;
  ambiguous backfill must not automatically rerun or be marked completed.
  Storage slice 5/5: initial 118 actual PG cases; review found terminal-state
  change during lease wait, fixed with post-lock recheck/savepoint rollback.
  Final race/clock 40 and shared-callers 54 pass. Later receipts, claimed execution,
  control and cutover slices now close group 4; process activation remains off.

- `RABBIT-ZEBRA-RELAY-01` passes SPEC/QUALITY: fenced Broker Outbox relay, confirmed
  transport, bounded physical retry and no network inside DB transactions.
  Actual PG/Rabbit combined suite 111 passed in 49.94 s; make check passes
  (799 typed files). Slice 5/5; later slices now close groups 1–5. Runtime
  activation remains off pending the remaining composition acceptance.

- `RABBIT-ZEBRA-LEASE-CLOCK-01` passes SPEC/QUALITY after a real-PG blocked-heartbeat
  expiry defect was reproduced. Fix the shared current Lease/Fence boundary before
  handoff activation; no new lease authority or original service changes. Slice
  5/5; 81 targeted/real-PG cases and full make check pass, including DST handling.

- `RABBIT-ZEBRA-DISCOVERY-01` passes independent SPEC/QUALITY: bounded canonical-history backfill
  and scoped pending discovery. Explicit admission cutover only; consumers remain
  off. Cursor and derived rows commit together, including old sessions and
  concurrent live admission. Slice 5/5; 60 focused/real-PG tests and make check
  (796 typed files) pass. Group 2 is not accepted until recovery also passes.

- `RABBIT-ZEBRA-ADMISSION-01` passes independent SPEC and QUALITY. Common
  PostgreSQL command admission gains opt-in derived pending/Outbox records; no
  publisher/consumer activation or SQLite changes. Real-PG plus focused tests pass
  36 cases across all four producers; existing PG regression 14 and make check pass.
  Slice 5/5; stage 3 is 1/6 (16.7%). Bounded historical backfill and recovery are
  next, with no activation. See `docs/rabbitmq_stage3_commands.md`.

- `RABBIT-TURN-E2E-01` passes isolated real-model/browser acceptance and independent
  reviews. Fixed shared mapper buffering, takeover reconstruction, separate model
  idle timeout, terminal replay and Next SSE gzip buffering. Browser first text
  4.795s with continuous increments; real files.publish/native asset download
  verified by bytes/hash. Slice 7/7; stage 2 10/10. Original activation remains off;
  stages 3–5 are not complete. Evidence: `docs/rabbitmq_stage2_product_e2e.md`.
  Full frontend typecheck retains three documented baseline fixture errors.

- `RABBIT-TURN-COMPOSE-01` passes spec and quality reviews after fixing real
  signed cancellation replay past earlier approval terminals. Default-off managed
  lifecycle, independent recovery, bounded drain, cancellation control capacity
  and fallback rollback are implemented. Actual PG/Rabbit acceptance: 10 passed,
  including three abrupt subprocess exits; 1000 Turns/route reduce local pickup
  p95 from 250.067ms to 53.939ms. Slice 6/6; stage 2 now 9/10 (90%). Real-model/
  browser verification awaits isolated authority confirmation; stages 3–5 remain
  pending. Original services/data untouched; no production activation or HA claim.

- `RABBIT-TURN-QUARANTINE-01` passes both independent reviews. Sanitized
  receipt/diagnostic Outbox, strict matching DTOs, mandatory confirmed transport,
  separate diagnostic quorum topology/ACL and additive migration are implemented.
  Parent actual PG/Rabbit suite passes 4 cases including 8-way receipt dedupe,
  fencing/migration parity and malformed-secret-safe delivery. Zebra `make check`
  passes (792 Mypy files, eval 10/10). Slice 5/5; stage 2 now 7/10 (70%).
  Default-off composition and dead-owner cancellation gap G20 are in progress.

- `RABBIT-TURN-CONSUMER-01` passes both independent reviews (28 tests each),
  and the combined consumer/dispatcher/handoff/recovery suite passes 65 tests.
  Actual PG/Rabbit capacity-1/prefetch-2 execution persists both answers without
  over-claiming after ACK. Shared reservations keep polling and broker execution
  within one bound. Slice 5/5; stage 2 is 6/10 (60%). Sanitized rejection and
  diagnostic delivery are next; original application startup remains unchanged.

- `RABBIT-TURN-RELAY-01` passes independent spec and quality reviews. Fenced
  relay preserves physical retry identity; durable recovery and scheduling
  deferral create atomic successor generations. Combined tests 60 passed;
  actual isolated PG/Rabbit lost-confirm/duplicate/owner-death acceptance passed.
  Slice 6/6; stage 2 now 5/10 (50%). Bounded consumer implementation continues;
  no original runtime activation. See `docs/rabbitmq_stage2_delivery_evidence.md`.

- `RABBIT-TURN-HANDOFF-01` adds dormant, explicit migration-mode atomic broker
  admission and scoped Inbox+execution-lease handoff in isolated Trench. Shared
  claim logic preserves fencing and fallback; separate broker tables do not
  replace execution Outbox. Independent spec/quality reviews pass, 174 targeted
  tests pass including 37 new cases; final 12 real PG cases pass three extra runs.
  Fixed publishing-state vocabulary and Unicode scope-key overflow. Current slice
  8/8 (100%); Trench Turn stage 3/10 (30%) under the fixed acceptance ledger in
  `docs/rabbitmq_completion.md`. No relay/consumer/sweeper or live activation yet.
  Evidence: `docs/rabbitmq_stage2_handoff_evidence.md`.

- `RABBIT-TURN-FENCE-01` completes the stage-2 prerequisite in isolated Trench:
  monotonic lease fences, owner/active/DB-expiry validation after Turn→Outbox
  locks, local cancellation on heartbeat loss, authoritative execution identity
  and individual shutdown release. Repeated PG tests exposed and fixed mixed
  admission/claim clocks. Independent spec/quality reviews pass; 53 targeted
  tests pass, including 9 real PG scenarios repeated three extra times. Additive
  migration tested on synthetic existing rows only. No business Rabbit activation,
  atomic broker Outbox/Inbox, original-service migration, merge or E2E claim.
  Evidence and next gates: `docs/rabbitmq_stage2_fencing_evidence.md`.

- `RABBIT-INFRA-01` adds optional RabbitMQ transports to both approved isolated
  repositories and a pinned 4.3.5 local broker fixture with least-privilege vhosts,
  quorum queues, mandatory confirmed publishing and explicit manual settlement.
  Both actual adapters pass the same 8 real broker scenarios (disconnect/restart,
  redelivery, routing/role isolation, prefetch, capacity and quarantine), with
  30 unit tests each and 3 provisioning tests. Zebra make check passes (791 Mypy
  files, eval 10/10). Independent spec and quality reviews pass after closing
  initial-connect cancellation and default-dev-install defects. No business activation,
  PG handoff, browser E2E or production HA is claimed. See
  `docs/rabbitmq_stage1_evidence.md` and `docker/rabbitmq/README.md`.
  Final full Zebra suite: 2984 passed, 381 skipped; disposable acceptance broker
  and test volume removed after zero-connection/zero-message checks.

- `RABBIT-FOUNDATION-01` implements the stage-0 envelope contract in both isolated
  repositories, with identical generated schema/fixtures and 84 envelope tests per
  repository. Real disposable PostgreSQL baselines measured Trench pickup p95 at
  242–257ms for 100-Turn runs and proved Zebra's recent-session scan misses an older
  pending command (9 SQL/9 connections per scan). No runtime integration or service
  activation. Core tests pass 637; Trench focused tests pass 97; Zebra make check
  passes (790 Mypy files, eval 10/10). See `docs/rabbitmq_stage0_evidence.md` for
  reproduction, identity/command producer inventory and remaining integration gates.

- `RABBIT-RELIABILITY-REVIEW-01`: RabbitMQ plan revised to content v1.1 after
  checking existing Trench/Zebra code and RabbitMQ delivery semantics. The
  audit distinguishes deterministic contradictions from implementation risks;
  it specifies scoped operation/generation deduplication, fenced handoff,
  mandatory returns, isolated shadow traffic, source scope and Redis limits.
  Work is isolated on `codex/rabbitmq-foundation-01`; no runtime activation or
  migration. The foundation continuation above supplies Schema/local baseline;
  real PG/Rabbit failure tests and runtime integration remain open. See
  `docs/RabbitMQ可靠投递缺口核验与验收.md` for evidence and gates.

- Trench user-file profile follow-up (`CLOUD-USER-FILES-TRN-PROFILE-02`) is in
  review on `codex/zebra-durable-turn-grants`. The research parent profile
  now exposes the existing governed `files.publish` Tool while keeping shell,
  patch, Git and nested delegation unavailable. Focused validation passes
  `27 passed`, Ruff and Mypy are clean, and real Trench browser acceptance
  published and downloaded a governed Markdown file.

- Trench long-turn recovery fixes (`TRN-MODEL-TOOL-REPAIR-02` and
  `CLOUD-CONT-FALLBACK-02`) are in review on
  `codex/zebra-durable-turn-grants`. OpenAI-compatible response rejection now
  preserves the provider tool name for bounded repair/audit. Cloud Provider
  Continuation only intercepts `provider_native`; `capsule_fallback` follows
  the ordinary durable Event path instead of failing for a missing artifact.
  Focused tests are `18 passed` with Ruff clean. A real Trench Task crossed
  three context compactions, persisted the fallback selections and completed
  with 360 Zebra Events; the repository-wide `make check` remains blocked only
  by the pre-existing 742-line handoff test against the 700-line size gate.

- Trench Durable Turn workload grants (`TRN-DURABLE-GRANT-01`) are in review on
  `codex/zebra-durable-turn-grants`. The Host Grant Broker now accepts either
  the existing verified browser Cookie or an allowlisted HMAC-authenticated
  Trench server workload. Workload signatures bind timestamp, nonce and the
  canonical principal/workspace/source request; repeated nonces derive the
  same JTI for Zebra replay rejection. The default grant TTL is 1900 seconds
  against the current 1800-second execution ceiling. Broker focused tests are
  `13 passed`; full Ruff, mypy (`789` source files), and the 10-case release eval
  pass. The full suite reached `2850 passed, 370 skipped`; its only failure is
  the pre-existing, out-of-scope 742-line
  `tests/agent_storage/test_postgres_session_handoffs.py` file-size violation.
  Local real Trench/Zebra cross-service execution and browser switch/refresh
  acceptance pass; production deployment remains a separate gate.

- Manifest-declared Host write approval (`HOST-WRITE-POLICY-01`) is in review on
  `codex/fix-agui-live-tail` after integrating `codex/host-write-policy-01`.
  The slice maps Host manifest write risk into
  Zebra's existing durable approval flow while keeping read-only Tasks closed;
  approval now enqueues one idempotent resume command, and cloud recovery repairs
  a one-sided Session/Workspace projection write from canonical Events before
  continuing. Real Trench acceptance subscribed an X profile through
  `sources.add`, resumed after explicit approval, and kept one subscription on
  an idempotent repeat. `make check` and the full suite (`2830 passed, 372
  skipped`) are green. The local Trench Cloud stack now has an explicit
  `ZEBRA_DEVELOPMENT_UNRESTRICTED` operator switch; it auto-allows approval-bound
  tools only in the `cloud` development profile and is rejected by production.
  The switch changes policy decisions only: the cloud gVisor/network profile,
  Host Grant, principal/resource binding, SSRF and path checks remain enforced.
  A logged-in browser acceptance directly subscribed the public ITJuzi feed and
  persisted exactly one user/workspace-scoped row. Trench remains responsible
  for business authorization and idempotent writes.

- Trench/Zebra response-latency and availability closeout (`TRN-PERF-01`) is
  implemented on `codex/fix-agui-live-tail`. Host-bound Tasks skip disposable
  workspace scanning; the first provider delta is committed immediately even
  when Host tools are advertised, and a streamed partial response disables
  semantic replay so visible text cannot be duplicated; later tiny chunks are
  bounded; PostgreSQL commits publish Redis live hints
  only after commit; the Worker fallback poll is 100ms; Memory/title side
  effects recover off the reply path. Conversation recovery now supplies the
  bounded completed-turn history, and AG-UI suppresses the internal tool-only
  assistant sentinel. DeepSeek Chat and Responses adapters preserve a present
  but empty provider reasoning field exactly, so a valid thinking-mode tool
  call no longer becomes a generic unavailable error while a genuinely missing
  continuation still fails closed. Current Compose images were rebuilt from
  this worktree. Real Trench TLS/Broker/Worker acceptance after rebuild passes
  three consecutive Turns: first visible events `36ms / 8ms / 7ms`, ordinary
  first text `4.04s / 4.15s`, exact recall of `灯塔`, and `sources.list` callback
  plus clean final answer in `6.65s`. The Trench development BFF now uses an
  explicit same-origin streaming Route Handler instead of the generic Next.js
  rewrite for chat SSE. A logged-in Chrome turn produced 27 increasing body
  snapshots (`47 -> 1625` characters) before terminal state. `make check` is green;
  the final repository-wide suite is `2826 passed, 369 skipped`.

- Cloud user file delivery (`CLOUD-USER-FILES-01`) is implemented on
  `codex/cloud-user-files-01`. A Grant-gated `files.publish` Tool accepts
  generated UTF-8 content or a safe workspace file, commits `kind=user_file`
  through the existing PostgreSQL Event/Artifact authority and private
  versioned MinIO store, and exposes raw private downloads behind
  `artifact.read`. The broker binds an opaque authenticated `principal`; Task
  binding renewal and task reads reject principal drift, so users sharing a
  namespace/workspace cannot cross-read files. Trench owns the stable BFF URL;
  neither MinIO credentials nor presigned URLs reach the browser. Real
  PostgreSQL + MinIO publication and HTTP download pass `2/2`; focused
  regression is green. Full-gate inherited failures remain separately recorded
  on the task card.
  The AG-UI adapter now preserves only the downloadable file fields in a
  versioned Tool-result envelope, allowing Hosts to build authenticated links
  without exposing MinIO keys, credentials, or presigned URLs. The production
  AG-UI stream tenant guard now authorizes the path's thread id (not its run id),
  restoring secure Host streaming without weakening principal isolation.

- Trench cloud governed Memory closeout (`TRN-MEM-E2E-01`) now routes API
  confirm/expire through the PostgreSQL aggregate CAS instead of the SQLite-only
  `upsert` path. Worker recovery persists a receipt for each closed Turn and
  selects oldest unreceipted closes, removing the moving recent-Session blind
  spot. Real PostgreSQL acceptance proves Lease-safe candidate review, atomic
  Memory/Event/Session/Workspace advancement, next-task confirmed recall and
  durable recovery selection (`6 passed`); the focused Memory matrix is
  `85 passed`. Local SQLite behavior is unchanged. Mem0 delivery/runtime remains
  separately locked and is not implied by this closeout.

- Orchestration package boundary is integrated into `cloud-agent`
  (`AL-BOUNDARY-ORCH-01`, source PR #260 / `codex/al-boundary-orch-01`,
  ADR-021): the
  deterministic orchestration domain — plan/budget contracts, DAG validation
  and scheduling, five-layer
  completion gate, worktree merge fix loop, Agent Team contracts and the
  ordinary `system/orchestrator@1` definition — moved from `agent-core`
  into the new `agent-orchestration` workspace package as pure renames +
  import rewrites, with the nine focused test modules moved to
  `tests/agent_orchestration/`. The undeclared `agent-core → agent-tools`
  reverse dependency is closed and now guarded by a new core architecture
  gate. Review closeout pins the internal wheel requirements to the Zebra
  `0.1.0` distributions; a clean trusted-wheelhouse install no longer
  resolves the unrelated public `agent-tools==1.0.1`. Core, control-plane
  and orchestration boundaries now use AST import allowlists plus exact
  TOML dependency sets, including adversarial future-agent/bare-apps/
  security/HTTP imports. The control-plane gate forbids
  `agent_orchestration` (allowed direction: orchestration → control plane,
  never the reverse).
  `subagents.py` stays in `agent-core` (Focused Subagent is the
  parent-agent mode); the PostgreSQL orchestration adapter stays in
  `agent-storage` and the AG-UI projection in `agent-integrations`, both
  now declaring the workspace dependency. No microservice split and no
  behavior change. Validation: `make sync`/`make check` green (file-size
  1446, Ruff, Mypy 716, Eval 10/10); focused boundary/orchestration matrix
  `133 passed / 4 skipped`; full suite `2614 passed / 0 failed / 342 skipped`
  (real-PG/MinIO suites skip locally as before).

## Current Mainline Snapshot

- Mainline branch is `cloud-agent` (it carries the cloud product line and
  sits ahead of `origin/main`; PRs land on `cloud-agent` and main syncs
  on cut points).

- Client Integration Plane architecture is proposed and under review
  (`CLIENT-ADR-01` on unmerged `codex/client-adr-01`, ADR-CLIENT-01): V1
  browser integration is designed as a durable client plane —
  published Frontend Capability Profiles as the configuration source of
  truth, Client Sessions with one-controller fencing (Observers are
  read-only), and PostgreSQL-durable Client Effects with receipts,
  idempotency and expected-UI-revision checks — while formal business
  writes stay on Host Backend Tools and the agent keeps no arbitrary
  JavaScript/DOM authority. Browser access goes through the Host BFF
  (Direct Browser-to-Zebra stays off). The dependency-ordered 22-card
  CLIENT board (contract → PostgreSQL → admission/API → client context →
  durable client action → suspend/resume → TS/React SDK → conformance →
  Trench pilot → production gate) is registered in `docs/AGENT_TASKS.md`;
  the original docs-only card was expanded by explicit maintainer batch
  activation, so the implementation and governance delta now require review
  together before this ADR can be accepted.

- Client Integration Plane V1 backend and browser-runtime candidate is
  partially implemented on the unmerged review branch (reviewed 2026-08-26): the
  backend chain — capability/session/effect contracts (append-only migrations
  v31-v34; real-PostgreSQL capability/session/effect suites PASS 7/6/6), platform bundle
  composition behind the default-off `ZEBRA_CLIENT_INTEGRATION_ENABLED`
  flag, the Runtime Client API, the schedule-only Worker client
  channel with `waiting_client_effect` suspension and atomic
  receipt-driven resume restoring the original tool call — plus the
  typed TypeScript client-core and initial React hook surface. Review fixes
  separate session credentials from controller fences, renew/release the
  controller lease, require every lease to reference the exact persisted Run
  Binding, bind Worker lookup through Task-to-active-Segment,
  harden legacy migration and exact digest/UI-revision checks, and add the
  dedicated Client Effect AG-UI SSE projection. Cloud HTTP uses independent
  HostGrant and Client Session headers and binds all runtime requests to the
  verified HostContext. Validation: `make check`; full Python suite
  2694 passed / 364 skipped; TypeScript `tsc --noEmit` and 15 Node/React tests;
  real PostgreSQL capability/session/effect suites pass 7/6/6; file-size gate
  0 violations. This is not end-to-end product acceptance: Management audit
  and complete CAS, durable AG-UI Binding/State admission, Worker client-state
  recovery, Client State projection, React HITL runtime evidence, real-process
  reconnect/restart drills, Trench pilot and production gate remain open.

- Task/Turn/Segment lifecycle implemented (2026-08-24, ADR-026,
  `CTX-TURN-*` cards 1-9, `codex/ctx-turn-lifecycle-01`, stacked on the
  `CTX-INHERIT-CLOUD-01` review closeout): a final model answer now closes
  a Turn (`TURN_COMPLETED/FAILED/CANCELLED` with `turn_id/turn_index`)
  instead of always closing the Segment. `conversation` Tasks stay in the
  new `SessionStatus.AWAITING_TURN` and keep one Segment across turns —
  the next human message re-arms the Segment to `ready` with a new
  deterministic Turn; `one_shot` (and every legacy admission, which reads
  as `one_shot`) additionally writes the compatible `SESSION_COMPLETED`,
  so all existing terminal consumers keep working unchanged. MESSAGE
  admission rejects a second normal message while a turn is
  `running/waiting_approval` (`turn_in_progress`), clarifications keep
  continuing their own turn, and API idempotency replays the same turn /
  conflicts on drift. Per-turn consumers are migrated: Memory extraction
  and title generation run after every successful Turn with a per-turn
  window and receipt anchoring, the workspace returns to `prepared` on
  `TURN_COMPLETED`, AG-UI emits one `RUN_FINISHED` per Turn (plus
  `RUN_STARTED` for the next turn) and the task stream stays open in
  `awaiting_turn`. Crash reconciliation heals a crashed one-shot
  `TURN_COMPLETED(closes_segment=true)` -> `SESSION_COMPLETED` window
  idempotently without re-invoking the model. Context coverage now fails
  closed on an uncovered gap between the active Capsule and the truncated
  History window and records explicit truncation omissions. The public
  task API adds `task_status`, `current_turn_status`, `turn_id`,
  `active_segment_id`, `interaction_mode` while keeping `status`.
  Latest validation: full repository `2677 passed / 349 skipped`, Context
  PostgreSQL `8/8`, Event PostgreSQL `15/15`, Cloud PG+MinIO composition
  `33/33 PASS`, and `make check` green (size `1462`, Mypy `723`, Eval
  `10/10`). The
  ADR-026 acceptance matrix covering multi-turn single-Segment continuity,
  one-shot legacy compatibility, admission conflicts, idempotency replay,
  crash healing and per-turn AG-UI boundaries. Not yet done: the optional
  explicit legacy Task upgrade path (last in the ADR-026 rollout order),
  full Cloud PostgreSQL+MinIO E2E with multi-worker crash drills, and the
  Trench 16-input cross-service acceptance.

- Cloud Context inheritance review closeout landed (2026-08-24,
  `CTX-INHERIT-CLOUD-01` closeout on
  `codex/cloud-context-inheritance-01`): automation handoff seeds
  (`source=session_handoff` / `actor_kind=automation`) no longer pollute
  the materialized History tail or the INITIAL/CONTINUE mode tally; SQL
  truncation is detected via limit+1 and surfaces as
  `history_tail_truncated` / `history_prefix_uncovered` omissions instead
  of silently dropping the prefix; the card's claims were narrowed to
  "Cloud Worker consumes authoritative materialization + bounded Child
  inheritance" — ordinary multi-turn Task continuity is owned by ADR-026.
  Validation: focused `15 passed`, Context PostgreSQL `7/7`.

- Cloud Context inheritance is ready for review (2026-08-23,
  `CTX-INHERIT-CLOUD-01`, `codex/cloud-context-inheritance-01`): Cloud Worker
  now consumes one PostgreSQL-authoritative materialization generation for
  recent History, active Capsule and confirmed scoped Memory. Durable children
  explicitly choose `fresh`, `capsule`, `fork_tail` or `resume`; non-fresh
  inputs are bounded, source-attributed, checksum-protected and frozen into the
  Child `TASK_PREPARED` Event. Handoff acceptance/files/validation/failures/
  questions/Artifacts are model-visible under a 2048-token auxiliary budget;
  any compiler-side truncation is explicitly marked,
  while credentials, hidden reasoning, raw tool output and Provider-private
  continuation remain omitted. The activated path also fixed PostgreSQL History
  to return the newest bounded text tail from one read-only Repeatable Read
  snapshot and made planner metadata JSON-native so
  canonical Event replay remains exact. Validation: focused `33 passed / 7
  dependency-gated skipped`, Context
  PostgreSQL `6/6`, Cloud PostgreSQL+MinIO composition `33/33`, no-filter full
  repository over real PostgreSQL+MinIO `2952 passed / 0 failed / 13 skipped`,
  and `make check` green (size `1441`, Mypy `718`, Eval `10/10`). Containers,
  networks and volumes were cleaned. Trench production acceptance is unchanged.

- Maintainer line acceptance closed (2026-08-21, gate 5, reviewed at
  `cloud-agent@5bab4b57`): the complete 59-path delta from
  `e2f76046^1..5bab4b57` was reviewed across Host admission/freeze,
  HTTP/auth, durable delegation, Effect replay, concurrency and recovery;
  no new P0/P1/P2 Cloud blocker was found. Independent validation passed
  `make check` (file-size `1441`, Ruff, Mypy `713`, Eval `10/10`) and a
  no-filter full-repository run over real PostgreSQL + MinIO (`2938 passed /
  0 failed / 11 skipped`); the isolated containers, network and volume were
  removed. `COMPOSE-CLOSEOUT-AUDIT-FOLLOWUP-01` is `Done`. PR #257's
  Backend and Cloud real-service checks are green; the inherited Packaged
  Tauri stop-stream failure remains a separate non-Cloud repository gate.
  Trench real acceptance (gate 3, 16 deployment inputs) is the remaining
  product delivery gate.

- Accepted-baseline delivery gates closed (2026-08-21, `cloud-agent`,
  PRs #255-#257): gate 4 — both inherited repo failures root-caused and
  fixed (mem0 spike insert lagged the 25-column governed-memory schema;
  the fenced effect-consumer replay minted a competing payload artifact
  before the schedule dedup — lookup-by-ledger-key now returns the
  stored dispatch for business-identical replays). Gate 1 — Host
  admission contract freeze (ADR-017): v30 host_manifest_freezes stores
  one immutable manifest per connector profile revision; admission
  get-or-fetches it BEFORE the atomic transaction and the binding
  carries the REAL manifest digest; the Worker consumes the frozen
  manifest (discovery disabled in the regression), unbound host-context
  sessions build a local-only surface per their frozen contract, and
  pinned-but-unfreezable admissions fail closed with 503. Gate 2 —
  real HTTP/auth-boundary E2E: the actual FastAPI app on a real
  uvicorn socket, RS256-signed Host Grants verified against a
  PostgreSQL authority registry (only the JWKS resolver is a test
  seam), covering 401/403 paths (anonymous, garbage grant, disallowed
  origin, missing scope, consumed jti), full-body idempotent replay,
  409 conflict, and worker completion of the HTTP-created session.
  Validation: no-filter full-repo over real PG+MinIO 2938 passed /
  0 failed / 11 skipped; make check green (mypy 713 files). Remaining
  gate: Trench real acceptance (inputs pending); maintainer line
  acceptance is closed above.

- Strict-revision closeout (2026-08-21, `cloud-agent`, PR #254):
  expected_revision is now a strict int in BOTH SessionCommand and
  SessionCommandAcceptedPayload — a corrupted JSON true/float/string is
  rejected instead of silently coerced to the integer a fingerprint was
  computed over (bool/float/string rejection tests added). The
  adversarial run-key regression now derives its payload from
  SessionCommand.event_payload() and corrupts exactly one field
  (command_id), so the core fingerprint stays correct by construction
  and the test cannot go falsely green if the algorithm evolves. The
  audit follow-up card's ownership list was regenerated from the actual
  `e2f76046^1..HEAD` diff (46 paths incl. the deleted research_binding,
  PROGRESS.md and every touched test) and records all seven rounds
  (#248-#254); it stays `Review` until the maintainer accepts the line.

- Review-round P2 closeout (2026-08-21, `cloud-agent`): the run-event
  pre-check now validates through the CORE contract instead of a local
  copy — the payload must parse as SessionCommandAcceptedPayload (UUID
  command/session ids, enum kind, bounded fields), rebuild into a
  SessionCommand, match kind=run/session/key/empty payload, and the
  accepted fingerprint must equal the command's own core-computed
  fingerprint. A durable event with a self-consistent fingerprint but a
  non-UUID command_id (injected via raw SQL, i.e. direct store
  corruption the validating append path would reject) now fails closed
  into idempotency_conflict instead of being rebuilt as 202 accepted
  (regression reproduces exactly that injection). Governance: the audit
  follow-up rounds #248-#253 now have an ownership card
  (COMPOSE-CLOSEOUT-AUDIT-FOLLOWUP-01) listing the actual branches and
  owned paths; F4/F5's stale branch/ownership lines point to it. Note:
  the no-filter full-repo number is subject to external-model drift —
  the DeepSeek smoke test failed transiently in the maintainer's run on
  an empty provider reasoning_content, independent of this line.

- Fifth review round: truncation prefix + run-key semantics (2026-08-21,
  `cloud-agent`): closes the two P1s found in PR #251. Canonical CJK
  summaries keep the longest original prefix fitting the per-child
  JSON-escaped budget via binary search — the previous cut emptied
  4000-char Chinese answers into the shared fallback (both producer and
  verifier read that fallback, so equality held while the answer was
  gone); regressions now require non-fallback, original-prefix,
  near-budget canonical forms plus the 16-child command-contract
  reconstruction. The run pre-check validates the persisted event
  completely (type, kind=run, session, key, empty payload,
  self-consistent fingerprint) before rebuilding; a cancel wearing the
  run key returns idempotency_conflict through the create replay (the
  reconciler propagates the conflict instead of the stale admission
  body). Standard full-repo selector over real PG+MinIO: 2926 passed /
  2 pre-existing failures / 11 skipped; `make check` green.

- Fourth review round: command-contract closure (2026-08-21,
  `cloud-agent`): the canonical child summary now budgets the exact
  serialization the command contract measures (json.dumps with
  ensure_ascii — CJK escapes to 6 bytes/char) at 3 KiB per child with
  whitespace-free ends, so the worst legal epoch (16 children with long
  Chinese answers) produces a wakeup payload that reconstructs into a
  valid SessionCommand (regression drives the real wakeup service over
  real PostgreSQL and validates the consumer's exact reconstruction;
  previously 16 CJK summaries measured 66,947 escaped bytes and were
  rejected). Truncation boundaries landing after a space can no longer
  break the Worker verifier's exact match (canonical form is
  edge-whitespace-free; the recovery side's defensive strip became a
  no-op). queue_cloud_run now looks up the persisted run event by
  command key BEFORE submitting — the crash window where the run event
  committed but the receipt body was never synced heals on replay
  (rebuild from the event + receipt re-sync) instead of re-submitting
  into idempotency_conflict and returning a stale ready/no-command body
  forever (regression simulates the exact window). Validation, standard
  full-repo selector over real PG+MinIO: 2925 passed / 2 failed /
  11 skipped — both failures (mem0 logical-reset spike, fenced
  effect-consumer replay) pre-exist on the PR #250 tree per the
  maintainer audit and are unrelated to this line; `make check` green.

- Third review round: multi-Worker wakeup closed (2026-08-20/21,
  `cloud-agent`): wakeup processing now serializes per parent (FOR
  UPDATE on the parent stream row) and emits a deterministic,
  per-epoch-idempotent wakeup event — 8 concurrent workers on one child
  produce exactly one wakeup; two children terminalizing concurrently
  join into one wakeup carrying both results (the prior race could emit
  8 duplicate wakeups or strand the parent with zero). Cancelled
  children settle legally (shared canonical reader includes
  session_cancelled; 2048-byte UTF-8-safe truncation shared by producer
  and verifier keeps worst-case 16-child payloads inside the 64 KiB
  command contract while preserving exact-match verification). API
  create idempotency is closed end to end: duplicate run commands are
  rebuilt into the accepted shape from the persisted event — 16
  concurrent same-key creates ALL return 201 with one identical full
  body, and the crash-after-run-commit replay now heals instead of
  returning a stale ready/no-command body forever. New real-PG
  regressions: same-child×8, distinct-children concurrent join,
  cancelled-child verification, 16-thread full-API create. Validation:
  2431 non-PG + 461 real-PG tests, `make check` green. Remaining
  follow-ups unchanged (Host manifest freeze at admission, Trench
  inputs; E2E still application-level API, not HTTP/auth).

- Second audit round closed on the durable delegation chain (2026-08-20,
  `cloud-agent`): the six P1 findings of the PR #248 review are fixed
  with real-PG evidence. Wakeup trust: only HARNESS-actor resume commands
  can wake a waiting parent (a USER resume neither resumes nor injects —
  restore fails closed without the trusted wakeup); every delivered
  child result is re-derived from the child's own terminal event inside
  the wakeup transaction AND re-verified by the Worker (terminal link +
  matching projection status + identical summary) before injection.
  Real answers: the wakeup reads `metadata.assistant_message`, not the
  lifecycle `summary`; the E2E's parent model can only finish after the
  child's real answer arrives in its conversation. Concurrency:
  admission idempotency claims keys with INSERT ... ON CONFLICT DO
  NOTHING (16 threads → 1 create + 15 identical replays); delegation
  losers roll their child back with the transaction and replay the
  winner's link (16 threads → 1 materialize + 15 winner replays, no
  orphans). Multi-child: the wakeup evaluates the durable
  ParentContinuation — parallel delegations keep the parent suspended
  until every epoch child is terminal, then one wakeup carries all
  results and the parent injects one real result per delegated call.
  Two-phase heal: a replayed create whose run command was lost re-
  submits it under the same command key and syncs the stored body. The
  wakeup append position derives from the event stream (MAX sequence),
  not the lagging projection. Validation: 2431 non-PG + 457 real-PG
  tests passed, `make check` green; new suites:
  `test_postgres_default_chain_scenarios.py` (forged resume,
  two-children join, replay requeue) and
  `test_postgres_concurrent_idempotency.py`, all registered in the
  compose runner. Known follow-ups unchanged: Host manifest/credential
  freeze at admission, Trench cutover inputs.

- Default-composition durable delegation proven end to end (2026-08-20,
  audit-fix branch on `cloud-agent`): the 2026-08-20 maintainer audit of
  PR #247 found all three "fixes" dead on the default path — the durable
  child could never materialize (fabricated `derived.local` parent
  binding + capability mismatch), the parent wrote SESSION_COMPLETED
  before SESSION_SUSPENDED with a contract-violating payload, and the
  idempotency hash diverged between API replay and PG admission (plus
  non-serializable attachment/UUID payloads). All closed on the real
  path: admission now freezes a binding for every cloud session
  (Host-bound pins the Host grant; internal sessions pin a
  deployment-authority binding) inside the atomic v25 transaction with a
  round-trippable snapshot; the tool loop suspends the parent on
  `suspend_after_turn` by freezing a `SUBAGENT_DELEGATED` join-state
  event (conversation, counters, tool-call identity) BEFORE any terminal
  event; the child runs READ_ONLY on a `research` tool profile (no
  `agent.research` — durable depth 1 is additionally enforced against
  the delegation link) with a binding narrowed to
  `{agent.execute, evidence.read}`; the wakeup command carries the
  child's terminal summary and the resumed parent injects it through the
  completed-tool continuation (`SESSION_RESUMED` now legal for logical
  resumes); idempotency uses ONE canonical hash computed by the API from
  the raw payload, stores the full 201 body atomically (run-command
  composition syncs it afterwards), replays it verbatim and 409s on
  hash conflict; child admission + delegation link commit in one
  transaction (no orphan children). Fixed three latent default-chain
  bugs the old component tests could not see: `load_task_binding` wrote
  a partial snapshot JSON no consumer could validate,
  `AttemptAuthorityEvidence.persist` recovered without the worker lease
  (cloud path always raised), and the workspace-projections CHECK
  rejected the `research` profile (v29 migration). New E2E
  `tests/agent_storage/test_postgres_default_chain_e2e.py` drives the
  REAL default API + Worker loop + `agent.research` over real
  PostgreSQL + MinIO with only the model transport scripted (registered
  in the compose runner). Validation: 2431 non-PG + 452 PG tests
  passed, `make check` green. Known follow-ups (explicitly not closed):
  Host-connector manifest/credential freeze at admission (Worker still
  discovers live at gateway build), and the Trench cutover chain.
- Agent Layer phases B–D executed (2026-08-18, PRs #208-#216): Phase B
  closed with `AL-TASK-BIND-CON-01` (immutable binding snapshots and
  capability intersection), `AL-CONNECTOR-PG-01` (v24 registry, immutable
  revisions, CAS bindings, real-PG evidence) and
  `AL-TASK-ADMISSION-PG-01` (v25; one-transaction admission across events,
  projections, task index, binding and idempotency with mid-transaction
  crash-injection rollback). Phase C closed with `AL-AUTH-WORKER-01`
  (P0.4: `BoundHostExecutionAuthorityResolver` derives Attempt authority
  from the frozen binding with fail-closed drift/expiry and narrowing-only
  revalidation), `AL-HOST-EGRESS-01` (P0.2 implementation side: pinned
  immutable connector profiles with memory-only ephemeral credentials) and
  `AL-HOST-EFFECT-01` (uncertain write receipts reconciled through the
  pinned profile path; blind retries structurally absent). Phase D's
  in-repo portion closed with `AL-QUERY-API-V1-01` (task-level AG-UI
  cursors survive rollover) and `AL-HOST-CONFORMANCE-01` (two-vocabulary
  fake hosts pass one shared 18-test suite over the real admission and
  effect paths; zero-branch gates). 14/16 cards Done:
  `AL-API-DECOUPLE-01` (#217) additionally moved
  `agent-runtime`/`zebra-agent-worker` out of the API's core dependencies
  into a `[local]` extra with lazily imported seams, so a cloud-only
  deployment packages the API without Worker or Runtime execution. The
  remaining two (`AL-TRENCH-CUTOVER-01`, `AL-LEGACY-REMOVAL-01`) are
  hard-gated on `EMB-TRN-READ-E2E-01` real-stack acceptance evidence and
  stay Locked until the maintainer provisions the deployment inputs
  (Trench/Zebra HTTP endpoints, both stacks' PG/Redis/object-store health,
  Grant exchange, Worker restart hook, and the Trench session cookie).
- Agent Layer Phase A executed (2026-08-18, PRs #204-#207 on `cloud-agent`):
  `AL-BOUNDARY-CON-01` lands the `agent-control-plane` workspace package
  (core-only dependency, boundary gate, `AgentAction` route vocabulary);
  `AL-HOST-CONTRACT-V1-01` freezes the capability/grant-scope separation,
  single-segment JSON-pointer resource binding rules, digest-canonical
  manifest v1, uncertain effect receipts and the ephemeral credential seam;
  `AL-WORKER-GENERIC-01` deletes the Worker's Trench tool/argument/resource
  branches — resolution now runs generically from manifest binding rules,
  legacy manifests are enriched by the Host adapter in integrations, and a
  vocabulary gate forbids Host names in Worker production code;
  `AL-CONNECTOR-CON-01` freezes immutable outbound connector profiles
  (bare-HTTPS origins, secret-free credential refs) and namespace bindings
  with published/deprecated/revoked lifecycle plus the operator-only
  registry Port. Phase B implementation cards (`AL-CONNECTOR-PG-01` from
  migration v24, `AL-TASK-BIND-CON-01`, `AL-TASK-ADMISSION-PG-01`) remain
  `Locked` awaiting activation.
- Agent Layer direction ratified (2026-08-18, `AL-PLAN-01` `Done`): Zebra
  Agent Layer = Agent Control Plane + Host Integration Plane, landing first
  as a logical `agent-control-plane` application package inside `apps/api`
  (no new microservice yet), with the Runtime untouched. The five
  architecture decisions are recorded in ADR-017; the authoritative
  engineering plan is `docs/cloud-agent构建实施方案.md` (review baseline
  `main@bb3a1bce`, key claims re-verified on ratification day). Sixteen
  `AL-*` implementation cards are registered `Locked` in four phases
  (boundary/protocol, connector/task-binding, execution authority/egress,
  API/conformance/migration); highest-leverage starters are
  `AL-HOST-CONTRACT-V1-01`, `AL-WORKER-GENERIC-01` and
  `AL-CONNECTOR-CON-01`, which together free the Worker from all Trench
  vocabulary and enable zero-branch second-Host onboarding.

- Snapshot date: `2026-08-16`
- 非产品决策收口（maintainer directive "除接入 Trench 外相关的功能全部
  做完，多租户也要开发完毕，用户体系是外挂的"）：多租户三切片全部落地——
  v23 迁移把租户 namespace 持久化到 session 投影（TASK_PREPARED host
  context 绑定一次），API 会话/任务/审批/流/AG-UI/users/tenants 内存读面
  全部按调用方租户隔离（跨租户 404，未绑定会话保持 operator 域），默认
  Cloud Worker 经 `TenantScopedAuthorityResolver` 在每次 Attempt 前持久化
  `execution_authority_resolved`（issuer 钉定、租户 namespace per-scope、
  外来 issuer fail closed）；顺带修复 `validate_event_payload` 的
  python-mode dump 泄漏 datetime 到 PostgreSQL Jsonb 的缺陷。扩展体系
  `EXT-PLUGIN-01`/`EXT-HOOK-01` 与 `ARCH-129-ACP-01`/`ARCH-129-CTX-01`
  按 blanket activation 全部实现并登记 `Done`。剩余 `Locked` 均为治理性
  门控而非工程缺口：`EXT-MARKETPLACE-01`（私有云 GA 前置）、Mem0 消费链
  （Provider admission: DENIED）、`AGENT-DEF-STO-01`（本地 SQLite Registry，
  云端产品定位推迟）。rig E2E 在 authority 事件入流后仍 `PASS` 11/11。
- Agent Definition chain closed: the full runtime chain
  REG（`AGENT-DEF-PG-01`，v19 迁移 + `PostgresAgentRegistry` + draft/version/
  release/eval evidence）→ DRAFT（`AGENT-DEF-DRAFT-01`，物化服务 + API）→
  BIND（`AGENT-DEF-BIND-01`，`AgentDefinitionSnapshot` + TASK_PREPARED +
  投影镜像 + 恢复校验）→ MEM（`AGENT-DEF-MEM-01`，Definition 域 governed
  Memory，v21 迁移）→ TRUST（`AGENT-DEF-TRUST-01`，内容信任与威胁模型）→
  EVAL（`AGENT-DEF-EVAL-01`，`AgentVersionPublicationGate`）→
  PUB（`AGENT-DEF-PUB-01`，受控发布 API + enforcement_mode，v22 迁移）全部
  `Done`；真实 PostgreSQL 矩阵 437 passed，本地套件 1290 passed，`make check`
  （file sizes/ruff/mypy 649/eval gate 10/10）全绿。`AGENT-DEF-STO-01`（本地
  SQLite Registry）按产品定位继续推迟。
- Durable positioning (2026-08-16, maintainer): the product is the cloud
  agent; the local agent exists to develop and prove the agent runtime and
  is not an independent product goal. Recorded explicitly in `AGENTS.md`
  (Product Positioning) and the `README.md` introduction; mainline
  prioritization follows cloud product value per ADR-012.
- Maintainer batch closeout: the entire 2026-08-10 to 2026-08-12 cloudline
  stack (`CLOUD-INTEGRATION-REG-01`, `CLOUD-TRN-NEXT-PLAN-01`, the three
  `QA-CLOUDLINE` quality baselines, the three `ARCH-CONFIG` boundary cards,
  `CLOUD-DEPLOY-PROFILE-CON/01`, the three `CLOUD-COMMAND` cards, the three
  `CLOUD-LIVE` cards, `CLOUD-REC-PROD-CON/PG-PITR/S3`, `CLOUD-DEPLOY-HELM-01`,
  `CLOUD-REAL-SVC-CI-01`, `CLOUD-K8S-GVISOR-E2E-01`, the `EMB-AUTH`,
  `EMB-AGUI`, `EMB-HOST-GW` and `EMB-HOST-RUNTIME` cards) was fast-forward
  merged into `zebra-cloud-trench` at `ca88aeba`, and the rebased
  `CLOUD-EFFECT-COMP-CLOSE-01` implementation merged as `bbd6108d`. All of
  these cards are recorded `Done`; per-card prose in
  `docs/AGENT_TASKS.md` is preserved as historical evidence. The preserved
  dirty-mainline handoff snapshot was kept on
  `codex/cloudline-worktree-snapshot` (removed 2026-08-17 during branch
  cleanup; superseded by mainline history). Follow-up correction
  (2026-08-17): the post-review gaps the card owner had reopened on
  `codex/cloud-effect-comp-close-01` — unknown Memory commit recovery
  (`cloud_memory_recovery`), fail-closed execution preflight
  (`execution_preflight`), receipt read validation, and the real-PostgreSQL
  compose runner under `tests/compose/cloud_effect_composition/` — were
  merged back into `zebra-cloud-trench`; `CLOUD-EFFECT-COMP-CLOSE-01` is
  `In Progress` again until its focused test acceptance criterion is
  re-verified. Verification closeout (2026-08-18): the real-PostgreSQL
  compose runner passes `19 passed` with
  `ZEBRA_CLOUD_EFFECT_COMPOSITION_TEST_RESULT=PASS` (isolated PostgreSQL +
  MinIO); one contract gap found and fixed — cross-session receipt lookups
  now raise a session-scoped `GovernedMemoryConflictError` instead of the
  generic identity-reuse message. The card is `Done`.
  Registry hygiene (2026-08-18): stale cards whose PRs merged in July
  (`CTX-SEG-01` #176, `FINOS-HAR-03` #169, `SUBAGENT-UX-01` #177,
  `WEB-UX-01` #178) and `CLOUD-WORKSPACE-CP-PLAN-01` (all seven successors
  `Done`) are closed; the registry now reflects reality with
  `EMB-TRN-READ-E2E-01` as the only open engineering item.
  `ARCH-RUNTIME-V2-PLAN-01` is `Done` (2026-08-18): the proposal's §2/§10
  were delta-aligned to the post-#194 `main` — the review confirmed the
  v2 direction was validated by implementation (Gate B–G cards all `Done`;
  every originally-missing symbol exists in code), and residual increments
  must be activated as new path-bounded cards.
  PR #194 merged 2026-08-18 (`91251fa5`): `main` again carries the full
  cloud mainline; branching returns to main-based flow.
  `EMB-TRN-READ-E2E-01` was re-attempted on the merged main and correctly
  produces the structured `BLOCKED` result (all 16 deployment inputs
  enumerated); it remains
  `In Progress` and fail-closed pending isolated cross-service inputs.
  Host cleanup follow-up (`QA-RIG-SCRATCH-VOL-01`, `Done` 2026-08-18): the
  2026-08-18 Desktop cleanup found seven leaked zebra RAM volumes — five
  `ZEBRACPE2E*` rig scratch volumes (the effect-default E2E fixture only
  detached on mount failure) plus workspace-CP probe mounts; all were
  ejected and their mount points removed, and the rig fixture now owns its
  scratch volume through a context manager that force-detaches on every exit
  path, so repeated rig runs no longer accumulate volumes on the host.
  `In Progress` and fail-closed pending isolated cross-service inputs.
- `CLOUD-EFFECT-DEFAULT-E2E-01` is `Done` with the full 10-scenario matrix
  passing on the rig: the two 2026-08-16 fault-injection scenarios verify
  that killing the Worker during the post-tool model turn recovers to a
  deterministic suspension with zero re-execution, and that rotating the
  control-plane epoch mid-execution rejects the stale terminal mutation
  while the effect reaches deterministic uncertain reconciliation. The
  completed-tool continuation recovery (`recover_approved_continuation`
  completed adjudication plus the `continue_completed_tool` harness path,
  covering executed and failed terminal outcomes) and command-consumption
  skip logging shipped with regression tests; the suspended-command-lane
  recovery follow-up is closed: the rig failure was a fixture bug (killing
  only the `uv` wrapper orphaned the worker, which suspended the session
  itself via model-call timeout); the scenario now kills the whole process
  tree and the killed session recovers through the completed-tool
  continuation to `session_completed` with zero re-execution.
  `CLOUD-WORKSPACE-CP-E2E-01` is `Done`: the automated
  `workspace_cp_provisioned_side_effect` scenario passes on the gVisor rig
  and the full runner returns `ZEBRA_EFFECT_DEFAULT_E2E=PASS` (11/11
  scenarios). The macOS APFS chmod fixture blocker is fixed by applying the
  mode change from inside the colima VM plus a guest-side write probe.
  `CLOUD-WORKSPACE-CP-PLAN-01` is registered as `Planning` for the P0.3
  Workspace Control Plane, splitting seven path-bounded successor cards
  (contract, PostgreSQL authority, provisioning provider, API command
  surface, Worker runtime wiring, GC/reconcile, default-entrypoint E2E).
  Previously `In Progress` with its execution tier
  validated on a test-only gVisor rig: the default Worker executed a real,
  policy-approved `command.run` side effect inside a gVisor sandbox through
  the durable command lane; PostgreSQL holds exactly one `succeeded` Effect
  with terminal Event and payload binding, MinIO holds both finalized
  versioned payloads, restart cycles do not duplicate the side effect, and a
  no-tool session reaches `COMPLETED` with governed Memory finalization.
  `lease_loss_uncertain_reconcile` stays skipped pending a fault-injection
  design. Composition tier (no engine) still closes green with `BLOCKED`
  (2). Recorded findings: inline execution never populates outbox
  `claim_fencing_token` (dispatch-consumer lane owns that). The
  post-approval wedge was root-caused by an instrumented rig experiment
  and fixed on 2026-08-15: `accept_persisted_event` drove guard-committed
  events through the legacy `index_event`/`upsert` path that the cloud
  Event-derived adapters forbid, aborting before projections advanced and
  leaving the event store ahead of the projection row, which made every
  terminal append conflict. The fix mirrors the recorder's transaction
  path (advance the view, index through fenced `index_worker_event`,
  save projections) and carries a regression test; the approved
  side-effect session now completes with a final model turn on the rig
  and the E2E matrix asserts it. The post-start fail-closed resume
  defense intentionally stays; genuine mid-execution Worker death
  checkpointing, the lease-loss fault-injection scenario and
  command-consumption failure logging remain on the successor card. The
  suspended-command-lane item closed on 2026-08-16: a local reproduction
  with a real hanging gateway proved that the exact durable death shape
  (completed approved tool plus a dangling model request from the killed
  Worker) already recovers through the completed-tool continuation to
  `completed` with zero re-execution — locked by a regression test — and
  the earlier `suspended` observation was rig-specific; the E2E death
  scenario now asserts completion. The worker loop additionally skips
  poisoned ready sessions with a logged reason instead of crashing the
  whole Worker on `WorkerExecutionError`. Previously: the repository now carries a fail-closed runner
  (`tests/compose/effect_default_e2e/`) that drives real PostgreSQL 17.5,
  MinIO, the committed API application object, the default Worker entrypoint
  and a provider-shaped OpenAI-compatible stub model. The composition
  scenarios (infrastructure, session acceptance, worker fail-closed with zero
  Effect side effects across repeated cycles, handoff Effect read) pass and
  are recorded in `docs/CLOUD-EFFECT-DEFAULT-E2E-01.md`. Source review and a
  host prototype proved runtime provisioning precedes the first model call,
  so the six execution-tier scenarios stay explicitly
  `gvisor_engine_absent`: the runner reports
  `ZEBRA_EFFECT_DEFAULT_E2E=BLOCKED` (exit 2) and never derives a PASS from
  composition-tier evidence. The execution tier needs a runsc-capable engine
  and its implementation slice; the local colima `zebra-gvisor` VM's runsc
  sandbox does not start under nerdctl yet.
- `CLOUD-EFFECT-COMP-CLOSE-01` is `Done` after maintainer activation and
  rebase onto the merged cloudline. It is a narrow application-composition
  gate: the default Cloud Worker now composes the typed
  `CloudWorkerComposition` (Effect dispatch, projection transaction,
  deployment namespace, cloud Artifact and Provider Continuation factories)
  instead of an unsafe `ControlPlaneStores` cast, the API handoff reads the
  narrow `EffectStateReadPort`, and cloud Memory finalization commits through
  the governed aggregate. It does not make the platform production-ready.
- `CLOUD-TRN-NEXT-PLAN-01` is in `Review` on
  `codex/cloud-trench-next-plan-01`, intentionally stacked after the regression
  fix. The inspected next-step plan is recorded in
  [Zebra Cloud 与 Trench 下一阶段执行计划 v1.0](./docs/Zebra%20Cloud与Trench下一阶段执行计划_v1.0.md).
  It makes the first product milestone the production Trench read-only vertical
  slice, but first gates it on a green cloud mainline, coherent PostgreSQL +
  gVisor production composition, stateless command-only API, durable replay plus
  Redis live tail, real-service CI, production recovery and deployment evidence.
  `EMB-HOST-RUNTIME-01` and the Trench-side `TRN-HOST-READ-AUTH-01` successor
  are now activated in isolated worktrees; no P4+, Memory runtime or Agent
  Definition runtime work is activated.
- `QA-CLOUDLINE-PY-01` is `Review` on
  `codex/qa-cloudline-py-01`. It owns the Python size/Ruff/Mypy gate after the
  Lease/API regression fix. The integrated Zebra line now passes Mypy over
  `617` source files and the full backend is `2210 passed, 275 skipped`; the
  existing concurrent PostgreSQL/Memory size and export fixes were validated
  as an isolated handoff snapshot, and the dirty `zebra-cloud-trench`
  worktree is preserved unchanged.
- `QA-CLOUDLINE-DESKTOP-01` is in `Review` on
  `codex/qa-cloudline-desktop-01`. It split the remaining Desktop stylesheet
  size violation without changing the composer CSS contract and made the
  long-stream/stop assertions event-driven. Node 22 build, all Desktop static
  checks, file-size validation, and the eight Playwright tests pass. The default
  Tauri check remains environment-blocked by the global USTC Cargo mirror;
  direct rsproxy Cargo validation passed with `--locked`. A macOS packaged
  `.app` build also passed, while packaged WebDriver execution remains a
  Linux CI concern because `tauri-driver` reports that macOS is unsupported.
- `QA-CLOUDLINE-CI-01` is in `Review` on `codex/qa-cloudline-ci-01`. It keeps
  the canonical Quality jobs intact, adds loopback proxy bypass to Desktop and
  packaged jobs, and updates the packaged driver helper to the durable
  cancellation and suspended-state contracts. The local Gate 0 matrix is
  green; the previous PR #194 failures are confirmed stale and predate the
  Lease, atomicity, stylesheet, and event-driven assertion fixes. Real OS
  sandbox smoke and the 20-cycle soak pass locally; canonical remote workflow
  evidence is still outstanding.
- `ARCH-CONFIG-BOUNDARY-01` is in `Review` on
  `codex/arch-config-boundary-01`. ADR-021 freezes the provider-neutral
  configuration boundary and the dependency contract passes: reusable packages
  cannot import `apps/*` composition roots, and the five current config imports
  are tracked as exact successor inventory for Integrations/Security.
- `ARCH-CONFIG-INTEGRATIONS-01` is in `Review` on
  `codex/arch-config-integrations-01`. Model, DeepSeek beta, SCM and credential
  builders now accept typed provider settings; `agent-integrations` no longer
  imports or depends on `zebra_agent_config`. App roots perform the mapping and
  preserve environment, retry, credential and network behavior.
- `ARCH-CONFIG-SECURITY-01` is in `Review` on
  `codex/arch-config-security-01`. Security credential policy now accepts only
  the minimal provider/token reference and has no `zebra_agent_config` import;
  redaction and provider validation remain unchanged. The package dependency
  inventory is now empty.
- `CLOUD-DEPLOY-PROFILE-CON-01` is in `Review` on
  `codex/cloud-deploy-profile-con-01`. ADR-022 and executable settings
  validation freeze the deployment/storage/runtime axes: local is lazy SQLite,
  cloud/production require PostgreSQL + gVisor + quota, and invalid mixes fail
  closed.
- `CLOUD-DEPLOY-PROFILE-01` is in `Review` on
  `codex/cloud-deploy-profile-01`. API, Worker, Storage, migration and
  application Compose now consume the validated storage/runtime axes; full
  Python validation is green, Compose config passes, and the actual image build
  is currently blocked by a Docker Hub authorization timeout.
- `CLOUD-COMMAND-API-CON-01` is in `Review` on
  `codex/cloud-command-api-con-01`. ADR-023 and the core contract freeze the
  durable command envelope, stable idempotency/revision admission and accepted
  Event payload; route/Worker execution remains reserved for its successors.
- `CLOUD-COMMAND-RUN-01` is `Review` on `codex/cloud-command-run-01`. Its owned
  slice adds the stateless API command submission seam and Worker
  run/resume/message wake-up without Runtime side effects in API. Full Python
  validation is green: `2128 passed, 271 skipped`; `make check` is green.
- `CLOUD-COMMAND-CTRL-01` is `Review` on `codex/cloud-command-ctrl-01`. Cloud
  stop/cancel/suspend/resume now use the durable command seam and Worker-side
  control service; local operator behavior remains compatible. Full validation
  is green: `2134 passed, 271 skipped`; `make check` passes.
- `CLOUD-LIVE-WIRE-CON-01` is `Review` on `codex/cloud-live-wire-con-01`. ADR-024
  and the shared post-commit publisher seam freeze durable-first ordering,
  duplicate tolerance and replay-barrier degradation before Redis composition.
  Full validation is green: `2138 passed, 271 skipped`; `make check` passes.
- `CLOUD-LIVE-PUBLISH-01` is `Review` on `codex/cloud-live-publish-01`. Cloud
  API/Worker now compose one namespace-bound Redis publisher around direct Event
  appends; SSE consumption remains next. Full validation is green:
  `2145 passed, 271 skipped`; `make check` and the real Redis runner pass.
- `CLOUD-LIVE-SSE-01` is in `Review` on `codex/cloud-live-sse-01`. HTTP SSE now
  captures a Redis replay barrier, drains durable Events, then tails Redis with
  duplicate filtering and durable polling fallback. Full validation is green:
  `2147 passed, 271 skipped`; `make check` is green.
- `CLOUD-REC-PROD-CON-01` is in `Review` on
  `codex/cloud-rec-prod-con-01`. Its recovery contract freezes PG physical/WAL,
  immutable object copies, restore epoch and identity rotation, machine-readable
  drill evidence, and the read-only → single Worker → ingress sequence. Full
  validation is green: `2147 passed, 271 skipped`; `make check` is green.
- `CLOUD-REC-PG-PITR-01` is in `Review` on
  `codex/cloud-rec-pg-pitr-01`. Its isolated physical base-backup/WAL runner
  restores to a named point, excludes a post-target Event, rebuilds Projection,
  rotates Lease epoch and records cleanup. Real runner and full validation are
  green: `2147 passed, 271 skipped`; `make check` is green. Measurements remain
  local-only (`RPO 0.077309s`, `RTO 6.462744s`).
- `CLOUD-REC-S3-01` is in `Review` on `codex/cloud-rec-s3-01`. Its independent
  versioned MinIO backup-copy/delete/restore runner verifies the PostgreSQL
  Artifact ref, checksum, metadata, namespace and cleanup without reading a
  Worker-local payload. Real runner and full validation are green:
  `2147 passed, 271 skipped`; `make check` is green. Evidence remains local-only.
- `CLOUD-DEPLOY-HELM-01` is in `Review` on
  `codex/cloud-deploy-helm-01`. Its fail-closed chart renders migration/API/
  Worker, Service, Secret refs, non-root/read-only pods, resources, PDBs and
  gVisor RuntimeClass. `helm lint/template` and static tests pass. A real
  isolated Helm install now proves migration hook ordering, API/Worker `2/2`,
  production `/health`, gVisor `/proc/version`, UID `65532`, Worker recovery,
  and cleanup; managed rollout evidence is still not claimed.
- `CLOUD-REAL-SVC-CI-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Its canonical workflow now runs separate
  application, Redis live, PITR, S3 and fresh-restore matrix runners with
  bounded timeouts and always-retained evidence. The integrated Zebra line
  `741a471f` also re-ran application Compose after seeding a valid test-only
  Host registry; the local Docker matrix is green. `actionlint` now passes the
  canonical quality workflow after removing duplicate proxy keys, and the
  Linux container quota smoke reports real `ENOSPC`. No remote Actions or
  managed rollout is claimed.
- `CLOUD-K8S-GVISOR-E2E-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. The fail-closed Kubernetes runner and dedicated
  workflow are implemented. An isolated Linux `colima-zebra-gvisor` cluster
  now passes the full runner (`WORKER_RESTART_RESUME`, quota, NetworkPolicy and
  cleanup); this is local task evidence, not remote canonical CI or managed
  production rollout evidence.
- `EMB-TOOL-CON-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. `ToolContract`/`ToolResult` now carry Host
  execution location, scopes, risk, bounds, idempotency and typed receipt
  metadata; transport, JWT and Trench implementation remain separate tasks.
- `EMB-AUTH-CON-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. The provider-neutral Host Grant/JWT contract
  pins algorithms, issuer/JWKS, exact origins, clock skew and bindings; JWT
  decoding, HTTP and PostgreSQL replay remain separate adapters.
- `EMB-AUTH-PG-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Migration v17, namespace-bound Host registry,
  secret-free Grant audit and atomic PostgreSQL `jti` replay now pass the real
  Compose runner (`4 passed`) and the existing control-plane migration runner
  (`11 passed`); HTTP/JWT and Trench remain out of scope.
- `EMB-AUTH-HTTP-01` is in `Review` on
  `codex/cloud-real-svc-ci-01`. Cloud/production HTTP now requires an injected
  Host Grant authorizer before route dispatch, and CORS uses normalized exact
  HTTPS origins without reflection; focused auth/HTTP (`5 passed`) and existing
  HTTP/command/live/stream (`52 passed`) matrices are green.
- `EMB-AUTH-01` is in `Review` on `codex/cloud-real-svc-ci-01`. A signed RS256
  PyJWT decoder with bounded injectable JWKS resolution now composes with the
  PostgreSQL registry/replay authorizer; the production HTTP factory wires that
  authorizer by default for the concrete cloud store bundle, while explicit
  injection remains available for tests and alternate roots. The real Host
  PostgreSQL/API matrix is `5 passed`, with no raw token in HTTP/audit evidence.
- `EMB-AGUI-CMD-01` is `Review` on `codex/cloud-real-svc-ci-01`. The bounded
  `run`/`resume`/`stop` envelope resolves `threadId` to the active durable
  Segment and calls only the existing command service; focused command tests
  pass (`5`), with no Worker execution import or construction.
- `EMB-AGUI-STREAM-01` is `Review` on `codex/cloud-real-svc-ci-01`. The AG-UI
  SSE route validates exact durable cursors, replays and live-tails the Event
  Store, and emits official projected events with a lossless polling fallback.
  Replay/reconnect/live-tail tests pass in the combined matrix.
- `EMB-AGUI-API-01` is `Review` on `codex/cloud-real-svc-ci-01`. Command-only
  API composition, durable AG-UI replay/live tail and existing Host Grant HTTP
  gating pass together; it remains a parent review gate until this branch is
  merged and mainline gates are repeated.
- `EMB-HOST-GW-01` is `Review` on `codex/cloud-real-svc-ci-01`. The typed Host
  gateway verifies manifest digest and workload identity, intersects scopes,
  validates resource/idempotency/SSRF boundaries and returns bounded receipts;
  focused tests pass (`7`) and the Integrations package is `143 passed,
  3 skipped`.
- `EMB-TRN-READ-E2E-01` is `In Progress` on `codex/emb-trn-read-e2e-01`.
  Zebra now owns a fail-closed real-service runner for Trench/BFF/Zebra
  read-only acceptance, with nine named scenarios, secret-free evidence and a
  business-table snapshot invariant. Its contract tests pass (`4`), Ruff and
  targeted Mypy pass; the integrated Trench branch passes the focused backend
  (`66` API, `49` cleaning), migration SQL, frontend build/test/lint, and the
  Zebra branch passes the full quality gate (`2209 passed, 275 skipped`). The
  five local Cloudline runners (application, Redis fan-out, PITR, S3 recovery,
  and fresh restore) are green. The real cross-service run is still `BLOCKED`
  because this machine has no isolated Trench/Zebra HTTP, PG, Redis,
  object-store, Grant exchange or Worker-restart inputs; no cross-service pass
  is claimed. The previously recorded Worker composition seam is now closed by
  the active `EMB-HOST-RUNTIME-01` successor: `build_worker_tool_gateway`
  discovers the Host manifest, exposes its typed tools and routes Host calls
  without local fallback. The Trench-side `TRN-HOST-READ-AUTH-01` successor
  verifies the signed workload binding and preserves read-only scope/resource
  filtering. Both successors are in review on the integrated branches; the
  real cross-service runner remains fail-closed until isolated services and
  credentials are provisioned.
- `EMB-HOST-RUNTIME-01` is in `Review` on `codex/emb-host-runtime-01`. Zebra
  now carries an optional, expiry-aware HostContext from authorized API request
  through TASK_PREPARED persistence and Worker recovery; Worker discovery is
  manifest-first and fail-closed, and Host read tools are routed through the
  typed Host gateway with resource/idempotency binding. Full `make test` passes
  (`2207 passed, 275 skipped`), and `make check` plus the focused API/Core/
  Worker/Integrations/Effect Guard matrix pass. The branch does not claim
  deployment or a real Trench call.
- Gate 3 combined API/Integrations matrix is `204 passed, 3 skipped`; no Trench
  business Tool or Kubernetes gVisor E2E completion is claimed.
- `CLOUD-INTEGRATION-REG-01` is in `Review` on
  `codex/cloud-integration-regressions-01`. It fixes two regressions found on
  `zebra-cloud-trench`: Worker heartbeat now starts from the recovery-renewed
  Lease checkpoint, and local/test API Store composition is lazy again while
  explicit cloud startup remains fail closed. The focused matrix passes `33
  passed, 1 skipped`; the full backend suite is `2104 passed, 271 skipped, 1
  failed`, with only four out-of-scope repository size violations remaining.
- Cloud mainline status is recorded in
  [Zebra Cloud 主线当前状态与后续工作](./docs/Zebra%20Cloud%20主线当前状态与后续工作.md):
  PostgreSQL adapters, API/Worker PostgreSQL composition, application Compose,
  isolated Redis live fan-out and local migration/recovery evidence are complete;
  production recovery and the CopilotKit/Trench production slice remain gated.
  `CLOUD-CONTROL-PLANE-PG-01`
  implementation and focused validation are complete on the isolated branch;
  sidebar closeout is approved and the task is recorded as `Done`; its API/Worker
  mapping remains a later gate. `CLOUD-DELIVERY-TXN-PG-01` is also merged to the
  cloud mainline at `9ec52b16` and recorded as `Done`; its API/Worker wiring,
  runtime selection and external execution remain out of scope.
- Sidebar review of the requested API/Worker PostgreSQL switch returned
  `ACTIVATE-BLOCKED`: the defect is confirmed, but implementation is not authorized
  while the explicit profile contract and dependency registry are incomplete.
  The follow-up contract review returned `CONTRACT-ACCEPTED` and closed
  `CLOUD-PROFILE-COMPOSITION-CON-01` as `Done`; its `CLOUD-LIVE-01` dependency was
  removed because the contract has no live-runtime scope. `CLOUD-API-WORKER-PG-01`
  and `CLOUD-COMPOSE-APP-01` are now `Done` on the cloud mainline. Local SQLite
  remains the default and cloud must fail closed rather than fall back to SQLite.
- `CLOUD-API-WORKER-PG-01` completed its authorized implementation slice and is
  now `Done` after independent Review and fast-forward merge of `d9fd0419` into
  `zebra-cloud-trench`. Focused API/HTTP/Worker and real PostgreSQL Compose
  evidence is green. It owns only shared profile selection,
  PostgreSQL stores injection and the model/tool projection compatibility seam;
  it does not activate application Compose, Redis live, `CLOUD-LIVE-01`, or any
  aggregate gate.
- Context fencing conformance child `CLOUD-AGG-FENCE-CTX-LIFECYCLE-CON-01` is
  now `Done` on its governance worktree. Its Store-level semantic gap was closed
  by `CLOUD-AGG-FENCE-CTX-SEMANTIC-01`, which is also `Done` after sidebar
  `CLOSEOUT-OK`, three zero-write regressions and a real PostgreSQL `18/18`
  focused matrix. The parent `CLOUD-AGG-FENCE-01` is now `Done` as a governance
  gate; the Model/Tool revision successor is now closed as `Done`.
- `CLOUD-AGG-FENCE-HANDOFF-DISPATCH-CON-01` is now `Done` with audit result
  `PASS`; its reserve/abort successor is `Done`, and the dispatch successor
  `CLOUD-AGG-FENCE-DISPATCH-01` is fast-forward merged and closed as `Done`.
  The mainline PostgreSQL runners pass `15/15` and `14/14` with
  `ZEBRA_HANDOFF_AUTH_POSTGRES_TEST_RESULT=PASS` and
  `ZEBRA_HANDOFF_DISPATCH_POSTGRES_TEST_RESULT=PASS`.
- `CLOUD-LIVE-01` is `Done` after completing and fast-forward merging the
  separately owned Redis live event fan-out slice at `cfbebcf7`. It remains
  limited to a provider-neutral Port, a
  bounded Redis Streams adapter and isolated evidence; the local Core/adapter
  matrix is `24/24` (including the non-blocking read and namespace validation
  regressions), the full integrations package is `127 passed, 3 skipped`,
  and the pinned `redis:8.2.1-alpine` host runner passes `1/1` with
  `ZEBRA_LIVE_FANOUT_REDIS_TEST_RESULT=PASS`. The detailed matrix is recorded
  in `docs/CLOUD-LIVE-01.md`. It does not authorize API/Worker startup wiring,
  application Compose, Runtime selection or any Redis authority.
- `CLOUD-COMPOSE-APP-01` is now `Done` on
  `codex/cloud-compose-app-01`. It owns only the non-root multi-target Zebra
  image, the application-only migration/API/Worker Compose overlay and isolated
  smoke evidence; host-side cloud composition already proves API health,
  `PostgresControlPlaneStores` and one Worker PostgreSQL cycle. The production
  `--no-dev` image now declares `uvicorn` as an API runtime dependency, and the
  complete three-container smoke passes with a temporary mirror-only Python
  base override (runtime UID `65532`) and now through the Application Compose
  default mirror with `ZEBRA_APPLICATION_COMPOSE_TEST_RESULT=PASS`. The
  Dockerfile keeps the official Docker Hub digest as its standalone default;
  that direct build remains an external review gap. The base dependency Compose
  remains a separate lifecycle.
- `CLOUD-AGG-FENCE-01` is now `Done` as a governance gate after the aggregate
  review's `PASS` evidence and maintainer continuation closeout. This unlocks
  only the recovery evidence sequence; Runtime/API/Worker selection and
  production rollout remain separate gates.
- `CLOUD-REC-01` is now `Done` as the local recovery evidence gate:
  `CLOUD-PG-MIG-01`, `CLOUD-REC-BACKUP-01`, `CLOUD-REC-RESTORE-01` and
  `CLOUD-REC-DRILL-01` are all independently validated and merged. The local
  drill proves rollback, fenced claim/reconcile races and zero-loss Event
  counts; no production RPO/RTO, PITR or DR claim is made from Compose.
- `CLOUD-PG-MIG-01` is now `Done` on `codex/cloud-pg-mig-01`. The completed
  slice provides canonical read-only SQLite snapshots, migration v16 cutover
  fencing, restricted Event-first import, Session/Workspace/Task rebuild,
  Event-derived Model/Tool projection replay, Context capsule/pointer
  verification, and fenced Handoff operation/envelope/dispatch replay with
  rebuilt-lineage checks, plus namespace-scoped idempotency and governed Memory
  replay, and rowid-evidenced Delivery Audit replay through snapshot v2. The
  PostgreSQL 17.5 runner passes `29/29` with
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS` and deterministic cleanup. New
  zero-write regressions reject legacy Artifact, Effect and Provider
  continuation tables before Event writes; their cloud authority mappings are
  closed as explicit quarantine contracts and runtime ACTIVE write wiring remains
  gated. The PostgreSQL 17.5 runner passes `29/29` with
  `ZEBRA_PG_MIGRATION_TEST_RESULT=PASS` and deterministic cleanup.
- `CLOUD-PG-MIG-LEGACY-CON-01` is now `Done` as the governance parent after all
  three path-bounded children were explicitly activated, independently
  validated and merged.
  `CLOUD-PG-MIG-LEGACY-ARTIFACT-01` is now `Done` after merge commit `bed02e4a`
  from `codex/cloud-pg-mig-legacy-artifact-01`. Its deterministic
  Artifact legacy quarantine/export contract and evidence runner pass the local
  focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5 runner (`5 passed`,
  `ZEBRA_PG_MIG_LEGACY_ARTIFACT_TEST_RESULT=PASS`) with cleanup.
  `CLOUD-PG-MIG-LEGACY-EFFECT-DELIVERY-01` is now `Done` after merge commit
  `62d2e601` from `codex/cloud-pg-mig-legacy-effect-delivery-01`. Its
  deterministic Effect/Delivery quarantine/export contract and evidence runner
  pass the local focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5
  runner (`5 passed`,
  `ZEBRA_PG_MIG_LEGACY_EFFECT_DELIVERY_TEST_RESULT=PASS`) with cleanup.
  `CLOUD-PG-MIG-LEGACY-PROVIDER-01` is now `Done` after merge commit
  `5f275d4b` from `codex/cloud-pg-mig-legacy-provider-01`. Its deterministic
  Provider Continuation quarantine/export contract and evidence runner pass the
  local focused matrix (`4 passed, 1 skipped`) and PostgreSQL 17.5 runner
  (`5 passed`, `ZEBRA_PG_MIG_LEGACY_PROVIDER_TEST_RESULT=PASS`) with cleanup.
  No cloud Artifact/Effect/Provider authority write or runtime wiring is implied.
- The current cloud governance slice
  `CLOUD-AGG-FENCE-WORKSPACE-TASK-CON-01` is now `Done` with audit result `PASS`.
  Its direct Task authority gap is implemented by `CLOUD-AGG-FENCE-TASK-01` at
  `6a31929a`; the focused Task PostgreSQL regression passes `23/23` and
  Handoff/dispatch regression passes `24/24`. The repository-owned
  `CLOUD-AGG-FENCE-WORKSPACE-TASK-EVIDENCE-01` runner is also `Done` at
  `49a8c026`, passing `36/36` on PostgreSQL `17.5-alpine3.21` with deterministic
  cleanup. The parent `CLOUD-AGG-FENCE-01` is now `Done` and no Runtime or
  application Compose activation is implied.
- `CLOUD-AGG-FENCE-MODEL-TOOL-01` is `Done` at implementation commit
  `31347989`. The PostgreSQL adapter now binds a Worker Model/Tool projection
  Event to `expected_stream_revision` and the current stream; its dedicated
  runner passes `8/8` with `ZEBRA_MODEL_TOOL_POSTGRES_TEST_RESULT=PASS`, while
  the existing Control Plane runner passes `11/11`. Both runners clean their
  resources. The parent gate is now `Done` and no runtime activation is
  implied.
- `CLOUD-AGG-FENCE-PROVIDER-01` is `Done` at implementation commit
  `816a1ae0`. `delete_for_worker` now binds the current LeaseFence and
  `expected_stream_revision` to the locked Session stream before soft-delete;
  its reproducible PostgreSQL 17.5 runner passes `4/4` with
  `ZEBRA_PROVIDER_CONTINUATION_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources. The parent `CLOUD-AGG-FENCE-01` is now `Done`.
- `CLOUD-AGG-FENCE-ARTIFACT-01` is `Done` as an evidence-only conformance
  slice. The repository-owned PostgreSQL 17.5 runner passes `13/13` with
  `ZEBRA_ARTIFACT_PAYLOAD_POSTGRES_TEST_RESULT=PASS` and cleans all resources;
  the existing v9 transitions already use the shared namespace, LeaseFence,
  stream CAS and lifecycle revision guards. No adapter or migration changed;
  the parent gate is now `Done`.
- `CLOUD-AGG-FENCE-EFFECT-PAYLOAD-01` is `Done` as an evidence-only
  conformance slice. Its repository-owned PostgreSQL 17.5 runner passes `7/7`
  with `ZEBRA_EFFECT_PAYLOAD_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources; existing payload-aware Effect transitions bind Worker authority
  and atomically coordinate Event, Artifact and outbox state. No adapter or
  migration changed; the parent gate is now `Done`.
- `CLOUD-AGG-FENCE-DELIVERY-01` is `Done` as Delivery boundary evidence.
  Delivery is intentionally an API command claim/receipt lane, not a Worker
  Lease aggregate; its corrected PostgreSQL 17.5 runner passes `12/12` with
  `ZEBRA_DELIVERY_TRANSACTION_POSTGRES_TEST_RESULT=PASS` and cleans all
  resources. No adapter or runtime wiring changed; the parent gate is now
  `Done`.
- `CLOUD-AGG-FENCE-REVIEW-01` is `Done` with result `PASS`. All registered
  path-bounded aggregate evidence is green: Context `18/18`, Handoff
  auth/dispatch `15/15` and `14/14`, Workspace/Task `36/36`, Model/Tool `8/8`,
  Provider `4/4`, Artifact `13/13`, Effect/Artifact `7/7` and Delivery `12/12`.
  The parent `CLOUD-AGG-FENCE-01` is now `Done` after maintainer continuation
  closeout; this does not authorize runtime or application Compose activation.
- `CLOUD-PROVIDER-CONT-PG-PLAN-01` is formally `Done` after sidebar
  architecture review. `CLOUD-PROVIDER-CONT-PG-01` is now `Done` on the isolated
  `codex/cloud-provider-cont-pg-01` worktree, based on `f6c8a926`, with its Core
  contract, PostgreSQL v13 adapter/migration, cloud Worker aggregate seam,
  focused tests, Compose evidence and review fixes committed as `39bbe444` and
  `abd7a7f0`. The sidebar closeout accepted the evidence, and the next storage
  composition card `CLOUD-CONTROL-PLANE-PG-01` is now `Done` after sidebar
  closeout on its isolated implementation branch. Runtime,
  API/Provider HTTP, Desktop, local SQLite, Redis, Mem0 and application Docker
  remain excluded.
- Review task: `CTX-MEM-01` is in PR `#198` and closes the valid parts of GitHub issue `#197` with
  an exact three-user-turn tail, complete tool groups, one strict retry from
  original history, recoverable context suspension, evidence-gated memory
  promotion, and repo-scoped SQLite FTS recall under a token budget. Local
  validation: `63` focused tests, changed-file Ruff, Mypy over `158` source
  files, and release eval `10/10` pass. Full suite: `1747 passed, 8 skipped`;
  the same nine failures reproduce on untouched `main`. The current file-size
  gate is blocked by four inherited violations outside this task. PR CI run
  `30332213200` did not execute any step because GitHub reported an account
  payment/spending-limit gate.
- Verified implementation baseline: `f1e4965` (PR `#174`)
- Product posture: `embeddable Agent Runtime / feature-complete local Beta / single-host Phase A complete`
- Review task: `CTX-SEG-01` has delivered the stable Task, internal Segment,
  unified stream/routing, automatic safe rollover, and SQLite migration slice.
- Active repair task: `CTX-SEG-02` preserves the latest bounded conversation
  checkpoint across terminal follow-up Segments, removes implicit low call
  ceilings, and converts explicit hard-budget exhaustion into recoverable pause.
- Review task: `SUBAGENT-UX-01` makes Subagent use a model-native tool decision;
  simple work remains in the parent and every valid delegation records its reason.
- Active architecture task: ADR-013 replaces user-visible child Sessions with a
  stable Task boundary and backend-internal execution Segments.
- Desktop browser task: `QA-DESKTOP-E2E-01` is Done via PR `#161`
- Runtime blueprint: `ARCH-RT-BP-01` is complete on its local task branch
- Completed Embedded architecture task: `EMB-PLAN-01` on `zebra-cloud-trench`
  replaces the conflicting draft with one CopilotKit/AG-UI target, ADR-015, and
  a dependency-ordered task roadmap. Formal review closed it as `Done`; it is
  documentation-only and does not activate Phase B or any Trench implementation
  card.
- Compatibility task `EMB-AGUI-SPIKE-01` is formally `Done` on the test-only
  closeout branch. It pins `ag-ui-protocol==0.1.19`, validates the canonical SSE,
  interrupt/resume and forward-compatibility boundaries with `11/11` focused
  tests, and adds no production API/Worker, CopilotKit, React SDK or UI wiring.
- Trench `TRN-CPK-SPIKE-01` is merged to Trench `main` at `5c59b22`; its
  focused/full checks, frontend builds, Alembic checks and `git diff --check`
  pass. `EMB-HOST-CON-01` is `Done` on `codex/emb-host-con-01` at
  `ca59753b`: provider-neutral Core Host authority claims, context derivation,
  bounded limits and fail-closed validation pass `16/16` focused and `386/386`
  `agent_core` tests. JWT/JWKS, API/AG-UI, Trench and runtime wiring remain
  separately gated.
- `EMB-AGUI-CON-01` is `Done` on `codex/emb-agui-con-01` at `5485fc2e` after
  Host authority closeout. Its pure, replayable AG-UI projection passes `5/5`
  focused and `132 passed, 3 skipped` package tests; API/Worker routes, Redis
  live fan-out, Trench/CopilotKit runtime and Host transport remain separately
  gated.
- Completed storage composition task: `CLOUD-STO-SEAM-01` on `codex/cloud-sto-seam-01` is the
  first Zebra-foundation task after the maintainer reprioritized durable storage
  and memory ahead of further Trench work. It injects existing control-plane Store
  Ports while preserving the local SQLite profile and adds no cloud dependency.
  Formal review closed it as `Done`; PostgreSQL, Redis, S3 and backend selection
  remain separate gates.
- Completed authoritative storage task: `CLOUD-STO-AUTH-01` on
  `codex/cloud-sto-auth-01` extends that same flat bundle across every durable
  API/Worker collaborator that advances Session state, gates effects or governs
  memory. A/B regressions prove the legacy path is not created; no cloud backend,
  migration or Mem0 integration is selected by this task. Formal review closed
  it as `Done`; Compose, PostgreSQL and Memory Gateway remain separate gates.
- Memory contract task `MEM-GW-CON-01` is formally `Done` on `codex/mem-gw-con-01`; it defines
  provider-neutral confirmed-memory publish, search and delete outcomes. Remote
  hits contain only a Zebra `MemoryId` for mandatory Store revalidation; no Mem0
  adapter, credential, Docker or runtime wiring is part of this slice.
- Completed dependency-container task: `CLOUD-COMPOSE-INFRA-01` on
  `codex/cloud-compose-infra-01` creates the base Docker Compose dependency stack
  and a separate optional Mem0 boot-smoke overlay. Its pinned image, migrations,
  health and anonymous-request rejection are verified locally. Mem0 remains
  derived and replaceable; Zebra application containers stay locked until real
  cloud adapters exist. Formal review closed the dependency baseline as `Done`;
  no Docker-socket operation or runtime selection was made here.
- PostgreSQL Event/Projection storage: `CLOUD-PG-01` is formally `Done` with
  isolated adapters, migration checksums, CAS/idempotency, namespace isolation
  and replay-safe projections. Recorded real PostgreSQL evidence is accepted;
  it is not runtime-selected. `CLOUD-LEASE-PG-01` separately covers
  epoch-scoped, database-clock Lease fencing.
- Lease/fencing contract plan: `CLOUD-LEASE-PLAN-01` is formally `Done`; it
  freezes epoch ownership, database-time TTL, fenced aggregate boundaries and
  uncertain external-effect recovery, while its implementation children retain
  independent gates and no runtime selection.
- Memory storage implementation: `MEM-GW-PG-NATIVE-01` is formally `Done` as a
  PostgreSQL-native, storage-only Memory Gateway with migration v12 and accepted
  isolated evidence. The native admission is `PASS`; Mem0 remains
  denied/deferred and all Runtime/Worker/provider paths stay locked.
- Effect Outbox task in Review: `CLOUD-EFFECT-OUTBOX-01` now has typed Core
  dispatch states and a PostgreSQL aggregate for fenced schedule, `SKIP LOCKED`
  claim, terminal commit, uncertain reconciliation and explicit retry. Its isolated
  Docker Compose PostgreSQL 17.5 matrix passes `49/49`, including fault rollback,
  concurrency, restore epoch, namespace and response-loss cases. It is not runtime-
  selected; Worker integration and any cloud-readiness claim remain locked.
- Integrated Effect consumer task: `CLOUD-EFFECT-CONSUMER-01` runs Lease heartbeat
  on a background thread before recovery, checks ownership at Event and external
  Effect boundaries, and releases through one fenced lifecycle exit. Explicitly
  injected cloud runtimes can now schedule, claim and terminalize durable Effect
  intents; expired claims become `uncertain` for reconciliation and never auto-
  replay. The local SQLite profile still uses its existing ledger, and no backend
  selector or production cutover is included. Its isolated Docker Compose
  PostgreSQL 17.5 consumer matrix passes `58/58`, including heartbeat, stale-fence,
  crash, response-loss and reconciliation cases; dedicated containers, volumes and
  network were removed after the run. Deterministic and full-suite gates retain
  only the confirmed inherited failures.
- Local microservice integration: the reviewed Lease contract, PostgreSQL Lease,
  Effect Outbox and Worker consumer cards are fast-forwarded onto the isolated
  `zebra-cloud-trench@2759345c`. `CLOUD-LEASE-01` is formally `Done` with its
  combined evidence record; it does not select PostgreSQL at runtime or claim
  full aggregate fencing, production cutover or exactly-once external execution.
- Completed aggregate-fencing inventory: `CLOUD-AGG-FENCE-PLAN-01` traces the
  authoritative Context, Handoff, Workspace/Task, Model/Tool, provider-history,
  Artifact and delivery-audit paths and splits them into dependency-ordered cards.
  It keeps Event-derived/read-only models out of the authority layer and API
  commands outside Worker Lease fencing. It is documentation-only and unlocks only
  `CLOUD-AGG-FENCE-CON-01`; the parent gate and adapter cards remain Locked.
- Context fencing conformance is now explicitly split into a governance audit and
  a minimal semantic successor. The audit matrix covers Worker compaction,
  administrative recovery, v7 constraints, fail-closed legacy methods and
  read-only Context Materialization. It records accepted stale-fence, namespace,
  pointer and rollback evidence, but keeps the audit card open until the semantic
  successor's review closes the former Event type and capsule binding gap. The
  successor adds only Store validation, focused tests and a PostgreSQL Compose
  runner; no migration or runtime composition is changed.
- Completed authority-contract task: `CLOUD-AGG-FENCE-CON-01` adds strict
  `WorkerMutationAuthority` and `AdministrativeMutationCAS` types. It reuses the
  existing LeaseFence, permits the empty-stream revision `-1`, rejects noncanonical
  namespaces and keeps aggregate-specific revisions out of the shared type. Its
  focused `19/19`, Core `270/270`, Ruff, strict Mypy and Eval `10/10` gates pass;
  it does not implement PostgreSQL, change Store selection or touch Desktop. Its
  local acceptance unlocks only `CLOUD-AGG-WORKSPACE-PG-01`.
- Added the sole current cloud `Ready` card, `CLOUD-SCOPE-CON-01`, to freeze the
  external opaque `(authority_issuer, namespace_id)` plus bounded
  `allowed_session_ids` read scope. The contract deliberately maps to the
  injected deployment namespace in trusted composition and adds no Tenant model,
  SQL, Runtime selection, Provider HTTP, Desktop, Redis or Mem0 behavior. Its
  successors are the still-locked Provider Continuation and Session History
  adapters.
- `CLOUD-SCOPE-CON-01` is now `Done`: `OpaqueAuthorityScope` is immutable,
  rejects malformed or over-broad allow-lists, preserves the full-scope versus
  deny-all distinction, and leaves external-to-deployment namespace mapping to
  trusted composition. Focused Core `9/9`, full Core `347/347`, relevant
  regressions `32/32` and Eval `10/10` pass; only the two inherited file-size
  violations keep `make check` red. Provider Continuation and Session History
  remain independently locked pending explicit adapter activation.
- `CLOUD-SESSION-HISTORY-PG-01` is now `Done`. It adds only a namespace-scoped
  PostgreSQL read adapter, JSONB row decoding, parity/isolation tests and an
  isolated Compose runner. Local focused validation is `13 passed, 3 skipped`,
  host PostgreSQL Compose validation is `3 passed` with
  `ZEBRA_SESSION_HISTORY_POSTGRES_TEST_RESULT=PASS`, changed static checks and
  Eval `10/10` pass. Provider Continuation, complete Store composition, Runtime
  selection and external Host verification remain out of scope.
- `CLOUD-CONTEXT-CON-01` is now `Done`. ADR-020 and the Core-only
  `ContextMaterializationPort` freeze a read-only, rebuildable generation across
  Session History, the active Context Capsule and confirmed governed Memory.
  Focused contract coverage is `3/3`, related scope/Capsule coverage is `16/16`,
  full Core is `350/350`, changed static checks and Eval `10/10` pass. The
  `CLOUD-CONTEXT-PG-01` is now `Done`: its read-only PostgreSQL adapter and
  isolated Compose runner are implemented, with local Storage `149 passed, 172
  skipped`, Core `350/350`, Eval `10/10`, and host Compose `4 passed` with
  `ZEBRA_CONTEXT_MATERIALIZATION_POSTGRES_TEST_RESULT=PASS`. No Runtime,
  Worker, API, Desktop, SQLite, Redis or Mem0 path is unlocked.
- Completed and formally closed Workspace adapter task: `CLOUD-AGG-WORKSPACE-PG-01`
  adds the additive
  PostgreSQL v4 projection schema and an injected Worker transaction that validates
  current Lease authority and Event-derived Session/Workspace content before
  committing all three primary records atomically. Replay remains monotonic and
  namespace-scoped; Model Call/Tool Run indexes remain replayable follow-up views.
  Lost-response retries now adopt the canonical stored Event and projections
  rather than the regenerated request envelope. Focused Ruff, Core/Storage strict
  Mypy, microservice file-size over `907` tracked and new files, `467 passed, 64
  skipped` backend regressions and Eval `10/10` pass. The final host PostgreSQL
  17.5 matrix passes `80/80`, including stale authority, rollback, semantic
  derivation and canonical lost-response retry paths. Formal review of the
  integrated implementation and its sole `Done` dependency closed the card as
  `Done`; it unlocks only `CLOUD-AGG-TASK-PG-01`. `CLOUD-CONTROL-PLANE-PG-01`,
  not this card, owns the cloud Worker composition root and runtime backend
  selection.
- Completed and formally closed Task/Segment adapter task:
  `CLOUD-AGG-TASK-PG-01` adds PostgreSQL v5,
  a namespace-scoped Task read model, deterministic explicit rebuild and a
  connection-scoped rollover primitive. Reads never write; rebuild and rollover
  share a Task advisory lock, Handoff Event pairs are validated by common identity,
  and composite foreign keys prevent cross-Task ownership. Ruff, strict Mypy over
  `166` files, the `911`-file microservice size gate, `473 passed, 77 skipped`
  related regressions and Eval `10/10` pass. The real PostgreSQL 17.5 matrix passes
  `32/32`; formal review of the integrated implementation and its `Done` authority
  dependency closed the card as `Done` and unlocks only
  `CLOUD-MODEL-TOOL-PG-01` for the next serialized migration. Context and Handoff
  continue planning in separate sidebar tasks without writing the migration hotspot.
- Completed and formally closed Model/Tool projection task:
  `CLOUD-MODEL-TOOL-PG-01` adds replayable PostgreSQL v6 Event-derived
  projections. Its focused Worker tests pass `7/7` and its isolated PostgreSQL
  migration/projection matrix passes `7/7`; the card is `Done` after dependency
  and path review. `CLOUD-AGG-CTX-PG-01` is now also formally closed as `Done`
  after its recorded isolated PostgreSQL `14/14` and SQLite/Worker `11/11`
  evidence; Context administrative recovery remains a separate Review card and
  neither selects the cloud runtime.
- Completed and formally closed Artifact contract task: `CLOUD-ART-OBJ-CON-01` freezes provider-neutral Artifact
  object/metadata authority before any SDK or adapter. ADR-017 separates stable
  `artifact://` identity from temporary access URLs and opaque external references,
  freezes staged/finalize/compensate recovery plus fenced Worker and management
  authority, and leaves provider, key encoding, API delivery and runtime selection
  unchosen. It unlocks planning for `CLOUD-ART-PAYLOAD-PG-01`; Artifact lifecycle,
  object and payload adapters remain separately gated. `CLOUD-AGG-HANDOFF-CON-01`
  is now formally closed as `Done`: it adds a tokenized Lease-fenced SQLite
  dispatch receipt before the PostgreSQL Handoff aggregate, with `290` recorded
  related tests and a current-HEAD focused `22/22` regression check. SQLite work
  stops at this compatibility contract. `CLOUD-AGG-HANDOFF-PG-01` remains the
  next v8 migration Review gate, while Artifact payload implementation remains
  locked.
- Completed and formally closed Context follow-up: `CLOUD-AGG-CTX-ADMIN-PG-01` reuses the v7
  administrative CAS only for historical capsule recovery in an explicitly injected
  PostgreSQL store. API recovery consumes the canonical Event/Session/Workspace result
  without a second projection write; the transaction rejects missing or changed
  projections and updates the active pointer with recovery Event time. Its isolated
  PostgreSQL 17.5 matrix passes `19/19`. It does not add PostgreSQL manual compact,
  Desktop behavior or runtime backend selection. Formal dependency/path review
  closed the card as `Done`; the dedicated PostgreSQL recovery adapter and matrix
  test are now explicitly recorded in its Owned paths.
- Completed and formally closed Handoff v8 aggregate slice preserves the exact v1-v7 migration names and
  checksums while splitting migration types, execution and the v8 catalog into focused
  files. The real PostgreSQL 17.5 migration matrix passes `6/6`; v8 adds only
  namespace-scoped operation, database-guarded immutable envelope and fenced dispatch
  tables, reusing
  the v5 Task/Segment index instead of creating a second lineage authority. A canonical
  request digest binds reserve, fresh commit and lost-response replay; the atomic
  transaction covers parent/child Events, projections, Task rollover, Envelope,
  dispatch and operation state. Child Workspace state remains fully Event-rebuildable.
  Dispatch uses database-time expiry, `FOR UPDATE SKIP LOCKED`, rotated tokens and exact
  full-fence ACK; Worker recovery now threads the acquired fence and cloud drift writes
  use the existing fenced projection transaction. The isolated PostgreSQL aggregate
  matrix passes `20/20`; Core/Storage/API/Worker pass `822/822` with `102` skips.
  Formal dependency/path review closed `CLOUD-AGG-HANDOFF-PG-01` as `Done`; no
  runtime, provider, Desktop or application Compose selection was made.
- Artifact v9 preflight confirmed that the local `ArtifactPayloadStorePort` lacks
  namespace/fence/staged lifecycle semantics. The v9 card requires the reviewed
  fenced cloud lifecycle Port and reserve -> object verification -> Event ->
  finalize/compensate ordering; its object boundary is direct botocore with MinIO
  bucket versioning and exact object-version evidence. It explicitly excludes SQLite,
  Desktop, runtime selection, Effect linkage and API read composition.
- Completed and formally closed Artifact v9 review slice starts from integrated Handoff v8 at
  `cfe40713`. `CLOUD-ART-PAYLOAD-PG-01` owns the PostgreSQL lifecycle metadata,
  provider-neutral object orchestration, Worker Event binding and isolated
  PostgreSQL/MinIO fault matrix; it does not select a runtime backend or add Desktop.
  The v9 migration foundation now adds one authoritative lifecycle metadata table,
  non-authoritative mutation/audit ledgers, exact Event/stream/fence bindings and
  reconcile/retention indexes. Core supplies one canonical reservation digest, while
  `(namespace, artifact_id)` remains the logical object locator and only the S3 adapter
  derives its private key. The PostgreSQL adapter now implements the complete fenced
  Worker lifecycle, canonical Event JSON binding, DB-owned transition timestamps,
  safe compensation, audited management recovery and Session-scoped reconcile reads.
  Isolated PostgreSQL 17.5 migration/lifecycle tests pass `19/19`. Worker orchestration
  now uses a default-off injection seam with strict reserve -> versioned put/head ->
  receipt -> Event -> finalize ordering. Managed URI spoofing fails closed, external
  references remain opaque, and uncertain outcomes remain staged for management
  reconcile. The real
  PostgreSQL+MinIO matrix passes `30/30`, including lost put/Event acknowledgements,
  sequence drift, finalize failure and concurrent retention prune. Worker/Runtime
  pass `260/260` with `16` environment-gated skips; Storage passes `131/131` with
  `114` environment-gated skips. Formal dependency/path review closed
  `CLOUD-ART-PAYLOAD-PG-01` as `Done`; Effect linkage, read composition and
  Runtime/provider selection remain separate gates.
- Completed and formally closed Effect/Artifact review slice `CLOUD-EFFECT-PAYLOAD-ATOMIC-01` starts from
  `zebra-cloud-trench@b87760b6`. Its dependencies are integrated; it owns the narrow
  transaction that binds the verified Effect request Artifact to the intent Event and
  Effect outbox row. Stable request identity, finalized-only cross-Worker reads and
  terminal result Artifact binding are implemented without migration v10. Real
  PostgreSQL+MinIO tests pass `53/53`; Tools/Worker/Runtime pass `418/418` and Storage
  passes `131/131`. Formal dependency/path review closed it as `Done`; it excludes
  SQLite, Desktop, runtime selection and delivery APIs.
- Completed and formally closed Artifact read-composition review slice `CLOUD-ART-READ-COMP-01` starts from
  `zebra-cloud-trench@4480ca66` after both PostgreSQL Model/Tool v6 and Artifact
  payload v9 dependencies were integrated. It adds one-snapshot namespace-scoped
  reads over those existing facts and injects a separate required payload-read
  capability through the current API store boundary. Canonical URI, exact Event
  binding, finalized lifecycle, recorded object version and verified bytes are all
  required; cloud composition disables legacy prune. The real PostgreSQL+MinIO matrix
  passes `39/39`, full tests pass `1943` with `145` gated skips, and no Artifact table
  or migration, SQLite feature, Desktop path or runtime backend selector was added.
  Formal dependency/path review closed it as `Done`; delivery APIs and complete
  Control Plane remain separate gates.
- Completed governed-memory planning slice `CLOUD-MEMORY-PG-PLAN-01` starts from
  `zebra-cloud-trench@f9568e34`. Audit confirmed the cloud branch still has only a
  SQLite `MemoryStorePort`; Mem0 is correctly derived but its future delivery ledger
  would otherwise depend on a local fact source. This docs-only card is formally
  `Done` and freezes the
  PostgreSQL Memory authority and atomic review boundary before migration or delivery
  implementation. The reviewed plan assigns v10 to governed facts/operation receipts,
  then v11 to Mem0 delivery; final review found no open P0/P1. Session History remains
  Locked on trusted Host scope.
- Completed governed-memory Core slice `CLOUD-MEMORY-CON-01` is formally `Done` and starts from integrated
  plan `2c43af0f`. It adds provider-neutral revision/CAS, content-free operation
  receipts and tombstones, plus pure candidate/promotion/review planning while
  preserving local wrapper behavior. Worker/Admin requests bind Session CAS and
  canonical payloads without coupling retry identity to LeaseFence or regenerated
  IDs/timestamps. Core tests pass `320/320`, API/Worker pass `411` with `14` gated
  skips, strict Core Mypy and changed-path Ruff pass, and release Eval is `10/10`.
  Full tests are `1971 passed, 145 skipped` with the sole inherited 561/500 Desktop
  file-size violation reproduced on the untouched cloud mainline.
  PostgreSQL v10, Mem0 v11, runtime selection, SQLite feature work and Desktop remain
  outside this task.
- Completed PostgreSQL governed-memory slice `CLOUD-MEMORY-PG-01` is formally `Done` and starts from integrated
  Core contract `4bda7f72`. It adds v10 authority/receipt storage, exact namespace reads,
  restart-safe content-free scans, Worker/Admin aggregate transactions and repeatable
  read-only SQLite import tooling. The isolated PostgreSQL 17.5 matrix passes `29/29`;
  full tests pass `1977` with `162` gated skips and only the inherited Desktop size
  failure. Runtime wiring was deliberately removed after review exposed terminal-event,
  active-set and mixed-store recovery gaps; it remains gated on one coherent cloud
  composition. Mem0 delivery, Desktop/SQLite feature work and production cutover remain
  excluded.
- Completed and formally closed Artifact contract slice: `CLOUD-ART-LIFECYCLE-CON-01` separates the
  provider-neutral cloud lifecycle Port/domain from the unchanged local
  `ArtifactPayloadStorePort`. It can proceed in Core without touching Handoff v8,
  PostgreSQL, MinIO, SQLite, Worker composition or Desktop, and becomes the explicit
  contract dependency for Artifact v9. The Core contract now freezes exact
  Event/object evidence, Worker versus management authority, safe cleanup evidence
  and staged/finalized/compensated/pruning/pruned shapes without changing local
  behavior. Its provider-neutral contract gate is `Done`; object, payload, Effect,
  read-composition and Runtime cards remain separate.
- Completed and formally closed object adapter slice: `CLOUD-ART-OBJECT-S3-01` implements the immutable
  S3-compatible bytes boundary and MinIO versioning against the reviewed Core Port.
  Conditional put, canonical retry, digest/size verification, exact-version read and
  delete, namespace-private keys and typed provider failures pass an isolated real
  MinIO cross-client matrix (`15/15`). All storage tests pass `130` with `87` gated
  skips and strict storage Mypy passes `49` files. PostgreSQL metadata, lifecycle
  orchestration, runtime selection, signed delivery, SQLite and Desktop remain
  untouched. Its object boundary is `Done`; PostgreSQL metadata, lifecycle
  orchestration, Effect linkage, reads and Runtime remain separate gates.
- Business-baseline recovery is active before cloud-stack integration. Exact replay
  on `zebra-cloud-trench@375dca92` reproduces all `9/9` remaining failures. Four
  path-bounded microservice cards own provider expectations, SCM credential
  fixtures, Worker cancellation convergence and Core Event contract
  extraction. All four microservice repair cards are locally integrated after the
  provider, SCM, cancellation, Core file-size, backend and Eval gates pass. Desktop
  is explicitly outside the new Zebra microservice mainline.
- Agent Definition architecture task `AGENT-DEF-ADR-01` is Done: ADR-016 records
  accepted Definition control-plane decisions and updates the final architecture.
  It separates Task-level Definition configuration from Attempt-level execution
  authority and preserves ADR-012's opaque external namespace. `AGENT-DEF-CON-01`
  is now Done: its frozen provider-neutral Definition/Version/Release models,
  deterministic digest/reference validation and Registry Port are merged, with
  `355/355` focused Core tests and changed static checks passing. The follow-up
  `AGENT-AUTH-SNAPSHOT-01` is now Done on
  `zebra-cloud-trench@50ad8d1c`: it owns only the schema, resolver Port, durable
  pre-Attempt event and narrowly injected Worker seam, with recoverable
  latest-snapshot revalidation. Focused authority `6/6`, Core `355/355` and
  Worker `93 passed, 13 skipped` are green; the full suite's single failure is
  the two inherited file-size violations outside this task. No implementation
  task is currently active; the cloud mainline is waiting for maintainer
  activation of a registered successor. Local SQLite Registry work is
  intentionally deferred on this cloud microservice mainline, while storage,
  API and runtime wiring remain locked.
  The implementation order is
  `CON -> AUTH`, then `{DRAFT,AUTH} -> BIND -> MEM -> TRUST -> EVAL -> PUB`;
  PostgreSQL Registry remains a separately gated adapter.
- Web Intelligence planning: `WEB-INT-PLAN-01` is a documentation-only review
  slice defining a provider-neutral native `web.*` surface over a replaceable
  wigolo Provider, Zebra-owned orchestration/security, and durable Watch. Its
  implementation cards remain Locked; no wigolo runtime or new native Tool is
  delivered.
- Locked architecture tasks: Web Intelligence implementation, ACP entry and
  optional code intelligence
- Open product issue: none; `#148` closed with PR `#156`
- Review task: `WEB-UX-01` makes explicit `local + trusted-local` execution
  non-interactive across Desktop/API/CLI/Worker, including existing Tasks, while
  retaining fail-closed non-local defaults and hard Gateway/Runtime boundaries.
- Active extension task: `EXT-0` registers the Skill/MCP/Plugin extension
  control-plane contract (`ADR-014`, merged via PR `#180`); the **EXT-1 Skill v2
  epic is complete** — `EXT-SKILL-01..05` are `Done` (metadata v2,
  scope/namespace/digest, task-level skill-component snapshot +
  handoff/authority/recovery/API threading, the bounded admin surface with
  SQLite enable/disable state, and `skills.read` provenance + release-eval
  cases). **`EXT-MCP-01` is `Done`** — bounded protocol-version negotiation
  (`SUPPORTED_PROTOCOL_VERSIONS` with server-version validation) and a
  Streamable HTTP transport (`mcp_http.py`) with bearer-token-via-env,
  module-level SSRF guard, https enforcement, and stdio/http routing in the
  harness. **`EXT-MCP-02` is `Done`** — `McpSessionPool` with
  healthy/degraded/quarantined health classification, bounded backoff, and
  acquire/release/health/close wrapping `McpProxyTransport` (shared by stdio +
  http); `SessionState` dataclass exposed from `mcp_protocol`. **`EXT-MCP-06`
  is `Done`** — elicitation mapped onto the durable Clarification flow:
  `ClarificationContext`/`ClarificationRequestedPayload` gain optional
  `response_schema` + `elicitation_source` (existing flow byte-identical),
  `McpElicitationBridge` converts `elicitation/create` → ClarificationContext,
  and `ZEBRA_MCP_ELICITATION` gates it (default on). **This completes the EXT
  Phase A scope** (EXT-0 + SKILL-01..05 + MCP-01/02/06).
  Plugin/Hook/Marketplace remain `Locked` pending private-cloud GA. Elicitation
  is reconciled to durable HITL; sampling stays a hard non-goal.
- Completed documentation task: `EXT-PLAN-01` records the Skill, MCP, and Plugin
  extension upgrade architecture, authority boundaries, phased task map, and
  acceptance gates. It changes no product capability and does not activate the
  deferred marketplace or remote MCP work.
- Active harness task: `HAR-TOOL-RECOVERY-01` enforces the durable contract
  that a single `ToolCallStatus.FAILED` (HTTP 4xx, missing file, timeout) must
  surface as a structured observation for model-selected correction rather than
  directly producing `session_failed`. Changes: repeated tool calls become
  observations with a threshold-gated `loop_guard_exhausted` hard stop (default
  3), sequential batches continue executing remaining tools after a mid-batch
  failure (matching concurrent-batch semantics), and a provider protocol
  firewall (`protocol_invariants.py`) validates tool-call/tool-result pairing
  before every model request to prevent `invalid_request` leakage.
- Model-response acceptance is now a separate provider-neutral boundary:
  malformed body/SSE/tool-call output becomes `ModelResponseRejectedError`,
  tool-capable stream deltas are committed only after validation, one bounded
  repair is allowed within the model-call budget, and exhaustion produces a
  recoverable `SESSION_SUSPENDED` rather than `session_failed`. Provider
  transport retries and semantic repairs have separate trace counters. The
  implementation and regression cases are present in the working tree; runtime
  validation has not been executed in this session.

## Current Capability

### Durable execution

- Event Store and projections are the durable source of truth.
- Harness and Worker execution is bounded, stoppable, resumable, and recoverable.
- SQLite leases, idempotency, tool/effect ledgers, snapshots, artifacts, and
  delivery audit cover the local execution lifecycle.
- Existing Session handoff safety contracts now back internal Segment rollover
  while the legacy ordinary-user mutation remains disabled by default.
- Stable Task persistence aggregates root and child Segments behind one identity,
  one monotonic event cursor, and active-Segment message/control routing.
- Completed-Task follow-up and cancelled/failed-Task recovery create internal Segments
  automatically; unsafe lifecycle boundaries pause or fail closed.
- Immediate terminal follow-ups inherit the previous user/Assistant checkpoint;
  internal rollover no longer drops the subject needed by short replies.

### Runtime and security

- Runtime classes are `trusted-local`, `os-sandbox`, `oci-rootless`, and `gvisor`.
- Production mode requires gVisor and a digest-pinned image and fails closed on
  missing runtime capability or authority drift.
- Hard runtime modes use a read-only root, non-root identity, dropped
  capabilities, no-new-privileges, default no-network, resource limits, and
  session-labelled cleanup.
- Policy, HITL, network profiles, MCP/Web gates, credential boundaries, and
  audit remain independent of model output.
- Explicit `local + trusted-local` mode uses effective `full-trusted-local`
  authority across Desktop/API/CLI/Worker, so new and existing Tasks execute model
  tools without per-call approval. One Agent Security resolver is the authority
  source for every execution entry point. System HTTPS proxies are honored for
  local Web execution; direct connections retain public-address DNS preflight.
  Core and non-local deployments remain default-deny and approval-gated.

### Context and model integration

- Every provider request crosses a model-aware context-window hard gate.
- Large tool outputs retain complete Artifact payloads while the model receives
  bounded, checksummed projections.
- Transparent Context Capsules support compaction, inspection, recovery, and
  deterministic provider-continuation fallback.
- DeepSeek stable Flash/Pro profiles, streaming/cache/TTFT/error telemetry, and
  default-off Beta capabilities are implemented without exposing private reasoning.
- Malformed provider JSON and Tool Call arguments are rejected before execution;
  one bounded model repair is attempted, then execution suspends recoverably.
- Explicit in-process DeepSeek thinking tool loops preserve and replay private
  `reasoning_content`; default executor profiles remain non-thinking, and missing
  continuation state fails before HTTP.
- `DS-RESP-01` adds an explicit Flash/Pro DeepSeek Responses wire adapter with
  semantic SSE terminal validation, required-tool support, stateless reasoning
  replay, provider-side tool rejection, and legacy Chat Completions compatibility.
  Responses remains opt-in; plaintext private reasoning does not become durable
  Session state, and vision/web-search/custom-tool combinations fail closed.
  Focused contracts pass `55/55`; a credentialed semantic-SSE smoke passed both
  the Flash thinking tool round trip and Pro high-thinking reviewer route. Full
  validation passes `2610` tests with `326` explicit skips, the 1425-file size
  gate, Ruff, strict Mypy across 707 source files, and the `10/10` release eval.

### Product surfaces

- Zebra owns Agent execution state and can run as an independent microservice;
  Desktop and CLI are optional operator surfaces over the same Runtime.
- Authelia/external identity owns authentication. Calling business systems own
  users, organizations, membership, business authorization, subscriptions, and billing.
- Zebra accepts signed Agent authority, opaque namespace, and technical limits;
  internal Policy may only preserve or narrow that authority.
- API, CLI, Worker, and Desktop read and mutate the same durable state.
- Desktop consumes replay-plus-tail SSE, renders truthful partial output, and
  supports approval, clarification, task plans, context, and artifacts without
  exposing internal child-Session or handoff controls.
- Real Chromium exercises the live Desktop/API/Worker/SQLite/SSE chain for long
  streams, reload recovery, cancellation, and invisible cross-Segment follow-up.
- Desktop composes Lobe UI `ThemeProvider` with Ant Design X and Zebra's durable
  event projection; Lobe UI does not replace session or chat state.
- The compact Ant Design X composer is merged; it does not change conversation
  or task-launch contracts.
- Typed local tools cover bounded file, command, patch, tests, Git, Web, Skill,
  MCP, and read-only Research paths according to the task profile.
- Failed tools return structured observations for model-selected correction or
  fallback, including bounded failure reason and detail when output is empty,
  while Policy, approval, protocol, effect, and budget stops remain hard.
- API and Harness model/tool call limits are optional and default to unlimited;
  an explicit caller ceiling remains strict. A batch that cannot fit starts no
  tools and suspends recoverably instead of becoming a generic Task failure.

### Platform Console (apps/platform-web)

- The management console frontend exists at `apps/platform-web`, built on the
  `next-shadcn-dashboard-starter` template (Next.js 16 App Router, React 19,
  Tailwind 4, base-ui shadcn) with the template's Clerk auth removed — the
  console intentionally ships without a user system for this phase and the
  operator identity is a local placeholder.
- The full PRD v1.1 information architecture is implemented: 8 top-level
  navigation modules and 52 routes — the PRD §7.3 recommended route list is
  fully covered, plus Notification and Platform Health which appear in the
  §7.2 nav tree (overview, integrations with the
  7-step onboarding wizard and three-pane Manifest editor, Agent assets with
  Effective Policy Simulator, runtime center with the 12-tab Task detail and a
  dependency-free SVG Orchestration DAG, frontend capability center with the
  profile-driven Hook code generator, quality/release gates, governance and
  audit with real CSV export, and system settings).
- Data access is centralized behind `src/lib/platform/repository.ts`; it reads
  a local mock dataset shaped on the Trench/Jazz pilot so the console runs
  standalone before the Management API exists. Swapping the repository for an
  OpenAPI-generated client is the single integration point.
- PRD safety rules are enforced in the UI layer: digests and IDs render as
  copyable monospace with full-value tooltips, high-risk operations require a
  reason-bearing confirm dialog, published revisions render immutable, and no
  page displays plaintext credentials or raw Fence tokens (references and
  hash digests only).

## Latest Validation Baseline

Validated on `codex/platform-web-bootstrap-01` on 2026-08-26 (Platform
Console, `apps/platform-web`):

- `pnpm typecheck` (`tsc --noEmit`): 0 errors across 299 source files
- `pnpm lint` (oxlint): 0 errors, 92 accepted warnings (73 are the standard
  TanStack Table inline-cell pattern; the rest are template-legacy)
- `pnpm build`: production build compiled successfully, 48 routes generated
- production server route smoke: `54/54` console routes returned 200 with
  SSR content markers verified (overview KPIs/charts, Task detail timeline
  and binding digests, the 6-node Orchestration DAG, wizard step gating and
  transition, the three-pane Manifest editor, Hook code generation with real
  profile contract names)
- code review pass closed on hydration safety, dead links, PRD secret/fence
  display rules, and immutability affordances

Validated on `codex/ctx-seg-02-followup-recovery` on 2026-07-20:

- focused API/Core/Worker regression: `74 passed`
- `make test`: `1519 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `419` source files,
  and all `8/8` release Eval cases passed
- all `22` deterministic Desktop checks and the production Vite build passed;
  Tauri validation was intentionally omitted per explicit scope waiver

Validated on `codex/web-ux-01-trusted-local-auto-web` on 2026-07-19:

- final focused authority, failure-observation, proxy, API, Worker and runtime:
  `101 passed`
- `make test`: `1515 passed, 7 skipped`
- `make check`: file-size `899`, Ruff, strict Mypy over `418` source files, and
  `8/8` release Eval cases passed
- every deterministic Desktop `check:*` script and production build passed
- real Chromium: `8/8`, covering the trusted-local launch default, automatic
  command execution, streaming, reload, cancellation, Segment and failure paths
- the original old Task completed a real OpenAI `web.fetch` via the configured
  macOS HTTPS proxy without approval or `private_network_blocked`
- real Zhipu Task `91fbddb3-d608-4e7c-a15b-694d6e55c9ae` recorded Policy
  `allow`, recovered from the site's expired TLS certificate, and gave the model
  the exact failure detail instead of a false allowlist explanation

Validated on `codex/subagent-delegation-model-native` on 2026-07-19:

- focused delegation and recovery regression: `39 passed`
- `make test`: `1509 passed, 5 skipped`
- `make check`: file-size `898`, Ruff, strict Mypy over `417` source files, and
  `8/8` release Eval cases passed
- isolated real-model API check answered `1+1` directly with `2`; trace and
  durable events contained no tool or Subagent activity

Validated on `codex/ctx-seg-01-task-runtime` on 2026-07-19:

- `make test`: `1501 passed, 7 skipped`
- `make check`: file-size, Ruff, strict Mypy over `417` source files, and `8/8`
  release Eval cases passed
- Desktop: every deterministic `check:*` script and production build passed
- real Chromium: `7/7` long-stream, reload, stop, invisible Segment follow-up,
  approval, and failure regressions passed
- terminal control state and approval identity now project through the stable Task
  boundary even while an internal Segment execution request is settling
- inherited workspace revision is fail-closed before the first Segment attempt;
  later approval continuations use current runtime authority instead of replaying
  the immutable creation-time revision check

Previous packaged mainline baseline:

Validated on `ARCH-RT-A4-E2E-01`, merged as `origin/main@d586a8f` / PR `#165`
on 2026-07-18:

- `make test`: `1484 passed, 7 skipped`
- file-size gate: `889` files, zero violations
- Ruff: passed
- strict Mypy: `412` source files, zero errors
- release Eval: `8/8`, `pass_rate=1.00`
- Desktop: deterministic checks, production build, and `7/7` real Chromium
  Runtime/streaming regressions passed
- Quality run `29645045918`: all seven jobs passed, including the packaged Ubuntu
  `.deb` WebDriver chain, real Linux gVisor, Workspace exhaustion, and real OS
  sandbox smoke on Ubuntu and macOS
- packaged evidence records `passed=true`, `runtime_class=os-sandbox`,
  `fallback_allowed=false`, cancellation, approval with real tool execution,
  failure visibility, and restart-durable-recovery; final screenshot shows the
  recovered failed session and Runtime Inspector value
- current main JavaScript chunk: about `1.47 MB` (`458 KB` gzip), Vite warning remains

The seven skips are opt-in real-provider/platform smokes. Linux CI runs the real
gVisor and native sandbox jobs instead of treating local skips as proof.

`UI-LOBE-01` validation additionally passes all Desktop checks, TypeScript,
Vite production build, and a real browser smoke without console warnings.

`UI-COMPOSER-01` additionally passes all `21` Desktop checks, TypeScript/Vite
build, and real Chromium desktop/mobile visual checks. The thread composer is
`117px` high instead of `183px`; the new-task and `390px` mobile variants are
`145px` and `113px`, with no horizontal overflow or browser console warnings.

The DeepSeek credentials-enabled focused run also passed all `39` contracts,
including a real thinking tool round trip.

## Governance State

- The Phase 0-8 implementation baseline is complete and historical.
- `docs/AGENT_TASKS.md` is the only executable task registry.
- All eight stale `Review` cards verified as merged are closed as `Done` by
  `QA-GOV-02` / PR `#144`.
- `QA-148-MDL-01`, `QA-DESKTOP-E2E-01`, and all Phase A Runtime tasks
  `ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01` are `Done`.
- `QA-HANDOFF-CLK-01`, `QA-PKG-E2E-02`, `QA-PKG-E2E-03`, and `UI-LOBE-01`
  are `Done` via PRs `#170`, `#171`, `#172`, and `#168`.
- `UI-COMPOSER-01` is `Done` via PR `#174`.
- `ARCH-129-ACP-01` and `ARCH-129-CTX-01` remain `Locked` until explicitly activated.
- `EMB-PLAN-01`, `EMB-AGUI-SPIKE-01`, `CLOUD-STO-SEAM-01`, and
  `CLOUD-STO-AUTH-01` are formally Done for their architecture, protocol and
  local Store-composition slices. Production AG-UI, Trench and cloud backend
  selection remain separately gated.
  `MEM-MEM0-ADP-01` is formally Done as a disabled-safe integration contract;
  it is not runtime-selected. `MEM-MEM0-SPIKE-01` is formally Done for its
  pinned OSS contract evidence; the provider-neutral
  Memory Gateway contract, Core delivery-certainty contract, PostgreSQL-native
  admission Spike, PostgreSQL-native storage gateway, and PostgreSQL v11
  delivery ledger are formally Done with isolated evidence; none selects a
  Runtime backend. Mem0 remains a derived, degraded-safe index;
  PostgreSQL Event/Projection and epoch/Lease Adapters have real-service
  restore and concurrency evidence.
  The local CI-billing waiver does not satisfy merge, runtime composition, release
  or production gates. The reviewed Effect and Artifact foundations are not runtime-
  selected; full aggregate fencing, Redis, production AG-UI, Trench, analysis,
  writeback, Memory delivery/runtime wiring and GA remain `Locked` pending explicit
  gates. `MEM-GW-DEL-PLAN-01` is formally `Done` on
  `codex/mem-gw-del-plan-closeout-01`; it keeps `MEM-GW-DEL-01` locked and
  registers the Core certainty, scoped reset Spike, PostgreSQL v11 ledger and
  runtime/rebuild child cards. `MEM-GW-DEL-CON-01` is formally `Done` after its explicitly activated,
  provider-neutral Core implementation slice. `MEM-MEM0-RESET-SPIKE-01` is now
  `Blocked` on `codex/mem0-reset-spike-01`: its isolated Compose run proved the
  pinned Mem0 list endpoint has no documented bounded pagination, so exact scoped
  enumeration cannot be accepted. `top_k` is not pagination. `MEM-GW-DEL-PG-01`
  is formally `Done` on `codex/mem-gw-del-pg-01` for the metadata-only v11
  ledger, atomic v10 enqueue and PostgreSQL claim/revalidation slice. Its host
  Compose runner passes `24` real PostgreSQL tests covering fresh/v1-v10 upgrade,
  checksum, migration rollback, replay, atomic enqueue, stale ACK, namespace
  isolation, unknown and in-flight quarantine, and batch search admission. The
  parent ledger and runtime wiring remain locked by the scoped-reset gate.

`MEM-MEM0-RESET-ALT-01` is formally `Done` as a zero-production-code validation
of whether v11 `scope/generation` plus confirmed provider mappings can replace
provider-wide enumeration for logical reset. Its isolated runner passes `2`
tests with verdict `B/PARTIAL`: logical reset and known mapping deletion are
bounded, but unknown provider orphans remain unrecoverable from the ledger. The
existing reset Spike remains `Blocked`; the partial verdict does not unlock the
runtime consumer. The focused delivery runner remains `24 passed`, and the full
storage matrix remains `295 passed, 1 skipped`.

`MEM-PROVIDER-DEL-COMPLIANCE-01` is now `Done` on
`codex/mem-provider-del-compliance-01`. This docs/specification-only slice adds
ADR-018 and a test-only admission matrix for deterministic recovery, physical
deletion and complete scoped coverage. The current Mem0 verdict is logical
fencing `PASS`, ledger mapping deletion `PASS`, ambiguous-create recovery
`FAIL/UNPROVEN`, complete scoped deletion `FAIL/UNPROVEN`, and Runtime admission
`BLOCKED`. Mem0 is therefore `Provider admission: DENIED` and
`Mainline candidate: DEFERRED`; `MEM-GW-DEL-RUN-01`, the parent ledger and
Runtime composition remain `Locked`. No production code, Provider HTTP, Worker,
Desktop or SQLite composition is changed.
The focused contract suite passes `2`; changed-path Ruff, format, Mypy,
compilation and `git diff --check` pass. `make check` remains blocked by two
unrelated file-size violations: Desktop stylesheet `561/500` and PostgreSQL
storage test `765/700`.

`MEM-PG-NATIVE-ADMISSION-SPIKE-01` is formally `Done`. Its isolated PostgreSQL
17.5 profile proves the ADR-018-compatible native boundary with `8 passed` and
emits `ZEBRA_PG_NATIVE_ADMISSION_VERDICT=PASS`; the full storage matrix passed
`303 passed, 1 skipped` (`295` predecessor cases plus `8` admission cases).
The result admitted the candidate architecture, after which
`MEM-GW-PG-NATIVE-01` was explicitly activated for storage-only work. Worker,
Provider HTTP, Desktop, SQLite, Redis and Runtime remain `Locked`.

`MEM-GW-PG-NATIVE-01` is formally `Done`. Production PostgreSQL migration v12
and the provider-neutral `PostgresNativeMemoryGateway` are covered by `10`
focused Compose cases; the full `tests/agent_storage` matrix passes `313 passed,
1 skipped`, and the existing delivery runner remains `24 passed`. The card does
not select a Runtime backend or add Provider HTTP, Worker, Desktop, SQLite or
Redis composition.

## Known Follow-Ups

1. Keep the completed Embedded architecture and AG-UI/Trench Spikes parked while
   the storage branches follow their recorded merge order.
2. Keep DeepSeek thinking mode opt-in and preserve its private continuation
   fail-closed boundary.
3. Preserve merge order from `CLOUD-STO-SEAM-01` through `CLOUD-STO-AUTH-01`,
   `CLOUD-PG-PLAN-01` (now `Done`), `CLOUD-PG-01`, and the Lease contract/Adapter chain; do not
   select PostgreSQL until every authoritative Store can move as one profile.
4. Split or lazy-load the Desktop main bundle based on a repeatable bundle report.
5. For private cloud, plan PostgreSQL, object storage, multi-Worker coordination,
   Credential/Egress Broker, external-namespace isolation, and Kubernetes in
   dependency order.
6. Review the dependency Compose baseline and Mem0 contract/Adapter chain. Preserve
   its duplicate, expired-search, timeout and error-classification findings; do not
   claim real-provider compatibility or make Mem0 authoritative.
7. Preserve the PostgreSQL/Lease order: `CLOUD-PG-PLAN-01 -> CLOUD-PG-01 ->
   CLOUD-LEASE-PLAN-01 -> CLOUD-LEASE-CON-01 -> CLOUD-LEASE-PG-01`; only then may
   fenced Effect Outbox and Worker consumer cards be activated.
8. Activate Object Storage, Redis live state, recovery and Memory delivery/runtime
   wiring one path-bounded card at a time; no production claim precedes complete
   composition, migration, restore and failover evidence.
9. Continue the memory lane one path-bounded child at a time. The Core and
   PostgreSQL delivery children, provider-neutral gateway, PostgreSQL-native
   admission and storage slices are Done. The scoped reset child is `Blocked`
   on bounded enumeration; keep the Mem0 consumer, parent ledger and Runtime
   locked until their own explicit gates are reviewed.
10. Keep `WEB-INT-PLAN-01` in review until its document evidence is accepted;
    do not activate Web Intelligence contracts, Provider, security, tools,
    orchestration or Watch cards out of dependency order.
11. The former DeepSeek vision dual-channel plan registered as `DS-VIS-PLAN-01`
    is retained only as a historical record and is superseded by
    `TRN-DEEPSEEK-V41-MM-01`; do not claim or implement the old `DS-VIS-*` chain.
    The replacement keeps Artifact/session authority and bounded image validation,
    but sends the authorized image directly in the current USER message to the
    official `deepseek-flash` model. Files API, remote image fetching and derived
    OCR/vision evidence remain separate future work rather than prerequisites.

## Runtime Blueprint

`ARCH-RT-BP-01` is complete on `codex/arch-runtime-deployment-blueprint` and
records the shared Runtime contract and the separate single-host and cloud
deployment profiles. It does not activate implementation or change the status
of locked architecture cards.

The maintainer activated single-host Phase A on 2026-07-18. Work is split into
`ARCH-RT-A1-OS-01` through `ARCH-RT-A4-E2E-01`; all four tasks are merged and
every Phase A exit criterion is evidenced. Phase B and Phase C remain deferred
pending explicit activation; Phase B additionally requires database migration
and recovery-model review.

A1 now implements macOS Seatbelt and Linux bubblewrap `os-sandbox` with
capability probes, sanitized process environments, network denial, whole-process
boundaries, immutable authority, snapshots, and fail-closed platform selection.
A1 merged through PR `#160` after Ubuntu bubblewrap, macOS Seatbelt, gVisor,
Backend, and Desktop CI passed. A2 now owns Setup/Agent isolation.

A2 now implements exact external HTTPS GET egress, SHA-256 cache reuse, temporary
Credential revocation before Sandbox startup, no-network Setup execution,
lockfile verification, SPDX Setup Artifact, verified Snapshot handoff, and a new
no-network Agent handle. It reuses existing Artifact/Snapshot storage and adds no
durable state model. A2 merged through PR `#163` after all five Quality jobs
passed. A3 now enforces a dedicated capacity-limited Workspace mount in
production, kills timed-out process groups, normalizes runtime failures, and adds
real `ENOSPC`, 20-cycle native soak, long-stream, and gVisor machine-readable CI
evidence. Local validation passed `1483` tests plus all static/release gates; PR
`#164` merged after all six Quality jobs passed. A4 then delivered the final
packaged Tauri/Desktop Runtime E2E exit gate through PR `#165` / merge commit
`d586a8f`. Quality run `29645045918` passed all seven jobs. The Ubuntu `.deb`
artifact was driven through the real API, Worker, and `os-sandbox`; its retained
JSON and screenshot evidence cover no-fallback identity, cancellation, approval,
real tool execution, failure visibility, API restart, and durable recovery.

## Explicitly Deferred

- Zebra AG-UI production adapter and HostSessionGrant verifier
- Trench CopilotKit Runtime/BFF, read-only panel, frontend tools and writeback
- Memory delivery runtime wiring: `MEM-GW-DEL-01` remains `Locked`; its Core
  certainty and PostgreSQL ledger children are Done, while scoped reset/rebuild
  is Blocked and the Mem0 consumer remains gated.
- ACP entry adapter
- optional code-intelligence adapter
- Kubernetes/Kata/Firecracker and distributed Sandbox scheduling
- complete PostgreSQL runtime composition and object-storage adapters
- external authority adapter and namespace-isolated cloud control plane
- centralized Vault/KMS-backed credentials and production Egress
- ecosystem marketplace, cross-organization A2A, and autonomous production release

## Permanently External Business Responsibilities

- user registration, login credentials, MFA and identity lifecycle
- organization, membership, invitation, join/leave and account-disable workflows
- business RBAC, subscriptions, plans, billing, invoices and commercial quota

Authelia is the selected authentication provider. Zebra verifies external Agent
authority and enforces technical execution limits, but does not duplicate these
business domains. The durable decision is `ADR-012`.

## Document Responsibilities

| Document | Responsibility |
|---|---|
| `README.md` | stable product entry, setup, capability summary, boundaries |
| `PROGRESS.md` | concise current mainline snapshot and next decisions |
| `docs/AGENT_TASKS.md` | executable task status, owner, branch, paths, acceptance |
| `task_plan.md` | current task checklist only |
| `WORKLOG.md` | session-level execution history and handoff evidence |
| final architecture | target architecture and invariants |
| `docs/Zebra Embedded 生产级目标架构.md` | Embedded/Trench target and invariant boundaries |
| `docs/Zebra Embedded与Trench实施任务拆解_v1.0.md` | dependency, ownership and phase gates for Embedded delivery |
| Phase 0-8 implementation document | historical dependency and acceptance baseline |

## Required Reading

1. `README.md`
2. `PROGRESS.md`
3. `docs/AGENT_TASKS.md`
4. `AGENTS.md`

## 2026-09-05 RabbitMQ Stage 5 capacity acceptance

`RABBIT-ROLLOUT-CAPACITY-01` is in Review and accepts Stage 5 group 1. Trench
now serializes per-user cross-conversation admission in PostgreSQL. Zebra
enforces global unpublished-Outbox and per-scope execution/control ceilings,
including recovery, backfill and old-writer migration paths, while reserving
control capacity. Fair pickup retains forward progress and probes a frozen ring
of active scope heads so continuous tail traffic cannot starve a newly active
scope. Actual PostgreSQL/API regression passed 146/146, the final migration
negative proof passed 2/2, and independent SPEC/QUALITY reviews passed. Stage 5
is **1/8 = 12.5%**; rollout/shadow, production activation and later hardening
groups remain open.

Before architecture changes, also read the source-of-truth documents in the
precedence order defined by `AGENTS.md`.

## 2026-09-07 Cloud extension Turn admission

`EXT-ADMIT-01A` is in Review after independent spec and quality re-reviews
passed. A separate default-off cloud flag now admits only
message commands carrying a genuine exact-scope Host Grant with `agent.run`.
The server selects a bounded set of currently enabled Skills, derives the same
Turn identity used by execution, and atomically persists the accepted command,
RabbitMQ wakeup/Outbox records, trusted digest binding and immutable v54
snapshot. Selection is limited by the authoritative root Task's immutable Host
binding and frozen `skill_components`: issuer, namespace, workspace and exactly
one principal must remain identical, while absent or empty Skill ceilings select
nothing. Client binding aliases are rejected; idempotent retries retain their
first binding, a second pending message is rejected before Turn selection, and
clarification continuations reuse the original Turn snapshot and digest even if
live configuration changed. Configuration and stream races leave no orphan
records. Local, disabled and non-message behavior is unchanged. This slice does
not activate Worker extension loading or MCP network execution.

Worker activation has an explicit follow-up blocker in
`apps/worker/src/zebra_agent_worker/task_recovery.py`: recovery still compares
browser origin with the frozen JWT issuer. This admission slice does not modify
Worker production code, and does not claim end-to-end extension execution.

Final issuer/origin remediation evidence: 184 focused deterministic checks and
140 related actual-PostgreSQL checks passed, including a production-shaped Task
creation and message admission with distinct JWT issuer/browser origin plus
forged issuer rejection. Final full regression is 3884 passed / 812 skipped;
`make check` passed file-size, Ruff, strict Mypy over 875 sources and Eval 10/10.
The quality-review follow-up now checks exact Task authority before duplicate or
revision disclosure, preserves duplicate replay without live configuration
selection, enforces one enabled installation per exact scope and Skill under
concurrent writes while retaining disabled history, and revalidates up to 32
selected installations with one parameterized PostgreSQL lock query. Evidence:
62 service-free focused checks, 249 related real-PostgreSQL checks, full suite
3892 passed / 814 skipped, and `make check` passed. Independent quality
re-review passed with no remaining actionable defect. Final P2 remediation makes
the advisory key an opaque digest of complete deployment/scope coordinates plus
Skill identity and detects legacy duplicate Skill IDs before applying the
unique-Skill count limit. Validation: 36 service-free focused checks, 67 real
PostgreSQL focused checks with controlled lock-timeout tenant isolation, full
suite 3893 passed / 815 skipped, and `make check` passed.
# 2026-08-28: Trench Native History Host Grant V2

- Trench Host Grant broker 现在会以 `include_removed=true` 回查用户来源投影，同时校验
  active `trench.source` 与恒定大小的 `trench.history` 账本资源；他人账本在 mint 前
  fail closed，具体 period 的用户/工作区归属继续由 Trench 权威账本校验。
- 默认允许 scope 增加 `source.read` 与 `history.read`，`trench.history`
  必须携带 `history.read`。通用 Host manifest/resource-binding/Worker 路径保持不含
  Trench 词汇，业务可见性仍由 Trench 执行。
- Trench real-service acceptance 的精确 manifest 期望升级为 `trench-native-v2`，保留
  原五项事件工具并加入六项来源/历史工具；acceptance compose policy 同步版本化。
# 2026-09-03 Multi-user isolation closeout

`CLOUD-TRN-MULTITENANT-01` is in Review on `codex/fix-agui-live-tail` with the
Trench companion branch `codex/trn-perf-01`. The slice is limited to the
audited Trench authentication/internal-route/workspace boundaries and Zebra
principal-scoped admission/AG-UI/legacy-session boundaries. Existing dirty
live-tail and model-projection work remains outside this slice and must be
preserved.

The closeout now scopes admission idempotency to Host/namespace/workspace/
principal authority, applies tenant and principal fences to AG-UI and Task
transports, hides unbound legacy Sessions from Host tenants, and terminates
streams at Grant expiry. Zebra `make check` passes. The Trench companion now
uses HttpOnly browser sessions, rejects implicit development identities,
derives source workspace ownership from the authenticated viewer, hides the
legacy/internal API composition by default, and isolates browser event-task
caches by user/workspace. Trench `make check` and live HTTP negative probes
pass.

The final code review removed the remaining Host-specific product vocabulary
from generic Zebra Worker/API paths: embedded runs now receive a generic
Host-product identity boundary while Trench retains its exact product role in
the Host task context. PostgreSQL Task bindings enforce principal ownership;
SQLite remains explicitly tenant-only because it has no durable binding table.
The suspend/resume acceptance helper now binds a temporary workspace instead of
snapshotting the repository and `.venv`. Final Zebra validation passes
`make check` and `make test` (`2849 passed, 369 skipped`).

# 2026-09-05 RabbitMQ Stage 5 scoped rollout acceptance

`RABBIT-ROLLOUT-SHADOW-01` is in Review and accepts Stage 5 group 2. Zebra and
Trench now default unlisted scopes to database fallback, use one audited rollout
authority, and recheck execution/control lane authority inside the fenced
handoff transaction. The physically separate shadow lane is bounded and
side-effect free; advisory try-lock contention skips evidence without delaying
formal admission. Formal and shadow consumers require distinct percent-decoded
Rabbit principals and mutually exclusive queue ACLs. Existing credential files
remain usable and gain shadow identities through an atomic, non-rotating
`prepare-shadow` upgrade.

Exact reconciliation starts from eligible formal Outbox rows and requires full
formal/shadow IDs, scope and digest equality; controlled corruption tests prove
drifted mirror/observation rows are not counted. Final evidence is Zebra focused
63/63 and actual PostgreSQL 30/30, Trench focused 32/32 and actual PostgreSQL
1/1, isolated RabbitMQ ACL acceptance, both full `make check` gates, and
independent SPEC/QUALITY pass. Stage 5 is **2/8 = 25%**. Production activation,
commit, merge and push remain separate and were not performed.

## 2026-09-07 Cloud Worker extension snapshot recovery

`EXT-WORKER-01A` is implemented and is now in Review after independent
review. A separate default-off cloud Worker flag composes the existing exact
PostgreSQL extension snapshot/Task authority only for cloud PostgreSQL workers;
disabled, local and projected legacy Turns perform no extension reads. An
enabled unbound nonlegacy Turn performs one exact boolean existence probe so a
persisted snapshot cannot be hidden by deleting accepted binding coordinates.
The accepted command's server-selected Turn and digest now survive message
materialization. Before Attempt authority persistence or any model/tool call,
the Worker resolves the active human Turn from durable events, requires the
extension authority's root Task binding to exactly equal the independently
loaded execution binding, derives scope from the frozen verified issuer rather
than browser origin, and revalidates deployment/scope/session/Turn/digest and
the frozen Skill ceiling. Missing, tampered, ambiguous and cross-tenant state
fails closed; restart and retry reload the same immutable binding.

Validation: 32 focused deterministic checks; 59 related actual-PostgreSQL
checks passed with 1 environment-gated skip; full suite 3903 passed / 816
skipped; `make check` passed file size, Ruff, strict Mypy over 876 sources and
Eval 10/10. This slice does not register Skill tools, load package bytes, call
MCP, add credentials/UI, activate deployment flags, commit or deploy.

Spec review then found the migrated RabbitMQ Worker bypassed the legacy message
consumer: `handoff_command` materialized `command-input:{accepted.event_id}`
with trusted causation but did not preserve the accepted extension Turn, while
recovery only recognized the legacy idempotency convention. The shared canonical
materializer now parses `SessionCommandAcceptedPayload` and supplies its bound
Turn for normal messages; clarification continues the already-open Turn.
Recovery prefers `causation_id == accepted.event_id`, validates canonical key,
actor, type, content and clarification identity, and retains legacy correlation
only for compatibility. Every bound association is validated, including
completed historical Turns, before only the current Turn participates.

Remediation evidence: dedicated deterministic and real-PostgreSQL handoff tests
passed 13, including normal/restart, missing and tampered correlation,
clarification and two consecutive bound Turns; the wider RabbitMQ handoff,
admission and recovery matrix passed 68; full suite passed 3904 / 821 skipped;
`make check`, diff and file-size gates passed. Independent re-review remains.

Quality review then found the API still treated Rabbit's canonical causation as
pending, and the materializer/recovery did not share a durable command-integrity
proof. Core now reconstructs an accepted `SessionCommand` and verifies its
fingerprint plus session/idempotency continuity at Rabbit materialization and
bound-message Worker recovery. API admission recognizes the exact Rabbit
causation/key and strict causation-free legacy key, so a completed first Turn
admits the second. Recovery validates all bound history even with no active Turn,
merges/de-duplicates canonical and legacy candidates by Event ID, and rejects
distinct dual, missing or tampered materializations before any extension read.
Unbound legacy streams remain unchanged. Deterministic/Core/API/Worker checks
passed 50; dedicated actual PostgreSQL admission/handoff checks passed 16; the
full suite passed 3913 / 824 skipped; and `make check` passed size, Ruff, strict
Mypy over 876 sources and Eval 10/10. Status remains In Progress for independent
re-review.

Final quality review centralized the exact association predicate: canonical
means matching causation and canonical key; legacy means no causation and the
strict legacy key. Accepted payloads are typed before binding semantics are
inspected, partial/non-MESSAGE bindings fail, and API/Worker correlation is
indexed in one pass. Deterministic operation-count tests exercise 100/120-command
histories. PostgreSQL exposes only an exact-coordinate boolean `exists` probe,
never an untrusted digest. API indexes retain candidate lists, validate accepted
Event-ID uniqueness, merge strict associations and require exactly one result,
so duplicate canonical/legacy/history identities cannot be overwritten. Focused
checks passed 59, dedicated actual PostgreSQL checks passed 51, the clean final
full suite passed 3922 / 826
skipped, and `make check` passed size, Ruff, strict Mypy over 876 sources and
Eval 10/10. The task remains In Progress pending independent re-review.

## 2026-09-07 Cloud Worker typed Skill tools

`EXT-WORKER-01B` is implemented and in Review after independent final quality
review passed with no remaining P0-P2 finding. A separate default-off flag
composes the same PostgreSQL deployment,
extension store and private object reader into cloud Workers only. The Worker
uses only `PreparedWorkerContext.extension`; local, disabled and legacy paths
do not construct a cloud catalog or read Skill publication/object state.

The existing typed `skills.list` and `skills.read` tools accept a narrow
injected catalog. Every call revalidates each frozen installation and pinned
publication against the complete trusted scope. Disable, revision/version
drift, missing or cross-tenant state fails closed. Listing reads metadata only;
reading one file uses the ready publication receipt's exact object version and
verifies object size/SHA, ZIP manifest/content digest,
name/description/version and bounded canonical UTF-8 content in memory, without
host extraction or script execution. Restart/retry reconstructs the same
catalog from the immutable recovered snapshot.

Validation: focused deterministic and PostgreSQL/MinIO/Rabbit Worker matrix
`86 passed, 35 dependency skips`; the broker-only production composition published and
consumed the command before the real model/tool gateway executed `skills.read`.
Strict Mypy passed 878 sources; format, lint, diff and source-size gates passed,
with `execution.py` at 499 lines. Full suite passed `3945 passed, 830 skipped`.
Deployment activation, MCP,
credentials, UI, commit and merge remain separate.

Quality follow-up replaced per-installation live reads with one bounded
PostgreSQL authorization query over all frozen installations and ready
publications. `skills.read` repeats that same batch after object/ZIP validation,
so concurrent disable/upgrade discards the provisional body. Synchronous Worker
calls now use `asyncio.run` directly unless already embedded in an event loop;
gateway construction performs no catalog authorization/object I/O. Unknown
cloud adapter exceptions are logged with the original traceback and translated
to a fixed chained catalog failure, keeping parallel and durable/client results
free of backend secrets.

## 2026-09-14 Trench composer model usage projection

- `MODEL_RESPONSE_RECEIVED` now emits a `zebra.model_usage` AG-UI custom event
  containing only input/limit/cache/model/reasoning fields.
- Private prompt hashes, provider payloads and reasoning content remain outside
  the host stream.
- Focused projection tests passed `9/9`; Ruff and strict Mypy passed.
- Zebra Task reads now also project a durable, task-level public usage summary.
  This lets an authorized host recover metrics for runs completed before the
  AG-UI custom event was deployed without exposing provider or prompt internals.
- Trench hydrates that summary only when an opened conversation has no local
  usage, caps the upstream wait at 1.5 seconds, then persists it on the latest
  Turn so later refreshes stay local. A real historical conversation displays
  `9.3k / 55.8万` and `57.7%` cache hits after refresh.

## 2026-09-14 Trench composer model and reasoning controls

- Trench now exposes a plus attachment control, switchable Flash/Pro executor
  profile, and DeepSeek-native `none|low|high|max` reasoning choices with wider
  control spacing.
- Model profile and reasoning effort now survive Trench durable Turn dispatch,
  Zebra admission/event persistence, Rabbit/Worker recovery, and reach the
  Harness model gateway. Explicit profiles no longer get overwritten by the
  legacy executor-model compatibility setting.
- Image input remains intentionally hidden until the existing `DS-VIS-*` chain
  supplies authoritative image Artifacts, egress checks and durable audit.
- Focused validation: Zebra `51 passed` plus Ruff/Mypy; Trench API `45 passed`,
  frontend `70 passed`, ESLint and live browser control switching.

## 2026-09-15 - CLOUD-USER-SCHEDULE-MATERIALIZER-01

- Added an independent `zebra-agent-scheduler` cloud/PostgreSQL composition root
  with bounded polling, batch, claim TTL, attempts and graceful shutdown.
- Each Firing freezes the exact Schedule version and Task template. Retries use
  one stable key and the existing in-process `ZebraAgentApi.create_session`
  facade, retaining atomic Task admission and Outbox/RabbitMQ Worker wakeup.
- Scheduler authority uses an HMAC workload exchange for a fresh asymmetric
  Host Grant, then verifies issuer/audience/JWKS/origin, identity and resources
  and removes management scopes before Task admission. No bearer token, Cookie
  or workload secret is persisted in a Schedule, Firing or Task.
- Validation: focused Schedule/Scheduler/Broker exchange `28 passed`; Core `767
  passed`; Storage `361 passed, 799 skipped`; Broker/Scheduler group `43 passed`;
  actual PostgreSQL Schedule tests `7 passed`; size, Ruff, strict Mypy over 938
  sources and Eval 10/10 passed; full repository regression passed `4426` with
  `885` dependency skips.
- Boundary: management API, frontend, deployment activation, RabbitMQ fault
  injection and Trench browser acceptance remain later phases.

## 2026-09-16 - Cloud/Trench quality review remediation

The remaining review defects in the selected Skill and Trench pipeline paths
were corrected without changing authority boundaries. Cloud Skill metadata now
contains the server-published ID and the typed reader resolves either ID or
name. Host HTTP diagnostics preserve a bounded business message while
redacting credentials and internal paths. Trench Raw Inbox recovery is now
lock-claimed with a publish-time backoff, worker heartbeats distinguish last
success from last failure, and pipeline health reports durable/replay
capabilities from the actual database probe. Zebra's full suite (`4450 passed,
887 skipped`) and `make check` are green; Trench's focused reliability and
cleaning gates are green. Deployment and browser acceptance remain separate
gates.

## 2026-09-17 - Cloud/Trench quality review follow-up

The compatibility fallback for legacy Trench source databases is now complete:
subscription lookup handles a missing user-subscription table and returns to
the owner-scoped source path. Route-registration coverage was made compatible
with the current FastAPI/Starlette nested-router implementation without
weakening path or precedence checks, and RSSHub serialization now matches the
canonical `rsshub://` source kind. Native history source listing also probes
subscription readiness before loading ORM rows, avoiding an expired-object
failure during the legacy fallback. Native history search and event lookup
also probe the events table, covering the case where the period ledger is
migrated before event storage. The Trench Python gate is green at `127
passed`; native-history/extension/route regression coverage is `20 passed`,
the product timeline now also degrades safely when the events table is absent,
evidence and historical trace now degrade when projection tables are absent,
and the combined timeline/read/native/extension/route compatibility set is
`37 passed`;
focused reliability/review coverage is `47 passed`, cleaning is `73 passed`,
ToC tests are `79 passed`, and the frontend/ToC builds, lint, migration SQL
generation, and diff checks are green. No deployment or browser acceptance is
claimed.

## 2026-09-20 - CLOUD-REMEDIATION-R11 scheduler and durable child closure

- Reused the existing Schedule/Scheduler path and revalidated duplicate firing,
  expired claim recovery, DST gap/fold, misfire, overlap, terminal cancellation
  and authority revocation behavior; no second scheduling engine or schema was
  introduced.
- Durable research children now freeze their configured model/tool call limits
  and retain the narrowed child binding. The child bootstrap and one
  deterministic HARNESS-authored RUN command commit in the same delegation
  transaction; admission establishes the Task index and binding before command
  wakeup projection, while Session/Workspace projections deliberately remain at
  bootstrap revision until the Worker consumes the command.
- Orchestration budget receipts are idempotent on identical recovery replay,
  reject conflicting duplicate receipts and cannot exceed either their child
  reservation or aggregate ceiling. Parent continuation rebuild preserves the
  pre-suspension model/tool counters.
- Evidence: focused Scheduler/subagent/Worker suite `62 passed, 1 skipped`;
  real PostgreSQL/MinIO admission, delegation, concurrency and Scheduler suite
  `52 passed`; default cloud API -> parent -> child -> wakeup -> parent chain
  passed with one child RUN and frozen `3/2` limits; full repository `4478
  passed, 887 skipped`. File-size, touched Ruff, strict Mypy over 949 sources,
  Eval 10/10 and diff gates passed. Full `make check` remains stopped only by
  the R00 import-order baseline in untouched `apps/api/.../host_auth.py`.

## 2026-09-20 - CLOUD-REMEDIATION-R08 Memory lifecycle delivery closure

- Preserved PostgreSQL governed Memory as lifecycle authority and reused the
  existing metadata-only v11 delivery ledger; no parallel outbox or fact source
  was introduced.
- Claims for the same Memory are now revision-serialized, preventing an older
  publish and newer delete from crossing the provider boundary concurrently.
  Other Memory identities remain independently claimable.
- Added a provider-neutral Worker consumer that revalidates the current governed
  revision, digest, lifecycle and expiry immediately before mutation. Tombstones
  and newer confirmed revisions suppress stale operations without provider I/O;
  disabled providers leave work pending, while timeouts/unknown outcomes enter
  the existing uncertain state and quarantine the scope.
- Evidence: focused Core/Worker/Gateway `45 passed`; real PostgreSQL governed
  Memory, delivery, import, scan and native regression `94 passed`; touched
  Ruff, strict Mypy over 950 sources, Eval 10/10, file-size and diff gates passed;
  full repository `4483 passed, 888 skipped`. Full `make check` retains only the
  R00 import-order baseline. Runtime composition remains default-off. Mem0 is
  still denied/deferred by ADR-018 and is not enabled.

## 2026-09-20 - CLOUD-REMEDIATION-R09 Redis Agent Memory guarded rollout

- Added the supported Redis Agent Memory REST adapter without adding its SDK as
  a runtime dependency. Stable Zebra Memory IDs and hashed owner IDs support
  exact reconciliation while keeping raw tenant, repository and user scope out
  of the provider.
- PostgreSQL remains the lifecycle and content authority. R08 delivery intents
  now compose into bounded background delivery; uncertain remote outcomes
  quarantine the scope. Shadow search cannot affect Context, while active search
  can only reorder PostgreSQL-authorized candidates after durable mapping,
  revision, digest and lifecycle revalidation.
- Startup remains `disabled/off` by default. Shadow or active rollout requires
  HTTPS service coordinates, an indirect API-key environment name and explicit
  data-export authorization. The old Mem0 path remains denied by ADR-018.
- Evidence: focused `36 passed, 5 skipped`; real PostgreSQL `22 passed`; cloud
  profile regression `23 passed, 2 skipped`; full repository `4502 passed, 891
  skipped`; touched Ruff, Mypy over 956 sources, Eval 10/10, file-size and diff
  gates passed. Full `make check` retains only the R00 import-order baseline.
  The real Redis service gate is `NOT_ENABLED`, so no production rollout or
  external data export is claimed.
2026-09-20 CLOUD-EFFECT-EPOCH-REGRESSION-01: the R14 local gVisor rehearsal
found three stale assumptions in the effect-default E2E rig rather than in the
production runtime: migrations now own idempotent epoch bootstrap, Cloud
`execute=true` queues the durable run while `false` creates a draft, and an
approval already submits its durable resume. The verifier is now read-only,
initial approval and recovery resume have separate helpers, and the rig can use
an explicitly pre-mounted control-plane volume when Colima cannot discover a
host submount created after VM startup. Focused contracts pass `7 passed`; the
real PostgreSQL/MinIO/Colima/runsc matrix passes all ten scenarios including
side-effect binding/idempotency, governed completion, Worker-death recovery,
lease-loss reconciliation and Workspace Control Plane execution. Production
startup, epoch rotation, local SQLite and runtime semantics are unchanged.
Repository validation completed with `4537 passed, 891 skipped` and one
transient live DeepSeek smoke failure (missing optional provider reasoning on a
successful tool call); the isolated retry passed. `make check` is fully green:
file-size gate, Ruff, strict Mypy over 958 sources and Eval 10/10.

## 2026-09-20 - Durable Trench terminal and cross-repository gate closure

- AG-UI now converts only non-recoverable Session suspension into one bounded
  terminal `RUN_ERROR`. Child waits and recoverable budget/verification
  interrupts remain resumable, and a Turn that already emitted its terminal
  event suppresses a trailing duplicate.
- Rebased the Trench acceptance runner on the current server-owned Durable Turn
  API and manifest. Revision-conflict recovery now rebuilds the command from
  the authoritative revision, Task state follows the active segment, and the
  protected operator sidecar can restart the Worker on the local Docker socket.
- The local real cross-repository matrix passed all nine scenarios: read,
  long-run streaming, disconnect replay, Worker restart, stop/resume, grant
  replay, host-tool failure and zero Trench subscription-table writes. A real
  logged-in browser turn also reached a terminal answer and survived reload;
  model selection and reasoning strength were unchanged.
- Scope boundary: this is local acceptance only. The physical deployment host
  was unreachable and no production rollout is claimed.

## 2026-09-20 - TRN-SUBAGENT-UX-02 real parent/child closure

- Durable research delegation now reaches a terminal child result, wakes the
  suspended parent and replays bounded child evidence into a fresh provider
  request without persisting private reasoning or orphan provider tool IDs.
  Invalid plan transitions are recoverable tool failures, and AG-UI keeps one
  public parent run across internal child wakeups.
- The local Trench browser Turn used parent Task
  `b13cb090-31ea-417b-be9c-877d1026c4f7`; children
  `5c04c3ea-1e3e-412b-9961-816acbeb493e` and
  `3ff7388a-2cf2-4542-b55c-86b297c3d009` both completed before the parent emitted
  its terminal answer. Reload restored the same tool/child timeline and final
  Markdown answer.
- Focused Zebra regression is `69 passed`; changed Python files pass Ruff and
  Mypy. Trench API regression is `53 passed`; the complete frontend suite is `89
  passed` with ESLint and diff checks clean. DeepSeek Flash and `high` reasoning
  remained unchanged.
- Acceptance used OrbStack's available `runc` through an explicitly local
  trusted-runtime override because the physical host was unavailable and this
  Docker engine does not provide `runsc`. Production's fail-closed gVisor
  default was not changed, and no deployment is claimed.
# 2026-09-20 — Host-selectable Cloud Agent capability modes

- Recorded the reusable Agent UI boundary and future npm extraction path in
  `docs/Agent_UI可复用包与宿主能力模式_v1.0.md`; Trench remains a Host adapter,
  not the product definition.
- Trench now exposes server-owned `research`, `general`, and `coding` modes.
  Browser clients cannot submit raw Tool, Policy, network, or budget profiles.
- Capability mode is durable across Turn admission, dispatcher restart, queued
  supplements, page reload, and Zebra command state. A mode change rotates the
  admission-frozen Task generation and hands bounded Host context to a successor.
- Model and reasoning-effort defaults are unchanged. Focused verification passed
  42 backend and 19 frontend tests; Trench `make check` passed 134 API/product,
  74 pipeline, and 90 ToC tests, both frontend production builds, lint, migrations,
  and diff validation. Browser inspection confirmed all three modes in the composer.

## 2026-09-21 - Durable interactive execution and idle reconnect recovery

- Interactive Tasks with no explicit caller budget now have an executable
  regression that completes 66 model calls and 65 distinct tool executions,
  beyond the retired Trench 24/64 ceilings.
- Harness suspension classification preserves unknown suspension as `suspended`
  instead of fabricating model-budget exhaustion. Explicit model/tool budget,
  verification and delivery-contract reasons remain unchanged.
- Trench catches an idle AG-UI stream at the reconnect boundary, exchanges a
  fresh Host Grant and resumes from the last durable cursor. The durable Turn no
  longer fails merely because one upstream stream was quiet for 60 seconds.
- Existing authorization renewal, Worker recovery and frontend replay paths were
  retained and revalidated. Model profile and reasoning effort are unchanged.
- Evidence: focused Zebra `20` and `60`; full Zebra `4580 passed, 892 skipped`;
  Zebra check passes file-size, Ruff, strict Mypy over 969 sources and Eval
  `30/30`. Trench focused `36` and `68`; frontend `91/91`; complete gate `137`
  product/API and `74` pipeline tests, builds, lint, migration and diff checks.
- Local browser acceptance on conversation `conv_1789911230325_53c036`
  completed Turn `da4e1425-b805-447c-8583-e5f1373a13ad` with the expected
  `37+58=95` answer. PostgreSQL records `completed`, a durable terminal cursor,
  `trench-native-v15:coding`, DeepSeek Flash and `high` reasoning.

## 2026-09-21 - DS-CACHE-01 DeepSeek prompt-cache continuity

- Removed the cloud-only 32K conversation ceiling. Context recovery now uses
  the selected model window, avoids compaction while under its trigger, and
  rejects no-op or growing compaction results.
- Removed the second lossy 24-message/65,536-character recovery truncation so
  the model-aware context compiler owns the physical budget. Completed tool
  pairs and exact recent history remain intact until compaction is required.
- Added privacy-safe request, message-count and cumulative message-prefix hashes
  to model telemetry and durable observability. Operators can locate the first
  changed message without logging prompt text or private provider reasoning.
- Child wakeup retains the maximal exact prefix. Where required DeepSeek private
  reasoning was intentionally not persisted, continuation is marked
  `private_reasoning_not_durable` and safely rebased; that recovery boundary is
  measured separately from cache-eligible warm loops.
- Validation: focused suites `114 passed`; final merged repository `4587 passed,
  892 skipped`, including all four real DeepSeek provider smoke cases; file-size,
  Ruff, strict Mypy over 969 sources, and eval `30/30` passed. Local cloud
  API/Worker images were rebuilt and both are healthy.
  Credentials-enabled DeepSeek tool-loop smoke passed `3/3`; one identical
  2,172-token request was cold at `0/2172` hit/miss and then stable at
  `1920/252` for two warm calls (88.4% measured warm hit rate). Model and
  reasoning-strength settings were not changed.

## 2026-09-21 - CLOUD-MEMORY-CLOSURE-01 PostgreSQL authority closure

- Replaced ephemeral Session workspace scoping with frozen Host workspace,
  principal and tenant coordinates while retaining Definition scope. Missing or
  ambiguous Host principal bindings now fail closed instead of widening recall.
- Added deterministic Chinese/English remember and forget directives, typed
  project/architecture/procedure memory, sensitive-text rejection and governed
  deletion. PostgreSQL remains authoritative; Redis Agent Memory remains off.
- Added bounded Chinese-capable recall ranking, durable selection and extraction
  checkpoints, recovery outcome counts, and additive Cloud runtime status on the
  existing session-memory API without changing local response contracts.
- Review follow-up corrected five defects hidden by the original closure claim:
  Host tool/doc candidates now use the same USER scope as Host recall; forget is
  exact rather than substring-destructive; validation events expire only
  auto-derived procedures; session metrics/reviews derive the frozen principal
  and source Session; and PostgreSQL ranks up to 500 authority-filtered candidates
  instead of truncating to the newest 80 before relevance ranking.
- Second-review closure freezes the complete Host workspace/principal/tenant/
  Definition scope for all session Memory APIs, rejects Host reads without one
  principal, verifies automatic expiry against the exact source tool event, and
  moves PostgreSQL feature relevance ahead of the row cutoff with a bounded
  stable-fact lane. A record behind 600 newer distractors is recalled.
- Focused regressions pass `49/49`. The real PostgreSQL
  governed/context group passes `38/38`, including a composed write-confirm in
  one Session and automatic scoped recall in a later Session, older relevant
  recall and cross-principal isolation. Full repository passes `4599 passed, 899
  skipped`; file-size, Ruff, Mypy over `975` sources and eval `30/30` pass.
  Isolated API/Worker Compose images rebuilt healthy and emitted
  `ZEBRA_APPLICATION_COMPOSE_TEST_RESULT=PASS`.
- Declared local implementation is `100%`. Merge, push, Trench production rollout
  and remote deployment are separate gates and are not claimed. Model and
  reasoning-effort settings are unchanged.

## 2026-09-21 - CLOUD-MEMORY-PROFILE-01 governed profile and outcome closure

- Confirmed PostgreSQL governed Memory now projects a source-visible user profile
  with preference, background and long-term goal sections. Natural Chinese and
  English self-statements create low-confidence EPISODIC candidates only; they
  never become profile facts without the existing review/confirmation boundary.
- Added principal-bound profile reads and exact user/tenant Memory deletion.
  Deletion reuses the governed administrative review transaction, advances the
  source Session Event stream and stores a content-free PostgreSQL tombstone.
- Recall keeps a bounded stable-preference lane of two entries, requires project
  rules to be query-relevant and gives each relevant Memory type one slot before
  score-based filling. PostgreSQL remains authoritative; Redis Agent Memory is
  still disabled.
- CHANGE, CREATE and OPERATE task contracts now require mutation, artifact or
  operation evidence as appropriate. Finalization suspends with
  `acceptance_outcomes_required` instead of committing a plausible but unproven
  answer. The deterministic release fixture now declares mutation semantics for
  mutation scenarios.
- Validation: focused Core/API/Worker coverage `873 passed`; principal/tenant API
  contract `21 passed`; real PostgreSQL governed Memory `25 passed`; file-size,
  Ruff, strict Mypy over `976` sources and Harness eval `30/30` pass. The full
  deterministic suite reached `4611 passed, 896 skipped`; its only failure was a
  credentials-enabled live DeepSeek smoke whose response supplied zero reasoning
  tokens, outside this change's deterministic boundary.
- Local code, API contracts and real PostgreSQL acceptance are complete. The
  generic platform-web remains a mock operator console and was not given a fake
  profile screen; Host product UI integration, live-model A/B, push and production
  deployment remain separate acceptance gates. Model and reasoning strength were
  not changed.

### 2026-09-21 - Host memory governance completion

- Trench now receives content-free `zebra.memory_context` metadata and shows a
  per-answer receipt only when confirmed Memory actually participated in context.
- Confirmed user Memory supports atomic PostgreSQL correction: the old revision
  becomes superseded, the replacement becomes confirmed, and candidate/review
  Events remain auditable. Delete remains a content-free tombstone and is absent
  from subsequent confirmed reads.
- The Host settings surface shows personal scope, source conversation metadata
  when a retained Task binding exists, deterministic confidence bands, and
  edit/delete controls without exposing Host Grants to the browser.
- Final validation: focused Zebra Memory/API/AG-UI `64 passed`; PostgreSQL
  correction/delete/cross-Session proof passed; complete repository `4613 passed,
  897 skipped`; `make check` passed file-size, Ruff, strict Mypy over `978`
  sources and eval `30/30`. Rebuilt local API/Worker are healthy, `/health` is
  `200`, and the logged-in Trench Memory page loads its real `0/0` account state.
  Redis Agent Memory remains disabled; model and reasoning settings are unchanged.

### 2026-09-21 - Final review and hardening

- Closed four review defects: Host Memory authority is fail-closed for missing
  principal/namespace keys; replacement transactions use scope-first lock order;
  Trench source enrichment is restricted to the bounded response's Session ids;
  and frontend/BFF mutation races and blank corrections are rejected.
- Final evidence: focused Zebra `26`, real PostgreSQL `6`, Trench API `19`, and
  Trench UI `11` pass. Full Zebra passes `4614 passed, 897 skipped`; Zebra
  `make check` passes over `978` typed sources and eval `30/30`. Trench
  `make check` passes `139 + 74 + 99` tests, production builds, migrations and
  diff checks. No commit, push or remote deployment is included.

### 2026-09-22 - AGENT-QUALITY-04 result-level acceptance

- Completion now enforces Host-overridable maximum response length and required
  answer terms, and informational questions no longer become mutation tasks by
  keyword accident. Change and operation outcomes require matching mutation
  evidence instead of accepting any successful write.
- Repository file evidence is typed at the tool boundary: reads and searches
  emit explicit file refs; directory paths are not citable. Objective quality
  revisions continue only while a deterministic deficit shrinks and preserve an
  exact evidence ref while shortening, avoiding both fixed global budgets and
  unbounded no-progress loops.
- Real DeepSeek read-only acceptance Session
  `3cf72f5e-0970-4c71-abd9-43ae30fb31e3` reached `answer_committed/complete` with
  a 150-character Chinese answer, exact file evidence, 12 model responses and 16
  successful tools. Focused tests pass `58/58`; `make check` and the complete
  `4633 passed, 897 skipped` suite pass.
- S4 local implementation is complete and in Review. Under the frozen 100-point
  delivery model, local plan implementation advances from `41%` to `61%`.
  Complete `12x3` live-eval execution, production release and remote deployment
  remain separate gates and are not claimed. Model/reasoning settings are unchanged.

### 2026-09-27 - CLIENT-TRENCH-LIVE-01 local pilot closure

- Closed the durable Client continuation chain across Host read, Research Child,
  browser effect scheduling, Receipt recovery and final-answer resume. Recovery
  now ignores superseded continuation markers after a later durable attempt
  boundary and handles the receipt-before-wait race without replaying effects.
- Hardened worker setup diagnostics, PostgreSQL projection synchronization,
  command classification, cancellation terminalization and Client profile
  readiness. Worker health now verifies model credentials and Docker runtime
  access instead of reporting healthy from process liveness alone.
- Real-model browser acceptance completed Turn
  `0aa25e03-1436-48eb-9672-238e91198bba`, conversation
  `conv_1790475335815_35ccbe`, run
  `85dc2ab3-a469-4db5-8291-533f7966b4e1`. The final browser effect opened
  `/dashboard/timeline?entityId=artificial-intelligence`, persisted a succeeded
  Receipt and resumed the same Turn to a committed answer.
- Final local gates pass: `make check` covers file size, Ruff, Mypy over `983`
  sources and eval `30/30`; `make test` passes `4689`, with `897`
  environment-gated skips. The composed Worker is healthy with a configured
  model credential and Docker daemon access.
- The local pilot implementation is complete and the card is in Review. Linux
  gVisor, one-digest production canary and rollback rehearsal remain external
  release evidence; no production deployment, commit or push is claimed.

### 2026-09-27 - Composer context composition observability

- The Context Window planner's real message, system-prompt and tool-definition
  estimates now propagate through durable response Events and bounded model-
  usage summaries into the shared React Composer. The popover shows total
  occupancy, category counts and percentages, and measured cache hit rate.
- Older conversations keep their total and cache summary and now explicitly say
  that composition was not recorded, instead of silently hiding the section.
  Skill and MCP rows are intentionally absent because the runtime does not yet
  account for them independently; no UI-only estimates were introduced.
- Focused Core/API projection tests pass `34/34`; SDK deterministic tests,
  package audit, React 18/19 Vite/Next consumers, Chromium/WebKit interactions
  and Next hydration pass. Trench Host integration remains a separate gate.
### 2026-09-27 - REACT-MEDIA-01 durable multimedia surface

- Added ordered, replayable `text/image/video/chart/file/app` parts while
  retaining legacy string messages. Published media remains in the Artifact
  Store; AG-UI carries only bounded metadata and opaque IDs.
- Added host-neutral image, video and file renderers, a constrained optional
  Vega-Lite package, and a fail-closed MCP Apps iframe boundary. The chart
  dependency is dynamically loaded and does not enter the base React bundle.
- Added authorized preview/download routes with safe inline MIME allowlists,
  metadata-only HEAD, single-byte Range, immutable ETag, CSP and private no-store
  behavior. Cloud Artifact reads now pin the verified object version and issue a
  native S3-compatible Range request; local SQLite keeps a compatibility slice.
- Closed the media review gaps: chart data/image/table Artifact fallbacks are
  active, transient chart errors recover, failed full-size images terminate
  visibly, image dialogs restore focus, and caption language is explicit.
- Trench consumes packed SDK artifacts through its same-origin BFF, durably
  persists content parts and renders image/chart output in a production
  Chromium acceptance run. No npm publication or production deployment is
  claimed.
- Final local evidence: SDK `verify` passes on Node 24/pnpm 10 with 42 unit
  tests, package audit, React 18/19 Vite/Next consumers and Chromium/WebKit;
  Zebra `make check` and `make test` pass (`4689 passed`, `901 skipped`).
  Trench `make check` passes `143` API/model, `74` pipeline and `123` ToC tests,
  lint with three pre-existing dashboard image warnings, both production
  builds, migrations and diff checks.

### 2026-09-28 - REACT-PRESENT-01 governed rich presentation intent

- Added the read-only `content.present` tool so the Harness can deliberately
  compose ordered image, video, Vega-Lite chart and file parts from existing
  current-Session Artifacts. The model chooses presentation intent; code owns
  Artifact authority, MIME allowlists, bounds and the final typed shape.
- The tool is registered only when an Artifact reader and current Session are
  available, and is enabled in General, Coding, Research and Research
  Coordinator profiles without changing model or reasoning settings.
- AG-UI now projects bounded V2 multi-part events in order while retaining the
  existing V1 `files.publish` MIME projection for historical replay. Arbitrary
  remote URLs, HTML, JavaScript and cross-Session Artifact references remain
  rejected.
- Local evidence passes: focused Python `77/77`; full repository `4711 passed,
  901 skipped`; file-size, Ruff, Mypy over `985` sources and eval `30/30`; and
  existing React media/chart package builds plus `10/10` focused renderer tests
  on Node 24. Provider generation/import, npm publication, Host packaging,
  merge and deployment are separate gates.

### 2026-09-28 - REACT-DOCUMENT-01 host-neutral Asset preview

- Added `AgentAssetPreview` to the reusable React package for bounded image,
  video, audio, PDF, Markdown, text, JSON, CSV/TSV and Vega-Lite previews.
  Markdown/LaTeX and chart engines remain explicit Host render slots; HTML
  preview is disabled unless the Host opts into a sandboxed frame.
- The paired Trench Host exposes the existing authorized preview route in its
  Asset index, renders reports and completed assistant answers through one
  Markdown/GFM/KaTeX surface, and opens generated files in a responsive preview
  sheet while retaining download fallback.
- Local evidence passes on Node 24: SDK build/type-check, serialized `45/45`
  tests, package audit, Trench Asset API `6/6`, frontend `159/159`, lint and
  production build. Zebra code is integrated on `cloud-agent-trench@989af16e`;
  npm publication, push, deployment and authenticated browser acceptance are
  separate gates.

### 2026-09-28 - user-managed flat Memory inventory

- Trench Memory settings now presents one chronological list instead of
  preference/background/goal/interest/portfolio sections. Review candidates
  remain visually separate because they are not yet effective Memory.
- Users can add explicit Memory from the settings surface. Trench resolves the
  current user's latest retained Zebra Task and forwards the request through the
  signed Host boundary; it does not persist a shadow copy.
- Zebra writes the item through a governed PostgreSQL transaction that
  atomically creates and confirms the record, appends candidate/review Events,
  advances Session projections, stores the operation receipt and enqueues the
  existing delivery path. Edit remains immutable replacement and delete remains
  a tombstone.
- The inventory read limit is aligned with the existing bounded profile maximum
  of 500 records. Redis remains optional and disabled; PostgreSQL remains the
  authority. No model or reasoning setting changed.

### 2026-09-28 - user personalization instructions

- Added one namespace- and user-scoped PostgreSQL standing-instructions record
  with revision CAS, plus signed Host GET/PUT/DELETE routes. Trench remains a
  client and stores no shadow configuration.
- Cloud Workers resolve the single Host principal at the start of every turn
  and inject the current value into the Harness system context. The wrapper
  explicitly keeps platform security, Host authority, project rules, current
  user requests and verified tool results at higher priority.
- The Trench AI settings surface now supports read, edit, save, clear,
  character bounds, conflict-safe revisions and honest read/write errors in
  the existing monochrome visual system. Local runs without a cloud store or
  Host principal remain unchanged. No model or reasoning setting changed.
- Local evidence: Zebra `make check` passed, its full suite reports `4723
  passed, 899 skipped`, and the real PostgreSQL migration/CAS slice reports
  `7 passed`. Trench `make check` passed with `145` API/model tests, `78`
  cleaning/pipeline tests, `147` ToC tests and both production builds. Browser
  acceptance, commit/push and deployment remain separate gates.

### 2026-10-01 - Cloud full-gateway profile (local merge)

- Added `full-gateway` as durable Task authority for simultaneous Web-gateway
  and MCP-proxy tools. It does not activate trusted-local approval bypass or
  direct sandbox networking; Host grants remain independent.
- Added PostgreSQL migration v60 and paired Trench Task-generation change.
  Existing Tasks retain their frozen profile. Search still requires a configured
  HTTPS endpoint. See `docs/CLOUD_FULL_GATEWAY_PROFILE.md`.
- Zebra `make check` and focused policy/runtime/schema tests pass locally;
  real Cloud search/MCP/Host acceptance, push, migration and deployment
  remain separate gates.

### 2026-09-30 - Trench historical media recovery (local)

- Existing chat images survived in PostgreSQL/Artifact Store but their old Task
  lived in `trench-prod` after the conversation rebound to a `zebra` Task.
  Trench now checks exact assistant artifact references for historical access;
  a restricted legacy namespace reader serves those files without broadening
  the current Task binding.
- Local browser verified four previously broken images decoded in the original
  conversation. Focused Trench tests: `49 passed`. Caddy config validated and
  rejects non-artifact/mutating legacy routes. Changes remain local and uncommitted;
  remote deployment and wider gates are separate.
### 2026-10-01 — CLOUD-USER-USAGE-01 (in progress)

Cloud Agent now exposes a bounded, signed-Host `GET /usage?days=7|30` read of
provider-reported token counts from committed Task events. It filters the
latest Task binding by Host app, namespace, workspace and opaque principal;
the Trench current-user API proxies through a fresh signed grant. The Zebra
React package includes a controlled Usage Analytics surface, consumed by the
new Trench account settings tab. No plan limits, prices, credit ledger, or
cross-Host identity mapping were added: unmetered model calls remain explicit
and billing reconciliation is still a separate task. Focused tests and Zebra
`make check` pass; the Trench frontend production build also passes. Deployment
and authenticated browser acceptance with real usage data remain open.

The 2026-10-01 Trench conversation incident exposed two local runtime drift
failures while this branch was under acceptance: Trench's new signed
`/capabilities/runtime` preflight had no Zebra API route, and the running
worker image lacked the already-tested media-evidence citation handling.
Zebra now returns its supported network-profile contract through the existing
Host-authorized API route. Both local API and worker images were rebuilt and
recreated healthy; a real Trench workload-signed grant received HTTP 200 and
`full-gateway` from the capability endpoint. The worker image now contains
the media-evidence citation handling. Focused Zebra harness/API tests and
Trench runtime tests passed. The original suspended Turn remains historical;
an authenticated browser retry of the conversation is still unverified.
### 2026-10-01 - Trench/Zebra conversation compatibility incident

- Confirmed old running Zebra API rejected Trench v20 `full-gateway` Tasks
  with HTTP 400 while PostgreSQL remained at v59. Applied v60 locally and
  replaced API/Worker from a matching isolated source snapshot; both now
  recognize `full-gateway`.
- Added an authenticated runtime-capabilities endpoint for Host preflight.
  Trench uses separate single-use Host Grants for capability GET and Task POST,
  identifies version mismatches explicitly and retains the existing conversation.
- Local browser acceptance: original conversation resumed and a newly created
  Task completed after correcting the Grant binding. This is local runtime
  evidence, not remote deployment or all Web/MCP capabilities acceptance.
- A later Turn in the same conversation stalled at `session_waiting_for_client_effect`:
  its accepted receipt and trusted resume command preceded the final waiting
  projection, so the fallback Worker scan skipped that command. The Worker now
  recognizes this narrow durable-event ordering; a regression test reproduces
  it. Replacing only the local Worker woke the old Turn, but its bound Host Grant
  had expired during the wait, so it failed closed. A fresh Turn in that same
  browser conversation completed with the expected answer. Durable command
  delivery cutover and remote deployment remain separate work.

2026-10-12: READ-BOUNDS3a3e5902 accepted locally after spec/quality GO and107 native/API checks, primary33passed14.59s;42unrelated file hashes preserved. WRITER Ready claimed before coding on codex/cloud-stream-writer-01; v2 remains dormant pending full client/reliability/performance acceptance. No push/deploy.

2026-10-14 stream proof follow-up: native header supplementation exposed a real v98 multi-projector scalar-subquery error. Claimed a minimal shared correlation fix with additive migration v100 and frozen historical statements/checksums. Current source/runtime validation and full acceptance remain pending; no deployment or push.

2026-10-14 stream verification boundary: current protocol admission performs necessary bounded canonical accepted-command body validation (intent fingerprint). Preserve it and account for its SQL; checkpoint/source metadata body-free checks are separate. The original whole-HTTP zero-Event-body test guarantee remains unachieved, not replaced by equivalent evidence. No production admission shortcut or new validation witness is claimed.

2026-10-14 STREAM PERF component convergence: frozen69 native batch59P/10F,
literal make check GO,93 review-file hashes unchanged. Current v10072 GO;
original172 has93 current/79 historical passes. Consolidated SPEC/QUALITY permit
component local acceptance→RELAY. Retain1 observer shape gap,8 output UNKNOWN,
1 preHTTP timeout UNKNOWN; completeHTTP/fulltest/fullPERF80/runtime/browser OPEN.
No further fixture/observer expansion in this batch; no push/deploy.

2026-10-14 PERF source component0f8c1716 locally integrated into cloud-agent-trench;
primary17dirtyfile hashes/modes preserved. CLAIM CLOUD-STREAM-RELAY-01 Ready→
InProgress, Luke/Codex, codex/cloud-stream-relay-01; exact owned paths and COV
write handoff in docs/CLOUD_STREAM_RELAY_PLAN.md. Tail100→reserved101; no source
edits before claim. Next implement committed frontier/retry and checkpoint ACK.
FullHTTP/fulltest/80/runtime/browser and retained10 PERF failures remain open.

2026-10-14 RELAY component SPEC/QUALITY GO; sole Unix factory P1 closed across
full-event and transient writer callers.57 earlier mixed-source passes plus11
targeted transport checks; clean exact-source literal make check GO. Runtime1273
4a5dba8e0a953d73703c2c11d643c0e30ea935dbf71abb62f234d3fb13501474.
Next ownedcommit/localFF then CAPACITY/GC; no push/deploy. Empty ledger452clientSQL/
56PGsockets/3352wholeWAL has no rate denominator; fullruntime80/TLS-handshake/
COV-MinIO/100Runs remain OPEN. All failures and oldPERF10 evidence retained.

2026-10-14 RELAY6bea341d locally fast-forwarded cloud-agent-trench;17dirtyfile
hashes/modes preserved. CLAIM CLOUD-STREAM-CAPACITY-01 Ready→InProgress,
Luke/Codex,codex/cloud-stream-capacity-01. Exact12 source/tests+serial handoff in
docs/CLOUD_STREAM_CAPACITY_PLAN.md before edits. Current tail101 unchanged;
implement bounded retained quotas/expiry/dirty recovery/GC, then CONTROL/STOP.
No push/deploy. Original PERF10/TLS/fullruntime80/fleet gates remain open.

2026-10-14 CAPACITY component SPEC/QUALITY GO. Frozen server policy and retained
Run/tenant/deployment quotas, bounded dirty recovery/GC, both Worker maintenance
entrances and oldV2 no-delta fallback are implemented. Original-key GC binding
is sealed atomically with charge; lost ledger remains failclosed pending explicit
owned inventory/drain. Final45unique passes=44 attempt06 +1 attempt07, clean
literal make check GO; prior batches keep distinct source/failure provenance.
Independent1330hash/proof-mode checks agree. Pending ownedcommit/localFF, then
CONTROL/STOP. Production cutover OFF;421clientSQL/66PGsockets whole lifecycle,
Redis instance-global CPU/memory samples are diagnostics, not SQL-rate/isolated
RSS certification. Actual SQL80/Worker/SDK/browser/fleet/TLS remain OPEN.

### 2026-10-14 - CLOUD-STREAM-DRAFT-SCOPE-01

Real Trench generation exposed omitted Task/Run identities in draft SSE serialization.
The API now preserves both validated identities on every chunk; Host scope rejection stays intact.
Signed-wire regressions: 9 passed; real producer-to-Host decoder accepts valid chunks and rejects wrong Task.
Local API is updated and healthy; deployed wire source hash matches verified fix.
Original Run 8126ca2b-c8d0-4a58-8904-3b2af3abc141 recovered through full v2 GET observation: Host completed, 4,179 answer characters, 92 events, answer exactly matches canonical fact, snapshot content readable.
Model calls remain 6; accepted Run commands remain 1. Trench protocol 7/7 passes. No push or model rerun.
Authenticated browser rendering remains user verification because automation has no logged-in session; this does not claim full performance/E2E acceptance.

### 2026-10-14 - CLOUD-OCI-IDENTITY-KEEPALIVE-01

Implement fresh Docker identity reads over persistent verified mTLS for the native explicit TCP engine. Existing CLI mutations/fences/instance ownership remain intact. 45 focused checks and targeted typing/Ruff pass; remote engine initialization+provision mean12.987s→8.882s (31.61%,3 alternating pairs, synthetic lifecycle). All six isolated containers removed. Local Worker updated; deployed source hashes and actual remote preflight verified. Whole-Run/browser/model TTFT remains unmeasured. No model calls or push. Details in docs/CLOUD_OCI_IDENTITY_KEEPALIVE.md.

### 2026-10-14 - CLOUD-OCI-CAPABILITY-KEEPALIVE-01

Remove the remaining native CLI capability query before instance reservation in favor of a fresh same-response daemon ID/version/runsc TLS check. 47 focused tests and targeted Ruff/mypy pass. Isolated storage primitives are measured separately; original3.4–5.7s is not a full live-stage attribution. Final3 paired probes: capability1.259s→0.272s (-78.39%), init+capability2.688s→2.015s (-25.04%). Unchanged initialization remains variable1–2s, mainly remote /info response wait. Local Worker source hashes/preflight/health verified; no model calls or push. Full historical interval/whole-Run TTFT attribution not claimed.

- 2026-10-14 LOCAL-GVISOR-INFO-CONNECT-01: daemon /info computation3–9ms;
  Worker direct container-to-VM retransmission path isolated. Explicit optional
  local Mac CONNECT transport retains end-to-end mTLS and fresh identity per
  operation. Three paired probes: cold1224.924→20.191ms (-98.35%),
  warm629.589→9.305ms (-98.52%);52 focused tests/Ruff passed. Platform packet-loss
  mechanism and whole-Run TTFT remain unproven; zero model calls.

- LOCAL-GVISOR-INFO-CONNECT-01 local activation:Worker healthy/source hashes match;
  fresh runtime preflight33.955/24.763/31.775ms; no-client-cert request rejected.
  Full build frontend network timeout; activated existing verified image plus two
  source replacements. Only local integration; no push/model/Run.

- 2026-10-15 CLOUD-AGENT-AUTONOMY-01:shared model-native guidance, scoped Host
  tool/recovery instructions, goal-only Trench contract and targeted revision
  feedback.103 Zebra/45 Trench focused tests; Ruff GO. No extra classifier call,
  routing categories, authorization/coverage changes. Real provider behavior
  remains pending manual testing; no model calls issued.

- CLOUD-AGENT-AUTONOMY-01 local activation:four Worker source hashes match,
  healthy/preflight ready; Trench reloaded/live. Integrated-source103+45 tests pass.
  No model invocation; semantic gain pending user manual test.

- 2026-10-15 CLOUD-AGENT-AUTONOMY-01 real paired UI acceptance FAILED:
  reply request2 model rounds/3 irrelevant inventory tools/24.793s; verification
  request3 rounds/13 tools/47.326s, sameFlash/high/general/v2. Both completed.
  First-stage implementation is active, but simple-request semantic fix is incomplete.

- 2026-10-15 CLOUD-AGENT-AUTONOMY-02:explicit natural-language expression/
  real-check boundary locally active. Exact paired real retest:reply1 round/
  0 tools/16.973s, verification4 rounds/13 tools/51.720s.103 regressions pass.
  No keyword routing/tool ban; broader generalization and speed SLO unproven.

## CLOUD-OCI-CLI-CONNECT-01 (2026-10-15)

Validated explicit INFO CONNECT routing now also applies to the native pinned Docker CLI private environment. Explicit mTLS/host flags, fresh identity, exact labels/ID, PG authority/fence and mutation retry behavior remain unchanged. No global environment modification; absent configuration keeps existing behavior.

66 focused runtime/worker regressions, targeted Ruff/mypy passed. Three alternating real Worker/gVisor lifecycle pairs with real isolated PostgreSQL authority/fence: provision mean 5.264s→1.776s (66.26% reduction). Pinning 21–27ms. All six containers removed and temporary PG schemas dropped. No model calls in lifecycle proof. Evidence .artifacts/oci-cli-connect-20261015/results.safe.json; real Trench startup acceptance pending local activation.

- CLOUD-OCI-CLI-CONNECT-01 local activation/real acceptance: three newFlash/high/general/v2 reply Runs all1 model round/0 tools; first model mean7.278s vs historical11.138s (34.7% reduction), Host completion mean11.585s vs16.973s (31.7%). reserve→model mean2.516s vs6.707s. Historical-v-current observational comparison, not concurrent model A/B or browser TTFT. Worker healthy/hash match/preflight ready; derivative one-source image, no dependency changes; no push. Detailed evidence primary .artifacts/oci-cli-connect-20261015/REPORT.md.

- CLOUD-STARTUP-DNS-01: real pre-runtime trace confirms repeated~380ms TaskIO DNS children. Simple explicit host/port child uses stdlib; complex service/multi-host/orderings keep psycopg.30 native/deterministic focused passes, cold resolver mean385.7→69.9ms. Local activation and real after-samples pending; no push. See docs/CLOUD_STARTUP_DNS_OPTIMIZATION.md.

- CLOUD-STARTUP-DNS-01 local acceptance complete: Worker+v2 API normal-entrypoint/source hash/healthy/preflight verified; real final first model5.375/4.626s mean5.001s vs previous7.278s (-31.3%), small-sample observational comparison.1 main model round/0 tools each; UI output visible. Temporary profiling removed. No browser precise TTFT/full suite/push claim; SQL calls unchanged.

- CLOUD-STARTUP-EXEC-01: isolated real PG/gVisor pairs prove nodelay on existing mTLS bridge: exec1071.654→727.978ms, provision1667.888→1291.748ms.61 focused runtime/worker regressions and Ruff GO. Real pre-model construction50/13/3/41ms is not the bottleneck; preserve it. Browser body DOM timing installed temporarily; local bridge activation/after acceptance pending. See docs/CLOUD_STARTUP_EXEC_OPTIMIZATION.md.

- CLOUD-STARTUP-EXEC-01 accepted locally: existing mTLS bridge nodelay activated/anonymous TLS rejected, daemon unchanged, normal Worker entrypoint/healthy/preflight restored.61 focused passes/Ruff GO. Real first model mean4.629s vs5.396s; DOM body mean10.779s vs12.840s, small-sample observational comparison with differing clock boundaries/UI fluctuations. All1 main round/0tools/v2. Temporary listener/profiling/DOM observer removed. No push.

- CLOUD-STREAM-SDK-PERF-01: core first-delta already immediate; confirmed SDK quadratic encoding and repeated historical React rows. Common SDK two-source fix reduces512frames mean257.1→10.8ms; historical rows41→1render/40updates.35 Python flow checks and initial83SDK tests/strictcheck/build GO; independent built-exports browser shows draft before commit/body7.5ms. Final package gates pending local integration; no Trench/model/npm publish/push. See docs/CLOUD_STREAM_SDK_PERFORMANCE.md.

- CLOUD-STREAM-SDK-PERF-01 accepted locally: v2 bootstrap pending-effects reads2→1 at unchanged awaited recovery boundary; reducer512frame mean257.137→10.756ms, list historical rows41→1/40updates. Current working-tree pnpm verify GO:103tests/strict TS/5 builds/package audit/React18+19 Vite+Next consumers/Chromium+WebKit+hydration.35 Python flow/privacy checks GO. Independent browser draft-before-commit proved without Trench/model. Existing UI changes remain dirty, including native toggle-wait test follow-up; no npm publish/push/Cloud deployment or real-model TTFT claim.

## 2026-10-15 - Cloud first-body latency plan

User approved the direction; detailed plan at docs/superpowers/plans/2026-10-15-cloud-first-body-latency.md. Sequence: reuse timing/real draft proof, on-demand cloud sandbox after dependency audit, measured admission waits, conditional node warm-up and Provider tuning. Generic running-container pool is conditional: immutable workspace mounts/session labels/spec digest require a separate authority design. Targets are proposed, not measured SLAs. Planning only; STOP and paired SQL80% gates remain independent. Existing dirty UI work preserved.

2026-10-15 LATENCY-TRACE/DRAFT component: official built SDK consumed real authenticated v2 SSE; provisional DOM preceded canonical by4357.6ms, observation→DOM3.6ms. Artificial queue wait excluded. Existing common production stream needs no change. Fixed diagnostic generation cancellation race; SPEC/QUALITY GO,35 focused passes plus observer/proxy smoke. Consolidated startup distributions remain final gate.

### Cloud first-body LAZY slice 2026-10-15

Source and focused/native gates accepted; eligible pure replies allocate no OCI runtime. SPEC/QUALITY GO. Real v2 pure Run completed with zero instances; candidate locally enabled for paired evidence, normal entrypoint activation pending. See docs/CLOUD_FIRST_BODY_LATENCY_ACCEPTANCE.md.

### Cloud first-body shared address reuse 2026-10-15

Three Worker execution phases reuse existing same-DSN address cache while retaining fresh database facts. Focused/static SPEC/QUALITY GO; local paired rollout follows. API/Broker time remains separately measured; no blanket 4s claim.

### First-body latency local activation and acceptance boundary 2026-10-15

Core source commits locally integrated and normal Worker/API restored; defer_provision=true in normal local env.40 real requests:20pure all1round/0tool, lazy pure0OCI;20sandbox each1actualcommand/1instance, all resources removed. Current-source flag comparison pre-model-event median3513.37→1811.73ms(-48.43%). Full make check and5npm verify pass. Trench draft adapter2aff921 fixes hidden provisional body (19tests), but Chrome connection blocks post-fix real DOM acceptance. Canonical35/40complete;5existing quality-revision Provider400 also present with eager, root response-body evidence unavailable. Core implementation is not fullE2E acceptance. STOP/fullSQL80 unchanged. See acceptance doc/runbook for exact next checks.

### Focused quality and Provider repair 2026-10-15

QUALITY-PROVIDER-REPAIR-01 fixes ambiguous bare 报告 forcing long structured output, and preserves exact empty DeepSeek reasoning for same-turn SYSTEM quality revisions. Controlled actual Provider pair: missing field400/present empty200; full real gateway completions pass stream/nonstream.71 focused regressions and make check pass. Normal local Worker updated,17 source hashes verified including all15 latency files; lazy flag/API unchanged. Final real-page DOM acceptance remains open due browser control timeouts after reconnect; no original Run replay or unrelated fixture work. See CLOUD_FIRST_BODY_LATENCY_ACCEPTANCE.md.

### Real page quality/Provider acceptance 2026-10-15

Browser restored. Fresh page revealed negated research/structure false positive; shared inference now excludes bounded negated clauses while preserving explicit contracts/length limits.108 focused tests + make check pass. Four fresh post-fix canonical v2 completions: story1model/0tools/0OCI, pure1/0/0, command2/1/1removed, pagepure1/0/0. Actual page first body5.518s short/14.334s story, both provisional before commit. Provider story TTFT8.764s, so stable3s page target is not achieved. Normal Workerb3f64784,17 source hashes verified/all prior latency files retained; API unchanged. Failure before follow-up retained; no old Run replay. See acceptance doc.

### Cloud input membership transaction slice 2026-10-15

INPUT-MEMBERSHIP-01 removes the extra PG Task-port socket and duplicate membership lookup inside each native input operation; no cross-operation cache or pool. Fresh native namespace/lease/deadline checks retained; SQLite/legacy helper compatibility verified.109 distinct relevant cases + make check pass. Two fresh canonical v2 short starts:91→76 TaskIO connections,566→551 cursorcalls,32 fence checks unchanged; inputs271–306→224–229ms exploratory. Worker236aef39 normal/healthy, API unchanged,18 source hashes match/all prior latency gains retained. No stable page-latency or totalSQL80% claim. See first-body acceptance doc.


### Bounded input SQL consolidation 2026-10-15

INPUT-BOUNDED-QUERIES-01 merges size-gated head reads and terminal index seeks in one storage file. Two actual starts: cursor551→525(-4.72%),76 fresh sockets/32 fence checks unchanged; no latency improvement proven.119 focused original cases pass; original long-history fixture expired60s lease before first advance, separate5min scratch diagnostic passes. makecheck green. Normal Worker a51c3a59/API unchanged,18hashes verified. Actual page short6.599s/story26.597s; story Provider firstbody21.871s/4978reasoning tokens, provisional visible633ms beforecommit. Stable3s/fullSQL80/STOP remain open; prioritize Cloud reasoning policy and page admission path, not further SQL micro-tuning. No push/remote deploy.


### Actual-page admission and key warmup 2026-10-15

PAGE-ADMISSION-TRACE-01 identifies client admission211–311ms plus pre-Cloud783ms/Worker1384–2092ms; no Host source change. Cloud API now prefetches active registered JWKS before readiness with existing cache/TTL/rotation and one2s bound; every request still checks fresh authority/nonce.49 focused checks/static pass;3isolated no-model pairs auth median81.32→29.92ms. Candidate startup fetch363ms moved before readiness; real key hit0.172ms but total auth496ms due DB/DNS variation, so no page improvement claim. Normal page12.338s has1logical round/2Provider attempts (one retry),v2/0tools/0OCI;917ms TTFT belongs only to successful attempt, total model7028ms. First retry cause not retained. APIc0b8e9dc/Worker a51 unchanged,21source hashes verified, normal services healthy. Next safe per-attempt retry diagnosis; stable3s/fullSQL80/STOP remain open. No push/remote deployment.


### Provider attempt diagnostics 2026-10-15

PROVIDER-ATTEMPT-TRACE-01 retains safe failure class/status and per-attempt/cumulative timings across both Gateway wire APIs, stream/nonstream. Durable TTFT remains successful-attempt-relative; diagnostic cumulative value explicitly includes earlier failures. Failures/recovered retries visible at default WARNING; no payload/secrets/delta SQL or retry-policy/default changes.21 new red/green checks;141 focused and make check pass. Three fresh normal pages completed/v2/1model/0tools/0OCI/retry0: first body5.364–6.085s, median5.652s, model-start event3.561–4.819s, Provider489–754ms. First short draft precedes commit500.5ms. Prior12.338s retry's original cause remains unknown; no causal speedup claimed. Normal Worker e76adcdc/APIc0b8e9dc healthy,24hashes and original composition verified. Next: measured pre-model boundary; preserve bounded TaskIO isolation, explicit high and existing gains. STOP/fullSQL80/distributions/lifecycle still open. See acceptance doc.


### Pre-model Context snapshot reuse 2026-10-15

PRE-MODEL-CRITICAL-01 removes two full recoveries immediately following the recorder's own fenced atomic Context appends. Reuse only if a fresh active primary exactly matches the committed Session and lease/fence/workspace revisions agree; concurrent drift keeps original recovery, with native cumulative2s deadline/ownership/cancellation unchanged. Local recovery and Callable[[],None] cancellation compatibility preserved. No pool/cache/dependency/Host/SDK/default change. Two frozen same-prompt Flash/high page pairs: Context709→426ms, Worker→HTTP1650→1456ms; startup cursor531→415(21.85%), TaskIOconnect76→66. Send→HTTP3923→3817ms, DOM5061→5387ms: no overall page gain established. Intermediate slower samples retained, old-code return control confirms531 calls.8new runs all completed/v2/1model/0tools/0OCI/high; normal入口body4900.9ms.46focused+5cancellation local pass,10nativeContext+6nativebounds pass; makecheck3068/Ruff/mypy1278/eval30 pass. One inherited identity wording failure and one unchanged250ms tail timing assertion retained; two native cancellation cases blocked in fixture setup by pinned existing header_scratch endpoint, no fixture/credential changes. Normal Worker376b20dd/APIc0b8e9dc healthy,26hashes/original composition verified. No old Run replay/publication. Stable3s/fullSQL80/STOP/lifecycle/distributions remain open; see acceptance doc.


### 2026-10-15 — SEARCH-WORKLOAD-PAIR-01：真实网络搜索验证

五个新页面会话均 canonical completed / transient_v2 / Flash high，实际4–6轮主模型、
6–10工具、每轮一个sandbox；包括3次失败抓取后的替代路径。最近Context固定工作
531→415启动cursor calls、76→66连接仍成立；整轮41.926–66.832s和3,713–5,467
Worker范围SQL调用暴露复杂任务尚未解决。优化组没有证明整体提速，首段过程说明
与实际带官方来源答案分开记录。工具串行、搜索命中/长文截断、控制读取和checkpoint
为后续窄切片；本次仅验收，无生产源码更改或旧fixture修复。正常镜像/六份Compose/
入口/命令与26源hash恢复核对。详见docs/CLOUD_SEARCH_WORKLOAD_ACCEPTANCE.md；
完整系统SQL80、稳定分布、STOP/GC仍未通过。仅本地集成，不推送/远端部署。


### 2026-10-15 — WEB-READ-PARALLEL-01

两文件最小实现：精确内置search/fetch注册为parallel_safe，共享每attempt两路信号量；
自定义/subclass/nativeWebv2及其他工具配置保持原状。既有executor每次submit复制
独立Context，保留deadline，现有线程保护拒绝跨线程父DB连接。5新检查红→绿，另2注入保护检查通过，
111聚焦通过/2跳过/1未选，mypy1278/eval30和排除私有.artifacts后的Ruff通过；
makecheck原命令因扫描未跟踪诊断脚本失败，未修无关文件。受控四个300ms输入
中位最终1211→610ms(49.62%)；四个真实v2/high联网Run均完成，网络峰值1→2、启动
415 SQL/66连接不变。整轮55–65s、SQL5127–6449，未证明总体提速或SQL降低。
正常Workerb9f1e732/APIc0b8e9dc、原六份Compose/入口/命令/28源hash已核对。
详见docs/CLOUD_WEB_READ_PARALLEL_ACCEPTANCE.md。第2步控制SQL及STOP/GC仍未通过。


### 2026-10-15 — WEB-CONTROL-READ-01

三份生产文件精简活动Cloud控制轮询：一次namespaced status SELECT替换SET+完整
Session；每次fresh连接/ownership、50ms轮询和2s累计预算保留。Context及Local保持
完整读取，终止状态回原新鲜Session异常路径；自定义get_session覆盖不被绕过。
固定100检查200→100显式cursor调用，SELECT/新连接均仍100，不冒充服务器SQL
或连接下降50%。97相关检查全通过，含独立PG新鲜/隔离/锁期限与两路真实TLS取消
回收；Ruff排除私有.artifacts、mypy1278/eval30/文件门通过，原makecheck仍因诊断
脚本Ruff失败。两个新v2/high联网Run完成：46.166→34.971s、SQL5173→3231，模型
6→4轮/工具9→6，未归因整轮差值；新样本272活动轮询各少SET。两路并行、启动
415SQL/66连接保留；正常Worker76937731/API不变，六Compose/入口/30源hash核对。
检索质量/checkpoint、完整系统SQL80/STOP/GC/稳定分布仍未过。详见
docs/CLOUD_WEB_CONTROL_READ_ACCEPTANCE.md，仅本地集成，不推送/远端部署。


### 2026-10-15 — WEB-RETRIEVAL-01

共享HTMLParser优先可见main/role main，未标记/空区域回退原全文，保留隐藏/script安全及
字节/模型预算。固定Redis官方HTML21883→14833字符，日期6560→296位置，通用投影
从省略日期变为保留；PG未标记页面不变。11新检查红→绿，99相关通过；Ruff排除私有
.artifacts、mypy1278/eval30/文件门通过，无旧fixture扩展。两个新真实high/v2Run均完成，
原持久Redis工具输出日期false→true。总58.225→52.419s、SQL5025→4397，但模型6→5/
工具9→8、两侧各2失败且网络等待增加，不归因总差值或宣称稳定收益。两路并行/启动
415SQL、66连接及fresh scalar保留；正常d9d84e3c/API不变、六Compose/入口/31hash核对。
检索完整query本地未丢，但cn.Bing重复首页/site限定无效，搜狗备用报错；上游原因仍
未彻底定位，未改全局引擎/语言或掩盖失败。报告docs/CLOUD_WEB_RETRIEVAL_ACCEPTANCE.md，
私有证据.artifacts/web-retrieval-20261015。整体SQL80/STOP/GC/稳定分布未验收。


### 2026-10-15 — SEARCH-PROVIDER-QUALITY-01

完整q与HTML首词泛化响应直接复现，固定Bing已含上游PR6671，换语言/市场/出口/RSS
未恢复。360限定官方公告不合格；Sogou限定查询302antispider且next_request兼容错误；
Google/Brave原生隔离测试拒绝/限流、DDG验证码，未绕过或盲换默认。用户无API凭据，
先落地operator误判修复：verify.py区分transport与已知来源约束，默认两公告canary，
自定义query配expect-source，transport-only不标ready。相同两查询旧版各5来源ready真，
新版正确expected_source_missing/退出1；官网导航正例仍过。13新检查红→绿，65相关过，
仅集中更新3个CLI调用点。Ruff排除私有.artifacts、mypy1278/eval30/文件门过；额外脚本
mypy原有9项未扩修。无模型/页面配对、无新增SQL/耗时收益主张，性能目标仍未完成。
原d9d84e3c/APIc0b/搜索245b675f及配置不变，31hash/六Compose正常入口核对；自有
隔离容器/卷/临时secret移除。报告docs/CLOUD_SEARCH_PROVIDER_QUALITY_ACCEPTANCE.md。
仅本地集成，保留27条脏改动；不推送/远端部署/改业务库。


### 2026-10-15 — SEARCH-FREE-PROVIDER-01

四个额外已安装免费原生候选：Yep空、Qwant验证码、Mwmbl超时，Yahoo命中具体公告。
源码发现Mojeek/Startpage自动解验证码而不执行。Yahoo中英文/独立Python源/域限定六项
通过；直连超时，标准容器HTTPS_PROXY下冷实例六过(首2.643s，后0.764–1.291s)。
最小settings启用Yahoo唯一默认、Bing显式保留；工具描述不写死默认，新增!yh说明。
本机出口仅原service.env的HTTPS_PROXY/NO_PROXY，不入可移植源码或Trench，无新依赖。
3检查红→绿，72相关过；Ruff排除私有.artifacts、mypy1278/eval30/文件门过。原TLS
入口operator两条ready且命中来源。新真实高/v2配对33.898→28.451s、模型4→3/工具6→5、
搜索4→2、Worker显式SQL3246→2738；只报本次观察16.1%/15.7%，不冒充稳定分布/系统
SQL80%。实际首轮候选从首页/教程变具体公告；两路并行及启动415SQL/66连接保留。
正常Worker d6b72027/APIc0b不变、32hash/六Compose；搜索245b675f/正常一Compose和
主checkout配置、原envfile已核对；trace/观察器/自有隔离容器卷/临时secret撤除。
报告docs/CLOUD_FREE_SEARCH_PROVIDER_ACCEPTANCE.md；本地集成，保留27脏改动，不推送。


### 2026-10-15 — WEB-RUNTIME-DEFER-01

共享工具入口对原生search/fetch也ensure_ready，真实OCI create796/start707/exec960ms；
仅实际注册的默认精确类型网络handler跳过DeferredRuntime，自定义/其它工具与Web另一
pipeline保守不变。新增7项红1→全绿，共90针对性检查，Ruff排除私有诊断/mypy1278/
eval30/文件门过。两次新高/v2页面首工具3110→249ms、首区间SQL143→73、实例1→0，
启动415SQL/66连接和并发2保留。整轮44.545→56.396s、SQL3989→4722，不报整体提速：
A1搜索失败一次，B1Redis博客抓取超时并增轮6/工具9，精确日期质量仍未完全验收。
正常Worker c7a422d5/API与Yahoo不变、32hash/原六Compose正常入口；报告
docs/CLOUD_WEB_RUNTIME_DEFER_ACCEPTANCE.md。只本地集成，保留27脏改动，不推送。


### 2026-10-15 — WEB-FETCH-CONNECT-01

旧Redis抓取10s父截止detail确认，但3次Redis/1次PG分段无模型复测未重现；不猜网络
阶段。稳定导入850–901ms另记，TCP1–3ms/TLS345–474ms，原HTML1692922bytes。
仅web_gateway.py新增gzip协商和wire/decoded双cap/完整性错误归一，10新回归红→绿，
211相关通过；Ruff排除私有诊断/mypy1278/eval30/文件门通过。固定同页ABBA，HTML/
投影hash全一致：wire1692922→418982(-75.25%)，正文659→398ms，进程2.272→2.086s。
单次新高/v2页面44.413s/6模型/7成功handler，RedisGA抓取2469ms；另2次模型limit
字符串被原类型边界拒绝，未扩修。SQL4412/连接998，启动415/66、并发2、0sandbox
保留；不报gzip系统总收益或原偶发超时已解决。正常Worker7be67b5c/API与Yahoo不变，
33hash/原六Compose入口复核；本地集成保留27脏改动，不推送。报告
docs/CLOUD_WEB_FETCH_CONNECT_ACCEPTANCE.md；下一独立优先项为子进程包导入依赖。


### 2026-10-15 — WEB-CHILD-IMPORT-01

四包入口按需加载原聚合，四份原导出模块逐字搬移、505公共名称/身份/import*保持。
7项新进程红→绿，235相关原生安全/Worker检查+32实际包级MCP调用点通过，Ruff排除
私有诊断/mypy1282/eval30/文件门通过。无网络同约束各3进程Web导入901→260ms、
搜索933→261ms，模块1241→257/262；真实原生同页Redis2397→1596ms、PG2571→1628ms
且投影hash一致。两次新高/v2页面27.167→24.318s、官方链接26.010→23.116s，模型
均4轮；候选另2参数类型失败、少1实际搜索，不能全归因导入。总SQL2863→2892反增29，
连接660→562；启动415/66、并发2、0sandbox保持，不报系统SQL80或稳定3s。正常Worker
4a1c78ad/API与Yahoo不变，41hash/原六Compose入口核对。本地集成保留27脏改动，
不推送。报告docs/CLOUD_WEB_CHILD_IMPORT_ACCEPTANCE.md；模型limit字符串损耗另查。


### 2026-10-15 — WEB-MODEL-LIMIT-01

模型非strict虽收到integer schema仍可能返回字符串；json.loads不改类型。既有模型
resolver仅规范原生search精确ASCII"1".."5"，保留原provider参数/continuation，原
Policy/直接输入/其它非法值仍严格拒绝；共享既有Policy事实加原始字段，无新事件/
SQL次数。35新检查与固定真实Harness证明错误输入3→2轮、失败1→0；169相关通过，
Ruff排除私有诊断/mypy1282/eval30/文件门过。两次新高/v2页面30.325→27.471s，
首过程文字4.853→4.994s，官方链接28.851→27.330s，均4模型/6工具/0失败；两侧
模型本次都给整数5，不能把9.4%总耗时差归因修复。Worker SQL3141→3120，仅少21，
不报整体SQL收益。启动415/66、两路并发/0sandbox、gzip/导入/新鲜scalar保持。
正常Worker b373f27d/API与Yahoo不变，42hash/原六Compose入口核对；本地集成保留
27脏改动，不推送。报告docs/CLOUD_WEB_MODEL_LIMIT_ACCEPTANCE.md。


### 2026-10-15 — WEB-PROGRESS-CATCHUP-01

persist写入后catch_up紧接repair内catch_up；仅删除重复调用，写前/后仍各新鲜检查，
锁/两秒累计预算/原子fence/CAS/未知提交恢复不变。新增真实checkpoint红[1,2,2]→
绿[1,2]及提交后Run supersede拒绝。125相关过+2原生PG SQL/commit截止过；1既有
缺Redis组合fixture失败在旧persist复现、不扩修；1专用TLS端点skip。Ruff排除私有
诊断/mypy1282/eval30/文件门过。无模型PG相同24事件ABBA，SQL792→720(-9.1%)、
新连接144→120、中位3599→3047ms。新高/v2真实配对均3模型/4工具/0失败/0sandbox，
37append相同，catch_up97→66；Worker SQL2324→2204，指纹精确减少93去重SQL+
27少轮询，连接499→441=31+27；总21.735→20.711s不全归因修复，首过程5.045→
5.129s未改善。启动415/66→412/65；两路Web/导入/gzip/limit/新鲜控制保持。
正常Worker5d086202/API与Yahoo不变，43hash/原六Compose入口核对；私有scratch/
匿名卷/临时DSN清理，本地集成保留27脏改动，不推送。报告
 docs/CLOUD_WEB_PROGRESS_CATCHUP_ACCEPTANCE.md。全系统SQL/稳定首正文目标仍未完成。


### 2026-10-15 — WEB-PREMODEL-ADMISSION-01

只读完整API/Worker新真实搜索拆解，点击→实际HTTP3231.645ms=首次Cloud前419.169+
串行准入1418.675+command到Worker243.194+Worker1150.606。首过程4911.4ms；
本次5模型/8工具/0失败、高/v2/无retry/0sandbox；不与旧3轮请求比较整轮性能。
HTTP合计952.776ms、间隙465.899ms；Client open/mount/bind窗口480.712ms，内部
214.029、间隙266.682。首次JWKS resolve0.087ms，热身已生效。Context340/Task317
为主要单段，尚无可直接删去的大重复；不再强凑毫秒修复。下一建议独立通用Client
组合准入，复用现有control-plane服务并先定义幂等/credential/fence/部分失败契约，
SDK协商，原验证/旧路径保留，页面收益估计数百毫秒未验收。未改生产/Host/SDK源码。
正常Worker5d086202/APIc0b/原六Compose恢复、43hash/搜索配置环境核对，临时观察器
撤除。本地诊断文档集成保留27脏改动，不推送。详细方案
 docs/CLOUD_WEB_PREMODEL_ADMISSION_ACCEPTANCE.md；稳定首正文/整体SQL目标仍OPEN。

## 2026-10-15 CLIENT-SURFACE-01 local acceptance

Generic Cloud mount+bind3→2HTTP, SDK helper and minimal Trench negotiation2731737 accepted.
Actual B1 cold-resolver201ms regression fixed through existing Cloud connector injection;
A1→B2 Client249.6→198.0ms/SQL38→36, first visible body4560.8→4378.8ms only4.0% in one pair.
Worker startup412SQL/65connect unchanged; high/v2 preserved, normal API/Worker/search verified.
All three new Runs retained; B2tools5 vs A1/B1six so total completion gain is not causal.
Focused native85, SDK25+check, consumer18/2skips, source quality/eval30 pass; raw makecheck
stops on private artifact lint. Full evidence: docs/CLOUD_CLIENT_SURFACE_ACCEPTANCE.md.
No push/npm/remote deployment or oldRun replay. Local integration target remainscloud-agent-trench.

## 2026-10-15 LATEST-RUN-READ-01 local acceptance

Shared PostgreSQL latest executable Run identity+metadata now one statement, reusing canonical
metadata/source checks. Native40pairs2→1SQL/8.611→7.783ms;59safety/native checks passed.
New real high/v2 search A1/B1 Worker startup412→404SQL,65connections unchanged; firstvisible
4.951→3.859s observed but not causally attributed (4/5→3/4model/tools, timing variation).
Normal API/Worker/56sourceidentities and unchanged six-file/search composition verified.
One-function SQL optimization only; full startup/first-body goal remains open. Details:
docs/CLOUD_LATEST_RUN_READ_ACCEPTANCE.md. No push/npm/remote deploy or oldRun replay.

## 2026-10-15 INPUT-READ-BATCH-01 backend acceptance; page pair pending

Generic Cloud execution-input preparation now shares only its initial membership/header/head
reads in one bounded native readonly RR snapshot. Final Task reads and post-commit refreshes
remain fresh; SQLite/legacy/custom and different database/namespace compositions fall back.
Fixed native40AB/BA pairs4→2connections,7→6SQL,323.778→187.520ms (-42.1%) in a loaded local
environment; not a whole-Worker/first-body percentage. 28targeted regressions pass; final new
suite8pass+1deadline timeout, isolated interleaving rerun passes; all9behavior cases evidenced.
Old baseline reproduces large SQLite fixture60slease failure; no unrelated fixture repairs.
Source Ruff/mypy1283/size/eval30 pass. Backend source-only local images prepared/activated;
final hash/normal service receipt in WORKLOG. Browser user reconnected but controls still
Debugger unattached/time out, so no new model Run and actual page pairing remains open.
See docs/CLOUD_INPUT_READ_BATCH_ACCEPTANCE.md; local integration only, no push/npm/remote deploy.

2026-10-15 page follow-up: browser restored, first baseline search failed before CloudSession
binding/model/tools/sandbox (all0). Error11757ms is not正文. Host extension-list admission503
at2036ms consumed2sbudget, DNSchild1184ms/connection1331ms + JWKS583ms. Worker deadline
restarts also observed. Input batching remains native-proven, actual page acceptance open;
next narrow candidate is resolver child startup after import/DNS stage measurements.

## 2026-10-15 RESOLVER-STARTUP-01 backend local acceptance

Real search baseline failed pre-model on2sHost admission (DNSchild1184ms + JWKS583ms).
Minimal shared TaskIO fix uses a killable python-S/native_socket address child only for explicit
single ASCII host/numeric port; bytes avoid IDNA import, credentials/settings remain parent.
International/service/multihost/env-only/prefer-standby/random stay with libpq. No deadline,
cacheTTL, fresh authentication, TLS host, SQL/COMMIT or Host authority relaxation.
Native20AB/BA cold pairs979.703→112.088ms/childCPU687.171→72.845ms,20/20success each;
first unhelpful prototype measurements retained. Two fresh realDB connections+SELECTs in one
original2sbudget completed392.5ms and closed.18focused behaviors evidenced incl both kill/reap
paths; final9pass+2timingfailures in concurrent build, both isolated cases pass4.28s, no fixture or
budget edits. SourceRuff/mypy1283/size3088/eval30 pass. NormalAPI/Worker running healthy,
zero restarts at receipt,62sourceidentities/sixCompose/search verified. User foreground/reconnected
browser again, controls still time out/native wrong window; no post-fix model Run or page A/B yet.
Local integration only; docs/CLOUD_RESOLVER_STARTUP_ACCEPTANCE.md has precise proof boundary.


### CATALOG-ADMISSION-AVAILABILITY-01 (2026-10-16)

Fixed local catalog admission false unavailability: extension GET/public-key warmup have bounded5s aligned with the existing key fetch; execution/write admission and per-connection TaskIO remain2s. Worker read-only discovery transient failures defer without losing cursor/intent or replaying effects. Real signed catalog3x503→3x200, nonce replays403;44focused+nativeTLS pass, Ruff/mypy1283/size3088/eval30 pass. Two baseline Redis fixture failures explicitly retained. NormalAPI50810e64/Worker017aae18 and63source identities/config/search verified; no model or oldRun replay. Local cloud-agent-trench integration/activation only. See docs/CLOUD_CATALOG_AVAILABILITY_REPAIR.md.

Read-only follow-up: later user Run9e3549d1 failed upstream_timeout before Cloud binding/model, during17Worker read deferrals and an OrbStack sleep window. Exact shared-stall cause remains unproven; initial success is not universal availability acceptance. After11h both normal services healthy/zero restarts; fresh catalog3x200/replay403, actual skill preparation262/73/48ms and normal-budget capabilities3x200. No further source/restart/model/oldRun replay. Controlled Chrome requires login before page acceptance; detailed timeline and proof limits in the same acceptance doc.

Page follow-up completed through the original authenticated Chrome extension tab (the earlier DevTools login page belonged to a separate browser session). Actual conversation shows the two durable failed turns, enabled composer, Flash/high and no-model-data indicator. No automatic retry/new message/model invocation. Read-only page acceptance passed; new-generation/first-body acceptance and exact historical shared-stall attribution remain open.


### E2E-SEARCH-LATENCY-01, 2026-10-16

Real search exposed a Host queued-dispatch incident and canonical COMMIT lock contention on derived projection work. Restored existing Host autoreload without content changes; cap only PG repair header sub-budget100ms, parent2s unchanged. Native negative234ms lock failure→candidate80ms commit, prefix+frontier converge;19consumer pass5skip/static gates pass. B1 high/v2 process4.62s/substantive provisional answer33.57s,9tools succeed but final contract false-positive operate blocks completion. Startup398SQL/53connections unchanged; no overall speedup claim. Separate focused task-contract repair required; normal restoration follows immediate acceptance work. See docs/CLOUD_E2E_SEARCH_LATENCY_ACCEPTANCE.md.


### QUALITY-PUBLICATION-DATE-01, 2026-10-16

Fixed fallback 发布日期/发布时间→operate false positive, preserving explicit publish/deploy verification, evidence/citations and model tool selection.12standalone boundary checks+62existing targeted tests/static gates pass. One fresh same-prompt Flash/high/v2 C1 completes4model rounds/6successful tools; process5.41s, substantive provisional body27.70s, Hostcompleted31.86s. B1 previously6rounds/9tools thenpaused; preserved without replay. Startup398SQL/53connections unchanged; model/network differences prevent causal percentage claims, and search still has substantial waits. Restored normalAPIb0f0832b/Workere46c3823, healthy66sourcehashes/originalsixCompose/env/commands/search verified; completed page reloads original answer. E2E normal-restoration follow-up complete; focused local acceptance only, no push/npm/remote deploy. See docs/CLOUD_PUBLICATION_DATE_CONTRACT_REPAIR.md.


### PROGRESS-POSTCOMMIT-REPAIR-01, 2026-10-16

Reproduced incident07663699: canonical model response/commentary45/46 committed but progress remained45; postcommitTimeoutError aborted the next tool batch and was mislabeled model failure. Shared typed acknowledgement boundary now defers only confirmed-source derived checkpoint timeouts; existing next-event canonical reconciliation fills the gap without repeating models/tools/writes. Unknown canonical commits and required preparation still fail safely with execution_progress_unavailable. Timer/Effect narration and quota/reservation bookkeeping use the same confirmation rule. Original2s budget/authority/fence/STOP/v2/priorperformance preserved. Native3s-query injection stops1.839s, one exact output and later convergence;53existing focused/native regressions and static gates pass. NormalAPI233f737d/Workera287087d healthy,75sourceidentities/originalsixCompose/env/search verified. Local integration/activation only; historical failedRun retained, no newmodel/replay/push/npm/remote deploy. See docs/CLOUD_PROGRESS_POSTCOMMIT_REPAIR.md.


### PROGRESS-RISK-HARDENING-01, 2026-10-16

Audited12shared publication/recovery/draft/terminal boundaries after the user requested prevention of sibling failures. Reproduced and fixed3additional defects: optional evidence before primary request, read-only observation timeout poisoning futureevents/cleanup, and pendingevidence discarded before publication. Classified eager pending-recovery timeout without assuming append success. Unknownprimary writes/fence/STOP/shutdown failures retainfailclosedbehavior. Added six standalone boundary checks and wired bothprogresschecksinto defaultmakecheck.95existing focused/native tests pass; native1.826s readdeadline retainsfacts and exactdedup, zero realmodel. Fullmakecheck passescleantracked-sourceexport (directworkspaceRuff scans5779historicalprivateartifacterrors; leftunchanged). NormalAPI907fcc00/Worker26f1769d healthy,77sourceidentities/originalsixCompose/env/search verified. Priorperformance kept; no newSQLpercent/model/pageSLA claim or oldRunreplay/push/deploy/npm. See docs/CLOUD_PROGRESS_RISK_AUDIT.md.


### PROGRESS-SOURCE-REUSE-01, 2026-10-16

Reduced timeout exposure by reusing the exact pending model response verified in the current successful bounded progress page, avoiding a duplicate point read. Cold recovery/CASwinner/sourceabsence retainoriginalpointfallback; no cross-call authority cache, larger budget or retries. Real native4A/4B operation:61→57SQL,10→9TaskIOconnections,3→2pages, median264.40→233.47ms. Injected slowduplicatepoint causes original1.819stimeout whilecandidatecompletes0.206s/oneoutput; no wholeRun performance/SLA claim.95focused/native/deadline tests and clean-source defaultmakecheck pass, no realmodel. OnlylocalWorkerbdd9972b replaced/healthy,78sourcefingerprints/originalsixCompose/env/search preserved; APIimage/starttimeunchanged. Localcloud-agent-trenchintegrationonly; docs/CLOUD_PROGRESS_SOURCE_REUSE.md.


### PROGRESS-HEAD-READ-01

Reused existing execution-input bounded SQL CASE pattern in shared Worker progress head read; metadata+body twoqueries→one without weakening32KiB/Unicode/scope/CAS boundaries. Native same-server4A/4B operation SQL57→55, connections9unchanged, median254.52→255.77ms (no stable latency gain); slowoldsecondSELECT1827.47ms timeout→235.56ms successful output under unchanged2s.85existing regressions,7nativebounds and cleantracked-source makecheck pass. Worker5f2b9889 healthy/79sourcehashes+originalcomposition verified, APIimage/startunchanged; no model/oldRun replay/schema/push/npm/remote deployment. Local integration only; docs/CLOUD_PROGRESS_HEAD_READ_OPTIMIZATION.md.


### PROGRESS-MEMBERSHIP-BATCH-01

Removed repeated per-output signature queries from shared progress advancement using existing bounded IN-query pattern, transaction-local only. Native fixed4A/4B128output recovery: signatureSELECT256→1,totalSQL398→143(-64.1%),269.45→122.10ms; ordinary operation55→54SQL with no stable latency gain.85existing regressions+8native identity controls/defaultclean-source gate pass; sameRun/canonical/fence/CAS/32KiB/2s bounds retained. Worker506d0d80 healthy/79sourcehashes+originalcomposition verified; APIunchanged. Localintegration only, no model/oldRunreplay/schema/push/npm/remote deployment; docs/CLOUD_PROGRESS_MEMBERSHIP_BATCH.md.


### CURRENT-RUNTIME-ACCEPTANCE-01

Completed current-version real search acceptance round:2fresh Flash/high/v2 Runs complete,8models/10successful tools. Firstsubstantive35.22/17.59s vsprocess4.64/4.13s; Hostcomplete44.53/21.13s. Startup395SQL/53connect both; Worker-scoped3117/2078 reflects5rounds6tools vs3rounds4tools, not systemreduction. PGofficialfetch9.31vs2.00s and one validcitationcorrection explain substantial variation; Worker-other10.60/6.86s remains to split. No sourcefix; focusedpaircannot certify<=10s/SQL80/STOP/GC. RestoredoriginalnormalAPI907fcc00/Worker506d0d80 healthy/zero restarts,79sourcehashes/originalcomposition verified; normalpage reloadpasses, diagnosticsremoved. Preserved oldClientSession502 and truncatednetwork/proof-boundary limits; no oldRun replay/schema/push/npm/remote deployment. See docs/CLOUD_CURRENT_RUNTIME_ACCEPTANCE.md.


### WEB-WAIT-PROFILE-01

No-model native segmentation: PG TLS1.01–1.07s/headers0.40–0.55s/parse<6ms; historical9.31s outlier unproven. Existing A1/A2 residual resolves progress3.862/2.489s andcanonicalappend3.148/1.980s, with nested/parallel time excluded. Restored omittedstdlibTCP_NODELAY in sharedpinnedHTTPadapter(sevenlines), originalSSRF/TLS/50mscontrol/deadline/killreap unchanged.3newregressions+242focused/native checks andclean-source makecheck pass. FixedABBA noisy2738→2639ms doesnot establishstablegain; exactcandidate2x200/realoption1/hashmatch verified. NormalWorker6f3a5d8b healthy/80sourcefingerprints/originalcomposition retained; APIimage/startunchanged. Localintegrationonly, no model/oldRunreplay/schema/push/npm/remote deployment. See docs/CLOUD_WEB_WAIT_PROFILE.md.


### 2026-10-16 PROGRESS-HEAD-LOCK-01

Claimed focused task/branch at6858b2b5 before implementation. Trace inspection confirms model/tool adapters already avoid no-op queries; shared hot progress advancement still initialized existing rows and locked/read separately. Minimum one storage-module change: bounded head SELECT optionally FOR UPDATE, INSERT only when absent and reread concurrent winner. Original byte gates/canonical validation/fresh authority/CAS/rollback/2s retained. Existing standalone hot INSERT check red→green; native barriers force both missing-row and existing-row races, one winner/one stale each.86targeted checks(74+12native), clean tracked-source makecheck/Ruff/mypy1283/size3094/eval30 pass; first gate line-length fixed only. Same-server fixed ABBA4each operation SQL54→50(-7.4%),9connections/2pages unchanged,215.49→215.04ms median(no stable latency gain). Zero model/provider/historicalRun replay. Worker03bc01aa updated after zero-active-intent guard, healthy/zero restarts;80sourcefingerprints/originalsixCompose/env/commands/search verified, API907fcc00 exactimage/start unchanged. Local FF preserves27unrelateddirtyentries; no schema/cache/pool/retry/deadlinechange/fixturefix/push/npm/remotedeploy. Whole-system80%/firstbody/STOP/GC/multiworker gates remainOPEN. Docs CLOUD_PROGRESS_HEAD_LOCK.md; safe receipts .artifacts/progress-head-lock-20261016.


### 2026-10-16 RUN-HEADER-PLAN-01

Claimed focused task/branch at3cc045bc before implementation. Native read-only original-Task EXPLAIN locates Run metadata planning5.16–8.23ms vs execution0.61–1.20ms; bounded SQL prototypes have no stable benefit and were not retained. Reused existing callback connection scope with explicit bounded=True, isolated from longer coverage callbacks, matching DSN/environment/cursor/deadline keys and libpq17+ cancellation; older clients/service-configured DSNs retain fresh sockets. Every adapter still commits/rolls back/resets independently; no cached Run/authority or shared active transaction/new Port/pool/dependency. Original2s/fresh fence/STOP/CAS/public draft/v2 behavior retained. Native socket-check3red→green; batched secondary close error audit finds query/unknownCOMMIT/callback masking3red, shared minimal cleanup preserves primary error and closes all handles.134distinct focused checks(74functional+60connector/scope/native) pass,2optional guarded sharedDNS experiments skip; cleantracked-source makecheck/Ruff/mypy1283/size3095/eval30 pass. Final same-server ABBA4each exact response/commentary operation physicalconnections9→1,SQL50→59(preserved9resets),214.695→115.305ms median(-46.3%); initial271.655→120.210 retained, no wholeRun/page extrapolation. NormalWorker8336bda6 activated afterzeroactiveintent guard, API907fcc00 exactimage/startunchanged; healthy/zero restarts,82sourcefingerprints/originalsixCompose/env/commands/search verified. ActualWorkerlibpq18 read-only probe proves two independent transactions/one socket/reset/scopeclose,0models. No appDBDDL/manualrepair/historicalRunreplay/model/schema/fixturefix/push/npm/remotedeploy; localFF preserves27unrelateddirtyentries. Whole-systemSQL80/firstbody/STOP/GC/multiworker gates remainOPEN. Docs CLOUD_RUN_HEADER_PLAN.md, safe receipts .artifacts/run-header-plan-20261016.


### 2026-10-16 PROGRESS-ROUNDTRIP-01

Profiled the current bounded-connection response/commentary operation: deferred canonical COMMIT routing dominates remaining native time; the ready trigger repeats privacy/version source classification across routing statements. Added function-only migration102 to classify each canonical Event once, retain set-based fanout and recheck enabled versions per statement. Existing shared builders retain byte-identical default output and all prior migration checksums through101. New resource check24→2 and mid-route disable regression red→green. Same-server fixed ABBA4each with two enabled versions125.600→110.060ms(-12.4%); four-version maximum127.615→109.895ms(-13.9%). Both retain59 application SQL/one physical connection; no whole-Run or page extrapolation.

Validation boundaries: expanded native96pass/2skip/3fail; v100 controls reproduce two obsolete repair-budget expectations and a real inherited100ms savepoint rollback/RELEASE error-masking hazard (fixed3sample control1pass/2fail). Final focused native42pass/2skip/1single-call-bootstrap expectation failure, exact case not separately baseline paired; full regression is not green. Bounded continuation in all native paired operations reaches exact queue frontier. No legacy fixtures/budgets or unrelated source changed. Clean tracked-source makecheck passes Ruff/mypy1284/size3097/eval30/standalone progress faults. Maintenance cleanup remains a separately scoped follow-up.

Local zero-active-intent guard, exact previous-function check and standard additive migration102 complete; source-only APIcfc1dcf8/Worker3cb401d3 healthy/zero restarts.88source fingerprints/originalsixCompose/env/entrypoint/commands/search verified; both services recreated intentionally for matching catalog. Actual Workerlibpq18 preserves two transactions/one physical socket/reset/close. No models/historicalRun replay/source rewrites/push/npm/remote deployment. Local integration preserves27 unrelated primary dirty entries. Whole-systemSQL80/page-first-body/STOP/GC/multiworker remainOPEN. See docs/CLOUD_PROGRESS_ROUNDTRIP.md; private receipts .artifacts/progress-roundtrip-20261016.


### 2026-10-16 PROJECTION-REPAIR-CLEANUP-01

Fixed the shared PostgreSQL repair exception path: RELEASE occurs only after a successful header; failed savepoint recovery rethrows the original deadline with cleanup cause and aborts the transaction, never acknowledges its unconfirmed prefix. Successful rollback still preserves completed headers. Inspected both other native savepoint users; replay-header cleanup already preserves primary failure and command preflight has no matching unconditional finally. Existing private bounded SQL adapter moved byte-identically to projection_work_io.py to respect near-limit rules (main module476lines); no new abstraction and original import alias retained.

Six no-framework forced faults pass (four red against old source); four isolated actual-transaction/cancellation cases prove confirmed-prefix versus full-page rollback and exact cold resume, three canonical Events unchanged.47 focused existing checks pass with5explicitlydeselected old budget/single-call expectations. Expanded run interrupted at102pass/5deselected because an orphan-ledger case stalled; unclassified, not marked a proved inherited defect, no fixture repair or full-suite pass. One disposable-server startup failure retained; final native4checks pass after the class move. Final clean tracked-source makecheck/Ruff/mypy1285/size3099/eval30/standalone progress faults pass. Eight native response/commentary samples retain59SQL/onephysicalconnection (current medians103.775/106.580ms, not a new paired gain).

Worker-only source overlayb24807f5 activated after zero-active-intent guard; healthy/zero restarts,89sourcefingerprints/originalsixCompose/env/entrypoints/commands/search verified. APIcfc1dcf8 exactimage/start unchanged. Actual Worker6cleanup checks and libpq18 read-only two-transactions/one-socket/reset/close pass. Original100ms/2s/fresh authority/STOP/v2/high unchanged. No model, historical Run replay, schema/event rewrite, push/npm/remote deployment; local integration preserves27 unrelated primary dirty entries. OverallSQL80/page-first-body/STOP/GC/multiworker and old test expectations remainOPEN. See docs/CLOUD_PROJECTION_REPAIR_CLEANUP.md and private .artifacts/projection-repair-cleanup-20261016 receipts.


### 2026-10-16 CURRENT-PAGE-RETENTION-01

Returned to actual authenticated Trench searches after storage/cleanup slices: fixed2new Flash/high/v2 Runs complete,11models,16tool attempts(15success/1gateway_unavailable), allretry0. Firstprocess4.710/5.390s vs substantive38.056/55.449s; Host42.343/60.275s. Startup403SQL/53TaskIO borrows/44open attempts each; full activeWorker3577/4630SQL is differing work, not normalized/system reduction. ExclusiveWorker residual12.655/10.997s remains, including progress3.756/3.502s andcanonicalappend3.768/3.629s. Cohort does not pass10s body SLA or prove wholeSQL80%.

Found and fixed a generic source-evidence loss: actual GitHub relative-time carries full UTC date but old parser drops attributes, and A2 explicitly fetches another official release-note file to recover the omitted year. Ten-line shared web_content change uses stdlib date/datetime parsing to retain only visible typed evidence, preserving date-only precision, ignored/hidden/main and byte bounds. New no-framework check red→green,20existing content/transport checks/defaultclean-source makecheck(Ruff/mypy1285/size3100/eval30/progressfaults) pass. Same exact capturedHTML now keeps full source timestamp in ToolOutputProjector preview; actual Worker produces identical preview hash. No forced tool choice, provider/effort downgrade, cache/retry/dependency/Port/schema or post-fix model retry; no new page speedup/SQL reduction claimed. Two initial check commands referenced nonexistent optional test files and ran no cases, then corrected to existing20-case suite; no fixture changes.

Temporary trace launchers removed and original normal images restored; Worker-only parser overlay8b8e16a6 healthy/zero restarts,89source fingerprints/originalsixCompose/env/entrypoint/commands/search retained. APIcfc1dcf8 post-restoration start unchanged by overlay (API did restart for diagnostics earlier). DOM observers/listeners/download element removed; pre-fix cohort A2 JPEG retained. Local integration preserves27unrelated primary dirty entries. No oldRun replay, manualappDBrepair, push/npm/remotedeploy. Overall page/SQL80/STOP/GC/multiworker gates remainOPEN; docs/CLOUD_CURRENT_PAGE_RETENTION.md and private current-page-retention-20261016 receipts.


### 2026-10-16 PROGRESS-HEADER-PLAN-01

Removed one redundant transaction-isolation SET from both single-statement PostgreSQL latest/explicit Run adapters; all canonical query/validators and multi-query/SQLite snapshots unchanged. Standalone native check red2→green1;22native freshness/snapshot/identity/cancel/head-race/fence/commentary +34local checks pass,7optional native skips. Currentv102 enabled-projector fixed ABBA4each operation SQL59→56(-5.1%),physical1retained; two-projector median127.975→121.865ms(-4.8%),four126.525→122.530ms(-3.2%). Small local operation gain, no real-page/wholeRun claim. Metadata plan rewrites and plan-preserving reset probes rejected for no stable/meaningful gains; DISCARD ALL stays. Two private query prototypes had syntax/reference errors and an initial counter missed Cursor before correction; no production impact/fixture repair.

Cleantracked-source makecheck passes Ruff/mypy1285/size3101/eval30 and existing progressfault gates; new script line-length fixed. Idle-guarded source-only API7eb869c9/Worker120509bc updated,healthy/zero restarts; both actual adapters pass no-write count/source-rejection checks,92sourcefingerprints/originalsixCompose/env/commands/search retained. Both services intentionally restart, no migration. LocalFF preserves27unrelateddirtyentries; no model/historicalRun replay/cache/dependency/push/npm/remotedeploy. Platform11–13s residual and overallSQL80/page/STOP/GC/multiworker remainOPEN. See docs/CLOUD_PROGRESS_HEADER_PLAN.md, private .artifacts/progress-header-plan-20261016.


### 2026-10-16 RUN-BOUNDED-SOCKETS-01

Cloud execution's existing shared stale-retry entry now explicitly owns the existing bounded socket scope for one attempt; each callback retains a fresh original2s budget, separate transactions/fullDISCARD/freshauthority/STOP/canonical checks. No local/ordinary pool/coverage scope change, global pool, Port or dependency.4sequential publications currentv102 fixedABBA4each:physical4→1(-75%),explicitSQL224unchanged;3emptyhealthrequests make totaldrivercalls224→227(+1.3%). Final medians twoProjectors393.115→375.910ms(-4.4%),four505.455→376.840ms(-25.4%). Earlier pre-health510.230→413.640/510.355→388.420ms retained separately; no page/wholeRun claim.

Own-idle-backend termination exposed a real new-lifetime risk; directnativeinput/status probe failed and was removed. Installed ConnectionPool.check_connection empty helper checks once after renewing the nextcallbackbudget, can reopen only before any business SQL; unknownCOMMIT/applicationSQL never auto-replayed. Standalone red→green covers ownership/budgets/reset/8idle/EOF/cleanup/cloud-local entry; real expiredfence/newRun controls preserve canonical source.23native +30execution tests pass, final23native rerun pass; new script Ruff imports/closure findings fixed, no fixture repair. Cleantracked-source makecheck/Ruff/mypy1285/size3102/eval30/progressfaults pass.

Guarded source-only Workerce680c30 healthy/zero restarts;93sourcefingerprints/originalsixCompose/env/commands/search retained,API7eb869c9 exactimage/start unchanged. Actual Workerlibpq18 no-model shared-entry stub/native-read probe:2callbacks/1socket/firstbudgetexpirythenfreshbudget/reset/close-at-attempt-exit. LocalFF preserves27unrelateddirtyentries, no model/historicalRun replay/schema/push/npm/remotedeploy. Up to8idleDBsessions retained per attempt until exit; capacity/GC/multiworker separateOPEN. OverallSQL80/page-first-body/STOP/revocation/takeover/Redis faults remainOPEN. Docs CLOUD_RUN_BOUNDED_SOCKETS.md; private .artifacts/run-bounded-sockets-20261016.


### 2026-10-16 RUN-SOCKETS-PAGE-PAIR-01

Fixed authenticated network-search ABBA4 (A d48912c4 / B9f154b25), Flash/high/transient_v2 retained. Four completed/17model calls/22successful tools, no provider retries; A2 extra official date check and second candidate retained. Body21.413/25.683/21.265/38.938s, Host25.477/30.308/25.497/48.577s. Rawmeans body-22.2%/Host-24.6% are unequal work, not proved causal improvement or10sSLA. Click→provider3.508→2.439s,Workerstartup1.091→0.422s; startup boundedopens44→5, nonemptySQL378→415. FullWorker mean nonemptySQL3010→2973.5(-1.2%),all execute includingemptyhealth3029→3118(+2.9%); no whole-systemSQL80claim. API scopedSQL/timewindow boundary and model/tool differences explicitly documented.

ExactoptimizednormalAPI7eb869c9/Workerce680c30 restored after idle guard; healthy/zeroRestarts/93sourcehashes/originalsixCompose/env/entrypoints/commands/search verified. Temporaryobserver/APIinterface prep failure retained; B2/A2 failedJSONdownloads recovered from retainedCDP timing/prefixes, no model replay. DOM listeners removed, originalB2result readable/high retained. Docs-only slice; no production/testfixture edits, unrelated cleanup, push or remote deployment. See docs/CLOUD_RUN_SOCKETS_PAGE_PAIR.md; private .artifacts/run-sockets-page-pair-20261016 (runnable summarize.py).


### 2026-10-16 SEARCH-BODY-CRITICAL-01

Existing21–26s body attribution: provider8.079/8.158s,toolunion12.749/8.571s,other4.856/4.536s (includes2.44s startup). Six current native samples expose repeatedFakeIPDoH in unusedpreflight andactualpinnedconnect; preflight429–1015ms. Remove onlyredundant prelookup at sharedproxyhelper, preserve connectionfreshness/publicallIP/pin/TLS/redirect/cancel/deadline and policyerror classification acrossfetch/search/search_json. Standalone red4→green2DNS over2freshrequests,6private/mixedcases/hostTLS; focused149pass/1compatmessage failure corrected, originalcasegreen; cleantrackedsource makecheck/Ruff/mypy1285/size3103/eval30/progressfaults pass, nofixture edits. Native fixed8ABBA all200/samehash,PGmedian2.351→1.755s/Redis2.493→1.383s,DoH2→1, varyingnetwork/no stablep50 claim.

FixedrealpageABBA4 Flash/high/v2 allcompleted/15modelreceiptsretry0/21toolattempts20success. B2 officialreleaseURL302 rejected andretained, no correctionmodelretry. Body15.543/15.960/24.295/21.790s,Host19.004/19.810/28.454/25.271s; meansbody+7.8%/Host+9.0%, no page netgain proven. Differingwork5models/7toolattemptsB2 vs3/4A1/B1; actualfetchDoH2→1 acrosspages confirmslocalfix. Workerexecute2753→2977.5(+8.2%), noSQLgain; startup448execute/5opens retained. Newpair replaces historicalcomparison; no favorable extrasamples. CompactCDPtimings/canonicalidentity checks retained; initialdisabledsend callednomodel, legacydownloadcollector staleA1 overwritten then corrected, screenshotdownloadblocked andsaved through oneclosedloopbackreceiver.

NormalAPI7eb869c9/Worker435867aa restored/updated (postpair onlysamefilecomment refinement from60052f35), healthy/zeroRestarts/95sourcehashes/originalsixCompose/env/entrypoint/commands/searchchecked; actualWorkerstandaloneboundary passes. API restartedfordiagnostics/restoration, not subsequentWorkeroverlay. DOMlisteners/temporaryanchor/receiver removed; normalB2result/high readable. Only3productionsources+1standalonecheck; docs CLOUD_SEARCH_BODY_CRITICAL.md/private search-body-critical-20261016. Localcloud-agent-trench integration preserves27unrelateddirtyentries; no source/fixturecleanup, oldRunreplay, schema/push/npm/remotedeploy. Full10sbody/SQL80/STOP/GC/multiworkergates remainOPEN.


### 2026-10-16 SEARCH-EVIDENCE-RECOVERY-01

Claimed focused task atfab4a5eb before implementation. Actual source HTML loses anchorhrefs in sharedprojection, forcing rediscovery/guessedPGrelease302; no literalduplicate URL/query in inspectedRuns. Retain admittedvisible HTTPS links relative to actualrequest and existingevidence_refs (collectedaddress, nottargetcontentverified), unknowncitations stillreject/coregateunchanged. ProposalB2 revealed metadataadoptionbug causing5433ms candidate rewrite; samecapturedcandidate deterministic check failsbefore/passesafter. Added defaultemptytuple propagation through siblingHTTPFetchProvider/CrawlGateway; nativeWEB_PIPELINE_V2 unchanged/off,streamtransient_v2 on, Agent chooses tools/highretained. Fiveproductionsources/one runnable no-networkcheck; no automaticretry/redirect/dedupe/cache/promptchange/dependency.

InitialfixedABBA4 allcompleted butunfavorable retained; finalfixedA3/B3 aftermetadatafix body21.584→25.890s/Host25.770→29.719s/models4→5/toolattempts5→7. Beforebody Provider8.617→12.726s/toolunion8.710→7.727s/other4.258→5.437s. BothfinalRuns Yahoo upstream_error; B3GAsearch dispatchedconcurrentlybeforewhatsnewlinkreturns. No provedpage orSQLgain; Worker nonempty2875→3505/all execute3022→3629/API1291→1528 underexplicitscopeboundary, notsystemtotal. Startup448execute/5opens retained, B3citationrefs propagated/onecandidate.

212focusedtests/defaultcleantrackedmakecheck pass; firstrealTLSlistenerfailure then originalcasepass/full212rerun, nofixturefix. Standalonelink/ledger/nativeSQLitegatewaycheck red→green and actualWorkerpass; earlier226network/33citationchecksretained. SixactualpageRuns only, no favorableextrasamples/modelreplay; completeDOM/canonical/nativeSQL receipts retained. IdleguardednormalAPI7eb869c9/Workera65cfdfe healthy/zeroRestarts,98sourcehashes/originalsixCompose/env/entrypoints/commands/searchverified; APIrestartfordiagnostics/restoration acknowledged, finalWorkeroverlay APIstartunchanged. Temporarylaunchers/listeners/receiversclosed,originalB3readable/highretained. Localcloud-agent-trenchFF preserves27unrelateddirtyentries; no schema/historicalEventrewrites/fixtureexpansion/push/npm/remotedeploy. Broad10sfirstbody/systemSQL80/STOP/GC/multiworkerremainOPEN. See docs/CLOUD_SEARCH_EVIDENCE_RECOVERY.md, private .artifacts/search-evidence-recovery-20261016.


### 2026-10-16 YAHOO-SEARCH-RECOVERY-01

Trace/source confirms Yahoo HTTPError loggedstatus0 is actualinvalidresponse, notcurlcode; installedNetwork returneditwithoutnativeinvalidstatusrecovery. Yahoo-only retries1/retry_on_http_error[0] reusesexistingclientclose/retry, no newretryloop/toolroute/protocol/TLSchange. Native0→200 red→green, persistent0/403/429/CAPTCHA failclosed; broaderinstalledRequestExceptionretry/specialdisconnectbehavior documented, budgetsnotwidened. Twelveactualnativecanariesallpassed; zeroHTTPexternaltrigger not reproduced, noproxylibrarycausalclaim.

FourrealpageRuns high/Flash/v2/Agentautonomous retained,20modelreceiptsretry0. B1twoYahoo5stimeouts thenallowed!bing/officialfetch exposedactualsourceURLs displacedbysorted128hrefinventory; samecapturedfirst/finalcandidate failbefore/passafterunknownstillreject. Sharedledger12lineboundedsourcepriority/forgedauxintersectionguard andstandalonefloodregression red→green; no qualityweakening/capraise/schema/Port. FirstA1/B1proposalcohort retained includingB1blocked, finalB2/A2 body29.446/59.663s/Host32.542/64.597s/models4/7/tools6/10;Worker nonempty3228/5284/API1377/2242. Observed50percentgap isunequalfailures/work, not stablecausalbenefit. A2fetch10.361sdeadline/404/308; B2twoYahoo failures andcold307trackinghopsremainOPEN. Pausefeedbackneedsrawresponse/timeevidence, not speculativefix.

39search/config+75ledger/quality/recoveryfocused (overlap)/defaultcleanmakecheck pass; wrongtestpath/newscriptlintcorrected, nofixtureexpansion. B2afterguardnative6receipt replay yieldsidenticalmetadata; noextraactualRun beyondfour. IdleguardednormalAPI7eb869c9/Worker38c42ab1/search245b675f composition updated/restored,99sourcehashes/exactYahooconfig/originalenv/commandsverified; diagnosticAPI/searchrestartsacknowledged. Temporarylaunchers/sitecustomizemount/DOMlisteners/ownisolatedcontaineranonymousvolumes/loopbackremoved. Localcloud-agent-trenchintegrationpreserves27unrelateddirtyentries, noDBrepair/historicalRunreplay/push/npm/remotedeploy. Wholebody10s/SQL80/STOP/capacity/GC/multiworkergatesOPEN. Docs CLOUD_YAHOO_SEARCH_RECOVERY.md, private yahoo-search-recovery-20261016.


## 2026-10-17 - YAHOO-COLD-READY-01

Yahoo installed EngineCache used /tmp while existing cache volume stayed empty.
One TMPDIR env reuses native SQLite/expiry in existing volume across recreation;
empty/expired/rejected YBV can still redirect. Shared paused JSON now accurately
reports not_executed only all bounded paused/no results, retryfalse/no invented
5s countdown; read-only search failure no longer suggests argument repair.
Native fresh/recreated controls and paused10.56ms/no-upstream proof pass; focused68
and standalone check pass. Fixed four actual page Runs all completed/high/Flash/v2.
Docker maxdepth before B1 model required exact-filesystem flatten124→2/config and69
Worker hashes preserved; final comparable B2/A2 body28.875/18.373s,Host37.317/21.254s,
models5/3, tools7/4 includingB2 one404 and2candidates. YahooHTTP4/6, redirects2/4,
but B2 cache hit still reinitialized; SQL Worker+API nonempty5185/3360. No end-to-end
speed/SQL reduction proved; no favorable extra samples. Startup5opens/448execute
(33empty) retained. Paused model behavior not exercised on page. Details and limits
in docs/CLOUD_YAHOO_COLD_READY.md. Normal local activation/source/gate closeout follows;
no push/remote deploy or unrelated fixture changes.

YAHOO-COLD-READY-01 closeout: clean default make check passed; local integration preserves27 unrelateddirtyentries. Normal Worker e03f72cacd5a/API7eb869c9/Search245b675f healthy/zero-restart, original6Compose/commands/env(exceptTMPDIR) and101sourcehashes verified. Actual normalWorker standalone pausecheck passes; diagnosticlaunchers/mounts/listeners/receiver removed. No push/remotedeploy.


## 2026-10-17 - SOURCE-CANDIDATE-ROUNDTRIP-01

PriorB2's extra candidate4745ms was a false citation rejection: successful PG
release-notes reference evicted by bounded128 inventory. Final gate now prioritizes
candidate-cited explicit refs from current in-memory successful tool events within
same128; no historical receipts/plain-text promotion/SQL/model retry added.
Generic model guidance matches product/edition/version, exact observed URL and
named evidence gaps; no forced tool route. PriorB2's guessed Redis website path
from GitHub caused404; enterprise source was optional, GA date fetch was necessary.
Original B2 receipt/candidate pure recheck now passes, unknown stillrejects.

Fixed four pageRuns high/Flash/v2 allcompleted/13modelsretry0/no404/onecandidateeach.
B1 early conversation-based recovery tightened to current events before B2; retain
all four, finalcomparison B2/A2only: body17.059/16.054s,Host19.799/18.546s,
models3/3,tools4/4,nonemptyWorker+APISQL3294/3314. No stableoveralllatencygain proved;
B1stillautonomouslyfetched4pages. Initial5opens/448execute(33empty) retained.
Focused66/standalone/defaultcleanmakecheck passed. Docs CLOUD_SOURCE_CANDIDATE_ROUNDTRIP.md;
localnormalactivation/sourceproof pendingcloseout, no unrelatedfixture/push/remotedeploy.

SOURCE-CANDIDATE-ROUNDTRIP-01 closeout: localcloud-agent-trench integrated/preserved27dirtyentries; normalWorker5fdb3e0d119b/API7eb869c9/Search245b675f healthy/zero-restart/original6Compose-env-commands and103sourcehashes verified. ActualnormalWorker standalonepasses. Diagnosticentrypoints/sitecustomize/DOMlisteners/receiver removed; no fifthRun/push/remotedeploy.


## 2026-10-17 - SEARCH-START-TOOL-WAIT-01

Measured16–17s firstbody: previousfinalpair provider5.2–5.9s/tools6.0–6.6s/other4.2–5.3s.
PreWorkeradmission1.97–2.82s, scopedWorker→model0.40–0.58s, no sandboxprovision;
largest avoidable fetch stage was RedisGA HTML1692922decodedbytes/body1.96–2.71s.
One existingHTTPAccept header now prefers text/markdown, originalformatsremainq0.9;
native sameURL16036bytes/date/featuresretained, no URLrewrite/newparser/dependency/
fallbackrequest/securitychange. ActualpageRedisbody864.5/2232.9ms(A)→2.25/0.86ms(B),
completefetch2.987/3.820s→1.706/1.518s. PGHTMLfallbackretained.

Fixed4ABBA pages allcompleted/high/Flash/v2/14modelretry0/20toolsuccess/onecandidateeach.
A1/B1/B2/A2 body26.541/15.157/16.558/19.755s,Host31.861/18.442/19.965/23.933s,
nonemptyWorker+APISQL4757/3274/3255/4136. Aextraquery/modelworkmeans raw31.5percent
body/26.6percentSQLmean gaps not stablecausalgains. Startupmeans2.724/2.798s unchanged,
5opens/448execute33empty retained. Focused134/standalone/defaultcleanmakecheck pass;
finaldocs onlytargeteddiff/sizegate, no repeatedbroadtest. Details CLOUD_SEARCH_START_TOOL_WAIT.md.
Normal localactivation/sourceproof pendingcloseout; preserve primary27dirtyentries,
no Trenchproductcode/unrelatedfixture/push/remotedeploy.

SEARCH-START-TOOL-WAIT-01 closeout: localcloud-agent-trench integrated/preserved27dirtyentries; normalWorker1a2270dfbf0b/API7eb869c9/Search245b675f healthy/zero-restart/original6Compose-env-commands and103sourcehashes verified. ActualnormalWorker standalone negotiationcheck passes; diagnosticentrypoints/mounts/DOMlisteners/receiver removed, no fifthRun/push/remotedeploy.

### CLOUD-SDK-ADMISSION-01 / 2026-10-17

- 2.3–3.3 秒启动继续按真实 Host → Cloud 请求图拆解；仅合并开 client session 与已有挂载/绑定。
- 通用 Cloud API 及 SDK 显式能力协商；新鲜 Host/目标/profile/credential/fence 校验保留。
- Trench 仅协议传输接线，业务/恢复/模型设置不改；Worker/Search 已验收实现保持。
- 四轮 completed/high/Flash/v2；局部 2→1 请求、36→30 SQL、233→180ms；整体启动稳定收益未证实。
- 正常服务与 103 指纹恢复通过，Worker/Search 不变；详细口径见 `docs/CLOUD_SDK_ADMISSION.md`。

### CLOUD-START-TRANSPORT-01 / 2026-10-17

定位建任务94SQL中的重复ensure索引重建，优先读取原子提交header；缺失/local仍旧路径。
准入借用现存httpx transport，每请求新鲜Grant及权限校验保留，Trench仅传输接线。
原生无模型94→73 SQL；四轮真实页面和正常服务验收见docs/CLOUD_START_TRANSPORT.md。

CLOUD-START-TRANSPORT-01验收：固定4ABBA均completed/high/Flash/v2；Task SQL94→73，前置183→162，startup非空598→577。启动样本均值2.451→2.197s，首正文19.157→18.109s，整轮22.656→23.951s，整轮收益未证实。首Cloud前主等待在入队180–220ms/调度准备235–459ms；主体校验3–8ms保留。正常API1fcd97720fade/Worker1a2270dfbf0b/Search245b675f健康、原6Compose/env/commands及104指纹复核，临时Hosthook移除；本地98d72222集成完成并保留27项脏状态；Host59773b7，未推送/远端部署。


## 2026-10-17 - CLOUD-TASK-ADMISSION-IO-01

Shared first Event coordinate/byte update and native insert-first mapping arbitration reduce
POST/tasks73→67 SQL, atomic55→49, initialindex43→37; same connection and all native
guards/authority/replay/rollback preserved. No schema/pool/dependency or Trench product change.
Native standalone red→green, focused30passed plus remainder38passed/3heavy scans deselected
(overlap); clean tracked makecheck passes, no fixture repair/full-suite claim. Fixed realABBA
allcompleted/high/Flash/v2/autonomous, 14 model responses retry0 and20successful tools.
Assignment latency45.3→44.8ms/initialindex76.1→69.0ms; no stable latency guarantee.
Firstbody19.295→17.528s and whole23.011→20.712s raw averages include model/write/connection
jitter, not6SQL causal gains. Whole SQL3742.5→3712.5 (~0.8%). API normal candidate only,
Worker/Search unchanged; original composition/health0restart/105hashes verified. Native
probes0command/0model; normalB2 result visible, receiver closed. Local integration only,
primary27unrelated dirty entries preserved; no push/npm/remotedeploy. Details in
docs/CLOUD_TASK_ADMISSION_IO.md. Broader performance and STOP/GC/scale-out gates remain open.


## 2026-10-17 - CLOUD-ADMISSION-WRITE-01

API standard Docker entrypoint now wraps unchanged Uvicorn CLI in existing bounded
postgres_pool_scope, matching Worker composition; no adapter/schema/trigger/authority
change. Source first INSERT backend initialization is reproducible; normalAPI retains
two backend PIDs across fresh-authority requests. Standalone red/green/actualimage/CLI
and56focused/1known deadline assertion deselected plus cleanmakecheck pass; nofixturefix.
4actualpage ABBA allcompleted/high/Flash/v2/autonomous,12executionmodelresponsesretry0,
16toolsuccess/singlecandidate+quality each. Body A12.844→B14.578s/whole16.208→17.863s;
no page gain claimed. SteadyHTTP controls afterpages Task177.6→122.9ms/firstINSERT
10.74→5.59ms rawmeans; nonempty67 preserved,7emptyprotocol checks added perTask.
OldA2nonindex174.8ms not reproduced or uniquely attributed; newA2SELECTGREATEST85.7ms
spike has bounded indexonly plan in controls, so no claim all jitter solved.
NormalAPI13e19eadb56d/Worker1a2270dfbf0b/Search245b675f/original6compose/env/commands
and107hashes healthy0restart verified; declaredAPIentrypoint changed intentionally.
NormalB2 result visible, no further model, receiverclosed. Localintegration only,
primary27dirtyentries preserved; no push/npm/Trenchproductchange/remotedeploy.
Details docs/CLOUD_ADMISSION_WRITE.md; historical spike and broadgates remain open.


### 2026-10-17 CLOUD-ADMISSION-SPIKE-01 — diagnostic boundary

- Correlated native server Parse/Bind/Execute and sampled waits/scheduler with raw driver timing before observer locks. Current A2 UPDATE43.402ms/server42.644ms; sampled runtime36.395ms/runqueue2.952ms, no blockers. Native UPDATE projection triggers5.107+3.478ms dominate10.808ms execution. Historical85.7/53.4ms not uniquely attributable; no justified production change or latency gain claimed.
- Four actual matched baseline search pages preserve high/Flash/v2/fresh authority/autonomous tools; body12.894–15.511s, whole16.193–22.088s,67business admission SQL unchanged. B2extra search/A2candidate revision retained.31 diagnostic Tasks have0commands/0models. Normal original API/Worker/Search/config/107sourcehashes restored; focused doc is docs/CLOUD_ADMISSION_SPIKE.md. Historical spike cause, production optimization, p95 and broader performance gates remain OPEN. No unrelated test/fixture repair, Trench change, push or remote deploy.


### 2026-10-17 CLOUD-PROJECTION-TRIGGER-01 — bounded plan reuse

- Additive v103 sets generic plans only inside two projection functions. Bodies/SQL/native guards unchanged; caller/global settings restored. Native repeated source/routing trigger averages1.666→0.705ms/3.709→0.413ms; actual page repeated coordinate UPDATE9.900→4.360ms, first-use gain not proven. No business SQL reduction: admission67+7empty/fresh authority6 unchanged.
- Fixed4realABBA completed/high/Flash/v2/autonomous,15executionresponsesretry0/19toolsuccess. Body13.598/12.397/22.121/14.537s, whole16.488/15.327/25.099/21.940s; B2extra work/A2candidate revision retained. No whole-page/p95 improvement claim. Defaultcheck/standalone+actualimagecheck pass; one historical partial-fixture repair I/O-budget case remains failing, no fixture repair. Normalv103 API/Worker/config109hashes restored,12controlTasks0commands/models. Local stage only; docs/CLOUD_PROJECTION_TRIGGER.md holds proof/limits; historical spike and broader gates remain OPEN.


## 2026-10-17 — CLOUD-SEARCH-EVIDENCE-ROUNDTRIP-01

Previous B2 extra rounds trace to broad Redis landing before targeted GA search, followed by two same-gap parallel paraphrases; final announcement fetch is necessary, initial results lacked it. Refined only shared model execution guidance (candidate suitability, source/event query terms, independent-gap parallelism); no forced tools/source, caps, cache or Trench change. Standalone wiring red→green/actualnormalWorker,12 focused tests and clean makecheck pass. Fixed4 realpageABBA allcompleted/high/Flash/v2, each3models4tools/onecandidate/retry0; bodyA13.829→B14.552s,whole17.086→18.289s,SQL3234.5→3204(-0.94%). No stable latency/SQL/round reduction proven; historical5/7 outlier is not causal baseline. All adverse results retained, no fifth modelRun. Admission67business+7empty/6freshSQL, sixstartupCloud156business, Worker448execute33empty5TaskIOopens and v103generic settings preserved. Restored originalnormalAPIeb4f695b/newWorker2a4b0ace/Search245b675f, originalconfig/env/commands/109hashes/healthy0restart verified;5HTTP201 diagnosticcontrols0commands/models, originalB2result/high read-only page verified, screenshot saved and observers/receiver removed. Localstaged integration into cloud-agent-trench preserves27dirtyentries; no remote publish/deploy. Detailed boundaries/results: docs/CLOUD_SEARCH_EVIDENCE_ROUNDTRIP.md; wider performance and repeat-prevention guarantees OPEN.

## 2026-10-15 - Web input errors and anomalous DNS repair

CLOUD-WEB-INPUT-DNS-REPAIR-01 distinguishes malformed web.search arguments from
network authorization denials. Numeric strings remain invalid; the read-only
harness observes the precise error and can correct arguments under existing
fingerprint/budget guards. Genuine denials remain fail-closed.
The shared public resolver reuses authenticated bounded DoH when DNS contains
Teredo plus otherwise public addresses; the entire answer set is replaced.
Mixed private sets remain rejected, and fallback answers must be public. This
addresses observed host DNS pollution without authorizing private targets or
changing Clash/TUN/global DNS settings. No broad arbitrary-DNS recovery claimed.
140 focused tests, Ruff and Mypy5 sources pass; baseline negative control fails
3 regressions. Local Worker98612d73 healthy/source hashes verified, native child
search5 results, CoinGecko HTTP200/price field and localhost rejection proven.
No model invocation, push or remote deployment. Isolated branch committed;
primary cloud-agent-trench source patch applied, integration commit pending.

- 2026-10-17: CLOUD-NETWORK-CHILD-REUSE-01 measured the remaining real-search first-body path. The latest live run produced first candidate public text at 13.56s and committed answer at 16.44s; parallel search/fetch waits, not SQL or serial tool dispatch, dominate. Native child import is only ~0.32–0.41s/request; repeated DoH/TLS is the larger variable cost. No speculative pooling/cache change was made because cancellation/SSRF freshness would regress; bounded guard and evidence doc added.

- 2026-10-17 CLOUD-DOH-TRANSPORT-01: Cloud gateway source now composes execution-scoped DoH transport reuse (local default unchanged), bounded two child lanes with fresh checks and kill/reap. Clean slice98tests/Mypy1289/Ruff/eval30 pass; primary combined DNS/cancel85pass. Local source integration d1b366da preserves unrelated dirty work and Teredo recovery. Native no-model follow-up median1.587→0.266s(3/4) but fullycold1.613→2.158s; cold/page stability gate remains open. Existing services unchanged; no model calls. docs/CLOUD_DOH_TRANSPORT.md records exact boundary.

- 2026-10-17 CLOUD-DOH-COLD-01: actual cold-child phases separated. OSlaunch0.2–2.9ms; stdlib/runtime imports~0.32–0.43s, SSRF package aggregate148–197ms, network TLS323–1321ms initially and up to2768ms in pairing. One production initializer now uses existing per-name lazy export pattern: SSRF preDNS133.324→1.744ms. Four fixed cold pairs only2/4 improve/batchmedian874→1912ms; no stable whole-cold/page gain. Actuallegacyweb.fetch does not hit this aggregate initialization, so no claimed page benefit.370focused+actualprimary133pass/Mypy1289/eval30. Local source b4f3abe9, all dirty work preserved, services unchanged/no model calls. docs/CLOUD_DOH_COLD.md.

- 2026-10-17 CLOUD-FETCH-TLS-01: actual fetch fixed4 pairs/32 successful website GETs+32 fresh DoH queries; follow-up batch median2887→2467ms(-14.5%,4/4), cold2823→3245ms(+14.9%,0/4). DNS+target TLS+headers dominate PG operation median90.6%; TLS CPU~1.6–2.4ms vs wall386–1066ms. Local OrbStack/Mihomo SOCKS5 forwarding observed; 1ms local TCP is not Internet RTT, no remote packet-loss attribution. No additional production change justified, no model/page gate or service activation.80 focused regressions and offline integrity check pass. Evidence/next egress-route isolation gate: docs/CLOUD_FETCH_TLS.md.

- 2026-10-17 CLOUD-EGRESS-ROUTE-01: fixed4 balanced ABC/CBA/ACB/BCA,24 successful actual fetches/24freshDNS/48coldTLS; normal local proxy median2069.9ms, proxy-carried SSH3165.4ms, process-interface direct SSH1675.0ms. Direct ready egress improves19.1%vsnormal/47.1%vssame remote via proxy,4of4; SSHsetup617ms excluded so must prebuild/reuse, not per-request. Remote-only header-matched mechanism DoH25–40ms/PG903ms retains upstream cost and runtime-version boundary. Real tunneled revoke+sibling200+2childrenreaped,80focused regressions/selfcheck/integrity pass; failed nc-idle cohort retained/rejected. Temporary tunnels/overlay removed/global proxy digest unchanged. No production connector/activation/Trench/model/page claim; focused shared numeric-IP connector plus Cloud-only composition is next gate. docs/CLOUD_EGRESS_ROUTE.md.


## 2026-10-17 — CLOUD-EGRESS-CONNECT-01

Cloud-only explicit public HTTPS/DoH connector now uses a supervised prebuilt egress; local defaults/private search/model transport unchanged, fresh authority/DNS/SSRF/TLS and request cancellation retained. No-model stable gate passed: cold−23.7%/4of4, follow-up−37.7%/3of4. Actual high/Flash/transient_v2 fixed4 page ABBA completed: first-body mean17.235→13.316s, whole20.733→15.669s; scoped SQL3611→3195.5 is observational, affected by A1 extra model/fetch. B2 first body exceeds A2; no universal or isolated page/SQL gain claim. A0 calibration instrumentation failure retained separately; five Runs total. Feature158/primary163focusedtests, Ruff/Mypy1291/eval30/size/progress gates pass. Normal local Worker9953a04d enabled with launchd-owned reusable SSH; original API/Search/envexceptnewkey/compose/entrypoints and12sourcehashes verified, observers removed, global proxy/Trench untouched. Source locally integrated only; no push/remote deployment. docs/CLOUD_EGRESS_CONNECTOR.md records exact scope, evidence and rollback.


2026-10-17 CLOUD-EGRESS-CONNECT-01 read-only follow-up: retained enabledB1/B2 firstbody mean13.316s partitions startup2.757/model-to-needed-output4.354/searchparallel2.268/fetchparallel1.624/interstage1.751/first-content-to-visible-prefix0.562s, disjoint sum verified. Provider firstevents156–248ms; finalcontent1656–2765ms, not purethinking measurements. Three model/fourtool rounds have no failed/retried/revision loop. Existing Run TaskIO scope is thread-affine; concurrent tools copy context but cannot borrow parent-thread connections. Read-only normalWorker two-thread40query index-miss probe fixed4 alternatingpairs: opens40→2,median146.2→20.0ms, allfreshreads retained; no model/auth correctness/page gain claim. Next minimal proposal: Cloud native read-tool thread-owned existing scope, fresh checks/50mscancel/deadlines/transaction reset unchanged, no core storage import/newpool/Trench change; actual tool security+critical-time gates required before activation/page. Production source/config/services unchanged; detailed evidence/bounds in docs/CLOUD_EGRESS_CONNECTOR.md.


2026-10-17 CLOUD-TOOL-THREAD-IO-01: implemented existing thread-owned Task I/O scope at Cloud native local read-tool boundary, preserving current same-thread Run scope, fresh checks/deadlines/transactions/DNS/SSRF/cancel and local/Host/client/management routes. Source74631d39 is isolated/review only. Focused resolved130pass/2skip plus two baseline-reproduced legacy PG takeover cause-assertion failures; new real STOP read on one reused connection passes. Ruff/Mypy2/size/diff pass. Fixed4 actual two-search+two-fetch no-model pairs/32executedtools: totalmedian3319.0→3059.6ms(-7.8%)but2of4wins; stability gate FAIL, no page models/normal activation/source integration. Physicalopens97–164→4 is resource benefit only; SQLtotal not captured. All unfavorable samples retained. Owned scratch credentials/role/schema/DB/overlay removed; normalWorker9953a04d/APIeb4f695b/Search245b675f/12sourcehashes/health0restart/globalproxy preserved; no Trench changes/push/deploy. Next latency boundary: inter-stage append/progress work, not favorable external resampling. docs/CLOUD_TOOL_THREAD_IO.md.


2026-10-17 CLOUD-PROGRESS-BOUNDARY-IO-01: measured retained page interstage1.75s; bounded no-model PG flow shows repeated Run metadata47%SQLwall,155drivercalls/2physicalopens. Small source e0fa56f3 on isolated branch queries fresh bound Run directly and rejects successor stop/anchor mismatch; no Port/schema/cache/deadline/canonical-write change, initial latestRun admission retained.98focusedpass, nativegroup20pass/11specialenvskips(overlap), Mypy1/Ruff/size/diff/progress safety scripts pass. Actual native-tool+progress fixed4cohort stopped on A2baseline double-search failure5626ms, concurrentYahoo timeouts; completeA1/B1/B2 boundaries578.6/515.9/511.4ms, total4149.8/5082.6/3676.8ms. One completepair is not stablegain, no SQL-count/page gain; all observed adverse samples retained and initial invalid namespace trial documented. No primary implementation integration/normal activation/model calls, no unaccepted prior thread-reuse inclusion. Own scratch resources/credential/overlay cleaned; normal Worker9953a04d/APIeb4f695b/Search245b675f/12sourcehashes/healthy0restart/globalproxy preserved; no Trench/push/deploy. docs/CLOUD_PROGRESS_BOUNDARY_IO.md records exact boundaries and closed gate.


2026-10-17 CLOUD-YAHOO-TIMEOUT-01: minimal native deadline ownership fix source2f6648c8 locally integrated7ceaeea8; pinned SearXNG wrapper now cancels its Future at engine timeout, avoiding demonstrated late native retry/orphan work. Checked-hash recompile required because base unchecked bytecode ignores source-only edit. No change to Yahoo5s/search6s, status0 recovery, YBV/parser/proxy, Cloud fresh auth/DNS/SSRF/cancel, high/v2/autonomous decisions or Trench. Original/stale-bytecode checks fail; final/live checks pass with sibling isolation; zero-status check and65focused regressions pass. Fixed4nativepairs16queries all succeed, no normal-response speed gain. Only normal Search replaced with ea7241c97288; original APIeb4f695b/Worker9953a04d/env/proxy/18unrelateddirtyhashes preserved. Fresh full4progresspairs complete16search+16fetch zero failures: boundary557.8→562.0ms,1of4wins; median total3509.2→3313.9ms,SQL520→517 notcausal. Gate FAIL: progress candidate remains unactivated, no model/page calls. Initial upstream stall's TLS-vs-header cause remains unproven; bounded successes do not guarantee Yahoo availability. Own probes/overlay/scratchrole/schema removed; ready egress retained, no push/remote deploy. Details/rollback docs/CLOUD_YAHOO_TIMEOUT.md; previous incomplete cohort retained.


2026-10-17 CLOUD-YAHOO-FIRST-REQUEST-01: reproduced5s cold search failure with native phase data: localCONNECT~2ms, firstserverTLS~2.4s/TLScomplete2.4–2.8s, one first307at4.908s and coldYBVredirect budget exhausted. Remote forwarding/TLS-flight/upstream tail dominates, exact remote hop not proven. Reject MAXAGE30 (two80sidle probes original902–1268ms vsforced1714–3965ms); retain uninstrumented startup/matched-image timeout/closed-followup adverse observations. Minimal pinned native Yahoo-only SEARXNG_YAHOO_PROXY opt-in reuses existing supervised exit; numeric-only native failure/>=2s logs, no query/body/cookie/auth leakage. Sourceef8b6dbf locally integrated000db762. Native fixed4cold2725→1614ms(-40.8%,3/4); separatefixed4cold+warm1510→1347ms(-10.8%,3/4)/1118→780ms(-30.2%,4/4),zero failures, adverse B2 retained.65focused regressions/native privacy/default-route/deadline/status0 checks and12+12actualCurl cancel-reuse pass. Exactly4realpageABBA/high/Flash/transient_v2 allcomplete/zero failedtools: body17.610/13.282/11.430/14.664s; total20.693/16.266/14.311/17.600s. Meansbody16.137→12.356s(-23.4%),whole19.147→15.289s(-20.1%); bothAautonomous4model/5tools vsB3/4 confounds puretransport attribution, noSQL gain claim. No extra calibration/model Run; whole usescanonicalcompletionforall4. Normal Search19f3942fe0f3 enabledonlynewoperatorenvkey/baseCompose; APIeb4f695b/Worker9953a04d untouched/healthy0restart; otherenv18dirtyhashes/proxydigest preserved. Managedexit retained; owncontainers/override/DOMobserver/binding/receiver cleaned; B2 read-only page retained. No Trench/SDK changes, unaccepted progress/threadsource activation, push or remote deploy. Upstream zero-timeout guarantee remains impossible from bounded evidence; docs/CLOUD_YAHOO_FIRST_REQUEST.md records limits/reproduction/rollback.


2026-10-17 CLOUD-SEARCH-CRITICAL-PATH-01: retained enabled B1/B2 disjoint body13.282/11.430s: startup2.492/2.261, model pre-candidate2.500/2.214, search2.767/2.386, fetch2.013/1.736, candidate-to-visible2.797/1.931, handoffs0.714/0.902. Shared model client/cache already effective; no redundant round demonstrated. Native accepted Worker2batches8successful read tools: search1.259/1.168s, fetch1.555/1.291s, PG projection4.5–4.7ms; callbacks count only, not auth proof. Two new same-config high/Flash/v2 Runs complete: R1 4models/5tools/Run19.653s, DOM timing missing due observer escape error retained/no replacement; R2 3models/4tools/body12.844s/whole16.717s. R1 extra search closes genuinely missing Redis GA source, not an invalid duplicate. No new candidate/performance improvement/SQL reduction claimed; first-body A/B gate remains open. No production edits/restart/config/globalproxy/Trench changes, unaccepted progress/thread activation or broad test repairs. Offline reconciliation script/Ruff/diff pass; own DOM/binding/receiver cleaned. Recommend next isolate generic Cloud pre-model2.26–3.06s; DoH TLS speculative prewarm has only ~0.1s+connect ceiling and unproven value. docs/CLOUD_SEARCH_CRITICAL_PATH.md records exact limits.


2026-10-17 CLOUD-START-ADMISSION-REUSE-01: Cloud client_surface reuses existing bounded request-owned PG scope (one production API file, fresh reads/commits/reset/deadlines/partial failures retained). Source9451985c; exact accepted Worker task_io/connection_scope dependency bytes also aligned into older API, identical in A/B. Nativefixed4 median196.4→64.8ms(-67%,4/4),physical14→1,17nonresetSQLsame+14resets; gatepass. Focused72pass/10skip/1oldfixture teardown privilege error retained/ownedDBcleaned, finalnew5nativepass, Ruff/targetMypy/nativeactualAPIreuse+deadline+recoverypass. Exactly4realpageABBA/high/Flash/transient_v2/zero retries or failedtools: Clientmean193.9→102.5ms(-47.1%),physical20→4; startupHTTPmean2497.5→2119.4ms(-15.1%,not fully causal). Body12.795→15.479s(+21.0%),whole16.153→18.531s(+14.7%); B1自主5models8tools vsothers3/4, adverse sample retained/no fifth Run. No stable body/whole benefit claimed. StartupAPIbusiness156+13empty unchanged,17extra resetSQL/TaskIOopens43→27,Worker448 unchanged; not SQL reduction. NormalAPIca0a85f2/Worker9953a04d/Search19f3942f/originalentries/env/healthy0restart/sourcehashes verified; no Trench/globalproxy/unsupported progress/thread integration/push/deploy. OwnDB/role/credential/DOM/receiver cleared; B2 reloaded read-only. docs/CLOUD_START_ADMISSION_REUSE.md.

## 2026-10-17 - B1 extra research attribution

CLOUD-B1-EVIDENCE-AUDIT-01 traced startup cohort B1 extra2models/4tools to
Redis landing-page detour and overlapping GA recovery search/version-doc fetch.
One recovery search was necessary because initial candidates lacked GA source;
three calls low-value/overlapping in hindsight, no exact duplicate execution.
B1vsB2 firstbody+4.297s primarily earlier-model envelopes+2.896/fetchunion+1.377s;
startup+0.132s, finalcandidate interval-1.331s. Existing offline checker reconciles
all4retained high/Flash/v2 completed pages, zero toolsfailed/Providerretry. Actual
Worker guidance already covers source selection/independent gaps/stop; no shared
result-loss/replay defect found. No production edit/new model cohort/SQL claim;
new candidate A/B remains unperformed rather than relabel unchanged reruns as gain.
Normal APIca0a85f2/Worker9953a04d/Search19f3942f retained. docs/CLOUD_B1_EVIDENCE_AUDIT.md.

## 2026-10-17 - Factual lookup versus operation stopping contract

CLOUD-SEARCH-DECISION-01 reproduces a hard conflict: “核对…首次发布” becomes
operate/result_verified, forcing2models/1fetch after first candidate then
verification_required. Shared inference recognizes lookups; explicit compound
actions/Host override still verify. No autonomy/tool/authority/Trench change.
7lookup/11action check/64existingfocusedpass/Ruff/mypy/image smoke. Accepted-base
normal Worker9e1a5f95 overlays only task_contracts.py; APIca0/Search19f/env preserved.
Exactly3varied high/Flash/v2pagepairs: Node7models8tools/pause32.962s→4/7/complete
20.395s, postcandidate forced2models1fetch→0/0. Python slower7.750→9.664s retained;
SQLite faster but unchanged contract, not patch causality. No general speedup/SQL
claim. B1 source choice/artifact range inefficiency remain. docs/CLOUD_SEARCH_DECISION.md.

## 2026-10-17 - Reject source-choice checklist without stable gain

CLOUD-SOURCE-DECISION-CHECK-01 runs fixed4realpage pairs/high/Flash/transient_v2.
Checklist candidate13→14models/14→15tools/medianbody12.466→13.040s; no source
promotion. Original B1 initial bad search result not reproduced; public commentary
does not establish internal model cause. Normal Worker9e1a5f95 restored, prior
classification/egress/connection work preserved. Two original public candidates
(SQLiteB2/PG-A4) independently reproduce false URL citations caused by Chinese
right parenthesis; separate minimal delimiter repair warranted. No broad prompt/
tool control, authority/Trench change, SQL reduction or generalized speedup claim.

## 2026-10-17 - Preserve exact targets while repairing citation prose boundaries

CLOUD-CITATION-DELIMITER-01 corrects false invented-URL rejection on Chinese
parenthesized prose. Original regex retained; explicit Markdown/angle/quoted
destinations remain exact, including invalid annotation targets. Three real
unchanged public candidates pass replay; standalone negatives/64regressions/
Ruff/mypy/image smoke pass. Preliminary one-sided fix and rejected blanket regex
excluded; failed-image activation rolled back before model traffic. Final normal
Workerd246fa25 overlays onlyquality_gates.py on9e1a5f95, original guidance/API/
Search/env/authority/high/v2 intact. Final2pages3models each,one candidate; SQLite
body12.262s/whole14.494s,PGRedis12.386/15.725s. No stable body/SQL speedup; old B1
semantic source detour remains open. Exactly11newRuns across prompt+quality
experiments,37canonical model responses/38successfultools, no replacement.


## 2026-10-17 - Fixed-evidence B1 source decisions, no speculative promotion

CLOUD-SOURCE-REPLAY-01 retains the actual original B1 public search/fetch evidence
and compares original, capability-description-only and lossless-result-layout
next decisions.24valid native high/Flash completions,4checkpoints/2repetitions;
A/D12tool proposals each,R11, no tools executed. All6complete-evidence probes
stop; all6GA-candidate probes still fetch GA+docs. Structured fields influence
initial source selection but no stable generic benefit proven; no production
prompt/formatter change or new page cohort. Replay-only missing synthetic
reasoning field caused26pre-generation400rejections, retained separately, then
corrected without retrieving private reasoning. Normal accepted APIca0/Worker
d246/Search19f/env/restarts and fresh authority/DNS/SSRF/cancel/high/v2 unchanged.
Offline focused checks/Ruff pass; no unrelated tests/Trench edits,SQL or speedup
claim. Diagnostic script and report retained; docs/CLOUD_SOURCE_REPLAY.md.


## 2026-10-17 - Diverse fixed-result replay rejects formatter promotion

CLOUD-SOURCE-REPLAY-DIVERSE-01 extends the existing diagnostic to three actual
Python/Node/SQLite page questions, two public-evidence checkpoints and four
repetitions.48valid native high/Flash decisions, original text versus lossless
orderedJSON; identical tool definitions/guidance, no tools executed.24pairs all
tie, proposedtools28→28. Python version-specific document selection improves
2/4→4/4 but still fetches overlapping documents4/4. SQLite correctly recovers
missing正文 and stops in both arms; Node continues first-release corroboration
and unobserved URL proposals11→12. No stable generic gain; gateFAIL, no source
promotion or page cohort. Input tokens+3.25%, no SQL/body/whole-turn speedup claim.
New/old offline checks andRuff pass; accepted normal API/Worker/Search/env/restarts
and fresh authorization/DNS/SSRF/cancel/high/v2 remain unchanged. Report
docs/CLOUD_SOURCE_REPLAY_DIVERSE.md; no Trench/proxy/unrelated fixture edits.


## 2026-10-17 - Correct replay public-state loss before source optimizations

CLOUD-SOURCE-PROVENANCE-AUDIT-01 stops structured-result experimentation. Complete
Node metadata refs confirm proposed paths were not observed; authorization and
provenance are different contracts. Found diagnostic reconstruction fault: extra
standalone acknowledgement and missing original public verified batch note. Real
NodeA3 already completed afterLTS; native loop/serialization/resume retains notes.
Correct shared replay and add one offline native-pairing/wire check; append prior
report fidelity correction.16frozen L/C calls: NodepostLTS4proposals→0/2answers,
initial4→4,Python/SQLite bothstop.4factor probes show neither public-content-only
nor topology-only fixes alone reproduced correctedstop; preserve interaction and
small-sample limits.20valid high/Flash model responses, no tools/retries/Runwrites.
No production gain claimed; original real B1 detour/overlap remains unresolved.
Normal images/env/restarts/freshauthority/DNS/SSRF/cancel/high/v2 preserved, no
Trench changes/page cohort. docs/CLOUD_SOURCE_PROVENANCE_AUDIT.md.


## 2026-10-17 - Original B1 batching/recall hypotheses bounded and rejected

Faithful original B1,24high/Flash decisions: deleting duplicate acceptance batch
sentence leaves18→18proposals and extra corroboration intact; gateFAIL. No source
change. Current raw Yahoo widequery still lacks GA across all7results, not just
top5;24native zh-CN/all comparisons have identical top5URLorders12/12. No locale
or cap change justified. No test-framework extension, source/Trench/auth/v2 change
or performanceclaim. Details docs/CLOUD_B1_BATCH_BOUNDARY.md.


## 2026-10-17 - Existing Pro profile does not qualify as B1 latency fix

Native identical-message B1 comparison12calls/high/auto: Flash11/Pro9proposals,
but first-source detour0/2→1/2 and medianmodel1409.6→2806.1ms. Optional parallel
corroboration reduced, not a measured model-round/body/SQL saving. GateFAIL; no
defaultmodel/router/production changes. Current investigation36modelresponses
and30nativequeries total, no executed proposedtools/test-framework expansion.
First-query event recall and semantic gap selection remain the unresolved target;
no validated generic small production fix claimed. Normal images/env/auth/DNS/
SSRF/cancel/high/v2/Trench preserved. docs/CLOUD_B1_DECISION_PROFILE.md.


## 2026-10-17 — Optional official Brave Search API prepared

CLOUD-BRAVE-OPTIONAL-01 adds an offline private-settings preparer and explicit
Compose settings-mount override for the pinned native braveapi engine. Yahoo
remains the only default, including in the optional configuration; Brave is
explicit !brapi only. No default startup, image, runtime authority/DNS/SSRF/cancel,
high/transient_v2, prompts or Trench changes. Network-disabled pinned-image
checks and Compose configuration comparison pass; no real credential, upstream
query, model call or running-service replacement. Actual recall/latency/page
acceptance waits for credentials. See docs/CLOUD_BRAVE_OPTIONAL.md.


## 2026-10-17 — Brave cancelled; keyless retrieval takes priority

User cancelled Brave then explicitly prioritized no-key alternatives. Remove
unused Brave preparer/check/Compose overlay; retain cancellation history and
any private operator files. Yahoo default settings/Compose/Dockerfile unchanged;
no service restart or API/provider/model requests. Read-only pinned source shows
Google already uses XML and DDG HTML is distinct from challenge-handling Web;
qualify only a genuinely different transport/interface before any activation.
Serper/Exa/Tavily require keys despite free offers, so are deferred. No promise
of recall/latency gain; bounded plan docs/CLOUD_SEARCH_ALTERNATIVES.md.


## 2026-10-17 — Keyless native search screen: no promotion

CLOUD-KEYLESS-RECALL-01 tested pinned Google XML and native DDG HTML POST on
existing controlled egress, distinct from prior proxy/raw GET failures. Four
fixed first queries: Yahoo official targets3/4 versus DDG2/4; Google403 stops
after1. One predeclared DDG all-region contrast then CAPTCHA on first request,
stopped. Total10native search requests, no models/retries/pages. DDG faster in
small fixed-order screen but weaker source recall; no stable benefit or SQL
claim. Yahoo default/normal containers/source unchanged, candidate removed.
Evidence and qualification boundaries docs/CLOUD_KEYLESS_RECALL.md.


## 2026-10-17 — New keyless provider screen: useful Exa recall, rate-limit gate fails

CLOUD-KEYLESS-PROVIDER-02 confirms official hosted Exa MCP anonymous access,
distinct from keyed REST. Initial4targets4/4 vsYahoo3/4; fixed12x2 expansion
has3text-only rate limits underHTTP200/noisError. Probe missed stop boundary,
all48fixed cells retained and entire expanded cohort NOT accepted. Frozen
exact target19/24 vs16/24; official Node translation adjudication21/24 kept
separately, not a posthoc pass. Seznam timeout1stop, Swiss zhCN/all1/4 each,
Yandex0/4.73search calls total, no model/Run/page/new prompts or runtime edits.
Normal services unchanged and temporary container removed. Only plausible future
candidate is bounded low-frequency anonymous MCP with correct limit/cooldown/
Yahoo fallback and existing Cloud authorization/cancellation, not default replacement.
See docs/CLOUD_KEYLESS_PROVIDER_02.md; no performance/SQL acceptance claim.

## 2026-10-17 — Exa anonymous MCP optional preparation, no normal activation

CLOUD-EXA-OPTIONAL-01 prepares an explicit native !exa engine/Compose overlay;
Yahoo remains sole default. Shared local-volume lease/cooldown recognizes HTTP,
RPC and HTTP200 textual limits, including initialize/notification429, honors
longer Retry-After and disables automatic recovery above24h. Native pooled
transport/cancellation reused; timeout/stop never starts late Yahoo fallback.
Known provider errors/cooldown use actual Yahoo within original deadline.
Offline native checks and37existing Cloud search/DNS/tool checks pass. Fixed4
real pairs normalize official targets Exa4/4 versusYahoo3/4; medians1612.701ms
versus889.394ms. No real limit in this cohort: injected regression proves limit
handling, not live quota acceptance. No stable latency/page/SQL benefit claimed;
no expansion/models/pages. Final image rebuilt after notification429 fix; startup,
exact source/default config/cancel patch checked without further search requests.
Normal API/Worker/Search unchanged; isolated container removed. Tool description,
high reasoning/transient_v2, authority/DNS/SSRF/Trench/globalproxy unchanged.
Local preparation only; operating bounds and commands docs/CLOUD_EXA_OPTIONAL.md.

## 2026-10-17 — Exa latency decomposition; paired optimization stopped on quota

CLOUD-EXA-LATENCY-01 isolates existing curl timing without production code edits.
Four baseline successes/official4of4: cold MCP initialize+notification770.293ms;
hot tools797–990ms, request-ready-to-first-byte748–920ms. All tools reuse native
connection/TLS; remote computation cannot be separated from RTT/service queue.
New956.032ms median versus previous1612.701ms is cohort variance, not a gain.
Freeze instant single-variable4pair test; firstfast request returns textual
HTTP200limit, persists900s cooldown and falls back Yahoo. Stop,0instant calls,
no retries/reset/rotation; one cooldown route check returnsYahoo with no new Exa
frames/state change. No unvalidated performance code applied or page/model run.
Normal service identity/runtime unchanged; existing offline control check passes.
Docs CLOUD_EXA_OPTIONAL.md records measured boundaries and uncompleted pairing.

## 2026-10-17 — Post-cooldown Exa pairing: instant rejected

CLOUD-EXA-PAIR-02 checked persisted deadline naturally expired, then executed
exact frozen4pairs/8searches, AB/BA/BA/AB, same pool/egress/state/arguments except
typefast/instant. Zero errors/limits/fallback; first-search officialtarget hit@1
and@5 both4/4 in each mode. Warm native tools mediansfast681.231ms versus
instant923.501ms: instant35.56percent slower, only1/4faster pairs. Upstream
self-reported searchTime medians339.05/617.40ms corroborate remote slow portion;
do not claim internal server-stage tracing. Cold669.113ms control excluded.
Gate fails: retain fast optional/Yahoo sole default; no speculative performance
source change, expanded samples, models or pages. Previous limited cohort retained,
no state reset/identity/egress rotation. Normal service snapshots identical,
owned candidate removed, one-shot follow-up deleted. Details CLOUD_EXA_OPTIONAL.md.

## 2026-10-17 — Remove redundant MCP initialization after rate limit

CLOUD-EXA-COLD-01 traces historical669.113ms cold controls:205.840ms transport
ready,258.721ms initialize response,204.552ms initialized notification. True cold
lifecycle still mandatory. Minimal response guard preserves already initialized
provider metadata only on RateLimit; lease/cooldown still gates every request,
non-rate/404 errors invalidate and cold/partial handshake behavior unchanged.
Native offline regression reproduced old session loss, then passes cooldown
zero-frame/expiry-no-reinitialize/404/cold2frames and existing controls.37Cloud
search/DNS/tool checks andRuff/format pass. Optional image built/startup checked
with networknone; no new Exa/model/page requests or normal service activation.
Potential recovery saving is two control requests/~463ms from historical timing,
not a measured real recovery latency win; reconnect/TLS and true process cold
remain. Actual provider state and normal services unchanged; no Trench/security/
high/v2/default changes. See CLOUD_EXA_OPTIONAL.md for scope and acceptance limits.

Real-recovery follow-up: original Exa processes were cleaned up and initialized
metadata was memory-only, so no original session is available for a true natural
rate-limit recovery pair. Zero new Exa/model requests; no quota fishing, state
reset or provider/default activation. Real recovery benefit remains unaccepted.
Future natural business-limit episodes must retain the process until recovery
observation ends; comparable baseline required before claiming paired gains.

## 2026-10-17 — Normal Search optional Exa activated; natural recovery observation

CLOUD-EXA-LIVE-01 follows explicit user authorization: normal Compose registers
Exa disabled/explicit!exa, Yahoo sole default, fast unchanged. Worker tool argument
description advertises optional supplement/fallback without forced routing.
Search real control bytes migrated into unchanged cache volume; no reset/egress
rotation. Native numeric RPC/PID/control logs support natural recovery without
query/header logging or extraSQL. Offline controls/privacy +37Cloud checks pass.
Normal Worker exact-image derivative updates only tool file, preserves env/mount/
command/security;0activeleases before update, API unchanged. Both services healthy.
Two Worker nativeHTTPS no-model queries: defaultYahoo0Exaframes; explicitExa3
frames/officialRedisGAfirst; no error/limit/fallback. Functional only, no latency
gain or autonomous-model/page claim. Keep normalSearch process. Read-only heartbeat
exa watches natural limits; no request until real eligible event, at mostone
post-cooldown recovery observation/probe then stop; no quota fishing/retry/reset.
Real paired recovery savings still pending. Details CLOUD_EXA_OPTIONAL.md.


## 2026-10-17 — CLOUD-RESEARCH-WEB-01 authorized search delegation

Cloud durable researchers can receive `research_web/domain-allowlist` only when
the parent durable tool/network profiles already allow the configured HTTPS search
endpoint. Child policy stays read_only and depth1; only web.search is added, no
fetch/commands/redelegation, and search auto_fetch remains denied. Missing/denied
parent permission retains research/none. Existing binding narrowing and fresh
authority/DNS/SSRF/cancellation remain on the normal path; local synchronous
researcher and Yahoo-default/Exa-fast/cooldown/fallback are unchanged. ADR-025
records this explicit extension of the former fixed-none rule.

No-model safety regression202passed including actual isolated PostgreSQL16
admission/projection/event replay, both Web tool chains, authority, DNS/SSRF and
cancellation; catalog/transport4passed; Ruff/diffcheck and source-resolved strict
mypy7files green. v104 is additive; no production migration or Worker update, no
external search/model/page requests, no new performance claim. This slice is
locally integrated only; activation must apply v104 before a new Worker image.


### CLOUD-RESEARCH-WEB-01 local service activation (2026-10-17)

The previously pending rollout is now complete: schema104 applied first; normal
Worker uses the exact prior image plus7changed files. API received only the3
profile/catalog compatibility files required to deserialize new child Tasks and
restart with schema104. Both healthy; effective env/mounts/command preserved.
Original Search container/start/image/PID1230/cooldown bytes and initialized MCP
process retained, with0newExa frames. Yahoo default/optional fast/fallback unchanged.

Deployed no-model acceptance recovered durable state and admitted/replayed6
synthetic narrow-authority cases in temporary schema+namespace on same database;
allow/deny behavior and read-only/no nested delegation verified. Deployed API read
and serializer6cases passed. Model events0/search requests0; owned temporary
schemas removed. This proves deployed composition/storage, not signed Host HTTP
or real-model business E2E or a new performance improvement. No Trench/globalproxy
changes, remote push or remote deployment.


### CLOUD-RESEARCH-WEB-01 actual page observation (2026-10-18)

One user-authorized normal-page research/high/transient_v2 sample completed.
Executor chose direct parent tools, no agent.research or Child links; actual
researcher-business search remains unverified despite no-model deployment proof.
10executor model rounds and24successful tools (search5/fetch7/artifactread12).
First plan text5.002s is progress, not answer. First actual answer Reactcommit
83.336s; finalcommit83.824s; page ready84.614s from click. Different multi-topic
workload, no paired speedup claim.0limits and0newExaRPC; defaultYahoo/fast/Search
PID1230/session/cooldown retained. No forced delegate/engine, extra samples,
product/Trench/config/service changes. Private page evidence retained.


## 2026-10-18 — CLOUD-ARTIFACT-LOCATE-01: bounded keyword reads implemented; page speedup unproven

Implemented optional literal query on the authorized immutable Artifact reader,
accurate model-visible snapshot ranges in a separate output_coverage observation,
and skipping unrelated DeferredRuntime preparation for Artifact reads. Existing
durable research tool description now states parent-authorized search and actual
read-only/depth1 restrictions. No system prompt/routing/Trench/engine change.
Three saved original snapshots pass exact-offset checks; focused64passed/2DB skips,
additional observation/recovery/harness46passed/2baseline-known parallel-safe
assertions (baseline gateway reproduced; no unrelated repair), Ruff/mypy6files pass.
Worker only updated from exact live image with6source copies, original effective
configuration retained; API and original Search/MCP/PID/control unchanged/healthy.
Live no-model original snapshot succeeds, foreign session denied,0sandbox/model/search.

One frozen original-question B on normal logged-in page (research/Flash/high,
transient_v2; no forced delegation/provider) completed: first real answer React
138.177s vsA83.336s, whole page139.482s vs84.614s;14vs10models,
37vs24tools (search6vs5/fetch11vs7/Artifact20vs12), all successful.
Runtime provisioning0vs1, but13keyword reads include4no-matches; directory
matches and fallback offset scans did not reduce read volume (86,500vs87,600chars).
Last input72,397vs56,708tokens; model intervals107.668vs56.125s, final
model43.496vs21.243s; inter-round26.843vs23.117s, startup3.090vs3.017s.
No researcher calls/children, no limits or new Exa frames. Yahoo sole default,
Exa optional fast/cooldown/fallback unchanged. Browser observer removed; result kept open.

Performance acceptance FAILED for this single historical A/oneB observation;
no stable benefit or causal slowdown percentage claim, no extra model sample.
Implementation is available locally, but do not call the overall latency goal done.
Next bounded question is why first literal matches hit directories and why misses
cause large fallback reads/source expansion; researcher business path remains unproven.
Evidence: .artifacts/cloud-artifact-locate-01/{snapshot-check.json,live/after.json,
live/probe.json,page/summary.json,page/run.json,page/browser-timing.json}.
No full-suite gate, push, remote deployment or extra quota probe claimed.


## 2026-10-18 — CLOUD-ARTIFACT-EXCERPTS-01: bounded multi-hit/candidate reads

One production file now returns up to4 non-overlapping short Artifact excerpts:
literal text≤2048chars, fenced metadata/code≤512, word candidates≤1024;
warning/separators share max_characters total. Exact original Unicode ranges
exclude labels/gaps. Literal miss candidates remain explicitly unverified
(literal_match=false/candidate_only=true); bounded word overlap≤16terms,
no synonym/semantic inference or external fallback. Offset-only reads unchanged;
authorization, immutable snapshot/digest, cancellation and no-sandbox preserved.
73focused tests passed/2DB environment skips; Ruff/strict mypy passed.
Saved original SQLite directory/body, Redis metadata/body/code, omitted-word
candidates, beta absence, Unicode/cursor/budgets/permission/cancel passed.
Worker updated via exact live-image derivative1sourcefile, effective configuration
retained. Deployed old-snapshot read/foreign-session denial passed with0sandbox.
API untouched; original Search container/start/PID1230/MCP/control bytes retained.

Exactly one normal-page original-question C: conv_1792256535989_31d585,
research/Flash/high/transient_v2, all7executor responses high/thinking enabled/auto.
First actual answer receipt58.709s/Reactcommit58.788s, wholepage59.620s;
7models/17successful tools (4search/6fetch/7read),0researcher/children/sandbox.
Five literal queries and2offset reads,24,000source characters; last input32,735tokens.
Actual SQLite4000-budget query exposes directory and body together; Redis durability
query exposes metadata+body. Term-candidate fallback did not occur in this page,
so its coverage remains offline only. Agent independently chose different Redis
queries/pages; no forced engine/delegation or extra system prompt/Trench change.
Against B:138.177s firstanswer/139.482s page/14models/37tools/20reads;
against A:83.336s/84.614s/10models/24tools/12reads. One sample with changing
source choices supports observed improvement, not stable/causal speedup certification.
Model intervals41.197s/final19.460s/inter-round14.391s/startup2.426s.
Some PG offset rereads remain; no full semantic answer-quality or researcher E2E claim.
No limits/newExaRPCs, Yahoo default/fast/cooldown/fallback unchanged. Temporary
browser observer removed; final result kept open. No further model sample/quota probe.
Evidence .artifacts/cloud-artifact-excerpts-01/{snapshot-check.json,regression.log,
live/after.json,live/probe.json,page/summary.json,page/browser-timing.json}.
Source integration is local to cloud-agent-trench; no push or remote deployment.

Correction to prior source diagnosis:95k was the identical A/B Vector sets guide,
not an additional Redis release page. The relevant15,111char release page had
Vector set [preview] at7799 inside the omitted initial5976:9134 interval.


## 2026-10-18 — CLOUD-SEARXNG-CONFIG-01 normal configuration installed

Primary-doc/maintainer research plus8 frozen Yahoo zh-CN/all native queries:
4/4success each, exact official target hit@5 both3/4; median1404.069/1149.376ms.
Redis same first3sources and missing expected What's-new in both; no recall/stable
latency improvement claim. Current-environment recommendation keeps Yahoo only
default/Exa optional fast, all-language neutral default, no autocomplete/favicon,
max_page1/safe1,5s/6s timeouts/pool20/HTTP2;429cooldown1h/403-CAPTCHA24h.
One mounted/native settings authority replaces unused build-time configuration copy;
normal startup image cloud-config-01 and compatibility overlay agree.
Network=none config/cookie and existing Exa regression passed, transport/provider
sources byte-equal original. Only Search replaced after zero active leases;
env except settings path, mounts/cache volumes/security/command preserved.
Runtime config digest matches host, healthy. API/Worker ID/image/start/env unchanged.
Two default Worker HTTPS/native smoke calls PG/SQLite succeeded with official
first results1.869s/1.190s.10real Yahoo calls total,0models/Exa/limits; no page or SQL claim.
Original Search/MCP memory process ended at2026-10-18 01:19:16 Shanghai for this
explicit installation. Original process had0natural limits and no recovery proof;
control file/cache retained, no resurrection/probe. Deleted exa heartbeat per its
stop condition. No Trench/globalproxy/auth/DNS/SSRF/cancellation changes.
Runbook docs/CLOUD_SEARXNG_CONFIG.md; private .artifacts/cloud-searxng-config-01/.
Local integration only, no push/remote deployment.

Follow-up: final Git integration exposed macOS Docker single-file bind inode
invalidation (running in-memory service remained healthy, new settings reads failed).
Moved sole source to docker/web-search/config/settings.yml; read-only config/ directory
mount excludes secrets/, avoids ordinary file atomic-replacement invalidation.
Offline checks updated for new path; final activation follows local integration.
Preserve cache/control/env/security and API/Worker; no additional search/model query.

Final directory-mount receipt: activated after Git integration, same-content atomic
replacement of host YAML stays readable inside container; current digest matches.
One final default Worker PG smoke1.753s/official first, no error/fallback; total11
Yahoo requests including original8comparison and3functional checks,0models/Exa.
Final transport/provider sources match original; API/Worker unchanged, all healthy;
control/cache preserved. Directory contains configuration only, not secrets.
Evidence directory-live-smoke.json/atomic-replace.json/final-seal.log.


### CLOUD-SEARXNG-PAGE-01 — 2026-10-18
One original-question real page D completed with current SearXNG config; high/Flash/research/transient_v2 and autonomous tools retained. First answer101.860s vs historical C58.788s (+73.27%); whole102.134 vs59.620s;9models/24tools (5search12fetch7read) vs7/17 (4/6/7). All successful, no limit/provider retry/Exa/researcher child. Added source/version verification and final high-thinking dominate extra time; no demonstrated page benefit or causal/stable regression claim. C SQL not captured; D shared117.271s database window69,940 top-level+11,271 nested includes background/observers, not per-run SQL or reduction. Existing counters only/no reset/config/restart/source changes; all service identities/env/images unchanged healthy, Exa state unchanged. Details docs/CLOUD_SEARXNG_CONFIG.md; private .artifacts/cloud-searxng-page-01/. No favorable rerun, push or remote deployment.


### CLOUD-SNAPSHOT-CONTEXT-01 — 2026-10-18
Implemented request-local exact Artifact range references through existing compaction hook; durable evidence/messages/IDs/provider reasoning unchanged, inline/reference/receipt coverage explicit, candidates unverified, changed/malformed source falls back. No prompt/tool/engine/security/Trench changes. Saved C/D no-model snapshots show net observation chars -6.31%/-6.97%; focused safety checks and isolated-image verification before one authorized page E. Separate managed worktree preserves unrelated main-directory media/settings changes.


CLOUD-SNAPSHOT-CONTEXT-01 closeout:31focused passes/Ruff/strict mypy; isolated-image and deployed no-model saved-D exact checks pass (-6.97% tool observation chars). Worker only exact2-file derivative updated, Search/API/env/security/cache state preserved. One original-question pageE first72.808s/whole73.713s/6models/18tools vsD101.860/102.134/9/24; high/thinking/v2/auto retained, no limit/retry/Exa/child. E actual context compaction2receipts saves1,250chars (0.95%); quality caveat: Redis8.8 Array omitted despite available unchanged fetch evidence. Thus same-coverage performance acceptance NOT passed; no stable/causal28.52% claim or favorable rerun. Shared SQL windows un-attributable, no SQL reduction claim. Initial image-reference build failure occurred before runtime change and was corrected using verified local base tag. Implementation done; performance/coverage boundary documented in docs/CLOUD_SNAPSHOT_CONTEXT.md. Unrelated dirty media/settings/chart work preserved; local-only integration.


### CLOUD-VERSION-SCOPE-01 — 2026-10-18
Added bounded requested/checked-source-version/unresolved completion assessment in core; partial source scope cannot be marked complete. No forced search/tool/engine/model repair or prompt changes; final body qualification respects JSON/code/length. Exact-source scope correspondence is not semantic correctness certification.64focused tests and saved D/E no-model checks pass; strict event payload compatible extension, moved existing delivery builder to keep final_completion below500lines. Preparing exact4-core-file Worker derivative and one original-question pageF; Search/API/Trench unchanged. Separate worktree protects unrelated dirty settings/media work.


CLOUD-VERSION-SCOPE-01 closeout: implemented and locally activated requested/checked-source/unresolved scope contract.64core+9API unique focused checks pass; Ruff/strict core mypy and saved-frame actual consumer roundtrip pass. Unique original pageF committed partial (PG18/Redis8 requested;18/8.0 checked;Redis8 unresolved), page scope note recovered on original Run with10models/17tools(3search9fetch5read), high/thinking/auto/v2, no retries/errors/limits. Old API rejected new shared event field; saved changed-suffix replacement reproduced stream_replacement_gap in unchanged consumer. Exact API derivative updates shared event schema and one bounded clear frame before unchanged authoritative body. No Trench source change/model rerun. API/Worker healthy and env/security retained; Search process/image/start/cache/cooldown unchanged. Normal page latency pairing invalid due compatibility recovery/reload and overwritten bounded timings; SQL window un-attributable, no speedup/reduction claim. Redis8.8 fact omission remains a semantic evidence limitation; partial is not semantic certification. Local integration only, no push/remote deploy; unrelated dirty work preserved. See docs/CLOUD_VERSION_SCOPE.md and private .artifacts/cloud-version-scope-01/.

### CLOUD-VERSION-STATE-01 — 2026-10-18
Existing acceptance context now carries bounded requested/observed-source/unresolved version scope state, refreshed before budgeting/request; no extra feedback/instruction paragraphs/tool/model calls. Shared extractor reused; final delivery still citation-bound and non-semantic.55focused checks/Ruff/strict mypy pass; saved C/D/F and isolated exact3file Worker no-model checks pass (state433–447chars,0extra messages/evidence unchanged). Local Worker updated with exact env/mount/security; API/Search process/cooldown preserved. One original-question pageG in progress, high/thinking/v2/autonomous/Yahoo/fast retained, stop on rate limit. No Trench changes/push/remote deploy. Target cloud-agent-trench currently has unrelated staged settings/media work including shared docs; do not disturb it for integration.

CLOUD-VERSION-STATE-01 closeout: source f171e9ca,55focused checks/Ruff/strict3file mypy and saved C/D/F + isolated-image checks passed. Worker exact3file derivative healthy; API/Search IDs/start/images/env/control unchanged, no Trench changes. One original pageG first65.835s/whole66.426s/8models/19tools(4search9fetch6read), high/thinking/auto/v2, all successful/no retry/limit. HistoricalE72.808/73.713/6/18 comparison is observational only (-9.58%/-9.89%); F timing invalid, no attributable SQL/stable gain claim. G still omits8.8/Array and commits partial; state visibility proven via real request-entry no-model capture, improved recall NOT demonstrated, no favorable rerun. Timer removed, screenshot retained. Code-only ff integration blocked by pre-existing target MERGE_HEAD (not our merge); no abort/stash or change to unrelated patches (byte-identical verification). Task branch keeps source/docs; live local Worker enabled, no push/remote deploy.

### CLOUD-SEARCH-CANDIDATES-01 — 2026-10-18
Same-response validated candidates retained up to20/20,000content chars via existing output Artifact; inline requested<=5 unchanged/order preserved, no new query/probe/engine/prompt/forced read. Accurate prefix/sparse ranges and checksums; raw headers excluded, internal payload removed, no-projector fallback does not advertise unavailable extras.28candidate/projection/snapshot +9gateway +55cancellation checks pass (92unique), Ruff/strict5file mypy pass. Saved Yahoo Redis rank7 official release snippet contains8.10/8.8 absent inline; same-session Artifact query recovers it, cross-session blocked,0upstream queries. Candidate value is not fact verification. Exact5file Worker derivative passed offline saved-response test then locally activated; API/Search/env/control preserved. One authorized original-question pageH underway, high/thinking/v2/Yahoo/fast retained, stop on limit/no replacement. No Trench/global proxy/engine changes or push/remote deploy.

CLOUD-SEARCH-CANDIDATES-01 closeout:92unique focused checks/Ruff/strict5file mypy passed; saved actual Yahoo rank7 official8.10/8.8 snippet recovered via existing authorized Artifact (offline,0upstream queries), no semantic fact certification. Exact5file Worker derivative activated, API/Search/control preserved. Unique pageH first71.561s/whole73.611s/10models/20tools(4search9fetch7read), high/thinking/auto/v2, all tools success/no retries/errors/limits.4searches each inline5/retained7; agent chose0search Artifact reads and current Redis extras contain no8.8. Still partial/narrow8.0; realized recall/performance gain NOT demonstrated (vsG65.835/66.426/8/19, +8.70%/+10.82% time, no causal attribution/SQL claim). No favorable rerun. Timer removed/screenshot saved. Main settings/media merge has since completed; task branch merged its tracked changes without conflicts, preserving live options; only local integration/no push/remote deploy. Post-page image cleanup only removes EOF blank line; no functional change or extra model/search.

CLOUD-SEARCH-CANDIDATES-01 final integration: local cloud-agent-trench ff through f450665c, previous version-state integration blocker resolved; user dirty patches byte-identical. Final exact5file Worker/image/env healthy, API/Search identity/start/image/restarts/env/control unchanged. No push/remote deploy, no extra model/search sample.


### CLOUD-TURN-CLOSE-01 — 2026-10-18
Cloud finalization reuses already-admitted immutable Turn identity instead of preparing accumulated model inputs again. Keeps1MiB/2048limits and Recorder fresh control/cancel/lease/sequence checks; unbound/foreign views fail closed, local behavior unchanged.33focused no-model regressions/Ruff/four-file mypy and offline exact-image checks pass. Only Worker updated with exact configuration, healthy; API/Search process/env/control unchanged. Original db605223 second Turn recovered through fenced revision444->445 canonical transaction, now awaiting_turn; answer8,818chars/hash unchanged, models20/20 and tools62 unchanged. Idempotence check passes. Original page both completed, no Pause, no Trench repair/code/model/search. Details docs/CLOUD_TURN_CLOSE.md; local integration cloud-agent-trench only, no push/remote deploy.


### CLOUD-CLOSE-RECOVERY-02 — 2026-10-18
Cloud lifecycle-only recovery now precedes execution inputs/progress/model/runtime setup. Heals committed-complete answer missing Turn close and Turn close missing Session terminal; partial/blocked/unmet suspend without successful recovery or automatic model rerun. Keeps1MiB/2048caps and fresh control/lease/fence/revision/idempotency checks. Same-Attempt complete answer survives cleanup/derived failure with diagnostics retained.82unique focused no-model checks/Ruff/seven-source mypy/exact-image offline pass. Local Worker exact seven-file derivative healthy with unchanged env/mount/security; API/Search identities/start/images/restarts/env and MCP control bytes unchanged. Model/tool counters unchanged across update; task-only native test PG removed, shared scratch left untouched. No migration/model/search/Trench/global proxy change or push/remote deploy. Details docs/CLOUD_TURN_CLOSE.md; local integration target cloud-agent-trench.

### CLOUD-CLOSE-GUARD-03 — 2026-10-18
Unified old preflight/early recovery Turn/Run/Attempt/revision guards; recovery CAS defers through retryable lease-release path without whole-execution retry or setup-failure outcome.1MiB/2048caps, fresh lease/control/cancel and partial assessment preserved.80focused no-model checks, Ruff/three-source mypy/exact-image offline pass; local Worker-only activation healthy/exact source/config, API/Search/MCP preserved and model/tool counters unchanged. No duplicate-read optimization or Trench/model/search change. See docs/CLOUD_TURN_CLOSE.md.


### CLOUD-CLIENT-RECOVERY-04 — 2026-10-18
Client Effect freezes/restores shared verification and dedupe state before eager
scheduled persistence and normal waiting; fenced effect-identity consumption,
legacy uncertainty suspension and conflict checks prevent receipt replay. Shared
error classification retains whitelisted state. Native provider timeout/invalid
response no longer dispatches ordinary fallback; pre-dispatch unsupported-only
fallback remains.109 focused offline checks/Ruff/14-source Mypy pass; Worker-only
exact-image activation completed: normalWorker c5792e55 healthy/restarts0, source
24eebf68 integrated locally. Image/live offline checks and14source hashes pass;
API/Search/MCP unchanged, protected partial Turns all hashes unchanged, update
window model/tool counts unchanged. Configuration equal apart from mount array
ordering (exact old-hash reconstruction proven). Coordinated stageK release first;
new baseline handed back. No model/search/Trench/Desktop changes or push/deploy.


## 2026-10-19 TRN-COMPOSER-SUGGESTIONS-01

Shared React AgentComposer now renders recommendation buttons before textarea;
no new API/style/dependency or callback change. Existing SDK test covers DOM order
and busy hiding; red against prior source,5focused checks/build/typecheck pass.
Trench consumes rebuilt matching React tarball, with only local integrity changed;
14focused/complete makecheck (243API/80cleaning/515frontend) pass. Original browser
conversation confirms recommendations above text input with matching accessible
order. Desktop screenshot in Trench .artifacts/trn-composer-suggestions-01/.
No actual model submission/service restart/push/remote deployment. Task Review,
focused local delivery; unrelated primary AGENTS.md/Trench dirty work preserved.

### 2026-10-19 CLOUD-PLUGIN-PLAN-01 — proposal only

Current-source Cloud Plugin adoption plan saved to
docs/superpowers/plans/2026-10-19-cloud-plugin-adoption.md. Four proposed slices:
package integrity, scoped durable installation, existing Turn/Worker integration,
then native acceptance and separately gated researcher inheritance. Reuses current
Skill/MCP authority and snapshots; no implicit grants or component enablement.
Default off; immutable object receipts retained without automatic Plugin GC.
316-line source-pointer/scope checks and independent review/recheck passed.
No runtime code, migration, service activation, model/search or Trench change.

CLOUD-PLUGIN-CON-01 implementation authorized and claimed 2026-10-19 on isolated
codex/cloud-plugin-con-01. Legacy Plugin baseline7passed using explicit task
source paths and existing interpreter. New-worktree make sync hit external PyPI
build-dependency timeout; dependency/lock files unchanged. No service activation.

CLOUD-PLUGIN-CON-01 complete: source8912c63b adds bounded v0.2/legacy normalization,
immutable byte snapshots and actual package hashes; fixes legacy path escapes.
45focused offline tests (0skips), Ruff/four-source Mypy pass; independent spec
then quality review approved. No installed plugin/runtime capability yet.


CLOUD-PLUGIN-STORE-01 complete: source3ca58a16/22293850 adds additive migration105,
scoped immutable installation/CAS/idempotency, ready exact component binding,
approved fixed-object publication and default-off management API.19newfocused
checks pass using disposable PostgreSQL; impacted215passed and one transient
connection-timeout fixture passed targeted rerun. Ruff/Mypy/file bounds pass;
independent spec then quality reviews approved. Normal service/DB/config remain
untouched. Automatic composition and Turn/Worker execution are the next stage.

CLOUD-PLUGIN-RUN-01 complete: source4b2f6998/97382630 plus01c2a954/e8e201cc
connects explicit selection, atomic Turn provenance and Worker live source checks.
Legacy snapshots/direct paths retained; setup and per-call authority loss suspend
without another model or Turn closure. Independent spec/quality approved; fresh
160focused +4setup seam tests, Ruff46files/Mypy34sources pass. Still default-off;
normal services/DB/config unchanged. Native cross-process acceptance follows.


CLOUD-PLUGIN-ACCEPT-01 claimed after RUN local integration. Final source stage
proves real isolated PG/versioned-object recovery and bounded native overhead;
child Plugin inheritance remains closed. Normal activation/model gates separate.


CLOUD-PLUGIN-ACCEPT-01 complete: source9b6eca55 proves real isolated PG/versioned
MinIO, nonempty Skill content, fixed-object recovery in independent process after
bundle deletion, native Worker tools/durable approval and closed child isolation.
78focusedpass/2optionalskip; whole test9885pass/2951skip/1knownbaselineevalfailure.
Globalfiles/Ruff/Mypy1315source and progress checks pass. Eval30 terminal/metrics
match pre-Plugin1d160735 exactly (24/30); release gate remains nongreen, no unrelated
fixture repair. Independent spec/quality approved. NormalAPI/Worker/Search ids,
images/start/restarts/envhashes match. Only task PG/MinIO containers/anonymous
volumes cleaned. Source locally integrated, default off; no normal migration,
service activation, real model/search/page calls or push/deploy. Runbook:
docs/CLOUD_PLUGINS.md. Separate activation/model gates remain unexecuted.


CLOUD-PLUGIN-LIVE-01 authorized: local normal-service v105 activation with a single
Skill-only digest/scoped pilot; no real models/search. Preflight104/no effective
leases; old ready/running projections are not to be repaired as part of rollout.

CLOUD-PLUGIN-LIVE-01 complete: v105 exact checksums/current schema; same-source
API/legacyAPI/Worker updated with preserved settings/resources, including shm.
API/Worker healthy; legacy internalhealth ok. One approved Skill-only digest and
isolated scoped installation; shared service flags global, existing heads unchanged.
Real signed HTTP CRUD/isolation plus native Worker PG/S3 fixed snapshot/Skill reads,
empty selection/disable denial/newrevision pass. Bootstrap-only testTask cancelled,
no accepted execution Run; no model/search requests or model/tool event increments.
Search fullID/start/PIDs/env/cooldown and2protectedpartialTurn hashes preserved.
MCP Worker remains off. Local activation gate passed; acceptedRun/model/page E2E
remains separate. No remote push/deploy. Runbook section7; no source/test expansion.

CLOUD-PLUGIN-E2E-01 in progress: one signedv2/high Run accepted with fixedPluginr4;
test workspace /workspaces was outside actual readonlyWorker writablemount, causing
gateway setup failure before0model/0tool. Failed sample retained. Correct isolated
mounted path passes native no-model gateway construction; replacement prepared,
then explicitreplacement authorized. Replacement made1realFlash/high round,
autonomousskills.list/files.list2started/0completed; v2commentary3.0009s/error4.3769s.
Dedicatedmount quota rejects isolatedsubdir; base10GiBmount passes. Skill reads
also unnecessarily triggerDeferredRuntime in currentgateway. No finalanswer/E2E
pass; no thirdRun/resume, security weakening or source/service/config changes.
Search/MCP process/cooldown and originalpartialTurns/oldheads preserved. Nextgate
requires nativeSkillruntime audit plus compliant isolation before another sample.

CLOUD-SKILL-RUNTIME-01 authorized/implemented: exactnativeSkillread/list share
existingArtifactruntime-free dispatch, existingcatalog/Plugin/cancel boundaries
intact; filesystem tools still provision.78focused/Ruff/Mypy1315/files pass,
read-only code/ops review noCritical/Important. True one-shotWorkerPG/S3 tools
andgVisor bidirectionalmarker prove nestedchildmount/10527662080Bcap within10GiB,
no quota weakening or exclusivecapacityclaim.0model/search/MCP; no-RunTaskclosed.
NormalWorker update and new once-onlyhigh/v2 Run are next; priorfailuresretained.


CLOUD-SKILL-RUNTIME-01 completed locally: onlynormalWorker updated to b72e1210
with dedicated ownedchildbind, quotaenabled/10527662080<=10737418240. Exactenvvalues,
security/resources preserved; API/Search fullidentity/start/PIDs/cooldown unchanged.
OnecanonicalnormalRun eb4e2171-e798-46f8-80e0-e9d86aab8a5e succeeds: Flashhigh/v2/
autotools,4modelrounds,4successful Skill/workspacetools, actualSKILL.md andmarker
reference read; answercommitted/turncompleted/sessioncompleted, coldreplayidentical.
Temporarycommentary3.158s, finaldraft13.5771s, terminal17.3511s; thisisfunctional
acceptance, not speeduppairing orTrenchpage. NativeSkill3calls0provision proof;
realRunfiles.list legitimatelyprovisionsonce. No extra models onrecovery, nosearch/
MCP, old12heads/2partialTurnhashes unchanged,0leases/pending. Priorfailedsamples
retained. No remote push/deploy. Currentrestarthelper andproofs inrunbooksection9.

CLOUD-PLUGIN-UI-01 completed locally: Trench Settings sidebar now has independent
Plugin immediately below Tools & connections, with real approved marketplace and
installed management. Browsing reuses hash-validated approved packages through a
bounded authenticated read catalog; no publication, automatic binding or grants.
Actual logged-in page displays the approved pilot and exact install prefill/current
Skill candidates; no live install/toggle or response interception. Zebra19 tests,
Ruff/Mypy1315, Trench20 proxy tests, focused frontend regressions and build pass.
Only API/legacy API updated preserving configuration; Worker/Search/TLS/MCP process
unchanged. Final read-only protection equals baseline: zero model/tool increments,
12 heads and two original partial Turns unchanged, zero leases/pending. No models,
searches, push or remote deploy. Runbook section10 records current restart helper
and proof; this is management UI acceptance, not another real Run acceptance.

CLOUD-PLUGIN-UI-02 complete locally: both Plugin views use full-width row lists;
fingerprints/internal IDs hidden. Market Install submits digest only; composed
installer reuses verified package bytes, Skill publication/install and exact scoped
MCP slots. No user binding form; explicit API compatibility, idempotency/CAS and
revocation checks retained.22focused Python/Ruff/Mypy1316/file gate, scoped frontend
regressions/type/lint/final build pass. Real isolated user clicked install once,
enabled r2, disabled r3; cold refresh after all three and API cleanup kept state.
Native PG confirmed Skill manifest and MCP connection/catalog pins. Synthetic MCP
fixture only, no remote MCP execution. Temporary fixture removed from market;
normal account unmodified. Only API layers changed; final env restored, Worker/
Search/TLS and MCP process unchanged.0model/search, old12heads/2partial Turns intact,
only3isolated heads added,0leases/pending. No push/deploy; runbook section11.


## 2026-10-19 - CLOUD-PLUGIN-NORMAL-01

Ordinary Runs now carry enabled scoped Plugin capabilities through the frozen Task
Skill ceiling and typed outer AG-UI selection; model tool choice remains autonomous.
Managed origins survive replay/rebind/version updates and cannot bypass disablement;
readonly ownership checks remain when execution is off. Skill/MCP readiness is
truthful, counts unique MCP connections, and every inventory GET/page uses a fresh
single-use Grant. Existing secured MCP runtime is now composed locally.
239Zebra tests/fullMypy1317 and Trench106pass/13existingPG-skips; finite independent
spec/quality review passed. Actual signed HTTP/Host selection/API serialization and
native Worker savedSkill/snapshot/catalog proof passed with zero new Run/model/search
or remoteMCP. Local API/legacy/Worker updated; Search/TLS/Exa/MCP process preserved.
15heads,2originalpartialTurns,125snapshots and all model/tool counters unchanged;
0leases/pending. Thin Host protocol adaptation only, no Trench product/UI logic.
Local source integration only, no push/remote deployment. See docs/CLOUD_PLUGINS.md12.


## 2026-10-20 - CLOUD-PLUGIN-PAGE-01

One ordinary page new Run completed at high/v2: actual frozen1Plugin/1Skill/1MCP,
provider Skill/MCP context and real Skill read confirmed.5model rounds/7tools
(6success/1old-unselected-Skill failure),28.392s page send to Host completion.
MCP fetch catalog present but not called; no remote-execution/session-recovery claim.
Cold refresh retained answer and durable counters. Found hardcoded MCP management
catalog_verified=false plus inventory/current-selection mismatch; no source fix expanded.
Scoped test records disabled and temporary API-only allowlist restored. Worker/Search/
TLS/originalMCP untouched; old15heads/2partial hashes/SearchPIDs/cooldown exact,
only2heads/1snapshot added,0leases/pending. No search/retry/push/remote deployment.
See docs/CLOUD_PLUGINS.md13 and .artifacts/cloud-plugin-page-01/acceptance.safe.json.


## 2026-10-20 - CLOUD-EXTENSION-INVENTORY-01

Fixed management inventory at the shared boundary: MCP reuses existing exact
stored catalog validation including current-Turn digest; Skill installed state
is distinct from current-Turn readable names via frozen pins plus the actual
live prepared catalog. No selector/prompt/permission changes; revocation and
fresh scope/lease checks retained.158focusedpass/1existingskip,Ruff,Mypy1318,
filegate3218/0 pass. Offline same-base5file Worker layer only; idle update yielded
healthy9e809d7c44b6, exact original env/security/resources/mounts/network.
Real stored MCP shows verified/1tool/no-refresh advice; unselected/disabled Skills
show unavailable/no readname in operator readonly metadata inspection. No active
Run/lease fabricated. Protection before/after exactlyequal:17heads/126snapshots,
model/tool counters/2originalpartialhashes/SearchPID/cooldown,0leases/pending.
No model/search/MCPwire/API/Search restart/Trench change/push/remote deploy.
Details docs/CLOUD_EXTENSION_INVENTORY.md; local source integration only.
## 2026-10-20 - CLOUD-EXTENSION-ACCEPT-01

Skill/MCP/Plugin functional acceptance passed:116 focused no-model tests and one
authorized ordinary page Run high/v2/auto. Actual Plugin-mounted Skill main/ref
reads and existing real MCPfetch both execute successfully; truthful current-Turn
inventory confirmed. Run completed in46.162s Send-to-Host persistence,5model rounds,
7successful tools,0retries/searches; refresh restores the answer without new Run
events. MCP's two successful representations took17.943/4.194s; no performance
improvement claim. Test Skill/Plugin disabled again, originalAPIimage/env restored,
Worker/Search/TLS/MCP preserved, original2partialTurn hashes exact. No production
source/Trench change, push or remote deployment. Scope and evidence boundaries:
docs/CLOUD_EXTENSION_ACCEPTANCE.md.

## 2026-10-20 - CLOUD-MCP-PREPARE-TIMING-01

Selected Cloud MCP tools now skip unrelated deferred sandbox preparation by exact
composed name; workspace/non-Cloud/unknown routes retain original preparation.
Per-call numeric metadata separates live authorization,DNS/SSRF,connect/TLS,SSE,
initialize/notify/call and result waiting; redacted failure timing logs preserve
original exceptions.414focused checks pass/1environment skip,Ruff/fullMypy1319,
filegate3220/0. Offline same-filesystem image flattening resolves127layer ceiling;
Worker-only12694c55ae77 is healthy with original config. Actual-image/Worker offline
smoke confirms0Cloudprepare/1workspaceprepare/8fresh guards/8captured HTTP frames.
APIs/Search/TLS/MCP sessions and original partialRuns preserved;17heads/127snapshots/
model-tool counts unchanged,0leases/pending. No model/search/remoteMCP/newRun,
Trench/prompt/rounds/reuse change,push or remote deploy. Real-page speedup remains
unmeasured. See docs/CLOUD_MCP_PREPARE_TIMING.md.
