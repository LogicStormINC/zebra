# CA-P5-01 Runtime deployment gates

Design fixed before implementation,2026-10-28; implemented/Review; final make test/check passed. DDD: RuntimeGate owns namespace admission
mode/revision and immutable operator intents/receipts; Registry owns exact Release,
Task streams own execution history; Workers own compatibility observations. Storage
adapters perform short bounded transactions. API only authenticates/translates;
Worker composition reuses existing snapshot compatibility before any model/tool I/O.

New private approval is explicitly for an exclusive deployment namespace. Shared
multi-product namespaces are unsupported. Existing target.describe remains read-only
and not_checked. New contract does not convert identity/health into readiness.
No new Agent/business credentials; machine management credential remains server-side.

Commands assess/drain/open carry original UUID and expected gate revision, optional
exact candidate Release reference. Drain/open atomically CAS gate mode and append
original receipt. Repeated POST conflicts; unknown GET original only, missing receipt
is not non-commit proof. Current private approval and DB revision/revocation rechecked.
No auto resume, Task/Run mutation, lease cleanup, Controller claim or new dispatch.

Drain closes new session/user-input/run/resume/message admission in PostgreSQL with
shared/exclusive namespace gate serialization, including old writers. Existing tasks,
control callbacks, cancellation and completion remain possible. Exact already-stored
event replays remain idempotent. Trusted internal resume classification reuses the
existing Native computed replay header (approval/child/client-effect wakeups); it
does not admit a new Run or grant authority. New child bootstraps remain blocked. Existing accepted
work may finish; waiting/unknown work blocks convergence. Unreleased leases (even
expired), pending commands, projection lag and unsettled Effects are explicit blockers.

Assess freezes exact original candidate IDs/digests. Actual Worker maintenance reads
candidate and bounded current active Task snapshots and runs its existing compatibility
checks without model/tool execution. Existing read-only OCI/gVisor preflight runs
outside the source DB transaction; trusted-local is explicitly development-only,
not production isolation readiness. One background probe cannot block the execution
loop or queue probes behind a still-running one. DB-clock TTL and input digest fence stale results;
missing/corrupt/legacy/foreign/overflow inputs cannot become compatible. A qualified
Worker observation is not complete fleet/routing proof. Source facts can change after
observation; executor must recheck under its future dispatch boundary.

Native execution quiescence proves only the named database predicates under closed
admission. It does not prove all processes stopped, external effects settled, queue
transport drained, schema/image rollback compatibility or deployment permission.
`safeToStop=false` remains explicit; historical uncertain receipts are retained.
Full owned disposable deployment/activation and process shutdown acceptance remain P5
consumer/executor work, not this API or the existing health endpoint.

## 已实现的公开接口与权限

`GET/POST /management/v1/runtime-gates`，合同 `runtime-gates/1`，
[OpenAPI](contracts/runtime-gates-v1/openapi.json)、[语义与限制](contracts/runtime-gates-v1/contract.json)、
[固定摘要](contracts/runtime-gates-v1/digest.txt)。必须提供 `X-Runtime-Gate-Contract`，
以及现有 Deployment/Audience/Product/Environment/Trust-Revision 五个机器 scope header。
Bearer 格式 `rtgate_` +43个base64url字符；与 Agent access/refresh/identity_key、业务 IdP、
Broker/HostGrant/Controller 凭据分开。原始机器凭据保留在服务端/BFF，Native配置只保存SHA256。
不新增浏览器认证或修改现有三字段认证；管理前端保持mock。

POST严格JSON <=16KiB：`operation_id`、`action`、`expected_revision`，assess额外提供精确
`candidate`（Native definition/version/release UUID、release_revision、裸64位definition_digest、
带sha256前缀的bundle_digest）。不允许 caller-ready/Worker报告等声明。只有当前 Published
Release及其不可变Version/Bundle匹配才可登记assessment；不读取latest草稿。
`assess`登记独立意图而不推进准入revision；`drain/open`各推进一次，重复POST一律409。
未知结果只能GET原 `X-Runtime-Operation` UUID；404、超时、403或503都不是未提交证明。
GET无operation header查询当前门禁；有header返回 immutable original 与 current facts 分开。
旧actor/trust revision收据通过当前受权凭据读取，文件轮换必须同步显式DB approval CAS。

| 观察字段 | 能证明 | 不能证明 |
| --- | --- | --- |
| checks.database | Native全部已发schema identity/checksum匹配，可读取数据库 | 备份/恢复、迁移可逆或生产HA |
| checks.candidate | 当前精确Published及原始Bundle/Version匹配，源完整 | OCI镜像已部署、真实Eval重跑 |
| qualifiedWorkerObserved | 实际Worker现有snapshot guard检查精确候选和当前活动快照；有当前epoch/15秒DB TTL匹配报告 | 全部Worker覆盖、空闲容量、路由已固定或调度许可 |
| checks.runtimeEngine | 已复用只读OCI/gVisor capability preflight；trusted-local明确为local_development_only | 镜像已拉取、sandbox已创建、挂载/模型网络/真实任务通过 |
| admission=draining | 命名空间准入行与新事件写入共享/排他锁形成数据库栅栏 | 杀进程、取消旧Task、撤销已提交Effect |
| executionQuiescent | 当次canonical数据库观察中命名阻塞项均为0，且准入关闭 | 所有将来工作都不可能发生、模型/工具外部效果已结清 |

始终返回 `proofScope=canonical_database_observation`、fleetCoverage/processesStopped/
externalEffectsSettled=not_proven、safeToStop=false、activationAuthorized=false。
已受理工作、原收据恢复和可信旧Run续行仍可发生，所以当次quiescence不是永久停机证书。
Worker报告过期、重启/epoch轮换、源指纹变化、活动旧任务不兼容/缺少绑定、溢出或损坏均不放行。
当前支持的原生Bundle/Script Worker guard保持；Coverage或legacy无法由此guard证明时明确阻塞，
不改写其快照、旧哈希或Coverage证明。API没有Worker attestation上传入口。

## 排空、并发和恢复

新增schema115仅增加namespace gate、original operations、Worker observations及索引/触发器。
历史迁移checksum不变，不迁移Task/Run/Event/Effect/Receipt或Coverage。
Native既有epoch初始化建立默认open行；新管理配置/作用域绑定/权限必须显式初始化，启动不做新DDL、
不自动审批或排空。新scope固定整个独立namespace；已知跨产品approval/Bundle scope冲突时
拒绝新增assess/drain，GET原记录保持可读；当前受权open仍可释放旧栅栏。共享namespace不作为支持形态，
`namespace_exclusive`是离线运维的专用部署前置，不代替业务身份/成员关系。

数据库BEFORE INSERT栅栏位于既有computed replay header之后；覆盖旧版本写入者的新
session_created/user_message_received与业务run/resume/message。cancel/stop/suspend和原生已有
可信内部resume分类（approval/child/client-effect）仍按既有权限执行；原有幂等/冲突语义不变。
新child bootstrap也受限制；排空可能等待业务处置，不自动取消或重发。SQL55000使该写事务回滚，
但不能据此推断另一个已登记原操作/在途请求没有提交；仍用其拥有者合同原GET对账。

阻塞项包括所有非终态session（等待审批/输入/Effect、suspended均保留）、未释放租约（过期亦算）、
pending命令、未结清/uncertain/dead-letter Effect、投影落后和源/作用域不完整。计数最多33，
饱和计数不冒充全量总数。32活动session/2MiB canonical源限制、SQL/I/O期限和schema错误fail closed。
管理事务持当前approval/epoch与gate边界锁，使用repeatable-read；并发序列化/CAS冲突409，无自动重试。
引擎探测在DB锁外，Worker单个后台任务最多检查最新4个assessment；每operation最多16个报告，
仅过期观察缓存可回收，original及其actor/input digest/created_at永不自动删除。

保留总上限128个original，普通操作在127时停止登记，最后一位只给显式open；不能因日志容量
耗尽永久困住closed admission。容量不足429，无自动清空/篡改收据；后续需独立归档方案。
变更凭据必须同时具备read权限以支持原操作恢复。客户端未知结果不可自动POST/new UUID或重领Controller。
这些限制是资源/一致性边界，未证明生产吞吐、故障转移、RTO/RPO或HA。

## 运维接入与回退边界（仅说明，未执行生产操作）

1. 独立测试/受权环境先应用已发Native迁移至115并建立既有control-plane epoch。
2. 通过绝对路径0400/0600私有文件设置 `ZEBRA_RUNTIME_GATE_CONFIG`。字段见
   `RuntimeGateApproval`：schema_version、scope、audience、actor、namespace_exclusive=true、
   contract_digest、trust_revision、credential_sha256、expires_at、actions。
   scope.namespace_id必须是当前部署namespace，与该独立Runtime的execution catalog一致。
3. 显式运行 `uv run python -m zebra_agent_api.runtime_gates_admin --deployment-namespace NAME
   --expected-revision 0`；该工具仅审批及绑定已有schema，不部署、不迁移、不排空。
   approval与namespace绑定是两个有界步骤；中断/报错可能已完成第一步，先核对当前审批再决定，不能盲重试。
4. 具备当前read权限后先查base，持原UUID和expected_revision显式assess/drain/open；本片没有
   Go executor/激活接线，不能把Native机器凭据交给管理前端或业务SDK。

镜像回退不是数据库降级，也不是自动更换Task快照。旧Version要重新发布为可信当前Release后
才能用本合同评估；当前Release记录本身仍不代表容器已切换。schema115不由此提供向后降级，
旧binary的严格schema/Worker门禁可能拒绝新schema，必须单独证明兼容方案；不得删除已发迁移、
原记录或Coverage。实际进程停止/全fleet路由/queue transport drain、镜像与挂载、业务模型及
生产gVisor、兼容回退和独立Compose闭环仍为后续P5 consumer/executor验收；本片不关闭P5/S1。

## 验证入口

`uv run pytest tests/api/test_runtime_gate_management.py tests/agent_core/test_runtime_gate_domain.py
 tests/worker/test_runtime_gate_observer.py -q`：实际独占PG/机器scope/CAS、独立API进程原GET、
真实Worker predicate/后台背压、旧任务快照、过期租约、当前撤权、namespace冲突与保留open容量。
生产Registry事实由fixture直接建立，不声称重跑真实Eval或模型。cloud根装配另验，ASGI不等同TLS/Ingress验收。
[验证与来源记录](evidence/ca-p5-01/README.md)分别记录专项、全量make test/check及Go合同交接。
